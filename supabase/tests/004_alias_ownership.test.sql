begin;
select plan(14);

-- A worker process holds the real broker credentials for an alias. Nothing bound
-- an alias to one owner, so a second account could register a profile with the
-- operator's alias and have the operator's worker run searches on its behalf.
select has_table('public', 'broker_alias_owners', 'alias ownership registry exists');

-- PostgreSQL 17 role creators do not automatically get SET membership.
grant kiwoom_worker to postgres;
grant usage on schema extensions to kiwoom_worker;

insert into auth.users(id, email) values
  ('10000000-0000-0000-0000-000000000001', 'a@example.invalid'),
  ('10000000-0000-0000-0000-000000000002', 'b@example.invalid');

insert into public.broker_alias_owners(alias, user_id) values
  ('own-a', '10000000-0000-0000-0000-000000000001'),
  ('op-real', '10000000-0000-0000-0000-000000000001'),
  ('own-b', '10000000-0000-0000-0000-000000000002'),
  ('own-b2', '10000000-0000-0000-0000-000000000002');

insert into public.broker_profiles(id, user_id, alias, mode) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'own-a', 'demo'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'own-b', 'demo'),
  -- A row that predates the policy: B holds a profile for the operator's alias.
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', 'op-real', 'demo'),
  -- A profile whose alias was never registered to anyone.
  ('20000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000001', 'ungranted', 'demo');

insert into public.runs(user_id, kind, profile_id, status, idempotency_key) values
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'queued', '40000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000002', 'sync', '20000000-0000-0000-0000-000000000003', 'queued', '40000000-0000-0000-0000-000000000002'),
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000004', 'queued', '40000000-0000-0000-0000-000000000003');

select throws_ok(
  $$insert into public.broker_profiles(user_id, alias, mode) values ('10000000-0000-0000-0000-000000000002', 'own-a', 'demo')$$,
  '23505', null, 'two profiles cannot share one alias');

-- The worker resolves work by alias, so the alias must carry its owner.
set local role kiwoom_worker;
select worker.heartbeat('w-a', array['own-a'], '1');
select worker.heartbeat('w-shared', array['own-a', 'own-b'], '1');
select is(worker.claim_next_run('w1', array['ungranted'], 60), null::jsonb,
  'an unregistered alias claims nothing');
select is(worker.claim_next_run('w1', array['op-real'], 60), null::jsonb,
  'an alias registered to another user claims nothing');
select isnt(worker.claim_next_run('w1', array['own-a'], 60), null::jsonb,
  'a registered alias claims its own run');
reset role;

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
select throws_ok(
  $$insert into public.broker_alias_owners(alias, user_id) values ('self-grant', '10000000-0000-0000-0000-000000000002')$$,
  '42501', null, 'clients cannot register an alias');
select throws_ok(
  $$insert into public.broker_profiles(user_id, alias, mode) values ('10000000-0000-0000-0000-000000000002', 'nope-b', 'demo')$$,
  '42501', null, 'a profile needs a registered alias');
select throws_ok(
  $$insert into public.broker_profiles(user_id, alias, mode) values ('10000000-0000-0000-0000-000000000002', 'own-a', 'demo')$$,
  '42501', null, 'B cannot take the alias registered to A');
select lives_ok(
  $$insert into public.broker_profiles(user_id, alias, mode) values ('10000000-0000-0000-0000-000000000002', 'own-b2', 'demo')$$,
  'B can create a profile for an alias registered to B');
select is((select count(*) from public.broker_alias_owners where alias = 'own-a'), 0::bigint,
  'B cannot see the alias registered to A');
select is((select count(*) from public.broker_alias_owners), 2::bigint,
  'B sees only the aliases registered to B');

-- The heartbeat table told every logged-in user which aliases to register.
select is((select count(*) from public.worker_heartbeats where worker_id = 'w-a'), 0::bigint,
  'B cannot see a worker serving only A aliases');
select is((select count(*) from public.worker_heartbeats where worker_id = 'w-shared'), 1::bigint,
  'B sees a worker that serves one of its aliases');
select is((select aliases from public.my_worker_heartbeats where worker_id = 'w-shared'), array['own-b']::text[],
  'the heartbeat view hides aliases B does not own');

select * from finish();
rollback;
