"""Tenant-scoped memory, usage statement, schedule delivery, and terminal notices.

Schedule rules reuse ScheduleService. The durable run is written here, so one
appserver process is not the cloud worker. Notices are sent once per terminal run.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.persistence.models import Run, RunEvent, SessionRow, UsageRecord
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
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS web_memories (
                    id varchar(64) PRIMARY KEY,
                    tenant_id varchar(64) NOT NULL,
                    project_id varchar(64) NOT NULL,
                    body text NOT NULL,
                    updated_at varchar(40) NOT NULL
                )
                """
                )
            )
            conn.execute(
                text(
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
                )
            )
            conn.execute(
                text("ALTER TABLE web_schedules ADD COLUMN IF NOT EXISTS user_id varchar(64)")
            )
            conn.execute(
                text(
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
                )
            )
            conn.execute(
                text(
                    """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_web_notifications_once
                ON web_notifications (tenant_id, user_id, run_id, kind)
                """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS web_unsubscribes (
                    tenant_id varchar(64) NOT NULL,
                    user_id varchar(64) NOT NULL,
                    kind varchar(64) NOT NULL,
                    PRIMARY KEY (tenant_id, user_id, kind)
                )
                """
                )
            )
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
                lines.append(
                    {
                        "run_id": record.run_id,
                        "model_id": record.model_id,
                        "tokens": int(record.tokens),
                        "amount": record.amount,
                        "cost_kind": usage_cost_kind(record.price_version),
                        "day": stamp,
                    }
                )
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
            {
                "id": row.id,
                "body": row.body,
                "project_id": row.project_id,
                "tenant_id": record.tenant_id,
            }
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
    name: str = "",
    message: str = "",
    timezone_name: str = "UTC",
    model_ref: str | None = None,
    permission_profile: str = "confirm",
    request_id: str | None = None,
) -> dict[str, object]:
    """Validate the rule with ScheduleService, then store the job in the web database."""
    from appserver.schedule_service import ScheduleService

    ensure_tables(database_url)
    if not _session_owned(database_url, tenant_id, project_id, session_id):
        raise ScheduleForbidden()
    stamp = _naive(now or datetime.now(timezone.utc))
    from scheduler.rules import next_fire as _next_fire, parse_rule

    parsed = parse_rule(rule)
    job = ScheduleService(persistent=False).create(
        rule=parsed,
        action={"kind": "session", "session_id": session_id},
        enabled=enabled,
        now=stamp,
    )
    fire = job["next_fire"]
    try:
        fire = _next_fire(parsed, stamp, timezone_name).isoformat()
    except Exception:
        pass
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO web_schedules (
                        id, tenant_id, project_id, session_id, user_id, rule,
                        enabled, notify, next_fire, last_run_id, created_at,
                        name, message, timezone, model_ref, permission_profile,
                        request_id, revision, blocked_reason
                    )
                    VALUES (
                        :id, :tenant, :project, :session, :user_id, :rule,
                        :enabled, :notify, :next_fire, NULL, :created,
                        :name, :message, :tz, :model_ref, :profile,
                        :request_id, 0, ''
                    )
                    """
                ),
                {
                    "id": job["id"],
                    "tenant": tenant_id,
                    "project": project_id,
                    "session": session_id,
                    "user_id": user_id,
                    "rule": json.dumps(parsed),
                    "enabled": bool(enabled),
                    "notify": bool(notify),
                    "next_fire": fire,
                    "created": _stamp(),
                    "name": name,
                    "message": message,
                    "tz": timezone_name,
                    "model_ref": model_ref,
                    "profile": permission_profile,
                    "request_id": request_id,
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


_LIVE_RUN = (
    "pending",
    "running",
    "leased",
    "cancel_requested",
    "waiting_approval",
)


def fire_due_schedules(database_url: str, *, now: datetime) -> list[dict[str, str]]:
    """Create a durable Run for each due job. No browser and no appserver session.

    ``schedule_executions`` (schedule_id, scheduled_for) is the idempotency
    key: two tickers or a restarted one can never double-fire one slot.
    """
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
                    SELECT id, tenant_id, user_id, project_id, session_id, rule,
                           next_fire, message, permission_profile, model_ref, timezone
                    FROM web_schedules
                    WHERE enabled = true
                    """
                )
            ).all()
            due_rows = [
                row
                for row in rows
                if (due_at := _naive_text(row.next_fire)) is not None and due_at <= stamp
            ]
        for row in due_rows:
            try:
                created.append(_fire_one(engine, row, stamp, next_fire))
            except Exception:
                continue
        # Housekeeping in the same tick: physically purge tombstoned
        # sessions older than a day.
        try:
            from rxycode_server.api.sessions import purge_deleted_sessions

            with Session(engine) as db:
                purge_deleted_sessions(db, older_than=stamp - timedelta(days=1))
                db.commit()
        except Exception:
            pass
    finally:
        engine.dispose()
    return created


def _session_state(db: Session, tenant_id: str, session_id: str) -> str:
    """'ok' | 'archived' | 'deleted' | 'missing' — the fire-time lifecycle."""
    row = db.scalars(
        select(SessionRow).where(SessionRow.id == session_id, SessionRow.tenant_id == tenant_id)
    ).one_or_none()
    if row is None or row.deleted_at is not None:
        return "missing" if row is None else "deleted"
    if row.archived_at is not None:
        return "archived"
    return "ok"


def _session_busy(db: Session, tenant_id: str, session_id: str) -> bool:
    return (
        db.scalar(
            select(func.count(Run.id)).where(
                Run.session_id == session_id,
                Run.tenant_id == tenant_id,
                Run.status.in_(_LIVE_RUN),
            )
        )
        or 0
    ) > 0


def _record_execution(
    db: Session,
    *,
    row,
    scheduled_for: datetime,
    status: str,
    reason: str = "",
    run_id: str | None = None,
) -> bool:
    """Insert the firing ledger row. False = this slot already fired."""
    from sqlalchemy.exc import IntegrityError

    db.execute(
        text(
            """
            INSERT INTO schedule_executions (
                id, tenant_id, schedule_id, scheduled_for, schedule_revision,
                run_id, status, reason, notification_status, created_at
            ) VALUES (
                :id, :tenant, :schedule, :for, :rev, :run, :status, :reason,
                'none', :created
            )
            """
        ),
        {
            "id": uuid.uuid4().hex,
            "tenant": row.tenant_id,
            "schedule": row.id,
            "for": scheduled_for,
            "rev": int(getattr(row, "revision", 0) or 0),
            "run": run_id,
            "status": status,
            "reason": reason,
            "created": _naive(datetime.now(timezone.utc)),
        },
    )
    try:
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _advance(engine, row, stamp: datetime, compute_next) -> None:
    with Session(engine) as db:
        db.execute(
            text("UPDATE web_schedules SET next_fire = :next_fire WHERE id = :id"),
            {
                "next_fire": compute_next(
                    json.loads(row.rule), stamp, getattr(row, "timezone", "UTC") or "UTC"
                ).isoformat(),
                "id": row.id,
            },
        )
        db.commit()


def _fire_one(engine: object, row: object, stamp: datetime, compute_next) -> dict[str, str]:
    """One slot → one ledger row → at most one run. Refusals are recorded."""
    with Session(engine) as db:
        scheduled_for = _naive_text(row.next_fire) or stamp
        state = _session_state(db, row.tenant_id, row.session_id)
        if state != "ok":
            if _record_execution(
                db,
                row=row,
                scheduled_for=scheduled_for,
                status="missed",
                reason=f"session_{state}",
            ):
                db.execute(
                    text(
                        "UPDATE web_schedules SET enabled = false, blocked_reason = :b"
                        " WHERE id = :id"
                    ),
                    {"b": state, "id": row.id},
                )
                db.commit()
            _advance(engine, row, stamp, compute_next)
            return {"run_id": "", "schedule_id": str(row.id), "skipped": state}
        if _session_busy(db, row.tenant_id, row.session_id):
            if _record_execution(
                db,
                row=row,
                scheduled_for=scheduled_for,
                status="skipped_busy",
                reason="run_active",
            ):
                db.commit()
            _advance(engine, row, stamp, compute_next)
            return {"run_id": "", "schedule_id": str(row.id), "skipped": "busy"}
        if not _record_execution(db, row=row, scheduled_for=scheduled_for, status="queued"):
            db.rollback()
            _advance(engine, row, stamp, compute_next)
            return {"run_id": "", "schedule_id": str(row.id), "skipped": "dup"}
        db.commit()

    accepted = _submit_scheduled(engine, row)
    with Session(engine) as db:
        db.execute(
            text(
                """
                UPDATE schedule_executions SET run_id = :run, status = 'queued'
                WHERE schedule_id = :sid AND scheduled_for = :for
                """
            ),
            {"run": accepted.run_id, "sid": row.id, "for": scheduled_for},
        )
        db.execute(
            text(
                """
                UPDATE web_schedules
                SET next_fire = :next_fire, last_run_id = :run_id
                WHERE id = :id
                """
            ),
            {
                "next_fire": compute_next(
                    json.loads(row.rule), stamp, getattr(row, "timezone", "UTC") or "UTC"
                ).isoformat(),
                "run_id": accepted.run_id,
                "id": row.id,
            },
        )
        db.commit()
    return {"run_id": accepted.run_id, "schedule_id": str(row.id)}


def _submit_scheduled(engine, row):
    """The schedule's stored intent becomes a real durable Run."""
    from types import SimpleNamespace

    from rxycode_server.runs.service import RunAlreadyActive, create_run

    with Session(engine) as db:
        record = SimpleNamespace(tenant_id=row.tenant_id, user_id=row.user_id or row.tenant_id)
        model_snapshot = None
        try:
            from rxycode_server.byok.resolver import resolve_run_model

            model_snapshot = resolve_run_model(db, record, getattr(row, "model_ref", None) or None)
        except Exception:
            model_snapshot = None
    message = (getattr(row, "message", "") or "").strip() or "scheduled run"
    profile = getattr(row, "permission_profile", "") or "confirm"
    if profile not in ("confirm", "full"):
        profile = "confirm"
    target_id = f"cloud:{row.tenant_id}:{row.project_id}"
    try:
        return create_run(
            engine.url.render_as_string(hide_password=False),
            tenant_id=row.tenant_id,
            session_id=row.session_id,
            message=message,
            target_id=target_id,
            permission_profile=profile,
            request_id=uuid.uuid4().hex,
            user_id=row.user_id or row.tenant_id,
            model_snapshot=model_snapshot,
            request_model_ref=getattr(row, "model_ref", None) or None,
        )
    except RunAlreadyActive:
        # TOCTOU busy — the ledger row stays 'queued' with no run; the next
        # due slot records its own skipped_busy.
        raise


def _fire_manual(db: Session, row: dict, *, reason: str) -> dict[str, str]:
    """Manual run-now: ledger reason 'manual:<request_id>' then a real run."""
    from rxycode_server.runs.service import create_run

    scheduled_for = _naive(datetime.now(timezone.utc))
    exec_id = uuid.uuid4().hex
    db.execute(
        text(
            """
            INSERT INTO schedule_executions (
                id, tenant_id, schedule_id, scheduled_for, schedule_revision,
                run_id, status, reason, notification_status, created_at
            ) VALUES (
                :id, :tenant, :schedule, :for, :rev, NULL, 'queued', :reason,
                'none', :created
            )
            """
        ),
        {
            "id": exec_id,
            "tenant": row["tenant_id"],
            "schedule": row["id"],
            "for": scheduled_for,
            "rev": int(row.get("revision") or 0),
            "reason": reason,
            "created": scheduled_for,
        },
    )
    db.flush()
    message = (row.get("message") or "").strip() or "scheduled run"
    profile = row.get("permission_profile") or "confirm"
    if profile not in ("confirm", "full"):
        profile = "confirm"
    # Same submission-time binding as the scheduled fire path — including
    # the platform grant check (a stored "platform" ref resolves only
    # while the owner still holds a grant).
    model_snapshot = None
    try:
        from types import SimpleNamespace

        from rxycode_server.byok.resolver import resolve_run_model

        record = SimpleNamespace(
            tenant_id=row["tenant_id"],
            user_id=row.get("user_id") or row["tenant_id"],
        )
        model_snapshot = resolve_run_model(
            db, record, row.get("model_ref") or None
        )
    except Exception:
        model_snapshot = None
    bind_url = db.get_bind().url.render_as_string(hide_password=False)
    accepted = create_run(
        bind_url,
        tenant_id=row["tenant_id"],
        session_id=row["session_id"],
        message=message,
        target_id=f"cloud:{row['tenant_id']}:{row['project_id']}",
        permission_profile=profile,
        request_id=uuid.uuid4().hex,
        user_id=row.get("user_id") or row["tenant_id"],
        model_snapshot=model_snapshot,
        request_model_ref=row.get("model_ref") or None,
    )
    db.execute(
        text("UPDATE schedule_executions SET run_id = :run WHERE id = :id"),
        {"run": accepted.run_id, "id": exec_id},
    )
    db.execute(
        text("UPDATE web_schedules SET last_run_id = :run WHERE id = :id"),
        {"run": accepted.run_id, "id": row["id"]},
    )
    db.flush()
    return {"run_id": accepted.run_id}


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
            if run.status != status:
                run.status = status
                from rxycode_server.events.store import append_run_status

                append_run_status(db, run, status)
            else:
                run.status = status
            if _silenced(db, tenant_id, user_id, run_id):
                db.commit()
                return {"notification_id": None, "status": status}
            found = db.execute(
                text(
                    """
                    SELECT id, delivery FROM web_notifications
                    WHERE tenant_id = :tenant AND user_id = :user
                      AND run_id = :run_id AND kind = :kind
                    """
                ),
                {"tenant": tenant_id, "user": user_id, "run_id": run_id, "kind": _NOTICE},
            ).first()
            if found is not None:
                # 重复终态回调：站内通知已存在，但首次入队邮件可能尚未发生
                # （旧版本写入的行没有 delivery 字段）。补入队一次，dedupe
                # 仍由 email_deliveries 唯一约束兜底。
                if str(found.delivery or "in_app") != "email":
                    _enqueue_result_email(
                        db,
                        run=run,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        notification_id=str(found.id),
                        status=status,
                    )
                db.commit()
                return {"notification_id": str(found.id), "status": status}
            schedule = _schedule_for_run(db, tenant_id, run_id)
            category = "scheduled_tasks" if schedule is not None else "agent_tasks"
            title = str(schedule.get("name") or "") if schedule else ""
            note_id = uuid.uuid4().hex
            delivery_id = _enqueue_result_email(
                db,
                run=run,
                tenant_id=tenant_id,
                user_id=user_id,
                notification_id=note_id,
                status=status,
            )
            db.execute(
                text(
                    """
                    INSERT INTO web_notifications
                        (id, tenant_id, user_id, kind, run_id, status, body,
                         title, category, delivery)
                    VALUES
                        (:id, :tenant, :user, :kind, :run_id, :status, :body,
                         :title, :category, :delivery)
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
                    "title": title or ("定时任务" if schedule else "任务"),
                    "category": category,
                    "delivery": "email" if delivery_id else "in_app",
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


# ---- 结果邮件投递（FR-SCHEDULE-03） -----------------------------------------
#
# 终态通知入队后由 enqueue 落一条 email_deliveries（同一事务，dedupe 由
# (run_id, recipient, kind) 唯一约束保证）；实际发送走 drain_email_deliveries
# —— 挂在 api 进程的调度 tick 上，worker 进程不需要 SMTP 凭据。

_EMAIL_MAX_ATTEMPTS = 5
_EMAIL_BACKOFF_S = 120


def _schedule_for_run(db: Session, tenant_id: str, run_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT s.id, s.name, s.timezone, s.notify, s.user_id
            FROM web_schedules s
            JOIN schedule_executions e ON e.schedule_id = s.id
            WHERE e.run_id = :run_id AND s.tenant_id = :tenant
            ORDER BY e.scheduled_for DESC LIMIT 1
            """
        ),
        {"run_id": run_id, "tenant": tenant_id},
    ).mappings().first()
    if row is None:
        row = db.execute(
            text(
                """
                SELECT id, name, timezone, notify, user_id FROM web_schedules
                WHERE tenant_id = :tenant AND last_run_id = :run_id LIMIT 1
                """
            ),
            {"tenant": tenant_id, "run_id": run_id},
        ).mappings().first()
    return dict(row) if row is not None else None


def _email_channel_on(db: Session, user_id: str, category: str) -> bool:
    """scheduled_tasks 默认开邮件（规格 §03）；其余分类默认仅站内。"""
    row = db.execute(
        text(
            "SELECT channels FROM notification_preferences"
            " WHERE user_id = :u AND category = :c"
        ),
        {"u": user_id, "c": category},
    ).first()
    default = ["in_app", "email"] if category == "scheduled_tasks" else ["in_app"]
    channels = list(row.channels) if row is not None else default
    return "email" in channels


def _result_excerpt(db: Session, run_id: str) -> str:
    """简短公开结果：最后一个 assistant.final 的可见文本，截 240 字符。
    不含工具输出/思维链/错误堆栈。"""
    event = db.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.type == "assistant.final")
        .order_by(RunEvent.seq.desc())
        .limit(1)
    ).first()
    if event is None:
        return ""
    payload = event.payload or {}
    text_out = str(payload.get("text") or payload.get("content") or "")
    return text_out.strip()[:240]


