-- The service login has no table grants or RLS bypass. Only these private RPCs
-- cross the privilege boundary; their ownership comes from a locked run.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kiwoom_worker') then
    create role kiwoom_worker nologin nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
  end if;
end $$;
-- Supabase's migration role is not a superuser and cannot ALTER SUPERUSER or
-- BYPASSRLS attributes, even to false. Refuse an unsafe pre-existing role.
do $$ begin
  if exists(select 1 from pg_roles where rolname = 'kiwoom_worker' and (rolsuper or rolbypassrls)) then
    raise exception 'UNSAFE_WORKER_ROLE';
  end if;
end $$;
alter role kiwoom_worker nologin nocreatedb nocreaterole noinherit;
create schema worker;
revoke all on schema worker from public, anon, authenticated, service_role;
grant usage on schema worker to kiwoom_worker;
alter default privileges in schema worker revoke execute on functions from public;

create table public.worker_heartbeats (
  worker_id text primary key,
  aliases text[] not null,
  version text not null,
  seen_at timestamptz not null default now()
);
alter table public.worker_heartbeats enable row level security;
revoke all on public.worker_heartbeats from public, anon, authenticated, kiwoom_worker;
grant select on public.worker_heartbeats to authenticated;
create policy authenticated_read on public.worker_heartbeats for select to authenticated using (true);

create function worker.heartbeat(p_worker_id text, p_aliases text[], p_version text)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if nullif(btrim(p_worker_id), '') is null or p_aliases is null or p_version is null then
    raise exception 'PAYLOAD_INVALID';
  end if;
  insert into public.worker_heartbeats(worker_id, aliases, version, seen_at)
    values (p_worker_id, p_aliases, p_version, clock_timestamp())
    on conflict (worker_id) do update set aliases = excluded.aliases,
      version = excluded.version, seen_at = excluded.seen_at;
end $$;

create function worker.claim_next_run(p_worker_id text, p_aliases text[], p_lease_seconds int)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  expired public.runs;
  claimed public.runs;
  result jsonb;
begin
  if nullif(btrim(p_worker_id), '') is null or p_aliases is null
     or p_lease_seconds is null or p_lease_seconds < 1 then raise exception 'PAYLOAD_INVALID'; end if;
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

-- Private helper: lock first, then check wall-clock expiry (now() is the
-- transaction start and would let old, long-lived transactions revive leases).
create function worker.locked_run(p_run_id uuid, p_worker_id text, p_kind text)
returns public.runs language plpgsql security definer set search_path = '' as $$
declare r public.runs;
begin
  select * into r from public.runs where id = p_run_id for update;
  if not found or r.status <> 'running' or r.lease_owner is distinct from p_worker_id
     or p_worker_id is null or r.lease_expires_at is null or r.lease_expires_at <= clock_timestamp()
     or (p_kind is not null and r.kind <> p_kind) then return null; end if;
  perform 1 from public.broker_profiles where id = r.profile_id and user_id = r.user_id;
  if not found then return null; end if;
  return r;
end $$;

create function worker.extend_lease(p_run_id uuid, p_worker_id text, p_lease_seconds int)
returns boolean language plpgsql security definer set search_path = '' as $$
declare r public.runs;
begin
  r := worker.locked_run(p_run_id, p_worker_id, null);
  if r.id is null then return false; end if;
  if p_lease_seconds is null or p_lease_seconds < 1 then raise exception 'PAYLOAD_INVALID'; end if;
  update public.runs set lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds)
    where id = r.id;
  return true;
end $$;

-- Validate immutable condition refs before accepting worker-supplied snapshots.
-- All writes derive user_id from the run, never from JSON or a caller argument.
create function worker.store_snapshots(p_run_id uuid, p_items jsonb, p_complete boolean)
returns void language plpgsql security definer set search_path = '' as $$
declare
  r public.runs;
  refs jsonb;
  item jsonb;
  member jsonb;
  snapshot_id uuid;
  condition_id uuid;
  seen uuid[] := '{}'::uuid[];
  start_time timestamptz;
  end_time timestamptz;
  pages int;
