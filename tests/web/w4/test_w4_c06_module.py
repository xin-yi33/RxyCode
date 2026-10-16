"""WEB-W4-C06. Emergency stop does not wait for the cloud."""

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


def test_w4_c06_integration(tmp_path: Path) -> None:
    """A local stop still kills the tree when the cloud ack fails."""
    from rxycode_runner.local.audit import AuditLog
    from rxycode_runner.local.emergency import EmergencyStop
    from rxycode_runner.local.supervisor import ProcessSupervisor

    work = tmp_path / "offline"
    work.mkdir()
    script = work / "sleep.py"
    script.write_text("import os,time\nfrom pathlib import Path\nPath('pid.txt').write_text(str(os.getpid()))\ntime.sleep(60)\n", encoding="utf-8")
    supervisor = ProcessSupervisor()
    audit = AuditLog(tmp_path / "audit.jsonl")
    started = supervisor.spawn([sys.executable, str(script)], cwd=work)
    assert started.started is True
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
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "emergency_stop" in text
    assert "cloud unreachable" in text
