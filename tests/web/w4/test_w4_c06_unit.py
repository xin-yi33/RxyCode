"""WEB-W4-C06. A local emergency stop kills the process tree and blocks new tools."""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "packages" / "rxycode-runner" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _alive(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return int(code.value) == 259


def test_w4_c06_contract(tmp_path: Path) -> None:
    """Local emergency stop ends the parent, the child, and the next full command."""
    import threading

    from rxycode_runner.local.emergency import EmergencyStop, bind_local_hotkey, press_local_hotkey
    from rxycode_runner.local.grant_store import (
        GrantStore,
        clear_grant_store,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.local.supervisor import ProcessSupervisor, bind_supervisor
    from rxycode_runner.transport.tool_rpc import _DEVICE, _run_remote_full

    work = REPO / "tests" / "web" / "w4" / "_bash_c06"
    work.mkdir(parents=True, exist_ok=True)
    (work / "child.py").write_text(
        "import os,time\nfrom pathlib import Path\nPath('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    (work / "parent.py").write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "Path('parent.pid').write_text(str(__import__('os').getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    supervisor = ProcessSupervisor()
    bind_supervisor(supervisor)
    store = GrantStore(tmp_path / "grants")
    install_grant_store("desk-c06", store)
    confirm_from_local_ui(
        store,
        {
            "device_id": "desk-c06",
            "session_id": "sess-c06",
            "run_id": "run-c06",
            "workspace": str(work),
            "capabilities": ["shell"],
            "expires_at": time.time() + 60,
        },
    )
    token = _DEVICE.set("desk-c06")
    holder: dict[str, object] = {}

    def _full() -> None:
        local = _DEVICE.set("desk-c06")
        try:
            holder["out"] = _run_remote_full(
                {
                    "permission": "full",
                    "session_id": "sess-c06",
                    "run_id": "run-c06",
                    "workspace": str(work),
                    "workdir": str(work),
                    "command": "cmd /c python parent.py",
                    "timeout": 30,
                },
                tool="bash",
                call_id="call-c06",
                cancel=threading.Event(),
            )
        except Exception as exc:
            holder["err"] = exc
        finally:
            _DEVICE.reset(local)

    try:
        worker = threading.Thread(target=_full)
        worker.start()
        deadline = time.time() + 8
        while time.time() < deadline and not (work / "child.pid").exists():
            time.sleep(0.05)
        assert (work / "child.pid").exists(), holder
        parent_pid = int((work / "parent.pid").read_text(encoding="utf-8"))
        child_pid = int((work / "child.pid").read_text(encoding="utf-8"))
        assert _alive(parent_pid) and _alive(child_pid)
        bind_local_hotkey(EmergencyStop(supervisor))
        press_local_hotkey()
        deadline = time.time() + 5
        while time.time() < deadline and (_alive(parent_pid) or _alive(child_pid)):
            time.sleep(0.05)
        assert not _alive(parent_pid)
        assert not _alive(child_pid)
        worker.join(5)
        try:
            _run_remote_full(
                {
                    "permission": "full",
                    "session_id": "sess-c06",
                    "run_id": "run-c06",
                    "workspace": str(work),
                    "workdir": str(work),
                    "command": "cmd /c echo no",
                    "timeout": 5,
                },
                tool="bash",
                call_id="call-c06-next",
                cancel=threading.Event(),
            )
        except RuntimeError as exc:
            assert "emergency_stop" in str(exc)
        else:
            raise AssertionError("full command ran after emergency stop")
        try:
            _run_remote_full(
                {
                    "permission": "full",
                    "session_id": "sess-c06",
                    "run_id": "run-c06",
                    "workspace": str(work),
                    "logical_x": 1,
                    "logical_y": 1,
                    "monitor": {"x": 0, "y": 0, "width": 10, "height": 10, "dpi": 96},
                },
                tool="click",
                call_id="call-c06-click",
                cancel=threading.Event(),
            )
        except RuntimeError as exc:
            assert "emergency_stop" in str(exc)
        else:
            raise AssertionError("full click ran after emergency stop")
    finally:
        supervisor.kill_tree()
        bind_supervisor(None)
        _DEVICE.reset(token)
        clear_grant_store("desk-c06")
        if work.exists():
            for child in work.iterdir():
                if child.is_file():
                    child.unlink()
            work.rmdir()


def test_w4_c06_negative(tmp_path: Path) -> None:
    """The audit log keeps the event and drops secrets and clipboard text."""
    from rxycode_runner.local.audit import AuditLog

    secret = "sk-proj-c06-secret-value"
    github = "ghp_c06secretvalue0123456789abcd"
    clipboard = "clipboard plaintext c06"
    log = AuditLog(tmp_path / "audit.jsonl")
    log.write(
        {
            "tool": "bash",
            "output": f"token={secret} {github}",
            "clipboard": clipboard,
            "api_key": github,
            "authorization": "Bearer super-secret-token",
            "access_token": "access-secret-c06",
            "device_token": "device-secret-c06",
            "note": "stopped",
        }
    )
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "stopped" in text
    assert secret not in text
    assert github not in text
    assert clipboard not in text
    assert "super-secret-token" not in text
    assert "access-secret-c06" not in text
    assert "device-secret-c06" not in text
