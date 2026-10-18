from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from kiwoom_worker.clock import Clock
from kiwoom_worker.kiwoom.session import ResponseTimeout


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self._now.timestamp()

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self._now += timedelta(seconds=seconds)


class ScriptedTransport:
    def __init__(
        self,
        responder: Callable[[dict], list[str | dict]],
        clock: Clock | None = None,
    ) -> None:
        self._responder = responder
        self._clock = clock
        self._recv_queue: deque[str] = deque()
        self.sent: list[dict] = []
        self.send_times: list[float] = []
        self.closed = False

    async def send(self, text: str) -> None:
        packet = json.loads(text)
        self.sent.append(packet)
        self.send_times.append(self._monotonic())
        for response in self._responder(packet):
            if isinstance(response, str):
                self._recv_queue.append(response)
            else:
                self._recv_queue.append(json.dumps(response, separators=(",", ":")))

    async def recv(self, timeout: float) -> str:
        if not self._recv_queue:
            raise ResponseTimeout(f"timed out after {timeout}s")
        return self._recv_queue.popleft()

    async def close(self) -> None:
        self.closed = True

    def _monotonic(self) -> float:
        if self._clock is None:
            return 0.0
        return self._clock.monotonic()
