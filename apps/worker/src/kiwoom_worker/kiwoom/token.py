from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

import httpx

from kiwoom_worker.clock import Clock

from .allowlist import assert_api_id_allowed
from .errors import KiwoomApiError, classify, resolve_return_code

TOKEN_API_ID = "au10001"
TOKEN_PATH = "/oauth2/token"
KST = timezone(timedelta(hours=9))

BASE_URLS = {"real": "https://api.kiwoom.com", "demo": "https://mockapi.kiwoom.com"}
WS_URLS = {
    "real": "wss://api.kiwoom.com:10000/api/dostk/websocket",
    "demo": "wss://mockapi.kiwoom.com:10000/api/dostk/websocket",
}


@dataclass(frozen=True)
class Credentials:
    alias: str
    mode: Literal["real", "demo"]
    appkey: str
    secretkey: str

    def __repr__(self) -> str:
        return (
            "Credentials("
            f"alias={self.alias!r}, mode={self.mode!r}, credentials='[redacted]'"
            ")"
        )


@dataclass(frozen=True)
class _CachedToken:
    token: str
    expires_at: datetime


class TokenProvider:
    def __init__(self, client: httpx.AsyncClient, clock: Clock, refresh_margin_s: float = 300) -> None:
        self._client = client
        self._clock = clock
        self._refresh_margin = timedelta(seconds=refresh_margin_s)
        self._cache: dict[str, _CachedToken] = {}

    async def get(self, creds: Credentials, *, force_refresh: bool = False) -> str:
        cached = self._cache.get(creds.alias)
        now = self._clock.now()
        if not force_refresh and cached is not None and now < cached.expires_at - self._refresh_margin:
            return cached.token

        token, expires_at = await self._issue_token(creds)
        self._cache[creds.alias] = _CachedToken(token=token, expires_at=expires_at)
        return token

    async def _issue_token(self, creds: Credentials) -> tuple[str, datetime]:
        assert_api_id_allowed(TOKEN_API_ID)
        url = f"{BASE_URLS[creds.mode]}{TOKEN_PATH}"
        payload = {
            "grant_type": "client_credentials",
            "appkey": creds.appkey,
            "secretkey": creds.secretkey,
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "api-id": TOKEN_API_ID,
            "Content-Type": "application/json;charset=UTF-8",
        }

        try:
            response = await self._client.post(url, headers=headers, content=body)
            raw_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            message = _sanitize_message(str(exc), creds)
            raise RuntimeError(f"token request failed: {message}") from None

        if not isinstance(raw_payload, dict):
            raise TypeError("token request failed: invalid response payload")

        payload_dict = raw_payload
        code = resolve_return_code(payload_dict.get("return_code"), payload_dict.get("return_msg"))
        if code not in (None, 0):
            message = _sanitize_message(_coerce_message(payload_dict.get("return_msg")), creds)
            classify(code)
            raise KiwoomApiError(code, message)

        token = payload_dict.get("token")
        expires_dt = payload_dict.get("expires_dt")
        if not isinstance(token, str) or not isinstance(expires_dt, str):
            raise TypeError("token request failed: missing token payload fields")

        return token, _parse_expires_at(expires_dt)


def _parse_expires_at(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        raise ValueError("invalid token expiry format") from None
    return parsed.replace(tzinfo=KST).astimezone(UTC)


def _coerce_message(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "Kiwoom token request failed"


def _sanitize_message(message: str, creds: Credentials) -> str:
    sanitized = message
    for secret in (creds.appkey, creds.secretkey):
        if secret:
            sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized
