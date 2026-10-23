from __future__ import annotations

from pathlib import Path

import pytest

from kiwoom_worker.config import (
    MAX_LEASE_SECONDS,
    ConfigError,
    load_profiles,
    load_settings,
)


def test_profiles_file_must_be_0600(tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.demo]
mode = "demo"
appkey = "demo-key"
secretkey = "demo-secret"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o644)

    with pytest.raises(ConfigError, match="0600"):
        load_profiles(path)


def _live_env(**overrides: str) -> dict[str, str]:
    env = {
        "KIWOOM_WORKER_DATABASE_URL": "postgresql://worker:secret@db.example.invalid:5432/postgres",
        "KIWOOM_WORKER_ID": "worker-1",
        "KIWOOM_WORKER_PROFILES_FILE": "/tmp/profiles.toml",
    }
    env.update(overrides)
    return env


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("KIWOOM_WORKER_POLL_INTERVAL_S", "0"),
        ("KIWOOM_WORKER_HEARTBEAT_INTERVAL_S", "-1"),
        ("KIWOOM_WORKER_LEASE_SECONDS", "0"),
        ("KIWOOM_WORKER_RESPONSE_TIMEOUT_S", "0"),
        ("KIWOOM_WORKER_MAX_PAGES", "0"),
        ("KIWOOM_WORKER_RUN_TIMEOUT_S", "-5"),
    ],
)
def test_non_positive_settings_are_rejected(key: str, value: str) -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        load_settings(_live_env(**{key: value}))


@pytest.mark.parametrize("key", ["KIWOOM_WORKER_REQUEST_INTERVAL_S", "KIWOOM_WORKER_RATE_LIMIT_RETRIES"])
def test_negative_settings_are_rejected(key: str) -> None:
    with pytest.raises(ConfigError, match="must not be negative"):
        load_settings(_live_env(**{key: "-1"}))


def test_request_interval_may_be_zero() -> None:
    settings = load_settings(_live_env(KIWOOM_WORKER_REQUEST_INTERVAL_S="0"))
    assert settings.request_interval_s == 0


def test_lease_seconds_capped_to_rpc_limit() -> None:
    assert load_settings(_live_env(KIWOOM_WORKER_LEASE_SECONDS=str(MAX_LEASE_SECONDS))).lease_seconds == MAX_LEASE_SECONDS
    with pytest.raises(ConfigError, match=str(MAX_LEASE_SECONDS)):
        load_settings(_live_env(KIWOOM_WORKER_LEASE_SECONDS=str(MAX_LEASE_SECONDS + 1)))


def test_fixture_transport_requires_local_db() -> None:
    with pytest.raises(ConfigError, match="localhost"):
        load_settings(
            {
                "KIWOOM_WORKER_DATABASE_URL": "postgresql://worker:secret@db.example.invalid:5432/postgres",
                "KIWOOM_WORKER_ID": "worker-1",
                "KIWOOM_WORKER_PROFILES_FILE": "/tmp/profiles.toml",
                "KIWOOM_WORKER_TRANSPORT": "fixture",
                "KIWOOM_WORKER_FIXTURE_FILE": "/tmp/e2e_market.json",
            }
        )


@pytest.mark.parametrize(
    "query",
    ["host=remote.example.invalid", "hostaddr=203.0.113.8", "service=remote"],
)
def test_fixture_transport_rejects_libpq_remote_overrides(query: str) -> None:
    with pytest.raises(ConfigError, match="localhost"):
        load_settings(
            {
                "KIWOOM_WORKER_DATABASE_URL": f"postgresql://worker:masked@localhost/postgres?{query}",
                "KIWOOM_WORKER_ID": "worker-1",
                "KIWOOM_WORKER_PROFILES_FILE": "/tmp/profiles.toml",
                "KIWOOM_WORKER_TRANSPORT": "fixture",
                "KIWOOM_WORKER_FIXTURE_FILE": "/tmp/e2e_market.json",
            }
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [("PGHOST", "remote.example.invalid"), ("PGHOSTADDR", "203.0.113.8"), ("PGSERVICE", "remote")],
)
def test_fixture_transport_rejects_remote_libpq_environment(name: str, value: str) -> None:
    env = {
        "KIWOOM_WORKER_DATABASE_URL": "postgresql://worker:masked@localhost/postgres",
        "KIWOOM_WORKER_ID": "worker-1",
        "KIWOOM_WORKER_PROFILES_FILE": "/tmp/profiles.toml",
        "KIWOOM_WORKER_TRANSPORT": "fixture",
        "KIWOOM_WORKER_FIXTURE_FILE": "/tmp/e2e_market.json",
        name: value,
    }

    with pytest.raises(ConfigError, match="localhost"):
        load_settings(env)


def test_profiles_file_rejects_owner_execute_permissions(tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    path.write_text(
        '[profiles.demo]\nmode = "demo"\nappkey = "key"\nsecretkey = "secret"\n',
        encoding="utf-8",
    )
    path.chmod(0o700)

    with pytest.raises(ConfigError, match="0600"):
        load_profiles(path)
