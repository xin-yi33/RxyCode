"""WEB-W6-C05. Usage totals match the ledger. Another tenant sees nothing."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from tests.support.pgurl import ensure_container, worker_url

_PG_BASE = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"
ensure_container("rxy-w2c01-pg", 55432)
DATABASE = worker_url(_PG_BASE)
SECRET = "local-web-secret-value-32bytes!!"
ORIGIN = "http://test.example"


async def test_w6_c05_contract() -> None:
    """Two runs open as one usage statement. Tokens and cost match the ledger."""
    from rxycode_server.notifications.service import read_usage
    from rxycode_server.usage.service import record_terminal_usage

    tenant = "ten-w6c05-" + uuid.uuid4().hex[:8]
    ids = _seed(tenant)
    try:
        first = record_terminal_usage(
            DATABASE,
            tenant_id=tenant,
            run_id=ids["run_a"],
            model_id="model-a",
            price_version="2026-10",
            tokens=100,
            event_id="evt-" + ids["run_a"],
        )
        second = record_terminal_usage(
            DATABASE,
            tenant_id=tenant,
            run_id=ids["run_b"],
            model_id="model-b",
            price_version="2026-10",
            tokens=50,
            event_id="evt-" + ids["run_b"],
        )
        draft = record_terminal_usage(
            DATABASE,
            tenant_id=tenant,
            run_id=ids["run_b"],
            model_id="model-b",
            price_version="draft",
            tokens=10,
            event_id="evt-draft-" + ids["run_b"],
        )
        statement = read_usage(_get(_session(tenant, ids["token"]), ids["token"]))
        assert statement["tokens"] == first["tokens"] + second["tokens"] + draft["tokens"]
        assert Decimal(str(statement["amount"])) == (
            Decimal(str(first["amount"])) + Decimal(str(second["amount"])) + Decimal(str(draft["amount"]))
        )
        narrowed = read_usage(_get(_session(tenant, ids["token"]), ids["token"], {"model_id": "model-a"}))
        assert narrowed["tokens"] == first["tokens"]
        assert {line["cost_kind"] for line in statement["lines"]} == {"confirmed", "estimate"}
        today = datetime.now(timezone.utc).date().isoformat()
        today_only = read_usage(_get(_session(tenant, ids["token"]), ids["token"], {"day": today}))
        assert today_only["tokens"] == statement["tokens"]
        empty = read_usage(_get(_session(tenant, ids["token"]), ids["token"], {"day": "1999-01-01"}))
        assert empty["tokens"] == 0
        assert empty["lines"] == []
    finally:
        _wipe(tenant, ids)


async def test_w6_c05_negative() -> None:
    """Tenant B cannot read or delete tenant A's memory or notifications."""
    from rxycode_server.notifications.service import (
        ScheduleForbidden,
        create_web_schedule,
        delete_memory,
        list_memory,
        list_notifications,
        put_memory,
        unsubscribe,
    )
    from rxycode_server.runs.service import complete_run

    tenant_a = "ten-w6c05a-" + uuid.uuid4().hex[:8]
    tenant_b = "ten-w6c05b-" + uuid.uuid4().hex[:8]
    ids_a = _seed(tenant_a)
    ids_b = _seed(tenant_b)
    secret = "secret-memory-" + uuid.uuid4().hex
    try:
        saved = await put_memory(
            ids_a["project"],
            _write(_session(tenant_a, ids_a["token"]), ids_a["token"], {"body": secret}),
        )
        complete_run(DATABASE, tenant_id=tenant_a, run_id=ids_a["run_a"], user_id="user-a")
        leaked = list_memory(ids_a["project"], _get(_session(tenant_b, ids_b["token"]), ids_b["token"]))
        notes = list_notifications(_get(_session(tenant_b, ids_b["token"]), ids_b["token"]))
        blob = str(leaked) + str(notes)
        assert secret not in blob
        assert leaked["memories"] == []
        delete_memory(
            ids_a["project"],
            saved["id"],
            _write(_session(tenant_b, ids_b["token"]), ids_b["token"], {}),
        )
        still = list_memory(ids_a["project"], _get(_session(tenant_a, ids_a["token"]), ids_a["token"]))
        assert any(item["body"] == secret for item in still["memories"])
        await unsubscribe(_write(_session(tenant_a, ids_a["token"]), ids_a["token"], {"kind": "run.completed"}))
        complete_run(DATABASE, tenant_id=tenant_a, run_id=ids_a["run_b"], user_id="user-a")
        blocked = False
        try:
            create_web_schedule(
                DATABASE,
                tenant_id=tenant_b,
                project_id=ids_a["project"],
                session_id=ids_a["session_a"],
                rule={"kind": "interval", "every": 1, "unit": "minutes"},
                now=datetime(2026, 10, 16, 12, 0, 0),
                user_id="user-b",
            )
        except ScheduleForbidden:
            blocked = True
        assert blocked
        own = list_notifications(_get(_session(tenant_a, ids_a["token"]), ids_a["token"]))
        assert any(item["run_id"] == ids_a["run_a"] for item in own["notifications"])
        assert all(item["run_id"] != ids_a["run_b"] for item in own["notifications"])
        foreign = list_notifications(_get(_session(tenant_b, ids_b["token"]), ids_b["token"]))
        assert secret not in str(foreign)
        assert all(item["tenant_id"] == tenant_b for item in foreign["notifications"])
    finally:
        _wipe(tenant_a, ids_a)
        _wipe(tenant_b, ids_b)


