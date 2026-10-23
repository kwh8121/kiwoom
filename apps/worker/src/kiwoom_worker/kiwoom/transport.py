from __future__ import annotations

import asyncio
from typing import Protocol

from websockets.asyncio.client import ClientConnection, connect


class Transport(Protocol):
    async def send(self, text: str) -> None: ...

    async def recv(self, timeout: float) -> str: ...

    async def close(self) -> None: ...


class _WebSocketTransport:
    def __init__(self, websocket: ClientConnection) -> None:
        self._websocket = websocket

    async def send(self, text: str) -> None:
        await self._websocket.send(text)

    async def recv(self, timeout: float) -> str:
        from .session import ResponseTimeout

        try:
            message = await asyncio.wait_for(self._websocket.recv(), timeout)
        except TimeoutError:
            raise ResponseTimeout(f"timed out after {timeout}s") from None

        if not isinstance(message, str):
            raise TypeError("expected text websocket message")
        return message

    async def close(self) -> None:
        await self._websocket.close()


async def open_websocket(url: str, *, open_timeout: float = 10) -> Transport:
    websocket = await connect(url, open_timeout=open_timeout, ping_interval=None)
    return _WebSocketTransport(websocket)
