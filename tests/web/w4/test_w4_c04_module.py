"""WEB-W4-C04. Reconnect dedups chunk sequence numbers."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx

_SECRET = "local-web-secret-value-32bytes!!"
REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
for entry in (str(REPO), str(_RUNNER), str(_WORKER), str(_SERVER)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def test_w4_c04_integration(tmp_path: Path) -> None:
    """After the device socket drops, later chunk seqs are replayed once."""
    from click.testing import CliRunner
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from RxyCode.RxyCode1_1_0.main import cli
    from rxycode_runner.remote.client import request_stop, reset_stop
    from rxycode_runner.transport.tool_rpc import CHUNK_LIMIT, clear_local_tools
    from rxycode_server.devices.gateway import serve_in_thread
    from rxycode_worker.supervisor import attempt_tool, resume_device_tool

    body = "你" * 5000
    note = tmp_path / "note.txt"
    gateway = serve_in_thread(secret=_SECRET)
    reset_stop()
    browser = gateway.browser_session("tenant-a")
    csrf = "csrf-token-value-for-c04"
    issued = httpx.post(
        f"{gateway.http}/api/v1/devices/pairings",
        headers={"Origin": gateway.http, "X-CSRF-Token": csrf},
        cookies={"rxy_session": browser, "rxy_csrf": csrf},
        timeout=5,
    )
    code = issued.json()["code"]
    thread = threading.Thread(
        target=lambda: CliRunner().invoke(
            cli,
            [
                "connect",
                "--url",
                gateway.ws,
                "--code",
                code,
                "--device-id",
                "desk-1",
                "--os-name",
                "Windows",
                "--capability",
                "click",
                "--heartbeat-seconds",
                "0.2",
            ],
        )
    )
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline and not gateway.session_id("desk-1"):
        time.sleep(0.05)
    attempt_id = f"att_{uuid4().hex}"
    call_id = f"call_{uuid4().hex}"
    try:
        assert gateway.session_id("desk-1")
        partial = attempt_tool(
            None, attempt_id, "write",
            {"path": str(note), "text": "hello-once", "body": body}, None,
            gateway=gateway, device_id="desk-1", call_id=call_id,
            ack=False, stop_after_chunks=2,
        )
        assert [item[0] for item in partial["chunks"]] == [1, 2]
        assert all(len(item[1].encode("utf-8")) <= CHUNK_LIMIT for item in partial["chunks"])
        first_session = gateway.session_id("desk-1")
        gateway.drop()
        second_session = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            second_session = gateway.session_id("desk-1")
            if second_session and second_session != first_session:
                break
            time.sleep(0.05)
        assert second_session and second_session != first_session
        resumed = resume_device_tool(
            gateway=gateway,
            device_id="desk-1",
            call_id=call_id,
            attempt_id=attempt_id,
            resume_from=2,
        )
        seqs = [item[0] for item in resumed.chunks]
        assert seqs
        assert len(seqs) == len(set(seqs))
        assert all(seq > 2 for seq in seqs)
        merged: dict[int, str] = {}
        for seq, data in partial["chunks"] + resumed.chunks:
            merged.setdefault(seq, data)
        replayed = "".join(merged[seq] for seq in sorted(merged))
        assert replayed == body or resumed.truncated
        assert all(len(item.encode("utf-8")) <= CHUNK_LIMIT for item in merged.values())
        assert note.read_text(encoding="utf-8") == "hello-once"
    finally:
        request_stop()
        thread.join(5)
        gateway.close()
        clear_local_tools("desk-1")
