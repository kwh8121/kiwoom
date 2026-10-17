begin;
select plan(53);

-- Missing the worker schema is the intended initial RED, before role setup.
select is(worker.claim_next_run('w1', array['other'], 60), null::jsonb, 'empty queue returns null');
-- PostgreSQL 17 role creators do not automatically get SET membership.
-- The test runner's temporary grant is rolled back with all test fixtures.
grant kiwoom_worker to postgres;
grant usage on schema extensions to kiwoom_worker;

insert into auth.users(id,email) values ('10000000-0000-0000-0000-000000000001','worker@example.invalid');
insert into public.broker_profiles(id,user_id,alias,mode) values
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','demo-a','demo');
insert into public.conditions(id,user_id,profile_id,seq,name) values
 ('40000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','0','A'),
 ('40000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','1','B');
insert into public.strategies(id,user_id,profile_id,name) values
 ('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','Worker strategy');
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"10000000-0000-0000-0000-000000000001","role":"authenticated"}',true);
select public.create_strategy_version('30000000-0000-0000-0000-000000000001',
 '{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000001","expr":{"type":"and","children":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]}}');
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
reset role;
select set_config('test.payload', '{"window_start":"2026-10-18T00:00:00Z","window_end":"2026-10-18T00:00:01Z","market_phase":"weekend","snapshots":[{"condition_id":"40000000-0000-0000-0000-000000000001","seq":"0","name":"A","started_at":"2026-10-18T00:00:00Z","completed_at":"2026-10-18T00:00:01Z","page_count":1,"members":[{"code":"0010F0","raw_code":"A0010F0","instrument_type":"stock","name":"First","price":3195,"change_rate":"6.86"}]},{"condition_id":"40000000-0000-0000-0000-000000000002","seq":"1","name":"B","started_at":"2026-10-18T00:00:00Z","completed_at":"2026-10-18T00:00:01Z","page_count":1,"members":[{"code":"0010F0","raw_code":"A0010F0","instrument_type":"stock","name":"Second","price":3200,"change_rate":"6.90"}]}],"results":[{"code":"0010F0","matched_condition_ids":["40000000-0000-0000-0000-000000000001","40000000-0000-0000-0000-000000000002"]}],"excluded_codes":["000660"]}',true);
set local role kiwoom_worker;
select is(worker.claim_next_run('w1',array['other'],60),null::jsonb,'alias filter skips a queued run for another profile');
select is(worker.claim_next_run('w1',array['demo-a'],60)->>'kind','search','claims queued search run');
select is(worker.claim_next_run('w2',array['demo-a'],60),null::jsonb,'running run not double-claimed');
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,'w2',current_setting('test.payload')::jsonb),'non-owner cannot complete');
reset role;
select is((select count(*) from public.run_results where run_id=current_setting('test.run')::uuid),0::bigint,'nothing written by non-owner');
set local role kiwoom_worker;
select ok(worker.complete_search_run(current_setting('test.run')::uuid,'w1',current_setting('test.payload')::jsonb),'owner completes');
reset role;
select is((select diff from public.run_results where run_id=current_setting('test.run')::uuid),'new','first run diff is new');
set local role authenticated;
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select worker.complete_search_run(current_setting('test.run')::uuid,'w1',current_setting('test.payload')::jsonb);
reset role;
select is((select diff from public.run_results where run_id=current_setting('test.run')::uuid),'kept','second run diff is kept');
set local role authenticated;
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select ok(worker.complete_search_run(current_setting('test.run')::uuid,'w1',jsonb_set(current_setting('test.payload')::jsonb,'{results}','[]')),'empty result succeeds');
reset role;
select is((select result_count from public.runs where id=current_setting('test.run')::uuid),0,'zero count recorded');
set local role authenticated;
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select is(worker.fail_run(current_setting('test.run')::uuid,'w1','RATE_LIMITED','Retry later',true,'[]'),'queued','retryable requeues');
set local role authenticated;
select public.cancel_run(current_setting('test.run')::uuid);
select set_config('test.run',(public.request_run('sync','20000000-0000-0000-0000-000000000001',null,gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select is(worker.complete_sync_run(current_setting('test.run')::uuid,'w1','[{"seq":"0","name":"A"},{"seq":"1","name":"B2"}]')->>'replaced','1','renamed seq recorded as replaced');

-- Focused probes extend the 12 contract cases. Helpers are test-only, rolled
-- back with fixtures, and never installed into the application schema.
reset role;
create function pg_temp.queue_run(kind text default 'search') returns uuid language plpgsql as $$
declare run_id uuid;
begin
 insert into public.runs(user_id,kind,profile_id,strategy_id,strategy_version_id,status,idempotency_key)
 select '10000000-0000-0000-0000-000000000001',kind,'20000000-0000-0000-0000-000000000001',
   case when kind='search' then s.id end,case when kind='search' then s.current_version_id end,'queued',gen_random_uuid()
 from public.strategies s where s.id='30000000-0000-0000-0000-000000000001' returning id into run_id;
 return run_id;
end $$;
select is((select count(*) from public.condition_sync_events where event='added'),0::bigint,'replacement is not double-counted as added');
select is((select count(*) from public.conditions where seq='1' and not is_active),1::bigint,'old condition identity retained inactive');
select is((select name from public.run_results order by run_id limit 1),'First','display fields use first matched snapshot');
set local role authenticated;
select throws_ok($$select worker.claim_next_run('web',array['demo-a'],60)$$,'42501',null,'web cannot call worker schema');
set local role kiwoom_worker;
select throws_ok($$select * from public.runs$$,'42501',null,'worker has no direct table read');
select throws_ok($$select worker.locked_run(gen_random_uuid(),'w1',null)$$,'42501',null,'worker cannot call private helper');
select lives_ok($$select worker.heartbeat('w1',array['demo-a'],'test-v1')$$,'heartbeat writes through RPC');
set local role authenticated;
select is((select version from public.worker_heartbeats where worker_id='w1'),'test-v1','authenticated can read heartbeat');
select throws_ok($$update public.worker_heartbeats set version='forged'$$,'42501',null,'authenticated cannot modify heartbeat');
reset role;
select ok((select not rolsuper and not rolbypassrls and not rolcreaterole and not rolcreatedb from pg_roles where rolname='kiwoom_worker'),'worker cannot bypass its RPC boundary');
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select is(worker.claim_next_run('w1',array['demo-a'],60)->'profile'->>'alias','demo-a','claim includes profile contract');
select ok(not worker.extend_lease(current_setting('test.run')::uuid,'w2',60),'non-owner cannot extend');
select ok(worker.extend_lease(current_setting('test.run')::uuid,'w1',60),'owner extends lease');
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,'w1',current_setting('test.payload')::jsonb #- '{snapshots,1}')$$,'P0001','PAYLOAD_INVALID','every leaf snapshot is required');
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,'w1',jsonb_set(current_setting('test.payload')::jsonb,'{results,0,code}','"000001"'))$$,'P0001','PAYLOAD_INVALID','result must exist in matched snapshots');
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,'w1',jsonb_set(current_setting('test.payload')::jsonb,'{snapshots,0,is_complete}','false'))$$,'P0001','PAYLOAD_INVALID','incomplete snapshot cannot succeed');
reset role;
insert into auth.users(id,email) values ('10000000-0000-0000-0000-000000000002','worker-other@example.invalid');
insert into public.broker_profiles(id,user_id,alias,mode) values ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','demo-other','demo');
insert into public.conditions(id,user_id,profile_id,seq,name) values ('40000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','0','A');
set local role kiwoom_worker;
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,'w1',jsonb_set(current_setting('test.payload')::jsonb,'{snapshots,0,condition_id}','"40000000-0000-0000-0000-000000000003"'))$$,'P0001','PAYLOAD_INVALID','other-user condition is rejected');
reset role;
select is((select count(*) from public.condition_snapshots where run_id=current_setting('test.run')::uuid),0::bigint,'invalid payload rolls back snapshots');
set local role kiwoom_worker;
select is(worker.fail_run(current_setting('test.run')::uuid,'w2','RATE_LIMITED','Retry',true,'[]'),null::text,'non-owner cannot fail');
select is(worker.fail_run(current_setting('test.run')::uuid,'w1','RATE_LIMITED','Retry',true,
 '[{"condition_id":"40000000-0000-0000-0000-000000000001","seq":"0","name":"A","started_at":"2026-10-18T00:00:00Z","completed_at":"2026-10-18T00:00:01Z","page_count":1,"row_count":4,"error_code":"RATE_LIMITED","members":[{"code":"0010F0"}]}]'),'queued','retry records partial metadata');