def _seed(tenant: str) -> dict[str, str]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import Organization, Project, Run, SessionRow

    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(DATABASE)
    suffix = uuid.uuid4().hex[:8]
    ids = {
        "org": "org-" + suffix,
        "project": "prj-" + suffix,
        "session_a": "ses-a-" + suffix,
        "session_b": "ses-b-" + suffix,
        "run_a": "run-a-" + suffix,
        "run_b": "run-b-" + suffix,
        "token": "tok-" + suffix,
    }
    engine = create_engine(DATABASE, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(Organization(id=ids["org"], tenant_id=tenant))
            db.add(Project(id=ids["project"], tenant_id=tenant, name="c05-" + suffix, repo_config={}))
            db.add(SessionRow(id=ids["session_a"], tenant_id=tenant, project_id=ids["project"], title="a"))
            db.add(SessionRow(id=ids["session_b"], tenant_id=tenant, project_id=ids["project"], title="b"))
            for key, session_id in (("run_a", ids["session_a"]), ("run_b", ids["session_b"])):
                db.add(
                    Run(
                        id=ids[key],
                        tenant_id=tenant,
                        session_id=session_id,
                        status="succeeded",
                        revision=0,
                        lease_epoch=0,
                        request_id="req-" + ids[key],
                        input_digest="",
                        event_seq=0,
                        target_id="",
                    )
                )
            db.commit()
    finally:
        engine.dispose()
    return ids


def _wipe(tenant: str, ids: dict[str, str]) -> None:
    from sqlalchemy import create_engine, delete, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import Organization, Outbox, Project, Run, RunEvent, SessionRow, UsageRecord

    engine = create_engine(DATABASE, poolclass=NullPool)
    try:
        with Session(engine) as db:
            for table in ("web_notifications", "web_unsubscribes", "web_memories", "web_schedules"):
                db.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tenant"), {"tenant": tenant})
            run_ids = [row.id for row in db.query(Run.id).filter(Run.tenant_id == tenant).all()]
            if run_ids:
                event_ids = [
                    row.event_id
                    for row in db.query(RunEvent).filter(RunEvent.run_id.in_(run_ids)).all()
                ]
                if event_ids:
                    db.query(Outbox).filter(Outbox.event_id.in_(event_ids)).delete(synchronize_session=False)
                db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
                db.execute(delete(UsageRecord).where(UsageRecord.run_id.in_(run_ids)))
                db.execute(delete(Run).where(Run.id.in_(run_ids)))
            db.execute(delete(SessionRow).where(SessionRow.tenant_id == tenant))
            db.execute(delete(Project).where(Project.tenant_id == tenant))
            db.execute(delete(Organization).where(Organization.tenant_id == tenant))
            db.commit()
    finally:
        engine.dispose()


def _session(tenant: str, token: str) -> object:
    import time

    from rxycode_server.api.auth import AuthRecord, _hash_token

    app = type("App", (), {})()
    app.state = type("State", (), {})()
    app.state.database_url = DATABASE
    app.state.allowed_origins = (ORIGIN,)
    app.state.secret = SECRET
    app.state.sessions = {}
    user = "user-b" if tenant.startswith("ten-w6c05b-") else "user-a"
    app.state.sessions[_hash_token(SECRET, token)] = AuthRecord(user, tenant, time.monotonic())
    return app


def _get(app: object, token: str, query: dict[str, str] | None = None):
    return _request("GET", app, token, {}, query or {})


def _write(app: object, token: str, body: dict[str, object]):
    return _request("POST", app, token, body, {})


def _request(method: str, app: object, token: str, body: dict[str, object], query: dict[str, str]):
    import json
    from urllib.parse import urlencode

    from starlette.requests import Request

    payload = json.dumps(body).encode("utf-8")
    query_string = urlencode(query).encode("ascii")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": query_string,
        "headers": [
            (b"origin", ORIGIN.encode("ascii")),
            (b"x-csrf-token", b"csrf-token"),
            (b"cookie", f"rxy_session={token}; rxy_csrf=csrf-token".encode("ascii")),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "app": app,
    }
    return Request(scope, receive)
