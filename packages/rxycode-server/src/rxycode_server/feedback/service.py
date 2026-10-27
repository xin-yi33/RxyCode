"""Feedback service layer: rate windows, batch rolling, dedupe, exports.

Batch rule (定量统计): every item lands in the current open batch; when the
open batch is full (``item_count >= capacity``) or the serving build_commit
no longer matches the batch's (a new deployment = a new version bucket), the
batch is closed — ``closed_at`` + a counter summary — and a fresh
``seq = max+1`` batch opens inside the same transaction. The partial unique
index ``uq_feedback_batches_open`` makes the whole thing safe under
concurrent submissions: two transactions racing to open a batch collide on
the index, the loser rolls back and retries (at most 3 times), finding the
winner's open batch on the second pass.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from rxycode_server.api.auth import _Window
from rxycode_server.api.version import build_commit
from rxycode_server.persistence.models import (
    FeedbackBatch,
    FeedbackImage,
    FeedbackItem,
)

DEFAULT_BATCH_SIZE = 20
MAX_SUBMIT_ATTEMPTS = 3
DAILY_USER_LIMIT = 30
GLOBAL_WINDOW_SECONDS = 600
GLOBAL_WINDOW_LIMIT = 200
CAPTCHA_ESCALATE_COUNT = 3
CAPTCHA_ESCALATE_SECONDS = 3600
DEDUPE_WINDOW = timedelta(hours=24)
STAGED_IMAGE_TTL = timedelta(hours=24)
STAGED_IMAGE_LIMIT = 10
MAX_IMAGES_PER_ITEM = 5

KINDS = {"bug", "suggestion", "content_quality"}
MODULES = {
    "chat",
    "run_output",
    "tools",
    "files_preview",
    "settings",
    "auth",
    "models_byok",
    "mobile",
    "performance",
    "other",
}
SEVERITIES = {"low", "normal", "high"}
SOURCES = {"manual", "auto_prompt"}
STATES = {"new", "triaged", "in_progress", "resolved", "wontfix", "spam"}


class FeedbackRateLimit:
    """Per-feature fixed windows. Two independent buckets on every write —
    per-user and per-IP, never a composite key (a composite key lets one IP
    burn the per-user quota of every account it can reach). DB counters
    cover the daily cap and the global circuit breaker."""

    def __init__(self) -> None:
        self.submit_user = _Window(5, window_seconds=600)
        self.submit_ip = _Window(20, window_seconds=600)
        self.image_user = _Window(20, window_seconds=600)
        self.image_ip = _Window(40, window_seconds=600)


def rate_limits(request) -> FeedbackRateLimit:
    limiter = getattr(request.app.state, "feedback_rate", None)
    if limiter is None:
        limiter = FeedbackRateLimit()
        request.app.state.feedback_rate = limiter
    return limiter


def _retry_after(window: _Window) -> int:
    return max(1, window.window_seconds - int(time.monotonic()) % window.window_seconds)


def check_submit_limit(request, user_id: str, ip: str) -> None:
    limiter = rate_limits(request)
    if not limiter.submit_user.hit(f"user:{user_id}"):
        raise HTTPException(
            429, detail="RATE_LIMITED", headers={"Retry-After": str(_retry_after(limiter.submit_user))}
        )
    if not limiter.submit_ip.hit(f"ip:{ip}"):
        raise HTTPException(
            429, detail="RATE_LIMITED", headers={"Retry-After": str(_retry_after(limiter.submit_ip))}
        )


def check_image_limit(request, user_id: str, ip: str) -> None:
    limiter = rate_limits(request)
    if not limiter.image_user.hit(f"user:{user_id}"):
        raise HTTPException(
            429, detail="RATE_LIMITED", headers={"Retry-After": str(_retry_after(limiter.image_user))}
        )
    if not limiter.image_ip.hit(f"ip:{ip}"):
        raise HTTPException(
            429, detail="RATE_LIMITED", headers={"Retry-After": str(_retry_after(limiter.image_ip))}
        )


def check_daily_user_cap(db: Session, user_id: str) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    count = db.scalar(
        select(func.count(FeedbackItem.id)).where(
            FeedbackItem.user_id == user_id, FeedbackItem.created_at >= since
        )
    ) or 0
    if count >= DAILY_USER_LIMIT:
        raise HTTPException(429, detail="RATE_LIMITED", headers={"Retry-After": "3600"})


def check_global_circuit(db: Session) -> None:
    since = datetime.now(timezone.utc) - timedelta(seconds=GLOBAL_WINDOW_SECONDS)
    count = db.scalar(
        select(func.count(FeedbackItem.id)).where(FeedbackItem.created_at >= since)
    ) or 0
    if count > GLOBAL_WINDOW_LIMIT:
        raise HTTPException(503, detail="FEEDBACK_BUSY", headers={"Retry-After": "60"})


def captcha_required(db: Session, user_id: str) -> bool:
    since = datetime.now(timezone.utc) - timedelta(seconds=CAPTCHA_ESCALATE_SECONDS)
    count = db.scalar(
        select(func.count(FeedbackItem.id)).where(
            FeedbackItem.user_id == user_id, FeedbackItem.created_at >= since
        )
    ) or 0
    return count >= CAPTCHA_ESCALATE_COUNT


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")


def sanitize_text(text: str, limit: int) -> str:
    cleaned = _CONTROL_RE.sub("", text or "").strip()
    return cleaned[:limit]


def sanitize_line(text: str, limit: int) -> str:
    """单行字段（title/page_path/UA 等）：换行与制表折叠成单空格，
    否则导出/展示时一个字段能跨行注入假元数据。"""
    return _WS_RE.sub(" ", sanitize_text(text, limit)).strip()


def normalize_body(body: str) -> str:
    return _WS_RE.sub(" ", body.strip().lower())


def content_hash(body: str) -> str:
    return hashlib.sha256(normalize_body(body).encode("utf-8")).hexdigest()


def ip_hmac(secret: str, ip: str) -> str:
    """Pseudonymized client key — the raw address never lands in the table."""
    return hmac.new(secret.encode(), f"feedback:{ip}".encode(), "sha256").hexdigest()


def batch_capacity() -> int:
    raw = os.environ.get("RXYCODE_FEEDBACK_BATCH_SIZE", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_BATCH_SIZE
    except ValueError:
        value = DEFAULT_BATCH_SIZE
    return max(1, value)


def admin_emails() -> set[str]:
    raw = os.environ.get("RXYCODE_FEEDBACK_ADMIN_EMAILS", "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def is_admin_email(email: str | None) -> bool:
    return bool(email) and email.strip().lower() in admin_emails()


def batch_label(seq: int) -> str:
    return f"FB-{seq:04d}"


def _batch_summary(db: Session, batch_id: str) -> dict[str, object]:
    items = list(
        db.scalars(select(FeedbackItem).where(FeedbackItem.batch_id == batch_id))
    )
    by_module = Counter(item.module for item in items)
    by_kind = Counter(item.kind for item in items)
    by_severity = Counter(item.severity or "none" for item in items)
    by_source = Counter(item.source for item in items)
    by_reason: Counter[str] = Counter()
    for item in items:
        for reason in item.trigger_reasons or []:
            by_reason[str(reason)] += 1
    groups = Counter(item.content_sha256 for item in items if item.content_sha256)
    dupes = [
        {"content_sha256": sha, "count": n}
        for sha, n in groups.most_common(10)
        if n > 1
    ]
    return {
        "items": len(items),
        "by_module": dict(by_module),
        "by_kind": dict(by_kind),
        "by_severity": dict(by_severity),
        "by_source": dict(by_source),
        "by_trigger_reason": dict(by_reason),
        "duplicate_groups": dupes,
    }


def close_batch(db: Session, batch: FeedbackBatch) -> None:
    batch.status = "closed"
    batch.closed_at = datetime.now(timezone.utc)
    batch.summary = _batch_summary(db, batch.id)
    db.flush()


# pg advisory lock key serializing batch roll/create —— 让「关闭旧批 + 开新批」
# 在多连接并发下严格串行，部分唯一索引只做兜底（不再被常规并发撞出重试）。
_BATCH_LOCK_KEY = 0xF33DBAC7


def assign_batch(db: Session, item: FeedbackItem) -> FeedbackBatch:
    """Lock the open batch, roll it when full/stale, attach the item.

    ``SET LOCAL lock_timeout`` 保底：争用时等待上限 5s，超时抛 55P03 交给
    submit_item 的重试循环 —— 否则一个卡住的事务会把所有提交永久挂在锁上。
    """
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BATCH_LOCK_KEY})
    commit = build_commit()
    capacity = batch_capacity()
    batch = db.scalars(
        select(FeedbackBatch)
        .where(FeedbackBatch.status == "open")
        .with_for_update()
    ).first()
    if batch is not None and (
        int(batch.item_count or 0) >= int(batch.capacity or capacity)
        or (batch.build_commit or "") != commit
    ):
        close_batch(db, batch)
        batch = None
    if batch is None:
        seq = db.scalar(select(func.max(FeedbackBatch.seq))) or 0
        batch = FeedbackBatch(
            id=uuid.uuid4().hex,
            seq=int(seq) + 1,
            status="open",
            build_commit=commit,
            capacity=capacity,
            item_count=0,
        )
        db.add(batch)
        db.flush()
    batch.item_count = int(batch.item_count or 0) + 1
    item.batch_id = batch.id
    return batch


def submit_item(
    db: Session, item: FeedbackItem, *, captcha_ok: bool = False
) -> tuple[FeedbackItem, int, bool]:
    """Idempotency + batch assignment with integrity-retry (concurrent open).

    ``uq_feedback_user_request`` and ``uq_feedback_batches_open`` are the two
    collision surfaces; both resolve to "retry the whole attempt" — on the
    second pass the earlier transaction's row is visible, so a duplicate
    request returns the existing item and a batch race finds the new open
    batch. Returns ``(item, batch_seq, is_duplicate)``.

    ``captcha_ok``：本请求是否已在端点层通过 ``_require_captcha``。日上限
    与验证码升级在拿到 batch 级 advisory lock 之后复查 —— 并发请求在
    锁外看到的是同一份旧计数，锁内复查才是串行真值。
    """
    for _attempt in range(MAX_SUBMIT_ATTEMPTS):
        existing = db.scalars(
            select(FeedbackItem).where(
                FeedbackItem.user_id == item.user_id,
                FeedbackItem.request_id == item.request_id,
            )
        ).first()
        if existing is not None:
            seq = db.scalar(
                select(FeedbackBatch.seq).where(FeedbackBatch.id == existing.batch_id)
            ) or 0
            return existing, int(seq), True
        try:
            batch = assign_batch(db, item)
            # advisory lock 仍持有（xact 级）——此时对计数的读是串行点。
            check_daily_user_cap(db, item.user_id)
            if captcha_required(db, item.user_id) and not captcha_ok:
                raise HTTPException(400, detail="CAPTCHA_REQUIRED")
            db.add(item)
            db.flush()
            return item, int(batch.seq), False
        except IntegrityError:
            db.rollback()
            item.batch_id = ""
        except OperationalError as exc:
            # 40P01：FOR UPDATE 死锁；55P03：lock_timeout 到期 —— 都与
            # 唯一索引冲突同等处理：回滚重试；其他 OperationalError 不掩盖。
            if getattr(exc.orig, "pgcode", "") not in ("40P01", "55P03"):
                raise
            db.rollback()
            item.batch_id = ""
    raise HTTPException(503, detail="FEEDBACK_BUSY")


def sweep_expired_images(
    db: Session, store, user_id: str | None = None, limit: int = 50
) -> int:
    """过期 staged 图片：删 blob + 删行（只改 state 会泄漏存储）。

    ``user_id=None`` 时是全局清扫（每次上传顺带跑一趟，LIMIT 50
    防大清扫阻塞请求）。blob 删除失败不阻塞行删除 —— 孤儿 blob 由
    下一轮清扫兜底，行必须先走，否则引用会永久悬挂。
    """
    now = datetime.now(timezone.utc)
    query = (
        select(FeedbackImage)
        .where(
            FeedbackImage.state == "staged",
            FeedbackImage.expires_at.is_not(None),
            FeedbackImage.expires_at < now,
        )
        .order_by(FeedbackImage.expires_at)
        .limit(limit)
    )
    if user_id is not None:
        query = query.where(FeedbackImage.user_id == user_id)
    rows = list(db.scalars(query))
    for row in rows:
        try:
            store.delete(row.blob_key)
        except Exception:
            pass
        db.delete(row)
    if rows:
        db.flush()
    return len(rows)


def staged_image_count(db: Session, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    return db.scalar(
        select(func.count(FeedbackImage.id)).where(
            FeedbackImage.user_id == user_id,
            FeedbackImage.state == "staged",
            FeedbackImage.expires_at > now,
        )
    ) or 0
