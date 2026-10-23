-- A worker process holds the real broker credentials for an alias, and
-- worker.claim_next_run chose work by alias alone. broker_profiles.alias was
-- unique per user only, so a second account could register a profile with the
-- operator's alias, and the operator's worker would run that account's searches
-- with the operator's credentials and store the results under its rows. The
-- worker_heartbeats table was readable by every logged-in user, so it also
-- published which aliases to copy. Bind each alias to one owner in the database
-- and keep both the registry and the heartbeat list out of client reach.

create table public.broker_alias_owners (
  alias text primary key check (alias ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  user_id uuid not null references auth.users on delete cascade,
  created_at timestamptz not null default now()
);
alter table public.broker_alias_owners enable row level security;
revoke all on table public.broker_alias_owners from public, anon, authenticated, kiwoom_worker;
grant select on table public.broker_alias_owners to authenticated;
-- Registration is an operator step during provisioning, so there is deliberately
-- no insert, update or delete grant to accompany this read policy.
create policy owner_select on public.broker_alias_owners
  for select to authenticated using (user_id = (select auth.uid()));
create index broker_alias_owners_user_id_idx on public.broker_alias_owners (user_id);

-- One alias, one profile. The per-user constraint is what left an alias
-- ambiguous for a worker that resolves credentials by alias.
alter table public.broker_profiles add constraint broker_profiles_alias_key unique (alias);

-- A profile may only use an alias registered to its owner.
drop policy owner_insert on public.broker_profiles;
create policy owner_insert on public.broker_profiles
  for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and exists (
      select 1 from public.broker_alias_owners o
      where o.alias = broker_profiles.alias
        and o.user_id = (select auth.uid())
    )
  );

-- Claiming now requires the profile's alias to be registered to the profile's
-- owner, so an unregistered or someone else's alias resolves to no work.
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
    order by r.requested_at, r.id for update of r skip locked limit 1;
  if not found then return null; end if;
  update public.runs set status = 'running', attempt = attempt + 1,
    lease_owner = p_worker_id, lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
    started_at = coalesce(started_at, clock_timestamp()), finished_at = null,
    error_code = null, error_message = null
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

-- Reachability needs only the aliases the caller owns, not the whole roster.
drop policy authenticated_read on public.worker_heartbeats;
create policy owner_alias_read on public.worker_heartbeats
  for select to authenticated using (
    exists (
      select 1 from public.broker_alias_owners o
      where o.user_id = (select auth.uid())
        and o.alias = any(worker_heartbeats.aliases)
    )
  );

-- One worker may serve several owners, and the row it shares must not disclose
-- the other owners' aliases, so the app reads the caller's intersection.
create view public.my_worker_heartbeats with (security_invoker = true) as
  select h.worker_id,
    array(
      select o.alias from public.broker_alias_owners o
      where o.user_id = (select auth.uid())
        and o.alias = any(h.aliases)
      order by o.alias
    ) as aliases,
    h.seen_at
  from public.worker_heartbeats h;
grant select on public.my_worker_heartbeats to authenticated;
