-- A retryable failure requeued the run with no delay, so claim_next_run picked
-- it straight back up and all three attempts burned within seconds. The
-- transient condition the retries exist for had no time to clear. Give a
-- requeued run an earliest-retry time and have claiming respect it.

alter table public.runs add column retry_after timestamptz;

-- Attempt 1 waits 5s, attempt 2 waits 20s, and the wait is capped so a run can
-- never park itself for longer than an operator would wait to see it move.
create function worker.retry_backoff(p_attempt int) returns interval
language sql immutable set search_path = '' as $$
  select make_interval(secs => least(60, 5 * power(4, greatest(coalesce(p_attempt, 1), 1) - 1)))
$$;

-- The claim must skip a run that is waiting out its backoff. The expired-lease
-- sweep above it deliberately keeps requeueing without a delay: that run's
-- worker died, and a live worker should pick the work up promptly.
create or replace function worker.claim_next_run(p_worker_id text, p_aliases text[], p_lease_seconds int)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  expired public.runs;
  claimed public.runs;
  result jsonb;
begin
  if nullif(btrim(p_worker_id), '') is null or p_aliases is null
     or p_lease_seconds is null or p_lease_seconds < 1
     or p_lease_seconds > worker.max_lease_seconds() then raise exception 'PAYLOAD_INVALID'; end if;
  for expired in select r.* from public.runs r
    where r.status = 'running' and r.lease_expires_at <= clock_timestamp()
    order by r.id for update skip locked
  loop
    update public.runs set
      status = case when attempt < max_attempts then 'queued' else 'failed' end,
      error_code = 'LEASE_EXPIRED', error_message = 'Worker lease expired',
      finished_at = case when attempt < max_attempts then null else clock_timestamp() end,
      lease_owner = null, lease_expires_at = null where id = expired.id;
  end loop;
  select r.* into claimed from public.runs r
    join public.broker_profiles p on p.id = r.profile_id and p.user_id = r.user_id
    join public.broker_alias_owners o on o.alias = p.alias and o.user_id = p.user_id
    where r.status = 'queued' and p.alias = any(p_aliases)
      and (r.retry_after is null or r.retry_after <= clock_timestamp())
    order by r.requested_at, r.id for update of r skip locked limit 1;
  if not found then return null; end if;
  update public.runs set status = 'running', attempt = attempt + 1,
    lease_owner = p_worker_id, lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
    started_at = coalesce(started_at, clock_timestamp()), finished_at = null,
    error_code = null, error_message = null, retry_after = null
    where id = claimed.id returning * into claimed;
  select jsonb_build_object('run_id', claimed.id, 'kind', claimed.kind, 'attempt', claimed.attempt,
    'profile', jsonb_build_object('id', p.id, 'alias', p.alias, 'mode', p.mode),
    'definition', case when claimed.kind = 'search' then v.definition else null end,
    'condition_refs', case when claimed.kind = 'search' then v.condition_refs else null end)
    into result from public.broker_profiles p
    left join public.strategy_versions v on v.id = claimed.strategy_version_id
      and v.user_id = claimed.user_id and v.strategy_id = claimed.strategy_id
    where p.id = claimed.profile_id;
  return result;
end $$;

-- Only a requeue schedules a retry; a terminal status has nothing to wait for.
create or replace function worker.fail_run(p_run_id uuid,p_worker_id text,p_error_code text,p_error_message text,p_retryable boolean,p_partial jsonb)
returns text language plpgsql security definer set search_path = '' as $$
declare
  r public.runs;
  lease_deadline timestamptz;
  next_status text;
begin
  r := worker.locked_run(p_run_id,p_worker_id,null);
  if r.id is null then return null; end if;
  lease_deadline := r.lease_expires_at;
  if nullif(p_error_code,'') is null or p_retryable is null then raise exception 'PAYLOAD_INVALID'; end if;
  perform worker.store_snapshots(r.id,p_partial,false);
  next_status := case when p_retryable and r.attempt < r.max_attempts then 'queued'
    when p_error_code = 'RUN_TIMEOUT' then 'timed_out' else 'failed' end;
  update public.runs set status = next_status,error_code = p_error_code,error_message = p_error_message,
    finished_at = case when next_status = 'queued' then null else clock_timestamp() end,
    retry_after = case when next_status = 'queued' then clock_timestamp() + worker.retry_backoff(r.attempt) else null end,
    lease_owner = null,lease_expires_at = null where id = r.id;
  update public.broker_profiles set last_error_code = p_error_code,last_error_message = p_error_message where id = r.profile_id;
  if lease_deadline <= clock_timestamp() then raise exception using errcode = 'PT001', message = 'LEASE_LOST'; end if;
  return next_status;
exception
  when sqlstate 'PT001' then return null;
  when data_exception or integrity_constraint_violation then raise exception 'PAYLOAD_INVALID';
end $$;
