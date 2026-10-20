"""Authorized terminal sessions. The PTY outlives any one browser socket."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field

from rxycode_server.api.auth import _lookup_session, current_record, require_write

router = APIRouter()


def _runner():
    root = Path(__file__).resolve().parents[4] / "rxycode-runner" / "src"
    entry = str(root)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    from rxycode_runner.local import pty as backend

    return backend


class OpenIn(BaseModel):
    argv: list[str] = Field(min_length=1)
    cols: int = 80
    rows: int = 24
    tenant_id: str | None = None
    host: str | None = None


def _owns(session: object, tenant_id: str, user_id: str) -> bool:
    return getattr(session, "tenant_id", None) == tenant_id and getattr(session, "user_id", None) == user_id


def _record(websocket: WebSocket):
    raw = websocket.cookies.get("rxy_session", "")
    if not raw:
        return None
    return _lookup_session(websocket.app, raw)


@router.post("/api/v1/terminals", status_code=201)
def open_terminal(payload: OpenIn, request: Request) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if payload.cols < 1 or payload.rows < 1 or payload.cols > 500 or payload.rows > 500:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if any(not isinstance(item, str) or not item or "\x00" in item for item in payload.argv):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    backend = _runner()
    sandboxed = request.app.state.mode == "cloud"
    try:
        session = backend.open_session(
            list(payload.argv),
            cols=payload.cols,
            rows=payload.rows,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            sandboxed=sandboxed,
            workspace_root=None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="SANDBOX_REQUIRED") from exc
    return {"id": session.id, "pid": session.pid, "exit_code": None}


@router.get("/api/v1/terminals/{terminal_id}")
def read_terminal(terminal_id: str, request: Request) -> dict[str, object]:
    record = current_record(request)
    session = _runner().get_session(terminal_id)
    if session is None or not _owns(session, record.tenant_id, record.user_id):
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return {
        "id": session.id,
        "pid": session.pid,
        "alive": session.alive,
        "exit_code": session.exit_code,
        "scrollback": session.text(),
    }


@router.websocket("/api/v1/terminals/{terminal_id}/ws")
async def stream_terminal(websocket: WebSocket, terminal_id: str) -> None:
    origin = websocket.headers.get("origin") or ""
    allowed = getattr(websocket.app.state, "allowed_origins", None) or ()
    mode = getattr(websocket.app.state, "mode", "")
    if (mode == "cloud" or allowed) and origin not in allowed:
        await websocket.close(code=1008, reason="ORIGIN_FORBIDDEN")
        return
    record = _record(websocket)
    session = _runner().get_session(terminal_id)
    if record is None or session is None or not _owns(session, record.tenant_id, record.user_id):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    queued, queue = session.attach()
    if queued:
        await websocket.send_json({"type": "output", "data": queued})

    async def pump() -> None:
        while True:
            frame = await queue.get()
            await websocket.send_json(frame)

    async def incoming() -> None:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            kind = str(message.get("type", ""))
            if kind == "input":
                session.write(str(message.get("data", "")))
            elif kind == "resize":
                session.resize(int(message["cols"]), int(message["rows"]))

    pump_task = asyncio.create_task(pump())
    incoming_task = asyncio.create_task(incoming())
    try:
        done, pending = await asyncio.wait(
            {pump_task, incoming_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    finally:
        session.unsubscribe(queue)
