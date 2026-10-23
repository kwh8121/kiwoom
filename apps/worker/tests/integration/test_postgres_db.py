from __future__ import annotations

import asyncio

import pytest
from psycopg import AsyncConnection

from kiwoom_worker.db import PostgresWorkerDb
from kiwoom_worker.runner import RunFailure

from .conftest import ADMIN_URL, WORKER_URL, _create_queued_search, _delete_test_user

pytestmark = pytest.mark.db

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
        assert await db.complete_search(run_id, claimed.lease_owner, payload) is True
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
        result = await db.fail(run_id, claimed.lease_owner, RunFailure("RATE_LIMITED", True, "retry", []))
        assert result == "queued"
    finally:
        await db.close()
        await _delete_test_user(user_id)


@pytest.mark.asyncio
async def test_heartbeat_is_not_blocked_by_a_slow_settlement() -> None:
    """Liveness reporting must not queue behind the settlement write.

    Settling a run writes snapshots, results and the profile's error fields.
    psycopg serializes statements per connection, so a shared connection makes
    the heartbeat wait for that write and the profile page shows the worker as
    unreachable while it is in fact busy finishing the run.

    The lease extension is a separate matter: the settlement holds the run row
    for its whole duration, so no connection can extend that run's lease while
    it is being settled. The database covers that case by rechecking expiry
    after its writes and rolling the settlement back.
    """
    user_id, profile_id, _first, _second, run_id = await _create_queued_search()
    db = await PostgresWorkerDb.connect(WORKER_URL)
    blocker = await AsyncConnection.connect(ADMIN_URL)
    try:
        claimed = await db.claim("integration-worker", [f"it-{profile_id}"], 60)
        assert claimed is not None

        # Hold the row the settlement's profile update needs, so the settlement
        # is still in flight while the heartbeat is attempted.
        await blocker.execute(
            "select 1 from public.broker_profiles where id=%s for update", (profile_id,)
        )
        settlement = asyncio.create_task(
            db.fail(run_id, claimed.lease_owner, RunFailure("RATE_LIMITED", True, "retry", []))
        )
        await asyncio.sleep(0.2)
        assert not settlement.done(), "the settlement did not block as this test needs"

        beat = asyncio.create_task(db.heartbeat("integration-worker", [f"it-{profile_id}"], "test"))
        done, _pending = await asyncio.wait({beat}, timeout=2)
        blocked = beat not in done

        await blocker.rollback()
        await asyncio.wait({settlement, beat}, timeout=5)

        assert not blocked, "the heartbeat queued behind the blocked settlement"
    finally:
        await blocker.close()
        await db.close()
        await _delete_test_user(user_id)
