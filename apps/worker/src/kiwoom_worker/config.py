from __future__ import annotations

import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from kiwoom_worker.kiwoom.token import Credentials


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str
    worker_id: str
    profiles_file: Path
    transport: Literal["live", "fixture"]
    fixture_file: Path | None
    poll_interval_s: float
    heartbeat_interval_s: float
    lease_seconds: int
    request_interval_s: float
    response_timeout_s: float
    max_pages: int
    rate_limit_retries: int
    run_timeout_s: float


def load_settings(env: Mapping[str, str]) -> WorkerSettings:
    database_url = _require_str(env, "KIWOOM_WORKER_DATABASE_URL")
    worker_id = _require_str(env, "KIWOOM_WORKER_ID")
    profiles_file = Path(_require_str(env, "KIWOOM_WORKER_PROFILES_FILE"))
    transport = _get_str(env, "KIWOOM_WORKER_TRANSPORT", "live")
    if transport not in {"live", "fixture"}:
        raise ConfigError("KIWOOM_WORKER_TRANSPORT must be 'live' or 'fixture'")

    fixture_value = _get_str(env, "KIWOOM_WORKER_FIXTURE_FILE")
    fixture_file = Path(fixture_value) if fixture_value is not None else None

    settings = WorkerSettings(
        database_url=database_url,
        worker_id=worker_id,
        profiles_file=profiles_file,
        transport=transport,
        fixture_file=fixture_file,
        poll_interval_s=_get_float(env, "KIWOOM_WORKER_POLL_INTERVAL_S", 3.0),
        heartbeat_interval_s=_get_float(env, "KIWOOM_WORKER_HEARTBEAT_INTERVAL_S", 15.0),
        lease_seconds=_get_int(env, "KIWOOM_WORKER_LEASE_SECONDS", 60),
        request_interval_s=_get_float(env, "KIWOOM_WORKER_REQUEST_INTERVAL_S", 0.25),
        response_timeout_s=_get_float(env, "KIWOOM_WORKER_RESPONSE_TIMEOUT_S", 10.0),
        max_pages=_get_int(env, "KIWOOM_WORKER_MAX_PAGES", 50),
        rate_limit_retries=_get_int(env, "KIWOOM_WORKER_RATE_LIMIT_RETRIES", 3),
        run_timeout_s=_get_float(env, "KIWOOM_WORKER_RUN_TIMEOUT_S", 120.0),
    )
    if settings.transport == "fixture":
        if settings.fixture_file is None:
            raise ConfigError("KIWOOM_WORKER_FIXTURE_FILE is required for fixture transport")
        if not _database_is_local(settings.database_url):
            raise ConfigError("fixture transport requires a localhost or 127.0.0.1 database URL")
    return settings


def load_profiles(path: Path) -> dict[str, Credentials]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & ~0o600:
        raise ConfigError("profiles file permissions must not be wider than 0600")

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError("profiles.toml must define [profiles.<alias>] entries")

    loaded: dict[str, Credentials] = {}
    for alias, raw in profiles.items():
        if not isinstance(alias, str) or not isinstance(raw, dict):
            raise ConfigError("invalid profile entry")
        mode_value = raw.get("mode")
        if mode_value not in {"real", "demo"}:
            raise ConfigError(f"profile {alias!r} has invalid mode")
        appkey = raw.get("appkey")
        secretkey = raw.get("secretkey")
        if not isinstance(appkey, str) or not isinstance(secretkey, str):
            raise ConfigError(f"profile {alias!r} must include string appkey and secretkey")
        loaded[alias] = Credentials(alias=alias, mode=mode_value, appkey=appkey, secretkey=secretkey)
    return loaded


def _database_is_local(database_url: str) -> bool:
    try:
        params = conninfo_to_dict(database_url)
    except ProgrammingError:
        raise ConfigError("KIWOOM_WORKER_DATABASE_URL is invalid") from None

    if params.get("service"):
        return False

    hosts = params.get("host")
    if not isinstance(hosts, str) or not hosts:
        return False
    if any(host.lower() not in {"localhost", "127.0.0.1"} for host in hosts.split(",")):
        return False

    host_addresses = params.get("hostaddr")
    if host_addresses:
        if not isinstance(host_addresses, str):
            return False
        if any(address != "127.0.0.1" for address in host_addresses.split(",")):
            return False
    return True


def _get_str(env: Mapping[str, str], key: str, default: str | None = None) -> str | None:
    value = env.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string")
    return value


def _require_str(env: Mapping[str, str], key: str) -> str:
    value = _get_str(env, key)
    if value is None:
        raise ConfigError(f"{key} is required")
    return value


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a float string")
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a float") from exc


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be an integer string")
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
