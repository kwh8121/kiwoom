-- complete_search_run checked only that each claimed condition's snapshot
-- contained the result code. It never checked the other direction, so a result
-- could understate which conditions matched it, and it never evaluated the
-- strategy expression at all. For an `A and B` strategy the worker could submit
-- a code that only A matched, claim it matched only A, and have it stored as a
-- success; it could equally drop a code that did satisfy the expression.
--
-- The worker is trusted for the raw broker data it collects into snapshots. It
-- is not trusted for the derivation from that data, so the derivation moves
-- here. This adds no grammar and no limits: public.strategy_leaf_ids already
-- walks this expression shape, and create_strategy_version already enforced
-- the depth and leaf caps on the definition being evaluated.
create function worker.expr_result_codes(p_run_id uuid, p_expr jsonb)
returns text[] language plpgsql security definer set search_path = '' as $$
declare
  child jsonb;
  child_codes text[];
  acc text[];
  seen_first boolean := false;
begin
  case p_expr->>'type'
    when 'condition' then
      select coalesce(array_agg(m.code), '{}'::text[]) into acc
        from public.condition_snapshots s
        join public.condition_snapshot_members m on m.snapshot_id = s.id
        where s.run_id = p_run_id and s.condition_id = (p_expr->>'conditionId')::uuid;
      return acc;
    when 'and' then
      for child in select value from jsonb_array_elements(p_expr->'children') loop
        child_codes := worker.expr_result_codes(p_run_id, child);
        if seen_first then
          acc := array(select unnest(acc) intersect select unnest(child_codes));
        else
          acc := child_codes;
          seen_first := true;
        end if;
      end loop;
      return coalesce(acc, '{}'::text[]);
    when 'or' then
      acc := '{}'::text[];
      for child in select value from jsonb_array_elements(p_expr->'children') loop
        child_codes := worker.expr_result_codes(p_run_id, child);
        acc := array(select unnest(acc) union select unnest(child_codes));
      end loop;
      return acc;
    when 'exclude' then
      acc := worker.expr_result_codes(p_run_id, p_expr->'base');
      for child in select value from jsonb_array_elements(p_expr->'subtract') loop
        child_codes := worker.expr_result_codes(p_run_id, child);
        acc := array(select unnest(acc) except select unnest(child_codes));
      end loop;
      return acc;
    else
      raise exception using errcode = 'P0001', message = 'PAYLOAD_INVALID';
  end case;
end $$;
-- Private like worker.locked_run: only the settlement RPC may call it.
revoke all on function worker.expr_result_codes(uuid, jsonb)
  from public, anon, authenticated, service_role, kiwoom_worker;

create or replace function worker.complete_search_run(p_run_id uuid, p_worker_id text, p_payload jsonb)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  r public.runs;
  lease_deadline timestamptz;
  previous_id uuid;
  item jsonb;
  matched uuid[];
  member public.condition_snapshot_members;
  start_time timestamptz;
  end_time timestamptz;
  exclusions text[];
  definition jsonb;
  expected text[];
  claimed text[];
  derived text[];
begin
  r := worker.locked_run(p_run_id,p_worker_id,'search');
  if r.id is null then return false; end if;
  lease_deadline := r.lease_expires_at;
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

  -- The stored snapshots are now the only input, and the expression decides
  -- which of their codes belong in the results.
  select v.definition into definition from public.strategy_versions v
    where v.id = r.strategy_version_id and v.user_id = r.user_id;
  if definition is null then raise exception 'PAYLOAD_INVALID'; end if;
  expected := array(select unnest(worker.expr_result_codes(r.id, definition->'expr')) order by 1);
  claimed := array(select distinct value->>'code' from jsonb_array_elements(p_payload->'results') value order by 1);
  -- Distinct collapses a repeated code, so compare the count as well.
  if jsonb_array_length(p_payload->'results') <> coalesce(cardinality(claimed),0)
     or claimed is distinct from expected then raise exception 'PAYLOAD_INVALID'; end if;

  select id into previous_id from public.runs where strategy_id = r.strategy_id and profile_id = r.profile_id
    and user_id = r.user_id and kind = 'search' and status = 'succeeded'
    order by finished_at desc, id desc limit 1;
  for item in select value from jsonb_array_elements(p_payload->'results') loop
    if jsonb_typeof(item->'matched_condition_ids') is distinct from 'array'
       or item->>'code' is null or item->>'code' !~ '^[0-9A-Z]{6}$' then raise exception 'PAYLOAD_INVALID'; end if;
    select array_agg(value::uuid order by ordinality) into matched
      from jsonb_array_elements_text(item->'matched_condition_ids') with ordinality;
    if coalesce(cardinality(matched),0) = 0 or cardinality(matched) <> (select count(distinct id) from unnest(matched) id)
       then raise exception 'PAYLOAD_INVALID'; end if;
    -- Every condition whose snapshot holds this code, and only those. The
    -- order the worker chose is preserved because it drives the display.
    derived := array(select s.condition_id::text from public.condition_snapshots s
      join public.condition_snapshot_members m on m.snapshot_id = s.id
      where s.run_id = r.id and m.code = item->>'code' order by 1);
    if derived is distinct from array(select unnest(matched)::text order by 1)
       then raise exception 'PAYLOAD_INVALID'; end if;
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
  update public.runs set status = 'succeeded',finished_at = clock_timestamp(),lease_owner = null,lease_expires_at = null,
    window_start = start_time,window_end = end_time,market_phase = p_payload->>'market_phase',
    compared_run_id = previous_id,excluded_codes = exclusions,result_count = jsonb_array_length(p_payload->'results'),
    error_code = null,error_message = null where id = r.id;
  update public.broker_profiles set last_ok_at = clock_timestamp(),last_error_code = null,last_error_message = null where id = r.profile_id;
  if lease_deadline <= clock_timestamp() then raise exception using errcode = 'PT001', message = 'LEASE_LOST'; end if;
  return true;
exception
  when sqlstate 'PT001' then return false;
  when data_exception or integrity_constraint_violation then raise exception 'PAYLOAD_INVALID';
end $$;
