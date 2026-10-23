begin;
select plan(71);

-- Missing the worker schema is the intended initial RED, before role setup.
select is(worker.claim_next_run('w1', array['other'], 60), null::jsonb, 'empty queue returns null');
-- PostgreSQL 17 role creators do not automatically get SET membership.
-- The test runner's temporary grant is rolled back with all test fixtures.
grant kiwoom_worker to postgres;
grant usage on schema extensions to kiwoom_worker;
-- Settlement is fenced to the lease owner each claim issues, not to the worker
-- id, so every claim that is later settled has to record what it was given.
create function pg_temp.claim(p_worker text, p_aliases text[], p_lease int) returns jsonb
language plpgsql as $CLAIM$
declare claimed jsonb;
begin
  claimed := worker.claim_next_run(p_worker, p_aliases, p_lease);
  perform set_config('test.owner', coalesce(claimed->>'lease_owner', ''), true);
  return claimed;
end $CLAIM$;

insert into auth.users(id,email) values ('10000000-0000-0000-0000-000000000001','worker@example.invalid');
-- claim_next_run resolves a run only when the alias is registered to the owner.
insert into public.broker_alias_owners(alias,user_id) values
 ('demo-a','10000000-0000-0000-0000-000000000001');
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
-- A lease blocks its profile for its whole duration, so an absurd one is refused.
select throws_ok($$select worker.claim_next_run('w1',array['demo-a'],901)$$,null,'PAYLOAD_INVALID','lease above the cap rejected at claim');
select throws_ok($$select worker.claim_next_run('w1',array['demo-a'],0)$$,null,'PAYLOAD_INVALID','non-positive lease rejected at claim');
select is(worker.claim_next_run('w1',array['other'],60),null::jsonb,'alias filter skips a queued run for another profile');
select is(pg_temp.claim('w1',array['demo-a'],60)->>'kind','search','claims queued search run');
select is(worker.claim_next_run('w2',array['demo-a'],60),null::jsonb,'running run not double-claimed');
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,'w2',current_setting('test.payload')::jsonb),'non-owner cannot complete');
reset role;
select is((select count(*) from public.run_results where run_id=current_setting('test.run')::uuid),0::bigint,'nothing written by non-owner');
set local role kiwoom_worker;
select ok(worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),current_setting('test.payload')::jsonb),'owner completes');
reset role;
select is((select diff from public.run_results where run_id=current_setting('test.run')::uuid),'new','first run diff is new');
set local role authenticated;
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),current_setting('test.payload')::jsonb);
reset role;
select is((select diff from public.run_results where run_id=current_setting('test.run')::uuid),'kept','second run diff is kept');
set local role authenticated;
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select ok(worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),jsonb_set(jsonb_set(current_setting('test.payload')::jsonb,'{snapshots,1,members}','[]'),'{results}','[]')),'a search whose conditions share nothing succeeds with no results');
reset role;
select is((select result_count from public.runs where id=current_setting('test.run')::uuid),0,'zero count recorded');
set local role authenticated;
select set_config('test.run',(public.request_run('search','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select is(worker.fail_run(current_setting('test.run')::uuid,current_setting('test.owner'),'RATE_LIMITED','Retry later',true,'[]'),'queued','retryable requeues');
set local role authenticated;
select public.cancel_run(current_setting('test.run')::uuid);
select set_config('test.run',(public.request_run('sync','20000000-0000-0000-0000-000000000001',null,gen_random_uuid())).id::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select is(worker.complete_sync_run(current_setting('test.run')::uuid,current_setting('test.owner'),'[{"seq":"0","name":"A"},{"seq":"1","name":"B2"}]')->>'replaced','1','renamed seq recorded as replaced');

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
select is(pg_temp.claim('w1',array['demo-a'],60)->'profile'->>'alias','demo-a','claim includes profile contract');
select ok(not worker.extend_lease(current_setting('test.run')::uuid,'w2',60),'non-owner cannot extend');
select ok(worker.extend_lease(current_setting('test.run')::uuid,current_setting('test.owner'),60),'owner extends lease');
select throws_ok($$select worker.extend_lease(current_setting('test.run')::uuid,current_setting('test.owner'),901)$$,null,'PAYLOAD_INVALID','lease above the cap rejected at extend');
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),current_setting('test.payload')::jsonb #- '{snapshots,1}')$$,'P0001','PAYLOAD_INVALID','every leaf snapshot is required');
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),jsonb_set(current_setting('test.payload')::jsonb,'{results,0,code}','"000001"'))$$,'P0001','PAYLOAD_INVALID','result must exist in matched snapshots');
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),jsonb_set(current_setting('test.payload')::jsonb,'{snapshots,0,is_complete}','false'))$$,'P0001','PAYLOAD_INVALID','incomplete snapshot cannot succeed');
reset role;
insert into auth.users(id,email) values ('10000000-0000-0000-0000-000000000002','worker-other@example.invalid');
insert into public.broker_alias_owners(alias,user_id) values ('demo-other','10000000-0000-0000-0000-000000000002');
insert into public.broker_profiles(id,user_id,alias,mode) values ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','demo-other','demo');
insert into public.conditions(id,user_id,profile_id,seq,name) values ('40000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','0','A');
set local role kiwoom_worker;
select throws_ok($$select worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),jsonb_set(current_setting('test.payload')::jsonb,'{snapshots,0,condition_id}','"40000000-0000-0000-0000-000000000003"'))$$,'P0001','PAYLOAD_INVALID','other-user condition is rejected');
reset role;
select is((select count(*) from public.condition_snapshots where run_id=current_setting('test.run')::uuid),0::bigint,'invalid payload rolls back snapshots');
set local role kiwoom_worker;
select is(worker.fail_run(current_setting('test.run')::uuid,'w2','RATE_LIMITED','Retry',true,'[]'),null::text,'non-owner cannot fail');
select is(worker.fail_run(current_setting('test.run')::uuid,current_setting('test.owner'),'RATE_LIMITED','Retry',true,
 '[{"condition_id":"40000000-0000-0000-0000-000000000001","seq":"0","name":"A","started_at":"2026-10-18T00:00:00Z","completed_at":"2026-10-18T00:00:01Z","page_count":1,"row_count":4,"error_code":"RATE_LIMITED","members":[{"code":"0010F0"}]}]'),'queued','retry records partial metadata');
