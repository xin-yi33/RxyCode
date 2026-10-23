"""WEB-W2-C06. After approve, a restarted worker runs the tool at most once."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
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

from rxycode_server.approvals.service import ApprovalStale, decide_approval  # noqa: E402
from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import Organization, Project, SessionRow, User  # noqa: E402
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_worker.interrupt_resume import pause_for_approval, resume_approved  # noqa: E402
from rxycode_worker.supervisor import claim  # noqa: E402


def _seed(url: str) -> str:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c06m", github_id="gh-c06m", kind="github"))
        db.add(Organization(id="org-c06m", tenant_id="tenant-c06m"))
        db.add(Project(id="project-c06m", tenant_id="tenant-c06m", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c06m",
                project_id="project-c06m",
                title="resume",
            )
        )
        db.commit()
    engine.dispose()
    return session_id


def _resume_in_new_process(env: dict[str, str]) -> dict:
    script = (
        "import json, os\n"
        "from rxycode_worker.interrupt_resume import resume_approved\n"
        "result = resume_approved(\n"
        "    os.environ['C06_URL'],\n"
        "    tenant_id=os.environ['C06_TENANT'],\n"
        "    run_id=os.environ['C06_RUN'],\n"
        "    approval_id=os.environ['C06_APPROVAL'],\n"
        "    worker_id=os.environ['C06_WORKER'],\n"
        "    journal_dir=os.environ['C06_JOURNAL'],\n"
        "    workdir=os.environ['C06_WORKDIR'],\n"
        "    command=os.environ['C06_COMMAND'],\n"
        ")\n"
        "print('C06_RESUME ' + json.dumps(result))\n"
    )
    child = os.environ.copy()
    child.update(env)
    previous = child.get("PYTHONPATH", "")
    parts = [str(REPO), str(_SERVER), str(_WORKER)]
    if previous:
        parts.append(previous)
    child["PYTHONPATH"] = os.pathsep.join(parts)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=child,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    line = next(item for item in proc.stdout.splitlines() if item.startswith("C06_RESUME "))
    return json.loads(line.removeprefix("C06_RESUME "))


def test_w2_c06_integration(postgres_url: str, tmp_path: Path):
    """Approve, restart the worker, and the shell still runs only once."""
    session_id = _seed(postgres_url)
    created = create_run(
        postgres_url,
        tenant_id="tenant-c06m",
        session_id=session_id,
        message="write once",
        target_id="local:c06",
        permission_profile="confirm_all",
        request_id="req-c06-once",
    )
    epoch = claim(postgres_url, created.run_id, "worker-c06")
    assert epoch == 1
    workdir = Path(tempfile.mkdtemp(prefix="w2c06-shell-", dir=REPO))
    try:
        target = workdir / "shell-write.txt"
        command = (
            "Add-Content -LiteralPath 'shell-write.txt' -Value 'shell-write' -Encoding utf8"
            if os.name == "nt"
            else "printf '%s' shell-write > shell-write.txt"
        )
        journal_dir = tmp_path / "journal"
        paused = pause_for_approval(
            postgres_url,
            tenant_id="tenant-c06m",
            run_id=created.run_id,
            call_id="call_" + uuid.uuid4().hex,
            tool="bash",
            permission_scope="workspace-write",
            arguments={"command": command},
            deadline=datetime.now(timezone.utc) + timedelta(hours=4),
            worker_id="worker-c06",
            epoch=epoch,
            journal_dir=str(journal_dir),
            workdir=str(workdir),
            command=command,
        )
        assert paused["asked"] is True
        assert not target.exists()
        decided = decide_approval(
            postgres_url,
            tenant_id="tenant-c06m",
            approval_id=paused["approval_id"],
            decision="approved",
            expected_revision=0,
            now=datetime.now(timezone.utc),
        )
        assert decided["status"] == "approved"
        first = resume_approved(
            postgres_url,
            tenant_id="tenant-c06m",
            run_id=created.run_id,
            approval_id=paused["approval_id"],
            worker_id="worker-c06",
            journal_dir=str(journal_dir),
            workdir=str(workdir),
            command=command,
        )
        assert first["executed"] is True, first
        assert target.read_text(encoding="utf-8").count("shell-write") == 1
        finished = create_engine(postgres_url)
        with Session(finished) as db:
            from rxycode_server.persistence.models import Run

            done = db.get(Run, created.run_id)
            assert done is not None
            assert done.status == "succeeded"
            assert done.lease_owner is None
        finished.dispose()
        follow = create_run(
            postgres_url,
            tenant_id="tenant-c06m",
            session_id=session_id,
            message="next",
            target_id="local:c06",
            permission_profile="confirm_all",
            request_id="req-c06-next",
        )
        assert follow.run_id != created.run_id
        second = _resume_in_new_process(
            {
                "C06_URL": postgres_url,
                "C06_TENANT": "tenant-c06m",
                "C06_RUN": created.run_id,
                "C06_APPROVAL": paused["approval_id"],
                "C06_WORKER": "worker-c06b",
                "C06_JOURNAL": str(journal_dir),
                "C06_WORKDIR": str(workdir),
                "C06_COMMAND": command,
            }
        )
        assert second["executed"] is False
        assert target.read_text(encoding="utf-8").count("shell-write") == 1
        with pytest.raises(ApprovalStale) as again:
            decide_approval(
                postgres_url,
                tenant_id="tenant-c06m",
                approval_id=paused["approval_id"],
                decision="approved",
                expected_revision=0,
                now=datetime.now(timezone.utc),
            )
        assert again.value.http_status == 409
        assert again.value.code == "APPROVAL_STALE"
        assert target.read_text(encoding="utf-8").count("shell-write") == 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
