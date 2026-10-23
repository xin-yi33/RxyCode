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
from rxycode_server.persistence.models import (  # noqa: E402
    Approval,
    Membership,
    Organization,
    Project,
    SessionRow,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_worker.supervisor import claim  # noqa: E402


def _seed(deadline: datetime) -> tuple[str, str]:
    engine = create_engine(_c02.URL)
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.kind == "local")).one_or_none()
        if user is None:
            user = User(id=uuid.uuid4().hex, github_id=None, kind="local")
            db.add(user)
            db.flush()
        tenant_id = db.scalars(
            select(Membership.tenant_id).where(Membership.user_id == user.id)
        ).one_or_none()
        if tenant_id is None:
            tenant_id = uuid.uuid4().hex
            db.add(Organization(id=uuid.uuid4().hex, tenant_id=tenant_id))
            db.add(
                Membership(
                    id=uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    user_id=user.id,
                    role="owner",
                )
            )
        project_id = uuid.uuid4().hex
        session_id = uuid.uuid4().hex
        db.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name="c06-" + uuid.uuid4().hex[:8],
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
    """A waiting approval shows the real ask and parks the run as 等待你的操作."""
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            deadline = datetime(2099, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
            run_id, approval_id = _seed(deadline)
            # W9-F3: the decision card moves to the F4 RunTimeline. The session
            # page still shows the parked status + pending approval row, and
            # the API still serves the real ask fields this test asserted.
            session = page.request.get(f"{stack.origin}/api/v1/runs/{run_id}")
            session_id = session.json()["session_id"]
            page.goto(
                f"{stack.origin}/app/s/{session_id}", wait_until="domcontentloaded"
            )
            expect(
                page.locator("[data-run-status='waiting_approval']").first
            ).to_be_visible(timeout=10000)
            expect(
                page.locator(f"[data-approval-id='{approval_id}']")
            ).to_contain_text("等待审批", timeout=10000)
            asks = page.request.get(f"{stack.origin}/api/v1/runs/{run_id}/approvals")
            assert asks.ok
            rows = asks.json()["approvals"]
            ask = next(item for item in rows if item["approval_id"] == approval_id)
            assert ask["tool"] == "shell.exec"
            assert ask["arguments"]["path"] == "src/app.py"
            assert "2099-01-02" in str(ask["deadline"])
            browser.close()
    finally:
        stack.close()


def test_w3_c06_negative() -> None:
    """Approving an expired ask conflicts and does not continue the run."""
    stack = _c02._Stack()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            _c02._login(page, stack.origin)
            run_id, approval_id = _seed(datetime.now(timezone.utc) + timedelta(minutes=10))
            asks = page.request.get(f"{stack.origin}/api/v1/runs/{run_id}/approvals")
            revision = asks.json()["approvals"][0]["revision"]
            # The approve button lives on the F4 card; the stale-revision
            # conflict it exercised is asserted at the API layer here.
            _expire(approval_id)
            csrf = page.request.get(f"{stack.origin}/api/v1/auth/csrf")
            denied = page.request.post(
                f"{stack.origin}/api/v1/runs/{run_id}/approvals",
                data={
                    "approval_id": approval_id,
                    "decision": "approve",
                    "revision": revision,
                },
                headers={
                    "origin": stack.origin,
                    "x-csrf-token": csrf.json()["csrf_token"],
                },
            )
            assert denied.status in (400, 409), denied.status
            run = page.request.get(f"{stack.origin}/api/v1/runs/{run_id}")
            assert run.json()["status"] != "succeeded"
            browser.close()
    finally:
        stack.close()


def test_w3_c06_question_reaches_waiting_worker() -> None:
    """The worker keeps waiting until this session's answer arrives."""
    import asyncio

    from appserver.question import PipeQuestionBroker
    from appserver.runtime import bind_prompt_context, reset_prompt_context
    from core.question import (
        QuestionRequest,
        clear_question_pending,
        list_pending_questions,
        publish_question_answer,
    )

    question_id = "c06" + uuid.uuid4().hex[:20]
    session_id = "ses" + uuid.uuid4().hex[:20]

    async def hang(_method: str, _params: dict) -> dict:
        await asyncio.Event().wait()
        return {"answer": "from-rpc"}

    async def scenario() -> None:
        broker = PipeQuestionBroker(hang, timeout=2)
        tokens = bind_prompt_context(session_id, None)
        ask_task = asyncio.create_task(
            broker.ask(QuestionRequest(question="继续吗？", question_id=question_id))
        )
        try:
            found = False
            for _ in range(40):
                rows = list_pending_questions(session_id)
                if any(row["question_id"] == question_id for row in rows):
                    found = True
                    break
                await asyncio.sleep(0.05)
            assert found, "the waiting worker did not register the question"
            hidden = list_pending_questions("other-session")
            assert all(row["question_id"] != question_id for row in hidden)
            stolen = publish_question_answer(
                question_id,
                "stolen",
                session_id="other-session",
            )
            assert stolen is False
            assert ask_task.done() is False
            delivered = publish_question_answer(
                question_id,
                "yes",
                session_id=session_id,
            )
            assert delivered is True
            replacement = publish_question_answer(
                question_id,
                "later",
                session_id=session_id,
            )
            assert replacement is False
            result = await asyncio.wait_for(ask_task, timeout=2)
            assert result.answer == "yes"
            assert result.timed_out is False
            assert result.unavailable is False
        finally:
            reset_prompt_context(tokens)
            if not ask_task.done():
                ask_task.cancel()
                try:
                    await ask_task
                except (asyncio.CancelledError, Exception):
                    pass
            clear_question_pending(question_id)

    asyncio.run(scenario())


def test_w3_c06_sse_question_uses_bound_session() -> None:
    """The base broker records the bound session so the web run can answer it."""
    import asyncio

    from appserver.runtime import bind_prompt_context, reset_prompt_context
    from core.question import (
        QuestionRequest,
        SseQuestionBroker,
        clear_question_pending,
        list_pending_questions,
        publish_question_answer,
    )

    question_id = "c06sse" + uuid.uuid4().hex[:16]
    session_id = "ses" + uuid.uuid4().hex[:20]

    async def scenario() -> None:
        broker = SseQuestionBroker(timeout=2)
        broker.set_event_sink(lambda _event: None)
        tokens = bind_prompt_context(session_id, None)
        ask_task = asyncio.create_task(
            broker.ask(QuestionRequest(question="走哪条？", question_id=question_id))
        )
        try:
            found = False
            for _ in range(40):
                rows = list_pending_questions(session_id)
                if any(row["question_id"] == question_id for row in rows):
                    found = True
                    break
                await asyncio.sleep(0.05)
            assert found, "the bound session cannot see the question"
            other = list_pending_questions("other-session")
            assert all(row["question_id"] != question_id for row in other)
            assert (
                publish_question_answer(question_id, "yes", session_id=session_id) is True
            )
            result = await asyncio.wait_for(ask_task, timeout=2)
            assert result.answer == "yes"
            assert result.timed_out is False
        finally:
            reset_prompt_context(tokens)
            if not ask_task.done():
                ask_task.cancel()
                try:
                    await ask_task
                except (asyncio.CancelledError, Exception):
                    pass
            clear_question_pending(question_id)

    asyncio.run(scenario())


def test_w3_c06_answer_file_is_complete() -> None:
    """The visible answer file is finished JSON, and a second publish does not replace it."""
    import json

    from core.question import (
        clear_question_pending,
        mark_question_pending,
        publish_question_answer,
    )

    question_id = "c06atom" + uuid.uuid4().hex[:12]
    answer_path = Path.home() / ".rxycode" / "questions" / f"{question_id}.answer.json"
    try:
        mark_question_pending(question_id, session_id="ses-atom", prompt="哪一步")
        assert publish_question_answer(question_id, "yes", session_id="ses-atom") is True
        assert json.loads(answer_path.read_text(encoding="utf-8")) == {
            "question_id": question_id,
            "answer": "yes",
        }
        assert publish_question_answer(question_id, "no", session_id="ses-atom") is False
        assert json.loads(answer_path.read_text(encoding="utf-8"))["answer"] == "yes"
    finally:
        clear_question_pending(question_id)
