"""Parent-side client for appserver.agent_worker subprocess (T1)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

_logger = logging.getLogger(__name__)
EmitFn = Callable[[dict[str, Any]], None]
ForwardServerRequest = Callable[[str, dict[str, Any]], Any]


class AgentHost:
    """One killable worker subprocess per session."""

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path,
        stub: bool,
        project_root: Path,
        forward_server_request: ForwardServerRequest,
        main_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.session_id = session_id
        self.workspace_root = workspace_root.resolve()
        self._stub = stub
        self._forward_server_request = forward_server_request
        self._main_loop = main_loop
        self._bootstrapped = False
        self._emit: EmitFn | None = None
        self._next_id = 1
        self._send_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._outgoing: queue.Queue[dict[str, Any]] = queue.Queue()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(project_root)
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "appserver.agent_worker"],
            cwd=project_root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._stderr = threading.Thread(target=self._drain_stderr, daemon=True)
        self._reader.start()
        self._writer.start()
        self._stderr.start()

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            text = line.rstrip()
            if text:
                _logger.info("[agent_worker %s] %s", self.session_id[:8], text)

    def _write_loop(self) -> None:
        assert self._proc.stdin is not None
        while self._proc.poll() is None:
            try:
                message = self._outgoing.get(timeout=0.2)
            except queue.Empty:
                continue
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._route_message(message)

    def _route_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if isinstance(request_id, int) and (
            "result" in message or "error" in message
        ):
            with self._pending_lock:
                pending = self._pending.get(request_id)
            if pending is not None:
                pending.put(message)
                return
        method = message.get("method")
        if isinstance(method, str) and method == "approval/request":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            rid = message.get("id")
            if not isinstance(rid, int):
                return

            def _complete() -> None:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._forward_server_request("approval/request", params),
                        self._main_loop,
                    )
                    result = future.result(timeout=125.0)
                    self._outgoing.put(
                        {"jsonrpc": "2.0", "id": rid, "result": result}
                    )
                except Exception as exc:
                    self._outgoing.put(
                        {
                            "jsonrpc": "2.0",
                            "id": rid,
                            "error": {"code": -32000, "message": str(exc)},
                        }
                    )

            threading.Thread(target=_complete, daemon=True).start()
            return
        if isinstance(method, str) and method.startswith("event/") and self._emit:
            self._emit(message)

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> dict:
        with self._send_lock:
            request_id = self._next_id
            self._next_id += 1
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._pending_lock:
            self._pending[request_id] = response_queue
        self._outgoing.put(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        try:
            message = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"agent worker timeout for {method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in message:
            error = message.get("error") or {}
            raise RuntimeError(str(error.get("message", "agent worker error")))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def ensure_bootstrapped(self, *, timeout: float) -> None:
        if self._bootstrapped:
            return
        import asyncio

        await asyncio.to_thread(
            self._request,
            "bootstrap",
            {
                "stub": self._stub,
                "workspace_root": str(self.workspace_root),
                "session_id": self.session_id,
            },
            timeout=timeout,
        )
        self._bootstrapped = True

    async def run_prompt(
        self,
        *,
        text: str,
        run_id: str,
        timeout: float,
        emit: EmitFn,
        mode: str = "build",
        thinking_expanded: bool = False,
    ) -> dict[str, Any]:
        self._emit = emit
        import asyncio

        return await asyncio.to_thread(
            self._request,
            "prompt",
            {
                "session_id": self.session_id,
                "text": text,
                "run_id": run_id,
                "mode": mode,
                "thinking_expanded": thinking_expanded,
            },
            timeout=timeout,
        )

    async def set_thinking_expanded(self, expanded: bool, timeout: float = 5.0) -> bool:
        """Forward Thought expand state to the in-flight worker TUI."""
        if not self.alive():
            return False
        import asyncio

        try:
            result = await asyncio.to_thread(
                self._request,
                "thinking/set_expanded",
                {"expanded": bool(expanded)},
                timeout=timeout,
            )
        except Exception:
            return False
        return bool(result.get("ok", False))

    async def kill_async(self) -> None:
        await asyncio.to_thread(self.kill)

    def kill(self) -> None:
        if self._proc.poll() is not None:
            return
        try:
            self._outgoing.put(
                {"jsonrpc": "2.0", "id": 9999, "method": "shutdown", "params": {}}
            )
        except Exception:
            pass
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)

    def alive(self) -> bool:
        return self._proc.poll() is None
