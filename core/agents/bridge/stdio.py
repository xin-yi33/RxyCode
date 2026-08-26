"""Local stdio NDJSON channel. Child stdin/stdout only; stderr is logs."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any

from RxyCode.RxyCode1_1_0.appserver.jsonrpc import parse_line

_LOG = logging.getLogger(__name__)


class StdioChannel:
    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._inbox: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._alive = True
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def send(self, message: dict[str, Any]) -> None:
        if self._proc.stdin is None:
            raise RuntimeError("worker stdin closed")
        self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def recv(self, timeout: float) -> dict[str, Any] | None:
        try:
            item = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None
        return item

    def close(self) -> None:
        self._alive = False
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)

    def kill(self) -> None:
        self._alive = False
        if self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=5)

    def _read_stdout(self) -> None:
        stream = self._proc.stdout
        if stream is None:
            return
        try:
            for line in stream:
                if not self._alive:
                    break
                try:
                    payload = parse_line(line)
                except Exception:
                    _LOG.warning("bridge stdout not JSON-RPC: %r", line[:80])
                    continue
                if payload is not None:
                    self._inbox.put(payload)
        finally:
            self._inbox.put(None)

    def _read_stderr(self) -> None:
        stream = self._proc.stderr
        if stream is None:
            return
        for line in stream:
            if line.strip():
                _LOG.info("bridge worker stderr: %s", line.rstrip())
