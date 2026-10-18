from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from websockets.exceptions import ConnectionClosedError, InvalidHandshake

from kiwoom_worker.kiwoom.errors import KiwoomApiError
from kiwoom_worker.kiwoom.parse import Member
from kiwoom_worker.kiwoom.session import (
    ConditionItem,
    IncompletePagination,
    ResponseTimeout,
    SearchResult,
)
from kiwoom_worker.kiwoom.token import TokenTransportError
from kiwoom_worker.runner import (
    ConditionRefSnapshot,
    RunFailure,
    SearchJob,
    execute_search,
    execute_sync,
    market_phase,
    to_run_failure,
)
from tests.fakes import FakeClock


def _condition(condition_id: str) -> dict[str, str]:
    return {"type": "condition", "conditionId": condition_id}


def _and(*children: dict[str, object]) -> dict[str, object]:
    return {"type": "and", "children": list(children)}


def _exclude(base: dict[str, object], *subtract: dict[str, object]) -> dict[str, object]:
    return {"type": "exclude", "base": base, "subtract": list(subtract)}


def _definition(expr: dict[str, object], *, profile_id: str = "demo") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "profileId": profile_id,
        "exchange": "K",
        "expr": expr,
    }


def _member(code: str, *, name: str | None = None) -> Member:
    return Member(
        code=code,
        raw_code=f"A{code}",
        instrument_type="stock",
        name=name or f"종목-{code}",
        price=1000,
        change_rate=Decimal("1.23"),
    )


def _search_result(
    seq: str,
    *,
    started_at: datetime,
    completed_at: datetime | None = None,
    page_count: int = 1,
    members: list[Member] | None = None,
) -> SearchResult:
    return SearchResult(
        seq=seq,
        started_at=started_at,
        completed_at=completed_at or started_at + timedelta(seconds=1),
        page_count=page_count,
        members=list(members or []),
    )


def _job(
    *,
    expr: dict[str, object],
    refs: dict[str, tuple[str, str]],
    run_id: str = "run-1",
    profile_id: str = "demo",
) -> SearchJob:
    return SearchJob(
        run_id=run_id,
        profile_id=profile_id,
        definition=_definition(expr, profile_id=profile_id),
        condition_refs=[
            ConditionRefSnapshot(condition_id=condition_id, seq=seq, name=name)
            for condition_id, (seq, name) in refs.items()
        ],
    )


@dataclass
class FakeSession:
    conditions: list[ConditionItem]
    search_plan: dict[str, list[SearchResult | BaseException]]

    def __post_init__(self) -> None:
        self._search_queues = {seq: deque(items) for seq, items in self.search_plan.items()}
        self.searched: list[str] = []

    async def list_conditions(self) -> list[ConditionItem]:
        return list(self.conditions)

    async def search(self, seq: str) -> SearchResult:
        self.searched.append(seq)
        queue = self._search_queues[seq]
        outcome = queue.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class SessionOpenerRecorder:
    def __init__(self, *sessions: FakeSession) -> None:
        self._sessions = deque(sessions)
        self.calls: list[bool] = []

    def __call__(self, force_token_refresh: bool):
        self.calls.append(force_token_refresh)
        session = self._sessions.popleft()

        @asynccontextmanager
        async def _manager():
            yield session

        return _manager()


@dataclass
class BlockingSession:
    block_list: asyncio.Event | None = None
    block_search: asyncio.Event | None = None

    async def list_conditions(self) -> list[ConditionItem]:
        if self.block_list is None:
            return []
        await self.block_list.wait()
        raise AssertionError("list_conditions should have been cancelled")

    async def search(self, seq: str) -> SearchResult:
        if self.block_search is None:
            raise AssertionError(f"unexpected search call for {seq}")
        await self.block_search.wait()
        raise AssertionError("search should have been cancelled")


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_payload_for_and() -> None:
    clock = _clock()
    started_at = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
    session = FakeSession(
        conditions=[ConditionItem("0", "A"), ConditionItem("1", "B")],
        search_plan={
            "0": [_search_result("0", started_at=started_at, members=[_member("001"), _member("002")])],
            "1": [
                _search_result(
                    "1",
                    started_at=started_at + timedelta(seconds=2),
                    completed_at=started_at + timedelta(seconds=3),
                    members=[_member("002"), _member("003")],
                )
            ],
        },
    )
    opener = SessionOpenerRecorder(session)

    payload = await execute_search(
        _job(expr=_and(_condition("A"), _condition("B")), refs={"A": ("0", "A"), "B": ("1", "B")}),
        opener,
        clock,
    )

    assert payload["window_start"] == started_at.isoformat()
    assert payload["window_end"] == (started_at + timedelta(seconds=3)).isoformat()
    assert payload["market_phase"] == "regular"
    assert len(payload["snapshots"]) == 2
    assert payload["snapshots"][0]["members"][0]["raw_code"] == "A001"
    assert payload["results"] == [{"code": "002", "matched_condition_ids": ["A", "B"]}]
    assert payload["excluded_codes"] == []


