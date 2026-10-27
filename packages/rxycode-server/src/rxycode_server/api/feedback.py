"""User feedback API — submit (with sanitized screenshots), list, admin export.

Anti-abuse layers, in order on every write path: in-memory rate windows
(checked BEFORE the body is read) → byte caps → honeypot → payload
validation → ownership checks → idempotency → 24h content dedupe → ALTCHA
escalation → DB daily cap → global circuit breaker. Admin endpoints return
404 for everyone outside RXYCODE_FEEDBACK_ADMIN_EMAILS — the surface does
not exist for ordinary users.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from rxycode_server.api.auth import (
    AuthRecord,
    _require_captcha,
    current_record,
    db_session,
    require_write,
)
from rxycode_server.api.client_ip import client_ip
from rxycode_server.api.version import build_commit
from rxycode_server.attachments.store import open_store
from rxycode_server.feedback import service as svc
from rxycode_server.feedback.export import batch_payload, export_markdown
from rxycode_server.feedback.images import (
    MAX_IMAGE_BYTES,
    ImageRejected,
    sanitize_image,
)
from rxycode_server.persistence.models import (
    FeedbackBatch,
    FeedbackImage,
    FeedbackItem,
    Run,
    SessionRow,
    User,
)

router = APIRouter()

_MAX_BODY_BYTES = 64 * 1024
_DEDUPE_HOURS = 24

# 解码是全内存操作（25MP 图 ≈ 百 MB 级工作集）——多用户同时上传会叠
# 内存。全局闸只允许同时 2 个解码，其余在 to_thread 里排队。
_DECODE_SEM = threading.BoundedSemaphore(2)


def _decode_guarded(raw: bytes):
    with _DECODE_SEM:
        return sanitize_image(raw)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store(request: Request):
    return open_store(request.app.state.attachment_blobs)


def _image_map(exc: ImageRejected) -> HTTPException:
    return HTTPException(exc.status, detail=exc.code)


async def _read_capped(request: Request, limit: int, code: str) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                raise HTTPException(413, detail=code)
        except ValueError:
            raise HTTPException(400, detail="INVALID_INPUT") from None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(413, detail=code)
    return bytes(body)


def _admin(request: Request, db: Session, record: AuthRecord) -> User:
    """404 for non-admins — existence of the admin surface is not leaked."""
    user = db.get(User, record.user_id)
    if user is None or not svc.is_admin_email(user.email):
        raise HTTPException(404, detail="NOT_FOUND")
    return user


def _public_item(item: FeedbackItem, batch_seq: int, images=None) -> dict:
    return {
        "id": item.id,
        "batch_seq": batch_seq,
        "kind": item.kind,
        "module": item.module,
        "severity": item.severity,
        "title": item.title,
        "body": item.body,
        "source": item.source,
        "trigger_reasons": item.trigger_reasons or [],
        "state": item.state,
        "run_id": item.run_id,
        "session_id": item.session_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "images": images if images is not None else [],
    }


# ---- images ---------------------------------------------------------------


def _image_precheck(db: Session, store, record: AuthRecord) -> None:
    """清扫 + 满额拒绝 —— 在读 body 前完成，满额用户不消耗解码资源。"""
    svc.sweep_expired_images(db, store)  # 全局过期清扫（每上传顺带，LIMIT 50）
    if svc.staged_image_count(db, record.user_id) >= svc.STAGED_IMAGE_LIMIT:
        raise HTTPException(429, detail="RATE_LIMITED", headers={"Retry-After": "60"})


def _image_commit(db: Session, store, record: AuthRecord, image) -> FeedbackImage:
    image_id = uuid.uuid4().hex
    blob_key = f"feedback/{record.tenant_id}/{image_id}"
    try:
        store.put_stream(
            blob_key, io.BytesIO(image.blob), content_type=image.content_type
        )
    except Exception:
        raise HTTPException(503, detail="STORAGE_UNAVAILABLE") from None
    row = FeedbackImage(
        id=image_id,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        state="staged",
        blob_key=blob_key,
        sha256=image.sha256,
        content_type=image.content_type,
        width=image.width,
        height=image.height,
        size_bytes=len(image.blob),
        expires_at=_now() + svc.STAGED_IMAGE_TTL,
    )
    db.add(row)
    db.flush()
    return row


# 事件循环上只允许：限流检查（内存）+ body 读取 + 解码（线程+信号量）。
# 所有 DB 访问走 run_in_threadpool —— sync SQLAlchemy 在 loop 线程上
# 阻塞（尤其 pg_advisory_xact_lock 等待）会冻住整个事件循环，连持锁
# 事务的 commit 都无法调度（本地压力实测全栈死锁）。
@router.post("/api/v1/feedback/images", status_code=201)
async def upload_image(
    request: Request, db: Session = Depends(db_session)
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    svc.check_image_limit(request, record.user_id, client_ip(request))
    store = _store(request)
    await run_in_threadpool(_image_precheck, db, store, record)

    raw = await _read_capped(request, MAX_IMAGE_BYTES, "FEEDBACK_IMAGE_TOO_LARGE")
    try:
        image = await asyncio.to_thread(_decode_guarded, raw)
    except ImageRejected as exc:
        raise _image_map(exc) from exc

    row = await run_in_threadpool(_image_commit, db, store, record, image)
    return {
        "image_id": row.id,
        "width": row.width,
        "height": row.height,
        "size_bytes": row.size_bytes,
        "content_type": row.content_type,
    }


@router.get("/api/v1/feedback/images/{image_id}")
def get_image(
    image_id: str, request: Request, db: Session = Depends(db_session)
) -> Response:
    record = current_record(request)
    row = db.get(FeedbackImage, image_id)
    if row is None:
        raise HTTPException(404, detail="NOT_FOUND")
    owner = row.user_id == record.user_id and row.tenant_id == record.tenant_id
    if not owner:
        _admin(request, db, record)  # admin may read; everyone else gets 404
    try:
        with _store(request).open_read(row.blob_key) as stream:
            payload = stream.read()
    except FileNotFoundError:
        raise HTTPException(404, detail="NOT_FOUND") from None
    return Response(
        content=payload,
        media_type=row.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline",
        },
    )


@router.delete("/api/v1/feedback/images/{image_id}", status_code=204)
def delete_image(
    image_id: str, request: Request, db: Session = Depends(db_session)
) -> None:
    require_write(request)
    record = current_record(request)
    row = db.get(FeedbackImage, image_id)
    if (
        row is None
        or row.user_id != record.user_id
        or row.tenant_id != record.tenant_id
        or row.state != "staged"
    ):
        raise HTTPException(404, detail="NOT_FOUND")
    _store(request).delete(row.blob_key)
    db.delete(row)
    db.flush()
    return None


# ---- submit ---------------------------------------------------------------


def _enum(value, allowed: set[str], code: str = "INVALID_INPUT") -> str:
    text = svc.sanitize_text(str(value or ""), 32)
    if text not in allowed:
        raise HTTPException(422, detail=code)
    return text


def _str_list(value, cap: int, item_len: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [svc.sanitize_text(str(v), item_len) for v in value[:cap] if str(v).strip()]


def _submit_db(
    request: Request, db: Session, record: AuthRecord, ip: str, fields: dict
) -> tuple[FeedbackItem, int, bool]:
    """整段 DB 工作 —— 在 worker 线程执行（advisory lock 等待不再冻 loop）。

    幂等最先：同 (user_id, request_id) 已存在直接 200 回原条目 —— 不做
    图片/run/session 校验，否则「响应丢失后重试」会被 422/404 误伤。
    """
    existing = db.scalars(
        select(FeedbackItem).where(
            FeedbackItem.user_id == record.user_id,
            FeedbackItem.request_id == fields["request_id"],
        )
    ).first()
    if existing is not None:
        seq = db.scalar(
            select(FeedbackBatch.seq).where(FeedbackBatch.id == existing.batch_id)
        ) or 0
        return existing, int(seq), True

    run_id = fields["run_id"]
    session_id = fields["session_id"]
    if run_id and db.scalar(
        select(Run.id).where(Run.id == run_id, Run.tenant_id == record.tenant_id)
    ) is None:
        raise HTTPException(404, detail="NOT_FOUND")
    if session_id and db.scalar(
        select(SessionRow.id).where(
            SessionRow.id == session_id, SessionRow.tenant_id == record.tenant_id
        )
    ) is None:
        raise HTTPException(404, detail="NOT_FOUND")

    images: list[FeedbackImage] = []
    if fields["image_ids"]:
        now = _now()
        for image_id in dict.fromkeys(fields["image_ids"]):
            row = db.get(FeedbackImage, image_id)
            if (
                row is None
                or row.user_id != record.user_id
                or row.tenant_id != record.tenant_id
                or row.state != "staged"
                or (row.expires_at is not None and row.expires_at < now)
            ):
                raise HTTPException(422, detail="FEEDBACK_IMAGE_INVALID")
            images.append(row)

    svc.check_daily_user_cap(db, record.user_id)
    svc.check_global_circuit(db)

    sha = svc.content_hash(fields["text"])
    if db.scalar(
        select(FeedbackItem.id).where(
            FeedbackItem.user_id == record.user_id,
            FeedbackItem.content_sha256 == sha,
            FeedbackItem.created_at >= _now() - svc.DEDUPE_WINDOW,
        )
    ) is not None:
        raise HTTPException(409, detail="FEEDBACK_DUPLICATE")

    captcha_ok = False
    if svc.captcha_required(db, record.user_id):
        if not fields["captcha"]:
            raise HTTPException(400, detail="CAPTCHA_REQUIRED")
        _require_captcha(request, {"captcha": fields["captcha"]})
        captcha_ok = True

    item = FeedbackItem(
        id=uuid.uuid4().hex,
        batch_id="",  # assigned inside submit_item's locked transaction
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        request_id=fields["request_id"],
        kind=fields["kind"],
        module=fields["module"],
        severity=fields["severity"],
        title=fields["title"],
        body=fields["text"],
        source=fields["source"],
        trigger_reasons=fields["reasons"],
        run_id=run_id,
        session_id=session_id,
        page_path=fields["page_path"],
        build_commit=build_commit(),
        client_build=fields["client_build"],
        user_agent=fields["user_agent"],
        viewport=fields["viewport"],
        locale=fields["locale"],
        content_sha256=sha,
        ip_hmac=svc.ip_hmac(request.app.state.secret, ip),
        state="new",
    )
    saved, batch_seq, duplicated = svc.submit_item(db, item, captcha_ok=captcha_ok)
    if not duplicated:
        for row in images:
            row.state = "bound"
            row.item_id = saved.id
            row.expires_at = None
        db.flush()
    return saved, batch_seq, duplicated


@router.post("/api/v1/feedback", status_code=201)
async def submit(request: Request, db: Session = Depends(db_session)) -> Response:
    require_write(request)
    record = current_record(request)
    ip = client_ip(request)
    svc.check_submit_limit(request, record.user_id, ip)

    raw = await _read_capped(request, _MAX_BODY_BYTES, "FEEDBACK_TOO_LARGE")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, detail="INVALID_INPUT") from None
    if not isinstance(body, dict):
        raise HTTPException(400, detail="INVALID_INPUT")

    # Honeypot: a real user never fills the hidden "website" field. Fake a
    # success and write nothing — no row, no images bound, no signal back.
    if str(body.get("website") or "").strip():
        return Response(
            status_code=201,
            content=json.dumps({"id": f"fb_fake_{uuid.uuid4().hex[:12]}", "batch_seq": 0, "state": "new"}),
            media_type="application/json",
        )

    request_id = svc.sanitize_text(str(body.get("request_id") or ""), 64)
    if not request_id:
        raise HTTPException(400, detail="INVALID_INPUT")
    kind = _enum(body.get("kind"), svc.KINDS)
    module = _enum(body.get("module"), svc.MODULES)
    severity_raw = svc.sanitize_text(str(body.get("severity") or ""), 16)
    severity = None
    if severity_raw:
        severity = _enum(severity_raw, svc.SEVERITIES)
    source = _enum(body.get("source") or "manual", svc.SOURCES)
    # title/单行字段 sanitize_line：换行/制表折叠成单空格，
    # 否则导出里一个字段能跨行注入假标题/假元数据。
    title = svc.sanitize_line(str(body.get("title") or ""), 120)
    if not title:
        raise HTTPException(422, detail="INVALID_INPUT")
    text = svc.sanitize_text(str(body.get("body") or ""), 5000)
    if len(text) < 10:
        raise HTTPException(422, detail="INVALID_INPUT")
    image_ids = [svc.sanitize_text(str(v), 64) for v in _str_list(body.get("image_ids"), svc.MAX_IMAGES_PER_ITEM + 1, 64)]
    if len(image_ids) > svc.MAX_IMAGES_PER_ITEM:
        raise HTTPException(422, detail="FEEDBACK_IMAGE_INVALID")

    fields = {
        "request_id": request_id,
        "kind": kind,
        "module": module,
        "severity": severity,
        "title": title,
        "text": text,
        "source": source,
        "reasons": _str_list(body.get("trigger_reasons"), 16, 40) or None,
        "run_id": svc.sanitize_line(str(body.get("run_id") or ""), 64) or None,
        "session_id": svc.sanitize_line(str(body.get("session_id") or ""), 64) or None,
        "page_path": svc.sanitize_line(str(body.get("page_path") or ""), 300),
        "client_build": svc.sanitize_line(str(body.get("client_build") or ""), 64) or None,
        "viewport": svc.sanitize_line(str(body.get("viewport") or ""), 32) or None,
        "locale": svc.sanitize_line(str(body.get("locale") or ""), 16) or None,
        "image_ids": image_ids,
        "captcha": str(body.get("captcha") or "").strip(),
        "user_agent": svc.sanitize_line(request.headers.get("user-agent", ""), 300),
    }
    saved, batch_seq, duplicated = await run_in_threadpool(
        _submit_db, request, db, record, ip, fields
    )
    status = 200 if duplicated else 201
    return Response(
        status_code=status,
        content=json.dumps(_public_item(saved, batch_seq)),
        media_type="application/json",
    )


@router.get("/api/v1/feedback/mine")
def list_mine(
    request: Request,
    limit: int = 20,
    cursor: str = "",
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    limit = max(1, min(limit, 50))
    query = (
        select(FeedbackItem, FeedbackBatch.seq)
        .join(FeedbackBatch, FeedbackItem.batch_id == FeedbackBatch.id)
        .where(FeedbackItem.user_id == record.user_id)
        .order_by(FeedbackItem.created_at.desc(), FeedbackItem.id.desc())
    )
    if cursor:
        # keyset 分页：游标 = 本页最后一条已返回的 id，下页取其 (created_at,id)
        # 之后的行 —— 不全量加载，也不让游标指向 lookahead 那条（会漏一条）。
        cur = db.get(FeedbackItem, cursor)
        if (
            cur is not None
            and cur.user_id == record.user_id
            and cur.created_at is not None
        ):
            query = query.where(
                or_(
                    FeedbackItem.created_at < cur.created_at,
                    and_(
                        FeedbackItem.created_at == cur.created_at,
                        FeedbackItem.id < cur.id,
                    ),
                )
            )
    rows = list(db.execute(query.limit(limit + 1)).all())
    page = rows[:limit]
    next_cursor = page[-1][0].id if len(rows) > limit else None
    out = []
    for item, seq in page:
        images = [
            {"id": img.id, "width": img.width, "height": img.height}
            for img in db.scalars(
                select(FeedbackImage).where(FeedbackImage.item_id == item.id)
            )
        ]
        out.append(_public_item(item, int(seq), images))
    return {"items": out, "next_cursor": next_cursor}


# ---- admin ----------------------------------------------------------------


def _get_batch(db: Session, seq: int) -> FeedbackBatch:
    batch = db.scalars(
        select(FeedbackBatch).where(FeedbackBatch.seq == seq)
    ).first()
    if batch is None:
        raise HTTPException(404, detail="NOT_FOUND")
    return batch


def _batch_summary_public(batch: FeedbackBatch) -> dict[str, object]:
    return {
        "seq": int(batch.seq),
        "label": svc.batch_label(int(batch.seq)),
        "status": batch.status,
        "build_commit": batch.build_commit,
        "capacity": int(batch.capacity or 0),
        "item_count": int(batch.item_count or 0),
        "opened_at": batch.opened_at.isoformat() if batch.opened_at else None,
        "closed_at": batch.closed_at.isoformat() if batch.closed_at else None,
        "summary": batch.summary,
    }


@router.get("/api/v1/admin/feedback/batches")
def admin_batches(request: Request, db: Session = Depends(db_session)) -> dict:
    record = current_record(request)
    _admin(request, db, record)
    batches = list(
        db.scalars(select(FeedbackBatch).order_by(FeedbackBatch.seq.desc()))
    )
    return {"batches": [_batch_summary_public(b) for b in batches]}


@router.get("/api/v1/admin/feedback/batches/{seq}")
def admin_batch_detail(
    seq: int, request: Request, db: Session = Depends(db_session)
) -> dict:
    record = current_record(request)
    _admin(request, db, record)
    batch = _get_batch(db, seq)
    payload = batch_payload(db, batch)
    groups: dict[str, list[dict]] = {}
    for item in payload["items"]:  # type: ignore[index]
        groups.setdefault(str(item["module"]), []).append(item)
    return {
        **_batch_summary_public(batch),
        "groups": groups,
        "items": payload["items"],
    }


@router.get("/api/v1/admin/feedback/batches/{seq}/export")
def admin_batch_export(
    seq: int,
    request: Request,
    format: str = "md",
    db: Session = Depends(db_session),
):
    record = current_record(request)
    _admin(request, db, record)
    batch = _get_batch(db, seq)
    payload = batch_payload(db, batch)
    label = svc.batch_label(seq)
    if format == "json":
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{label}.json"'
            },
        )
    if format != "md":
        raise HTTPException(422, detail="INVALID_INPUT")
    return Response(
        content=export_markdown(payload),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{label}.md"'},
    )


@router.post("/api/v1/admin/feedback/batches/{seq}/close")
def admin_batch_close(
    seq: int, request: Request, db: Session = Depends(db_session)
) -> dict:
    require_write(request)
    record = current_record(request)
    _admin(request, db, record)
    batch = _get_batch(db, seq)
    if batch.status != "open":
        raise HTTPException(409, detail="BATCH_CLOSED")
    svc.close_batch(db, batch)
    db.flush()
    return _batch_summary_public(batch)


def _patch_item_db(
    request: Request, db: Session, record: AuthRecord, item_id: str, state: str
) -> dict:
    _admin(request, db, record)
    item = db.get(FeedbackItem, item_id)
    if item is None:
        raise HTTPException(404, detail="NOT_FOUND")
    item.state = state
    db.flush()
    seq = db.scalar(
        select(FeedbackBatch.seq).where(FeedbackBatch.id == item.batch_id)
    ) or 0
    return _public_item(item, int(seq))


@router.patch("/api/v1/admin/feedback/items/{item_id}")
async def admin_patch_item(
    item_id: str, request: Request, db: Session = Depends(db_session)
) -> dict:
    require_write(request)
    record = current_record(request)
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, detail="INVALID_INPUT") from None
    if not isinstance(body, dict):
        raise HTTPException(400, detail="INVALID_INPUT")
    state = _enum(body.get("state"), svc.STATES)
    return await run_in_threadpool(_patch_item_db, request, db, record, item_id, state)
