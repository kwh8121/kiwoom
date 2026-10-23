-- worker.locked_run identified the lease holder by KIWOOM_WORKER_ID alone, so
-- two processes sharing that id were indistinguishable. The one whose lease had
-- expired could still extend and settle the run the other now held, and its own
-- keepalive never detected the loss because the id still matched -- which also
-- defeats the lease-loss cancellation in the worker. Issue a distinct lease
-- owner per claim and have the worker echo it back, so a superseded holder is
-- told apart from the current one. locked_run already compares lease_owner to
-- the value it is handed, so no other function changes.
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
  -- The worker id stays in the value so operators can still read the holder out
  -- of runs.lease_owner and journalctl; the suffix is what fences the claim.
  update public.runs set status = 'running', attempt = attempt + 1,
    lease_owner = p_worker_id || ':' || gen_random_uuid(),
    lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
    started_at = coalesce(started_at, clock_timestamp()), finished_at = null,
    error_code = null, error_message = null, retry_after = null
    where id = claimed.id returning * into claimed;
  select jsonb_build_object('run_id', claimed.id, 'kind', claimed.kind, 'attempt', claimed.attempt,
    'lease_owner', claimed.lease_owner,
    'profile', jsonb_build_object('id', p.id, 'alias', p.alias, 'mode', p.mode),
    'definition', case when claimed.kind = 'search' then v.definition else null end,
    'condition_refs', case when claimed.kind = 'search' then v.condition_refs else null end)
    into result from public.broker_profiles p
    left join public.strategy_versions v on v.id = claimed.strategy_version_id
      and v.user_id = claimed.user_id and v.strategy_id = claimed.strategy_id
    where p.id = claimed.profile_id;
  return result;
end $$;
