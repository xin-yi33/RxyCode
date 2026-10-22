"""Shared PostgreSQL container for the web security threat-model suite.

Reuses the already-running ``rxy-w2c01-pg`` container when healthy; only starts
one when it is missing. Never removes the shared container.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

import pytest
from sqlalchemy import create_engine, text

_CONTAINER = "rxy-w2c01-pg"
_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"


def _worker_url(server_url: str) -> str:
    """Give each pytest-xdist worker its own database in the shared container.

    ``--dist loadscope`` keeps one module per worker, so sibling workers that
    share one ``public`` schema drop it out from under each other
    (``DROP SCHEMA`` in ``postgres_url``). Namespacing per
    ``PYTEST_XDIST_WORKER`` makes the drop worker-local.
    """
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
            "127.0.0.1:55432:5432",
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
def postgres_url(_postgres_server: str) -> str:
    """Give each test an empty database. The test itself runs Alembic."""
    engine = create_engine(_postgres_server)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return _postgres_server