def _enqueue_result_email(
    db: Session,
    *,
    run: Run,
    tenant_id: str,
    user_id: str,
    notification_id: str,
    status: str,
) -> str | None:
    """Create the pending delivery row in the same tx as the notification.
    Returns the delivery id, or None when email is not warranted."""
    schedule = _schedule_for_run(db, tenant_id, run.id)
    category = "scheduled_tasks" if schedule is not None else "agent_tasks"
    if not _email_channel_on(db, user_id, category):
        return None
    recipient_row = db.execute(
        text("SELECT email FROM users WHERE id = :u"), {"u": user_id}
    ).first()
    recipient = str(recipient_row.email or "") if recipient_row else ""
    if not recipient:
        return None
    delivery_id = uuid.uuid4().hex
    try:
        with db.begin_nested():  # dedupe by (run_id, recipient, kind)
            db.execute(
                text(
                    """
                    INSERT INTO email_deliveries (
                        id, tenant_id, user_id, notification_id, run_id,
                        schedule_id, recipient, kind, status, attempts,
                        last_error, created_at
                    ) VALUES (
                        :id, :tenant, :user, :note, :run, :schedule,
                        :recipient, :kind, 'pending', 0, '', :now
                    )
                    """
                ),
                {
                    "id": delivery_id,
                    "tenant": tenant_id,
                    "user": user_id,
                    "note": notification_id,
                    "run": run.id,
                    "schedule": schedule["id"] if schedule else None,
                    "recipient": recipient,
                    "kind": _NOTICE,
                    "now": datetime.now(timezone.utc),
                },
            )
    except Exception:
        # Unique-key race or repeated terminal callback — the intended mail
        # already exists; nothing to enqueue.
        return None
    return delivery_id


