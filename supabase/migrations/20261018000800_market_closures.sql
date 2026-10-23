-- market_phase is computed from the clock alone, so a weekday the exchange was
-- closed is classified `regular` and the "after market close" caveat on a run
-- disappears exactly when the data is most likely stale.
--
-- The worker cannot answer this: its API allowlist is the Kiwoom condition
-- endpoints, and CNSRLST carries no trading-day marker. KRX publishes the
-- closure calendar once a year, so the operator records it here. Nothing
-- outside this table is consulted, and no runtime call is added.
create table public.market_closures (
  closed_on date primary key,
  note text,
  created_at timestamptz not null default now()
);
alter table public.market_closures enable row level security;
revoke all on table public.market_closures from public, anon, authenticated, kiwoom_worker;
grant select on table public.market_closures to authenticated;
-- Exchange closures are public market facts, not per-user data, so every
-- signed-in user reads the same rows. Writing is an operator step, so there is
-- deliberately no insert, update or delete grant.
create policy authenticated_read on public.market_closures
  for select to authenticated using (true);

-- A year with no rows means the calendar was never filled for that year. The
-- app treats that as unknown and keeps warning, so an unmaintained calendar
-- produces extra caveats rather than false confidence.
comment on table public.market_closures is
  'Operator-maintained KRX non-trading dates. A year with no rows is treated as uncovered.';
