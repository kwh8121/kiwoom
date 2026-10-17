begin;
select plan(8);

select has_table('public', 'runs', 'runs table exists');
-- Fail immediately on a missing runs relation before preparing dependent fixtures.
select count(*) from public.runs;

insert into auth.users (id, email) values
  ('10000000-0000-0000-0000-000000000001', 'a@example.invalid'),
  ('10000000-0000-0000-0000-000000000002', 'b@example.invalid');
insert into public.broker_profiles (id, user_id, alias, mode, display_name) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'demo-a', 'demo', 'A demo');
insert into public.strategies (id, user_id, profile_id, name) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'A strategy');
insert into public.runs (user_id, kind, profile_id, status, idempotency_key) values
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'queued', '40000000-0000-0000-0000-000000000001');
insert into public.conditions (user_id, profile_id, seq, name) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'original');

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
select is((select count(*) from public.broker_profiles), 0::bigint, 'B cannot see A profiles');
select is((select count(*) from public.strategies), 0::bigint, 'B cannot see A strategies');
select is((select count(*) from public.runs), 0::bigint, 'B cannot see A runs');
select throws_ok($$insert into public.strategies(user_id, profile_id, name) values ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 'x')$$, '42501', null, 'B cannot attach strategy to A profile');
select throws_ok($$update public.conditions set name = 'x'$$, '42501', null, 'name column not updatable');
reset role;
select throws_ok($$insert into public.conditions(user_id, profile_id, seq, name) values ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'dup')$$, '23505', null, 'two active rows with same seq rejected');
select lives_ok($$update public.conditions set is_active = false where seq = '1'; insert into public.conditions(user_id, profile_id, seq, name) values ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'new')$$, 'inactive + active same seq allowed');

select * from finish();
rollback;
