"""Isolated AgentV2 worker subprocess (T1): killable bootstrap + prompt execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .bootstrap import bootstrap_agent
from .emitter import model_to_notification
from .jsonrpc import write_message
from .runtime import bind_prompt_context, install_tui_context_hook, get_bound_tui, reset_prompt_context
from .tui import ProtocolTui

try:
    from ..core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
    from ..core.safety.approval import set_approval_broker
    from ..core.session import Session
except ImportError:
    from core.safety.approval import ApprovalBroker, ApprovalDecision, ApprovalRequest
    from core.safety.approval import set_approval_broker
    from core.session import Session

_logger = logging.getLogger(__name__)


class _PipeApproval(ApprovalBroker):
    """Forward approval requests to the parent appserver over worker stdout."""

    def __init__(self, send_request: Callable[[str, dict[str, Any]], Any]) -> None:
        super().__init__()
        self._send_request = send_request

    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        try:
            from .runtime import get_bound_session_id
        except ImportError:
            from appserver.runtime import get_bound_session_id

        session_id = get_bound_session_id()
        try:
            payload = await asyncio.wait_for(
                self._send_request(
                    "approval/request",
                    {
                        "session_id": session_id,
                        "request_id": request.approval_id,
                        "risk_level": request.risk.name,
                        "action": request.tool_name,
                        "details": {"args": request.args_summary},
                    },
                ),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            return ApprovalDecision.REJECTED
        decision_name = str(payload.get("decision", "rejected"))
        try:
            return ApprovalDecision(decision_name)
        except ValueError:
            return ApprovalDecision.REJECTED


class AgentWorker:
    def __init__(self) -> None:
        install_tui_context_hook()
        self._agent: Any | None = None
        self._session_id = "worker"
        self._workspace_root = Path.cwd()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1
        self._approval = _PipeApproval(self._send_parent_request)
        self._thinking_expanded = False
        self._active_tui: Any | None = None
        self._pending_writes: set[asyncio.Task[Any]] = set()

    def _schedule_write(self, message: dict[str, Any]) -> None:
        """Queue stdout write from sync emit callbacks (T3: no sync I/O on loop)."""
        task = asyncio.get_running_loop().create_task(write_message(message))
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    async def _flush_pending_writes(self) -> None:
        """Wait for all scheduled notifications to hit stdout before a result."""
        if not self._pending_writes:
            return
        await asyncio.gather(*list(self._pending_writes), return_exceptions=True)

    async def _send_parent_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await write_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return await future

    def _resolve_parent_response(self, message: dict[str, Any]) -> bool:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return False
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        if "error" in message:
            error = message.get("error") or {}
            future.set_exception(
                RuntimeError(str(error.get("message", "parent request failed")))
            )
            return True
        result = message.get("result")
        if not isinstance(result, dict):
            result = {}
        future.set_result(result)
        return True

    async def _handle_bootstrap(self, params: dict[str, Any], request_id: int) -> None:
        stub = bool(params.get("stub", False))
        workspace = Path(str(params.get("workspace_root", ".")))
        self._workspace_root = workspace.resolve()
        self._session_id = str(params.get("session_id", "worker"))
        set_approval_broker(self._approval)
        self._agent = await asyncio.to_thread(
            bootstrap_agent,
            stub=stub,
            workspace_root=self._workspace_root,
        )
        await self._flush_pending_writes()
        await write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"ok": True, "workspace_root": str(self._workspace_root)},
            }
        )

    async def _handle_prompt(self, params: dict[str, Any], request_id: int) -> None:
        if self._agent is None:
            await write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32002, "message": "bootstrap first"},
                }
            )
            return
        text = str(params.get("text", ""))
        run_id = str(params.get("run_id") or uuid.uuid4().hex)
        session_id = str(params.get("session_id", self._session_id))

        def emit(notification: BaseModel) -> None:
            self._schedule_write(model_to_notification(notification))

        tui = ProtocolTui(session_id, emit)
        expanded = bool(params.get("thinking_expanded", self._thinking_expanded))
        self._thinking_expanded = expanded
        tui.set_thinking_expanded(expanded)
        tokens = bind_prompt_context(session_id, tui)
        self._active_tui = tui
        session = Session(
            session_id=session_id,
            workspace_root=self._workspace_root,
            emit=emit,
        )
        try:
            result = await session.prompt(
                self._agent, text, mode=str(params.get("mode", "build")), run_id=run_id
            )
        except Exception as exc:
            await write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc)},
                }
            )
            return
        finally:
            reset_prompt_context(tokens)
            self._active_tui = None

        # Ensure notifications (e.g. reasoning_snapshot) reach stdout before
        # the result, so the client never observes the result arrive first.
        await self._flush_pending_writes()
        await write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "run_id": run_id,
                    "status": result.status,
                    "text": result.answer,
                    "thinking": result.thinking,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
            }
        )

    async def _handle_interrupt(self, request_id: int) -> None:
        cancelled = False
        if self._agent is not None:
            session = Session(
                session_id=self._session_id,
                workspace_root=self._workspace_root,
                emit=lambda _n: None,
            )
            cancelled = session.interrupt(self._agent)
        await write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"cancelled": cancelled},
            }
        )

    async def _handle_set_thinking_expanded(
        self, params: dict[str, Any], request_id: int
    ) -> None:
        expanded = bool(params.get("expanded", False))
        self._thinking_expanded = expanded
        tui = self._active_tui or get_bound_tui()
        if tui is not None and hasattr(tui, "set_thinking_expanded"):
            tui.set_thinking_expanded(expanded)
        await write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"ok": True, "expanded": expanded},
            }
        )

    async def _dispatch(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            if self._resolve_parent_response(message):
                return
        if message.get("method") is None:
            return
        request_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        method = str(message.get("method", ""))
        if method == "bootstrap":
            await self._handle_bootstrap(params, int(request_id))
        elif method == "prompt":
            await self._handle_prompt(params, int(request_id))
        elif method == "interrupt":
            await self._handle_interrupt(int(request_id))
        elif method == "thinking/set_expanded":
            await self._handle_set_thinking_expanded(params, int(request_id))
        elif method == "shutdown":
            await write_message(
                {"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}
            )
            raise SystemExit(0)
        else:
            await write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"unknown method: {method}"},
                }
            )

    async def _dispatch_safe(self, message: dict[str, Any]) -> None:
        try:
            await self._dispatch(message)
        except SystemExit:
            raise
        except Exception:
            _logger.exception("worker dispatch failed for %s", message)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if "id" in message and ("result" in message or "error" in message):
                if self._resolve_parent_response(message):
                    continue
            asyncio.create_task(self._dispatch_safe(message))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    asyncio.run(AgentWorker().run())


if __name__ == "__main__":
    main()
