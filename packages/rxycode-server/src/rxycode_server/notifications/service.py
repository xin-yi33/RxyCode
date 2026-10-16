"""Tenant-scoped memory, usage statement, schedule delivery, and terminal notices.

Schedule rules reuse ScheduleService. The durable run is written here, so one
appserver process is not the cloud worker. Notices are sent once per terminal run.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.persistence.models import Outbox, Run, RunEvent, SessionRow, UsageRecord
from rxycode_server.usage.service import usage_cost_kind

router = APIRouter()
_TERMINAL = {"succeeded", "failed", "cancelled"}
_NOTICE = "run.completed"


class ScheduleForbidden(Exception):
    """The project or session is not in this tenant."""

    def __init__(self) -> None:
        super().__init__("schedule forbidden")
        self.http_status = 403
        self.code = "FORBIDDEN"


def ensure_tables(database_url: str) -> None:
    """Create the product tables owned by this card."""
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS web_memories (
                    id varchar(64) PRIMARY KEY,
                    tenant_id varchar(64) NOT NULL,
                    project_id varchar(64) NOT NULL,
                    body text NOT NULL,
                    updated_at varchar(40) NOT NULL
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS web_schedules (
                    id varchar(64) PRIMARY KEY,
                    tenant_id varchar(64) NOT NULL,
                    project_id varchar(64) NOT NULL,
                    session_id varchar(64) NOT NULL,
                    user_id varchar(64) NOT NULL DEFAULT '',
                    rule text NOT NULL,
                    enabled boolean NOT NULL,
                    notify boolean NOT NULL,
                    next_fire varchar(40),
                    last_run_id varchar(64),
                    created_at varchar(40) NOT NULL
                )
                """
            ))
            conn.execute(text(
                "ALTER TABLE web_schedules ADD COLUMN IF NOT EXISTS user_id varchar(64)"
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS web_notifications (
                    id varchar(64) PRIMARY KEY,
                    tenant_id varchar(64) NOT NULL,
                    user_id varchar(64) NOT NULL,
                    kind varchar(64) NOT NULL,
                    run_id varchar(64) NOT NULL,
                    status varchar(32) NOT NULL,
                    body text NOT NULL
                )
                """
            ))
            conn.execute(text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_web_notifications_once
                ON web_notifications (tenant_id, user_id, run_id, kind)
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS web_unsubscribes (
                    tenant_id varchar(64) NOT NULL,
                    user_id varchar(64) NOT NULL,
                    kind varchar(64) NOT NULL,
                    PRIMARY KEY (tenant_id, user_id, kind)
                )
                """
            ))
    finally:
        engine.dispose()


def usage_statement(
    database_url: str,
    tenant_id: str,
    *,
    model_id: str | None = None,
    day: str | None = None,
) -> dict[str, object]:
    """Sum the ledger for this tenant. A day or model narrows the same rows."""
    ensure_tables(database_url)
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            records = db.scalars(
                select(UsageRecord)
                .join(Run, Run.id == UsageRecord.run_id)
                .where(Run.tenant_id == tenant_id)
            ).all()
            lines: list[dict[str, object]] = []
            for record in records:
                if model_id and record.model_id != model_id:
                    continue
                stamp = _usage_day(db, record)
                if day and stamp != day:
                    continue
                lines.append({
                    "run_id": record.run_id,
                    "model_id": record.model_id,
                    "tokens": int(record.tokens),
                    "amount": record.amount,
                    "cost_kind": usage_cost_kind(record.price_version),
                    "day": stamp,
                })
    finally:
        engine.dispose()
    tokens = sum(int(line["tokens"]) for line in lines)
    amount = sum((Decimal(str(line["amount"])) for line in lines), Decimal("0"))
    shown = format(amount.quantize(Decimal("0.00000001")), "f")
    return {"tokens": tokens, "amount": shown, "lines": lines}


def read_usage(request: Request) -> dict[str, object]:
    """Usage for the signed-in tenant. The query string only filters that ledger."""
    record = current_record(request)
    return usage_statement(
        request.app.state.database_url,
        record.tenant_id,
        model_id=request.query_params.get("model_id") or None,
        day=request.query_params.get("day") or None,
    )


