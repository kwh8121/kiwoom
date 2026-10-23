from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from kiwoom_worker.clock import SystemClock
from kiwoom_worker.config import WorkerSettings
from kiwoom_worker.db import ClaimedRun, SettlementRejected
from kiwoom_worker.kiwoom.session import ConditionItem, ResponseTimeout, SearchResult
from kiwoom_worker.kiwoom.token import Credentials
from kiwoom_worker.main import _open_session, process_one, run_worker
from kiwoom_worker.runner import ConditionRefSnapshot, RunFailure
from tests.fakes import FakeClock


def _settings(**overrides: Any) -> WorkerSettings:
    values: dict[str, Any] = {
        "database_url": "postgresql://worker:secret@127.0.0.1:54322/postgres",
        "worker_id": "worker-1",
        "profiles_file": Path("profiles.toml"),
        "transport": "fixture",
        "fixture_file": Path("fixtures/e2e_market.json"),
        "poll_interval_s": 3.0,
        "heartbeat_interval_s": 15.0,
        "lease_seconds": 6,
        "request_interval_s": 0.0,
        "response_timeout_s": 10.0,
        "max_pages": 50,
        "rate_limit_retries": 3,
        "run_timeout_s": 120.0,
    }
    values.update(overrides)
    return WorkerSettings(**values)


def _search_definition(profile_id: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "exchange": "K",
        "profileId": profile_id,
        "expr": {"type": "condition", "conditionId": "cond-1"},
    }


def _claimed_search(mode: str = "demo") -> ClaimedRun:
    return ClaimedRun(
        run_id="run-search-1",
        kind="search",
        attempt=1,
        profile_id="profile-1",
        alias="demo-a",
        mode=mode,
        definition=_search_definition("profile-1"),
        condition_refs=[ConditionRefSnapshot(condition_id="cond-1", seq="0", name="기본종목")],
    )


def _claimed_sync(mode: str = "demo") -> ClaimedRun:
    return ClaimedRun(
        run_id="run-sync-1",
        kind="sync",
        attempt=1,
        profile_id="profile-1",
        alias="demo-a",
        mode=mode,
        definition=None,
        condition_refs=[],
    )


def _profiles() -> dict[str, Credentials]:
    return {"demo-a": Credentials("demo-a", "demo", "demo-key", "demo-secret")}


def _search_result(*, clock: FakeClock) -> SearchResult:
    started_at = clock.now()
    return SearchResult(
        seq="0",
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
        page_count=1,
        members=[],
    )


@dataclass
class FakeDb:
    claimed: deque[ClaimedRun | None]
    claim_calls: list[tuple[str, list[str], int]] = field(default_factory=list)
    heartbeats: list[tuple[str, list[str], str]] = field(default_factory=list)
    leases: list[tuple[str, str, int]] = field(default_factory=list)
    completed_search: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)
    completed_sync: list[tuple[str, str, list[dict[str, str]]]] = field(default_factory=list)
    failed: list[tuple[str, str, RunFailure]] = field(default_factory=list)
    complete_search_result: bool = True
    complete_sync_result: dict[str, object] | None = field(default_factory=lambda: {"added": 0})
    fail_result: str = "failed"

    async def heartbeat(self, worker_id: str, aliases: list[str], version: str) -> None:
        self.heartbeats.append((worker_id, aliases, version))

    async def claim(self, worker_id: str, aliases: list[str], lease_seconds: int) -> ClaimedRun | None:
        self.claim_calls.append((worker_id, aliases, lease_seconds))
        return self.claimed.popleft()

    async def extend_lease(self, run_id: str, worker_id: str, lease_seconds: int) -> bool:
        self.leases.append((run_id, worker_id, lease_seconds))
        return True

    async def complete_search(self, run_id: str, worker_id: str, payload: dict[str, object]) -> bool:
        self.completed_search.append((run_id, worker_id, payload))
        return self.complete_search_result

    async def complete_sync(self, run_id: str, worker_id: str, items: list[dict[str, str]]) -> dict[str, object] | None:
        self.completed_sync.append((run_id, worker_id, items))
        return self.complete_sync_result

    async def fail(self, run_id: str, worker_id: str, failure: RunFailure) -> str:
        self.failed.append((run_id, worker_id, failure))
        return self.fail_result


@dataclass
class SearchSession:
    result: SearchResult
    delay_s: float = 0.0
    clock: FakeClock | None = None

    async def list_conditions(self) -> list[ConditionItem]:
        return [ConditionItem("0", "기본종목")]

    async def search(self, seq: str) -> SearchResult:
        if self.delay_s and self.clock is not None:
            await self.clock.sleep(self.delay_s)
        return self.result


@dataclass
class SyncSession:
    items: list[ConditionItem]

    async def list_conditions(self) -> list[ConditionItem]:
        return list(self.items)

    async def search(self, seq: str) -> SearchResult:
        raise AssertionError(f"unexpected search for {seq}")


