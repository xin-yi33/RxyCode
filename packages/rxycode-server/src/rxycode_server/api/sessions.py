"""Session lifecycle — list filters, rename/pin/move, archive, delete.

The lifecycle is server-side state, not a list filter: ``archived_at`` freezes
execution (submit/steer/schedule all refuse), ``deleted_at`` seals the session
from every read path before exclusive content is cleaned up. Active-run
mutations take the session row FOR UPDATE so the busy check and the state
change are one atomic step.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.persistence.models import (
    Project,
    Run,
    SessionRow,
    User,
    UserSessionMeta,
)

router = APIRouter()
_LIVE_RUN_STATUSES = (
    "pending",
    "running",
    "leased",
    "cancel_requested",
    "waiting_approval",
)
_PAGE_LIMIT = 100


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    stamp = _aware(value)
    return stamp.isoformat() if stamp is not None else None


def _meta_map(db: Session, user_id: str, session_ids: list[str]) -> dict[str, UserSessionMeta]:
    if not session_ids:
        return {}
    rows = db.scalars(
        select(UserSessionMeta).where(
            UserSessionMeta.user_id == user_id,
            UserSessionMeta.session_id.in_(session_ids),
        )
    ).all()
    return {row.session_id: row for row in rows}


def _last_runs(db: Session, tenant_id: str, session_ids: list[str]) -> dict[str, dict[str, str]]:
    if not session_ids:
        return {}
    rows = db.scalars(
        select(Run)
        .where(Run.tenant_id == tenant_id, Run.session_id.in_(session_ids))
        .order_by(Run.created_at.desc(), Run.id.desc())
    ).all()
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.session_id not in latest:
            latest[row.session_id] = {"run_id": row.id, "status": row.status}
    return latest


def session_item(
    row: SessionRow,
    *,
    project_name: str | None,
    is_default_project: bool,
    meta: UserSessionMeta | None,
    last_run: dict[str, str] | None,
) -> dict[str, object]:
    """The safe session item — lifecycle fields plus per-user pin state."""
    archived = row.archived_at is not None
    return {
        "id": row.id,
        "title": row.title,
        "project_id": row.project_id,
        "project_name": project_name,
        "is_default_project": is_default_project,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "archived_at": _iso(row.archived_at),
        "archived": archived,
        "origin": row.origin or "cloud",
        "source": row.source or "chat",
        "pinned": bool(meta.pinned) if meta else False,
        "pin_order": meta.pin_order if meta else None,
        "revision": int(row.revision or 0),
        "last_run": last_run,
        "can_execute": not archived,
        "blocked_reason": "archived" if archived else "",
    }


def _project_names(
    db: Session, tenant_id: str, project_ids: list[str]
) -> dict[str, tuple[str, bool]]:
    if not project_ids:
        return {}
    rows = db.scalars(
        select(Project).where(Project.tenant_id == tenant_id, Project.id.in_(set(project_ids)))
    ).all()
    return {row.id: (row.name, bool(row.is_default)) for row in rows}


def _locked_session(db: Session, tenant_id: str, session_id: str) -> SessionRow:
    row = db.execute(
        select(SessionRow)
        .where(
            SessionRow.id == session_id,
            SessionRow.tenant_id == tenant_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return row


def _has_active_run(db: Session, session_id: str) -> bool:
    return (
        db.scalar(
            select(func.count(Run.id)).where(
                Run.session_id == session_id,
                Run.status.in_(_LIVE_RUN_STATUSES),
            )
        )
        or 0
    ) > 0


def _check_revision(row: SessionRow, expected: int | None) -> None:
    if expected is not None and int(row.revision or 0) != expected:
        raise HTTPException(status_code=409, detail="REVISION_CONFLICT")


def _bump(row: SessionRow) -> None:
    row.revision = int(row.revision or 0) + 1


def _meta_for(
    db: Session, user_id: str, session_id: str, *, create: bool = False
) -> UserSessionMeta | None:
    meta = db.get(UserSessionMeta, (user_id, session_id))
    if meta is None and create:
        meta = UserSessionMeta(user_id=user_id, session_id=session_id)
        db.add(meta)
        db.flush()
    return meta


def _pause_schedules(db: Session, tenant_id: str, session_id: str) -> int:
    """Pause this session's schedules; archive does not silently resume them."""
    result = db.execute(
        text(
            """
            UPDATE web_schedules
            SET enabled = false, blocked_reason = 'archived'
            WHERE tenant_id = :tenant AND session_id = :session AND enabled = true
            """
        ),
        {"tenant": tenant_id, "session": session_id},
    )
    return int(result.rowcount or 0)


