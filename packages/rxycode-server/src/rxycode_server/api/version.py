"""W10-D1: unauthenticated ``GET /api/v1/version`` build stamp.

``commit`` comes from ``RXYCODE_BUILD_COMMIT`` (the image build bakes it in
via a build ARG); a source checkout falls back to ``git rev-parse --short
HEAD``. ``built_at`` is ``RXYCODE_BUILD_TIME`` when the image stamped it,
otherwise the process start time recorded on ``app.state`` at ``create_app``.
"""

from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter, Request

router = APIRouter()

_UNKNOWN = "unknown"


def _git_commit() -> str:
    """Short HEAD of the checkout this process runs from, or ``unknown``.

    The production image ships no .git directory — git absent or a non-repo
    cwd both degrade to ``unknown`` instead of raising into the endpoint.
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _UNKNOWN
    commit = done.stdout.strip()
    return commit if done.returncode == 0 and commit else _UNKNOWN


def _commit() -> str:
    env_commit = os.environ.get("RXYCODE_BUILD_COMMIT", "").strip()
    return env_commit or _git_commit()


def _built_at(request: Request) -> str:
    env_time = os.environ.get("RXYCODE_BUILD_TIME", "").strip()
    if env_time:
        return env_time
    return str(getattr(request.app.state, "built_at", "") or _UNKNOWN)


@router.get("/api/v1/version")
def version(request: Request) -> dict[str, str]:
    return {"commit": _commit(), "built_at": _built_at(request)}
