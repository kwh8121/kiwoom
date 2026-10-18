from __future__ import annotations

from pathlib import Path

import pytest

from kiwoom_worker.config import ConfigError, load_profiles, load_settings


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