@pytest.mark.asyncio
async def test_renamed_condition_fails_before_search() -> None:
    clock = _clock()
    session = FakeSession(
        conditions=[ConditionItem("0", "A-renamed")],
        search_plan={"0": [_search_result("0", started_at=clock.now(), members=[_member("001")])]},
    )
    opener = SessionOpenerRecorder(session)

    with pytest.raises(RunFailure) as excinfo:
        await execute_search(_job(expr=_condition("A"), refs={"A": ("0", "A")}), opener, clock)

    assert excinfo.value.code == "CONDITION_CHANGED"
    assert excinfo.value.retryable is False
    assert "seq=0" in excinfo.value.message
    assert session.searched == []


def test_900004_maps_condition_changed() -> None:
    failure = to_run_failure(KiwoomApiError(900004, "조건식을 찾을 수 없습니다"), partial=[])

    assert failure.code == "CONDITION_CHANGED"
    assert failure.retryable is False


@pytest.mark.asyncio
async def test_duplicate_leaf_searched_once() -> None:
    clock = _clock()
    session = FakeSession(
        conditions=[ConditionItem("0", "A")],
        search_plan={"0": [_search_result("0", started_at=clock.now(), members=[_member("001")])]},
    )
    opener = SessionOpenerRecorder(session)

    payload = await execute_search(
        _job(expr=_and(_condition("A"), _condition("A")), refs={"A": ("0", "A")}),
        opener,
        clock,
    )

    assert session.searched == ["0"]
    assert payload["results"] == [{"code": "001", "matched_condition_ids": ["A"]}]


@pytest.mark.asyncio
async def test_token_expired_retries_once_with_refresh() -> None:
    clock = _clock()
    first = FakeSession(
        conditions=[ConditionItem("0", "A")],
        search_plan={"0": [KiwoomApiError(8005, "token expired")]},
    )
    second = FakeSession(
        conditions=[ConditionItem("0", "A")],
        search_plan={"0": [_search_result("0", started_at=clock.now(), members=[_member("001")])]},
    )
    opener = SessionOpenerRecorder(first, second)

    payload = await execute_search(_job(expr=_condition("A"), refs={"A": ("0", "A")}), opener, clock)

    assert opener.calls == [False, True]
    assert payload["results"] == [{"code": "001", "matched_condition_ids": ["A"]}]


@pytest.mark.asyncio
async def test_incomplete_pagination_retryable_with_partial() -> None:
    clock = _clock()
    started_at = clock.now()
    session = FakeSession(
        conditions=[ConditionItem("0", "A"), ConditionItem("1", "B")],
        search_plan={
            "0": [_search_result("0", started_at=started_at, members=[_member("001"), _member("002")])],
            "1": [IncompletePagination("more pages expected")],
        },
    )
    opener = SessionOpenerRecorder(session)

    with pytest.raises(RunFailure) as excinfo:
        await execute_search(
            _job(expr=_and(_condition("A"), _condition("B")), refs={"A": ("0", "A"), "B": ("1", "B")}),
            opener,
            clock,
        )

    assert excinfo.value.code == "INCOMPLETE_PAGINATION"
    assert excinfo.value.retryable is True
    assert excinfo.value.partial[0]["row_count"] == 2
    assert excinfo.value.partial[1]["error_code"] == "INCOMPLETE_PAGINATION"


@pytest.mark.asyncio
async def test_ip_device_not_retryable() -> None:
    clock = _clock()
    session = FakeSession(
        conditions=[ConditionItem("0", "A")],
        search_plan={"0": [KiwoomApiError(8010, "접속 단말 정보가 없습니다")]},
    )
    opener = SessionOpenerRecorder(session)

    with pytest.raises(RunFailure) as excinfo:
        await execute_search(_job(expr=_condition("A"), refs={"A": ("0", "A")}), opener, clock)

    assert excinfo.value.code == "IP_DEVICE_AUTH"
    assert excinfo.value.retryable is False


@pytest.mark.asyncio
async def test_excluded_codes_in_payload() -> None:
    clock = _clock()
    session = FakeSession(
        conditions=[ConditionItem("0", "A"), ConditionItem("1", "B")],
        search_plan={
            "0": [_search_result("0", started_at=clock.now(), members=[_member("001"), _member("002")])],
            "1": [_search_result("1", started_at=clock.now(), members=[_member("002")])],
        },
    )
    opener = SessionOpenerRecorder(session)

    payload = await execute_search(
        _job(expr=_exclude(_condition("A"), _condition("B")), refs={"A": ("0", "A"), "B": ("1", "B")}),
        opener,
        clock,
    )

    assert payload["results"] == [{"code": "001", "matched_condition_ids": ["A"]}]
    assert payload["excluded_codes"] == ["002"]


