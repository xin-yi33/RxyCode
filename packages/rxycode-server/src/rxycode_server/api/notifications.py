"""Notification preferences, list/read, email retry and push subscriptions.

Categories are the fixed product taxonomy; a user row only stores overrides —
no row means the default channel set (in_app). Legacy web_unsubscribes rows
still silence agent_tasks in-app, so an old unsubscribe can never fight the
new preference surface.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.persistence.models import (
    EmailDelivery,
    NotificationPreference,
    PushSubscription,
    User,
)

router = APIRouter()
_CATEGORIES = (
    "agent_tasks",
    "personalized",
    "scheduled_tasks",
    "usage",
    "health",
    "replies",
    "group_chats",
    "marketing",
    "library",
    "projects",
)
_CHANNELS = {"in_app", "push", "email"}
_DEFAULT_CHANNELS = ["in_app"]
_PAGE_LIMIT = 100
_PUSH_HOST = re.compile(r"^https://[a-z0-9.-]+(:\d+)?/", re.IGNORECASE)


def _iso(value) -> str | None:
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if value is not None else None


def _push_capability(request: Request) -> dict[str, object]:
    configured = bool(getattr(request.app.state, "webpush_public_key", ""))
    return {
        "available": configured,
        "reason": "" if configured else "webpush_not_configured",
    }


def _email_delivery(request: Request) -> str:
    configured = bool(getattr(request.app.state, "smtp_url", "") or "")
    return "configured" if configured else "unavailable"


def _category_rows(db: Session, user_id: str) -> dict[str, NotificationPreference]:
    return {
        row.category: row
        for row in db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        ).all()
    }


def _legacy_muted(db: Session, record) -> set[str]:
    rows = db.execute(
        text("SELECT kind FROM web_unsubscribes WHERE tenant_id = :t AND user_id = :u"),
        {"t": record.tenant_id, "u": record.user_id},
    ).all()
    # Old unsubscribes map onto the matching category's in_app channel.
    return {str(row.kind) for row in rows}


def _prefs_payload(db: Session, request: Request, record) -> dict[str, object]:
    overrides = _category_rows(db, record.user_id)
    muted = _legacy_muted(db, record)
    email_ok = _email_delivery(request) == "configured"
    push_ok = bool(_push_capability(request)["available"])
    # 无业务源的分类诚实标依赖（§03 NTF-05/07/09/10 待确认项）：
    # 行保留、可选渠道为空、原因可读；不伪称已接入。
    _SOURCES: dict[str, str] = {
        "health": "no_event_source",
        "group_chats": "no_event_source",
        "library": "no_event_source",
        "projects": "no_event_source",
        "personalized": "no_event_source",
    }
    categories = []
    for cat in _CATEGORIES:
        row = overrides.get(cat)
        if cat == "scheduled_tasks":
            # 定时结果邮件默认开启（§03）；其余分类默认仅站内。
            default = ["in_app", "email"]
        elif cat == "marketing":
            default = []  # 单独同意，默认关闭
        else:
            default = list(_DEFAULT_CHANNELS)
        selected = list(row.channels) if row is not None else default
        if cat == "agent_tasks" and "run.completed" in muted and row is None:
            selected = [c for c in selected if c != "in_app"]
        source = _SOURCES.get(cat, "")
        channels_allowed = ["in_app"]
        if push_ok:
            channels_allowed.append("push")
        if email_ok:
            channels_allowed.append("email")
        if source:
            channels_allowed = []
            selected = []
        categories.append(
            {
                "id": cat,
                "label": cat.replace("_", " "),
                "available": not source,
                "reason": source,
                "allowed_channels": channels_allowed,
                "selected_channels": selected,
            }
        )
    revision = max((0 for _ in ()), default=0)
    if overrides:
        # The category rows share no single revision; the max updated_at
        # epoch-ms acts as the optimistic-concurrency token.
        stamps = [
            int(row.updated_at.timestamp() * 1000)
            for row in overrides.values()
            if row.updated_at is not None
        ]
        revision = max(stamps, default=0)
    return {
        "revision": revision,
        "categories": categories,
        "email_delivery": _email_delivery(request),
        "push_capability": _push_capability(request),
    }


@router.get("/api/v1/me/notification-preferences")
def get_notification_preferences(
    request: Request, db: Session = Depends(db_session)
) -> dict[str, object]:
    record = current_record(request)
    return _prefs_payload(db, request, record)


class _PrefPatch(BaseModel):
    category_id: str
    selected_channels: list[str]
    expected_revision: int | None = None


@router.patch("/api/v1/me/notification-preferences")
def patch_notification_preferences(
    payload: _PrefPatch,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if payload.category_id not in _CATEGORIES:
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    if not set(payload.selected_channels) <= _CHANNELS:
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    if "push" in payload.selected_channels and not _push_capability(request)["available"]:
        raise HTTPException(status_code=503, detail="PUSH_UNAVAILABLE")
    if "email" in payload.selected_channels and _email_delivery(request) != "configured":
        raise HTTPException(status_code=503, detail="EMAIL_DELIVERY_UNAVAILABLE")
    # 无业务源的分类拒绝假开启（NTF-05/07/09/10 待确认项）。
    _NO_SOURCE = {"health", "group_chats", "library", "projects", "personalized"}
    if payload.selected_channels and payload.category_id in _NO_SOURCE:
        raise HTTPException(status_code=422, detail="CATEGORY_UNAVAILABLE")
    row = db.execute(
        select(NotificationPreference)
        .where(
            NotificationPreference.user_id == record.user_id,
            NotificationPreference.category == payload.category_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if payload.expected_revision is not None:
        current = _prefs_payload(db, request, record)["revision"]
        if int(current) != int(payload.expected_revision):
            raise HTTPException(status_code=409, detail="REVISION_CONFLICT")
    if row is None:
        row = NotificationPreference(user_id=record.user_id, category=payload.category_id)
        db.add(row)
    row.channels = list(dict.fromkeys(payload.selected_channels))
    db.flush()
    # New preferences win over the legacy mute: clear the matching
    # unsubscribe so the UI never shows "on" while the old row silences it.
    if payload.category_id == "agent_tasks" and "in_app" in row.channels:
        db.execute(
            text(
                "DELETE FROM web_unsubscribes WHERE tenant_id = :t"
                " AND user_id = :u AND kind = 'run.completed'"
            ),
            {"t": record.tenant_id, "u": record.user_id},
        )
    db.flush()
    return _prefs_payload(db, request, record)


def _cursor(raw: str) -> str | None:
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        return str(data[0])
    except (ValueError, TypeError, IndexError, KeyError):
        return None


@router.get("/api/v1/notifications")
def list_notifications(
    request: Request,
    category: str = "all",
    unread: str = "false",
    cursor: str = "",
    limit: int = 30,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    if category != "all" and category not in _CATEGORIES:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if unread not in ("true", "false"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    limit = max(1, min(int(limit or 30), _PAGE_LIMIT))
    clauses = ["tenant_id = :t", "user_id = :u"]
    params: dict[str, object] = {"t": record.tenant_id, "u": record.user_id}
    if category != "all":
        clauses.append("category = :cat")
        params["cat"] = category
    if unread == "true":
        clauses.append("read_at IS NULL")
    mark = _cursor(cursor) if cursor else None
    if cursor and mark is None:
        raise HTTPException(status_code=400, detail="INVALID_CURSOR")
    if mark:
        clauses.append("id < :mark")
        params["mark"] = mark
    rows = (
        db.execute(
            text(
                "SELECT id, run_id, kind, status, body, title, category, delivery,"
                " read_at, created_at FROM web_notifications WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC NULLS LAST, id DESC LIMIT :limit"
            ),
            {**params, "limit": limit + 1},
        )
        .mappings()
        .all()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(json.dumps([rows[-1]["id"]]).encode()).decode()
    return {
        "notifications": [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "kind": row["kind"],
                "status": row["status"],
                "body": row["body"],
                "title": row["title"] or "",
                "category": row["category"],
                "delivery": row["delivery"],
                "read": row["read_at"] is not None,
                "created_at": _iso(row["created_at"]),
                "tenant_id": record.tenant_id,
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


class _ReadIn(BaseModel):
    read: bool = True


@router.post("/api/v1/notifications/{notification_id}/read")
def mark_read(
    notification_id: str,
    payload: _ReadIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    stamp = datetime.now(timezone.utc) if payload.read else None
    result = db.execute(
        text(
            "UPDATE web_notifications SET read_at = :stamp"
            " WHERE id = :id AND tenant_id = :t AND user_id = :u"
        ),
        {
            "stamp": stamp,
            "id": notification_id,
            "t": record.tenant_id,
            "u": record.user_id,
        },
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="NOTIFICATION_NOT_FOUND")
    db.flush()
    return {"id": notification_id, "read": bool(payload.read)}


class _RetryIn(BaseModel):
    request_id: str | None = None


@router.post("/api/v1/notifications/{notification_id}/retry-email", status_code=202)
def retry_email(
    notification_id: str,
    payload: _RetryIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    """Re-queue ONLY the email leg — never re-runs the model or the run."""
    require_write(request)
    record = current_record(request)
    if not getattr(request.app.state, "smtp_url", "") or "":
        raise HTTPException(status_code=503, detail="EMAIL_DELIVERY_UNAVAILABLE")
    note = (
        db.execute(
            text(
                "SELECT id, run_id, kind FROM web_notifications"
                " WHERE id = :id AND tenant_id = :t AND user_id = :u"
            ),
            {"id": notification_id, "t": record.tenant_id, "u": record.user_id},
        )
        .mappings()
        .first()
    )
    if note is None:
        raise HTTPException(status_code=404, detail="NOTIFICATION_NOT_FOUND")
    user = db.get(User, record.user_id)
    recipient = str(getattr(user, "email", "") or "")
    if not recipient:
        raise HTTPException(status_code=422, detail="EMAIL_REQUIRED")
    # One intended email per (run, recipient, kind): retry revives the same
    # delivery row instead of inserting a duplicate (unique constraint).
    delivery = db.scalars(
        select(EmailDelivery).where(
            EmailDelivery.run_id == note["run_id"],
            EmailDelivery.recipient == recipient,
            EmailDelivery.kind == (note["kind"] or "run.completed"),
        )
    ).first()
    if delivery is not None:
        if delivery.status == "sent":
            return {"delivery_id": delivery.id, "status": "sent"}
        delivery.status = "pending"
        delivery.notification_id = notification_id
        delivery.next_retry_at = None
        delivery.last_error = ""
        db.flush()
        return {"delivery_id": delivery.id, "status": "pending"}
    delivery = EmailDelivery(
        id=uuid.uuid4().hex,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        notification_id=notification_id,
        run_id=note["run_id"],
        recipient=recipient,
        kind=note["kind"] or "run.completed",
        status="pending",
        attempts=0,
    )
    db.add(delivery)
    db.flush()
    return {"delivery_id": delivery.id, "status": "pending"}


class _PushIn(BaseModel):
    subscription: dict
    request_id: str | None = None


class _PushDelete(BaseModel):
    subscription_id: str


@router.post("/api/v1/me/push-subscriptions", status_code=201)
def add_push_subscription(
    payload: _PushIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if not _push_capability(request)["available"]:
        raise HTTPException(status_code=503, detail="PUSH_UNAVAILABLE")
    sub = payload.subscription
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    if (
        not _PUSH_HOST.match(endpoint)
        or len(endpoint) > 2000
        or not isinstance(keys, dict)
        or not str(keys.get("p256dh") or "")
        or not str(keys.get("auth") or "")
        or len(str(keys.get("p256dh"))) > 200
        or len(str(keys.get("auth"))) > 100
    ):
        raise HTTPException(status_code=422, detail="INVALID_SUBSCRIPTION")
    endpoint_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    existing = db.scalars(
        select(PushSubscription).where(
            PushSubscription.user_id == record.user_id,
            PushSubscription.endpoint_hash == endpoint_hash,
        )
    ).one_or_none()
    if existing is not None:
        return {"subscription_id": existing.id}
    row = PushSubscription(
        id=uuid.uuid4().hex,
        user_id=record.user_id,
        endpoint_hash=endpoint_hash,
        endpoint=endpoint,
        keys={"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])},
    )
    db.add(row)
    db.flush()
    return {"subscription_id": row.id}


@router.delete("/api/v1/me/push-subscriptions", status_code=204)
def delete_push_subscription(
    payload: _PushDelete,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    result = db.execute(
        PushSubscription.__table__.delete().where(
            PushSubscription.id == payload.subscription_id,
            PushSubscription.user_id == record.user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="SUBSCRIPTION_NOT_FOUND")
    db.flush()
    return None
