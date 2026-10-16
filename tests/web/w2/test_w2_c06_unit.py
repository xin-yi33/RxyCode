"""WEB-W2-C06. A pending approval survives overnight, and a stale decision does nothing."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _path in (REPO, _SERVER, _WORKER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.approvals.service import (  # noqa: E402
    ApprovalStale,
    cancel_approval,
    decide_approval,
    list_pending,
    request_approval,
)
from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Organization,
    Project,
    Run,
    SessionRow,
    User,
)
from rxycode_server.runs.service import RunAlreadyActive, create_run  # noqa: E402
from rxycode_worker.interrupt_resume import (  # noqa: E402
    pause_for_approval,
    resume_approved,
)
from rxycode_worker.supervisor import claim  # noqa: E402


def _seed(url: str) -> str:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c06", github_id="gh-c06", kind="github"))
        db.add(Organization(id="org-c06", tenant_id="tenant-c06"))
        db.add(Project(id="project-c06", tenant_id="tenant-c06", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c06",
                project_id="project-c06",
                title="approve",
            )
        )
        db.commit()
    engine.dispose()
    return session_id


def _run(url: str, session_id: str, request_id: str, profile: str = "confirm_all"):
    created = create_run(
        url,
        tenant_id="tenant-c06",
        session_id=session_id,
        message="needs approval",
        target_id="local:c06",
        permission_profile=profile,
        request_id=request_id,
    )
    epoch = claim(url, created.run_id, "worker-c06")
    assert epoch == 1
    return created.run_id, epoch


def test_w2_c06_contract(postgres_url: str):
    """The next day the same pending request and permission scope are still there."""
    session_id = _seed(postgres_url)
    run_id, epoch = _run(postgres_url, session_id, "req-c06-pending")
    call_id = "call_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    requested = request_approval(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        call_id=call_id,
        tool="bash",
        permission_scope="workspace-write",
        arguments={"command": "echo hi"},
        deadline=now + timedelta(days=2),
        worker_id="worker-c06",
        epoch=epoch,
    )
    tomorrow = now + timedelta(days=1)
    pending = list_pending(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        now=tomorrow,
    )
    assert len(pending) == 1
    assert pending[0]["approval_id"] == requested["approval_id"]
    assert pending[0]["call_id"] == call_id
    assert pending[0]["tool"] == "bash"
    assert pending[0]["permission_scope"] == "workspace-write"
    assert pending[0]["status"] == "pending"
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.status == "waiting_approval"
        assert run.lease_owner is None
    engine.dispose()
    with pytest.raises(RunAlreadyActive):
        create_run(
            postgres_url,
            tenant_id="tenant-c06",
            session_id=session_id,
            message="second",
            target_id="local:c06",
            permission_profile="confirm_all",
            request_id="req-c06-second",
        )


def test_w2_c06_negative(postgres_url: str, tmp_path: Path):
    """Expired and cancelled approvals reject a later approve and do not run a tool."""
    session_id = _seed(postgres_url)
    run_id, epoch = _run(postgres_url, session_id, "req-c06-stale")
    now = datetime.now(timezone.utc)
    expired = request_approval(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        call_id="call_" + uuid.uuid4().hex,
        tool="bash",
        permission_scope="workspace-write",
        arguments={"command": "echo stale"},
        deadline=now - timedelta(seconds=1),
        worker_id="worker-c06",
        epoch=epoch,
    )
    marker = tmp_path / "stale-write.txt"
    with pytest.raises(ApprovalStale) as expired_decision:
        decide_approval(
            postgres_url,
            tenant_id="tenant-c06",
            approval_id=expired["approval_id"],
            decision="approved",
            expected_revision=0,
            now=now,
        )
    assert expired_decision.value.http_status == 409
    assert expired_decision.value.code == "APPROVAL_STALE"
    refused = resume_approved(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        approval_id=expired["approval_id"],
        worker_id="worker-c06",
        journal_dir=str(tmp_path / "journal"),
        workdir=str(tmp_path),
        command=f"Set-Content -LiteralPath '{marker}' -Value 'ran'",
    )
    assert refused["executed"] is False
    assert not marker.exists()

    engine = create_engine(postgres_url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c06",
                project_id="project-c06",
                title="cancel",
            )
        )
        db.commit()
    engine.dispose()
    run_id, epoch = _run(postgres_url, session_id, "req-c06-cancel")
    live = request_approval(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        call_id="call_" + uuid.uuid4().hex,
        tool="bash",
        permission_scope="workspace-write",
        arguments={"command": "echo cancel"},
        deadline=now + timedelta(hours=2),
        worker_id="worker-c06",
        epoch=epoch,
    )
    cancel_approval(
        postgres_url,
        tenant_id="tenant-c06",
        approval_id=live["approval_id"],
        expected_revision=0,
        now=now,
    )
    with pytest.raises(ApprovalStale) as cancelled:
        decide_approval(
            postgres_url,
            tenant_id="tenant-c06",
            approval_id=live["approval_id"],
            decision="approved",
            expected_revision=0,
            now=now,
        )
    assert cancelled.value.http_status == 409
    assert cancelled.value.code == "APPROVAL_STALE"


def test_w2_c06_full_skips_ask(postgres_url: str, tmp_path: Path):
    """A full local grant does not open a per-call ask or run the tool by itself."""
    session_id = _seed(postgres_url)
    run_id, epoch = _run(postgres_url, session_id, "req-c06-full", profile="full_auto")
    marker = tmp_path / "full-write.txt"
    paused = pause_for_approval(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        call_id="call_" + uuid.uuid4().hex,
        tool="bash",
        permission_scope="full",
        arguments={"command": "echo full"},
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="worker-c06",
        epoch=epoch,
        journal_dir=str(tmp_path / "journal"),
        workdir=str(tmp_path),
        command=f"Set-Content -LiteralPath '{marker}' -Value 'ran'",
    )
    assert paused["asked"] is False
    assert list_pending(
        postgres_url,
        tenant_id="tenant-c06",
        run_id=run_id,
        now=datetime.now(timezone.utc),
    ) == []
    assert not marker.exists()
