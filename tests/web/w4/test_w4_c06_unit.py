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
    """Local emergency stop ends the parent, the child, and the next command."""
    from rxycode_runner.local.emergency import EmergencyStop, bind_local_hotkey, press_local_hotkey
    from rxycode_runner.local.supervisor import ProcessSupervisor

    work = tmp_path / "tree"
    work.mkdir()
    child_script = work / "child.py"
    child_script.write_text("import os,time\nfrom pathlib import Path\nPath('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n", encoding="utf-8")
    parent_script = work / "parent.py"
    parent_script.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "Path('parent.pid').write_text(str(__import__('os').getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    supervisor = ProcessSupervisor()
    started = supervisor.spawn([sys.executable, str(parent_script)], cwd=work)
    assert started.started is True
    deadline = time.time() + 8
    while time.time() < deadline and not (work / "child.pid").exists():
        time.sleep(0.05)
    assert (work / "child.pid").exists()
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
    blocked = supervisor.spawn([sys.executable, "-c", "print('no')"], cwd=work)
    assert blocked.started is False


def test_w4_c06_negative(tmp_path: Path) -> None:
    """The audit log keeps the event and drops secrets and clipboard text."""
    from rxycode_runner.local.audit import AuditLog

    secret = "sk-proj-c06-secret-value"
    clipboard = "clipboard plaintext c06"
    log = AuditLog(tmp_path / "audit.jsonl")
    log.write(
        {
            "tool": "bash",
            "output": f"token={secret}",
            "clipboard": clipboard,
            "note": "stopped",
        }
    )
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "stopped" in text
    assert secret not in text
    assert clipboard not in text