begin
  select * into strict r from public.runs where id = p_run_id;
  select v.condition_refs into refs from public.strategy_versions v
    join public.strategies s on s.id = v.strategy_id and s.user_id = r.user_id and s.profile_id = r.profile_id
    where v.id = r.strategy_version_id and v.strategy_id = r.strategy_id and v.user_id = r.user_id;
  if jsonb_typeof(p_items) is distinct from 'array' or (r.kind = 'search' and refs is null)
     or (r.kind = 'sync' and p_items <> '[]'::jsonb) then raise exception 'PAYLOAD_INVALID'; end if;
  if p_complete and jsonb_array_length(p_items) <> jsonb_array_length(refs) then raise exception 'PAYLOAD_INVALID'; end if;
  delete from public.condition_snapshots where run_id = r.id;
  for item in select value from jsonb_array_elements(p_items) loop
    condition_id := (item->>'condition_id')::uuid;
    if condition_id is null or condition_id = any(seen) then raise exception 'PAYLOAD_INVALID'; end if;
    seen := array_append(seen, condition_id);
    perform 1 from jsonb_array_elements(refs) ref
      join public.conditions c on c.id = condition_id and c.user_id = r.user_id and c.profile_id = r.profile_id
      where ref->>'conditionId' = condition_id::text and ref->>'seq' = item->>'seq' and ref->>'name' = item->>'name';
    if not found then raise exception 'PAYLOAD_INVALID'; end if;
    start_time := (item->>'started_at')::timestamptz;
    end_time := (item->>'completed_at')::timestamptz;
    pages := (item->>'page_count')::int;
    if pages < 0 or (end_time is not null and start_time is not null and end_time < start_time)
       or (p_complete and (start_time is null or end_time is null or pages is null or pages < 1
         or jsonb_typeof(item->'members') is distinct from 'array'
         or (item ? 'is_complete' and item->'is_complete' <> 'true'::jsonb)
         or item->>'error_code' is not null)) then raise exception 'PAYLOAD_INVALID'; end if;
    insert into public.condition_snapshots(user_id,run_id,condition_id,seq,name,started_at,completed_at,page_count,row_count,is_complete,error_code)
      values (r.user_id,r.id,condition_id,item->>'seq',item->>'name',start_time,end_time,pages,
        case when p_complete then jsonb_array_length(item->'members') else (item->>'row_count')::int end,
        p_complete,case when p_complete then null else item->>'error_code' end)
      returning id into snapshot_id;
    if p_complete then
      for member in select value from jsonb_array_elements(item->'members') loop
        if member->>'code' is null or member->>'code' !~ '^[0-9A-Z]{6}$'
           or member->>'raw_code' is null or member->>'instrument_type' is null
           or member->>'instrument_type' not in ('stock','elw','etn') then raise exception 'PAYLOAD_INVALID'; end if;
        insert into public.condition_snapshot_members(user_id,snapshot_id,code,raw_code,instrument_type,name,price,change_rate)
          values (r.user_id,snapshot_id,member->>'code',member->>'raw_code',member->>'instrument_type',
            member->>'name',(member->>'price')::bigint,(member->>'change_rate')::numeric);
      end loop;
    elsif coalesce((item->>'row_count')::int,0) < 0 then raise exception 'PAYLOAD_INVALID';
    end if;
  end loop;
end $$;

create function worker.complete_search_run(p_run_id uuid, p_worker_id text, p_payload jsonb)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  r public.runs;
  previous_id uuid;
  item jsonb;
  matched uuid[];
  member public.condition_snapshot_members;
  start_time timestamptz;
  end_time timestamptz;
  exclusions text[];
