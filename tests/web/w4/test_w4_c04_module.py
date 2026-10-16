"""WEB-W4-C04. Reconnect dedups chunk sequence numbers."""

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


def test_w4_c04_integration(tmp_path: Path) -> None:
    """After a drop, chunk seq is replayed once and the write does not repeat."""
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_runner.transport.tool_rpc import CHUNK_LIMIT, serve_tool_rpc
    from rxycode_worker.runner_client import RunnerClient

    writes: list[int] = []
    body = "abc" * (CHUNK_LIMIT + 1)

    def execute(args: dict[str, object], *, cancel: threading.Event) -> str:
        del args, cancel
        writes.append(1)
        assert server.writer_count() == 1
        target = tmp_path / "note.txt"
        target.write_text("hello-once", encoding="utf-8")
        return body

    journal = RemoteJournalAdapter(ToolExecutionJournal(tmp_path / "journal"))
    server = serve_tool_rpc(device_id="desk-1", journal=journal, execute=execute)
    client = RunnerClient()
    attempt_id = f"att_{uuid4().hex}"
    call_id = f"call_{uuid4().hex}"
    try:
        partial = client.invoke(
            url=server.url,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"marker": "stream"},
            ack=False,
            stop_after_chunks=2,
        )
        assert [item[0] for item in partial.chunks] == [1, 2]
        assert all(len(item[1]) <= CHUNK_LIMIT for item in partial.chunks)
        resumed = client.resume(
            url=server.url,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            tool="write",
            args={"marker": "stream"},
            resume_from=2,
        )
        seqs = [item[0] for item in resumed.chunks]
        assert len(seqs) == len(set(seqs))
        assert all(seq > 2 for seq in seqs)
        replayed = "".join(item[1] for item in partial.chunks + resumed.chunks)
        assert replayed == body or resumed.truncated
        assert writes == [1]
        assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello-once"
    finally:
        server.close()
