-- Supabase issues an aal1 session for a correct password alone, and that
-- session's access token can call PostgREST directly. Gating only the web
-- routes would leave MFA decorative, so the requirement lives in the row
-- policies and in the web RPCs, which are SECURITY DEFINER and bypass RLS.
--
-- A user who has not enrolled a factor is unaffected. Requiring aal2
-- unconditionally would lock the operator out of their own data the moment this
-- migration applied, before they could enroll anything.
create function public.mfa_satisfied() returns boolean
language sql stable security definer set search_path = '' as $MFA$
  select case
    when exists (
      select 1 from auth.mfa_factors f
      where f.user_id = (select auth.uid()) and f.status = 'verified'
    ) then coalesce(auth.jwt()->>'aal', '') = 'aal2'
    else true
  end
$MFA$;
revoke all on function public.mfa_satisfied() from public, anon, service_role, kiwoom_worker;
grant execute on function public.mfa_satisfied() to authenticated;

-- Every owned table reads through the same policy shape, so rewrite them the
-- way they were created. The call is wrapped in a scalar subquery so it is
-- evaluated once per query rather than once per row.
do $REWRITE$
declare
  owned text;
begin
  foreach owned in array array['broker_profiles', 'conditions', 'strategies', 'strategy_versions', 'runs', 'condition_snapshots', 'condition_snapshot_members', 'run_results', 'condition_sync_events'] loop
    execute format('drop policy owner_select on public.%I', owned);
    execute format(
      'create policy owner_select on public.%I for select to authenticated'
      ' using (user_id = (select auth.uid()) and (select public.mfa_satisfied()))',
      owned
    );
  end loop;
end $REWRITE$;

drop policy owner_insert on public.broker_profiles;
create policy owner_insert on public.broker_profiles
  for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and (select public.mfa_satisfied())
    and exists (
      select 1 from public.broker_alias_owners o
      where o.alias = broker_profiles.alias
        and o.user_id = (select auth.uid())
    )
  );
drop policy owner_update on public.broker_profiles;
create policy owner_update on public.broker_profiles
  for update to authenticated
  using (user_id = (select auth.uid()) and (select public.mfa_satisfied()))
  with check (user_id = (select auth.uid()) and (select public.mfa_satisfied()));

drop policy owner_insert on public.strategies;
create policy owner_insert on public.strategies
  for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and (select public.mfa_satisfied())
    and exists (
      select 1 from public.broker_profiles
      where broker_profiles.id = strategies.profile_id
        and broker_profiles.user_id = (select auth.uid())
    )
  );
drop policy owner_update on public.strategies;
create policy owner_update on public.strategies
  for update to authenticated
  using (user_id = (select auth.uid()) and (select public.mfa_satisfied()))
  with check (user_id = (select auth.uid()) and (select public.mfa_satisfied()));

drop policy owner_update on public.conditions;
create policy owner_update on public.conditions
  for update to authenticated
  using (user_id = (select auth.uid()) and (select public.mfa_satisfied()))
  with check (user_id = (select auth.uid()) and (select public.mfa_satisfied()));

drop policy owner_select on public.broker_alias_owners;
create policy owner_select on public.broker_alias_owners
  for select to authenticated
  using (user_id = (select auth.uid()) and (select public.mfa_satisfied()));

drop policy owner_alias_read on public.worker_heartbeats;
create policy owner_alias_read on public.worker_heartbeats
  for select to authenticated using (
    (select public.mfa_satisfied())
    and exists (
      select 1 from public.broker_alias_owners o
      where o.user_id = (select auth.uid())
        and o.alias = any(worker_heartbeats.aliases)
    )
  );

-- market_closures stays readable: exchange closures are public market facts and
-- carry nothing about the user.

create or replace function public.create_strategy_version(p_strategy_id uuid, p_definition jsonb)
returns public.strategy_versions
language plpgsql security definer set search_path = ''
as $$
declare
  strategy public.strategies;
  condition public.conditions;
  leaf uuid;
  refs jsonb := '[]'::jsonb;
  result public.strategy_versions;
