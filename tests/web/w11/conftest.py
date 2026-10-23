"""Shared PostgreSQL fixture for the W11 files/capabilities/preview wave.

Reuses ``rxy-w11-pg`` on 127.0.0.1:55441 — starts it when missing, never
removes it. ``RXYCODE_PGURL`` points at an external postgres when Docker is
unavailable locally; CI leaves it unset so the docker path is unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
for _name in (
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.support.pgurl import ensure_container, external_url, worker_url

_CONTAINER = "rxy-w11-pg"
_PORT = 55441
_URL = f"postgresql+psycopg://postgres@127.0.0.1:{_PORT}/rxycode"

ORIGIN = "https://w11.example"
SECRET = "w11-web-secret-value-32bytes-long!!"


@pytest.fixture(scope="session")
def _postgres_server() -> str:
    external = external_url()
    if external:
        return worker_url(external)
    ensure_container(_CONTAINER, _PORT)
    return worker_url(_URL)


@pytest.fixture
def postgres_url(_postgres_server: str, monkeypatch: pytest.MonkeyPatch):
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
        "RXYCODE_ATTACHMENTS_ROOT",
        "RXYCODE_S3_ENDPOINT",
        "RXYCODE_S3_BUCKET",
        "RXYCODE_S3_ACCESS_KEY",
        "RXYCODE_S3_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    from rxycode_server.quotas.service import install_gate

    install_gate(None)
    yield _postgres_server
    install_gate(None)
