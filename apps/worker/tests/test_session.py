from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kiwoom_worker.kiwoom.errors import ErrorClass, KiwoomApiError
from kiwoom_worker.kiwoom.session import (
    ConditionItem,
    ConditionSession,
    IncompletePagination,
    ProtocolError,
    ResponseTimeout,
)
from tests.fakes import FakeClock, ScriptedTransport

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phase0_cnsrreq_seq1.json"
SEARCH_FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
_USE_FIXTURE = object()


def _make_clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 18, 0, 0, tzinfo=UTC))


def _login_ok() -> dict:
    return {"trnm": "LOGIN", "return_code": 0, "return_msg": ""}


def _list_ok(rows: list[list[str]] | None = None) -> dict:
    return {
        "trnm": "CNSRLST",
        "return_code": 0,
        "return_msg": "",
        "data": rows if rows is not None else [["0", "급등주포착검색"], ["1", "눌림후반등자리"]],
    }


def _search_ok(
    *,
    seq: str = "1",
    cont_yn: str = "N",
    next_key: str = "",
    data: object = _USE_FIXTURE,
) -> dict:
    payload = copy.deepcopy(SEARCH_FIXTURE)
    payload["seq"] = seq
    payload["cont_yn"] = cont_yn
    payload["next_key"] = next_key
    payload["return_code"] = 0
    payload["return_msg"] = ""
    payload["data"] = copy.deepcopy(payload["data"] if data is _USE_FIXTURE else data)
    return payload


def _error_packet(trnm: str, code: int, message: str) -> dict:
    return {"trnm": trnm, "return_code": code, "return_msg": message}


def _session_with_responder(responder) -> tuple[ConditionSession, ScriptedTransport, FakeClock]:
    clock = _make_clock()
    transport = ScriptedTransport(responder, clock=clock)
    session = ConditionSession(transport, clock=clock)
    return session, transport, clock


class BlockingSearchTransport:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._recv_queue: asyncio.Queue[str] = asyncio.Queue()
        self.first_search_blocked = asyncio.Event()
        self.release_first_search = asyncio.Event()
        self.closed = False
        self._first_search_seen = False

    async def send(self, text: str) -> None:
        packet = json.loads(text)
        self.sent.append(packet)
        trnm = packet["trnm"]
        if trnm == "LOGIN":
            await self._recv_queue.put(json.dumps(_login_ok(), separators=(",", ":")))
            return
        if trnm == "CNSRLST":
            await self._recv_queue.put(json.dumps(_list_ok(), separators=(",", ":")))
            return
        if trnm != "CNSRREQ":
            return

        if not self._first_search_seen:
            self._first_search_seen = True
            self.first_search_blocked.set()
            await self.release_first_search.wait()

        payload = _search_ok(seq=str(packet["seq"]), data=[])
        await self._recv_queue.put(json.dumps(payload, separators=(",", ":")))

    async def recv(self, timeout: float) -> str:
        try:
            return await asyncio.wait_for(self._recv_queue.get(), timeout)
        except TimeoutError:
            raise ResponseTimeout(f"timed out after {timeout}s") from None

    async def close(self) -> None:
        self.closed = True


class CancelDuringSearchTransport:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False
        self._recv_queue: asyncio.Queue[str] = asyncio.Queue()
        self.search_recv_started = asyncio.Event()
        self.release_search_recv = asyncio.Event()

    async def send(self, text: str) -> None:
        packet = json.loads(text)
        self.sent.append(packet)
        if packet["trnm"] == "LOGIN":
            await self._recv_queue.put(json.dumps(_login_ok(), separators=(",", ":")))
        elif packet["trnm"] == "CNSRLST":
            await self._recv_queue.put(json.dumps(_list_ok(), separators=(",", ":")))

    async def recv(self, timeout: float) -> str:
        if any(packet["trnm"] == "CNSRREQ" for packet in self.sent):
            self.search_recv_started.set()
            await self.release_search_recv.wait()
        try:
            return await asyncio.wait_for(self._recv_queue.get(), timeout)
        except TimeoutError:
            raise ResponseTimeout(f"timed out after {timeout}s") from None

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_list_before_login_raises() -> None:
    session, _transport, _clock = _session_with_responder(lambda _packet: [_list_ok()])

    with pytest.raises(ProtocolError, match="LOGIN_REQUIRED"):
        await session.list_conditions()


@pytest.mark.asyncio
async def test_search_before_login_raises() -> None:
    session, _transport, _clock = _session_with_responder(lambda _packet: [_search_ok(seq="1")])

    with pytest.raises(ProtocolError, match="LOGIN_REQUIRED"):
        await session.search("1")


@pytest.mark.asyncio
async def test_failed_login_remains_retryable() -> None:
    login_attempts = 0

    def responder(packet: dict) -> list[str | dict]:
        nonlocal login_attempts
        if packet["trnm"] != "LOGIN":
            return []
        login_attempts += 1
        if login_attempts == 1:
            return [_error_packet("LOGIN", 8010, "접속 단말 정보가 없습니다")]
        return [_login_ok()]

    session, transport, _clock = _session_with_responder(responder)

    with pytest.raises(KiwoomApiError):
        await session.login("demo-token")

    await session.login("demo-token")

    assert [packet["trnm"] for packet in transport.sent] == ["LOGIN", "LOGIN"]


