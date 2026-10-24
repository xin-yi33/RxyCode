"""Shared PostgreSQL container for the W7 security wave.

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
    # ``RXYCODE_PGURL`` external postgres channel (same as w8/w9/w11).
    from tests.support.pgurl import ensure_container, external_url

    external = external_url()
    if external:
        return _worker_url(external)
    ensure_container(_CONTAINER, 55432)
    return _worker_url(_URL)


@pytest.fixture
def postgres_url(_postgres_server: str) -> str:
    """Give each test an empty database. The test itself runs Alembic."""
    from tests.support.pgurl import reset_schema

    reset_schema(_postgres_server)
    return _postgres_server
