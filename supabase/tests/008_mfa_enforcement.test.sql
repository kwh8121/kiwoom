begin;
select plan(9);

-- Supabase issues an aal1 session for a correct password alone, and that
-- session's token can call PostgREST directly. Gating only the web routes
-- would leave MFA decorative, so the row policies and the web RPCs are what
-- require the second factor. A user who has not enrolled must be unaffected,
-- or shipping this locks the operator out of their own data.
select has_function('public', 'mfa_satisfied', '{}'::text[],
  'the database can tell whether this session met the user''s factor requirement');

insert into auth.users(id, email) values
  ('10000000-0000-0000-0000-000000000001', 'plain@example.invalid'),
  ('10000000-0000-0000-0000-000000000002', 'enrolled@example.invalid');
insert into public.broker_alias_owners(alias, user_id) values
  ('demo-plain', '10000000-0000-0000-0000-000000000001'),
  ('demo-mfa', '10000000-0000-0000-0000-000000000002');
insert into public.broker_profiles(id, user_id, alias, mode) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'demo-plain', 'demo'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'demo-mfa', 'demo');
insert into public.conditions(id, user_id, profile_id, seq, name) values
  ('40000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', '0', 'A');
insert into public.strategies(id, user_id, profile_id, name) values
  ('30000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'MFA strategy');
-- Only the second user enrolled a factor.
insert into auth.mfa_factors(id, user_id, friendly_name, factor_type, status, created_at, updated_at)
  values ('70000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002',
          'phone authenticator', 'totp', 'verified', now(), now());

set local role authenticated;

-- A user with no factor is untouched, whatever the session's assurance level.
select set_config('request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000001","role":"authenticated","aal":"aal1"}', true);
select is((select count(*) from public.broker_profiles), 1::bigint,
  'a user who never enrolled reads their rows at aal1');

-- The enrolled user at aal1 has a password-only session.
select set_config('request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated","aal":"aal1"}', true);
select is((select count(*) from public.broker_profiles), 0::bigint,
  'an enrolled user reads nothing from a password-only session');
select is((select count(*) from public.conditions), 0::bigint,
  'the row policies hold for every owned table, not just profiles');
select throws_ok(
  $$select public.request_run('sync','20000000-0000-0000-0000-000000000002',null,gen_random_uuid())$$,
  'P0001', 'MFA_REQUIRED', 'a password-only session cannot request a run');
select throws_ok(
  $$select public.create_strategy_version('30000000-0000-0000-0000-000000000002','{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000002","expr":{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}}')$$,
  'P0001', 'MFA_REQUIRED', 'a password-only session cannot save a strategy version');
select throws_ok(
  $$select public.cancel_run(gen_random_uuid())$$,
  'P0001', 'MFA_REQUIRED', 'a password-only session cannot cancel a run');

-- The same user after presenting the second factor.
select set_config('request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated","aal":"aal2"}', true);
select is((select count(*) from public.broker_profiles), 1::bigint,
  'the second factor restores access to their own rows');
select lives_ok(
  $$select public.create_strategy_version('30000000-0000-0000-0000-000000000002','{"schemaVersion":1,"exchange":"K","profileId":"20000000-0000-0000-0000-000000000002","expr":{"type":"condition","conditionId":"40000000-0000-0000-0000-000000000002"}}')$$,
  'the second factor restores the web RPCs');

reset role;
select * from finish();
rollback;
