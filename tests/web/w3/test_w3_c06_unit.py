"""WEB-W3-C06. The approval card shows the real ask, and an expired one conflicts."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
CARD = REPO / "apps" / "web" / "src" / "features" / "approvals" / "ApprovalCard.tsx"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _path in (_SERVER, _WORKER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_UNIT = Path(__file__).with_name("test_w3_c02_unit.py")
_spec = importlib.util.spec_from_file_location("w3c02_stack_c06", _UNIT)
assert _spec is not None and _spec.loader is not None
_c02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c02)

from rxycode_server.approvals.service import request_approval  # noqa: E402
from rxycode_server.persistence.models import Approval, Membership, Project, SessionRow, User  # noqa: E402
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_worker.supervisor import claim  # noqa: E402


def _seed(deadline: datetime) -> tuple[str, str]:
    engine = create_engine(_c02.URL)
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.kind == "local")).one()
        tenant_id = db.scalars(
            select(Membership.tenant_id).where(Membership.user_id == user.id)
        ).one()
        project_id = uuid.uuid4().hex
        session_id = uuid.uuid4().hex
        db.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name="c06",
                repo_config={},
            )
        )
        db.add(
            SessionRow(
                id=session_id,
                tenant_id=tenant_id,
                project_id=project_id,
                title="approve",
            )
        )
        db.commit()
    engine.dispose()
    created = create_run(
        _c02.URL,
        tenant_id=tenant_id,
        session_id=session_id,
        message="needs approval",
        target_id="local:c06",
        permission_profile="confirm_all",
        request_id="req-" + uuid.uuid4().hex,
    )
    epoch = claim(_c02.URL, created.run_id, "worker-c06")
    assert epoch == 1
    requested = request_approval(
        _c02.URL,
        tenant_id=tenant_id,
        run_id=created.run_id,
        call_id="call-" + uuid.uuid4().hex,
        tool="shell.exec",
        permission_scope="workspace-write",
        arguments={"path": "src/app.py"},
        deadline=deadline,
        worker_id="worker-c06",
        epoch=epoch,
        command="python src/app.py",
        workdir="src",
    )
    return created.run_id, requested["approval_id"]


def _expire(approval_id: str) -> None:
    engine = create_engine(_c02.URL)
    with Session(engine) as db:
        row = db.get(Approval, approval_id)
        assert row is not None
        row.deadline = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()
    engine.dispose()


def test_w3_c06_contract() -> None:
    """A waiting approval shows the tool, path, and deadline from the server."""
    assert CARD.is_file(), "ApprovalCard.tsx is missing"
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            deadline = datetime(2099, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
            run_id, _approval_id = _seed(deadline)
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            card = page.locator("[data-approval-card]")
            expect(card).to_contain_text("shell.exec", timeout=10000)
            expect(card).to_contain_text("src/app.py")
            expect(card).to_contain_text("2099-01-02")
            browser.close()
    finally:
        stack.close()


def test_w3_c06_negative() -> None:
    """Approving an expired ask shows a conflict and does not continue the run."""
    assert CARD.is_file(), "ApprovalCard.tsx is missing"
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            run_id, approval_id = _seed(datetime.now(timezone.utc) + timedelta(minutes=10))
            page.goto(f"{stack.origin}/runs/{run_id}", wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="批准")).to_be_visible(timeout=10000)
            _expire(approval_id)
            page.get_by_role("button", name="批准").click()
            expect(page.get_by_role("alert")).to_contain_text("冲突", timeout=10000)
            expect(page.locator("body")).not_to_contain_text("succeeded")
            expect(page.locator("body")).not_to_contain_text("继续")
            browser.close()
    finally:
        stack.close()
