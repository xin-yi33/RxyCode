"""WEB-W4-C05. An expired or revoked grant rejects the next tool call."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx

_SECRET = "local-web-secret-value-32bytes!!"
REPO = Path(__file__).resolve().parents[3]
for entry in (
    REPO,
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _pair(gateway: object, device_id: str) -> threading.Thread:
    from click.testing import CliRunner
    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import reset_stop

    reset_stop()
    browser = gateway.browser_session("tenant-a")  # type: ignore[attr-defined]
    csrf = "csrf-token-value-for-c05"
    issued = httpx.post(
        f"{gateway.http}/api/v1/devices/pairings",  # type: ignore[attr-defined]
        headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
        cookies={"rxy_session": browser, "rxy_csrf": csrf},
        timeout=5,
    )
    issued.raise_for_status()
    holder: dict[str, object] = {}

    def launch() -> None:
        holder["result"] = CliRunner().invoke(
            cli,
            [
                "connect",
                "--url",
                gateway.ws,  # type: ignore[attr-defined]
                "--code",
                issued.json()["code"],
                "--device-id",
                device_id,
                "--os-name",
                "Windows",
                "--capability",
                "shell",
                "--heartbeat-seconds",
                "0.2",
            ],
        )

    thread = threading.Thread(target=launch)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline and not gateway.session_id(device_id):  # type: ignore[attr-defined]
        time.sleep(0.05)
    if not gateway.session_id(device_id):  # type: ignore[attr-defined]
        raise AssertionError(holder.get("result"))
    return thread


def test_w4_c05_integration(tmp_path: Path) -> None:
    """A temporary grant stops working after expiry and after revoke."""
    from rxycode_runner.local.grant_store import (
        GrantStore,
        clear_grant_store,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_server.devices.grants import GrantMirror

    device_id = "desk-c05"
    clock = {"t": 2_000.0}
    work = REPO / "tests" / "web" / "w4" / "_bash_c05"
    work.mkdir(parents=True, exist_ok=True)
    marker = work / "expire-mark.txt"
    script = work / "mark.py"
    script.write_text(
        "from pathlib import Path\n"
        f"p = Path({str(marker)!r})\n"
        "old = p.read_text(encoding='utf-8') if p.exists() else ''\n"
        "p.write_text(old + 'x', encoding='utf-8')\n",
        encoding="utf-8",
    )
    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway, device_id)
    browser = gateway.browser_session("tenant-a")
    csrf = "csrf-token-value-for-c05"
    store = GrantStore(tmp_path / "grants", clock=lambda: clock["t"])
    install_grant_store(device_id, store)
    mirror = GrantMirror()
    session_id, run_id = "sess-expire", "run-expire"
    try:
        request = mirror.request_remote_full(
            device_id=device_id,
            session_id=session_id,
            run_id=run_id,
            workspace=str(work),
            capabilities=["shell"],
            expires_at=clock["t"] + 10,
        )
        saved = confirm_from_local_ui(store, request)

        def _bash() -> httpx.Response:
            return httpx.post(
                f"{gateway.http}/api/v1/devices/{device_id}/invocations",
                headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
                cookies={"rxy_session": browser, "rxy_csrf": csrf},
                json={
                    "attempt_id": f"att_{uuid4().hex}",
                    "call_id": f"call_{uuid4().hex}",
                    "tool": "bash",
                    "args": {
                        "permission": "full",
                        "session_id": session_id,
                        "run_id": run_id,
                        "workspace": str(work),
                        "command": ("cmd /c python mark.py" if __import__("os").name == "nt" else "python3 mark.py"),
                        "workdir": str(work),
                        "timeout": 30,
                    },
                },
                timeout=20,
            )

        first = _bash()
        assert first.status_code == 200, first.text
        assert first.json()["state"] == "completed", first.text
        assert marker.read_text(encoding="utf-8") == "x"
        clock["t"] = float(saved["expires_at"])
        expired = _bash()
        assert expired.json()["state"] == "recovery_required", expired.text
        assert marker.read_text(encoding="utf-8") == "x"
        assert any(item.get("reason") == "GRANT_EXPIRED" for item in store.audit_entries())
        clock["t"] = 3_000.0
        again = mirror.request_remote_full(
            device_id=device_id,
            session_id="sess-revoke",
            run_id="run-revoke",
            workspace=str(work),
            capabilities=["shell"],
            expires_at=clock["t"] + 30,
        )
        confirm_from_local_ui(store, again)
        revived = httpx.post(
            f"{gateway.http}/api/v1/devices/{device_id}/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "permission": "full",
                    "session_id": "sess-revoke",
                    "run_id": "run-revoke",
                    "workspace": str(work),
                    "command": ("cmd /c python mark.py" if __import__("os").name == "nt" else "python3 mark.py"),
                    "workdir": str(work),
                    "timeout": 30,
                },
            },
            timeout=20,
        )
        assert revived.json()["state"] == "completed", revived.text
        store.revoke(str(store.latest_grant_id()))
        revoked = httpx.post(
            f"{gateway.http}/api/v1/devices/{device_id}/invocations",
            headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
            cookies={"rxy_session": browser, "rxy_csrf": csrf},
            json={
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "permission": "full",
                    "session_id": "sess-revoke",
                    "run_id": "run-revoke",
                    "workspace": str(work),
                    "command": ("cmd /c python mark.py" if __import__("os").name == "nt" else "python3 mark.py"),
                    "workdir": str(work),
                    "timeout": 30,
                },
            },
            timeout=20,
        )
        assert revoked.json()["state"] == "recovery_required", revoked.text
        assert marker.read_text(encoding="utf-8") == "xx"
        assert any(item.get("reason") == "GRANT_REVOKED" for item in store.audit_entries())
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools(device_id)
        clear_grant_store(device_id)
        from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker

        set_approval_broker(None)
        if work.exists():
            for child in work.iterdir():
                if child.is_file():
                    child.unlink()
            work.rmdir()
