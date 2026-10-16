"""WEB-W4-C04. A repeated call_id replays the result and does not run twice."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for entry in (str(REPO), str(_RUNNER), str(_WORKER)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _ids() -> tuple[str, str]:
    return f"att_{uuid4().hex}", f"call_{uuid4().hex}"


def test_w4_c04_contract(tmp_path: Path) -> None:
    """A second invoke of a completed call returns the first result."""
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_runner.transport.tool_rpc import serve_tool_rpc
    from rxycode_worker.runner_client import RunnerClient

    writes: list[str] = []

    def execute(args: dict[str, object], *, cancel: threading.Event) -> str:
        del cancel
        target = tmp_path / "note.txt"
        target.write_text("once", encoding="utf-8")
        writes.append(str(args["marker"]))
        return "once"

    journal = RemoteJournalAdapter(ToolExecutionJournal(tmp_path / "journal"))
    server = serve_tool_rpc(device_id="desk-1", journal=journal, execute=execute)
    client = RunnerClient()
    attempt_id, call_id = _ids()
    try:
        first = client.invoke(
            url=server.url,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"marker": "a"},
        )
        second = client.invoke(
            url=server.url,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"marker": "a"},
        )
        assert first.state == "completed"
        assert first.result == "once"
        assert second.state == "completed"
        assert second.result == "once"
        assert writes == ["a"]
        assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "once"
    finally:
        server.close()


def test_w4_c04_negative(tmp_path: Path) -> None:
    """A lost result ack stays unknown and does not write again."""
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_runner.transport.tool_rpc import serve_tool_rpc
    from rxycode_worker.runner_client import RunnerClient

    target = tmp_path / "side.txt"
    writes: list[int] = []
    started = threading.Event()
    released = threading.Event()

    def execute(args: dict[str, object], *, cancel: threading.Event) -> str:
        if args.get("mode") == "cancel":
            started.set()
            cancel.wait(3)
            return "stopped"
        writes.append(1)
        previous = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(previous + "W", encoding="utf-8")
        return "W"

    journal = RemoteJournalAdapter(ToolExecutionJournal(tmp_path / "journal"))
    server = serve_tool_rpc(device_id="desk-1", journal=journal, execute=execute)
    client = RunnerClient()
    attempt_id, call_id = _ids()
    try:
        dropped = client.invoke(
            url=server.url,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"mode": "write"},
            ack=False,
        )
        assert dropped.state == "unacked"
        assert target.read_text(encoding="utf-8") == "W"
        retried = client.invoke(
            url=server.url,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"mode": "write"},
        )
        assert retried.state == "recovery_required"
        assert writes == [1]
        assert target.read_text(encoding="utf-8") == "W"
        cancel_attempt, cancel_call = _ids()
        cancelled = client.invoke_and_cancel(
            url=server.url,
            device_id="desk-1",
            call_id=cancel_call,
            attempt_id=cancel_attempt,
            tool="write",
            args={"mode": "cancel"},
            started=started,
        )
        assert cancelled.state == "cancelled"
        assert target.read_text(encoding="utf-8") == "W"
        released.set()
    finally:
        server.close()
