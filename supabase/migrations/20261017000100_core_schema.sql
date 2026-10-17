-- Broker credentials stay outside the database: profiles identify CLI aliases only.
create table public.broker_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  alias text not null check (alias ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  mode text not null check (mode in ('real', 'demo')),
  display_name text,
  last_ok_at timestamptz,
  last_error_code text,
  last_error_message text,
  created_at timestamptz not null default now(),
  unique (user_id, alias)
);

create table public.conditions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  profile_id uuid not null references public.broker_profiles,
  seq text not null,
  name text not null,
  ref_description text,
  is_active boolean not null default true,
  first_seen_at timestamptz not null default now(),
  last_synced_at timestamptz not null default now(),
  deactivated_at timestamptz
);
create unique index conditions_active_profile_seq_key
  on public.conditions (profile_id, seq) where is_active;

create table public.strategies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  profile_id uuid not null references public.broker_profiles,
  name text not null check (char_length(name) between 1 and 100),
  current_version_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);

create table public.strategy_versions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  strategy_id uuid not null references public.strategies on delete cascade,
  version integer not null,
  definition jsonb not null,
  condition_refs jsonb not null,
  created_at timestamptz not null default now(),
  unique (strategy_id, version)
);
alter table public.strategies add constraint strategies_current_version_id_fkey
  foreign key (current_version_id) references public.strategy_versions on delete set null;

create table public.runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  kind text not null check (kind in ('search', 'sync')),
  profile_id uuid not null references public.broker_profiles,
  strategy_id uuid references public.strategies,
  strategy_version_id uuid references public.strategy_versions,
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled')),
  idempotency_key uuid not null,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  lease_owner text,
  lease_expires_at timestamptz,
  attempt integer not null default 0,
  max_attempts integer not null default 3,
  error_code text,
  error_message text,
  window_start timestamptz,
  window_end timestamptz,
  market_phase text check (market_phase in ('pre', 'regular', 'post', 'weekend')),
  compared_run_id uuid references public.runs,
  excluded_codes text[] not null default '{}',
  result_count integer,
  sync_summary jsonb,
  check (kind <> 'search' or strategy_version_id is not null),
  unique (user_id, idempotency_key)
);
create unique index runs_active_profile_key
  on public.runs (profile_id) where status in ('queued', 'running');

create table public.condition_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  run_id uuid not null references public.runs on delete cascade,
  condition_id uuid not null references public.conditions,
  seq text not null,
  name text not null,
  started_at timestamptz,
  completed_at timestamptz,
  page_count integer,
  row_count integer,
  is_complete boolean not null default false,
  error_code text,
  unique (run_id, condition_id)
);

create table public.condition_snapshot_members (
  user_id uuid not null references auth.users on delete cascade,
  snapshot_id uuid not null references public.condition_snapshots on delete cascade,
  code text not null check (code ~ '^[0-9A-Z]{6}$'),
  raw_code text not null,
  instrument_type text not null check (instrument_type in ('stock', 'elw', 'etn')),
  name text,
  price bigint,
  change_rate numeric(8,2),
  primary key (snapshot_id, code)
);

create table public.run_results (
  user_id uuid not null references auth.users on delete cascade,
  run_id uuid not null references public.runs on delete cascade,
  code text not null check (code ~ '^[0-9A-Z]{6}$'),
  name text,
  instrument_type text not null check (instrument_type in ('stock', 'elw', 'etn')),
  matched_condition_ids uuid[] not null default '{}',
  diff text not null check (diff in ('new', 'kept')),
  price bigint,
  change_rate numeric(8,2),
  primary key (run_id, code)
);

create table public.condition_sync_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  profile_id uuid not null references public.broker_profiles,
  run_id uuid not null references public.runs on delete cascade,
  event text not null check (event in ('added', 'removed', 'replaced')),
  seq text not null,
  old_name text,
  new_name text,
  condition_id uuid references public.conditions,
  created_at timestamptz not null default now()
);

create function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
revoke all on function public.set_updated_at() from public, anon, authenticated;
create trigger strategies_set_updated_at
  before update on public.strategies
  for each row execute function public.set_updated_at();

-- Start closed, then expose read access and only the required direct writes.
do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'broker_profiles', 'conditions', 'strategies', 'strategy_versions', 'runs',
    'condition_snapshots', 'condition_snapshot_members', 'run_results', 'condition_sync_events'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on table public.%I from public, anon, authenticated', table_name);
    execute format('grant select on table public.%I to authenticated', table_name);
    execute format(
      'create policy owner_select on public.%I for select to authenticated using (user_id = (select auth.uid()))',
      table_name
    );
    execute format('create index %I on public.%I (user_id)', table_name || '_user_id_idx', table_name);
  end loop;
end;
$$;

grant insert on public.broker_profiles, public.strategies to authenticated;
grant update (display_name) on public.broker_profiles to authenticated;
grant update (name, archived_at) on public.strategies to authenticated;
grant update (ref_description) on public.conditions to authenticated;

create policy owner_insert on public.broker_profiles
  for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy owner_update on public.broker_profiles
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy owner_insert on public.strategies
  for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and exists (
      select 1 from public.broker_profiles
      where broker_profiles.id = strategies.profile_id
        and broker_profiles.user_id = (select auth.uid())
    )
  );
create policy owner_update on public.strategies
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy owner_update on public.conditions
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));
