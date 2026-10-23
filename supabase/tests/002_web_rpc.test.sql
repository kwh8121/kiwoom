begin;
select plan(17);

insert into auth.users (id, email) values
 ('10000000-0000-0000-0000-000000000001', 'rpc-a@example.invalid'),
 ('10000000-0000-0000-0000-000000000002', 'rpc-b@example.invalid');
insert into public.broker_profiles (id, user_id, alias, mode) values
 ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'rpc-a', 'demo'),
 ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', 'rpc-other', 'demo');
insert into public.strategies (id, user_id, profile_id, name) values
 ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'RPC strategy');
insert into public.conditions (id, user_id, profile_id, seq, name) values
 ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '1', 'A'),
 ('40000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '2', 'B'),
 ('40000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000002', '3', 'Other');
select set_config('test.definition', '{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000001","expr":{"type":"and","children":[{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000001"},{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}]}}', true);
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000001","role":"authenticated"}', true);

select is((public.create_strategy_version('30000000-0000-0000-0000-000000000001'::uuid, current_setting('test.definition')::jsonb)).version, 1, 'first version is 1');
select is((select condition_refs from public.strategy_versions where strategy_id = '30000000-0000-0000-0000-000000000001'), '[{"conditionId":"40000000-0000-0000-0000-000000000001","seq":"1","name":"A"},{"conditionId":"40000000-0000-0000-0000-000000000002","seq":"2","name":"B"}]'::jsonb, 'refs captured in DFS order');
select throws_ok($$select public.create_strategy_version('30000000-0000-0000-0000-000000000001', jsonb_set(current_setting('test.definition')::jsonb, '{expr,children,1,conditionId}', '"40000000-0000-0000-0000-000000000003"'))$$, 'P0001', 'PROFILE_MISMATCH');
select throws_ok($$select public.create_strategy_version('30000000-0000-0000-0000-000000000001', jsonb_set(current_setting('test.definition')::jsonb, '{exchange}', '"A"'))$$, 'P0001', 'INVALID_DEFINITION');
reset role;
-- Privileged mutation reaches the trigger; web clients have no UPDATE grant.
select throws_ok($$update public.strategy_versions set version = 9$$, 'P0001', 'VERSION_IMMUTABLE');
set local role authenticated;
select is((public.request_run('search', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001')).id, (public.request_run('search', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001')).id, 'same key returns same run');
select throws_ok($$select public.request_run('search', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000002')$$, 'P0001', 'PROFILE_BUSY');
select is((public.cancel_run((select id from public.runs where idempotency_key = '50000000-0000-0000-0000-000000000001'))).status, 'cancelled', 'queued run cancellable');
reset role;
update public.conditions set is_active = false where seq = '2';
set local role authenticated;
select throws_ok($$select public.request_run('search', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000003')$$, 'P0001', 'CONDITION_INACTIVE');
select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
select throws_ok($$select public.request_run('search', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000004')$$, 'P0001', 'NOT_FOUND');

-- Denial paths. Each RPC is SECURITY DEFINER, so an ownership or state
-- regression here would be invisible to the owner-side assertions above.
-- Still acting as user B, who owns nothing in this fixture.
select throws_ok($$select public.create_strategy_version('30000000-0000-0000-0000-000000000001', current_setting('test.definition')::jsonb)$$, 'P0001', 'NOT_FOUND', 'B cannot add a version to A strategy');
select throws_ok($$select public.cancel_run((select id from public.runs where idempotency_key = '50000000-0000-0000-0000-000000000001'))$$, 'P0001', 'NOT_FOUND', 'B cannot cancel A run');
select throws_ok($$select public.cancel_run('60000000-0000-0000-0000-00000000000f')$$, 'P0001', 'NOT_FOUND', 'cancelling an unknown run is not found');

select set_config('request.jwt.claims', '{"sub":"10000000-0000-0000-0000-000000000001","role":"authenticated"}', true);
-- An already-cancelled run is terminal, so cancelling it again must be refused.
select throws_ok($$select public.cancel_run((select id from public.runs where idempotency_key = '50000000-0000-0000-0000-000000000001'))$$, 'P0001', 'RUN_NOT_CANCELLABLE', 'a cancelled run cannot be cancelled again');
select throws_ok($$select public.create_strategy_version('30000000-0000-0000-0000-000000000001', jsonb_set(current_setting('test.definition')::jsonb, '{expr,children,1,conditionId}', '"40000000-0000-0000-0000-00000000000f"'))$$, 'P0001', 'CONDITION_INACTIVE', 'an unknown condition id is refused');
-- seq 2 was deactivated above, so a version referencing it must be refused.
select throws_ok($$select public.create_strategy_version('30000000-0000-0000-0000-000000000001', current_setting('test.definition')::jsonb)$$, 'P0001', 'CONDITION_INACTIVE', 'an inactive condition is refused');
reset role;
update public.strategies set archived_at = now() where id = '30000000-0000-0000-0000-000000000001';
update public.conditions set is_active = true, deactivated_at = null where seq = '2';
set local role authenticated;
select throws_ok($$select public.create_strategy_version('30000000-0000-0000-0000-000000000001', current_setting('test.definition')::jsonb)$$, 'P0001', 'NOT_FOUND', 'an archived strategy takes no new version');

select * from finish();
rollback;
