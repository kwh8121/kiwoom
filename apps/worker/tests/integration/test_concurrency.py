"""Two-connection contention tests for the claim and request paths.

pgTAP runs everything on one connection inside one transaction, so it can
assert the locking clauses exist but never that they hold under real
contention. These tests open genuine concurrent sessions, which is the only
way to see `for update skip locked` and the active-run unique index do their
job. They were the open item left by the worker RPC review.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from psycopg import AsyncConnection, errors

from .conftest import ADMIN_URL, WORKER_URL, _create_queued_search, _delete_test_user

pytestmark = pytest.mark.db


async def _claim(alias: str, worker_id: str) -> str | None:
    """Claim on a connection of this call's own, as the worker role does."""
    async with await AsyncConnection.connect(WORKER_URL, autocommit=True) as db:
        row = await (
            await db.execute(
                "select worker.claim_next_run(%s, %s, %s)", (worker_id, [alias], 60)
            )
        ).fetchone()
    claimed = row[0] if row else None
    return None if claimed is None else str(claimed["run_id"])


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_the_same_run() -> None:
    user_id, profile_id, _first, _second, run_id = await _create_queued_search()
    try:
        alias = f"it-{profile_id}"
        first, second = await asyncio.gather(
            _claim(alias, "contender-a"), _claim(alias, "contender-b")
        )

        assert sorted([first, second], key=lambda value: value or "") == [None, run_id], (
            "both workers claimed the same run"
        )
    finally:
        await _delete_test_user(user_id)


async def _request_sync(user_id: str, profile_id: str) -> str | None:
    """Request a sync as the owner, each call on its own session.

    Returns None when the database refuses because the profile already has an
    active run, which is the contention this asserts.
    """
    async with await AsyncConnection.connect(ADMIN_URL, autocommit=True) as db:
        await db.execute("set role authenticated")
        await db.execute(
            "select set_config('request.jwt.claims', %s, false)",
            (f'{{"sub":"{user_id}","role":"authenticated"}}',),
        )
        try:
            row = await (
                await db.execute(
                    "select (public.request_run('sync',%s,null,%s)).id",
                    (profile_id, str(uuid4())),
                )
            ).fetchone()
        except errors.RaiseException as exc:
            if "PROFILE_BUSY" not in str(exc):
                raise
            return None
    return str(row[0]) if row else None


@pytest.mark.asyncio
async def test_one_profile_cannot_hold_two_active_runs() -> None:
    """A profile drives one broker session, so only one run may be active.

    Two owners' tabs can submit at the same moment. The partial unique index on
    active runs is what keeps the second one out, and only concurrent sessions
    can show that it does.
    """
    user_id, profile_id, _first, _second, search_run_id = await _create_queued_search()
    try:
        async with await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin:
            # The fixture leaves a queued search, which already occupies the
            # profile. Clear it so both sync requests start from a free profile.
            await admin.execute(
                "update public.runs set status='cancelled', finished_at=clock_timestamp()"
                " where id=%s",
                (search_run_id,),
            )

        first, second = await asyncio.gather(
            _request_sync(user_id, profile_id), _request_sync(user_id, profile_id)
        )

        accepted = [run for run in (first, second) if run is not None]
        assert len(accepted) == 1, f"the profile accepted {len(accepted)} active runs"

        async with await AsyncConnection.connect(ADMIN_URL, autocommit=True) as admin:
            row = await (
                await admin.execute(
                    "select count(*) from public.runs"
                    " where profile_id=%s and status in ('queued','running')",
                    (profile_id,),
                )
            ).fetchone()
        assert row[0] == 1
    finally:
        await _delete_test_user(user_id)