@pytest.mark.asyncio
async def test_login_after_list_raises() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        return [_list_ok()]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(ProtocolError, match="LOGIN_OUT_OF_ORDER"):
        await session.login("demo-token")


@pytest.mark.asyncio
async def test_login_sends_token_and_accepts_ack() -> None:
    session, transport, _clock = _session_with_responder(lambda _packet: [_login_ok()])

    await session.login("demo-token")

    assert transport.sent == [{"trnm": "LOGIN", "token": "demo-token"}]


@pytest.mark.asyncio
async def test_login_error_8010_is_ip_device() -> None:
    session, _transport, _clock = _session_with_responder(
        lambda _packet: [_error_packet("LOGIN", 8010, "접속 단말 정보가 없습니다")]
    )

    with pytest.raises(KiwoomApiError) as exc_info:
        await session.login("demo-token")

    assert exc_info.value.error_class is ErrorClass.IP_DEVICE


@pytest.mark.asyncio
async def test_ping_is_echoed() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        return [{"trnm": "PING"}, _list_ok()]

    session, transport, _clock = _session_with_responder(responder)

    await session.login("demo-token")
    await session.list_conditions()

    assert transport.sent[-1] == {"trnm": "PING"}


@pytest.mark.asyncio
async def test_search_before_list_raises() -> None:
    session, _transport, _clock = _session_with_responder(lambda _packet: [_login_ok()])
    await session.login("demo-token")

    with pytest.raises(ProtocolError, match="CNSRLST_REQUIRED"):
        await session.search("1")


@pytest.mark.asyncio
async def test_list_parses_array_rows() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        return [_list_ok()]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")

    assert await session.list_conditions() == [
        ConditionItem("0", "급등주포착검색"),
        ConditionItem("1", "눌림후반등자리"),
    ]


@pytest.mark.asyncio
async def test_bare_message_skipped() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [{"trnm": "CNSRREQ"}, _search_ok(seq="1")]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    result = await session.search("1")

    assert len(result.members) == 28
    assert session.skipped_bare_messages == 1


@pytest.mark.asyncio
async def test_stale_other_seq_ignored() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq="0"), _search_ok(seq="1")]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    result = await session.search("1")

    assert result.seq == "1"
    assert len(result.members) == 28


@pytest.mark.asyncio
async def test_null_data_is_zero_rows() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq="1", data=None)]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    result = await session.search("1")

    assert result.members == []
    assert result.page_count == 1


@pytest.mark.asyncio
async def test_empty_continuation_page_is_incomplete() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq="1", cont_yn="Y", next_key="k1", data=[])]

    session, transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(IncompletePagination):
        await session.search("1")

    search_packets = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]
    assert len(search_packets) == 1


@pytest.mark.asyncio
async def test_null_data_without_return_code_is_protocol_error() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        payload = _search_ok(seq="1", data=None)
        del payload["return_code"]
        return [payload]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(ProtocolError, match="return_code"):
        await session.search("1")


@pytest.mark.asyncio
async def test_list_missing_return_code_is_protocol_error() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        payload = _list_ok()
        del payload["return_code"]
        return [payload]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")

    with pytest.raises(ProtocolError, match="return_code"):
        await session.list_conditions()


@pytest.mark.asyncio
async def test_pagination_same_connection() -> None:
    page_one = _search_ok(
        seq="1",
        cont_yn="Y",
        next_key="k1",
        data=[
            {"9001": "A001210", "302": "금호전기", "10": "000009530", "12": "00000781"},
            {"9001": "A005160", "302": "동국산업", "10": "000004340", "12": "00000864"},
        ],
    )
    page_two = _search_ok(
        seq="1",
        data=[
            {"9001": "A005160", "302": "동국산업", "10": "000004340", "12": "00000864"},
            {"9001": "A009470", "302": "삼화전기", "10": "000031100", "12": "00000651"},
        ],
    )

    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        if packet.get("cont_yn") == "Y":
            return [page_two]
        return [page_one]

    session, transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    result = await session.search("1")

    search_packets = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]
    assert search_packets[1]["cont_yn"] == "Y"
    assert search_packets[1]["next_key"] == "k1"
    assert result.page_count == 2
    assert [member.code for member in result.members] == ["001210", "005160", "009470"]


@pytest.mark.asyncio
async def test_cont_y_without_next_key_incomplete() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq="1", cont_yn="Y", next_key="")]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(IncompletePagination):
        await session.search("1")


@pytest.mark.asyncio
async def test_max_pages_incomplete() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq="1", cont_yn="Y", next_key="k1")]

    _base_session, transport, clock = _session_with_responder(responder)
    session = ConditionSession(transport, clock=clock, max_pages=1)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(IncompletePagination):
        await session.search("1")