def _open_session_for(session: object):
    calls: list[tuple[str, bool]] = []

    def opener(creds: Credentials, force_token_refresh: bool):
        calls.append((creds.alias, force_token_refresh))

        @asynccontextmanager
        async def _manager():
            yield session

        return _manager()

    opener.calls = calls
    return opener


@pytest.mark.asyncio
async def test_process_one_completes_search() -> None:
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = FakeDb(deque([_claimed_search()]))
    opener = _open_session_for(SearchSession(_search_result(clock=clock)))

    handled = await process_one(db, _settings(), _profiles(), opener, clock)

    assert handled is True
    assert db.completed_search[0][0] == "run-search-1"
    assert db.failed == []
    assert opener.calls == [("demo-a", False)]


@pytest.mark.asyncio
async def test_lease_lost_is_logged_not_failed(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = FakeDb(deque([_claimed_search()]), complete_search_result=False)
    opener = _open_session_for(SearchSession(_search_result(clock=clock)))

    with caplog.at_level(logging.WARNING):
        handled = await process_one(db, _settings(), _profiles(), opener, clock)

    assert handled is True
    assert db.failed == []
    assert "lease" in caplog.text.lower()


@pytest.mark.asyncio
async def test_completion_database_error_is_not_reported_as_broker_failure() -> None:
    class BrokenCompletionDb(FakeDb):
        async def complete_search(self, run_id: str, worker_id: str, payload: dict[str, object]) -> bool:
            raise RuntimeError("database unavailable")

    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = BrokenCompletionDb(deque([_claimed_search()]))
    opener = _open_session_for(SearchSession(_search_result(clock=clock)))

    with pytest.raises(RuntimeError, match="database unavailable"):
        await process_one(db, _settings(), _profiles(), opener, clock)

    assert db.failed == []


@pytest.mark.asyncio
async def test_rejected_search_payload_is_recorded_instead_of_retried(caplog: pytest.LogCaptureFixture) -> None:
    class RejectingDb(FakeDb):
        async def complete_search(self, run_id: str, worker_id: str, payload: dict[str, object]) -> bool:
            raise SettlementRejected("complete_search_run", RuntimeError("PAYLOAD_INVALID"))

    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = RejectingDb(deque([_claimed_search()]))
    opener = _open_session_for(SearchSession(_search_result(clock=clock)))

    with caplog.at_level(logging.ERROR):
        handled = await process_one(db, _settings(), _profiles(), opener, clock)

    assert handled is True
    assert db.failed[0][2].code == "SETTLE_REJECTED"
    assert db.failed[0][2].retryable is False
    assert "PAYLOAD_INVALID" in caplog.text


@pytest.mark.asyncio
async def test_rejected_sync_payload_is_recorded_instead_of_retried() -> None:
    class RejectingDb(FakeDb):
        async def complete_sync(self, run_id: str, worker_id: str, items: list[dict[str, str]]) -> dict[str, object] | None:
            raise SettlementRejected("complete_sync_run", RuntimeError("PAYLOAD_INVALID"))

    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = RejectingDb(deque([_claimed_sync()]))
    opener = _open_session_for(SyncSession([ConditionItem("0", "기본종목")]))

    handled = await process_one(db, _settings(), _profiles(), opener, clock)

    assert handled is True
    assert db.failed[0][2].code == "SETTLE_REJECTED"


@pytest.mark.asyncio
async def test_rejected_failure_report_does_not_end_the_worker(caplog: pytest.LogCaptureFixture) -> None:
    class RejectingFailDb(FakeDb):
        async def fail(self, run_id: str, worker_id: str, failure: RunFailure) -> str:
            raise SettlementRejected("fail_run", RuntimeError("PAYLOAD_INVALID"))

    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = RejectingFailDb(deque([_claimed_search(mode="real")]))

    with caplog.at_level(logging.ERROR):
        handled = await process_one(db, _settings(), _profiles(), _open_session_for(object()), clock)

    assert handled is True
    assert "PROFILE_CONFIG" in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_failure_does_not_cancel_an_active_run(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    profiles_file = tmp_path / "profiles.toml"
    profiles_file.write_text(
        '[profiles.demo-a]\nmode = "demo"\nappkey = "demo-key"\nsecretkey = "demo-secret"\n',
        encoding="utf-8",
    )
    profiles_file.chmod(0o600)

    class FlakyHeartbeatDb(FakeDb):
        async def heartbeat(self, worker_id: str, aliases: list[str], version: str) -> None:
            self.heartbeats.append((worker_id, aliases, version))
            raise RuntimeError("heartbeat connection reset")

    clock = SystemClock()
    db = FlakyHeartbeatDb(deque([_claimed_search(), None]))
    settings = _settings(profiles_file=profiles_file, heartbeat_interval_s=0.01, poll_interval_s=0.01)
    stop = asyncio.Event()

    with caplog.at_level(logging.ERROR):
        worker = asyncio.create_task(
            run_worker(settings, db, _open_session_for(SearchSession(_search_result(clock=FakeClock(datetime(2026, 10, 18, tzinfo=UTC))))), clock, stop)
        )
        try:
            await asyncio.wait_for(asyncio.shield(_wait_for_search(db)), timeout=1.0)
        finally:
            stop.set()
            await asyncio.wait_for(worker, timeout=1.0)

    assert db.completed_search, "the run must settle despite heartbeat failures"
    assert "heartbeat failed" in caplog.text


async def _wait_for_search(db: FakeDb) -> None:
    while not db.completed_search:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_mode_mismatch_fails_profile_config() -> None:
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = FakeDb(deque([_claimed_search(mode="real")]))

    handled = await process_one(db, _settings(), _profiles(), _open_session_for(object()), clock)

    assert handled is True
    assert db.failed[0][2].code == "PROFILE_CONFIG"
    assert db.failed[0][2].retryable is False


@pytest.mark.asyncio
async def test_run_timeout_marks_timed_out() -> None:
    db = FakeDb(deque([_claimed_search()]))
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))

    class TimeoutSession(SearchSession):
        async def search(self, seq: str) -> SearchResult:
            await asyncio.sleep(0.05)
            return self.result

    opener = _open_session_for(TimeoutSession(_search_result(clock=clock)))

    handled = await process_one(db, _settings(run_timeout_s=0.01), _profiles(), opener, clock)

    assert handled is True
    assert db.failed[0][2].code == "RUN_TIMEOUT"
    assert db.failed[0][2].retryable is False


