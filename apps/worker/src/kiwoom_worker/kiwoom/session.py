from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

from kiwoom_worker.clock import Clock

from .allowlist import assert_outgoing_allowed
from .errors import ErrorClass, KiwoomApiError, classify, resolve_return_code
from .parse import Member, parse_member
from .transport import Transport


class ProtocolError(RuntimeError):
    pass


class ResponseTimeout(TimeoutError):
    pass


class IncompletePagination(RuntimeError):
    pass


@dataclass(frozen=True)
class ConditionItem:
    seq: str
    name: str


@dataclass(frozen=True)
class SearchResult:
    seq: str
    started_at: datetime
    completed_at: datetime
    page_count: int
    members: list[Member]


STATE_NEW = "NEW"
STATE_LOGGED_IN = "LOGGED_IN"
STATE_CONDITIONS_READY = "CONDITIONS_READY"
STATE_UNUSABLE = "UNUSABLE"


class ConditionSession:
    def __init__(
        self,
        transport: Transport,
        *,
        clock: Clock,
        request_interval_s: float = 0.25,
        response_timeout_s: float = 10.0,
        max_pages: int = 50,
        rate_limit_retries: int = 3,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._request_interval_s = request_interval_s
        self._response_timeout_s = response_timeout_s
        self._max_pages = max_pages
        self._rate_limit_retries = rate_limit_retries
        self._state = STATE_NEW
        self._last_search_sent_at: float | None = None
        self.skipped_bare_messages = 0
        self._search_lock = asyncio.Lock()

    async def login(self, token: str) -> None:
        self._ensure_usable()
        if self._state != STATE_NEW:
            raise ProtocolError("LOGIN_OUT_OF_ORDER")
        await self._send_packet({"trnm": "LOGIN", "token": token})
        response = await self._recv_by_trnm("LOGIN")
        self._raise_if_error(response)
        self._state = STATE_LOGGED_IN

    async def list_conditions(self) -> list[ConditionItem]:
        self._ensure_usable()
        if self._state == STATE_NEW:
            raise ProtocolError("LOGIN_REQUIRED")
        if self._state != STATE_LOGGED_IN:
            raise ProtocolError("CNSRLST_OUT_OF_ORDER")
        await self._send_packet({"trnm": "CNSRLST"})
        response = await self._recv_by_trnm("CNSRLST")
        self._raise_if_error(response)

        rows = response.get("data")
        if not isinstance(rows, list):
            raise TypeError("CNSRLST data must be a list")

        conditions: list[ConditionItem] = []
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or not isinstance(row[0], str)
                or not isinstance(row[1], str)
            ):
                raise TypeError("CNSRLST row must be [seq, name]")
            conditions.append(ConditionItem(seq=row[0], name=row[1]))

        self._state = STATE_CONDITIONS_READY
        return conditions

    async def search(self, seq: str) -> SearchResult:
        self._ensure_usable()
        if self._state == STATE_NEW:
            raise ProtocolError("LOGIN_REQUIRED")
        if self._state != STATE_CONDITIONS_READY:
            raise ProtocolError("CNSRLST_REQUIRED")

        async with self._search_lock:
            self._ensure_usable()
            if self._state == STATE_NEW:
                raise ProtocolError("LOGIN_REQUIRED")
            if self._state != STATE_CONDITIONS_READY:
                raise ProtocolError("CNSRLST_REQUIRED")

            started_at = self._clock.now()
            members_by_code: dict[str, Member] = {}
            page_count = 0
            next_key: str | None = None

            while True:
                if page_count >= self._max_pages:
                    raise IncompletePagination("search exceeded max_pages")

                response = await self._request_search_page(seq=seq, next_key=next_key)
                page_count += 1

                rows = self._extract_rows(response)
                for row in rows:
                    member = parse_member(row)
                    members_by_code.setdefault(member.code, member)

                cont_yn = response.get("cont_yn")
                if cont_yn == "N":
                    return SearchResult(
                        seq=seq,
                        started_at=started_at,
                        completed_at=self._clock.now(),
                        page_count=page_count,
                        members=list(members_by_code.values()),
                    )
                if cont_yn != "Y":
                    raise ProtocolError("invalid cont_yn")

                raw_next_key = response.get("next_key")
                if not isinstance(raw_next_key, str) or not raw_next_key:
                    raise IncompletePagination("cont_yn=Y requires next_key")
                next_key = raw_next_key

    async def _request_search_page(self, *, seq: str, next_key: str | None) -> dict[str, object]:
        retries = 0

        while True:
            packet = {
                "trnm": "CNSRREQ",
                "seq": seq,
                "search_type": "0",
                "stex_tp": "K",
            }
            if next_key is not None:
                packet["cont_yn"] = "Y"
                packet["next_key"] = next_key

            try:
                await self._send_packet(packet)
                response = await self._recv_search_response(seq)
            except (ResponseTimeout, asyncio.CancelledError):
                await self._invalidate_session()
                raise

            code = self._require_return_code(response)
            if code == 0:
                return response

            error_class = classify(code)
            if error_class is ErrorClass.RATE_LIMIT and retries < self._rate_limit_retries:
                delay_s = 1.0 * (2**retries)
                retries += 1
                await self._clock.sleep(delay_s)
                continue

            raise KiwoomApiError(code, self._coerce_message(response.get("return_msg")))

    async def _send_packet(self, packet: dict[str, object]) -> None:
        assert_outgoing_allowed(packet)
        if packet.get("trnm") == "CNSRREQ":
            await self._pace_search_requests()
        await self._transport.send(json.dumps(packet, separators=(",", ":")))
        if packet.get("trnm") == "CNSRREQ":
            self._last_search_sent_at = self._clock.monotonic()

    async def _pace_search_requests(self) -> None:
        if self._last_search_sent_at is None:
            return
        elapsed = self._clock.monotonic() - self._last_search_sent_at
        remaining = self._request_interval_s - elapsed
        if remaining > 0:
            await self._clock.sleep(remaining)

    async def _recv_by_trnm(self, expected_trnm: str) -> dict[str, object]:
        while True:
            response = self._decode_packet(await self._transport.recv(self._response_timeout_s))
            trnm = response.get("trnm")
            if trnm == "PING":
                await self._send_packet({"trnm": "PING"})
                continue
            if trnm == expected_trnm:
                return response

    async def _recv_search_response(self, seq: str) -> dict[str, object]:
        while True:
            response = self._decode_packet(await self._transport.recv(self._response_timeout_s))
            trnm = response.get("trnm")
            if trnm == "PING":
                await self._send_packet({"trnm": "PING"})
                continue
            if trnm != "CNSRREQ":
                continue

            response_seq = response.get("seq")
            if response_seq == seq:
                return response

            code = resolve_return_code(response.get("return_code"), response.get("return_msg"))
            if response_seq is None and code not in (None, 0):
                return response
            if response_seq is None:
                self.skipped_bare_messages += 1

    def _extract_rows(self, response: dict[str, object]) -> list[dict[str, object]]:
        data = response.get("data")
        cont_yn = response.get("cont_yn")
        if data is None:
            if cont_yn == "N":
                return []
            raise TypeError("CNSRREQ data missing")
        if not isinstance(data, list):
            raise TypeError("CNSRREQ data must be a list")
        if cont_yn == "Y" and not data:
            raise IncompletePagination("empty continuation page")

        rows: list[dict[str, object]] = []
        for row in data:
            if not isinstance(row, dict):
                raise TypeError("CNSRREQ rows must be objects")
            rows.append(row)
        return rows

    def _raise_if_error(self, response: dict[str, object]) -> None:
        code = self._require_return_code(response)
        if code == 0:
            return
        classify(code)
        raise KiwoomApiError(code, self._coerce_message(response.get("return_msg")))

    def _ensure_usable(self) -> None:
        if self._state == STATE_UNUSABLE:
            raise ProtocolError("SESSION_UNUSABLE")

    async def _invalidate_session(self) -> None:
        self._state = STATE_UNUSABLE
        await self._transport.close()

    def _decode_packet(self, raw_message: str) -> dict[str, object]:
        payload = json.loads(raw_message)
        if not isinstance(payload, dict):
            raise TypeError("websocket payload must be an object")
        return payload

    @staticmethod
    def _coerce_message(value: object) -> str:
        if isinstance(value, str) and value:
            return value
        return "Kiwoom websocket request failed"

    @staticmethod
    def _require_return_code(response: dict[str, object]) -> int:
        if "return_code" not in response:
            raise ProtocolError("missing return_code")
        code = resolve_return_code(response.get("return_code"), response.get("return_msg"))
        if code is None:
            raise ProtocolError("invalid return_code")
        return code
