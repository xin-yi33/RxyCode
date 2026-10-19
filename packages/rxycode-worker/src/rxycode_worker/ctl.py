"""Per-run control channel between the drain (trusted parent) and the
confined turn (untrusted child).

The confined turn must never hold the platform database credentials, the
Docker socket, or another tenant's secret: every control-plane operation it
needs is proxied through this channel. The drain opens one UNIX socket per
run inside a task-private directory that is bound into the sandbox; the
child speaks a one-request-per-connection JSON protocol.

Wire format (UTF-8 JSON, one object per connection, ``\\n``-terminated)::

    request : {"op": "<name>", "args": {...}}
    response: {"ok": true,  "result": <any>}
             | {"ok": false, "error": {"type": "<class>", "message": "..."}}

Boundaries enforced here, not by convention:

* The socket lives in a directory bound only into the owning run's
  sandbox — a sibling tenant's filesystem view never contains it.
* Every handler is bound to the drain's ``(tenant_id, run_id, worker_id,
  epoch)`` at accept time: a turn can only ever act on its own run, and
  lease-fenced service calls still refuse once the claim is gone.
* Payloads are capped (``_MAX_REQUEST_BYTES``); the child can flood its own
  log at worst — the same blast radius it already had via direct writes.

The client is synchronous on purpose: journal/emit call sites are a mix of
loop and thread contexts, matching the blocking profile ``append_event``
already had.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

#: One request is one JSON object; bigger payloads are refused whole.
_MAX_REQUEST_BYTES = 512 * 1024


class CtlError(RuntimeError):
    """Raised on the child side when the parent reports a failure."""

    def __init__(self, err_type: str, message: str) -> None:
        super().__init__(f"{err_type}: {message}")
        self.err_type = err_type


def ctl_call(sock_path: str | os.PathLike[str], op: str, *, timeout: float = 30.0, **args: Any) -> Any:
    """One synchronous request/response round-trip on the control socket.

    Each call opens a fresh connection — safe from loop threads and worker
    threads alike (no shared state, no half-written frames).
    """
    request = json.dumps({"op": str(op), "args": args}, ensure_ascii=False).encode("utf-8") + b"\n"
    if len(request) > _MAX_REQUEST_BYTES:
        raise CtlError("request_too_large", f"{op} payload exceeds {_MAX_REQUEST_BYTES} bytes")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(str(sock_path))
        sock.sendall(request)
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        chunks: list[bytes] = []
        while True:
            part = sock.recv(65536)
            if not part:
                break
            chunks.append(part)
            if sum(len(c) for c in chunks) > _MAX_REQUEST_BYTES:
                raise CtlError("response_too_large", f"{op} reply exceeds cap")
    finally:
        sock.close()
    raw = b"".join(chunks).strip()
    if not raw:
        raise CtlError("empty_response", f"{op} returned no data")
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CtlError("bad_response", f"{op} reply is not JSON: {exc}") from exc
    if not isinstance(response, dict):
        raise CtlError("bad_response", f"{op} reply is not an object")
    if response.get("ok"):
        return response.get("result")
    error = response.get("error") or {}
    raise CtlError(
        str(error.get("type") or "error"),
        str(error.get("message") or ""),
    )


class CtlServer:
    """Async UNIX-socket server owned by the drain for one run.

    Handlers are plain callables ``dict -> any``; each runs in a worker
    thread (they are synchronous DB calls) so a slow query never stalls the
    drain loop.
    """

    def __init__(
        self,
        sock_path: Path,
        handlers: Mapping[str, Callable[[dict[str, Any]], Any]],
    ) -> None:
        self.sock_path = Path(sock_path)
        self._handlers = dict(handlers)
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self.sock_path)
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        try:
            self.sock_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                raw = await asyncio.wait_for(reader.read(_MAX_REQUEST_BYTES + 1), timeout=60.0)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                raw = b""
            response = await self._dispatch(raw)
        except Exception as exc:  # never wedge the child on a framing bug
            _LOG.warning("ctl dispatch failed", exc_info=True)
            response = {"ok": False, "error": {"type": "internal", "message": str(exc)[:400]}}
        try:
            writer.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    async def _dispatch(self, raw: bytes) -> dict[str, Any]:
        if not raw or len(raw) > _MAX_REQUEST_BYTES:
            return {"ok": False, "error": {"type": "bad_request", "message": "empty or oversized"}}
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "error": {"type": "bad_request", "message": "not JSON"}}
        if not isinstance(request, dict):
            return {"ok": False, "error": {"type": "bad_request", "message": "not an object"}}
        op = str(request.get("op") or "")
        args = request.get("args")
        handler = self._handlers.get(op)
        if handler is None or not isinstance(args, dict):
            return {"ok": False, "error": {"type": "unknown_op", "message": op[:80]}}
        try:
            result = await asyncio.to_thread(handler, args)
        except Exception as exc:
            return {
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)[:800]},
            }
        return {"ok": True, "result": result}


class TurnChannel:
    """Child-side handle over the per-run control socket.

    One method per op, all synchronous — the same call profile the direct
    ``append_event``/``load_*`` functions had, so loop threads and worker
    threads can both use it without an event loop.
    """

    def __init__(self, sock_path: str | os.PathLike[str]) -> None:
        self.sock_path = str(sock_path)

    def _call(self, op: str, *, timeout: float = 30.0, **args: Any) -> Any:
        return ctl_call(self.sock_path, op, timeout=timeout, **args)

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> int:
        """Append one event to the run's own log; returns the row seq."""
        result = self._call("emit", type=str(event_type), payload=dict(payload))
        return int((result or {}).get("seq") or 0)

    def load_run(self) -> dict[str, Any]:
        """The run row fields the turn needs (message/session binding)."""
        return dict(self._call("load_run") or {})

    def commands(self, after_seq: int) -> list[dict[str, Any]]:
        """Steer/child-cancel events committed after ``after_seq`` — same
        shape ``load_command_events`` returns for the DB-backed path."""
        result = self._call("commands", after_seq=int(after_seq))
        return list((result or {}).get("events") or [])

    def pause_approval(
        self,
        *,
        source_call_id: str,
        tool: str,
        permission_scope: str,
        arguments: Mapping[str, Any],
        deadline: str,
        workdir: str,
        command: str,
    ) -> dict[str, Any]:
        """Persist a durable approval request and park the run.

        ``source_call_id`` is the raw orchestrator/model call id — the
        parent derives the journal-keyed durable ``call_id`` so a confined
        child cannot pick a key that collides across runs.

        ``{"asked": True}`` means the run is now ``waiting_approval`` and
        the lease is released — the caller must unwind without writing.
        ``{"asked": False, "reason": ...}`` means the ask resolved
        synchronously (already authorized in this mode / approvals off) and
        the call may proceed or must be refused per ``reason``.
        """
        return dict(
            self._call(
                "pause_approval",
                source_call_id=str(source_call_id),
                tool=str(tool),
                scope=str(permission_scope),
                arguments=dict(arguments),
                deadline=str(deadline),
                workdir=str(workdir),
                command=str(command),
            )
            or {}
        )

    def resume_state(self, approval_id: str) -> dict[str, Any]:
        """Fetch the stored call for an approved approval bound to THIS run."""
        return dict(self._call("resume_state", approval_id=str(approval_id)) or {})

    # -- parent-owned journal ops ----------------------------------------
    # The approval-resume journal lives in the drain's state dir — never
    # in child-writable storage. These three ops are the child's only
    # access; the parent runs the real RemoteJournalAdapter.

    def journal_state(self, *, attempt_id: str, call_id: str) -> str:
        result = self._call(
            "journal_state", attempt_id=str(attempt_id), call_id=str(call_id)
        )
        return str((result or {}).get("state") or "unknown")

    def journal_reserve(
        self, *, attempt_id: str, call_id: str, tool: str, args: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = self._call(
            "journal_reserve",
            attempt_id=str(attempt_id),
            call_id=str(call_id),
            tool=str(tool),
            args=dict(args or {}),
        )
        return dict(result or {})

    def journal_complete(
        self,
        *,
        attempt_id: str,
        call_id: str,
        tool: str,
        args: Mapping[str, Any],
        result: str,
    ) -> str:
        out = self._call(
            "journal_complete",
            attempt_id=str(attempt_id),
            call_id=str(call_id),
            tool=str(tool),
            args=dict(args or {}),
            result=str(result),
        )
        if dict(out or {}).get("refused"):
            # The pair is not this run's stored approval — an empty
            # return here would fake a completion, so the refusal must
            # surface as an error.
            raise RuntimeError("journal_complete refused: unbound call")
        return str((out or {}).get("result") or "")
