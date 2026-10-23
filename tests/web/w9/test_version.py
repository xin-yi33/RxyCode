"""W10-D1: GET /api/v1/version — unauthenticated build stamp.

``commit`` = ``RXYCODE_BUILD_COMMIT`` (image build ARG) else
``git rev-parse --short HEAD`` else ``unknown``; ``built_at`` =
``RXYCODE_BUILD_TIME`` else the process start time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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

from rxycode_server.main import create_app  # noqa: E402

ORIGIN = "https://w9.example"
SECRET = "w9-web-secret-value-32bytes-long!!"


def _client(postgres_url: str) -> TestClient:
    app = create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
    )
    return TestClient(app)


def test_version_reports_image_build_stamp(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RXYCODE_BUILD_COMMIT", "deadbeef")
    monkeypatch.setenv("RXYCODE_BUILD_TIME", "2026-10-20T00:00:00+00:00")
    response = _client(postgres_url).get("/api/v1/version")
    assert response.status_code == 200
    assert response.json() == {
        "commit": "deadbeef",
        "built_at": "2026-10-20T00:00:00+00:00",
    }


def test_version_falls_back_without_build_env(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RXYCODE_BUILD_COMMIT", raising=False)
    monkeypatch.delenv("RXYCODE_BUILD_TIME", raising=False)
    response = _client(postgres_url).get("/api/v1/version")
    assert response.status_code == 200
    body = response.json()
    assert body["commit"]
    assert body["built_at"]


def test_version_is_unauthenticated(postgres_url: str) -> None:
    # No session cookie, no CSRF — the route must still answer 200.
    response = _client(postgres_url).get("/api/v1/version")
    assert response.status_code == 200
    assert set(response.json()) == {"commit", "built_at"}
