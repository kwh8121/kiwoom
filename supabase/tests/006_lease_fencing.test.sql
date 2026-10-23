begin;
select plan(6);

-- locked_run identified the holder by KIWOOM_WORKER_ID alone. Two processes
-- sharing that id are indistinguishable: the one whose lease expired can still
-- extend and settle the run the other now holds, and its own keepalive never
-- notices the loss because the id still matches. Issue a distinct lease owner
-- per claim so the holder of a superseded lease is told apart from the current
-- one even when both run under the same worker id.
grant kiwoom_worker to postgres;
grant usage on schema extensions to kiwoom_worker;

insert into auth.users(id, email) values ('10000000-0000-0000-0000-000000000001', 'fence@example.invalid');
insert into public.broker_alias_owners(alias, user_id) values ('demo-a', '10000000-0000-0000-0000-000000000001');
insert into public.broker_profiles(id, user_id, alias, mode) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'demo-a', 'demo');
insert into public.runs(user_id, kind, profile_id, status, idempotency_key) values
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'queued',
   '40000000-0000-0000-0000-000000000001');
select set_config('test.run', (select id from public.runs limit 1)::text, true);

set local role kiwoom_worker;
select set_config('test.first',
  worker.claim_next_run('shared', array['demo-a'], 60)->>'lease_owner', true);
reset role;

select isnt(current_setting('test.first'), 'shared', 'the claim issues its own lease owner');

-- The first process stalls past its lease, and a second one with the same id
-- picks the run up.
update public.runs set lease_expires_at = clock_timestamp() - interval '1 second'
  where id = current_setting('test.run')::uuid;

set local role kiwoom_worker;
select set_config('test.second',
  worker.claim_next_run('shared', array['demo-a'], 60)->>'lease_owner', true);
reset role;

select isnt(current_setting('test.second'), current_setting('test.first'),
  'reclaiming under the same worker id issues a different lease owner');

set local role kiwoom_worker;
select ok(not worker.extend_lease(current_setting('test.run')::uuid, current_setting('test.first'), 60),
  'a superseded lease owner cannot extend the lease');
select is(worker.complete_sync_run(current_setting('test.run')::uuid, current_setting('test.first'),
  '[{"seq":"0","name":"A"}]'), 'false'::jsonb, 'a superseded lease owner cannot complete the run');
select is(worker.fail_run(current_setting('test.run')::uuid, current_setting('test.first'),
  'RATE_LIMITED', 'stale', true, '[]'), null::text, 'a superseded lease owner cannot fail the run');
select isnt(worker.complete_sync_run(current_setting('test.run')::uuid, current_setting('test.second'),
  '[{"seq":"0","name":"A"}]'), 'false'::jsonb, 'the current lease owner settles the run');
reset role;

select * from finish();
rollback;
