"""Shared PostgreSQL container for the W9 auth/task/quota wave.

Dedicated ``rxy-w9-pg`` on 127.0.0.1:55439 — reuses it when healthy, starts it
when missing, never removes it. Every test gets an empty public schema with
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

ORIGIN = "https://w9.example"
SECRET = "w9-web-secret-value-32bytes-long!!"



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
    # RXYCODE_PGURL：外部 postgres（本地无 Docker 时用）；CI 不设此 env。
    external = os.environ.get("RXYCODE_PGURL", "").strip()
    if external:
        return _worker_url(external)
    from tests.support.pgurl import ensure_container

    ensure_container(_CONTAINER, 55439)
    return _worker_url(_URL)


@pytest.fixture
def postgres_url(_postgres_server: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Empty schema migrated to head, and a deterministic env."""
    from tests.support.pgurl import reset_schema

    reset_schema(_postgres_server, migrate=True)
    monkeypatch.delenv("RXYCODE_WEB_REGISTRATION", raising=False)
    for name in (
        "RXYCODE_QUOTA_CONCURRENCY",
        "RXYCODE_QUOTA_TASKS_PER_DAY",
        "RXYCODE_QUOTA_TOKENS_PER_DAY",
        "RXYCODE_QUEUE_MAX",
        "RXYCODE_SMTP_URL",
        "RXYCODE_SMTP_FROM",
        # BYOK: BYOK tests opt in via their own fixtures; an operator-set
        # env must never flip the rest of the suite into enforcement.
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
