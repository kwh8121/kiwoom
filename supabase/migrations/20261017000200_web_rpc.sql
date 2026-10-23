-- The web can mutate versions and runs only through ownership-checked RPCs.
create function public.strategy_leaf_ids(p_expr jsonb)
returns uuid[]
language plpgsql security definer set search_path = ''
as $$
declare
  nodes jsonb[] := array[p_expr];
  depths integer[] := array[1];
  node jsonb;
  children jsonb;
  depth integer;
  leaf uuid;
  leaves integer := 0;
  result uuid[] := '{}'::uuid[];
begin
  while cardinality(nodes) > 0 loop
    node := nodes[1];
    depth := depths[1];
    nodes := nodes[2:];
    depths := depths[2:];
    if node is null or jsonb_typeof(node) <> 'object' or depth > 5 then
      raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
    end if;
    case node->>'type'
      when 'condition' then
        if jsonb_typeof(node->'conditionId') is distinct from 'string' then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end if;
        begin
          leaf := (node->>'conditionId')::uuid;
        exception when invalid_text_representation then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end;
        leaves := leaves + 1;
        if leaves > 10 then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end if;
        if not (leaf = any(result)) then result := array_append(result, leaf); end if;
        continue;
      when 'and', 'or' then
        children := node->'children';
        if jsonb_typeof(children) is distinct from 'array' then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end if;
        if jsonb_array_length(children) < 2 then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end if;
      when 'exclude' then
        children := node->'subtract';
        if jsonb_typeof(children) is distinct from 'array' then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end if;
        if jsonb_array_length(children) < 1 or not (node ? 'base') then
          raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
        end if;
        children := jsonb_build_array(node->'base') || children;
      else
        raise exception using errcode = 'P0001', message = 'INVALID_DEFINITION';
    end case;
    -- Prepend children in source order so traversal is depth-first.
    select array_agg(value order by ordinality) || nodes,
           array_agg(depth + 1 order by ordinality) || depths
      into nodes, depths from jsonb_array_elements(children) with ordinality;
  end loop;
  return result;
end;
$$;

create function public.create_strategy_version(p_strategy_id uuid, p_definition jsonb)
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

create function public.request_run(p_kind text, p_profile_id uuid, p_strategy_id uuid, p_idempotency_key uuid)
returns public.runs
language plpgsql security definer set search_path = ''
as $$
declare
  strategy public.strategies;
  version public.strategy_versions;
  ref jsonb;
  result public.runs;
begin
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

create function public.cancel_run(p_run_id uuid)
returns public.runs
language plpgsql security definer set search_path = ''
as $$
declare result public.runs;
begin
  update public.runs set status = 'cancelled', finished_at = now()
    where id = p_run_id and user_id = auth.uid() and status = 'queued' returning * into result;
  if found then return result; end if;
  perform 1 from public.runs where id = p_run_id and user_id = auth.uid();
  if not found then raise exception using errcode = 'P0001', message = 'NOT_FOUND'; end if;
  raise exception using errcode = 'P0001', message = 'RUN_NOT_CANCELLABLE';
end;
$$;

create function public.reject_strategy_version_mutation()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  raise exception using errcode = 'P0001', message = 'VERSION_IMMUTABLE';
end;
$$;
create trigger strategy_versions_immutable before update or delete on public.strategy_versions
  for each row execute function public.reject_strategy_version_mutation();

revoke all on function public.strategy_leaf_ids(jsonb) from public, anon, authenticated, service_role;
revoke all on function public.create_strategy_version(uuid, jsonb) from public, anon, authenticated, service_role;
revoke all on function public.request_run(text, uuid, uuid, uuid) from public, anon, authenticated, service_role;
revoke all on function public.cancel_run(uuid) from public, anon, authenticated, service_role;
revoke all on function public.reject_strategy_version_mutation() from public, anon, authenticated, service_role;
grant execute on function public.strategy_leaf_ids(jsonb) to authenticated;
grant execute on function public.create_strategy_version(uuid, jsonb) to authenticated;
grant execute on function public.request_run(text, uuid, uuid, uuid) to authenticated;
grant execute on function public.cancel_run(uuid) to authenticated;
