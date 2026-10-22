"""WEB-W0-C03. Appserver wire events are consumed by the protocol client."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from appserver.emitter import model_to_notification
from execution.tool_journal import ToolExecutionJournal, new_attempt_id
from protocol.notifications import FinalAnswer, RecoveryStarted

REPO = Path(__file__).resolve().parents[3]
CLIENT = REPO / "frontend" / "protocol-client"


def test_w0_c03_integration(tmp_path: Path):
    """Recovery then final keeps method order when the old client reads the wire."""
    started = RecoveryStarted(
        session_id="ses-c03",
        run_id="run-c03",
        recovery_id="rec-1",
        event_id="evt-1",
        seq=1,
        timestamp="2026-10-16T00:00:00Z",
        source_call_id="call-1",
        recovery_kind="transport_retry",
        error_kind="timeout",
        max_attempts=2,
    )
    final = FinalAnswer(
        session_id="ses-c03",
        run_id="run-c03",
        text="done",
        session_schema_version=4,
    )
    payload = "\n".join(
        json.dumps(model_to_notification(item), ensure_ascii=False)
        for item in (started, final)
    )
    script = """
import { ProtocolClient } from "./src/client.ts";
const seen = [];
const client = new ProtocolClient(() => {});
client.onNotification = (method, params) => {
  seen.push({
    method,
    recovery_kind: params && params.recovery_kind ? params.recovery_kind : null,
    session_schema_version: params ? params.session_schema_version ?? null : null,
  });
};
const text = await new Response(Bun.stdin).text();
for (const line of text.split(String.fromCharCode(10)).filter((item) => item.length > 0)) {
  await client.handleLine(line);
}
console.log(JSON.stringify(seen));
"""
    from tests.support.pgurl import bun_path

    bun = bun_path()
    assert bun, "BLOCKED: bun is not installed"
    proc = subprocess.run(
        [bun, "-e", script],
        input=payload,
        text=True,
        capture_output=True,
        cwd=CLIENT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    seen = json.loads(proc.stdout)
    assert [item["method"] for item in seen] == [
        "event/recovery_started",
        "event/final",
    ]
    assert seen[0]["recovery_kind"] == "transport_retry"
    assert seen[1]["session_schema_version"] == 4

    journal = ToolExecutionJournal(tmp_path / "journal")
    attempt_id = new_attempt_id()
    binding = journal.binding(attempt_id)
    call = binding.next_call("write", {"path": "a.txt"})
    assert journal.reserve(attempt_id, call).action == "execute"
    assert journal.has_pending(attempt_id) is True
    retry = binding.next_call("write", {"path": "a.txt"})
    assert journal.reserve(attempt_id, retry).action == "uncertain"

    definitions = sorted(
        path.relative_to(REPO).as_posix()
        for path in (REPO / "execution").rglob("*.py")
        if "async def execute_tool" in path.read_text(encoding="utf-8")
    )
    assert definitions == ["execution/tool_orchestrator.py"]

    async def host_for_one_session() -> None:
        from appserver.server import AppServer

        server = AppServer(stub=True)
        first_record = server._sessions.create(tmp_path / "ws-host")
        first = await server._host_for_session(first_record.session_id)
        try:
            assert first.session_id == first_record.session_id
            assert await server._host_for_session(first_record.session_id) is first
            second_record = server._sessions.create(tmp_path / "ws-other")
            second = await server._host_for_session(second_record.session_id)
            try:
                assert second is not first
                assert second.session_id == second_record.session_id
            finally:
                await server._kill_session_host(second_record.session_id)
        finally:
            await server._kill_session_host(first_record.session_id)

    asyncio.run(host_for_one_session())
