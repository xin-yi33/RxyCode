"""SSE replay. Subscribe first, then keep reading new seqs from the database."""

from __future__ import annotations

import json
import time
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


def iter_frames(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    after_seq: int,
    redis_client=None,
    follow: bool = False,
) -> Iterator[str]:
    """Subscribe before the first read. A later heartbeat reads the database again."""
    pubsub = None
    if redis_client is not None:
        pubsub = redis_client.pubsub()
        pubsub.subscribe(f"rxycode:run:{run_id}")
    sent: set[int] = set()
    cursor, frames = _pull(database_url, tenant_id, run_id, after_seq, sent)
    yield from frames
    cursor, frames = _pull(database_url, tenant_id, run_id, cursor, sent)
    yield from frames
    if not follow:
        if pubsub is not None:
            pubsub.close()
        return
    if pubsub is not None:
        pubsub.get_message(timeout=0.05)
    time.sleep(0.6)
    _cursor, frames = _pull(database_url, tenant_id, run_id, cursor, sent)
    yield from frames
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

    def generate():
        yield from iter_frames(
            request.app.state.database_url,
            tenant_id=record.tenant_id,
            run_id=run_id,
            after_seq=cursor,
            redis_client=redis_client,
            follow=bool(follow),
        )

    return StreamingResponse(generate(), media_type="text/event-stream")
