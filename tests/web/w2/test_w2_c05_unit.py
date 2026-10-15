"""WEB-W2-C05. A restarted worker restores a read-only checkpoint and fails closed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _path in (REPO, _SERVER, _WORKER):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_worker.checkpoints import (  # noqa: E402
    accept_run,
    graph_thread_id,
    record_readonly_checkpoint,
    resume_readonly,
)
from rxycode_worker.recovery import (  # noqa: E402
    recover_unknown_shell,
    run_shell_before_ack,
)

from RxyCode.RxyCode1_1_0.execution.tool_journal import (  # noqa: E402
    RemoteJournalAdapter,
    ToolExecutionJournal,
)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH", "")
    parts = [str(REPO), str(_SERVER), str(_WORKER)]
    if previous:
        parts.append(previous)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _resume_in_new_process(database_url: str, session_id: str, run_id: str) -> dict:
    """Load the checkpoint from a second interpreter. That is the worker restart."""
    script = (
        "import asyncio, json, os\n"
        "from rxycode_worker.checkpoints import resume_readonly\n"
        "async def main():\n"
        "    restored = await resume_readonly(\n"
        "        os.environ['C05_URL'],\n"
        "        session_id=os.environ['C05_SESSION'],\n"
        "        run_id=os.environ['C05_RUN'],\n"
        "    )\n"
        "    print('C05_RESUME ' + json.dumps(restored))\n"
        "asyncio.run(main())\n"
    )
    env = _child_env()
    env["C05_URL"] = database_url
    env["C05_SESSION"] = session_id
    env["C05_RUN"] = run_id
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    line = next(
        item for item in proc.stdout.splitlines() if item.startswith("C05_RESUME ")
    )
    return json.loads(line.removeprefix("C05_RESUME "))


@pytest.mark.asyncio
async def test_w2_c05_contract(postgres_url: str, tmp_path: Path):
    """A pure-read node survives a new process, and a second run does not share it."""
    session_id = "session-c05"
    run_a = "run-read-a"
    run_b = "run-read-b"
    marker = tmp_path / "side-effect.txt"
    await record_readonly_checkpoint(
        postgres_url,
        session_id=session_id,
        run_id=run_a,
        source="alpha-snapshot",
        marker=str(marker),
    )
    await record_readonly_checkpoint(
        postgres_url,
        session_id=session_id,
        run_id=run_b,
        source="beta-snapshot",
        marker=str(marker),
    )
    assert not marker.exists()
    restored = _resume_in_new_process(postgres_url, session_id, run_a)
    other = _resume_in_new_process(postgres_url, session_id, run_b)
    assert restored["observed"] == "alpha-snapshot"
    assert other["observed"] == "beta-snapshot"
    assert restored["thread_id"] == graph_thread_id(session_id, run_a)
    assert other["thread_id"] == graph_thread_id(session_id, run_b)
    assert restored["thread_id"] != other["thread_id"]
    assert "side" in restored["next"]
    assert not marker.exists()


@pytest.mark.asyncio
async def test_w2_c05_negative(tmp_path: Path):
    """An unavailable checkpointer does not start an unjournaled side effect."""
    marker = tmp_path / "unjournaled.txt"

    def effect() -> None:
        marker.write_text("wrote", encoding="utf-8")

    outcome = await accept_run(
        "postgresql://postgres@127.0.0.1:1/rxycode?connect_timeout=2",
        session_id="session-c05",
        run_id="run-closed",
        effect=effect,
    )
    assert outcome["started"] is False
    assert outcome["status"] == "recovery_required"
    assert not marker.exists()


def test_w2_c05_corrupt_journal(tmp_path: Path, postgres_url: str):
    """A damaged journal blocks the shell instead of guessing the outcome."""
    attempt_id = "att_" + "ab" * 16
    call_id = "call_" + "cd" * 16
    journal = ToolExecutionJournal(tmp_path / "journal")
    (journal.directory / f"{attempt_id}.json").write_text("{not-json", encoding="utf-8")
    marker = tmp_path / "corrupt-write.txt"
    outcome = recover_unknown_shell(
        postgres_url,
        tenant_id="tenant-c05",
        run_id="run-missing",
        call_id=call_id,
        attempt_id=attempt_id,
        command="Set-Content -LiteralPath 'corrupt-write.txt' -Value 'should-not-run'",
        workdir=str(tmp_path),
        journal=journal,
        worker_id="worker-c05",
        epoch=1,
    )
    assert outcome["executed"] is False
    assert outcome["journal_state"] == "unknown"
    assert not marker.exists()


def test_w2_c05_shell_requires_checkpointer(tmp_path: Path):
    """A closed database does not start the shell from the recovery helper."""
    marker = tmp_path / "closed.txt"
    journal = ToolExecutionJournal(tmp_path / "journal")
    outcome = run_shell_before_ack(
        "postgresql://postgres@127.0.0.1:1/rxycode?connect_timeout=2",
        tenant_id="tenant-c05",
        run_id="run-closed",
        call_id="call_" + "ab" * 16,
        attempt_id="att_" + "cd" * 16,
        command="Set-Content -LiteralPath 'closed.txt' -Value 'nope'",
        workdir=str(tmp_path),
        journal=journal,
        worker_id="worker-c05",
        epoch=1,
    )
    assert outcome["executed"] is False
    assert not marker.exists()


def test_w2_c05_remote_journal_states(tmp_path: Path):
    """Remote call ids use not_started, unknown, and completed without a second write."""
    journal = ToolExecutionJournal(tmp_path / "journal")
    adapter = RemoteJournalAdapter(journal)
    attempt_id = "att_" + "11" * 16
    call_id = "call_" + "22" * 16
    other_call = "call_" + "33" * 16
    args = {"cmd": "echo hi"}
    assert adapter.state(attempt_id=attempt_id, call_id=call_id) == "not_started"
    first = adapter.reserve(
        attempt_id=attempt_id,
        call_id=call_id,
        tool="shell",
        args=args,
    )
    assert first.action == "execute"
    assert adapter.state(attempt_id=attempt_id, call_id=call_id) == "unknown"
    blocked = adapter.reserve(
        attempt_id=attempt_id,
        call_id=other_call,
        tool="shell",
        args=args,
    )
    assert blocked.action == "uncertain"
    adapter.complete(
        attempt_id=attempt_id,
        call_id=call_id,
        tool="shell",
        args=args,
        result="ok",
    )
    assert adapter.state(attempt_id=attempt_id, call_id=call_id) == "completed"
    reused = adapter.reserve(
        attempt_id=attempt_id,
        call_id=call_id,
        tool="shell",
        args=args,
    )
    assert reused.action == "reuse"
    assert reused.result == "ok"
