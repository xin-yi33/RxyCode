"""WEB-W7-C02. A crashed worker leaves approvals durable and shells un-replayed."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
for _path in (REPO, _SERVER, _WORKER, _RUNNER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.approvals.service import decide_approval, list_pending  # noqa: E402
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
from rxycode_worker.recovery import recover_unknown_shell, run_shell_before_ack  # noqa: E402
from rxycode_worker.supervisor import claim  # noqa: E402


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra)
    parts = [str(REPO), str(_SERVER), str(_WORKER), str(_RUNNER)]
    previous = env.get("PYTHONPATH", "")
    if previous:
        parts.append(previous)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _spawn(script: str, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _read_stdout(proc: subprocess.Popen, prefix: str, timeout: float) -> str:
    """Block until a stdout line starts with ``prefix`` or the deadline passes."""
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = lines.get(timeout=max(0.05, deadline - time.time()))
        except queue.Empty:
            break
        if line.startswith(prefix):
            return line.strip()
    raise AssertionError(f"child did not print {prefix!r} within {timeout}s")


def _run_child(script: str, env: dict[str, str], prefix: str, timeout: float = 120) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-3000:]
    line = next(
        item for item in proc.stdout.splitlines() if item.startswith(prefix)
    )
    return json.loads(line.removeprefix(prefix))


_PAUSE_WORKER = """\
import os, time
from datetime import datetime, timedelta, timezone
from rxycode_worker.supervisor import claim
from rxycode_worker.interrupt_resume import pause_for_approval