class _PatchIn(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    project_id: str | None = None
    expected_revision: int | None = None


class _RevisionIn(BaseModel):
    expected_revision: int | None = None


class _DeleteIn(BaseModel):
    expected_revision: int | None = None
    confirm: bool = False


def _default_project_id(db: Session, record) -> str:
    user = db.get(User, record.user_id)
    if user is not None and user.default_project_id:
        return user.default_project_id
    from rxycode_server.api.auth import _ensure_default_project

    project_id = _ensure_default_project(db, record.tenant_id)
    project = db.get(Project, project_id)
    if project is not None:
        project.is_default = True
    if user is not None:
        user.default_project_id = project_id
    db.flush()
    return project_id


def _finish(db: Session, record, row: SessionRow) -> dict[str, object]:
    names = _project_names(db, record.tenant_id, [row.project_id])
    pname, pdefault = names.get(row.project_id, (None, False))
    meta = _meta_for(db, record.user_id, row.id)
    last = _last_runs(db, record.tenant_id, [row.id]).get(row.id)
    return session_item(
        row, project_name=pname, is_default_project=pdefault, meta=meta, last_run=last
    )


def _encode_cursor(sort: str, row: SessionRow, meta: UserSessionMeta | None) -> str:
    if sort == "title":
        key = row.title or ""
    elif sort == "created_at":
        key = _iso(row.created_at) or ""
    elif sort == "manual":
        key = str(meta.manual_order if meta and meta.manual_order is not None else 0)
    else:
        key = _iso(row.updated_at) or ""
    raw = json.dumps([sort, key, row.id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(raw: str, sort: str) -> tuple[str, str] | None:
    try:
        kind, key, row_id = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        if kind != sort:
            return None
        return str(key), str(row_id)
    except (ValueError, TypeError, KeyError):
        return None


@router.patch("/api/v1/sessions/{session_id}")
def patch_session(
    session_id: str,
    payload: _PatchIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    row = _locked_session(db, record.tenant_id, session_id)
    _check_revision(row, payload.expected_revision)

    if payload.title is not None:
        title = payload.title.strip()
        if not 1 <= len(title) <= 200:
            raise HTTPException(status_code=400, detail="INVALID_INPUT")
        row.title = title
        # Rename never reorders the activity list.
        _bump(row)

    if payload.pinned is not None:
        meta = _meta_for(db, record.user_id, row.id, create=True)
        meta.pinned = bool(payload.pinned)
        if meta.pinned and meta.pin_order is None:
            top = db.scalar(
                select(func.max(UserSessionMeta.pin_order)).where(
                    UserSessionMeta.user_id == record.user_id,
                    UserSessionMeta.pinned == True,  # noqa: E712
                )
            )
            meta.pin_order = int(top or 0) + 1
        elif not meta.pinned:
            meta.pin_order = None
        _bump(row)

    if payload.project_id is not None:
        if _has_active_run(db, row.id):
            raise HTTPException(status_code=409, detail="SESSION_BUSY")
        if payload.project_id in ("", "none"):
            target = _default_project_id(db, record)
        else:
            project = db.scalars(
                select(Project).where(
                    Project.id == payload.project_id,
                    Project.tenant_id == record.tenant_id,
                )
            ).one_or_none()
            if project is None:
                raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
            target = project.id
        if target != row.project_id:
            row.project_id = target
            _bump(row)

    db.flush()
    return {"session": _finish(db, record, row)}


@router.post("/api/v1/sessions/{session_id}/archive")
def archive_session(
    session_id: str,
    payload: _RevisionIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    row = _locked_session(db, record.tenant_id, session_id)
    _check_revision(row, payload.expected_revision)
    paused = 0
    if row.archived_at is None:
        if _has_active_run(db, row.id):
            raise HTTPException(status_code=409, detail="SESSION_BUSY")
        row.archived_at = datetime.now(timezone.utc)
        paused = _pause_schedules(db, record.tenant_id, row.id)
        _bump(row)
        db.flush()
    # Repeat archives are idempotent — return the current state.
    return {"session": _finish(db, record, row), "paused_schedule_count": paused}


@router.post("/api/v1/sessions/{session_id}/unarchive")
def unarchive_session(
    session_id: str,
    payload: _RevisionIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    row = _locked_session(db, record.tenant_id, session_id)
    _check_revision(row, payload.expected_revision)
    if row.archived_at is not None:
        row.archived_at = None
        _bump(row)
        db.flush()
    # Schedules paused by the archive stay paused — no surprise paid catch-ups.
    return {"session": _finish(db, record, row), "paused_schedule_count": 0}


@router.delete("/api/v1/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    payload: _DeleteIn,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="CONFIRM_REQUIRED")
    row = _locked_session(db, record.tenant_id, session_id)
    _check_revision(row, payload.expected_revision)
    if _has_active_run(db, row.id):
        raise HTTPException(status_code=409, detail="SESSION_BUSY")
    # Tombstone first: every read path excludes deleted_at from this instant,
    # then exclusive content is cleaned out of band by purge_deleted_sessions.
    row.deleted_at = datetime.now(timezone.utc)
    _bump(row)
    db.execute(
        text(
            """
            UPDATE web_schedules
            SET enabled = false, blocked_reason = 'deleted'
            WHERE tenant_id = :tenant AND session_id = :session
            """
        ),
        {"tenant": record.tenant_id, "session": session_id},
    )
    db.flush()
    return None


def purge_deleted_sessions(db: Session, *, older_than: datetime) -> int:
    """Physically remove tombstoned sessions and their exclusive rows.

    Runs/events/approvals/artifacts belong to the session — they go with it.
    Shared project files and billing/audit ledgers are never touched.
    """
    from rxycode_server.persistence.models import (
        Approval,
        Artifact,
        RunEvent,
        ToolInvocation,
    )

    doomed = db.scalars(select(SessionRow.id).where(SessionRow.deleted_at < older_than)).all()
    if not doomed:
        return 0
    run_ids = db.scalars(select(Run.id).where(Run.session_id.in_(doomed))).all()
    if run_ids:
        db.execute(
            text(
                "DELETE FROM outbox WHERE event_id IN (SELECT event_id FROM run_events WHERE run_id = ANY(:ids))"
            ),
            {"ids": list(run_ids)},
        )
        for model in (Approval, RunEvent, ToolInvocation, Artifact):
            db.execute(model.__table__.delete().where((model.run_id.in_(run_ids))))
        db.execute(
            text("DELETE FROM schedule_executions WHERE run_id = ANY(:ids)"),
            {"ids": list(run_ids)},
        )
        db.execute(
            text("DELETE FROM usage_records WHERE run_id = ANY(:ids)"),
            {"ids": list(run_ids)},
        )
        db.execute(Run.__table__.delete().where(Run.id.in_(run_ids)))
    db.execute(
        text("DELETE FROM web_schedules WHERE session_id = ANY(:ids)"),
        {"ids": list(doomed)},
    )
    db.execute(
        text("DELETE FROM user_session_meta WHERE session_id = ANY(:ids)"),
        {"ids": list(doomed)},
    )
    db.execute(
        text("DELETE FROM web_notifications WHERE run_id = ANY(:ids)"),
        {"ids": list(run_ids)},
    )
    db.execute(SessionRow.__table__.delete().where(SessionRow.id.in_(doomed)))
    return len(doomed)


# -- list (replaces the plain tenant list; same route, richer contract) -------


def list_sessions_filtered(
    request: Request,
    db: Session,
    *,
    archived: str = "false",
    pinned: str | None = None,
    project_id: str | None = None,
    origin: str = "all",
    source: str = "all",
    sort: str = "updated_at",
    q: str = "",
    cursor: str = "",
    limit: int = 30,
) -> dict[str, object]:
    record = current_record(request)
    if archived not in ("false", "true", "all"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if sort not in ("updated_at", "created_at", "title", "manual"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if origin not in ("all", "local", "cloud"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if source not in ("all", "chat", "scheduled"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if len(q or "") > 200:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    limit = max(1, min(int(limit or 30), _PAGE_LIMIT))

    query = (
        select(SessionRow, UserSessionMeta)
        .outerjoin(
            UserSessionMeta,
            (UserSessionMeta.session_id == SessionRow.id)
            & (UserSessionMeta.user_id == record.user_id),
        )
        .where(SessionRow.tenant_id == record.tenant_id)
        .where(SessionRow.deleted_at.is_(None))
    )
    if archived == "false":
        query = query.where(SessionRow.archived_at.is_(None))
    elif archived == "true":
        query = query.where(SessionRow.archived_at.isnot(None))
    if pinned == "true":
        query = query.where(UserSessionMeta.pinned == True)  # noqa: E712
    elif pinned == "false":
        query = query.where(
            or_(UserSessionMeta.pinned == False, UserSessionMeta.pinned.is_(None))  # noqa: E712
        )
    if project_id == "none":
        default_id = _default_project_id(db, record)
        query = query.where(SessionRow.project_id == default_id)
    elif project_id:
        query = query.where(SessionRow.project_id == project_id)
    if origin != "all":
        query = query.where(SessionRow.origin == origin)
    if source != "all":
        query = query.where(SessionRow.source == source)
    if q:
        like = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(SessionRow.title.ilike(like))

    mark = _decode_cursor(cursor, sort) if cursor else None
    if cursor and mark is None:
        raise HTTPException(status_code=400, detail="INVALID_CURSOR")

    if sort == "title":
        order_col = func.lower(SessionRow.title)
        query = query.order_by(order_col, SessionRow.id)
        if mark:
            key, last_id = mark
            query = query.where(
                (func.lower(SessionRow.title) > key.lower())
                | ((func.lower(SessionRow.title) == key.lower()) & (SessionRow.id > last_id))
            )
    elif sort == "created_at":
        query = query.order_by(SessionRow.created_at.desc().nulls_last(), SessionRow.id.desc())
        if mark:
            key, last_id = mark
            try:
                moment = datetime.fromisoformat(key) if key else None
            except ValueError:
                moment = None
            if moment is not None:
                query = query.where(
                    (SessionRow.created_at < moment)
                    | ((SessionRow.created_at == moment) & (SessionRow.id < last_id))
                )
    elif sort == "manual":
        query = query.order_by(
            UserSessionMeta.manual_order.asc().nulls_last(),
            SessionRow.updated_at.desc(),
            SessionRow.id.desc(),
        )
        if mark:
            _key, last_id = mark
            # manual cursors key off the last id; position comes from order.
            anchor = db.scalars(select(SessionRow).where(SessionRow.id == last_id)).one_or_none()
            if anchor is not None:
                anchor_meta = db.get(UserSessionMeta, (record.user_id, last_id))
                if anchor_meta is not None and anchor_meta.manual_order is not None:
                    query = query.where(
                        (UserSessionMeta.manual_order > anchor_meta.manual_order)
                        | (
                            UserSessionMeta.manual_order.is_(None)
                            & (SessionRow.updated_at < anchor.updated_at)
                        )
                    )
    else:
        query = query.order_by(SessionRow.updated_at.desc().nulls_last(), SessionRow.id.desc())
        if mark:
            key, last_id = mark
            try:
                moment = datetime.fromisoformat(key) if key else None
            except ValueError:
                moment = None
            if moment is not None:
                query = query.where(
                    (SessionRow.updated_at < moment)
                    | ((SessionRow.updated_at == moment) & (SessionRow.id < last_id))
                )

    rows = db.scalars(query.limit(limit + 1)).all()
    # outerjoin on scalars returns SessionRow only — fetch metas separately.
    session_ids = [row.id for row in rows]
    metas = _meta_map(db, record.user_id, session_ids)
    next_cursor = ""
    if len(rows) > limit:
        rows = rows[:limit]
        session_ids = [row.id for row in rows]
        next_cursor = _encode_cursor(sort, rows[-1], metas.get(rows[-1].id))
    latest = _last_runs(db, record.tenant_id, session_ids)
    names = _project_names(db, record.tenant_id, [row.project_id for row in rows])
    return {
        "sessions": [
            session_item(
                row,
                project_name=names.get(row.project_id, (None, False))[0],
                is_default_project=names.get(row.project_id, (None, False))[1],
                meta=metas.get(row.id),
                last_run=latest.get(row.id),
            )
            for row in rows
        ],
        "next_cursor": next_cursor or None,
    }
