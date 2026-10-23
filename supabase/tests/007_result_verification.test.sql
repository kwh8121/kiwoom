begin;
select plan(12);

-- complete_search_run checked only that each claimed condition's snapshot
-- contained the result code. It never checked the other direction, so a result
-- could understate which conditions matched it, and it never evaluated the
-- strategy expression at all. For an `A and B` strategy the worker could submit
-- a code that only A matched, claim it matched only A, and have it stored as a
-- success; it could equally drop a code that did satisfy the expression. The
-- worker is trusted for the raw broker data in its snapshots, not for the
-- derivation from that data, so the derivation moves into the database.
select has_function('worker', 'expr_result_codes', array['uuid', 'jsonb'],
  'the database can evaluate a strategy expression over a run''s snapshots');

grant kiwoom_worker to postgres;
grant usage on schema extensions to kiwoom_worker;

insert into auth.users(id, email) values ('10000000-0000-0000-0000-000000000001', 'verify@example.invalid');
insert into public.broker_alias_owners(alias, user_id) values ('demo-a', '10000000-0000-0000-0000-000000000001');
insert into public.broker_profiles(id, user_id, alias, mode) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'demo-a', 'demo');
insert into public.conditions(id, user_id, profile_id, seq, name) values
  ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '0', 'A'),
  ('40000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'B');
insert into public.strategies(id, user_id, profile_id, name) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Intersection'),
  ('30000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Difference'),
  ('30000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Union'),
  ('30000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'Symmetric');

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
select public.create_strategy_version('30000000-0000-0000-0000-000000000001',
  '{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000001","expr":{"type":"and","children":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]}}');
select public.create_strategy_version('30000000-0000-0000-0000-000000000002',
  '{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000001","expr":{"type":"exclude","base":{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},"subtract":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]}}');
select public.create_strategy_version('30000000-0000-0000-0000-000000000003',
  '{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000001","expr":{"type":"or","children":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]}}');
-- Nested: (A or B) except (A and B), which exercises every operator and the
-- recursion below the top level.
select public.create_strategy_version('30000000-0000-0000-0000-000000000004',
  '{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000001","expr":{"type":"exclude","base":{"type":"or","children":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]},"subtract":[{"type":"and","children":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]}]}}');
reset role;

-- A: 000111 and 000222. B: 000222 and 000333.
-- `A and B` therefore yields 000222, and `A except B` yields 000111.
create function pg_temp.members(p_codes text[]) returns jsonb language sql as $MEMBERS$
  select coalesce(jsonb_agg(jsonb_build_object(
    'code', code, 'raw_code', 'A' || code, 'instrument_type', 'stock',
    'name', 'N' || code, 'price', 1000, 'change_rate', '1.00')), '[]'::jsonb)
  from unnest(p_codes) as code
$MEMBERS$;

create function pg_temp.payload(p_results jsonb) returns jsonb language sql as $PAYLOAD$
  select jsonb_build_object(
    'window_start', '2026-10-23T00:00:00Z', 'window_end', '2026-10-23T00:00:01Z',
    'market_phase', 'weekend', 'excluded_codes', '[]'::jsonb, 'results', p_results,
    'snapshots', jsonb_build_array(
      jsonb_build_object('condition_id', '40000000-0000-0000-0000-000000000001', 'seq', '0', 'name', 'A',
        'started_at', '2026-10-23T00:00:00Z', 'completed_at', '2026-10-23T00:00:01Z', 'page_count', 1,
        'members', pg_temp.members(array['000111', '000222'])),
      jsonb_build_object('condition_id', '40000000-0000-0000-0000-000000000002', 'seq', '1', 'name', 'B',
        'started_at', '2026-10-23T00:00:00Z', 'completed_at', '2026-10-23T00:00:01Z', 'page_count', 1,
        'members', pg_temp.members(array['000222', '000333']))))
$PAYLOAD$;

create function pg_temp.queue(p_strategy uuid) returns uuid language plpgsql as $QUEUE$
declare run_id uuid;
begin
  insert into public.runs(user_id, kind, profile_id, strategy_id, strategy_version_id, status, idempotency_key)
  select '10000000-0000-0000-0000-000000000001', 'search', '20000000-0000-0000-0000-000000000001',
    s.id, s.current_version_id, 'queued', gen_random_uuid()
  from public.strategies s where s.id = p_strategy returning id into run_id;
  return run_id;
end $QUEUE$;

create function pg_temp.claim() returns void language plpgsql as $CLAIM$
begin
  perform set_config('test.owner',
    worker.claim_next_run('w1', array['demo-a'], 60)->>'lease_owner', true);
end $CLAIM$;

-- `A and B`
select set_config('test.run', pg_temp.queue('30000000-0000-0000-0000-000000000001')::text, true);
set local role kiwoom_worker;
select pg_temp.claim();
select throws_ok(
  $$select worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000111","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]}]'))$$,
  'P0001', 'PAYLOAD_INVALID', 'a result that does not satisfy the expression is refused');
