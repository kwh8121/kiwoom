from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from kiwoom_worker.kiwoom.errors import ErrorClass, KiwoomApiError
from kiwoom_worker.kiwoom.token import Credentials, TokenProvider
from tests.fakes import FakeClock

KST = timezone(timedelta(hours=9))


def _kst_timestamp(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y%m%d%H%M%S")


def _token_response(token: str, expires_at: datetime) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "token": token,
            "expires_dt": _kst_timestamp(expires_at),
        },
    )


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_token_cached_until_margin() -> None:
    start = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    clock = FakeClock(start)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _token_response("tok-1", start + timedelta(hours=1))

    async with _client(handler) as client:
        provider = TokenProvider(client, clock)
        creds = Credentials("demo-alias", "demo", "demo-key", "demo-secret")

        assert await provider.get(creds) == "tok-1"
        assert await provider.get(creds) == "tok-1"

    assert calls == 1


@pytest.mark.asyncio
async def test_token_refreshed_inside_margin() -> None:
    start = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    clock = FakeClock(start)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _token_response(f"tok-{calls}", start + timedelta(hours=1, minutes=calls))

    async with _client(handler) as client:
        provider = TokenProvider(client, clock)
        creds = Credentials("demo-alias", "demo", "demo-key", "demo-secret")

        assert await provider.get(creds) == "tok-1"
        await clock.sleep(56 * 60)
        assert await provider.get(creds) == "tok-2"

    assert calls == 2
    assert clock.slept == [56 * 60]


@pytest.mark.asyncio
async def test_force_refresh() -> None:
    start = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    clock = FakeClock(start)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _token_response(f"tok-{calls}", start + timedelta(hours=2))

    async with _client(handler) as client:
        provider = TokenProvider(client, clock)
        creds = Credentials("demo-alias", "demo", "demo-key", "demo-secret")

        assert await provider.get(creds) == "tok-1"
        assert await provider.get(creds, force_refresh=True) == "tok-2"

    assert calls == 2


@pytest.mark.asyncio
async def test_request_shape() -> None:
    start = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["json"] = json.loads(request.content.decode("utf-8"))
        return _token_response("tok-1", start + timedelta(hours=1))

    async with _client(handler) as client:
        provider = TokenProvider(client, FakeClock(start))
        creds = Credentials("demo-alias", "demo", "demo-key", "demo-secret")

        assert await provider.get(creds) == "tok-1"

    assert seen["method"] == "POST"
    assert seen["url"] == "https://mockapi.kiwoom.com/oauth2/token"
    assert seen["headers"]["api-id"] == "au10001"
    assert seen["headers"]["content-type"] == "application/json;charset=UTF-8"
    assert seen["json"] == {
        "grant_type": "client_credentials",
        "appkey": "demo-key",
        "secretkey": "demo-secret",
    }


@pytest.mark.asyncio
async def test_error_8001_is_config() -> None:
    start = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "return_code": 8001,
                "return_msg": "설정값을 확인해 주세요",
            },
        )

    async with _client(handler) as client:
        provider = TokenProvider(client, FakeClock(start))
        creds = Credentials("demo-alias", "demo", "demo-key", "demo-secret")

        with pytest.raises(KiwoomApiError) as excinfo:
            await provider.get(creds)

    assert excinfo.value.error_class is ErrorClass.CONFIG
    assert creds.appkey not in str(excinfo.value)
    assert creds.secretkey not in str(excinfo.value)


@pytest.mark.asyncio
async def test_invalid_expiry_format_is_sanitized() -> None:
    marker = "probe-value-123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "token": "tok-1",
                "expires_dt": marker,
            },
        )

    start = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    async with _client(handler) as client:
        provider = TokenProvider(client, FakeClock(start))
        creds = Credentials("demo-alias", "demo", "demo-key", "demo-secret")

        with pytest.raises(ValueError) as excinfo:
            await provider.get(creds)

    assert str(excinfo.value) == "invalid token expiry format"
    assert marker not in str(excinfo.value)


def test_credentials_repr_hides_keys() -> None:
    creds = Credentials("alias", "demo", "demo-key", "very-secret")

    rendered = repr(creds)

    assert "alias" in rendered
    assert "demo" in rendered
    assert "secret" not in rendered
    assert "demo-key" not in rendered
    assert "very-secret" not in rendered