url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
epoch = claim(url, run_id, os.environ["C02_WORKER"], ttl_seconds=30)
paused = pause_for_approval(
    url,
    tenant_id=os.environ["C02_TENANT"],
    run_id=run_id,
    call_id=os.environ["C02_CALL"],
    tool="bash",
    permission_scope="workspace-write",
    arguments={"command": os.environ["C02_COMMAND"]},
    deadline=datetime.now(timezone.utc) + timedelta(hours=4),
    worker_id=os.environ["C02_WORKER"],
    epoch=epoch,
    journal_dir=os.environ["C02_JOURNAL"],
    workdir=os.environ["C02_WORKDIR"],
    command=os.environ["C02_COMMAND"],
)
print("PAUSED " + str(paused["approval_id"]), flush=True)
time.sleep(120)
"""

_RESUME_WORKER = """\
import json, os
from rxycode_worker.interrupt_resume import resume_approved
result = resume_approved(
    os.environ["C02_URL"],
    tenant_id=os.environ["C02_TENANT"],
    run_id=os.environ["C02_RUN"],
    approval_id=os.environ["C02_APPROVAL"],
    worker_id=os.environ["C02_WORKER"],
    journal_dir=os.environ["C02_JOURNAL"],
    workdir=os.environ["C02_WORKDIR"],
    command=os.environ["C02_COMMAND"],
)
print("RESUMED " + json.dumps(result), flush=True)
"""

_SHELL_WORKER = """\
import json, os
from rxycode_worker.supervisor import claim
from rxycode_worker.recovery import run_shell_before_ack
from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
epoch = claim(
    url, run_id, os.environ["C02_WORKER"],
    ttl_seconds=int(os.environ["C02_TTL"]),
)
result = run_shell_before_ack(
    url,
    tenant_id=os.environ["C02_TENANT"],
    run_id=run_id,
    call_id=os.environ["C02_CALL"],
    attempt_id=os.environ["C02_ATTEMPT"],
    command=os.environ["C02_COMMAND"],
    workdir=os.environ["C02_WORKDIR"],
    journal=ToolExecutionJournal(os.environ["C02_JOURNAL"]),
    worker_id=os.environ["C02_WORKER"],
    epoch=epoch,
)
print("RESULT " + json.dumps(result, default=str), flush=True)
"""

_RECOVER_WORKER = """\
import json, os
from rxycode_worker.supervisor import claim
from rxycode_worker.recovery import recover_unknown_shell
from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
url = os.environ["C02_URL"]
run_id = os.environ["C02_RUN"]
epoch = claim(url, run_id, os.environ["C02_WORKER"], ttl_seconds=60)
result = recover_unknown_shell(
    url,
    tenant_id=os.environ["C02_TENANT"],
    run_id=run_id,
    call_id=os.environ["C02_CALL"],
    attempt_id=os.environ["C02_ATTEMPT"],
    command=os.environ["C02_COMMAND"],
    workdir=os.environ["C02_WORKDIR"],
    journal=ToolExecutionJournal(os.environ["C02_JOURNAL"]),
    worker_id=os.environ["C02_WORKER"],
    epoch=epoch,
)
print("RECOVERED " + json.dumps(result, default=str), flush=True)
"""


def _seed(postgres_url: str, tag: str) -> tuple[str, str]:
    upgrade_head(postgres_url)
    engine = create_engine(postgres_url)
    session_id = uuid.uuid4().hex
    tenant = f"tenant-{tag}"
    with Session(engine) as db:
        db.add(User(id=f"user-{tag}", github_id=f"gh-{tag}", kind="github"))
        db.add(Organization(id=f"org-{tag}", tenant_id=tenant))
        db.add(
            Project(id=f"project-{tag}", tenant_id=tenant, name="app", repo_config={})
        )
        db.add(
            SessionRow(
                id=session_id,
                tenant_id=tenant,
                project_id=f"project-{tag}",
                title=tag,
            )
        )
        db.commit()
    engine.dispose()
    return tenant, session_id


def _marker_procs(marker: str, ignore_pid: int | None = None) -> list[dict]:
    hits: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
        if proc.info["pid"] in {os.getpid(), ignore_pid}:
            continue
        try:
            cmdline = proc.info["cmdline"] or []
            if any(marker in arg for arg in cmdline):
                hits.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return hits


def test_w7_c02_contract(postgres_url: str, tmp_path: Path):
    """A worker dies while waiting for approval; the ask survives, tool runs once."""
    tenant_id, session_id = _seed(postgres_url, "c02contract")
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="approve once",
        target_id="local:c02",
        permission_profile="confirm_all",
        request_id="req-c02-contract",
    )
    workdir = Path(tempfile.mkdtemp(prefix="w7c02-contract-", dir=REPO))
    journal_dir = tmp_path / "journal-contract"
    command = (
        "Add-Content -LiteralPath 'c02-approve.txt' -Value 'once' -Encoding utf8"
    )
    target = workdir / "c02-approve.txt"
    base_env = {
        "C02_URL": postgres_url,
        "C02_TENANT": tenant_id,
        "C02_RUN": created.run_id,
        "C02_CALL": "call_" + uuid.uuid4().hex,
        "C02_JOURNAL": str(journal_dir),
        "C02_WORKDIR": str(workdir),
        "C02_COMMAND": command,
    }
    proc = _spawn(_PAUSE_WORKER, _child_env({**base_env, "C02_WORKER": "w-c02-a"}))
    try:
        approval_id = _read_stdout(proc, "PAUSED ", 90).removeprefix("PAUSED ")
    finally:
        proc.kill()
        proc.wait(timeout=15)

    engine = create_engine(postgres_url)
    with Session(engine) as db:
        run = db.get(Run, created.run_id)
        assert run is not None
        assert run.status == "waiting_approval"
        assert run.lease_owner is None
    pending = list_pending(postgres_url, tenant_id=tenant_id, run_id=created.run_id)
    assert [row["approval_id"] for row in pending] == [approval_id]
    assert pending[0]["tool"] == "bash"
    assert pending[0]["permission_scope"] == "workspace-write"
    assert pending[0]["arguments"]["command"] == command
    assert not target.exists()

    early = _run_child(
        _RESUME_WORKER,
        _child_env({**base_env, "C02_WORKER": "w-c02-early", "C02_APPROVAL": approval_id}),
        "RESUMED ",
    )
    assert early["executed"] is False, early
    assert not target.exists()

    decided = decide_approval(
        postgres_url,
        tenant_id=tenant_id,
        approval_id=approval_id,
        decision="approved",
        expected_revision=0,
        now=datetime.now(timezone.utc),
    )
    assert decided["status"] == "approved"
    first = _run_child(
        _RESUME_WORKER,
        _child_env({**base_env, "C02_WORKER": "w-c02-b", "C02_APPROVAL": approval_id}),
        "RESUMED ",
    )
    assert first["executed"] is True, first
    assert target.read_text(encoding="utf-8").count("once") == 1

    again = _run_child(
        _RESUME_WORKER,
        _child_env({**base_env, "C02_WORKER": "w-c02-c", "C02_APPROVAL": approval_id}),
        "RESUMED ",
    )
    assert again["executed"] is False
    assert target.read_text(encoding="utf-8").count("once") == 1

    with Session(engine) as db:
        done = db.get(Run, created.run_id)
        assert done is not None
        assert done.status == "succeeded"
    engine.dispose()
    shutil.rmtree(workdir, ignore_errors=True)


def test_w7_c02_negative(postgres_url: str, tmp_path: Path):
    """The side effect ran but the ACK died with the worker; never re-executed."""
    tenant_id, session_id = _seed(postgres_url, "c02negative")
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="write then die",
        target_id="local:c02",
        permission_profile="full_auto",
        request_id="req-c02-negative",
    )
    workdir = Path(tempfile.mkdtemp(prefix="w7c02-side-", dir=REPO))
    journal_dir = tmp_path / "journal-side"
    marker = f"c02marker-{uuid.uuid4().hex}"
    command = (
        "Add-Content -LiteralPath 'c02-side.txt' -Value 'once' -Encoding utf8; "
        f"Start-Sleep -Seconds 30  # {marker}"
    )
    target = workdir / "c02-side.txt"
    call_id = "call_" + uuid.uuid4().hex
    attempt_id = "att_" + uuid.uuid4().hex
    base_env = {
        "C02_URL": postgres_url,
        "C02_TENANT": tenant_id,
        "C02_RUN": created.run_id,
        "C02_CALL": call_id,
        "C02_ATTEMPT": attempt_id,
        "C02_JOURNAL": str(journal_dir),
        "C02_WORKDIR": str(workdir),
        "C02_COMMAND": command,
        "C02_TTL": "3",
    }
    leaked: list[dict] = []
    try:
        proc = _spawn(
            _SHELL_WORKER, _child_env({**base_env, "C02_WORKER": "w-c02-n"})
        )
        deadline = time.time() + 60
        while time.time() < deadline and not target.exists():
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout is not None else ""
                raise AssertionError(
                    f"worker exited before the side effect:\n{out[-3000:]}"
                )
            time.sleep(0.2)
        assert target.exists()
        proc.kill()
        proc.wait(timeout=15)

        # Lease expiry (ttl_seconds=3), then a fresh worker reclaims epoch 2.
        time.sleep(4.5)
        engine = create_engine(postgres_url)
        recovered = _run_child(
            _RECOVER_WORKER,
            _child_env({**base_env, "C02_WORKER": "w-c02-n2"}),
            "RECOVERED ",
        )
        assert recovered["executed"] is False, recovered
        assert recovered["run_status"] == "recovery_required"
        assert target.read_text(encoding="utf-8").count("once") == 1

        with Session(engine) as db:
            rows = db.scalars(
                select(ToolInvocation).where(ToolInvocation.run_id == created.run_id)
            ).all()
        matched = [row for row in rows if row.call_id == call_id]
        assert len(matched) == 1
        assert matched[0].journal_state == "unknown"
        engine.dispose()

        second = _run_child(
            _RECOVER_WORKER,
            _child_env({**base_env, "C02_WORKER": "w-c02-n3"}),
            "RECOVERED ",
        )
        assert second["executed"] is False
        assert target.read_text(encoding="utf-8").count("once") == 1

        # Process leak check: the killed worker's shell must not outlive it.
        deadline = time.time() + 10
        while time.time() < deadline:
            leaked = _marker_procs(marker, ignore_pid=proc.pid)
            if not leaked:
                break
            time.sleep(0.5)
        leaked = _marker_procs(marker, ignore_pid=proc.pid)
        assert not leaked, f"orphaned shell survived the worker kill: {leaked}"
    finally:
        for info in _marker_procs(marker):
            try:
                psutil.Process(info["pid"]).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        shutil.rmtree(workdir, ignore_errors=True)

    # The reaping job must not break normal execution: a live worker's command
    # still returns its output and exit status.
    ok_run = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="still works",
        target_id="local:c02",
        permission_profile="full_auto",
        request_id="req-c02-negative-ok",
    )
    ok_workdir = Path(tempfile.mkdtemp(prefix="w7c02-ok-", dir=REPO))
    try:
        epoch = claim(postgres_url, ok_run.run_id, "w-c02-ok")
        assert epoch is not None
        from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal

        result = run_shell_before_ack(
            postgres_url,
            tenant_id=tenant_id,
            run_id=ok_run.run_id,
            call_id="call_" + uuid.uuid4().hex,
            attempt_id="att_" + uuid.uuid4().hex,
            command="Write-Output 'c02-ok-output'",
            workdir=str(ok_workdir),
            journal=ToolExecutionJournal(str(tmp_path / "journal-ok")),
            worker_id="w-c02-ok",
            epoch=epoch,
        )
        # ``executed`` means completed-and-ACKed; the ACK step happens after
        # this call returns, so a live run reports False. What proves job
        # binding did not break execution is the output: a nonzero exit
        # surfaces as ``[error executing bash: ... [exit code: N]]``.
        assert result["run_status"] == "running", result
        ok_output = str(result.get("output") or "")
        assert "c02-ok-output" in ok_output, result
        assert "[error executing bash" not in ok_output
        assert "[exit code:" not in ok_output
    finally:
        shutil.rmtree(ok_workdir, ignore_errors=True)


_BG_SHELL_WORKER = """\
import json, os, time
from RxyCode.RxyCode1_1_0.utils.shell import shell_executor
result = shell_executor.execute(
    os.environ["C02_COMMAND"], workdir=os.environ["C02_WORKDIR"], timeout=60
)
print("BGDONE " + json.dumps({
    "exit_code": result.get("exit_code"),
    "stderr": (result.get("stderr") or "")[:200],
}), flush=True)
time.sleep(120)
"""

_BG_NATIVE_WORKER = """\
import asyncio, json, os, time
from pathlib import Path
from RxyCode.RxyCode1_1_0.utils.shell import shell_executor
from rxycode_runner.local.native_backend import LocalNativeBackend

