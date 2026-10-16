"""Shared PostgreSQL container for the W7 security wave.

Reuses the already-running ``rxy-w2c01-pg`` container when healthy; only starts
one when it is missing. Never removes the shared container.
"""

from __future__ import annotations

import subprocess
import time

import pytest
from sqlalchemy import create_engine, text

_CONTAINER = "rxy-w2c01-pg"
_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        check=False,
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
    """Give each test an empty database. The test itself runs Alembic."""
    engine = create_engine(_postgres_server)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return _postgres_server
