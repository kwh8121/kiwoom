from __future__ import annotations

import json
from collections import deque
from typing import Any

from .session import ResponseTimeout


class FixtureTransport:
    def __init__(self, market: dict[str, Any]) -> None:
        self._conditions = market["conditions"]
        self._results = market["results"]
        self._recv_queue: deque[str] = deque()
        self._closed = False

    async def send(self, text: str) -> None:
        packet = json.loads(text)
        trnm = packet.get("trnm")
        if trnm == "LOGIN":
            self._enqueue({"trnm": "LOGIN", "return_code": 0})
            return
        if trnm == "CNSRLST":
            self._enqueue({"trnm": "CNSRLST", "return_code": 0, "data": self._conditions})
            return
        if trnm == "CNSRREQ":
            seq = packet.get("seq")
            rows = self._results.get(seq)
            if not isinstance(seq, str) or not isinstance(rows, list):
                self._enqueue({"trnm": "CNSRREQ", "return_code": 900004, "return_msg": "존재하지 않는 일련번호입니다"})
                return

            next_key = packet.get("next_key")
            if next_key is None:
                if len(rows) <= 1:
                    self._enqueue({"trnm": "CNSRREQ", "seq": seq, "return_code": 0, "cont_yn": "N", "data": rows})
                    return
                self._enqueue(
                    {
                        "trnm": "CNSRREQ",
                        "seq": seq,
                        "return_code": 0,
                        "cont_yn": "Y",
                        "next_key": "1",
                        "data": [rows[0]],
                    }
                )
                return

            self._enqueue({"trnm": "CNSRREQ"})
            self._enqueue(
                {
                    "trnm": "CNSRREQ",
                    "seq": seq,
                    "return_code": 0,
                    "cont_yn": "N",
                    "data": rows[1:],
                }
            )
            return

        self._enqueue({"trnm": str(trnm), "return_code": 1999, "return_msg": "지원하지 않는 메시지입니다"})

    async def recv(self, timeout: float) -> str:
        if not self._recv_queue:
            raise ResponseTimeout(f"timed out after {timeout}s")
        return self._recv_queue.popleft()

    async def close(self) -> None:
        self._closed = True

    def _enqueue(self, payload: dict[str, object]) -> None:
        self._recv_queue.append(json.dumps(payload, separators=(",", ":")))
