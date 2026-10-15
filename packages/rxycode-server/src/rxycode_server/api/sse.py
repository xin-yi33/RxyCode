"""SSE replay. Subscribe first, then keep reading new seqs from the database."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from rxycode_server.api.auth import current_record
from rxycode_server.events.store import replay

router = APIRouter()


def follow_after_subscribe(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    after_seq: int,
    during_gap: Callable[[], None] | None = None,
) -> list[dict]:
    """Arm the subscription, allow the gap callback, then read the database."""
    if during_gap is not None:
        during_gap()
    result = replay(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        after_seq=after_seq,
    )
    return list(result.get("events") or [])


def _cursor(after_seq: int | None, last_event_id: str | None) -> int | None:
    """An explicit after_seq wins. Last-Event-ID is the fallback."""
    if after_seq is not None:
        return after_seq
    if last_event_id is None or last_event_id == "":
        return 0
    try:
        return int(last_event_id)
    except ValueError:
        return None


def _frame(event: dict) -> str:
    body = json.dumps(
        {"seq": event["seq"], "type": event["type"], "payload": event["payload"]},
        separators=(",", ":"),
    )
    return f"id: {event['seq']}\ndata: {body}\n\n"


def _pull(database_url: str, tenant_id: str, run_id: str, cursor: int, sent: set[int]) -> tuple[int, list[str]]:
    result = replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=cursor)
    if result.get("code"):
        return cursor, []
    frames: list[str] = []
    for event in result["events"]:
        seq = int(event["seq"])
        if seq in sent:
            continue
        sent.add(seq)
        cursor = seq
        frames.append(_frame(event))
    return cursor, frames


_TERMINAL = {"succeeded", "failed", "cancelled", "recovery_required"}


def _run_status(database_url: str, run_id: str) -> str:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return str(conn.execute(text("SELECT status FROM runs WHERE id = :id"), {"id": run_id}).scalar())
    finally:
        engine.dispose()


async def iter_frames(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    after_seq: int,
    redis_client=None,
    follow: bool = False,
    is_disconnected: Callable[[], bool] | None = None,
):
    """Subscribe before the first read. Follow keeps polling until disconnect or a terminal run."""
    pubsub = None
    sent: set[int] = set()
    cursor = after_seq
    try:
        yield ": open\n\n"
        if redis_client is not None:
            pubsub = redis_client.pubsub()
            await asyncio.to_thread(pubsub.subscribe, f"rxycode:run:{run_id}")
        while True:
            if is_disconnected is not None:
                try:
                    if await asyncio.wait_for(is_disconnected(), timeout=0.05):
                        return
                except TimeoutError:
                    pass
            cursor, frames = _pull(database_url, tenant_id, run_id, cursor, sent)
            for frame in frames:
                yield frame
            if not follow:
                return
            if _run_status(database_url, run_id) in _TERMINAL and not frames:
                return
            if pubsub is not None:
                pubsub.get_message(timeout=0.05)
            await asyncio.sleep(0.25)
    finally:
        if pubsub is not None:
            pubsub.close()


@router.get("/api/v1/runs/{run_id}/events")
def stream_events(
    run_id: str,
    request: Request,
    after_seq: int | None = Query(default=None),
    follow: int = Query(default=0),
):
    record = current_record(request)
    cursor = _cursor(after_seq, request.headers.get("last-event-id"))
    if cursor is None or cursor < 0:
        return JSONResponse(status_code=409, content={"code": "CURSOR_EXPIRED", "events": []})
    result = replay(
        request.app.state.database_url,
        tenant_id=record.tenant_id,
        run_id=run_id,
        after_seq=cursor,
    )
    if result.get("code") == "RUN_NOT_FOUND":
        return JSONResponse(status_code=404, content={"code": "RUN_NOT_FOUND"})
    if result.get("code") == "CURSOR_EXPIRED":
        return JSONResponse(
            status_code=409,
            content={
                "code": "CURSOR_EXPIRED",
                "snapshot_seq": result["snapshot_seq"],
                "events": [],
            },
        )
    redis_client = getattr(request.app.state, "redis", None)

    async def generate():
        async for frame in iter_frames(
            request.app.state.database_url,
            tenant_id=record.tenant_id,
            run_id=run_id,
            after_seq=cursor,
            redis_client=redis_client,
            follow=bool(follow),
            is_disconnected=request.is_disconnected,
        ):
            yield frame

    return StreamingResponse(generate(), media_type="text/event-stream")