begin
  if not public.mfa_satisfied() then raise exception using errcode = 'P0001', message = 'MFA_REQUIRED'; end if;
  select * into strategy from public.strategies
    where id = p_strategy_id and user_id = auth.uid() and archived_at is null for update;
  if not found then raise exception using errcode = 'P0001', message = 'NOT_FOUND'; end if;
  if jsonb_typeof(p_definition) is distinct from 'object'
     or (p_definition->'schemaVersion') is distinct from '1'::jsonb
     or (p_definition->'exchange') is distinct from '"K"'::jsonb
     or (p_definition->'profileId') is distinct from to_jsonb(strategy.profile_id::text) then
    raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
  end if;
  foreach leaf in array public.strategy_leaf_ids(p_definition->'expr') loop
    select * into condition from public.conditions
      where id = leaf and user_id = auth.uid() for share;
    if not found then raise exception using errcode = 'P0001', message = 'CONDITION_INACTIVE'; end if;
    if condition.profile_id <> strategy.profile_id then
      raise exception using errcode = 'P0001', message = 'PROFILE_MISMATCH';
    end if;
    if not condition.is_active then raise exception using errcode = 'P0001', message = 'CONDITION_INACTIVE'; end if;
    refs := refs || jsonb_build_array(jsonb_build_object('conditionId', condition.id, 'seq', condition.seq, 'name', condition.name));
  end loop;
  insert into public.strategy_versions(user_id, strategy_id, version, definition, condition_refs)
    select auth.uid(), strategy.id, coalesce(max(version), 0) + 1, p_definition, refs
    from public.strategy_versions where strategy_id = strategy.id
    returning * into result;
  update public.strategies set current_version_id = result.id where id = strategy.id;
  return result;
end;
$$;

create or replace function public.request_run(p_kind text, p_profile_id uuid, p_strategy_id uuid, p_idempotency_key uuid)
returns public.runs
language plpgsql security definer set search_path = ''
as $$
declare
  strategy public.strategies;
  version public.strategy_versions;
  ref jsonb;
  result public.runs;
begin
  if not public.mfa_satisfied() then raise exception using errcode = 'P0001', message = 'MFA_REQUIRED'; end if;
  select * into result from public.runs where user_id = auth.uid() and idempotency_key = p_idempotency_key;
  if found then return result; end if;
  perform 1 from public.broker_profiles where id = p_profile_id and user_id = auth.uid() for update;
  if not found then raise exception using errcode = 'P0001', message = 'NOT_FOUND'; end if;
  -- Recheck after the profile lock: a simultaneous identical request may have committed.
  select * into result from public.runs where user_id = auth.uid() and idempotency_key = p_idempotency_key;
  if found then return result; end if;
  if p_kind is null or p_kind not in ('sync', 'search') or p_idempotency_key is null
     or (p_kind = 'sync' and p_strategy_id is not null) then
    raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
  end if;
  if p_kind = 'search' then
    select * into strategy from public.strategies
      where id = p_strategy_id and user_id = auth.uid() and profile_id = p_profile_id and archived_at is null for share;
    if not found then raise exception using errcode = 'P0001', message = 'NOT_FOUND'; end if;
    if strategy.current_version_id is null then raise exception using errcode = 'P0001', message = 'STRATEGY_HAS_NO_VERSION'; end if;
    select * into version from public.strategy_versions
      where id = strategy.current_version_id and strategy_id = strategy.id and user_id = auth.uid();
    if not found then raise exception using errcode = 'P0001', message = 'STRATEGY_HAS_NO_VERSION'; end if;
    for ref in select value from jsonb_array_elements(version.condition_refs) loop
      perform 1 from public.conditions
        where id::text = ref->>'conditionId' and user_id = auth.uid() and profile_id = p_profile_id
          and is_active and seq = ref->>'seq' and name = ref->>'name' for share;
      if not found then raise exception using errcode = 'P0001', message = 'CONDITION_INACTIVE'; end if;
    end loop;
  end if;
  begin
    insert into public.runs(user_id, kind, profile_id, strategy_id, strategy_version_id, status, idempotency_key)
      values (auth.uid(), p_kind, p_profile_id, strategy.id, version.id, 'queued', p_idempotency_key)
      returning * into result;
  exception when unique_violation then
    select * into result from public.runs where user_id = auth.uid() and idempotency_key = p_idempotency_key;
    if not found then raise exception using errcode = 'P0001', message = 'PROFILE_BUSY'; end if;
  end;
  return result;
end;
$$;

create or replace function public.cancel_run(p_run_id uuid)
returns public.runs
language plpgsql security definer set search_path = ''
as $$
declare result public.runs;
begin
  if not public.mfa_satisfied() then raise exception using errcode = 'P0001', message = 'MFA_REQUIRED'; end if;
  update public.runs set status = 'cancelled', finished_at = now()
    where id = p_run_id and user_id = auth.uid() and status = 'queued' returning * into result;
  if found then return result; end if;
  perform 1 from public.runs where id = p_run_id and user_id = auth.uid();
  if not found then raise exception using errcode = 'P0001', message = 'NOT_FOUND'; end if;
  raise exception using errcode = 'P0001', message = 'RUN_NOT_CANCELLABLE';
end;
$$;
