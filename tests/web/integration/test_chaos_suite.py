"""WEB-W7-C02. Drive the chaos recovery CLI and check the scenario outcomes."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]

_CONTAINER = "rxy-w2c01-pg"
_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"
_REDIS_URL = "redis://127.0.0.1:56390/0"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=False
    )


@pytest.fixture(scope="session")
def _postgres_server() -> str:
    ready = _docker("exec", _CONTAINER, "pg_isready", "-U", "postgres", "-d", "rxycode")
    if ready.returncode == 0:
        return _URL
    exists = _docker("inspect", _CONTAINER)
    if exists.returncode == 0:
        started = _docker("start", _CONTAINER)
        assert started.returncode == 0, started.stderr
    else:
        started = _docker(
            "run",
            "-d",
            "--name",
            _CONTAINER,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=rxycode",
            "-p",
            "127.0.0.1:55432:5432",
            "postgres:16",
        )
        assert started.returncode == 0, started.stderr
    deadline = time.time() + 60
    while time.time() < deadline:
        probe = _docker("exec", _CONTAINER, "pg_isready", "-U", "postgres", "-d", "rxycode")
        if probe.returncode == 0:
            return _URL
        time.sleep(1)
    logs = _docker("logs", _CONTAINER)
    raise RuntimeError(logs.stderr or logs.stdout or "postgres did not become ready")


@pytest.fixture
def postgres_url(_postgres_server: str) -> str:
    """Empty schema per test, same as the W7 conftest fixture."""
    engine = create_engine(_postgres_server)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return _postgres_server


# Redis stream is at-least-once (outbox pattern; a publish that timed out
# during a pause may still land). Exactly-once delivery to clients is by
# seq from PostgreSQL — the scenarios assert that on the SSE path.
_EXPECTED = {
    "worker_kill_during_approval": "correct",
    "worker_kill_after_side_effect": "unknown",
    "redis_down_after_commit": "correct",
    "sse_disconnect_reconnect": "correct",
    "stale_lease_after_pause": "correct",
    "postgres_unreachable": "correct",
}


def test_chaos_suite(postgres_url: str, tmp_path: Path):
    report_path = tmp_path / "chaos-report.json"
    cli = REPO / "platform_tests" / "web" / "chaos" / "run_recovery.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--database-url",
            postgres_url,
            "--redis-url",
            _REDIS_URL,
            "--report",
            str(report_path),
            "--workdir",
            str(tmp_path / "work"),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    scenarios = {row["name"]: row for row in report["scenarios"]}
    expected_names = {
        "worker_kill_during_approval",
        "worker_kill_after_side_effect",
        "redis_down_after_commit",
        "sse_disconnect_reconnect",
        "stale_lease_after_pause",
        "postgres_unreachable",
        "runner_disconnect_replay",
    }
    assert set(scenarios) == expected_names
    assert report["counts"]["failed"] == 0, report["scenarios"]
    assert report["process_leak"] == 0, report["scenarios"]
    assert report["cross_tenant_leak"] is False
    for name, outcome in _EXPECTED.items():
        assert scenarios[name]["outcome"] == outcome, scenarios[name]
    replay = scenarios["runner_disconnect_replay"]
    if replay["outcome"] == "blocked":
        assert replay.get("details") or replay.get("reason"), replay
        print("runner_disconnect_replay blocked:", replay.get("details") or replay.get("reason"))
    else:
        assert replay["outcome"] == "correct", replay