async def main():
    backend = LocalNativeBackend(target="local", permission="full")
    argv = shell_executor.build_argv(os.environ["C02_COMMAND"])
    result = await backend.run_command(
        argv, Path(os.environ["C02_WORKDIR"]), timeout=60
    )
    print("BGDONE " + json.dumps({
        "exit_code": result.exit_code,
        "stderr": (result.stderr or "")[:200],
    }), flush=True)

asyncio.run(main())
time.sleep(120)
"""


def test_w7_c02_background_survives_command_reaped_on_crash(tmp_path: Path):
    """A detached background process outlives the command but not the worker.

    The reaping Job is process-lifetime: the command returning must NOT
    close the job (a per-command close would KILL_ON_JOB_CLOSE any child
    the agent detached on purpose). Killing the worker is what reaps the
    tree. Runs the real spawn paths of both ShellExecutor (approval /
    confirm_all surface) and LocalNativeBackend.run_command (full path,
    fed ShellExecutor's argv).
    """
    del tmp_path  # workdir must sit under execution.workspace_root
    workdir = Path(tempfile.mkdtemp(prefix="w7c02-bg-", dir=REPO))
    marker = f"c02bg-{uuid.uuid4().hex}"
    # argv[3] of the background python is the marker, so it shows in cmdline.
    # -ArgumentList array elements join WITHOUT quoting on Windows PowerShell,
    # so the quotes around the -c payload must be embedded in the element.
    command = (
        "Start-Process -WindowStyle Hidden -FilePath "
        f"'{sys.executable}' -ArgumentList "
        "'-c','\"import time; time.sleep(120)\"',"
        f"'{marker}'"
    )
    try:
        for name, script in (
            ("shell_executor", _BG_SHELL_WORKER),
            ("native_backend", _BG_NATIVE_WORKER),
        ):
            env = _child_env(
                {"C02_COMMAND": command, "C02_WORKDIR": str(workdir)}
            )
            proc = _spawn(script, env)
            try:
                done = _read_stdout(proc, "BGDONE ", 90).removeprefix("BGDONE ")
                info = json.loads(done)
                assert info["exit_code"] == 0, (name, info)

                # The command already returned; the detached child must
                # still be alive while the worker is alive.
                deadline = time.time() + 10
                while time.time() < deadline and not _marker_procs(
                    marker, ignore_pid=proc.pid
                ):
                    time.sleep(0.2)
                time.sleep(2)
                live = _marker_procs(marker, ignore_pid=proc.pid)
                assert live, (
                    f"{name}: detached background process died with the "
                    f"command (per-command job close regression): {info}"
                )
            finally:
                proc.kill()
                proc.wait(timeout=15)

            # Only the worker died; the reaping job must reap the tree.
            deadline = time.time() + 10
            while time.time() < deadline:
                if not _marker_procs(marker, ignore_pid=proc.pid):
                    break
                time.sleep(0.5)
            leaked = _marker_procs(marker, ignore_pid=proc.pid)
            assert not leaked, (
                f"{name}: background process survived the worker kill: "
                f"{leaked}"
            )
    finally:
        for info in _marker_procs(marker):
            try:
                psutil.Process(info["pid"]).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        shutil.rmtree(workdir, ignore_errors=True)
