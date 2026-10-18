from __future__ import annotations

from datetime import datetime, timedelta


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