reset role;
select ok((select not is_complete and page_count=1 and row_count=4 and error_code='RATE_LIMITED' from public.condition_snapshots where run_id=current_setting('test.run')::uuid),'partial snapshot is incomplete with counts');
select is((select count(*) from public.condition_snapshot_members m join public.condition_snapshots s on s.id=m.snapshot_id where s.run_id=current_setting('test.run')::uuid),0::bigint,'partial payload never stores members');
-- A requeued run waits out its retry backoff before it can be claimed again.
-- Standing in for the wall clock so the lease-expiry cases below stay focused.
update public.runs set retry_after=null where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
reset role;
update public.runs set lease_expires_at=clock_timestamp()-interval '1 second' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),current_setting('test.payload')::jsonb),'expired owner cannot complete');
select ok(not worker.extend_lease(current_setting('test.run')::uuid,current_setting('test.owner'),60),'expired owner cannot revive lease');
select is(pg_temp.claim('w2',array['demo-a'],60)->>'attempt','3','expired attempt is reclaimed with increment');
select is(worker.fail_run(current_setting('test.run')::uuid,current_setting('test.owner'),'RATE_LIMITED','Exhausted',true,'[]'),'failed','retry exhaustion is terminal');
reset role;
select is((select last_error_code from public.broker_profiles where alias='demo-a'),'RATE_LIMITED','profile records failure code');
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select is(worker.fail_run(current_setting('test.run')::uuid,current_setting('test.owner'),'RUN_TIMEOUT','Timeout',false,'[]'),'timed_out','timeout gets distinct terminal status');
reset role;
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
reset role;
update public.runs set attempt=max_attempts,lease_expires_at=clock_timestamp()-interval '1 second' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select pg_temp.claim('w2',array['demo-a'],60);
reset role;
select ok((select status='failed' and error_code='LEASE_EXPIRED' and lease_owner is null from public.runs where id=current_setting('test.run')::uuid),'expired exhausted lease fails and releases ownership');
select set_config('test.run',pg_temp.queue_run('sync')::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select is(worker.complete_sync_run(current_setting('test.run')::uuid,'w2','[]'),'false'::jsonb,'non-owner sync returns false');
select throws_ok($$select worker.complete_sync_run(current_setting('test.run')::uuid,current_setting('test.owner'),'[{"seq":"0","name":"A"},{"seq":"0","name":"B"}]')$$,'P0001','PAYLOAD_INVALID','duplicate sync seq rejected atomically');
reset role;
select is((select count(*) from public.conditions where is_active and profile_id='20000000-0000-0000-0000-000000000001'),2::bigint,'failed sync attempts leave active conditions intact');
set local role kiwoom_worker;
select throws_ok($$select worker.complete_sync_run(current_setting('test.run')::uuid,current_setting('test.owner'),'[]')$$,'P0001','CONDITION_LIST_EMPTY','empty list refused while conditions are active');
reset role;
select is((select count(*) from public.conditions where is_active and profile_id='20000000-0000-0000-0000-000000000001'),2::bigint,'refused empty list leaves every condition active');
-- Dropping one of two conditions is a real removal, not a wholesale wipe.
select set_config('test.revived',(select id::text from public.conditions where profile_id='20000000-0000-0000-0000-000000000001' and seq='1' and name='B2' and is_active),true);
set local role kiwoom_worker;
select is(worker.complete_sync_run(current_setting('test.run')::uuid,current_setting('test.owner'),'[{"seq":"0","name":"A"}]')->>'removed','1','partial list still deactivates the dropped condition');
reset role;
-- A condition that comes back must regain its old id, or every strategy
-- version referencing it stays permanently unusable.
select set_config('test.run',pg_temp.queue_run('sync')::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select is(worker.complete_sync_run(current_setting('test.run')::uuid,current_setting('test.owner'),'[{"seq":"0","name":"A"},{"seq":"1","name":"B2"}]')->>'added','1','a returning condition is reported as added');
reset role;
select is((select id::text from public.conditions where profile_id='20000000-0000-0000-0000-000000000001' and seq='1' and is_active),current_setting('test.revived'),'revived condition keeps its original identity');
select is((select count(*) from public.conditions where profile_id='20000000-0000-0000-0000-000000000001' and seq='1'),2::bigint,'reviving does not mint another row');
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
select ok(worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),jsonb_set(jsonb_set(current_setting('test.payload')::jsonb,'{results,0,matched_condition_ids}','["40000000-0000-0000-0000-000000000002","40000000-0000-0000-0000-000000000001"]'),'{snapshots,0,user_id}','"10000000-0000-0000-0000-000000000002"')),'worker-supplied user_id does not control ownership');
reset role;
select is((select name from public.run_results where run_id=current_setting('test.run')::uuid),'Second','matched id order controls result display');
select is((select count(*) from public.condition_snapshots where user_id='10000000-0000-0000-0000-000000000002'),0::bigint,'no wrong-user snapshot was created');
select is((select raw_code from public.condition_snapshot_members m join public.condition_snapshots s on s.id=m.snapshot_id where s.run_id=current_setting('test.run')::uuid limit 1),'A0010F0','raw code retained');
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
reset role;
create function pg_temp.delay_snapshot() returns trigger language plpgsql as $$ begin perform pg_sleep(0.05); return new; end $$;
create trigger task3_expiry_probe before insert on public.condition_snapshots for each row execute function pg_temp.delay_snapshot();
update public.runs set lease_expires_at=clock_timestamp()+interval '0.02 seconds' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),current_setting('test.payload')::jsonb),'lease expiry during writes rolls back completion');
reset role;
select is((select count(*) from public.condition_snapshots where run_id=current_setting('test.run')::uuid),0::bigint,'lost lease leaves no snapshot writes');
select is((select count(*) from public.run_results where run_id=current_setting('test.run')::uuid),0::bigint,'lost lease leaves no result writes');
update public.runs set status='cancelled',finished_at=clock_timestamp(),lease_owner=null,lease_expires_at=null where id=current_setting('test.run')::uuid;
drop trigger task3_expiry_probe on public.condition_snapshots;
create function pg_temp.delay_profile_update() returns trigger language plpgsql as $$ begin perform pg_sleep(0.05); return new; end $$;
create trigger task3_profile_expiry_probe before update on public.broker_profiles for each row execute function pg_temp.delay_profile_update();
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
reset role;
update public.runs set lease_expires_at=clock_timestamp()+interval '0.02 seconds' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select ok(not worker.complete_search_run(current_setting('test.run')::uuid,current_setting('test.owner'),current_setting('test.payload')::jsonb),'profile write expiry rolls back search settlement');
reset role;
select is((select status from public.runs where id=current_setting('test.run')::uuid),'running','search settlement expiry leaves run running');
select is((select count(*) from public.run_results where run_id=current_setting('test.run')::uuid),0::bigint,'search settlement expiry leaves no result writes');
select is((select count(*) from public.condition_snapshots where run_id=current_setting('test.run')::uuid),0::bigint,'search settlement expiry leaves no snapshot writes');
update public.runs set status='cancelled',finished_at=clock_timestamp(),lease_owner=null,lease_expires_at=null where id=current_setting('test.run')::uuid;
select set_config('test.run',pg_temp.queue_run('sync')::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
reset role;
update public.runs set lease_expires_at=clock_timestamp()+interval '0.02 seconds' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select is(worker.complete_sync_run(current_setting('test.run')::uuid,current_setting('test.owner'),'[{"seq":"0","name":"A"},{"seq":"1","name":"B2"}]'),'false'::jsonb,'profile write expiry rolls back sync settlement');
reset role;
select is((select status from public.runs where id=current_setting('test.run')::uuid),'running','sync settlement expiry leaves run running');
select is((select count(*) from public.condition_sync_events where run_id=current_setting('test.run')::uuid),0::bigint,'sync settlement expiry leaves no sync events');
update public.runs set status='cancelled',finished_at=clock_timestamp(),lease_owner=null,lease_expires_at=null where id=current_setting('test.run')::uuid;
select set_config('test.run',pg_temp.queue_run()::text,true);
set local role kiwoom_worker;
select pg_temp.claim('w1',array['demo-a'],60);
reset role;
update public.runs set lease_expires_at=clock_timestamp()+interval '0.02 seconds' where id=current_setting('test.run')::uuid;
set local role kiwoom_worker;
select is(worker.fail_run(current_setting('test.run')::uuid,current_setting('test.owner'),'RUN_TIMEOUT','Timeout',false,'[]'),null,'profile write expiry rolls back fail settlement');
reset role;
select is((select status from public.runs where id=current_setting('test.run')::uuid),'running','fail settlement expiry leaves run running');
select is((select last_error_code from public.broker_profiles where alias='demo-a'),null,'fail settlement expiry leaves profile error unchanged');
update public.runs set status='cancelled',finished_at=clock_timestamp(),lease_owner=null,lease_expires_at=null where id=current_setting('test.run')::uuid;
select * from finish();
rollback;