@pytest.mark.asyncio
async def test_invalid_definition_not_retryable() -> None:
    clock = _clock()
    opener = SessionOpenerRecorder()
    job = SearchJob(
        run_id="run-1",
        profile_id="demo",
        definition={"schemaVersion": 2, "profileId": "demo", "exchange": "K", "expr": _condition("A")},
        condition_refs=[ConditionRefSnapshot(condition_id="A", seq="0", name="A")],
    )

    with pytest.raises(RunFailure) as excinfo:
        await execute_search(job, opener, clock)

    assert excinfo.value.code == "INVALID_DEFINITION"
    assert excinfo.value.retryable is False
    assert opener.calls == []


def test_market_phase_boundaries() -> None:
    kst = ZoneInfo("Asia/Seoul")

    assert [market_phase(datetime(2026, 10, 19, hour, minute, tzinfo=kst)) for hour, minute in [(8, 59), (9, 0), (15, 29), (15, 30)]] == [
        "pre",
        "regular",
        "regular",
        "post",
    ]
    assert market_phase(datetime(2026, 10, 17, 12, 0, tzinfo=kst)) == "weekend"


@pytest.mark.asyncio
async def test_execute_sync_returns_items() -> None:
    session = FakeSession(
        conditions=[ConditionItem("0", "A"), ConditionItem("1", "B")],
        search_plan={},
    )
    opener = SessionOpenerRecorder(session)

    payload = await execute_sync(opener)

    assert opener.calls == [False]
    assert payload == [{"seq": "0", "name": "A"}, {"seq": "1", "name": "B"}]


@dataclass
class FailingListSession:
    outcomes: list[BaseException]

    def __post_init__(self) -> None:
        self._queue = deque(self.outcomes)

    async def list_conditions(self) -> list[ConditionItem]:
        raise self._queue.popleft()

    async def search(self, seq: str) -> SearchResult:
        raise AssertionError(f"unexpected search for {seq}")


@pytest.mark.asyncio
async def test_execute_sync_response_timeout_is_retryable() -> None:
    opener = SessionOpenerRecorder(FailingListSession([ResponseTimeout("timed out after 10.0s")]))

    with pytest.raises(RunFailure) as caught:
        await execute_sync(opener)

    assert caught.value.code == "RESPONSE_TIMEOUT"
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_execute_sync_token_expired_retries_once_with_refresh() -> None:
    opener = SessionOpenerRecorder(
        FailingListSession([KiwoomApiError(8005, "token expired")]),
        FakeSession(conditions=[ConditionItem("0", "A")], search_plan={}),
    )

    assert await execute_sync(opener) == [{"seq": "0", "name": "A"}]
    assert opener.calls == [False, True]


@pytest.mark.asyncio
async def test_execute_sync_token_expired_twice_is_terminal() -> None:
    opener = SessionOpenerRecorder(
        FailingListSession([KiwoomApiError(8005, "token expired")]),
        FailingListSession([KiwoomApiError(8005, "token expired")]),
    )

    with pytest.raises(RunFailure) as caught:
        await execute_sync(opener)

    assert caught.value.code == "TOKEN_INVALID"
    assert opener.calls == [False, True]


@pytest.mark.asyncio
async def test_execute_sync_disconnect_is_transient() -> None:
    opener = SessionOpenerRecorder(FailingListSession([ConnectionClosedError(None, None)]))

    with pytest.raises(RunFailure) as caught:
        await execute_sync(opener)

    assert caught.value.code == "KIWOOM_TRANSIENT"
    assert caught.value.retryable is True


def test_connection_and_token_transport_failures_are_transient() -> None:
    for exc in (
        ConnectionClosedError(None, None),
        InvalidHandshake("unexpected status"),
        TokenTransportError("token request failed: connect error"),
    ):
        failure = to_run_failure(exc, [])
        assert failure.code == "KIWOOM_TRANSIENT", exc
        assert failure.retryable is True, exc


@pytest.mark.asyncio
async def test_execute_search_cancellation_during_list_conditions_propagates() -> None:
    clock = _clock()
    opener = SessionOpenerRecorder(BlockingSession(block_list=asyncio.Event()))
    task = asyncio.create_task(
        execute_search(_job(expr=_condition("A"), refs={"A": ("0", "A")}), opener, clock)
    )

    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_execute_search_cancellation_during_search_propagates() -> None:
    clock = _clock()
    opener = SessionOpenerRecorder(
        BlockingSession(
            block_search=asyncio.Event(),
        )
    )

    async def list_conditions(self) -> list[ConditionItem]:
        return [ConditionItem("0", "A")]

    opener._sessions[0].list_conditions = list_conditions.__get__(opener._sessions[0], BlockingSession)
    task = asyncio.create_task(
        execute_search(_job(expr=_condition("A"), refs={"A": ("0", "A")}), opener, clock)
    )

    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
