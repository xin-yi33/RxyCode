"""WEB-W2-C05. A shell write whose ACK was lost is not executed a second time."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _path in (REPO, _SERVER, _WORKER):
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

from RxyCode.RxyCode1_1_0.execution.tool_journal import (  # noqa: E402
    ToolExecutionJournal,
)


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
        permission_profile="workspace-write",
        request_id="req-c05",
    )
    journal = ToolExecutionJournal(tmp_path / "journal")
    target = tmp_path / "shell-write.txt"
    attempt_id = "att_" + uuid.uuid4().hex
    call_id = "call_" + uuid.uuid4().hex
    command = [
        "pwsh",
        "-NoProfile",
        "-Command",
        f"Add-Content -LiteralPath '{target}' -Value 'shell-write' -Encoding utf8",
    ]
    started = run_shell_before_ack(
        postgres_url,
        tenant_id="tenant-c05",
        run_id=created.run_id,
        call_id=call_id,
        attempt_id=attempt_id,
        command=command,
        journal=journal,
    )
    assert started["executed"] is True
    assert started["acked"] is False
    assert target.read_text(encoding="utf-8").count("shell-write") == 1

    recovered = recover_unknown_shell(
        postgres_url,
        tenant_id="tenant-c05",
        run_id=created.run_id,
        call_id=call_id,
        attempt_id=attempt_id,
        command=command,
        journal=journal,
    )
    assert recovered["executed"] is False
    assert recovered["journal_state"] == "unknown"
    assert recovered["run_status"] == "recovery_required"
    assert target.read_text(encoding="utf-8").count("shell-write") == 1

    again = recover_unknown_shell(
        postgres_url,
        tenant_id="tenant-c05",
        run_id=created.run_id,
        call_id=call_id,
        attempt_id=attempt_id,
        command=command,
        journal=journal,
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
    assert len(rows) == 1
    assert rows[0].call_id == call_id
    assert rows[0].attempt_id == attempt_id
    assert rows[0].journal_state == "unknown"
    assert rows[0].target_id == "local:c05"