def _render_result_email(
    db: Session, run: Run, schedule: dict | None, status: str
) -> tuple[str, str]:
    tz_name = str(schedule.get("timezone") or "UTC") if schedule else "UTC"
    name = str(schedule.get("name") or "") if schedule else ""
    try:
        from scheduler.rules import parse_timezone

        zone = parse_timezone(tz_name)
    except Exception:
        zone = timezone.utc
    finished = run.created_at or datetime.now(timezone.utc)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    local = finished.astimezone(zone)
    when = local.strftime("%Y-%m-%d %H:%M %Z")
    model = run.model_id or run.model_ref or ""
    session_url = f"/app/s/{run.session_id}"

    if status == "succeeded":
        label = "已完成"
        subject = f"定时任务「{name}」已完成" if name else "定时任务已完成"
        excerpt = _result_excerpt(db, run.id)
    elif status == "cancelled":
        label = "已取消"
        subject = f"定时任务「{name}」已取消" if name else "定时任务已取消"
        excerpt = ""
    else:
        label = "执行失败"
        subject = f"定时任务「{name}」执行失败" if name else "定时任务执行失败"
        excerpt = _result_excerpt(db, run.id)

    lines = [
        f"任务：{name or '定时任务'}",
        f"状态：{label}",
        f"完成时间：{when}（{tz_name}）",
        f"模型：{model or '—'}",
    ]
    if excerpt:
        lines += ["", "结果摘要：", excerpt]
    lines += ["", f"查看完整记录：{session_url}"]
    return subject, "\n".join(lines)


