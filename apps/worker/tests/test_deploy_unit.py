"""Static assertions on the worker's systemd unit.

The unit is the worker's only runtime boundary on the host, and nothing else in
the suite reads it. These assertions keep the hardening from being dropped in
an edit and keep the stop timeout tied to the run budget it has to outlast.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kiwoom_worker.config import load_settings

UNIT = Path(__file__).resolve().parents[3] / "deploy" / "worker" / "kiwoom-worker.service"


def _directives() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in UNIT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "[")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key] = value
    return values


def _default_run_timeout_s() -> float:
    return load_settings(
        {
            "KIWOOM_WORKER_DATABASE_URL": "postgresql://worker:pw@127.0.0.1:5432/postgres",
            "KIWOOM_WORKER_ID": "unit-test",
            "KIWOOM_WORKER_PROFILES_FILE": "profiles.toml",
        }
    ).run_timeout_s


def test_stop_timeout_outlasts_the_run_budget() -> None:
    """A stop lets the current run finish, so systemd must wait that long.

    systemd's default stop timeout is 90 seconds. The run budget is longer than
    that, so without an explicit value a restart during a long search is killed
    partway through instead of being allowed to settle.
    """
    directives = _directives()

    assert "TimeoutStopSec" in directives, "the unit relies on systemd's 90 second default"
    assert directives["TimeoutStopSec"].endswith("s")
    assert float(directives["TimeoutStopSec"].removesuffix("s")) > _default_run_timeout_s()


@pytest.mark.parametrize(
    ("directive", "value"),
    [
        # The worker opens sockets and reads files; it needs no capabilities.
        ("CapabilityBoundingSet", ""),
        ("AmbientCapabilities", ""),
        ("SystemCallFilter", "@system-service"),
        ("SystemCallArchitectures", "native"),
        ("RestrictNamespaces", "true"),
        ("RestrictSUIDSGID", "true"),
        ("RestrictRealtime", "true"),
        ("ProtectProc", "invisible"),
        ("ProtectClock", "true"),
        ("ProtectHostname", "true"),
        ("ProtectKernelLogs", "true"),
        # Already present; asserted so an edit cannot quietly drop them.
        ("ProtectSystem", "strict"),
        ("ProtectHome", "true"),
        ("NoNewPrivileges", "true"),
        ("PrivateTmp", "true"),
        ("PrivateDevices", "true"),
        ("MemoryDenyWriteExecute", "true"),
        ("LockPersonality", "true"),
        ("RestrictAddressFamilies", "AF_INET AF_INET6 AF_UNIX"),
        ("UMask", "0077"),
    ],
)
def test_unit_keeps_its_sandbox(directive: str, value: str) -> None:
    assert _directives().get(directive) == value
