"""WEB-W2-C05. A shell write whose ACK was lost is not executed a second time."""

from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
for _path in (REPO, _SERVER, _WORKER, _RUNNER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Organization,
    Project,
    Run,
    SessionRow,
    ToolInvocation,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_worker.recovery import (  # noqa: E402
    recover_unknown_shell,
    run_shell_before_ack,
)
from rxycode_worker.supervisor import claim  # noqa: E402

from RxyCode.RxyCode1_1_0.execution.tool_journal import (  # noqa: E402
    ToolExecutionJournal,
)


class _LostAckJournal(ToolExecutionJournal):
    """The shell can finish while the durable ACK still fails."""

    def complete(self, attempt_id: str, call: object, result: object) -> str:
        raise OSError("ack lost")


def _seed(url: str) -> str:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c05", github_id="gh-c05", kind="github"))
        db.add(Organization(id="org-c05", tenant_id="tenant-c05"))
        db.add(Project(id="project-c05", tenant_id="tenant-c05", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c05",
                project_id="project-c05",
                title="recover",
            )
        )
        db.commit()
    engine.dispose()
    return session_id


def test_w2_c05_integration(postgres_url: str, tmp_path: Path):
    """A completed shell write with a lost ACK stays unknown and is not repeated."""
    session_id = _seed(postgres_url)
    created = create_run(
        postgres_url,
        tenant_id="tenant-c05",
        session_id=session_id,
        message="append a line",
        target_id="local:c05",
        permission_profile="full_auto",
        request_id="req-c05",
    )
    journal = _LostAckJournal(tmp_path / "journal")
    # The shell sandbox only allows the configured workspace, which is this repo.
    workdir = Path(tempfile.mkdtemp(prefix="w2c05-shell-", dir=REPO))
    try:
        _assert_lost_ack(postgres_url, created, workdir, journal)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _assert_lost_ack(postgres_url: str, created, workdir: Path, journal) -> None:
    target = workdir / "shell-write.txt"
    attempt_id = "att_" + uuid.uuid4().hex
    call_id = "call_" + uuid.uuid4().hex
    command = "Add-Content -LiteralPath 'shell-write.txt' -Value 'shell-write' -Encoding utf8"
    epoch = claim(postgres_url, created.run_id, "worker-c05")
    assert epoch == 1
    common = {
        "tenant_id": "tenant-c05",
        "run_id": created.run_id,
        "command": command,
        "workdir": str(workdir),
        "journal": journal,
    }
    stale = run_shell_before_ack(
        postgres_url,
        call_id=call_id,
        attempt_id=attempt_id,
        worker_id="other-worker",
        epoch=1,
        **common,
    )
    assert stale["executed"] is False
    assert stale["run_status"] == "lease_rejected"
    assert not target.exists()

    started = run_shell_before_ack(
        postgres_url,
        call_id=call_id,
        attempt_id=attempt_id,
        worker_id="worker-c05",
        epoch=epoch,
        **common,
    )
    assert started["executed"] is True, started.get("output")
    assert started["acked"] is False, started.get("output")
    assert target.exists(), started.get("output")
    assert target.read_text(encoding="utf-8").count("shell-write") == 1

    bypass = run_shell_before_ack(
        postgres_url,
        call_id="call_" + uuid.uuid4().hex,
        attempt_id="att_" + uuid.uuid4().hex,
        worker_id="worker-c05",
        epoch=epoch,
        **common,
    )
    assert bypass["executed"] is False
    assert bypass["journal_state"] == "unknown"
    assert bypass["run_status"] == "recovery_required"
    assert target.read_text(encoding="utf-8").count("shell-write") == 1

    denied = recover_unknown_shell(
        postgres_url,
        call_id=call_id,
        attempt_id=attempt_id,
        worker_id="other-worker",
        epoch=2,
        **common,
    )
    assert denied["executed"] is False
    assert denied["run_status"] == "lease_rejected"

    recovered = recover_unknown_shell(
        postgres_url,
        call_id=call_id,
        attempt_id=attempt_id,
        worker_id="worker-c05",
        epoch=epoch,
        **common,
    )
    assert recovered["executed"] is False
    assert recovered["journal_state"] == "unknown"
    assert recovered["run_status"] == "recovery_required"
    assert target.read_text(encoding="utf-8").count("shell-write") == 1

    again = recover_unknown_shell(
        postgres_url,
        call_id=call_id,
        attempt_id=attempt_id,
        worker_id="worker-c05",
        epoch=epoch,
        **common,
    )
    assert again["executed"] is False
    assert target.read_text(encoding="utf-8").count("shell-write") == 1

    engine = create_engine(postgres_url)
    with Session(engine) as db:
        run = db.get(Run, created.run_id)
        assert run is not None
        assert run.status == "recovery_required"
        rows = db.scalars(
            select(ToolInvocation).where(ToolInvocation.run_id == created.run_id)
        ).all()
    engine.dispose()
    matched = [row for row in rows if row.call_id == call_id]
    assert len(matched) == 1
    assert matched[0].attempt_id == attempt_id
    assert matched[0].journal_state == "unknown"
    assert matched[0].target_id == "local:c05"

    asked = create_run(
        postgres_url,
        tenant_id="tenant-c05",
        session_id=run.session_id,
        message="do not auto run",
        target_id="local:c05",
        permission_profile="confirm_all",
        request_id="req-c05-ask",
    )
    ask_epoch = claim(postgres_url, asked.run_id, "worker-ask")
    assert ask_epoch == 1
    denied_file = workdir / "not-approved.txt"
    ask_journal = ToolExecutionJournal(workdir / "ask-journal")
    blocked = run_shell_before_ack(
        postgres_url,
        tenant_id="tenant-c05",
        run_id=asked.run_id,
        call_id="call_" + uuid.uuid4().hex,
        attempt_id="att_" + uuid.uuid4().hex,
        command="Add-Content -LiteralPath 'not-approved.txt' -Value 'nope' -Encoding utf8",
        workdir=str(workdir),
        journal=ask_journal,
        worker_id="worker-ask",
        epoch=ask_epoch,
    )
    assert blocked["executed"] is False
    assert not denied_file.exists()