begin
  r := worker.locked_run(p_run_id,p_worker_id,'search');
  if r.id is null then return false; end if;
  if jsonb_typeof(p_payload) is distinct from 'object'
     or jsonb_typeof(p_payload->'results') is distinct from 'array'
     or jsonb_typeof(p_payload->'excluded_codes') is distinct from 'array'
     or p_payload->>'market_phase' is null or p_payload->>'market_phase' not in ('pre','regular','post','weekend')
     then raise exception 'PAYLOAD_INVALID'; end if;
  start_time := (p_payload->>'window_start')::timestamptz;
  end_time := (p_payload->>'window_end')::timestamptz;
  if start_time is null or end_time is null or end_time < start_time then raise exception 'PAYLOAD_INVALID'; end if;
  if exists(select 1 from jsonb_array_elements(p_payload->'excluded_codes') e
    where jsonb_typeof(e) <> 'string' or e #>> '{}' !~ '^[0-9A-Z]{6}$') then raise exception 'PAYLOAD_INVALID'; end if;
  select coalesce(array_agg(value order by value),'{}') into exclusions
    from jsonb_array_elements_text(p_payload->'excluded_codes');
  perform worker.store_snapshots(r.id,p_payload->'snapshots',true);
  select id into previous_id from public.runs where strategy_id = r.strategy_id and profile_id = r.profile_id
    and user_id = r.user_id and kind = 'search' and status = 'succeeded'
    order by finished_at desc, id desc limit 1;
  for item in select value from jsonb_array_elements(p_payload->'results') loop
    if jsonb_typeof(item->'matched_condition_ids') is distinct from 'array'
       or item->>'code' is null or item->>'code' !~ '^[0-9A-Z]{6}$' then raise exception 'PAYLOAD_INVALID'; end if;
    select array_agg(value::uuid order by ordinality) into matched
      from jsonb_array_elements_text(item->'matched_condition_ids') with ordinality;
    if coalesce(cardinality(matched),0) = 0 or cardinality(matched) <> (select count(distinct id) from unnest(matched) id)
       or exists(select 1 from unnest(matched) as match_id(id) where not exists (
         select 1 from public.condition_snapshots s join public.condition_snapshot_members m on m.snapshot_id = s.id
         where s.run_id = r.id and s.condition_id = match_id.id and m.code = item->>'code')) then raise exception 'PAYLOAD_INVALID'; end if;
    select m.* into member from public.condition_snapshots s
      join public.condition_snapshot_members m on m.snapshot_id = s.id
      where s.run_id = r.id and s.condition_id = matched[1] and m.code = item->>'code';
    if not found then raise exception 'PAYLOAD_INVALID'; end if;
    insert into public.run_results(user_id,run_id,code,name,instrument_type,matched_condition_ids,diff,price,change_rate)
      values (r.user_id,r.id,member.code,member.name,member.instrument_type,matched,
        case when exists(select 1 from public.run_results where run_id = previous_id and code = member.code)
          then 'kept' else 'new' end,member.price,member.change_rate);
  end loop;
  -- An expiry during payload processing rolls back every write in this block.
  if r.lease_expires_at <= clock_timestamp() then raise exception using errcode = 'PT001', message = 'LEASE_LOST'; end if;
  update public.runs set status = 'succeeded',finished_at = clock_timestamp(),lease_owner = null,lease_expires_at = null,
    window_start = start_time,window_end = end_time,market_phase = p_payload->>'market_phase',
    compared_run_id = previous_id,excluded_codes = exclusions,result_count = jsonb_array_length(p_payload->'results'),
    error_code = null,error_message = null where id = r.id;
  update public.broker_profiles set last_ok_at = clock_timestamp(),last_error_code = null,last_error_message = null where id = r.profile_id;
  return true;
exception
  when sqlstate 'PT001' then return false;
  when data_exception or integrity_constraint_violation then raise exception 'PAYLOAD_INVALID';
end $$;

create function worker.complete_sync_run(p_run_id uuid, p_worker_id text, p_items jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  r public.runs;
  old public.conditions;
  item jsonb;
  new_id uuid;
  replaced_seqs text[] := '{}'::text[];
  added int := 0;
  removed int := 0;
  replaced int := 0;
  unchanged int := 0;
  summary jsonb;
begin
  r := worker.locked_run(p_run_id,p_worker_id,'sync');
  if r.id is null then return 'false'::jsonb; end if;
  if jsonb_typeof(p_items) is distinct from 'array' then raise exception 'PAYLOAD_INVALID'; end if;
  if exists(select 1 from jsonb_array_elements(p_items) e where jsonb_typeof(e->'seq') is distinct from 'string'
      or jsonb_typeof(e->'name') is distinct from 'string' or nullif(e->>'seq','') is null or nullif(e->>'name','') is null)
     or (select count(*) <> count(distinct e->>'seq') from jsonb_array_elements(p_items) e)
     then raise exception 'PAYLOAD_INVALID'; end if;
  for old in select * from public.conditions where profile_id = r.profile_id and user_id = r.user_id and is_active for update loop
    select value into item from jsonb_array_elements(p_items) where value->>'seq' = old.seq;
    if found and item->>'name' = old.name then
      update public.conditions set last_synced_at = clock_timestamp() where id = old.id;
      unchanged := unchanged + 1;
    else
      update public.conditions set is_active = false,deactivated_at = clock_timestamp() where id = old.id;
      if item is not null then
        replaced := replaced + 1;
        replaced_seqs := array_append(replaced_seqs,old.seq);
      else removed := removed + 1;
      end if;
      insert into public.condition_sync_events(user_id,profile_id,run_id,event,seq,old_name,new_name,condition_id)
        values(r.user_id,r.profile_id,r.id,case when item is null then 'removed' else 'replaced' end,
          old.seq,old.name,item->>'name',old.id);
    end if;
  end loop;
  for item in select value from jsonb_array_elements(p_items) loop
    if not exists(select 1 from public.conditions where profile_id = r.profile_id and user_id = r.user_id
      and is_active and seq = item->>'seq') then
      insert into public.conditions(user_id,profile_id,seq,name)
        values(r.user_id,r.profile_id,item->>'seq',item->>'name') returning id into new_id;
      if not (item->>'seq' = any(replaced_seqs)) then
        added := added + 1;
        insert into public.condition_sync_events(user_id,profile_id,run_id,event,seq,new_name,condition_id)
          values(r.user_id,r.profile_id,r.id,'added',item->>'seq',item->>'name',new_id);
      end if;
    end if;
  end loop;
  if r.lease_expires_at <= clock_timestamp() then raise exception using errcode = 'PT001', message = 'LEASE_LOST'; end if;
  summary := jsonb_build_object('added',added,'removed',removed,'replaced',replaced,'unchanged',unchanged);
  update public.runs set status = 'succeeded',finished_at = clock_timestamp(),lease_owner = null,lease_expires_at = null,
    sync_summary = summary,error_code = null,error_message = null where id = r.id;
  update public.broker_profiles set last_ok_at = clock_timestamp(),last_error_code = null,last_error_message = null where id = r.profile_id;
  return summary;
exception
  when sqlstate 'PT001' then return 'false'::jsonb;
  when data_exception or integrity_constraint_violation then raise exception 'PAYLOAD_INVALID';
end $$;

create function worker.fail_run(p_run_id uuid,p_worker_id text,p_error_code text,p_error_message text,p_retryable boolean,p_partial jsonb)
returns text language plpgsql security definer set search_path = '' as $$
declare r public.runs; next_status text;
begin
  r := worker.locked_run(p_run_id,p_worker_id,null);
  if r.id is null then return null; end if;
  if nullif(p_error_code,'') is null or p_retryable is null then raise exception 'PAYLOAD_INVALID'; end if;
  perform worker.store_snapshots(r.id,p_partial,false);
  next_status := case when p_retryable and r.attempt < r.max_attempts then 'queued'
    when p_error_code = 'RUN_TIMEOUT' then 'timed_out' else 'failed' end;
  if r.lease_expires_at <= clock_timestamp() then raise exception using errcode = 'PT001', message = 'LEASE_LOST'; end if;
  update public.runs set status = next_status,error_code = p_error_code,error_message = p_error_message,
    finished_at = case when next_status = 'queued' then null else clock_timestamp() end,
    lease_owner = null,lease_expires_at = null where id = r.id;
  update public.broker_profiles set last_error_code = p_error_code,last_error_message = p_error_message where id = r.profile_id;
  return next_status;
exception
  when sqlstate 'PT001' then return null;
  when data_exception or integrity_constraint_violation then raise exception 'PAYLOAD_INVALID';
end $$;

revoke all on all functions in schema worker from public,anon,authenticated,service_role,kiwoom_worker;
grant execute on function worker.heartbeat(text,text[],text),worker.claim_next_run(text,text[],int),
  worker.extend_lease(uuid,text,int),worker.complete_search_run(uuid,text,jsonb),
  worker.complete_sync_run(uuid,text,jsonb),worker.fail_run(uuid,text,text,text,boolean,jsonb) to kiwoom_worker;
