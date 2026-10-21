"""Run submission and history. The tenant comes from the session."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import (
    _ensure_default_project,
    current_record,
    db_session,
    require_write,
)
from rxycode_server.byok.resolver import resolve_run_model
from rxycode_server.persistence.models import (
    Outbox,
    Project,
    Run,
    RunEvent,
    SessionRow,
    User,
)
from rxycode_server.quotas.service import QuotaRefused
from rxycode_server.runs.service import (
    RunAlreadyActive,
    RunConflict,
    _digest,
    create_run,
)

_DONE = {"succeeded", "failed", "cancelled", "recovery_required"}
_PROFILES = ("confirm", "full")
_PAGE_LIMIT = 100

router = APIRouter()


def _strip_unstorable(text: str) -> str:
    # Postgres text/jsonb cannot store NUL or other C0 controls; a pasted log
    # line carrying them must not 500 the insert (audit: tasks submit 500).
    return "".join(c for c in text if c == "\n" or c == "\t" or c == "\r" or ord(c) >= 32)


class _TaskIn(BaseModel):
    message: str
    request_id: str
    permission_profile: str
    project_id: str | None = None
    model_ref: str | None = None

    _clean_message = field_validator("message")(_strip_unstorable)


class _RunIn(BaseModel):
    message: str
    request_id: str
    permission_profile: str
    model_ref: str | None = None

    _clean_message = field_validator("message")(_strip_unstorable)


def _check_run_input(message: str, request_id: str, permission_profile: str) -> None:
    if (
        not message.strip()
        or len(message) > 20000
        or not 8 <= len(request_id) <= 64
        or permission_profile not in _PROFILES
    ):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _session_row(db: Session, record, session_id: str) -> SessionRow:
    row = db.scalars(
        select(SessionRow).where(
            SessionRow.id == session_id,
            SessionRow.tenant_id == record.tenant_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return row


def _default_project(db: Session, record) -> str:
    user = db.get(User, record.user_id)
    if user is not None and user.default_project_id:
        return user.default_project_id
    project_id = _ensure_default_project(db, record.tenant_id)
    if user is not None:
        user.default_project_id = project_id
        db.flush()
    return project_id


def _submit(
    request: Request,
    db: Session,
    record,
    *,
    session_id: str,
    project_id: str,
    message: str,
    request_id: str,
    permission_profile: str,
    fresh_session: SessionRow | None = None,
    model_snapshot: dict | None = None,
    request_model_ref: str | None = None,
):
    """create_run + contract error mapping. fresh_session is deleted on error."""
    target_id = f"cloud:{record.tenant_id}:{project_id}"
    try:
        accepted = create_run(
            request.app.state.database_url,
            tenant_id=record.tenant_id,
            session_id=session_id,
            message=message,
            target_id=target_id,
            permission_profile=permission_profile,
            request_id=request_id,
            user_id=record.user_id,
            model_snapshot=model_snapshot,
            request_model_ref=request_model_ref,
        )
    except RunAlreadyActive:
        _discard(db, fresh_session)
        raise HTTPException(status_code=409, detail="RUN_ACTIVE") from None
    except RunConflict:
        _discard(db, fresh_session)
        raise HTTPException(status_code=409, detail="REQUEST_CONFLICT") from None
    except QuotaRefused as exc:
        _discard(db, fresh_session)
        return JSONResponse(
            status_code=429,
            content={
                "code": "QUOTA_EXCEEDED",
                "reason": exc.decision.body.get("kind", "task"),
            },
        )
    run = db.scalars(select(Run).where(Run.id == accepted.run_id)).one_or_none()
    if run is not None and run.session_id != session_id:
        # A concurrent create won the request_id race with a different session.
        _discard(db, fresh_session)
        session_id = run.session_id
    now = datetime.now(timezone.utc)
    db.execute(
        update(SessionRow).where(SessionRow.id == session_id).values(updated_at=now)
    )
    db.commit()
    return JSONResponse(
        status_code=202,
        content={
            "run_id": accepted.run_id,
            "status": run.status if run is not None else "pending",
            "session_id": session_id,
            "events_url": accepted.events_url,
        },
    )


def _discard(db: Session, session: SessionRow | None) -> None:
    if session is None:
        return
    row = db.get(SessionRow, session.id)
    if row is not None:
        db.delete(row)
        db.commit()


def _first_event(db: Session, run_ids: list[str]) -> dict[str, dict]:
    if not run_ids:
        return {}
    rows = db.scalars(
        select(RunEvent).where(
            RunEvent.run_id.in_(run_ids), RunEvent.seq == 1, RunEvent.type == "run.created"
        )
    ).all()
    return {row.run_id: (row.payload if isinstance(row.payload, dict) else {}) for row in rows}


def _final_previews(db: Session, tenant_id: str, run_ids: list[str]) -> dict[str, str]:
    if not run_ids:
        return {}
    rows = db.scalars(
        select(RunEvent)
        .where(RunEvent.tenant_id == tenant_id, RunEvent.run_id.in_(run_ids), RunEvent.type == "assistant.final")
        .order_by(RunEvent.seq)
    ).all()
    previews: dict[str, str] = {}
    for row in rows:
        if row.run_id in previews:
            continue
        payload = row.payload if isinstance(row.payload, dict) else {}
        previews[row.run_id] = str(payload.get("text") or "")[:200]
    return previews


def _encode_cursor(run: Run) -> str:
    stamp = _aware(run.created_at) or datetime.now(timezone.utc)
    raw = json.dumps([stamp.isoformat(), run.id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(raw: str) -> tuple[datetime, str] | None:
    try:
        stamp, run_id = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment, str(run_id)
    except (ValueError, TypeError, KeyError):
        return None


def _run_model_json(row: Run) -> dict | None:
    """The submission-time model echo — null for pre-BYOK legacy rows."""
    if not row.model_ref:
        return None
    return {
        "model_ref": row.model_ref,
        "model_id": row.model_id,
        "provider_id": row.provider_id,
        "provider_name": row.provider_name,
        "credential_source": row.credential_source,
    }


def _session_item(db: Session, row: SessionRow, last_run: dict[str, str] | None) -> dict:
    stamp = _aware(row.updated_at)
    return {
        "id": row.id,
        "title": row.title,
        "project_id": row.project_id,
        "updated_at": stamp.isoformat() if stamp is not None else None,
        "last_run": last_run,
    }


def _last_runs(db: Session, tenant_id: str, session_ids: list[str]) -> dict[str, dict[str, str]]:
    """Latest run per session — one ordered query, first hit per session wins."""
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


@router.post("/api/v1/tasks", status_code=202)
def create_task(
    payload: _TaskIn,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    _check_run_input(payload.message, payload.request_id, payload.permission_profile)
    if payload.project_id:
        project = db.scalars(
            select(Project).where(
                Project.id == payload.project_id,
                Project.tenant_id == record.tenant_id,
            )
        ).one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
        project_id = project.id
    else:
        project_id = _default_project(db, record)
        db.flush()
    existing = db.scalars(
        select(Run).where(
            Run.tenant_id == record.tenant_id, Run.request_id == payload.request_id
        )
    ).one_or_none()
    if existing is not None:
        digest = _digest(
            payload.message,
            f"cloud:{record.tenant_id}:{project_id}",
            payload.permission_profile,
            payload.request_id,
            existing.session_id,
            model_ref=payload.model_ref,
        )
        if existing.input_digest != digest:
            raise HTTPException(status_code=409, detail="REQUEST_CONFLICT")
        return JSONResponse(
            status_code=202,
            content={
                "run_id": existing.id,
                "status": existing.status,
                "session_id": existing.session_id,
                "events_url": f"/api/v1/runs/{existing.id}/events",
            },
        )
    # BYOK resolves BEFORE the session row exists — a refused submission
    # leaves neither a run nor an orphan session behind.
    model_snapshot = resolve_run_model(
        db,
        record,
        payload.model_ref,
        mode=getattr(request.app.state, "mode", None),
    )
    title = " ".join(payload.message.splitlines()).strip()[:40]
    session = SessionRow(
        id=uuid.uuid4().hex,
        tenant_id=record.tenant_id,
        project_id=project_id,
        title=title,
    )
    db.add(session)
    db.commit()
    return _submit(
        request,
        db,
        record,
        session_id=session.id,
        project_id=project_id,
        message=payload.message,
        request_id=payload.request_id,
        permission_profile=payload.permission_profile,
        fresh_session=session,
        model_snapshot=model_snapshot,
        request_model_ref=payload.model_ref,
    )


@router.post("/api/v1/sessions/{session_id}/runs", status_code=202)
def create_session_run(
    session_id: str,
    payload: _RunIn,
    request: Request,
    db: Session = Depends(db_session),
):
    require_write(request)
    record = current_record(request)
    _check_run_input(payload.message, payload.request_id, payload.permission_profile)
    session = _session_row(db, record, session_id)
    model_snapshot = resolve_run_model(
        db,
        record,
        payload.model_ref,
        mode=getattr(request.app.state, "mode", None),
    )
    return _submit(
        request,
        db,
        record,
        session_id=session.id,
        project_id=session.project_id,
        message=payload.message,
        request_id=payload.request_id,
        permission_profile=payload.permission_profile,
        model_snapshot=model_snapshot,
        request_model_ref=payload.model_ref,
    )


@router.get("/api/v1/sessions/{session_id}/runs")
def list_session_runs(
    session_id: str,
    request: Request,
    limit: int = 10,
    before: str = "",
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    _session_row(db, record, session_id)
    limit = max(1, min(int(limit or 10), _PAGE_LIMIT))
    query = (
        select(Run)
        .where(Run.session_id == session_id, Run.tenant_id == record.tenant_id)
        .order_by(Run.created_at.desc(), Run.id.desc())
    )
    cursor = _decode_cursor(before) if before else None
    if before and cursor is None:
        raise HTTPException(status_code=400, detail="INVALID_CURSOR")
    if cursor is not None:
        moment, run_id = cursor
        query = query.where(
            (Run.created_at < moment)
            | ((Run.created_at == moment) & (Run.id < run_id))
        )
    runs = db.scalars(query.limit(limit + 1)).all()
    next_cursor = ""
    if len(runs) > limit:
        runs = runs[:limit]
        next_cursor = _encode_cursor(runs[-1])
    run_ids = [row.id for row in runs]
    firsts = _first_event(db, run_ids)
    previews = _final_previews(db, record.tenant_id, run_ids)
    items = []
    for row in runs:
        created = firsts.get(row.id, {})
        stamp = _aware(row.created_at)
        items.append(
            {
                "run_id": row.id,
                "status": row.status,
                "created_at": stamp.isoformat() if stamp is not None else None,
                "message": str(created.get("message") or ""),
                "permission_profile": str(created.get("permission_profile") or ""),
                "final_preview": previews.get(row.id, ""),
                "model": _run_model_json(row),
            }
        )
    return {"runs": items, "next_cursor": next_cursor or None}


@router.get("/api/v1/sessions")
def list_tenant_sessions(
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    rows = db.scalars(
        select(SessionRow)
        .where(SessionRow.tenant_id == record.tenant_id)
        .order_by(SessionRow.updated_at.desc())
        .limit(50)
    ).all()
    latest = _last_runs(db, record.tenant_id, [row.id for row in rows])
    return {
        "sessions": [_session_item(db, row, latest.get(row.id)) for row in rows]
    }


@router.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, object]:
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != record.tenant_id:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            created = _first_event(db, [row.id]).get(row.id, {})
            stamp = _aware(row.created_at)
            return {
                "run_id": row.id,
                "status": row.status,
                "session_id": row.session_id,
                "event_seq": int(row.event_seq or 0),
                "created_at": stamp.isoformat() if stamp is not None else None,
                "message": str(created.get("message") or ""),
                "permission_profile": str(created.get("permission_profile") or ""),
                "model": _run_model_json(row),
            }
    finally:
        engine.dispose()


@router.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    database_url = request.app.state.database_url
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == record.tenant_id).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            if row.status in _DONE:
                raise HTTPException(status_code=409, detail="RUN_TERMINAL")
            # A queued run executes nothing — cancel it terminally right here
            # instead of waiting for a worker slot (one-click stop). The same
            # shortcut heals a queued cancel_requested that never got leased.
            direct_terminal = row.status == "pending" or (
                row.status == "cancel_requested" and not row.lease_owner
            )
            next_status = "cancelled" if direct_terminal else "cancel_requested"
            if row.status != next_status:
                row.status = next_status
                row.revision = int(row.revision or 0) + 1
                retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == row.id))
                seq = max(int(row.event_seq or 0), int(retained or 0)) + 1
                row.event_seq = seq
                event_id = uuid.uuid4().hex
                db.add(
                    RunEvent(
                        event_id=event_id,
                        run_id=row.id,
                        tenant_id=record.tenant_id,
                        seq=seq,
                        type="run.status",
                        payload={"status": next_status},
                        at=datetime.now(timezone.utc),
                    )
                )
                db.flush()
                db.add(
                    Outbox(
                        id=uuid.uuid4().hex,
                        event_id=event_id,
                        dispatch_status="pending",
                        attempts=0,
                    )
                )
            db.commit()
            if direct_terminal:
                from rxycode_server.notifications.service import notify_run_terminal
                from rxycode_server.runs.service import release_worker_for_run

                release_worker_for_run(database_url, run_id)
                notify_run_terminal(database_url, run_id, "cancelled")
    finally:
        engine.dispose()
    return {"status": next_status}


@router.post("/api/v1/runs/{run_id}/steer")
async def steer_run(run_id: str, request: Request) -> dict[str, object]:
    """Queue a steer on this run. The event log is the command, not EventStore."""
    require_write(request)
    body = await request.json()
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    record = current_record(request)
    database_url = request.app.state.database_url
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == record.tenant_id).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            if row.status in _DONE:
                raise HTTPException(status_code=409, detail="RUN_TERMINAL")
            retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == row.id))
            seq = max(int(row.event_seq or 0), int(retained or 0)) + 1
            row.event_seq = seq
            row.revision = int(row.revision or 0) + 1
            event_id = uuid.uuid4().hex
            db.add(
                RunEvent(
                    event_id=event_id,
                    run_id=row.id,
                    tenant_id=record.tenant_id,
                    seq=seq,
                    type="steer.accepted",
                    payload={"text": text, "seq": seq},
                    at=datetime.now(timezone.utc),
                )
            )
            db.flush()
            db.add(
                Outbox(
                    id=uuid.uuid4().hex,
                    event_id=event_id,
                    dispatch_status="pending",
                    attempts=0,
                )
            )
            db.commit()
    finally:
        engine.dispose()
    from rxycode_worker.agent_events import deliver_persisted_command

    delivered = await deliver_persisted_command(run_id, "steer.accepted", {"text": text})
    return {"run_id": run_id, "status": "accepted", "text": text, "delivered": bool(delivered.get("delivered") or delivered.get("accepted"))}


@router.post("/api/v1/runs/{run_id}/children/{session_id}/cancel")
async def cancel_child_run(run_id: str, session_id: str, request: Request) -> dict[str, object]:
    """Record a child cancel. The parent run status stays unchanged."""
    require_write(request)
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == record.tenant_id).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            if row.status in _DONE:
                raise HTTPException(status_code=409, detail="RUN_TERMINAL")
            retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == row.id))
            seq = max(int(row.event_seq or 0), int(retained or 0)) + 1
            row.event_seq = seq
            row.revision = int(row.revision or 0) + 1
            event_id = uuid.uuid4().hex
            db.add(
                RunEvent(
                    event_id=event_id,
                    run_id=row.id,
                    tenant_id=record.tenant_id,
                    seq=seq,
                    type="child.cancel",
                    payload={"session_id": session_id},
                    at=datetime.now(timezone.utc),
                )
            )
            db.flush()
            db.add(
                Outbox(
                    id=uuid.uuid4().hex,
                    event_id=event_id,
                    dispatch_status="pending",
                    attempts=0,
                )
            )
            db.commit()
    finally:
        engine.dispose()
    from rxycode_worker.agent_events import deliver_persisted_command

    delivered = await deliver_persisted_command(
        run_id,
        "child.cancel",
        {"session_id": session_id},
    )
    return {
        "run_id": run_id,
        "session_id": session_id,
        "status": "cancel_requested",
        "delivered": bool(delivered.get("delivered")),
    }
