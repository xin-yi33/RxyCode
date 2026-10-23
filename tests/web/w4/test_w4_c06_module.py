"""WEB-W4-C06. Emergency stop does not wait for the cloud."""

from __future__ import annotations

import os
import sys
import time

import pytest
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


@pytest.mark.skipif(
    os.name != "nt", reason="Windows process tree semantics (ctypes.windll)"
)
def test_w4_c06_integration(tmp_path: Path) -> None:
    """A local stop still kills the tree when the cloud ack fails."""
    import threading

    from rxycode_runner.local.audit import AuditLog
    from rxycode_runner.local.emergency import EmergencyStop
    from rxycode_runner.local.grant_store import (
        GrantStore,
        clear_grant_store,
        confirm_from_local_ui,
        install_grant_store,
    )
    from rxycode_runner.local.supervisor import ProcessSupervisor, bind_supervisor
    from rxycode_runner.transport.tool_rpc import _DEVICE, _run_remote_full

    work = REPO / "tests" / "web" / "w4" / "_bash_c06_off"
    work.mkdir(parents=True, exist_ok=True)
    (work / "sleep.py").write_text(
        "import os,time\nfrom pathlib import Path\nPath('pid.txt').write_text(str(os.getpid()))\ntime.sleep(60)\n",
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
            "session_id": "sess-off",
            "run_id": "run-off",
            "workspace": str(work),
            "capabilities": ["shell"],
            "expires_at": time.time() + 60,
        },
    )
    token = _DEVICE.set("desk-c06")
    audit = AuditLog(tmp_path / "audit.jsonl")

    def _full() -> None:
        local = _DEVICE.set("desk-c06")
        try:
            _run_remote_full(
                {
                    "permission": "full",
                    "session_id": "sess-off",
                    "run_id": "run-off",
                    "workspace": str(work),
                    "workdir": str(work),
                    "command": "cmd /c python sleep.py",
                    "timeout": 30,
                },
                tool="bash",
                call_id="call-off",
                cancel=threading.Event(),
            )
        except Exception:
            return
        finally:
            _DEVICE.reset(local)

    worker = threading.Thread(target=_full)
    worker.start()
    try:
        deadline = time.time() + 8
        while time.time() < deadline and not (work / "pid.txt").exists():
            time.sleep(0.05)
        pid = int((work / "pid.txt").read_text(encoding="utf-8"))
        assert _alive(pid)

        def _cloud() -> None:
            raise OSError("cloud unreachable")

        stopped = EmergencyStop(supervisor, audit=audit, cloud_ack=_cloud).press()
        assert stopped.ok is True
        assert stopped.waited_for_cloud is False
        deadline = time.time() + 5
        while time.time() < deadline and _alive(pid):
            time.sleep(0.05)
        assert not _alive(pid)
        worker.join(5)
        text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "emergency_stop" in text
        assert "cloud unreachable" in text
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
