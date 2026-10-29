"""Schedule API — list/detail/executions/patch/delete/run-now on top of the
existing durable schedule store. One rule engine (`scheduler.rules`), one
firing ledger (`schedule_executions`), the same tenant scoping as everything
else. A schedule belongs to its owner user inside the tenant."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.persistence.models import (
    Project,
    Run,
    SessionRow,
)

router = APIRouter()
_PAGE_LIMIT = 100
_PROFILES = {"confirm", "full"}


def _iso(value) -> str | None:
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value is not None else None


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _row(db: Session, schedule_id: str, record, *, lock: bool = False):
    query = (
        select(text("*"))
        .select_from(text("web_schedules"))
        .where(text("id = :id AND tenant_id = :tenant"))
    )
    bound = query.params(id=schedule_id, tenant=record.tenant_id)
    if lock:
        bound = bound.with_for_update()
    row = db.execute(bound).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="SCHEDULE_NOT_FOUND")
    return dict(row)


def _item(db: Session, record, row: dict) -> dict[str, object]:
    last_execution = None
    exec_row = (
        db.execute(
            select(text("id, scheduled_for, status, reason, run_id"))
            .select_from(text("schedule_executions"))
            .where(text("schedule_id = :id"))
            .params(id=row["id"])
            .order_by(text("scheduled_for DESC"))
            .limit(1)
        )
        .mappings()
        .first()
    )
    if exec_row is not None:
        last_execution = {
            "id": exec_row["id"],
            "scheduled_for": _iso(exec_row["scheduled_for"]),
            "status": exec_row["status"],
            "reason": exec_row["reason"],
            "run_id": exec_row["run_id"],
        }
    next_occurrences: list[str] = []
    if row.get("enabled") and row.get("next_fire"):
        try:
            from scheduler.rules import preview

            start = _naive(datetime.now(timezone.utc))
            for stamp in preview(
                json.loads(row["rule"] or "{}"), start, row.get("timezone") or "UTC", count=3
            ):
                next_occurrences.append(stamp.isoformat())
        except Exception:
            next_occurrences = []
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "project_id": row["project_id"],
        "session_id": row["session_id"],
        "message": row.get("message") or "",
        "rule": json.loads(row["rule"] or "{}"),
        "timezone": row.get("timezone") or "UTC",
        "model_ref": row.get("model_ref"),
        "permission_profile": row.get("permission_profile") or "confirm",
        "enabled": bool(row["enabled"]),
        "notify": bool(row["notify"]),
        "next_fire": row.get("next_fire"),
        "next_occurrences": next_occurrences,
        "last_execution": last_execution,
        "revision": int(row.get("revision") or 0),
        "blocked_reason": row.get("blocked_reason") or "",
        "created_at": row.get("created_at"),
    }


def _cursor(raw: str) -> str | None:
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        return str(data[0])
    except (ValueError, TypeError, IndexError, KeyError):
        return None


@router.get("/api/v1/schedules")
def list_schedules(
    request: Request,
    filter: str = "all",
    project_id: str | None = None,
    cursor: str = "",
    limit: int = 30,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    if filter not in ("all", "enabled", "paused"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    limit = max(1, min(int(limit or 30), _PAGE_LIMIT))
    clauses = ["tenant_id = :tenant", "user_id = :uid"]
    params: dict[str, object] = {"tenant": record.tenant_id, "uid": record.user_id}
    if filter == "enabled":
        clauses.append("enabled = true")
    elif filter == "paused":
        clauses.append("enabled = false")
    if project_id:
        clauses.append("project_id = :project")
        params["project"] = project_id
    mark = _cursor(cursor) if cursor else None
    if cursor and mark is None:
        raise HTTPException(status_code=400, detail="INVALID_CURSOR")
    if mark:
        clauses.append("id > :mark")
        params["mark"] = mark
    sql = "SELECT * FROM web_schedules WHERE " + " AND ".join(clauses) + " ORDER BY id LIMIT :limit"
    params["limit"] = limit + 1
    rows = db.execute(text(sql), params).mappings().all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(json.dumps([rows[-1]["id"]]).encode()).decode()
    return {
        "schedules": [_item(db, record, dict(row)) for row in rows],
        "next_cursor": next_cursor,
    }


@router.get("/api/v1/schedules/{schedule_id}")
def get_schedule(
    schedule_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    return {"schedule": _item(db, record, _row(db, schedule_id, record))}


@router.get("/api/v1/schedules/{schedule_id}/executions")
def list_executions(
    schedule_id: str,
    request: Request,
    cursor: str = "",
    limit: int = 30,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    _row(db, schedule_id, record)
    limit = max(1, min(int(limit or 30), _PAGE_LIMIT))
    params: dict[str, object] = {"id": schedule_id, "limit": limit + 1}
    clauses = "schedule_id = :id"
    mark = _cursor(cursor) if cursor else None
    if cursor and mark is None:
        raise HTTPException(status_code=400, detail="INVALID_CURSOR")
    if mark:
        clauses += " AND id < :mark"
        params["mark"] = mark
    rows = (
        db.execute(
            text(
                "SELECT * FROM schedule_executions WHERE "
                + clauses
                + " ORDER BY scheduled_for DESC, id DESC LIMIT :limit"
            ),
            params,
        )
        .mappings()
        .all()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(json.dumps([rows[-1]["id"]]).encode()).decode()
    # SCH-13：按 run_id 关联通知与邮件投递行，详情抽屉可展示投递状态
    # 并对 failed 提供“重试邮件”（只重发该结果邮件，不重跑 Agent）。
    run_ids = [str(r["run_id"]) for r in rows if r.get("run_id")]
    notes: dict[str, str] = {}
    delivery: dict[str, dict] = {}
    run_status: dict[str, str] = {}
    if run_ids:
        run_status = {
            str(r.id): str(r.status)
            for r in db.scalars(select(Run).where(Run.id.in_(run_ids))).all()
        }
        for note in db.execute(
            text(
                "SELECT id, run_id FROM web_notifications"
                " WHERE run_id = ANY(:ids) AND tenant_id = :t"
            ),
            {"ids": run_ids, "t": record.tenant_id},
        ).mappings():
            notes[str(note["run_id"])] = str(note["id"])
        for row in db.execute(
            text(
                "SELECT DISTINCT ON (run_id) run_id, id, status FROM email_deliveries"
                " WHERE run_id = ANY(:ids) AND tenant_id = :t"
                " ORDER BY run_id, created_at DESC"
            ),
            {"ids": run_ids, "t": record.tenant_id},
        ).mappings():
            delivery[str(row["run_id"])] = {
                "id": str(row["id"]),
                "status": str(row["status"]),
            }
    return {
        "executions": [
            {
                "id": row["id"],
                "schedule_id": row["schedule_id"],
                "scheduled_for": _iso(row["scheduled_for"]),
                "schedule_revision": int(row["schedule_revision"] or 0),
                "run_id": row["run_id"],
                "status": row["status"],
                "reason": row["reason"] or "",
                "notification_status": row.get("notification_status") or "none",
                "notification_id": notes.get(str(row["run_id"])),
                "email": delivery.get(str(row["run_id"])),
                "run_status": run_status.get(str(row["run_id"])),
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


def _validate_session(db: Session, record, project_id: str, session_id: str) -> None:
    session = db.scalars(
        select(SessionRow).where(
            SessionRow.id == session_id,
            SessionRow.tenant_id == record.tenant_id,
            SessionRow.project_id == project_id,
        )
    ).one_or_none()
    if session is None or session.deleted_at is not None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    if session.archived_at is not None:
        raise HTTPException(status_code=409, detail="SESSION_ARCHIVED")


def _check_project(db: Session, record, project_id: str) -> None:
    if (
        db.scalars(
            select(Project).where(Project.id == project_id, Project.tenant_id == record.tenant_id)
        ).first()
        is None
    ):
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")


def _validate_rule(rule: object, tz_name: str) -> dict:
    from scheduler.rules import ScheduleRuleError, next_fire, parse_rule, parse_timezone

    if not isinstance(rule, dict):
        raise HTTPException(status_code=422, detail="INVALID_SCHEDULE")
    try:
        parsed = parse_rule(rule)
        parse_timezone(tz_name)
        if parsed.get("once"):
            due = next_fire(parsed, _naive(datetime.now(timezone.utc)), tz_name)
            if due <= _naive(datetime.now(timezone.utc)):
                raise HTTPException(status_code=422, detail="INVALID_SCHEDULE")
    except ScheduleRuleError as exc:
        raise HTTPException(status_code=422, detail="INVALID_SCHEDULE") from exc
    return parsed


class _ScheduleIn(BaseModel):
    project_id: str
    session_id: str
    rule: dict
    name: str = ""
    message: str = ""
    timezone: str = "UTC"
    model_ref: str | None = None
    permission_profile: str = "confirm"
    notify: bool = True
    enabled: bool = True
    request_id: str | None = None


class _SchedulePatch(BaseModel):
    name: str | None = None
    message: str | None = None
    rule: dict | None = None
    timezone: str | None = None
    model_ref: str | None = None
    permission_profile: str | None = None
    notify: bool | None = None
    enabled: bool | None = None
    expected_revision: int | None = None


class _RunNowIn(BaseModel):
    request_id: str | None = None
    expected_revision: int | None = None
    allow_billable: bool = False


def _valid_profile(value: str) -> str:
    if value not in _PROFILES:
        raise HTTPException(status_code=422, detail="INVALID_INPUT")
    return value


def _create_row(db: Session, record, payload: _ScheduleIn) -> dict:
    from scheduler.rules import next_fire

    _check_project(db, record, payload.project_id)
    _validate_session(db, record, payload.project_id, payload.session_id)
    parsed = _validate_rule(payload.rule, payload.timezone)
    profile = _valid_profile(payload.permission_profile)
    message = payload.message.strip()
    if not 1 <= len(message) <= 20000:
        raise HTTPException(status_code=422, detail="INVALID_SCHEDULE")
    name = payload.name.strip()[:100]
    if payload.request_id:
        existing = db.execute(
            text(
                "SELECT id FROM web_schedules WHERE tenant_id = :t AND user_id = :u"
                " AND request_id = :r"
            ),
            {"t": record.tenant_id, "u": record.user_id, "r": payload.request_id},
        ).first()
        if existing is not None:
            row = _row(db, existing.id, record)
            return {"schedule": _item(db, record, row), "created": False}
    job_id = uuid.uuid4().hex
    fire = next_fire(parsed, _naive(datetime.now(timezone.utc)), payload.timezone)
    db.execute(
        text(
            """
            INSERT INTO web_schedules (
                id, tenant_id, project_id, session_id, user_id, rule, enabled,
                notify, next_fire, last_run_id, created_at, name, message,
                timezone, model_ref, permission_profile, request_id, revision,
                blocked_reason
            ) VALUES (
                :id, :tenant, :project, :session, :uid, :rule, :enabled,
                :notify, :next_fire, NULL, :created, :name, :message,
                :tz, :model_ref, :profile, :request_id, 0, ''
            )
            """
        ),
        {
            "id": job_id,
            "tenant": record.tenant_id,
            "project": payload.project_id,
            "session": payload.session_id,
            "uid": record.user_id,
            "rule": json.dumps(parsed),
            "enabled": bool(payload.enabled),
            "notify": bool(payload.notify),
            "next_fire": fire.isoformat(),
            "created": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "message": message,
            "tz": payload.timezone,
            "model_ref": payload.model_ref,
            "profile": profile,
            "request_id": payload.request_id,
        },
    )
    db.flush()
    return {"schedule": _item(db, record, _row(db, job_id, record)), "created": True}


@router.post("/api/v1/schedules", status_code=201)
def create_schedule(
    payload: _ScheduleIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    result = _create_row(db, record, payload)
    return {"schedule": result["schedule"]}


@router.patch("/api/v1/schedules/{schedule_id}")
def patch_schedule(
    schedule_id: str,
    payload: _SchedulePatch,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    row = _row(db, schedule_id, record, lock=True)
    if row.get("user_id") and row["user_id"] != record.user_id:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    revision = int(row.get("revision") or 0)
    if payload.expected_revision is not None and revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="REVISION_CONFLICT")

    tz_name = payload.timezone or row.get("timezone") or "UTC"
    rule = parsed = None
    if payload.rule is not None or payload.timezone is not None:
        rule = payload.rule if payload.rule is not None else json.loads(row["rule"] or "{}")
        parsed = _validate_rule(rule, tz_name)
    profile = (
        _valid_profile(payload.permission_profile)
        if payload.permission_profile is not None
        else None
    )
    message = None
    if payload.message is not None:
        message = payload.message.strip()
        if not 1 <= len(message) <= 20000:
            raise HTTPException(status_code=422, detail="INVALID_SCHEDULE")

    fields: dict[str, object] = {"revision": revision + 1}
    if payload.name is not None:
        fields["name"] = payload.name.strip()[:100]
    if message is not None:
        fields["message"] = message
    if parsed is not None:
        from scheduler.rules import next_fire

        fields["rule"] = json.dumps(parsed)
        fields["timezone"] = tz_name
        fields["next_fire"] = next_fire(
            parsed, _naive(datetime.now(timezone.utc)), tz_name
        ).isoformat()
    if profile is not None:
        fields["permission_profile"] = profile
    if payload.model_ref is not None:
        fields["model_ref"] = payload.model_ref
    if payload.notify is not None:
        fields["notify"] = bool(payload.notify)
    if payload.enabled is not None:
        fields["enabled"] = bool(payload.enabled)
        if payload.enabled:
            fields["blocked_reason"] = ""
            if "next_fire" not in fields:
                from scheduler.rules import next_fire

                fields["next_fire"] = next_fire(
                    json.loads(str(fields.get("rule") or row["rule"] or "{}")),
                    _naive(datetime.now(timezone.utc)),
                    tz_name,
                ).isoformat()

    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "id": schedule_id, "tenant": record.tenant_id}
    db.execute(
        text(f"UPDATE web_schedules SET {assignments} WHERE id = :id AND tenant_id = :tenant"),
        params,
    )
    db.flush()
    return {"schedule": _item(db, record, _row(db, schedule_id, record))}


@router.delete("/api/v1/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    """Deletes only future firings — history runs stay put."""
    require_write(request)
    record = current_record(request)
    row = _row(db, schedule_id, record, lock=True)
    if row.get("user_id") and row["user_id"] != record.user_id:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    db.execute(
        text("DELETE FROM web_schedules WHERE id = :id AND tenant_id = :tenant"),
        {"id": schedule_id, "tenant": record.tenant_id},
    )
    db.flush()
    return None


@router.post("/api/v1/schedules/{schedule_id}/run-now", status_code=202)
def run_now(
    schedule_id: str,
    payload: _RunNowIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if not payload.allow_billable:
        raise HTTPException(status_code=422, detail="ALLOW_BILLABLE_REQUIRED")
    row = _row(db, schedule_id, record, lock=True)
    if row.get("user_id") and row["user_id"] != record.user_id:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    revision = int(row.get("revision") or 0)
    if payload.expected_revision is not None and revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="REVISION_CONFLICT")
    _validate_session(db, record, row["project_id"], row["session_id"])
    # Ledger row = idempotency of "manual fire at now" per request_id.
    if payload.request_id:
        dup = db.execute(
            text(
                "SELECT run_id FROM schedule_executions WHERE schedule_id = :id"
                " AND reason = :reason AND run_id IS NOT NULL LIMIT 1"
            ),
            {"id": schedule_id, "reason": f"manual:{payload.request_id}"},
        ).first()
        if dup is not None:
            run = db.scalars(select(Run).where(Run.id == dup.run_id)).one_or_none()
            if run is not None:
                return {"run_id": run.id, "status": run.status, "session_id": run.session_id}
    from rxycode_server.notifications.service import _fire_manual
    from rxycode_server.platform_quota.service import PlatformQuotaRefused
    from rxycode_server.quotas.service import QuotaRefused

    try:
        fired = _fire_manual(db, row, reason=f"manual:{payload.request_id or uuid.uuid4().hex}")
    except PlatformQuotaRefused as exc:
        # Roll back the 'queued' ledger row _fire_manual already flushed —
        # a refused fire must not journal a run that never existed.
        db.rollback()
        if exc.code == "PLATFORM_NOT_ALLOWED":
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND") from None
        return JSONResponse(
            status_code=429,
            content={
                "code": "QUOTA_EXCEEDED",
                "reason": (
                    "platform_quota"
                    if exc.code == "PLATFORM_QUOTA_EXHAUSTED"
                    else "concurrency"
                ),
            },
        )
    except QuotaRefused as exc:
        db.rollback()
        return JSONResponse(
            status_code=429,
            content={
                "code": "QUOTA_EXCEEDED",
                "reason": exc.decision.body.get("kind", "task"),
            },
        )
    return {
        "run_id": fired["run_id"],
        "status": "pending",
        "session_id": row["session_id"],
        "events_url": f"/api/v1/runs/{fired['run_id']}/events",
    }
