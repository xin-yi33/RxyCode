"""Shared PostgreSQL container for the UI-2026-10-22 wave (W10).

Reuses the ``rxy-w9-pg`` container on 127.0.0.1:55439 — starts it when
missing, never removes it. Every test gets an empty public schema with
Alembic already at head.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
for _name in (
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
    "rxycode-core",
):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_CONTAINER = "rxy-w9-pg"
_URL = "postgresql+psycopg://postgres@127.0.0.1:55439/rxycode"

ORIGIN = "https://w10.example"
SECRET = "w10-web-secret-value-32bytes-long!!"


def _worker_url(server_url: str) -> str:
    """Give each pytest-xdist worker its own database in the shared container."""
    worker = re.sub(
        r"[^A-Za-z0-9_]", "_", os.environ.get("PYTEST_XDIST_WORKER") or "main"
    )
    if worker == "main":
        return server_url
    dbname = f"rxycode_{worker}"
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": dbname},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()
    base, _, _ = server_url.rpartition("/")
    return f"{base}/{dbname}"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="session")
def _postgres_server() -> str:
    # RXYCODE_PGURL：外部 postgres（如 LAN 上的临时容器）——本地无 Docker 时用；
    # CI 不设此 env，docker 路径不变。
    external = os.environ.get("RXYCODE_PGURL", "").strip()
    if external:
        return _worker_url(external)
    ready = _docker("exec", _CONTAINER, "pg_isready", "-U", "postgres", "-d", "rxycode")
    if ready.returncode == 0:
        return _worker_url(_URL)
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
            "127.0.0.1:55439:5432",
            "postgres:16",
        )
        assert started.returncode == 0, started.stderr
    deadline = time.time() + 60
    while time.time() < deadline:
        probe = _docker("exec", _CONTAINER, "pg_isready", "-U", "postgres", "-d", "rxycode")
        if probe.returncode == 0:
            return _worker_url(_URL)
        time.sleep(1)
    logs = _docker("logs", _CONTAINER)
    raise RuntimeError(logs.stderr or logs.stdout or "postgres did not become ready")


@pytest.fixture
def postgres_url(_postgres_server: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Empty schema migrated to head, and a deterministic env."""
    engine = create_engine(_postgres_server)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(_postgres_server)
    monkeypatch.delenv("RXYCODE_WEB_REGISTRATION", raising=False)
    for name in (
        "RXYCODE_QUOTA_CONCURRENCY",
        "RXYCODE_QUOTA_TASKS_PER_DAY",
        "RXYCODE_QUOTA_TOKENS_PER_DAY",
        "RXYCODE_QUEUE_MAX",
        "RXYCODE_SMTP_URL",
        "RXYCODE_SMTP_FROM",
        "RXYCODE_BYOK_ENFORCE",
        "RXYCODE_BYOK_KEYRING_FILE",
        "RXYCODE_BYOK_ALLOW_PRIVATE",
        "RXYCODE_PLATFORM_MODEL_USERS",
    ):
        monkeypatch.delenv(name, raising=False)
    from rxycode_server.quotas.service import install_gate

    install_gate(None)
    yield _postgres_server
    install_gate(None)
