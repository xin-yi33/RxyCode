"""WEB-W7-C06 module leg — the public demo's real refusal surface.

The card asks: given the public Demo URL, an unauthenticated browser can
complete a restricted real cloud task. The codebase truth: there is NO
anonymous run HTTP entry — the runs API exposes only GET/cancel/steer, all
behind ``require_write``/``current_record``; the "restricted" semantics the
card freezes are exactly that an unauthenticated caller is refused
(401/403) before any work happens. This test boots the real
``create_app`` against the shared dev Postgres and drives that refusal
surface end-to-end. The full browser leg is BLOCKED (apps/web has no
Playwright dependency) — labeled, not claimed.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-runner", "rxycode-protocol"):
    _path = REPO / "packages" / _name / "src"
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.timeout(300)

SECRET = "w7c06-secret-value-32bytes-minimum!!"
ORIGIN = "https://demo.rxycode.local"


@pytest.mark.timeout(300)
def test_w7_c06_integration(_postgres_server: str) -> None:
    """Given 公开 Demo URL When 从未登录访问 Then 服务端拒绝且泄漏面为零：
    reads need a session (401), writes need origin+CSRF (403), and a forged
    session cookie is still 401 — the '受限' boundary is real server-side."""
    import asyncio

    import httpx

    from rxycode_server.main import create_app
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(_postgres_server)
    app = create_app(
        _postgres_server,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        rate_limit_rpm=0,
    )

    async def _drive() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://public-demo.test"
        ) as client:
            run_id = uuid.uuid4().hex

            # -- unauthenticated reads are refused -------------------------
            me = await client.get("/api/v1/me")
            assert me.status_code == 401, me.text
            run = await client.get(f"/api/v1/runs/{run_id}")
            assert run.status_code == 401, run.text
            events = await client.get(f"/api/v1/runs/{run_id}/events")
            assert events.status_code == 401, events.text

            # -- unauthenticated writes: the gate runs before the session --
            cancel = await client.post(f"/api/v1/runs/{run_id}/cancel")
            assert cancel.status_code == 403, cancel.text
            steer = await client.post(f"/api/v1/runs/{run_id}/steer", json={"text": "run anything"})
            assert steer.status_code == 403, steer.text

            # -- a correct Origin alone is not enough (CSRF pair missing) --
            cancel2 = await client.post(f"/api/v1/runs/{run_id}/cancel", headers={"Origin": ORIGIN})
            assert cancel2.status_code == 403, cancel2.text

            # -- Origin+CSRF satisfied but no session: still refused --------
            cancel3 = await client.post(
                f"/api/v1/runs/{run_id}/cancel",
                headers={"Origin": ORIGIN, "X-CSRF-Token": "t"},
                cookies={"rxy_csrf": "t"},
            )
            assert cancel3.status_code in (401, 403), cancel3.text

            # -- a forged session cookie is refused, not trusted -----------
            forged = await client.get("/api/v1/me", cookies={"rxy_session": "forged-token"})
            assert forged.status_code == 401, forged.text

    # pytest-asyncio may already own this thread's loop. Run the driver
    # on a fresh thread so asyncio.run is legal.
    box: dict[str, BaseException | None] = {"error": None}

    def _go() -> None:
        try:
            asyncio.run(_drive())
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=_go)
    worker.start()
    worker.join()
    if box["error"] is not None:
        raise box["error"]
