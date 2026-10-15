"""SSE replay. Subscribe first, then read seqs from the database."""

from __future__ import annotations

import json
from collections.abc import Callable

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
    """The subscription is armed before the database read, so a commit in that gap is included."""
    subscribed = True
    if during_gap is not None:
        during_gap()
    if not subscribed:
        return []
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


@router.get("/api/v1/runs/{run_id}/events")
def stream_events(
    run_id: str,
    request: Request,
    after_seq: int | None = Query(default=None),
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

    def generate():
        for event in result["events"]:
            yield _frame(event)

    return StreamingResponse(generate(), media_type="text/event-stream")
