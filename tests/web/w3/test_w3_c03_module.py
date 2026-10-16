"""WEB-W3-C03. Reloading the chat keeps the server tool failure, approval, and answer."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from rxycode_server.events.store import append_event, prune_through  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Membership,
    Project,
    SessionRow,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402

_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)

CHAT = REPO / "apps" / "web" / "src" / "features" / "chat" / "ChatPage.tsx"


def _seed() -> tuple[str, str]:
    engine = create_engine(_c02.URL)
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.kind == "local")).one()
        tenant_id = db.scalars(
            select(Membership.tenant_id).where(Membership.user_id == user.id)
        ).one()
        project_id = uuid.uuid4().hex
        session_id = uuid.uuid4().hex
        db.add(Project(id=project_id, tenant_id=tenant_id, name="chat", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id=tenant_id,
                project_id=project_id,
                title="chat",
            )
        )
        db.commit()
    engine.dispose()
    created = create_run(
        _c02.URL,
        tenant_id=tenant_id,
        session_id=session_id,
        message="show the run",
        target_id="local:c03",
        permission_profile="workspace-write",
        request_id="req-c03-chat",
    )
    run_id = created.run_id
    append_event(
        _c02.URL,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="tool.failed",
        payload={"call_id": "call-1", "tool": "shell.exec", "error": "exit 1"},
    )
    append_event(
        _c02.URL,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="assistant.delta",
        payload={"text": "hidden reasoning", "intermediate": True},
    )
    append_event(
        _c02.URL,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="assistant.final",
        payload={"text": "final user answer"},
    )
    append_event(
        _c02.URL,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="approval.requested",
        payload={"approval_id": "appr-1", "tool": "shell.exec"},
    )
    return tenant_id, run_id


def _expect_run(page) -> None:
    tool = page.locator("[data-tool-id='call-1']")
    expect(tool).to_contain_text("shell.exec", timeout=10000)
    expect(tool).to_contain_text("失败")
    expect(tool).not_to_contain_text("成功")
    expect(page.locator("[data-approval-id='appr-1']")).to_contain_text("等待审批")
    answer = page.locator("[data-answer]")
    expect(answer).to_have_text("final user answer")
    expect(answer).not_to_contain_text("hidden reasoning")
    expect(page.locator("[data-run-status='pending']")).to_be_visible()


def test_w3_c03_integration() -> None:
    """Reload shows the same server tool failure, approval, and final answer."""
    assert CHAT.is_file(), "ChatPage.tsx is missing"
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            _tenant, run_id = _seed()
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            _expect_run(page)
            page.reload(wait_until="domcontentloaded")
            _expect_run(page)
            prune_through(_c02.URL, tenant_id=_tenant, run_id=run_id, through_seq=1)
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            expect(page.get_by_role("alert")).to_contain_text("重新同步", timeout=10000)
            expect(page.locator("[data-answer]")).to_have_count(0)
            browser.close()
    finally:
        stack.close()
