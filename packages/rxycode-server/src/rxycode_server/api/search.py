"""GET /search — one cursor-paginated query over chats, images, documents and
projects. Substring matching on the database side; no search cluster, no
embeddings. Tombstoned sessions never appear, whatever the archived filter."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session
from rxycode_server.persistence.models import (
    Artifact,
    Project,
    Run,
    RunEvent,
    SessionRow,
)

router = APIRouter()
_TYPES = ("chat", "image", "document", "project")
_PAGE_LIMIT = 50


def _iso(value: datetime | None) -> str | None:
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value is not None else None


def _snippet(text: str, needle: str) -> tuple[str, list[list[int]]]:
    """Plain-text snippet ≤240 chars plus escaped highlight offsets."""
    flat = " ".join((text or "").split())
    if len(flat) > 240:
        flat = flat[:237] + "..."
    highlights: list[list[int]] = []
    if needle:
        lower = flat.lower()
        key = needle.lower()
        start = lower.find(key)
        while start != -1 and len(highlights) < 8:
            highlights.append([start, start + len(key)])
            start = lower.find(key, start + len(key))
    return flat, highlights


def _encode(kind: str, stamp: str, row_id: str) -> str:
    raw = json.dumps([kind, stamp, row_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode(raw: str) -> tuple[str, str, str] | None:
    try:
        kind, stamp, row_id = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        if kind not in _TYPES:
            return None
        return str(kind), str(stamp), str(row_id)
    except (ValueError, TypeError, KeyError):
        return None


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/api/v1/search")
def search(
    request: Request,
    q: str = "",
    type: str = "all",
    archived: str = "all",
    project_id: str | None = None,
    cursor: str = "",
    limit: int = 20,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    if type != "all" and type not in _TYPES:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if archived not in ("all", "true", "false"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if len(q or "") > 200:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    limit = max(1, min(int(limit or 20), _PAGE_LIMIT))
    mark = _decode(cursor) if cursor else None
    if cursor and mark is None:
        raise HTTPException(status_code=400, detail="INVALID_CURSOR")

    needle = (q or "").strip()
    hits: list[dict[str, object]] = []
    kinds = _TYPES if type == "all" else (type,)

    for kind in kinds:
        remaining = limit + 1 - len(hits)
        if remaining <= 0:
            break
        if kind == "chat":
            hits.extend(
                _chat_hits(
                    db,
                    record,
                    needle,
                    archived=archived,
                    project_id=project_id,
                    mark=mark if type == "chat" else None,
                    limit=remaining,
                )
            )
        elif kind == "project":
            hits.extend(
                _project_hits(
                    db,
                    record,
                    needle,
                    mark=mark if type == "project" else None,
                    limit=remaining,
                )
            )
        else:
            hits.extend(
                _artifact_hits(
                    db,
                    record,
                    needle,
                    kind,
                    archived=archived,
                    project_id=project_id,
                    mark=mark if type == kind else None,
                    limit=remaining,
                )
            )

    hits.sort(key=lambda h: (h["updated_at"] or "", str(h["id"])), reverse=True)
    next_cursor = None
    if len(hits) > limit:
        hits = hits[:limit]
        tail = hits[-1]
        next_cursor = _encode(str(tail["type"]), str(tail["updated_at"] or ""), str(tail["id"]))
    return {
        "query": needle,
        "type": type,
        "hits": hits,
        "next_cursor": next_cursor,
    }


def _session_filter(record, archived: str):
    clauses = [
        SessionRow.tenant_id == record.tenant_id,
        SessionRow.deleted_at.is_(None),
    ]
    if archived == "false":
        clauses.append(SessionRow.archived_at.is_(None))
    elif archived == "true":
        clauses.append(SessionRow.archived_at.isnot(None))
    return clauses


def _chat_hits(db, record, needle, *, archived, project_id, mark, limit):
    clauses = _session_filter(record, archived)
    if project_id:
        clauses.append(SessionRow.project_id == project_id)
    if needle:
        pat = _like(needle)
        # Title OR the first prompt of any run in the session.
        msg_sessions = (
            select(Run.session_id)
            .join(RunEvent, RunEvent.run_id == Run.id)
            .where(
                Run.tenant_id == record.tenant_id,
                RunEvent.type == "run.created",
                cast(RunEvent.payload["message"], Text).ilike(pat),
            )
        )
        clauses.append(or_(SessionRow.title.ilike(pat), SessionRow.id.in_(msg_sessions)))
    query = (
        select(SessionRow)
        .where(*clauses)
        .order_by(SessionRow.updated_at.desc().nulls_last(), SessionRow.id.desc())
        .limit(limit)
    )
    rows = db.scalars(query).all()
    out = []
    for row in rows:
        title = row.title or "Untitled chat"
        snippet_src = title
        if needle and needle.lower() not in title.lower():
            message = db.scalar(
                select(cast(RunEvent.payload["message"], Text))
                .join(Run, Run.id == RunEvent.run_id)
                .where(
                    Run.session_id == row.id,
                    Run.tenant_id == record.tenant_id,
                    RunEvent.type == "run.created",
                )
                .order_by(RunEvent.seq)
                .limit(1)
            )
            if message:
                snippet_src = str(message)
        snippet, highlights = _snippet(snippet_src, needle)
        out.append(
            {
                "id": row.id,
                "type": "chat",
                "title": title,
                "snippet": snippet,
                "highlights": highlights,
                "updated_at": _iso(row.updated_at),
                "session_id": row.id,
                "project_id": row.project_id,
                "archived": row.archived_at is not None,
                "href": f"/app/{row.id}",
                "preview": None,
            }
        )
    return out


def _project_hits(db, record, needle, *, mark, limit):
    clauses = [
        Project.tenant_id == record.tenant_id,
        Project.is_default == False,  # noqa: E712
    ]
    if needle:
        clauses.append(Project.name.ilike(_like(needle)))
    rows = db.scalars(
        select(Project)
        .where(*clauses)
        .order_by(Project.created_at.desc().nulls_last(), Project.id.desc())
        .limit(limit)
    ).all()
    out = []
    for row in rows:
        snippet, highlights = _snippet(row.name, needle)
        out.append(
            {
                "id": row.id,
                "type": "project",
                "title": row.name,
                "snippet": snippet,
                "highlights": highlights,
                "updated_at": _iso(row.created_at),
                "session_id": None,
                "project_id": row.id,
                "archived": False,
                "href": f"/app/p/{row.id}",
                "preview": None,
            }
        )
    return out


def _artifact_hits(db, record, needle, kind, *, archived, project_id, mark, limit):
    mime = "image/%" if kind == "image" else None
    clauses = [
        Run.tenant_id == record.tenant_id,
        SessionRow.deleted_at.is_(None),
    ]
    if archived == "false":
        clauses.append(SessionRow.archived_at.is_(None))
    elif archived == "true":
        clauses.append(SessionRow.archived_at.isnot(None))
    if project_id:
        clauses.append(SessionRow.project_id == project_id)
    if mime is not None:
        clauses.append(Artifact.content_type.ilike(mime))
    else:
        clauses.append(~Artifact.content_type.ilike("image/%"))
    if needle:
        clauses.append(Artifact.object_key.ilike(_like(needle)))
    rows = db.execute(
        select(Artifact, Run, SessionRow)
        .join(Run, Run.id == Artifact.run_id)
        .join(SessionRow, SessionRow.id == Run.session_id)
        .where(*clauses)
        .order_by(Run.created_at.desc().nulls_last(), Artifact.id.desc())
        .limit(limit)
    ).all()
    out = []
    for artifact, run, session in rows:
        name = artifact.object_key.rsplit("/", 1)[-1] or artifact.object_key
        snippet, highlights = _snippet(name, needle)
        out.append(
            {
                "id": artifact.id,
                "type": kind,
                "title": name,
                "snippet": snippet,
                "highlights": highlights,
                "updated_at": _iso(run.created_at),
                "session_id": run.session_id,
                "project_id": session.project_id,
                "archived": session.archived_at is not None,
                "href": f"/api/v1/artifacts/{artifact.id}",
                "preview": {
                    "content_type": artifact.content_type,
                    "size": int(artifact.size),
                },
            }
        )
    return out