def list_memory(project_id: str, request: Request) -> dict[str, object]:
    """Memory rows for this tenant and project. Other tenants are not readable."""
    record = current_record(request)
    ensure_tables(request.app.state.database_url)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, body, project_id
                    FROM web_memories
                    WHERE tenant_id = :tenant AND project_id = :project
                    ORDER BY updated_at
                    """
                ),
                {"tenant": record.tenant_id, "project": project_id},
            ).all()
    finally:
        engine.dispose()
    return {
        "memories": [
            {"id": row.id, "body": row.body, "project_id": row.project_id, "tenant_id": record.tenant_id}
            for row in rows
        ]
    }


async def put_memory(project_id: str, request: Request) -> dict[str, object]:
    """Store a note for the signed-in tenant. A foreign id is not overwritten."""
    require_write(request)
    record = current_record(request)
    payload = await request.json()
    body = str((payload or {}).get("body") or "")
    memory_id = str((payload or {}).get("id") or "")
    ensure_tables(request.app.state.database_url)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            if memory_id:
                owner = conn.execute(
                    text("SELECT tenant_id FROM web_memories WHERE id = :id"),
                    {"id": memory_id},
                ).first()
                if owner is not None and owner.tenant_id != record.tenant_id:
                    return {"id": memory_id, "body": "", "stored": False}
                if owner is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE web_memories
                            SET body = :body, project_id = :project, updated_at = :stamp
                            WHERE id = :id AND tenant_id = :tenant
                            """
                        ),
                        {
                            "body": body,
                            "project": project_id,
                            "stamp": _stamp(),
                            "id": memory_id,
                            "tenant": record.tenant_id,
                        },
                    )
                    return {"id": memory_id, "body": body, "stored": True}
            memory_id = uuid.uuid4().hex
            conn.execute(
                text(
                    """
                    INSERT INTO web_memories (id, tenant_id, project_id, body, updated_at)
                    VALUES (:id, :tenant, :project, :body, :stamp)
                    """
                ),
                {
                    "id": memory_id,
                    "tenant": record.tenant_id,
                    "project": project_id,
                    "body": body,
                    "stamp": _stamp(),
                },
            )
    finally:
        engine.dispose()
    return {"id": memory_id, "body": body, "stored": True}


def delete_memory(project_id: str, memory_id: str, request: Request) -> dict[str, object]:
    """Delete only a note owned by this tenant and project."""
    require_write(request)
    record = current_record(request)
    ensure_tables(request.app.state.database_url)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    DELETE FROM web_memories
                    WHERE id = :id AND tenant_id = :tenant AND project_id = :project
                    """
                ),
                {"id": memory_id, "tenant": record.tenant_id, "project": project_id},
            )
    finally:
        engine.dispose()
    return {"deleted": bool(result.rowcount)}


def list_notifications(request: Request) -> dict[str, object]:
    """Notices for the signed-in user. Another tenant's rows are not selected."""
    record = current_record(request)
    ensure_tables(request.app.state.database_url)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, run_id, status, body
                    FROM web_notifications
                    WHERE tenant_id = :tenant AND user_id = :user
                    ORDER BY id
                    """
                ),
                {"tenant": record.tenant_id, "user": record.user_id},
            ).all()
    finally:
        engine.dispose()
    return {
        "notifications": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "status": row.status,
                "body": row.body,
                "tenant_id": record.tenant_id,
            }
            for row in rows
        ]
    }


async def unsubscribe(request: Request) -> dict[str, object]:
    """Stop terminal notices for this user. The choice is stored, not implied."""
    require_write(request)
    record = current_record(request)
    payload = await request.json()
    kind = str((payload or {}).get("kind") or _NOTICE)
    ensure_tables(request.app.state.database_url)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO web_unsubscribes (tenant_id, user_id, kind)
                    VALUES (:tenant, :user, :kind)
                    ON CONFLICT (tenant_id, user_id, kind) DO NOTHING
                    """
                ),
                {"tenant": record.tenant_id, "user": record.user_id, "kind": kind},
            )
    finally:
        engine.dispose()
    return {"unsubscribed": True, "kind": kind}


