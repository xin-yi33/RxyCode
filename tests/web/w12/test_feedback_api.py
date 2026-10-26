"""Feedback API module tests — pg-backed.

Covers: happy path + image binding, request_id idempotency, 24h content
dedupe, honeypot fake-success, independent per-user/per-IP windows, daily
cap, ALTCHA escalation, tenant isolation, staged-image lifecycle, batch
rolling (capacity + build_commit) with summary, concurrency safety, admin
gating, markdown export, /me.feedback_admin.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from tests.web.w12.conftest import ORIGIN, SECRET
from tests.web.w9.test_auth import _solve_captcha

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker"):
    _path = REPO / "packages" / _name / "src"
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.main import create_app
from rxycode_server.persistence.models import (
    FeedbackBatch,
    FeedbackImage,
    FeedbackItem,
    Invite,
    Run,
    SessionRow,
    User,
)
from rxycode_server.api.auth import invite_digest


def _app(postgres_url: str, **kwargs):
    return create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        **kwargs,
    )


def _csrf(client: TestClient) -> str:
    return client.get("/api/v1/auth/csrf").json()["csrf_token"]


def _headers(token: str, **extra) -> dict[str, str]:
    return {"X-CSRF-Token": token, "Origin": ORIGIN, **extra}


def _client(postgres_url: str, email: str, *, app=None) -> tuple[TestClient, dict]:
    code = "w12-" + uuid.uuid4().hex[:12]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(Invite(code_hash=invite_digest(code), max_uses=1, used=0, note="w12"))
        db.commit()
    engine.dispose()
    if app is None:
        app = _app(postgres_url)
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "invite_code": code,
            "captcha": _solve_captcha(client),
        },
        headers=_headers(_csrf(client)),
    )
    assert response.status_code == 201, response.text
    return client, response.json()


def _png(size=(6, 6), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _submit_body(**over) -> dict:
    body = {
        "request_id": uuid.uuid4().hex,
        "kind": "bug",
        "module": "chat",
        "title": "页面白屏",
        # 24h 内容去重是同用户同文 —— 多提交场景的测试需要唯一正文。
        "body": f"打开会话列表后整个页面白屏，控制台报错。{uuid.uuid4().hex[:8]}",
        "page_path": "/app",
    }
    body.update(over)
    return body


def _submit(client: TestClient, body: dict, **extra_headers):
    return client.post("/api/v1/feedback", json=body, headers=_headers(_csrf(client), **extra_headers))


def _upload(client: TestClient, raw: bytes, ctype="application/octet-stream"):
    return client.post(
        "/api/v1/feedback/images",
        content=raw,
        headers=_headers(_csrf(client), **{"Content-Type": ctype}),
    )


# ---- happy path + image lifecycle ------------------------------------------


def test_happy_path_with_image_and_batch(postgres_url: str):
    client, _me = _client(postgres_url, "fb-a@example.com")
    up = _upload(client, _png())
    assert up.status_code == 201, up.text
    image_id = up.json()["image_id"]

    response = _submit(client, _submit_body(image_ids=[image_id]))
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["id"] and item["batch_seq"] == 1 and item["state"] == "new"

    engine = create_engine(postgres_url)
    with Session(engine) as db:
        row = db.get(FeedbackImage, image_id)
        assert row.state == "bound" and row.item_id == item["id"]
        saved = db.get(FeedbackItem, item["id"])
        batch = db.get(FeedbackBatch, saved.batch_id)
        assert batch.seq == 1 and batch.item_count == 1 and batch.status == "open"
    engine.dispose()

    mine = client.get("/api/v1/feedback/mine")
    assert mine.status_code == 200
    assert mine.json()["items"][0]["id"] == item["id"]
    assert mine.json()["items"][0]["images"][0]["id"] == image_id


def test_image_get_owner_and_delete(postgres_url: str):
    client, _me = _client(postgres_url, "fb-img@example.com")
    other, _ = _client(postgres_url, "fb-img2@example.com")
    image_id = _upload(client, _png()).json()["image_id"]

    got = client.get(f"/api/v1/feedback/images/{image_id}")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in got.headers["content-security-policy"]

    # 其他用户不可见（404，不泄露存在）。
    assert other.get(f"/api/v1/feedback/images/{image_id}").status_code == 404
    assert other.delete(
        f"/api/v1/feedback/images/{image_id}", headers=_headers(_csrf(other))
    ).status_code == 404

    deleted = client.delete(
        f"/api/v1/feedback/images/{image_id}", headers=_headers(_csrf(client))
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/feedback/images/{image_id}").status_code == 404


def test_image_type_and_size_gates(postgres_url: str):
    client, _me = _client(postgres_url, "fb-type@example.com")
    assert _upload(client, b"GIF89a" + b"\x00" * 64).status_code == 415
    assert _upload(client, b"<svg></svg>").status_code == 415
    assert _upload(client, b"").status_code == 415
    huge = client.post(
        "/api/v1/feedback/images",
        content=b"x" * (5 * 1024 * 1024 + 8),
        headers=_headers(_csrf(client), **{"Content-Type": "application/octet-stream"}),
    )
    assert huge.status_code == 413


def test_foreign_and_expired_images_rejected(postgres_url: str):
    client, _ = _client(postgres_url, "fb-own@example.com")
    other, _ = _client(postgres_url, "fb-own2@example.com")
    foreign_id = _upload(other, _png()).json()["image_id"]
    assert _submit(client, _submit_body(image_ids=[foreign_id])).status_code == 422

    mine_id = _upload(client, _png()).json()["image_id"]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        from datetime import datetime, timedelta, timezone

        db.get(FeedbackImage, mine_id).expires_at = datetime.now(timezone.utc) - timedelta(
            hours=1
        )
        db.commit()
    engine.dispose()
    assert _submit(client, _submit_body(image_ids=[mine_id])).status_code == 422


def test_staged_image_quota(postgres_url: str):
    client, _ = _client(postgres_url, "fb-quota@example.com")
    for _ in range(10):
        assert _upload(client, _png()).status_code == 201
    assert _upload(client, _png()).status_code == 429


# ---- idempotency / dedupe / honeypot ----------------------------------------


def test_request_id_idempotent(postgres_url: str):
    client, _ = _client(postgres_url, "fb-idem@example.com")
    body = _submit_body()
    first = _submit(client, body)
    second = _submit(client, body)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        assert db.scalar(select(text("count(*)")).select_from(text("feedback_items"))) == 1
    engine.dispose()


def test_content_dedupe_24h(postgres_url: str):
    client, _ = _client(postgres_url, "fb-dedupe@example.com")
    assert _submit(client, _submit_body(body="The app   CRASHED\n on load")).status_code == 201
    # 规范化后同文（大小写 + 空白折叠）→ 409，即使 request_id 不同。
    response = _submit(client, _submit_body(body="the app crashed on load"))
    assert response.status_code == 409
    assert response.json()["code"] == "FEEDBACK_DUPLICATE"


def test_honeypot_fake_success(postgres_url: str):
    client, _ = _client(postgres_url, "fb-honey@example.com")
    response = _submit(client, _submit_body(website="http://spam.example"))
    assert response.status_code == 201
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        assert db.scalar(select(text("count(*)")).select_from(text("feedback_items"))) == 0
    engine.dispose()


# ---- rate limits ------------------------------------------------------------


def test_per_user_submit_window(postgres_url: str):
    client, _ = _client(postgres_url, "fb-rate@example.com")
    import rxycode_server.feedback.service as svc

    original = svc.CAPTCHA_ESCALATE_COUNT
    svc.CAPTCHA_ESCALATE_COUNT = 10_000  # 只测窗口，不触发 captcha 升级
    try:
        results = [_submit(client, _submit_body()).status_code for _ in range(6)]
    finally:
        svc.CAPTCHA_ESCALATE_COUNT = original
    assert results[:5] == [201] * 5
    assert results[5] == 429


def test_per_ip_independent_bucket(postgres_url: str):
    """per-IP 桶独立于 per-user：放宽用户桶后，同 IP 多用户仍吃 IP 上限。"""
    app = _app(postgres_url)
    clients = [_client(postgres_url, f"fb-ip{i}@example.com", app=app)[0] for i in range(2)]
    limiter = app.state.feedback_rate
    limiter.submit_user.limit = 10_000
    import rxycode_server.feedback.service as svc

    original = svc.CAPTCHA_ESCALATE_COUNT
    svc.CAPTCHA_ESCALATE_COUNT = 10_000
    try:
        codes = []
        for i in range(22):
            codes.append(_submit(clients[i % 2], _submit_body()).status_code)
    finally:
        svc.CAPTCHA_ESCALATE_COUNT = original
    assert codes[:20] == [201] * 20
    assert 429 in codes[20:]


def test_image_windows(postgres_url: str):
    client, _ = _client(postgres_url, "fb-imgr@example.com")
    import rxycode_server.feedback.service as svc

    original = svc.STAGED_IMAGE_LIMIT
    svc.STAGED_IMAGE_LIMIT = 100  # 先放宽行数上限，单独看上传窗口
    try:
        for _ in range(20):
            assert _upload(client, _png()).status_code == 201
        # 已用 20 次 → 下一发命中 per-user 图片窗口。
        assert _upload(client, _png()).status_code == 429
    finally:
        svc.STAGED_IMAGE_LIMIT = original


def test_daily_user_cap(postgres_url: str):
    client, _ = _client(postgres_url, "fb-daily@example.com")
    import rxycode_server.feedback.service as svc

    original = svc.DAILY_USER_LIMIT
    svc.DAILY_USER_LIMIT = 2
    try:
        assert _submit(client, _submit_body()).status_code == 201
        assert _submit(client, _submit_body()).status_code == 201
        assert _submit(client, _submit_body()).status_code == 429
    finally:
        svc.DAILY_USER_LIMIT = original


def test_captcha_escalation(postgres_url: str):
    client, _ = _client(postgres_url, "fb-cap@example.com")
    import rxycode_server.feedback.service as svc

    original = svc.CAPTCHA_ESCALATE_COUNT
    svc.CAPTCHA_ESCALATE_COUNT = 2
    try:
        assert _submit(client, _submit_body()).status_code == 201
        assert _submit(client, _submit_body()).status_code == 201
        third = _submit(client, _submit_body())
        assert third.status_code == 400
        assert third.json()["code"] == "CAPTCHA_REQUIRED"
        body = _submit_body(captcha=_solve_captcha(client))
        assert _submit(client, body).status_code == 201
    finally:
        svc.CAPTCHA_ESCALATE_COUNT = original


# ---- tenant / validation ------------------------------------------------------


def test_cross_tenant_run_404(postgres_url: str):
    client, _ = _client(postgres_url, "fb-t1@example.com")
    _other, other_me = _client(postgres_url, "fb-t2@example.com")
    other_tenant = other_me["organization"]["tenant_id"]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        project_id = db.scalar(
            text("SELECT id FROM projects WHERE tenant_id = :t"), {"t": other_tenant}
        )
        session_id = "s_" + uuid.uuid4().hex[:20]
        db.add(
            SessionRow(
                id=session_id,
                tenant_id=other_tenant,
                project_id=project_id,
                title="x",
            )
        )
        run_id = "r_" + uuid.uuid4().hex[:20]
        db.add(
            Run(
                id=run_id,
                tenant_id=other_tenant,
                session_id=session_id,
                status="succeeded",
                request_id=uuid.uuid4().hex,
            )
        )
        db.commit()
    engine.dispose()
    # 同 tenant 资源才允许带；他 tenant 的 run/session 一律 404。
    assert _submit(client, _submit_body(run_id=run_id)).status_code == 404
    assert _submit(client, _submit_body(session_id=session_id)).status_code == 404
    assert _submit(client, _submit_body(run_id="nonexistent")).status_code == 404
    # 本人 tenant 的 run 可以通过 —— 拿上面的 session/run 在 other 下验证。
    ok = _submit(_other, _submit_body(run_id=run_id, session_id=session_id))
    assert ok.status_code == 201


def test_validation(postgres_url: str):
    client, _ = _client(postgres_url, "fb-val@example.com")
    assert _submit(client, _submit_body(kind="nope")).status_code == 422
    assert _submit(client, _submit_body(title="")).status_code == 422
    assert _submit(client, _submit_body(body="短")).status_code == 422
    assert _submit(client, _submit_body(request_id="")).status_code == 400


# ---- batch rolling + summary + concurrency ------------------------------------


def test_batch_rolls_on_capacity_and_build(postgres_url: str, monkeypatch):
    import rxycode_server.feedback.service as svc

    monkeypatch.setenv("RXYCODE_FEEDBACK_BATCH_SIZE", "3")
    client, _ = _client(postgres_url, "fb-roll@example.com")
    app = client.app
    limiter = app.state.feedback_rate
    limiter.submit_user.limit = 10_000
    limiter.submit_ip.limit = 10_000
    original_escalate = svc.CAPTCHA_ESCALATE_COUNT
    svc.CAPTCHA_ESCALATE_COUNT = 10_000

    for _ in range(4):
        assert _submit(client, _submit_body()).status_code == 201

    engine = create_engine(postgres_url)
    with Session(engine) as db:
        batches = list(db.scalars(select(FeedbackBatch).order_by(FeedbackBatch.seq)))
        assert len(batches) == 2
        assert batches[0].status == "closed" and batches[0].item_count == 3
        assert batches[0].summary["items"] == 3
        assert batches[0].summary["by_kind"]["bug"] == 3
        assert batches[1].status == "open" and batches[1].item_count == 1

        # 新部署（build_commit 变化）→ 下一单滚批。
        batches[1].build_commit = "oldcommit"
        db.commit()
    engine.dispose()

    assert _submit(client, _submit_body()).status_code == 201
    svc.CAPTCHA_ESCALATE_COUNT = original_escalate
    with Session(engine) as db:
        batches = list(db.scalars(select(FeedbackBatch).order_by(FeedbackBatch.seq)))
        assert len(batches) == 3
        assert batches[1].status == "closed"
        assert batches[2].status == "open" and batches[2].item_count == 1
    engine.dispose()


def test_batch_concurrent_rolls(postgres_url: str, monkeypatch):
    """30 并发提交、容量 10 → 恰好 3 批各 10 条且只有一个 open。"""
    monkeypatch.setenv("RXYCODE_FEEDBACK_BATCH_SIZE", "10")
    app = _app(postgres_url)
    limiter = app.state.feedback_rate
    limiter.submit_user.limit = 10_000
    limiter.submit_ip.limit = 10_000
    limiter.image_user.limit = 10_000
    limiter.image_ip.limit = 10_000
    import rxycode_server.feedback.service as svc

    original_daily, original_global = svc.DAILY_USER_LIMIT, svc.GLOBAL_WINDOW_LIMIT
    original_escalate = svc.CAPTCHA_ESCALATE_COUNT
    svc.DAILY_USER_LIMIT, svc.GLOBAL_WINDOW_LIMIT = 10_000, 10_000
    svc.CAPTCHA_ESCALATE_COUNT = 10_000
    app.state.auth_rate.register_hour.limit = 10_000  # 6 个注册会踩 5/h
    clients = [_client(postgres_url, f"fb-c{i}@example.com", app=app)[0] for i in range(6)]
    errors: list[Exception] = []
    results: list[int] = []

    def send(index: int) -> None:
        try:
            results.append(_submit(clients[index % len(clients)], _submit_body()).status_code)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    try:
        threads = [threading.Thread(target=send, args=(i,)) for i in range(30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        svc.DAILY_USER_LIMIT, svc.GLOBAL_WINDOW_LIMIT = original_daily, original_global
        svc.CAPTCHA_ESCALATE_COUNT = original_escalate

    assert not errors
    assert sorted(results) == [201] * 30
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        batches = list(db.scalars(select(FeedbackBatch).order_by(FeedbackBatch.seq)))
        assert [b.item_count for b in batches] == [10, 10, 10]
        assert sum(1 for b in batches if b.status == "open") == 1
        assert db.scalar(select(text("count(*)")).select_from(text("feedback_items"))) == 30
    engine.dispose()


# ---- admin --------------------------------------------------------------------


def test_me_feedback_admin(postgres_url: str, monkeypatch):
    monkeypatch.setenv("RXYCODE_FEEDBACK_ADMIN_EMAILS", "boss@example.com")
    boss, _ = _client(postgres_url, "boss@example.com")
    plain, _ = _client(postgres_url, "plain@example.com")
    assert boss.get("/api/v1/me").json()["feedback_admin"] is True
    assert plain.get("/api/v1/me").json()["feedback_admin"] is False


def test_admin_endpoints_and_export(postgres_url: str, monkeypatch):
    monkeypatch.setenv("RXYCODE_FEEDBACK_ADMIN_EMAILS", "boss@example.com")
    boss, _ = _client(postgres_url, "boss@example.com")
    plain, _ = _client(postgres_url, "plain@example.com")
    _submit(plain, _submit_body(body="反馈正文不可信 ```fence``` 注入尝试", title="注入"))

    # 非 admin：全部 404。
    assert plain.get("/api/v1/admin/feedback/batches").status_code == 404
    assert plain.get("/api/v1/admin/feedback/batches/1").status_code == 404
    assert plain.get("/api/v1/admin/feedback/batches/1/export").status_code == 404

    batches = boss.get("/api/v1/admin/feedback/batches")
    assert batches.status_code == 200
    assert batches.json()["batches"][0]["label"] == "FB-0001"

    detail = boss.get("/api/v1/admin/feedback/batches/1")
    assert detail.status_code == 200
    assert "chat" in detail.json()["groups"]

    md = boss.get("/api/v1/admin/feedback/batches/1/export?format=md")
    assert md.status_code == 200
    assert "attachment" in md.headers["content-disposition"]
    assert "```text" in md.text and "不可信输入" in md.text
    assert "```fence" not in md.text  # 正文反引号已转义

    payload = boss.get("/api/v1/admin/feedback/batches/1/export?format=json")
    assert payload.status_code == 200
    assert payload.json()["batch"] == "FB-0001"

    item_id = detail.json()["items"][0]["id"]
    patched = boss.patch(
        f"/api/v1/admin/feedback/items/{item_id}",
        json={"state": "triaged"},
        headers=_headers(_csrf(boss)),
    )
    assert patched.status_code == 200 and patched.json()["state"] == "triaged"

    closed = boss.post(
        "/api/v1/admin/feedback/batches/1/close", headers=_headers(_csrf(boss))
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["summary"]["items"] == 1


def test_admin_image_read(postgres_url: str, monkeypatch):
    monkeypatch.setenv("RXYCODE_FEEDBACK_ADMIN_EMAILS", "boss@example.com")
    boss, _ = _client(postgres_url, "boss@example.com")
    plain, _ = _client(postgres_url, "plain@example.com")
    image_id = _upload(plain, _png()).json()["image_id"]
    assert boss.get(f"/api/v1/feedback/images/{image_id}").status_code == 200


# ---- migration -----------------------------------------------------------------


def test_migration_downgrade_upgrade(postgres_url: str):
    from tests.support.pgurl import reset_schema
    from sqlalchemy import inspect as sa_inspect

    from alembic import command
    from alembic.config import Config

    reset_schema(postgres_url, migrate=True)
    engine = create_engine(postgres_url)
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO / "packages" / "rxycode-server" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.downgrade(cfg, "012_files_batch")
    names = set(sa_inspect(engine).get_table_names())
    assert "feedback_items" not in names
    command.upgrade(cfg, "head")
    names = set(sa_inspect(engine).get_table_names())
    assert {"feedback_batches", "feedback_items", "feedback_images"} <= names
    engine.dispose()


def _seed_items(postgres_url: str, user_id: str, tenant_id: str, count: int) -> None:
    """直接插行（绕过内存窗/端点）——构造并发升级场景的基线计数。"""
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        seq = db.scalar(text("SELECT COALESCE(MAX(seq), 0) FROM feedback_batches")) or 0
        batch = FeedbackBatch(
            id=uuid.uuid4().hex,
            seq=int(seq) + 1,
            status="closed",
            build_commit="seed",
            capacity=20,
            item_count=count,
            opened_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        for _ in range(count):
            db.add(
                FeedbackItem(
                    id=uuid.uuid4().hex,
                    batch_id=batch.id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    request_id=uuid.uuid4().hex,
                    kind="bug",
                    module="chat",
                    title="seed",
                    body="seeded feedback row " + uuid.uuid4().hex[:8],
                    source="manual",
                    content_sha256=uuid.uuid4().hex,
                    ip_hmac="",
                    state="new",
                    created_at=datetime.now(timezone.utc),
                )
            )
        db.commit()
    engine.dispose()


def test_captcha_escalation_is_serialized(postgres_url: str):
    """并发绕过验证码升级：DB 里已有 2 条（锁外计数 <3 都放行），
    4 个线程无 captcha 并发 —— 锁内复查后恰 1 个 201、其余 400。"""
    client, me = _client(postgres_url, "fb-caprace@example.com")
    user_id = me["user"]["id"]
    tenant_id = me["organization"]["tenant_id"]
    _seed_items(postgres_url, user_id, tenant_id, 2)

    results: list[int] = []
    errors: list[Exception] = []

    def send() -> None:
        try:
            results.append(_submit(client, _submit_body()).status_code)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=send) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert sorted(results) == [201, 400, 400, 400]
    cap = _submit(client, _submit_body(captcha=_solve_captcha(client)))
    assert cap.status_code == 201, cap.text


def test_expired_staged_sweep_deletes_blob_and_row(postgres_url: str):
    """过期 staged：sweep 后 blob 与行都不存在 —— 不能只改 state 留孤儿。"""
    app = _app(postgres_url)
    client, _ = _client(postgres_url, "fb-sweep@example.com", app=app)
    resp = _upload(client, _png())
    assert resp.status_code == 201
    image_id = resp.json()["image_id"]

    engine = create_engine(postgres_url)
    with Session(engine) as db:
        row = db.get(FeedbackImage, image_id)
        assert row is not None
        blob_key = row.blob_key
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        # 上传触发的全局清扫等价物 —— 直接调服务层验证语义。
        from rxycode_server.attachments.store import open_store
        import rxycode_server.feedback.service as svc

        store = open_store(app.state.attachment_blobs)
        swept = svc.sweep_expired_images(db, store)
        assert swept == 1
        db.commit()

        assert db.get(FeedbackImage, image_id) is None
        with pytest.raises(FileNotFoundError):
            with store.open_read(blob_key):
                pass
    engine.dispose()
