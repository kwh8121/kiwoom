from __future__ import annotations

import os
from uuid import uuid4

import pytest
from psycopg import AsyncConnection

from kiwoom_worker.db import PostgresWorkerDb
from kiwoom_worker.runner import RunFailure

pytestmark = pytest.mark.db

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
    async with (
        await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin,
        admin.cursor() as cursor,
    ):
        await cursor.execute("alter table public.strategy_versions disable trigger strategy_versions_immutable")
        try:
            await cursor.execute("delete from auth.users where id=%s", (user_id,))
        finally:
            await cursor.execute("alter table public.strategy_versions enable trigger strategy_versions_immutable")


@pytest.fixture(autouse=True)
async def worker_role_login() -> None:
    await _login_worker_role()
    try:
        yield
    finally:
        await _logout_worker_role()


@pytest.mark.asyncio
async def test_postgres_worker_db_claim_and_complete_search() -> None:
    user_id, profile_id, first_condition_id, second_condition_id, run_id = await _create_queued_search()
    db = await PostgresWorkerDb.connect(WORKER_URL)
    try:
        claimed = await db.claim("integration-worker", [f"it-{profile_id}"], 60)
        assert claimed is not None
        assert claimed.run_id == run_id
        assert claimed.profile_id == profile_id
        assert [ref.condition_id for ref in claimed.condition_refs] == [first_condition_id, second_condition_id]

        payload: dict[str, object] = {
            "window_start": "2026-10-18T00:00:00Z",
            "window_end": "2026-10-18T00:00:01Z",
            "market_phase": "weekend",
            "snapshots": [
                {
                    "condition_id": first_condition_id,
                    "seq": "0",
                    "name": "A",
                    "started_at": "2026-10-18T00:00:00Z",
                    "completed_at": "2026-10-18T00:00:01Z",
                    "page_count": 1,
                    "members": [
                        {"code": "005930", "raw_code": "A005930", "instrument_type": "stock", "name": "First"}
                    ],
                },
                {
                    "condition_id": second_condition_id,
                    "seq": "1",
                    "name": "B",
                    "started_at": "2026-10-18T00:00:00Z",
                    "completed_at": "2026-10-18T00:00:01Z",
                    "page_count": 1,
                    "members": [
                        {"code": "005930", "raw_code": "A005930", "instrument_type": "stock", "name": "Second"}
                    ],
                },
            ],
            "results": [{"code": "005930", "matched_condition_ids": [first_condition_id, second_condition_id]}],
            "excluded_codes": [],
        }
        assert await db.complete_search(run_id, "integration-worker", payload) is True
        async with (
            await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin,
            admin.cursor() as cursor,
        ):
            await cursor.execute("select count(*) from public.run_results where run_id=%s", (run_id,))
            assert (await cursor.fetchone())[0] == 1
    finally:
        await db.close()
        await _delete_test_user(user_id)


@pytest.mark.asyncio
async def test_postgres_worker_db_fail_retryable_requeues() -> None:
    user_id, profile_id, _first_condition_id, _second_condition_id, run_id = await _create_queued_search()
    db = await PostgresWorkerDb.connect(WORKER_URL)
    try:
        claimed = await db.claim("integration-worker", [f"it-{profile_id}"], 60)
        assert claimed is not None and claimed.run_id == run_id
        result = await db.fail(run_id, "integration-worker", RunFailure("RATE_LIMITED", True, "retry", []))
        assert result == "queued"
    finally:
        await db.close()
        await _delete_test_user(user_id)
