"""WEB-W4-C05. Remote Full runs only after this machine confirms the grant."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

_SECRET = "local-web-secret-value-32bytes!!"
REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
for entry in (
    REPO,
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _render(view: dict[str, object]) -> str:
    script = REPO / "tests" / "web" / "w4" / "_render_c05.mjs"
    payload = REPO / "tests" / "web" / "w4" / "_render_c05.json"
    payload.write_text(json.dumps(view), encoding="utf-8")
    component = REPO / "apps" / "web" / "src" / "features" / "devices" / "DeviceGrants.tsx"
    script.write_text(
        "\n".join(
            [
                'import { createElement } from "react";',
                'import { renderToStaticMarkup } from "react-dom/server";',
                'import { readFileSync } from "node:fs";',
                f"import {{ DeviceGrants }} from {json.dumps(component.as_posix())};",
                f"const view = JSON.parse(readFileSync({json.dumps(payload.as_posix())}, 'utf8'));",
                "process.stdout.write(renderToStaticMarkup(createElement(DeviceGrants, { view })));",
            ]
        ),
        encoding="utf-8",
    )
    ran = subprocess.run(
        [str(BUN), str(script)],
        cwd=WEB,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    script.unlink(missing_ok=True)
    payload.unlink(missing_ok=True)
    if ran.returncode != 0:
        raise AssertionError(ran.stderr or ran.stdout)
    return ran.stdout


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
                "click",
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


def _invoke(gateway: object, browser: str, csrf: str, body: dict[str, object]) -> httpx.Response:
    return httpx.post(
        f"{gateway.http}/api/v1/devices/desk-c05/invocations",  # type: ignore[attr-defined]
        headers={"Origin": gateway.http, "X-CSRF-Token": csrf},  # type: ignore[attr-defined]
        cookies={"rxy_session": browser, "rxy_csrf": csrf},
        json=body,
        timeout=20,
    )


def test_w4_c05_contract(tmp_path: Path) -> None:
    """A local confirm lets shell and click in scope skip per-item approval."""
    from uuid import uuid4

    from RxyCode.RxyCode1_1_0.core.safety.approval import get_approval_broker
    from rxycode_runner.local.grant_store import (
        GrantStore,
        bind_click_sender,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_server.devices.grants import GrantMirror

    device_id = "desk-c05"
    clock = {"t": 1_000.0}
    work = REPO / "tests" / "web" / "w4" / "_bash_c05"
    work.mkdir(parents=True, exist_ok=True)
    marker = work / "grant-mark.txt"
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
    points: list[tuple[int, int]] = []
    store = GrantStore(tmp_path / "grants", clock=lambda: clock["t"])
    install_grant_store(device_id, store)
    bind_click_sender(device_id, points.append)
    mirror = GrantMirror()
    session_id, run_id = "sess-c05", "run-c05"
    try:
        request = mirror.request_remote_full(
            device_id=device_id,
            session_id=session_id,
            run_id=run_id,
            workspace=str(work),
            capabilities=["shell", "click"],
            expires_at=clock["t"] + 50,
        )
        assert request["status"] == "waiting_for_local_confirmation"
        assert request.get("permission") in {None, ""}
        assert store.confirmed_count() == 0
        waiting = _render(mirror.view(device_id))
        assert "waiting_for_local_confirmation" in waiting
        assert "完全控制" not in waiting
        forged = mirror.forge_full(device_id)
        assert forged["permission"] == "full"
        assert store.confirmed_count() == 0
        assert "waiting_for_local_confirmation" in _render(mirror.view(device_id))
        saved = confirm_from_local_ui(store, request)
        acked = mirror.ack(
            device_id,
            grant_id=str(saved["grant_id"]),
            revoke_epoch=int(saved["revoke_epoch"]),
        )
        assert acked["status"] == "granted"
        granted = _render(mirror.view(device_id))
        assert "waiting_for_local_confirmation" not in granted
        assert "shell" in granted and "click" in granted and device_id in granted
        broker = get_approval_broker()
        seen = {"n": 0}
        previous = getattr(broker, "_sink", None)

        def _count(event: dict[str, object]) -> None:
            seen["n"] += 1
            if previous is not None:
                previous(event)

        if broker is not None:
            broker.set_event_sink(_count)
        bash = _invoke(
            gateway,
            browser,
            csrf,
            {
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "permission": "full",
                    "session_id": session_id,
                    "run_id": run_id,
                    "workspace": str(work),
                    "command": "cmd /c python mark.py",
                    "workdir": str(work),
                    "timeout": 30,
                },
            },
        )
        assert bash.status_code == 200, bash.text
        assert bash.json()["state"] == "completed", bash.text
        assert marker.read_text(encoding="utf-8") == "x"
        assert seen["n"] == 0
        click = _invoke(
            gateway,
            browser,
            csrf,
            {
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "click",
                "args": {
                    "permission": "full",
                    "session_id": session_id,
                    "run_id": run_id,
                    "workspace": str(work),
                    "logical_x": 100,
                    "logical_y": 200,
                    "monitor": {"x": 1920, "y": 0, "width": 1920, "height": 1080, "dpi": 144},
                },
            },
        )
        assert click.status_code == 200, click.text
        assert click.json()["state"] == "completed", click.text
        assert points == [(2070, 300)]
        assert seen["n"] == 0
        where = work / "where.txt"
        inherited = _invoke(
            gateway,
            browser,
            csrf,
            {
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "permission": "full",
                    "session_id": session_id,
                    "run_id": run_id,
                    "workspace": str(work),
                    "command": "cmd /c python -c \"from pathlib import Path; Path('where.txt').write_text(str(Path.cwd()))\"",
                    "timeout": 30,
                },
            },
        )
        assert inherited.status_code == 200, inherited.text
        assert inherited.json()["state"] == "completed", inherited.text
        assert where.is_file()
        assert Path(where.read_text(encoding="utf-8").strip()).resolve() == work.resolve()
        assert not (REPO / "where.txt").exists()
        from rxycode_runner.transport.tool_rpc import _DEVICE, local_tool

        stopped = threading.Event()
        stopped.set()
        token = _DEVICE.set(device_id)
        try:
            try:
                local_tool(
                    {
                        "permission": "full",
                        "session_id": session_id,
                        "run_id": run_id,
                        "workspace": str(work),
                        "command": "cmd /c python mark.py",
                        "workdir": str(work),
                        "timeout": 30,
                    },
                    cancel=stopped,
                    tool="bash",
                    call_id=f"call_{uuid4().hex}",
                )
            except RuntimeError as exc:
                assert "cancelled before execution" in str(exc)
            else:
                raise AssertionError("cancelled full bash ran")
        finally:
            _DEVICE.reset(token)
        assert marker.read_text(encoding="utf-8") == "x"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools(device_id)
        from rxycode_runner.local.grant_store import clear_grant_store

        clear_grant_store(device_id)
        from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker

        set_approval_broker(None)
        if work.exists():
            for child in work.iterdir():
                if child.is_file():
                    child.unlink()
            work.rmdir()


def test_w4_c05_negative(tmp_path: Path) -> None:
    """A forged full permission does nothing when this machine has no grant."""
    from uuid import uuid4

    from rxycode_runner.local.grant_store import (
        GrantStore,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.remote.client import request_stop
    from rxycode_runner.transport.tool_rpc import clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_server.devices.grants import GrantMirror

    device_id = "desk-c05"
    work = REPO / "tests" / "web" / "w4" / "_bash_c05"
    work.mkdir(parents=True, exist_ok=True)
    marker = work / "forged-mark.txt"
    gateway = serve_in_thread(secret=_SECRET)
    thread = _pair(gateway, device_id)
    browser = gateway.browser_session("tenant-a")
    csrf = "csrf-token-value-for-c05"
    store = GrantStore(tmp_path / "grants")
    install_grant_store(device_id, store)
    mirror = GrantMirror()
    try:
        mirror.forge_full(device_id)
        denied = _invoke(
            gateway,
            browser,
            csrf,
            {
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "bash",
                "args": {
                    "permission": "full",
                    "session_id": "sess-c05",
                    "run_id": "run-c05",
                    "workspace": str(work),
                    "command": "cmd /c python -c \"print(1)\"",
                    "workdir": str(work),
                    "timeout": 30,
                },
            },
        )
        assert denied.status_code == 200, denied.text
        assert denied.json()["state"] == "recovery_required", denied.text
        assert not marker.exists()
        reasons = [str(item.get("reason")) for item in store.audit_entries()]
        assert "GRANT_REQUIRED" in reasons
        assert any(
            item.get("permission") == "full" and item.get("allowed") is False
            for item in store.audit_entries()
        )
        saved = confirm_from_local_ui(
            store,
            mirror.request_remote_full(
                device_id=device_id,
                session_id="sess-c05",
                run_id="run-c05",
                workspace=str(work),
                capabilities=["shell"],
                expires_at=time.time() + 60,
            ),
        )
        assert saved["confirmed"] is True

        def _denied(args: dict[str, object]) -> str:
            response = _invoke(
                gateway,
                browser,
                csrf,
                {
                    "attempt_id": f"att_{uuid4().hex}",
                    "call_id": f"call_{uuid4().hex}",
                    "tool": "bash",
                    "args": args,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "recovery_required", response.text
            return str(response.json().get("result") or "")

        base = {
            "permission": "full",
            "session_id": "sess-c05",
            "run_id": "run-c05",
            "workspace": str(work),
            "command": "cmd /c python -c \"print(1)\"",
            "workdir": str(work),
            "timeout": 30,
        }
        assert "RUN_MISMATCH" in _denied({**base, "run_id": "run-other"})
        assert "SESSION_MISMATCH" in _denied({**base, "session_id": "sess-other"})
        outside = REPO / "tests" / "web" / "w4"
        assert "WORKSPACE_MISMATCH" in _denied({**base, "workspace": str(outside), "workdir": str(outside)})
        assert "CAPABILITY_MISMATCH" in _invoke(
            gateway,
            browser,
            csrf,
            {
                "attempt_id": f"att_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "tool": "click",
                "args": {
                    "permission": "full",
                    "session_id": "sess-c05",
                    "run_id": "run-c05",
                    "workspace": str(work),
                    "logical_x": 1,
                    "logical_y": 1,
                    "monitor": {"x": 0, "y": 0, "width": 100, "height": 100, "dpi": 96},
                },
            },
        ).json()["result"]
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools(device_id)
        from rxycode_runner.local.grant_store import clear_grant_store

        clear_grant_store(device_id)
        from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker

        set_approval_broker(None)
        if work.exists():
            for child in work.iterdir():
                if child.is_file():
                    child.unlink()
            work.rmdir()
