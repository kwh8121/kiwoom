begin;
select plan(7);

-- A retryable failure requeued the run with no delay, so claim_next_run picked
-- it up again immediately and all three attempts burned within seconds. The
-- transient condition they were meant to ride out had no time to clear.
select has_column('public', 'runs', 'retry_after', 'runs records when a requeued run may be retried');

grant kiwoom_worker to postgres;
grant usage on schema extensions to kiwoom_worker;

insert into auth.users(id, email) values ('10000000-0000-0000-0000-000000000001', 'backoff@example.invalid');
insert into public.broker_alias_owners(alias, user_id) values ('demo-a', '10000000-0000-0000-0000-000000000001');
insert into public.broker_profiles(id, user_id, alias, mode) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'demo-a', 'demo');
insert into public.runs(user_id, kind, profile_id, status, idempotency_key) values
  ('10000000-0000-0000-0000-000000000001', 'sync', '20000000-0000-0000-0000-000000000001', 'queued',
   '40000000-0000-0000-0000-000000000001');

select set_config('test.run', (select id from public.runs limit 1)::text, true);

select cmp_ok(worker.retry_backoff(1), '<', worker.retry_backoff(2), 'each attempt waits longer than the last');
select is(worker.retry_backoff(99), interval '60 seconds', 'the wait is capped');

set local role kiwoom_worker;
select worker.claim_next_run('w1', array['demo-a'], 60);
select is(worker.fail_run(current_setting('test.run')::uuid, 'w1', 'RATE_LIMITED', 'Retry later', true, '[]'),
  'queued', 'a retryable failure requeues the run');
select is(worker.claim_next_run('w1', array['demo-a'], 60), null::jsonb,
  'a requeued run is not reclaimed before its backoff elapses');
reset role;

select ok((select retry_after > clock_timestamp() from public.runs where id = current_setting('test.run')::uuid),
  'the requeued run carries a future retry time');
-- Standing in for the wall clock moving forward.
update public.runs set retry_after = clock_timestamp() - interval '1 second' where id = current_setting('test.run')::uuid;

set local role kiwoom_worker;
select isnt(worker.claim_next_run('w1', array['demo-a'], 60), null::jsonb,
  'the run is reclaimed once its backoff has elapsed');
reset role;

select * from finish();
rollback;
