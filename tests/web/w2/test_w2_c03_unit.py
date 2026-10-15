"""WEB-W2-C03. One idempotency key is one Run, and a stale lease cannot finish it."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _path in (_SERVER, _WORKER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.migrate import upgrade_head
from rxycode_server.persistence.models import Organization, Project, SessionRow, User
from rxycode_server.runs.service import RunAlreadyActive, RunConflict, create_run
from rxycode_worker.supervisor import LeaseRejected, claim, commit_terminal


def _seed(url: str) -> str:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c03", github_id="gh-c03", kind="github"))
        db.add(Organization(id="org-c03", tenant_id="tenant-c03"))
        db.add(Project(id="project-c03", tenant_id="tenant-c03", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c03",
                project_id="project-c03",
                title="run",
            )
        )
        db.commit()
    engine.dispose()
    return session_id


def _counts(url: str) -> tuple[int, int, int]:
    engine = create_engine(url)
    with engine.connect() as conn:
        runs = conn.execute(text("SELECT count(*) FROM runs")).scalar()
        events = conn.execute(text("SELECT count(*) FROM run_events")).scalar()
        outbox = conn.execute(text("SELECT count(*) FROM outbox")).scalar()
    engine.dispose()
    return int(runs), int(events), int(outbox)


def test_w2_c03_contract(postgres_url: str):
    """The same payload returns the same Run. A second active payload does not."""
    session_id = _seed(postgres_url)
    kwargs = {
        "tenant_id": "tenant-c03",
        "session_id": session_id,
        "message": "build the gate",
        "target_id": "local:1",
        "permission_profile": "workspace-write",
        "request_id": "req-same",
        "claimed_tenant_id": "attacker",
    }
    first = create_run(postgres_url, **kwargs)
    second = create_run(postgres_url, **kwargs)
    assert first.http_status == 202
    assert second.http_status == 202
    assert first.run_id == second.run_id
    assert first.status == "queued"
    assert first.events_url == f"/api/v1/runs/{first.run_id}/events"
    assert _counts(postgres_url) == (1, 1, 1)
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        tenant_id, status = conn.execute(
            text("SELECT tenant_id, status FROM runs WHERE id = :id"),
            {"id": first.run_id},
        ).one()
    engine.dispose()
    assert tenant_id == "tenant-c03"
    assert status == "pending"
    with pytest.raises(RunConflict):
        create_run(postgres_url, **{**kwargs, "message": "different payload"})
    assert _counts(postgres_url) == (1, 1, 1)
    with pytest.raises(RunAlreadyActive):
        create_run(
            postgres_url,
            tenant_id="tenant-c03",
            session_id=session_id,
            message="another",
            target_id="local:1",
            permission_profile="workspace-write",
            request_id="req-other",
        )
    assert _counts(postgres_url) == (1, 1, 1)


def test_w2_c03_negative(postgres_url: str, tmp_path: Path):
    """A killed worker's old epoch cannot write the terminal status."""
    session_id = _seed(postgres_url)
    created = create_run(
        postgres_url,
        tenant_id="tenant-c03",
        session_id=session_id,
        message="hold",
        target_id="local:1",
        permission_profile="workspace-write",
        request_id="req-lease",
    )
    marker = tmp_path / "epoch.txt"
    claim_script = tmp_path / "claim_worker.py"
    claim_script.write_text(
        textwrap.dedent(
            f"""
            import sys, time
            sys.path[:0] = {[str(_SERVER), str(_WORKER)]!r}
            from rxycode_worker.supervisor import claim
            epoch = claim({postgres_url!r}, {created.run_id!r}, "worker-a")
            open({str(marker)!r}, "w", encoding="utf-8").write(str(epoch))
            time.sleep(30)
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(_SERVER), str(_WORKER), str(REPO)])
    worker = subprocess.Popen([sys.executable, str(claim_script)], cwd=tmp_path, env=env)
    deadline = time.time() + 20
    while time.time() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.read_text(encoding="utf-8") == "1"
    worker.kill()
    worker.wait(timeout=10)
    engine = create_engine(postgres_url)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE runs SET lease_until = lease_until - interval '1 hour' WHERE id = :id"),
            {"id": created.run_id},
        )
    engine.dispose()
    script = tmp_path / "stale_worker.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path[:0] = { [str(_SERVER), str(_WORKER)]!r}
            from rxycode_worker.supervisor import LeaseRejected, commit_terminal
            try:
                commit_terminal({postgres_url!r}, {created.run_id!r}, "worker-a", 1, "succeeded")
            except LeaseRejected:
                print("REJECTED")
                raise SystemExit(0)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(_SERVER), str(_WORKER), str(REPO)])
    run = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert run.returncode == 0, run.stderr
    assert "REJECTED" in run.stdout
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        status, owner, current = conn.execute(
            text("SELECT status, lease_owner, lease_epoch FROM runs WHERE id = :id"),
            {"id": created.run_id},
        ).one()
    engine.dispose()
    assert status == "leased"
    assert owner == "worker-a"
    assert current == 1
    with pytest.raises(LeaseRejected):
        commit_terminal(postgres_url, created.run_id, "worker-a", 1, "succeeded")
