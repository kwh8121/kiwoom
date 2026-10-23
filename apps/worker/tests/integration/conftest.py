"""Shared setup for the integration suite.

These live here rather than in one test module because the worker role login is
an autouse fixture: every module in this directory connects as kiwoom_worker,
which the migration leaves NOLOGIN.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from psycopg import AsyncConnection

ADMIN_URL = os.getenv(
    "KIWOOM_WORKER_TEST_ADMIN_URL",
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
)
WORKER_URL = os.getenv(
    "KIWOOM_WORKER_TEST_DATABASE_URL",
    "postgresql://kiwoom_worker:kiwoom-worker-local@127.0.0.1:54322/postgres",
)


async def _create_queued_search() -> tuple[str, str, str, str, str]:
    user_id, profile_id, strategy_id, first_condition_id, second_condition_id = [
        str(uuid4()) for _ in range(5)
    ]
    async with (
        await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin,
        admin.cursor() as cursor,
    ):
        await cursor.execute(
            "insert into auth.users(id,email) values (%s,%s)",
            (user_id, f"{user_id}@example.invalid"),
        )
        # claim_next_run only resolves an alias registered to the profile owner.
        await cursor.execute(
            "insert into public.broker_alias_owners(alias,user_id) values (%s,%s)",
            (f"it-{profile_id}", user_id),
        )
        await cursor.execute(
            "insert into public.broker_profiles(id,user_id,alias,mode) values (%s,%s,%s,'demo')",
            (profile_id, user_id, f"it-{profile_id}"),
        )
        await cursor.execute(
            "insert into public.conditions(id,user_id,profile_id,seq,name) values "
            "(%s,%s,%s,'0','A'),(%s,%s,%s,'1','B')",
            (first_condition_id, user_id, profile_id, second_condition_id, user_id, profile_id),
        )
        await cursor.execute(
            "insert into public.strategies(id,user_id,profile_id,name) values (%s,%s,%s,'Integration')",
            (strategy_id, user_id, profile_id),
        )
        await cursor.execute("set role authenticated")
        await cursor.execute(
            "select set_config('request.jwt.claims', %s, false)",
            (f'{{"sub":"{user_id}","role":"authenticated"}}',),
        )
        await cursor.execute(
            "select public.create_strategy_version(%s,%s::jsonb)",
            (
                strategy_id,
                '{"schemaVersion":1,"exchange":"K","profileId":"'
                + profile_id
                + '","expr":{"type":"and","children":[{"type":"condition","conditionId":"'
                + first_condition_id
                + '"},{"type":"condition","conditionId":"'
                + second_condition_id
                + '"}]}}',
            ),
        )
        await cursor.execute(
            "select (public.request_run('search',%s,%s,%s)).id",
            (profile_id, strategy_id, str(uuid4())),
        )
        run_id = str((await cursor.fetchone())[0])
        await cursor.execute("reset role")
    return user_id, profile_id, first_condition_id, second_condition_id, run_id


async def _login_worker_role() -> None:
    async with (
        await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin,
        admin.cursor() as cursor,
    ):
        await cursor.execute("alter role kiwoom_worker login password 'kiwoom-worker-local'")


async def _logout_worker_role() -> None:
    async with (
        await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin,
        admin.cursor() as cursor,
    ):
        await cursor.execute("alter role kiwoom_worker nologin password null")


async def _delete_test_user(user_id: str) -> None:
    """Remove one disposable user and, by cascade, everything it owns.

    Every table that records an owner cascades from auth.users, but the
    strategy_versions
    immutability trigger refuses the cascade, so it is disabled for the delete
    and restored afterwards. Each test calls this: without it the local
    database accumulates the rows of every run, and a test that looks for the
    run of a profile can pick up a leftover instead. worker_heartbeats records
    no owner, so it is not reached from here; see _delete_heartbeat.
    """
    async with (
        await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin,
        admin.cursor() as cursor,
    ):
        await cursor.execute("alter table public.strategy_versions disable trigger strategy_versions_immutable")
        try:
            await cursor.execute("delete from auth.users where id=%s", (user_id,))
        finally:
            await cursor.execute("alter table public.strategy_versions enable trigger strategy_versions_immutable")


async def _delete_heartbeat(worker_id: str) -> None:
    """Remove a heartbeat a test wrote.

    worker_heartbeats has no owner column, so it is the one table that does not
    cascade from auth.users and _delete_test_user cannot reach it. A row left
    behind reports a worker as reachable for an alias that no longer exists.
    """
    async with await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin:
        await admin.execute(
            "delete from public.worker_heartbeats where worker_id=%s", (worker_id,)
        )


@pytest.fixture(autouse=True)
async def worker_role_login() -> None:
    await _login_worker_role()
    try:
        yield
    finally:
        await _logout_worker_role()