def create_web_schedule(
    database_url: str,
    *,
    tenant_id: str,
    project_id: str,
    session_id: str,
    rule: dict[str, object],
    now: datetime | None = None,
    notify: bool = True,
    enabled: bool = True,
    user_id: str = "",
) -> dict[str, object]:
    """Validate the rule with ScheduleService, then store the job in the web database."""
    from appserver.schedule_service import ScheduleService

    ensure_tables(database_url)
    if not _session_owned(database_url, tenant_id, project_id, session_id):
        raise ScheduleForbidden()
    stamp = _naive(now or datetime.now(timezone.utc))
    job = ScheduleService(persistent=False).create(
        rule=rule,
        action={"kind": "session", "session_id": session_id},
        enabled=enabled,
        now=stamp,
    )
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO web_schedules (
                        id, tenant_id, project_id, session_id, user_id, rule,
                        enabled, notify, next_fire, last_run_id, created_at
                    )
                    VALUES (
                        :id, :tenant, :project, :session, :user_id, :rule,
                        :enabled, :notify, :next_fire, NULL, :created
                    )
                    """
                ),
                {
                    "id": job["id"],
                    "tenant": tenant_id,
                    "project": project_id,
                    "session": session_id,
                    "user_id": user_id,
                    "rule": json.dumps(job["rule"]),
                    "enabled": bool(enabled),
                    "notify": bool(notify),
                    "next_fire": job["next_fire"],
                    "created": _stamp(),
                },
            )
    finally:
        engine.dispose()
    return {
        "id": job["id"],
        "next_fire": job["next_fire"],
        "enabled": True,
        "notify": bool(notify),
    }


def fire_due_schedules(database_url: str, *, now: datetime) -> list[dict[str, str]]:
    """Create a durable Run for each due job. No browser and no appserver session."""
    from scheduler.rules import next_fire

    ensure_tables(database_url)
    stamp = _naive(now)
    engine = create_engine(database_url, poolclass=NullPool)
    created: list[dict[str, str]] = []
    try:
        with Session(engine) as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, tenant_id, session_id, rule, next_fire
                    FROM web_schedules
                    WHERE enabled = true
                    """
                )
            ).all()
            due_rows = []
            for row in rows:
                due_at = _naive_text(row.next_fire)
                if due_at is not None and due_at <= stamp:
                    due_rows.append(row)
        for row in due_rows:
            try:
                created.append(_fire_one(engine, row, stamp, next_fire))
            except Exception:
                continue
    finally:
        engine.dispose()
    return created


def _fire_one(engine: object, row: object, stamp: datetime, compute_next: object) -> dict[str, str]:
    """Insert one run plus its queue event. A failure stays inside this job."""
    run_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    event_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(
            Run(
                id=run_id,
                tenant_id=row.tenant_id,
                session_id=row.session_id,
                status="pending",
                revision=0,
                lease_epoch=0,
                request_id=request_id,
                input_digest="",
                event_seq=1,
                target_id="",
            )
        )
        db.flush()
        db.add(
            RunEvent(
                event_id=event_id,
                run_id=run_id,
                tenant_id=row.tenant_id,
                seq=1,
                type="run.created",
                payload={
                    "message": "scheduled run",
                    "permission_profile": "default",
                    "request_id": request_id,
                    "session_id": row.session_id,
                    "target_id": "",
                    "schedule_id": row.id,
                },
                at=datetime.now(timezone.utc),
            )
        )
        db.flush()
        db.add(Outbox(id=uuid.uuid4().hex, event_id=event_id, dispatch_status="pending", attempts=0))
        rule = json.loads(row.rule)
        db.execute(
            text(
                """
                UPDATE web_schedules
                SET next_fire = :next_fire, last_run_id = :run_id
                WHERE id = :id
                """
            ),
            {"next_fire": compute_next(rule, stamp).isoformat(), "run_id": run_id, "id": row.id},
        )
        db.commit()
    return {"run_id": run_id, "schedule_id": str(row.id)}


def _session_owned(database_url: str, tenant_id: str, project_id: str, session_id: str) -> bool:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.scalar(
                select(SessionRow).where(
                    SessionRow.id == session_id,
                    SessionRow.tenant_id == tenant_id,
                    SessionRow.project_id == project_id,
                )
            )
    finally:
        engine.dispose()
    return row is not None


def notify_run_terminal(database_url: str, run_id: str, status: str) -> dict[str, object]:
    """Notify the user who owned the schedule for this run."""
    ensure_tables(database_url)
    engine = create_engine(database_url, poolclass=NullPool)
    tenant_id = ""
    user_id = ""
    try:
        with Session(engine) as db:
            run = db.get(Run, run_id)
            if run is None:
                return {"notification_id": None, "status": status}
            tenant_id = run.tenant_id
            job = db.execute(
                text(
                    """
                    SELECT user_id FROM web_schedules
                    WHERE tenant_id = :tenant AND last_run_id = :run_id
                    """
                ),
                {"tenant": tenant_id, "run_id": run_id},
            ).first()
            if job is not None and job.user_id:
                user_id = str(job.user_id)
    finally:
        engine.dispose()
    if not user_id:
        return {"notification_id": None, "status": status}
    return publish_run_status(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        status=status,
        user_id=user_id,
    )