@pytest.mark.asyncio
async def test_sync_response_timeout_is_not_reported_as_a_run_timeout() -> None:
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = FakeDb(deque([_claimed_sync()]))

    class SlowListSession(SyncSession):
        async def list_conditions(self) -> list[ConditionItem]:
            raise ResponseTimeout("timed out after 10.0s")

    opener = _open_session_for(SlowListSession([]))

    handled = await process_one(db, _settings(), _profiles(), opener, clock)

    assert handled is True
    assert db.failed[0][2].code == "RESPONSE_TIMEOUT"
    assert db.failed[0][2].retryable is True


@pytest.mark.asyncio
async def test_lease_extended_during_run() -> None:
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = FakeDb(deque([_claimed_search()]))
    opener = _open_session_for(SearchSession(_search_result(clock=clock), delay_s=2.5, clock=clock))

    handled = await process_one(db, _settings(lease_seconds=6), _profiles(), opener, clock)

    assert handled is True
    assert db.leases


@pytest.mark.asyncio
async def test_sync_job_completes_with_items() -> None:
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))
    db = FakeDb(deque([_claimed_sync()]))
    opener = _open_session_for(SyncSession([ConditionItem("0", "기본종목"), ConditionItem("1", "전일고가돌파")]))

    handled = await process_one(db, _settings(), _profiles(), opener, clock)

    assert handled is True
    assert db.completed_sync == [
        (
            "run-sync-1",
            "worker-1",
            [{"seq": "0", "name": "기본종목"}, {"seq": "1", "name": "전일고가돌파"}],
        )
    ]


@pytest.mark.asyncio
async def test_run_worker_heartbeats_while_run_is_active(tmp_path: Path) -> None:
    profiles_file = tmp_path / "profiles.toml"
    profiles_file.write_text(
        '[profiles.demo-a]\nmode = "demo"\nappkey = "demo-key"\nsecretkey = "demo-secret"\n',
        encoding="utf-8",
    )
    profiles_file.chmod(0o600)
    settings = _settings(profiles_file=profiles_file, heartbeat_interval_s=0.01, run_timeout_s=2.0)
    clock = SystemClock()
    db = FakeDb(deque([_claimed_search()]))
    search_started = asyncio.Event()
    release_search = asyncio.Event()

    class BlockingSession(SearchSession):
        async def search(self, seq: str) -> SearchResult:
            search_started.set()
            await release_search.wait()
            return self.result

    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_worker(
            settings,
            db,
            _open_session_for(
                BlockingSession(
                    SearchResult(
                        seq="0",
                        started_at=clock.now(),
                        completed_at=clock.now() + timedelta(seconds=1),
                        page_count=1,
                        members=[],
                    )
                )
            ),
            clock,
            stop,
        )
    )
    try:
        await asyncio.wait_for(search_started.wait(), timeout=1.0)
        await asyncio.sleep(0.05)
        heartbeats_during_run = len(db.heartbeats)
    finally:
        release_search.set()
        stop.set()
        await asyncio.wait_for(worker, timeout=1.0)

    assert heartbeats_during_run >= 2


@pytest.mark.asyncio
async def test_open_session_closes_transport_when_login_fails() -> None:
    class FailingLoginTransport:
        closed = False

        async def send(self, text: str) -> None:
            raise RuntimeError("login failed")

        async def recv(self, timeout: float) -> str:
            raise AssertionError("recv should not run after send fails")

        async def close(self) -> None:
            self.closed = True

    transport = FailingLoginTransport()
    clock = FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))

    with pytest.raises(RuntimeError, match="login failed"):
        async with _open_session(_settings(), lambda: transport, "token", clock):
            pytest.fail("session must not open when login fails")

    assert transport.closed is True