select throws_ok(
  $$select worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[]'))$$,
  'P0001', 'PAYLOAD_INVALID', 'dropping a code that satisfies the expression is refused');
select throws_ok(
  $$select worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000222","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]}]'))$$,
  'P0001', 'PAYLOAD_INVALID', 'understating which conditions matched a result is refused');
reset role;
select is((select count(*) from public.run_results where run_id = current_setting('test.run')::uuid), 0::bigint,
  'a refused payload leaves no results');
set local role kiwoom_worker;
select ok(worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000222","matched_condition_ids":["40000000-0000-0000-0000-000000000001","40000000-0000-0000-0000-000000000002"]}]')),
  'the intersection payload the expression implies is accepted');
reset role;
select is((select array_agg(code order by code) from public.run_results where run_id = current_setting('test.run')::uuid),
  array['000222'], 'only the intersection is stored');

-- `A except B`
select set_config('test.run', pg_temp.queue('30000000-0000-0000-0000-000000000002')::text, true);
set local role kiwoom_worker;
select pg_temp.claim();
select throws_ok(
  $$select worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000111","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]},{"code":"000222","matched_condition_ids":["40000000-0000-0000-0000-000000000001","40000000-0000-0000-0000-000000000002"]}]'))$$,
  'P0001', 'PAYLOAD_INVALID', 'keeping a subtracted code is refused');
select ok(worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000111","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]}]')),
  'the difference payload the expression implies is accepted');
reset role;

-- `A or B`
select set_config('test.run', pg_temp.queue('30000000-0000-0000-0000-000000000003')::text, true);
set local role kiwoom_worker;
select pg_temp.claim();
select ok(worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000111","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]},{"code":"000222","matched_condition_ids":["40000000-0000-0000-0000-000000000001","40000000-0000-0000-0000-000000000002"]},{"code":"000333","matched_condition_ids":["40000000-0000-0000-0000-000000000002"]}]')),
  'the union payload the expression implies is accepted');
reset role;

-- (A or B) except (A and B)
select set_config('test.run', pg_temp.queue('30000000-0000-0000-0000-000000000004')::text, true);
set local role kiwoom_worker;
select pg_temp.claim();
select throws_ok(
  $$select worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000111","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]},{"code":"000222","matched_condition_ids":["40000000-0000-0000-0000-000000000001","40000000-0000-0000-0000-000000000002"]},{"code":"000333","matched_condition_ids":["40000000-0000-0000-0000-000000000002"]}]'))$$,
  'P0001', 'PAYLOAD_INVALID', 'a nested expression still refuses a code its subtraction removes');
select ok(worker.complete_search_run(current_setting('test.run')::uuid, current_setting('test.owner'),
    pg_temp.payload('[{"code":"000111","matched_condition_ids":["40000000-0000-0000-0000-000000000001"]},{"code":"000333","matched_condition_ids":["40000000-0000-0000-0000-000000000002"]}]')),
  'the nested payload the expression implies is accepted');
reset role;

select * from finish();
rollback;
