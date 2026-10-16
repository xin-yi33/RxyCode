"""WEB-W4-C01. Local full runs a native process and refuses a sandbox."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
if str(_RUNNER) not in sys.path:
    sys.path.insert(0, str(_RUNNER))


def _session(pid: int) -> int:
    value = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.c_uint(pid), ctypes.byref(value))
    if not ok:
        raise OSError(ctypes.GetLastError())
    return int(value.value)


def test_w4_c01_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A local full shell is a native pid in this session and is not wrapped."""
    from rxycode_runner.local.native_backend import LocalNativeBackend

    wrapped: list[object] = []

    def spy(*args: object, **kwargs: object) -> object:
        wrapped.append(args)
        raise AssertionError("full mode called wrap_command")

    monkeypatch.setattr("core.sandbox.manager.wrap_command", spy)
    backend = LocalNativeBackend(target="local", permission="full")
    handle = backend.start(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
    )
    try:
        assert handle.started is True
        assert handle.wrapped is False
        assert handle.argv[0] == sys.executable
        assert handle.pid is not None
        assert _session(handle.pid) == _session(os.getpid())
        assert wrapped == []
        assert any(item["approval"] == "skipped" for item in backend.audit)
    finally:
        backend.kill(handle.pid or 0)


def test_w4_c01_negative() -> None:
    """Full mode rejects an injected sandbox instead of wrapping the command."""
    from rxycode_runner.local.native_backend import LocalNativeBackend

    backend = LocalNativeBackend(target="local", permission="full")

    class SandboxBackend:
        def wrap_command(self, argv: list[str]) -> list[str]:
            return ["bwrap", *argv]

    with pytest.raises(PermissionError, match="SANDBOX_FORBIDDEN"):
        backend.attach_sandbox(SandboxBackend())
