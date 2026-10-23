begin;
select plan(24);

select has_table('public', 'runs', 'runs table exists');
-- Fail immediately on a missing runs relation before preparing dependent fixtures.
select count(*) from public.runs;

insert into auth.users (id, email) values
  ('10000000-0000-0000-0000-000000000001', 'a@example.invalid'),
  ('10000000-0000-0000-0000-000000000002', 'b@example.invalid');
-- A profile may only use an alias registered to its owner, so the aliases the
-- client-side insert assertions below use must be registered first.
insert into public.broker_alias_owners (alias, user_id) values
  ('demo-a', '10000000-0000-0000-0000-000000000001'),
  ('demo-b', '10000000-0000-0000-0000-000000000002'),
  ('demo-b2', '10000000-0000-0000-0000-000000000002'),
  ('demo-b3', '10000000-0000-0000-0000-000000000002');
insert into public.broker_profiles (id, user_id, alias, mode, display_name) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'demo-a', 'demo', 'A demo');
insert into public.strategies (id, user_id, profile_id, name) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'A strategy');
insert into public.broker_profiles (id, user_id, alias, mode) values
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'demo-b', 'demo');
insert into public.strategy_versions (id, user_id, strategy_id, version, definition, condition_refs) values
  ('50000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 1, '{}', '[]');
insert into public.runs (id, user_id, kind, profile_id, status, idempotency_key) values
  ('50000000-0000-0000-0000-00000000000a', '10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'queued', '40000000-0000-0000-0000-000000000001');
insert into public.conditions (id, user_id, profile_id, seq, name) values
  ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'original');
-- Give every RLS table a row owned by A so B's read isolation can be asserted
-- per table. A policy regression on a table with no fixture row is invisible.
insert into public.condition_snapshots (id, user_id, run_id, condition_id, seq, name) values
  ('60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-00000000000a', '40000000-0000-0000-0000-000000000001', '1', 'original');
insert into public.condition_snapshot_members (user_id, snapshot_id, code, raw_code, instrument_type) values
  ('10000000-0000-0000-0000-000000000001', '60000000-0000-0000-0000-000000000001', '005930', 'A005930', 'stock');
insert into public.run_results (user_id, run_id, code, instrument_type, diff) values
  ('10000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-00000000000a', '005930', 'stock', 'new');
insert into public.condition_sync_events (user_id, profile_id, run_id, event, seq) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-00000000000a', 'added', '1');

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
select is((select count(*) from public.broker_profiles where alias = 'demo-a'), 0::bigint, 'B cannot see A profiles');
select is((select count(*) from public.strategies), 0::bigint, 'B cannot see A strategies');
select is((select count(*) from public.runs), 0::bigint, 'B cannot see A runs');
select is((select count(*) from public.latest_profile_sync_runs), 0::bigint, 'latest sync view inherits the caller RLS');
select is((select count(*) from public.conditions), 0::bigint, 'B cannot see A conditions');
select is((select count(*) from public.strategy_versions), 0::bigint, 'B cannot see A strategy versions');
select is((select count(*) from public.condition_snapshots), 0::bigint, 'B cannot see A condition snapshots');
select is((select count(*) from public.condition_snapshot_members), 0::bigint, 'B cannot see A snapshot members');
select is((select count(*) from public.run_results), 0::bigint, 'B cannot see A run results');
select is((select count(*) from public.condition_sync_events), 0::bigint, 'B cannot see A sync events');
-- Under RLS a cross-user UPDATE silently matches no rows, so assert the count.
-- Target A's rows explicitly: B owns rows of its own by this point, so an
-- unqualified UPDATE would legitimately match them and hide a policy failure.
with updated as (update public.broker_profiles set display_name = 'hijack' where id = '20000000-0000-0000-0000-000000000001' returning 1)
  select is((select count(*) from updated), 0::bigint, 'B cannot rename A profile');
with updated as (update public.strategies set name = 'hijack' where id = '30000000-0000-0000-0000-000000000001' returning 1)
  select is((select count(*) from updated), 0::bigint, 'B cannot rename A strategy');
with updated as (update public.conditions set ref_description = 'hijack' where id = '40000000-0000-0000-0000-000000000001' returning 1)
  select is((select count(*) from updated), 0::bigint, 'B cannot annotate A condition');
select throws_ok($$insert into public.strategies(user_id, profile_id, name) values ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 'x')$$, '42501', null, 'B cannot attach strategy to A profile');
select throws_ok($$update public.conditions set name = 'x'$$, '42501', null, 'name column not updatable');
select throws_ok($$insert into public.strategies(user_id, profile_id, name, current_version_id) values ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'invalid version link', '50000000-0000-0000-0000-000000000001')$$, '42501', null, 'B cannot assign A version during strategy creation');
select lives_ok($$insert into public.strategies(user_id, profile_id, name) values ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'B strategy')$$, 'B can create strategy with own profile and default server fields');
select throws_ok($$insert into public.broker_profiles(user_id, alias, mode, last_ok_at) values ('10000000-0000-0000-0000-000000000002', 'demo-b2', 'demo', now())$$, '42501', null, 'worker health fields not insertable by clients');
select lives_ok($$insert into public.broker_profiles(user_id, alias, mode, display_name) values ('10000000-0000-0000-0000-000000000002', 'demo-b3', 'demo', 'B demo')$$, 'B can create profile with client-owned columns');
reset role;
-- An older profile's latest sync must not be pushed out by a busier profile.
insert into public.runs (user_id, kind, profile_id, status, idempotency_key, requested_at) values
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'succeeded', gen_random_uuid(), now() - interval '2 days'),
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'succeeded', gen_random_uuid(), now() - interval '1 day');
select is((select count(*) from public.latest_profile_sync_runs where profile_id = '20000000-0000-0000-0000-000000000001'), 1::bigint, 'latest sync view returns one row per profile');
select is((select requested_at from public.latest_profile_sync_runs where profile_id = '20000000-0000-0000-0000-000000000001') > now() - interval '2 hours', true, 'latest sync view picks the newest run');
select throws_ok($$insert into public.conditions(user_id, profile_id, seq, name) values ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'dup')$$, '23505', null, 'two active rows with same seq rejected');
select lives_ok($$update public.conditions set is_active = false where seq = '1'; insert into public.conditions(user_id, profile_id, seq, name) values ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'new')$$, 'inactive + active same seq allowed');

select * from finish();
rollback;