def publish_run_status(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    status: str,
    user_id: str,
) -> dict[str, object]:
    """Record a terminal status once. A repeat or an unsubscribed user adds nothing."""
    ensure_tables(database_url)
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
            ).scalar_one_or_none()
            if run is None or status not in _TERMINAL:
                return {"notification_id": None, "status": status}
            if run.status in _TERMINAL and run.status != status:
                return {"notification_id": None, "status": run.status}
            run.status = status
            if _silenced(db, tenant_id, user_id, run_id):
                db.commit()
                return {"notification_id": None, "status": status}
            found = db.execute(
                text(
                    """
                    SELECT id FROM web_notifications
                    WHERE tenant_id = :tenant AND user_id = :user
                      AND run_id = :run_id AND kind = :kind
                    """
                ),
                {"tenant": tenant_id, "user": user_id, "run_id": run_id, "kind": _NOTICE},
            ).first()
            if found is not None:
                db.commit()
                return {"notification_id": str(found.id), "status": status}
            note_id = uuid.uuid4().hex
            db.execute(
                text(
                    """
                    INSERT INTO web_notifications
                        (id, tenant_id, user_id, kind, run_id, status, body)
                    VALUES
                        (:id, :tenant, :user, :kind, :run_id, :status, :body)
                    """
                ),
                {
                    "id": note_id,
                    "tenant": tenant_id,
                    "user": user_id,
                    "kind": _NOTICE,
                    "run_id": run_id,
                    "status": status,
                    "body": status + " " + run_id,
                },
            )
            db.commit()
            return {"notification_id": note_id, "status": status}
    finally:
        engine.dispose()


def _silenced(db: Session, tenant_id: str, user_id: str, run_id: str) -> bool:
    unsubscribed = db.execute(
        text(
            """
            SELECT 1 FROM web_unsubscribes
            WHERE tenant_id = :tenant AND user_id = :user AND kind = :kind
            """
        ),
        {"tenant": tenant_id, "user": user_id, "kind": _NOTICE},
    ).first()
    if unsubscribed is not None:
        return True
    job = db.execute(
        text(
            """
            SELECT notify FROM web_schedules
            WHERE tenant_id = :tenant AND last_run_id = :run_id
            """
        ),
        {"tenant": tenant_id, "run_id": run_id},
    ).first()
    return job is not None and not bool(job.notify)


def _usage_day(db: Session, record: UsageRecord) -> str:
    events = db.scalars(
        select(RunEvent).where(
            RunEvent.run_id == record.run_id,
            RunEvent.type == "usage.updated",
        )
    ).all()
    for event in events:
        payload = event.payload or {}
        if payload.get("model_id") == record.model_id and payload.get("price_version") == record.price_version:
            return _day(event.at)
    return ""


def _day(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date().isoformat()


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _naive_text(value: str | None) -> datetime | None:
    if not value:
        return None
    stamp = datetime.fromisoformat(value)
    return _naive(stamp)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


router.add_api_route("/api/v1/usage", read_usage, methods=["GET"])
router.add_api_route("/api/v1/projects/{project_id}/memory", list_memory, methods=["GET"])
router.add_api_route("/api/v1/projects/{project_id}/memory", put_memory, methods=["POST"])
router.add_api_route(
    "/api/v1/projects/{project_id}/memory/{memory_id}",
    delete_memory,
    methods=["DELETE"],
)
router.add_api_route("/api/v1/notifications", list_notifications, methods=["GET"])
router.add_api_route("/api/v1/notifications/unsubscribe", unsubscribe, methods=["POST"])


async def create_schedule(request: Request) -> dict[str, object]:
    """Create a durable schedule for the signed-in tenant."""
    require_write(request)
    record = current_record(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    rule = payload.get("rule")
    if not isinstance(rule, dict):
        rule = {"kind": "interval", "every": 1, "unit": "minutes"}
    return create_web_schedule(
        request.app.state.database_url,
        tenant_id=record.tenant_id,
        project_id=str(payload.get("project_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        rule=rule,
        notify=bool(payload.get("notify", True)),
        enabled=bool(payload.get("enabled", True)),
        user_id=record.user_id,
    )


router.add_api_route("/api/v1/schedules", create_schedule, methods=["POST"])