def drain_email_deliveries(
    database_url: str,
    *,
    smtp_url: str,
    smtp_from: str = "",
    limit: int = 10,
    now: datetime | None = None,
) -> dict[str, int]:
    """Send pending result emails via the shared mailer. Called from the API
    process tick loop — workers never hold SMTP credentials."""
    counts = {"sent": 0, "failed": 0, "pending": 0}
    if not smtp_url:
        return counts
    from rxycode_server.mailer import send_mail

    stamp = _naive(now or datetime.now(timezone.utc))
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            rows = db.execute(
                text(
                    """
                    SELECT id FROM email_deliveries
                    WHERE status = 'pending'
                      AND (next_retry_at IS NULL OR next_retry_at <= :now)
                    ORDER BY created_at LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"now": stamp, "limit": limit},
            ).all()
            ids = [str(row.id) for row in rows]
            if not ids:
                return counts
            deliveries = db.execute(
                text("SELECT * FROM email_deliveries WHERE id = ANY(:ids)"),
                {"ids": ids},
            ).mappings().all()
            for row in deliveries:
                run = db.get(Run, row["run_id"]) if row["run_id"] else None
                schedule = (
                    _schedule_for_run(db, str(row["tenant_id"]), str(row["run_id"]))
                    if row["run_id"]
                    else None
                )
                if run is None:
                    db.execute(
                        text(
                            "UPDATE email_deliveries SET status = 'failed',"
                            " last_error = 'run_missing' WHERE id = :id"
                        ),
                        {"id": row["id"]},
                    )
                    counts["failed"] += 1
                    continue
                subject, body = _render_result_email(
                    db, run, schedule, str(run.status)
                )
                attempts = int(row["attempts"] or 0) + 1
                ok = send_mail(
                    smtp_url,
                    to=str(row["recipient"]),
                    subject=subject,
                    body=body,
                    sender=smtp_from,
                )
                if ok:
                    db.execute(
                        text(
                            "UPDATE email_deliveries SET status = 'sent',"
                            " attempts = :a, sent_at = :now, last_error = ''"
                            " WHERE id = :id"
                        ),
                        {"a": attempts, "now": stamp, "id": row["id"]},
                    )
                    counts["sent"] += 1
                else:
                    exhausted = attempts >= _EMAIL_MAX_ATTEMPTS
                    db.execute(
                        text(
                            "UPDATE email_deliveries SET status = :status,"
                            " attempts = :a, last_error = :err,"
                            " next_retry_at = :retry WHERE id = :id"
                        ),
                        {
                            "status": "failed" if exhausted else "pending",
                            "a": attempts,
                            "err": "smtp_rejected" if not exhausted else "smtp_rejected_final",
                            "retry": None
                            if exhausted
                            else stamp + timedelta(seconds=_EMAIL_BACKOFF_S * attempts),
                            "id": row["id"],
                        },
                    )
                    counts["failed" if exhausted else "pending"] += 1
            db.commit()
            return counts
    finally:
        engine.dispose()


def _usage_day(db: Session, record: UsageRecord) -> str:
    events = db.scalars(
        select(RunEvent).where(
            RunEvent.run_id == record.run_id,
            RunEvent.type == "usage.updated",
        )
    ).all()
    for event in events:
        payload = event.payload or {}
        if (
            payload.get("model_id") == record.model_id
            and payload.get("price_version") == record.price_version
        ):
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
# GET /api/v1/notifications moved to api/notifications.py (cursor/category/
# read fields). POST /notifications/unsubscribe stays here for compat.
router.add_api_route("/api/v1/notifications/unsubscribe", unsubscribe, methods=["POST"])


# POST /api/v1/schedules is served by api/schedules.py — the extended
# contract (name/message/timezone/model_ref/request_id). create_web_schedule
# above stays as the programmatic entry used by tests and seeding.
