"""Interactive PTY sessions. Local mode is unsandboxed. Cloud mode stays in the OS sandbox."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

_GUARD = threading.Lock()
_SESSIONS: dict[str, "Session"] = {}
_SCROLL_LIMIT = 200_000


def live_pids() -> list[int]:
    with _GUARD:
        return [item.pid for item in _SESSIONS.values() if item.exit_code is None]


def get_session(session_id: str) -> "Session | None":
    with _GUARD:
        return _SESSIONS.get(session_id)


class Session:
    def __init__(self, argv: list[str], cols: int, rows: int, tenant_id: str, sandboxed: bool) -> None:
        self.id = uuid.uuid4().hex
        self.tenant_id = tenant_id
        self.exit_code: int | None = None
        self._scroll = ""
        self._listeners: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []
        self._lock = threading.Lock()
        self._backend = _spawn(argv, cols, rows, sandboxed)
        self.pid = self._backend.pid
        self._backend.start(self._on_output, self._on_exit)

    @property
    def alive(self) -> bool:
        return self.exit_code is None

    def text(self) -> str:
        with self._lock:
            return self._scroll

    def write(self, data: str) -> None:
        self._backend.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._backend.resize(cols, rows)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._listeners.append((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._listeners = [item for item in self._listeners if item[1] is not queue]

    def _on_output(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._scroll = (self._scroll + text)[-_SCROLL_LIMIT:]
            listeners = list(self._listeners)
        frame = {"type": "output", "data": text}
        for loop, queue in listeners:
            loop.call_soon_threadsafe(queue.put_nowait, frame)

    def _on_exit(self, code: int) -> None:
        with self._lock:
            self.exit_code = code
            listeners = list(self._listeners)
        frame = {"type": "exit", "exit_code": code}
        for loop, queue in listeners:
            loop.call_soon_threadsafe(queue.put_nowait, frame)


def open_session(
    argv: list[str],
    *,
    cols: int,
    rows: int,
    tenant_id: str,
    sandboxed: bool,
) -> Session:
    session = Session(argv, cols, rows, tenant_id, sandboxed)
    with _GUARD:
        _SESSIONS[session.id] = session
    return session


class _Backend:
    pid: int

    def start(self, on_output, on_exit) -> None:
        raise NotImplementedError

    def write(self, data: str) -> None:
        raise NotImplementedError

    def resize(self, cols: int, rows: int) -> None:
        raise NotImplementedError

    def terminate(self) -> None:
        raise NotImplementedError


def _spawn(argv: list[str], cols: int, rows: int, sandboxed: bool) -> _Backend:
    if sandboxed:
        return _sandboxed_spawn(argv, cols, rows)
    if os.name == "nt":
        return _WinPty(argv, cols, rows)
    return _PosixPty(argv, cols, rows)


def _sandboxed_spawn(argv: list[str], cols: int, rows: int) -> _Backend:
    from core.sandbox.manager import open_sandbox_job, wrap_command
    from core.sandbox.policy import SandboxPolicy

    policy = SandboxPolicy(
        enabled=True,
        mode="workspace",
        workspace_root=Path.cwd(),
        network="inherit",
        on_missing_capability="fail_closed",
    )
    wrapped = wrap_command(policy, argv, Path.cwd())
    if wrapped.downgraded or not wrapped.applied:
        raise PermissionError("SANDBOX_REQUIRED")
    if os.name == "nt":
        from core.sandbox import windows as win_sandbox

        backend = _WinPty(list(wrapped.argv), cols, rows)
        job = open_sandbox_job(wrapped)
        try:
            win_sandbox.assign_pid_to_job_handle(job, backend.pid)
        except Exception as exc:
            backend.terminate()
            raise PermissionError("SANDBOX_REQUIRED") from exc
        backend.job = job
        return backend
    return _PosixPty(list(wrapped.argv), cols, rows)


class _WinPty(_Backend):
    def __init__(self, argv: list[str], cols: int, rows: int) -> None:
        from winpty import PtyProcess

        self._proc = PtyProcess.spawn(argv, dimensions=(rows, cols))
        self.pid = int(self._proc.pid)
        self.job = 0

    def start(self, on_output, on_exit) -> None:
        threading.Thread(target=self._read_loop, args=(on_output,), daemon=True).start()
        threading.Thread(target=self._wait_loop, args=(on_exit,), daemon=True).start()

    def write(self, data: str) -> None:
        self._proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._proc.setwinsize(rows, cols)

    def terminate(self) -> None:
        self._proc.terminate(force=True)

    def _read_loop(self, on_output) -> None:
        while self._proc.isalive():
            try:
                chunk = self._proc.read(4096)
            except EOFError:
                break
            if chunk:
                on_output(chunk)

    def _wait_loop(self, on_exit) -> None:
        while self._proc.isalive():
            threading.Event().wait(0.05)
        code = self._proc.exitstatus
        on_exit(0 if code is None else int(code))
        if self.job:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(self.job)


class _PosixPty(_Backend):
    def __init__(self, argv: list[str], cols: int, rows: int) -> None:
        import fcntl
        import pty
        import termios

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, _winsize(rows, cols))
        self._master = master
        self._proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        self.pid = int(self._proc.pid)

    def start(self, on_output, on_exit) -> None:
        threading.Thread(target=self._read_loop, args=(on_output,), daemon=True).start()
        threading.Thread(target=self._wait_loop, args=(on_exit,), daemon=True).start()

    def write(self, data: str) -> None:
        os.write(self._master, data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        import fcntl
        import termios

        fcntl.ioctl(self._master, termios.TIOCSWINSZ, _winsize(rows, cols))

    def terminate(self) -> None:
        self._proc.kill()

    def _read_loop(self, on_output) -> None:
        while True:
            try:
                chunk = os.read(self._master, 4096)
            except OSError:
                break
            if not chunk:
                break
            on_output(chunk.decode("utf-8", errors="replace"))

    def _wait_loop(self, on_exit) -> None:
        on_exit(int(self._proc.wait()))


def _winsize(rows: int, cols: int) -> bytes:
    import struct

    return struct.pack("HHHH", rows, cols, 0, 0)