@pytest.mark.asyncio
async def test_rate_limit_then_success() -> None:
    attempts = 0

    def responder(packet: dict) -> list[str | dict]:
        nonlocal attempts
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        attempts += 1
        if attempts == 1:
            return [_error_packet("CNSRREQ", 105110, "허용된 요청 건수를 초과하였습니다")]
        return [_search_ok(seq="1")]

    session, transport, clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    result = await session.search("1")

    assert len(result.members) == 28
    assert clock.slept[0] >= 1.0
    assert len([packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]) == 2


@pytest.mark.asyncio
async def test_rate_limit_exhausted() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_error_packet("CNSRREQ", 105110, "허용된 요청 건수를 초과하였습니다")]

    session, _transport, clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(KiwoomApiError) as exc_info:
        await session.search("1")

    assert exc_info.value.error_class is ErrorClass.RATE_LIMIT
    assert clock.slept == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_error_without_seq_attributed() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_error_packet("CNSRREQ", 900004, "존재하지 않는 일련번호입니다")]

    session, _transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(KiwoomApiError) as exc_info:
        await session.search("1")

    assert exc_info.value.error_class is ErrorClass.CONDITION_MISSING


@pytest.mark.asyncio
async def test_requests_spaced() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq=packet["seq"], data=[])]

    session, transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()
    await session.search("1")
    await session.search("2")

    search_send_times = [
        send_time
        for packet, send_time in zip(transport.sent, transport.send_times, strict=True)
        if packet["trnm"] == "CNSRREQ"
    ]
    assert search_send_times[1] - search_send_times[0] >= 0.25


@pytest.mark.asyncio
async def test_response_timeout() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return []

    session, transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()

    with pytest.raises(ResponseTimeout):
        await session.search("1")

    sent_count = len(transport.sent)
    assert transport.closed is True
    with pytest.raises(ProtocolError, match="SESSION_UNUSABLE"):
        await session.search("2")
    assert len(transport.sent) == sent_count


@pytest.mark.asyncio
async def test_all_packets_allowlisted() -> None:
    def responder(packet: dict) -> list[str | dict]:
        if packet["trnm"] == "LOGIN":
            return [_login_ok()]
        if packet["trnm"] == "CNSRLST":
            return [_list_ok()]
        return [_search_ok(seq=packet["seq"], data=[])]

    session, transport, _clock = _session_with_responder(responder)
    await session.login("demo-token")
    await session.list_conditions()
    await session.search("1")
    await session.search("2")

    packets = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]
    assert packets
    assert all(packet["search_type"] == "0" for packet in packets)
    assert all(packet["stex_tp"] == "K" for packet in packets)


@pytest.mark.asyncio
async def test_concurrent_searches_share_one_in_flight_request() -> None:
    clock = _make_clock()
    transport = BlockingSearchTransport()
    session = ConditionSession(transport, clock=clock, request_interval_s=0.0)

    await session.login("demo-token")
    await session.list_conditions()

    first_task = asyncio.create_task(session.search("1"))
    await transport.first_search_blocked.wait()

    second_task = asyncio.create_task(session.search("2"))
    await asyncio.sleep(0)

    sent_searches = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]
    assert [packet["seq"] for packet in sent_searches] == ["1"]

    transport.release_first_search.set()

    first_result, second_result = await asyncio.gather(first_task, second_task)
    sent_searches = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]

    assert [packet["seq"] for packet in sent_searches] == ["1", "2"]
    assert first_result.seq == "1"
    assert second_result.seq == "2"


@pytest.mark.asyncio
async def test_cancelled_search_invalidates_transport() -> None:
    clock = _make_clock()
    transport = CancelDuringSearchTransport()
    session = ConditionSession(transport, clock=clock, request_interval_s=0.0)

    await session.login("demo-token")
    await session.list_conditions()

    search_task = asyncio.create_task(session.search("1"))
    await transport.search_recv_started.wait()

    search_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await search_task

    sent_count = len(transport.sent)
    assert transport.closed is True
    with pytest.raises(ProtocolError, match="SESSION_UNUSABLE"):
        await session.search("2")
    assert len(transport.sent) == sent_count


@pytest.mark.asyncio
async def test_waiting_search_fails_after_prior_search_invalidates_session() -> None:
    clock = _make_clock()
    transport = CancelDuringSearchTransport()
    session = ConditionSession(transport, clock=clock, request_interval_s=0.0)

    await session.login("demo-token")
    await session.list_conditions()

    first_task = asyncio.create_task(session.search("1"))
    await transport.search_recv_started.wait()

    second_task = asyncio.create_task(session.search("2"))
    await asyncio.sleep(0)

    sent_searches = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]
    assert [packet["seq"] for packet in sent_searches] == ["1"]

    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task

    transport.release_search_recv.set()

    with pytest.raises(ProtocolError, match="SESSION_UNUSABLE"):
        await asyncio.wait_for(second_task, timeout=1.0)

    sent_searches = [packet for packet in transport.sent if packet["trnm"] == "CNSRREQ"]
    assert [packet["seq"] for packet in sent_searches] == ["1"]