reset role;
select ok((select not is_complete and page_count=1 and row_count=4 and error_code='RATE_LIMITED' from public.condition_snapshots where run_id=current_setting('test.run')::uuid),'partial snapshot is incomplete with counts');
select is((select count(*) from public.condition_snapshot_members m join public.condition_snapshots s on s.id=m.snapshot_id where s.run_id=current_setting('test.run')::uuid),0::bigint,'partial payload never stores members');
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
reset role;
update public.runs set lease_expires_at=clock_timestamp()-interval '1 second' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,'w1',current_setting('test.payload')::jsonb),'expired owner cannot complete');
select ok(not worker.extend_lease(current_setting('test.run')::uuid,'w1',60),'expired owner cannot revive lease');
select is(worker.claim_next_run('w2',array['demo-a'],60)->>'attempt','3','expired attempt is reclaimed with increment');
select is(worker.fail_run(current_setting('test.run')::uuid,'w2','RATE_LIMITED','Exhausted',true,'[]'),'failed','retry exhaustion is terminal');
reset role;
select is((select last_error_code from public.broker_profiles where alias='demo-a'),'RATE_LIMITED','profile records failure code');
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select is(worker.fail_run(current_setting('test.run')::uuid,'w1','RUN_TIMEOUT','Timeout',false,'[]'),'timed_out','timeout gets distinct terminal status');
reset role;
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
reset role;
update public.runs set attempt=max_attempts,lease_expires_at=clock_timestamp()-interval '1 second' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select worker.claim_next_run('w2',array['demo-a'],60);
reset role;
select ok((select status='failed' and error_code='LEASE_EXPIRED' and lease_owner is null from public.runs where id=current_setting('test.run')::uuid),'expired exhausted lease fails and releases ownership');
select set_config('test.run',pg_temp.queue_run('sync')::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select is(worker.complete_sync_run(current_setting('test.run')::uuid,'w2','[]'),'false'::jsonb,'non-owner sync returns false');
select throws_ok($$select worker.complete_sync_run(current_setting('test.run')::uuid,'w1','[{"seq":"0","name":"A"},{"seq":"0","name":"B"}]')$$,'P0001','PAYLOAD_INVALID','duplicate sync seq rejected atomically');
reset role;
select is((select count(*) from public.conditions where is_active and profile_id='20000000-0000-0000-0000-000000000001'),2::bigint,'failed sync attempts leave active conditions intact');
set local role kiwoom_worker;
select is(worker.complete_sync_run(current_setting('test.run')::uuid,'w1','[]')->>'removed','2','empty sync deactivates removed conditions');
reset role;
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
select ok(worker.complete_search_run(current_setting('test.run')::uuid,'w1',jsonb_set(jsonb_set(current_setting('test.payload')::jsonb,'{results,0,matched_condition_ids}','["40000000-0000-0000-0000-000000000002","40000000-0000-0000-0000-000000000001"]'),'{snapshots,0,user_id}','"10000000-0000-0000-0000-000000000002"')),'worker-supplied user_id does not control ownership');
reset role;
select is((select name from public.run_results where run_id=current_setting('test.run')::uuid),'Second','matched id order controls result display');
select is((select count(*) from public.condition_snapshots where user_id='10000000-0000-0000-0000-000000000002'),0::bigint,'no wrong-user snapshot was created');
select is((select raw_code from public.condition_snapshot_members m join public.condition_snapshots s on s.id=m.snapshot_id where s.run_id=current_setting('test.run')::uuid limit 1),'A0010F0','raw code retained');
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select worker.claim_next_run('w1',array['demo-a'],60);
reset role;
create function pg_temp.delay_snapshot() returns trigger language plpgsql as $$ begin perform pg_sleep(0.05); return new; end $$;
create trigger task3_expiry_probe before insert on public.condition_snapshots for each row execute function pg_temp.delay_snapshot();
update public.runs set lease_expires_at=clock_timestamp()+interval '0.02 seconds' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,'w1',current_setting('test.payload')::jsonb),'lease expiry during writes rolls back completion');
reset role;
select is((select count(*) from public.condition_snapshots where run_id=current_setting('test.run')::uuid),0::bigint,'lost lease leaves no snapshot writes');
select is((select count(*) from public.run_results where run_id=current_setting('test.run')::uuid),0::bigint,'lost lease leaves no result writes');
select * from finish();
rollback;
