"""Pure state-machine regressions for the clipboard broker.

These tests use an in-memory request spy and never import or call Windows
clipboard APIs. The actual OS-clipboard suite lives in a separate opt-in file.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from .clipboard_broker import (
    ClipboardBroker,
    ClipboardSafetyError,
    ExternalClipboardModificationError,
    _POWERSHELL,
    _EMPTY_SHA256,
    _helper_command,
    _verified_snapshot,
    _write_helper_script,
)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


ORIGINAL = {
    "format_count": 2,
    "formats_sha256": _digest(b"original formats"),
    "contents_sha256": _digest(b"original contents"),
}
TEST_TEXT = {
    "format_count": 1,
    "formats_sha256": _digest(b"UnicodeText"),
    "contents_sha256": _digest(b"synthetic test text"),
}


class ClipboardSpy:
    """Respond to broker protocol messages without touching the OS clipboard."""

    def __init__(self, snapshot_response: Any, replies: dict[str, Any] | None = None) -> None:
        self.snapshot_response = snapshot_response
        self.replies = replies or {}
        self.requests: list[dict[str, Any]] = []
        self.close_count = 0

    def request(self, row: dict[str, Any]) -> dict[str, Any] | None:
        self.requests.append(dict(row))
        op = row["op"]
        response = self.snapshot_response if op == "snapshot" else self.replies.get(op)
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self) -> None:
        self.close_count += 1

    @property
    def operations(self) -> list[str]:
        return [str(row["op"]) for row in self.requests]


def _backup(sequence: int = 647) -> dict[str, Any]:
    return {"ok": True, "op": "snapshot", "snapshot": dict(ORIGINAL), "sequence": sequence}


@pytest.mark.unit
@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("synthetic backup exception"),
        None,
        {
            "ok": False,
            "op": "snapshot",
            "error_type": "System.NotSupportedException",
            "error_code": "unsupported_clipboard_format",
            "error_stage": "snapshot-copy-value",
        },
        {"ok": True, "op": "snapshot", "snapshot": {"format_count": 1}, "sequence": 647},
        {
            "ok": True,
            "op": "snapshot",
            "snapshot": {
                **ORIGINAL,
                "value": "SYNTHETIC_MUST_NOT_BE_PERSISTED",
            },
            "sequence": 647,
        },
    ],
    ids=[
        "backup-exception",
        "nil-response",
        "unknown-format",
        "incomplete-snapshot",
        "snapshot-with-unexpected-field",
    ],
)
def test_unverified_backup_closes_helper_without_any_write_or_restore(
    tmp_path: Path, response: Any
) -> None:
    spy = ClipboardSpy(response)

    expected_error = RuntimeError if isinstance(response, BaseException) else ClipboardSafetyError
    with pytest.raises(expected_error):
        ClipboardBroker(tmp_path, _backend=spy)

    evidence = json.loads((tmp_path / "clipboard-safety.json").read_text(encoding="utf-8"))
    evidence_text = (tmp_path / "clipboard-safety.json").read_text(encoding="utf-8")
    assert evidence["status"] == "backup-unverified"
    assert evidence["ready"] is False
    assert evidence["restored"] is False
    assert evidence["original_snapshot"] is None
    assert evidence["content_values_persisted"] is False
    assert "SYNTHETIC_MUST_NOT_BE_PERSISTED" not in evidence_text
    failure = evidence["construction_error"]
    assert failure["op"] == "snapshot"
    assert failure["ready"] is False
    assert failure["error_type"]
    assert failure["error_code"]
    assert failure["error_stage"]
    if isinstance(response, dict) and response.get("error_stage"):
        assert failure["error_stage"] == "snapshot-copy-value"

    assert spy.operations == ["snapshot"]
    assert not any(op in {"set_files", "set_text", "set_image", "clear", "restore"} for op in spy.operations)
    assert spy.close_count == 1, "failed construction must not leave its helper/backend alive"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error_code", "error_stage", "native_count", "managed_count"),
    [
        (
            "zero_native_formats_managed_formats_present",
            "snapshot-zero-native-managed-formats",
            0,
            2,
        ),
        (
            "nonempty_native_formats_managed_formats_empty",
            "snapshot-nonempty-native-managed-formats-empty",
            2,
            0,
        ),
    ],
)
def test_format_count_disagreement_evidence_is_specific_and_numeric_only(
    tmp_path: Path,
    error_code: str,
    error_stage: str,
    native_count: int,
    managed_count: int,
) -> None:
    private_marker = "SYNTHETIC_PRIVATE_CLIPBOARD_VALUE"
    spy = ClipboardSpy(
        {
            "ok": False,
            "op": "snapshot",
            "error_type": "System.Management.Automation.RuntimeException",
            "error_code": error_code,
            "error_stage": error_stage,
            "native_format_count": native_count,
            "managed_format_count": managed_count,
            "format_name": private_marker,
            "payload": private_marker,
        }
    )

    with pytest.raises(ClipboardSafetyError):
        ClipboardBroker(tmp_path, _backend=spy)

    evidence_path = tmp_path / "clipboard-safety.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_text = evidence_path.read_text(encoding="utf-8")
    failure = evidence["construction_error"]
    assert failure == {
        "op": "snapshot",
        "error_type": "System.Management.Automation.RuntimeException",
        "error_code": error_code,
        "error_stage": error_stage,
        "ready": False,
        "native_format_count": native_count,
        "managed_format_count": managed_count,
    }
    assert private_marker not in evidence_text
    assert evidence["ready"] is False
    assert evidence["restored"] is False
    assert evidence["original_snapshot"] is None
    assert spy.operations == ["snapshot"]
    assert spy.close_count == 1


@pytest.mark.unit
def test_external_sequence_change_skips_restore_and_closes_only_the_owned_helper(
    tmp_path: Path,
) -> None:
    spy = ClipboardSpy(
        _backup(),
        {
            "set_text": {
                "ok": False,
                "op": "set_text",
                "external_change": True,
                "sequence": 648,
            }
        },
    )

    with pytest.raises(ExternalClipboardModificationError):
        with ClipboardBroker(tmp_path, _backend=spy) as broker:
            broker.set_text("synthetic fixture only")

    assert spy.operations == ["snapshot", "set_text"]
    assert spy.operations.count("restore") == 0
    assert spy.close_count == 1, "ownership loss must not retain a helper process"


@pytest.mark.unit
def test_verified_restore_runs_once_and_matches_exact_backup_without_sequence_delta_assumption(
    tmp_path: Path,
) -> None:
    # Sequence values deliberately jump by arbitrary amounts. The Win32 API
    # does not promise one increment per clipboard API call.
    spy = ClipboardSpy(
        _backup(647),
        {
            "set_text": {
                "ok": True,
                "op": "set_text",
                "sequence": 683,
                "snapshot": dict(TEST_TEXT),
                "empty_clipboard_verified": False,
            },
            "restore": {
                "ok": True,
                "op": "restore",
                "restored": True,
                "snapshot": dict(ORIGINAL),
                "original_sequence": 647,
                "owned_sequence": 731,
                "restored_sequence": 731,
                "empty_clipboard_verified": False,
            },
        },
    )

    with ClipboardBroker(tmp_path, _backend=spy) as broker:
        broker.set_text("synthetic fixture only")

    assert broker.restored is True
    assert broker.backup == ORIGINAL
    assert spy.operations == ["snapshot", "set_text", "restore"]
    assert spy.operations.count("restore") == 1
    assert spy.close_count == 1


@pytest.mark.unit
def test_empty_snapshot_requires_explicit_native_empty_verification() -> None:
    empty = {
        "format_count": 0,
        "formats_sha256": _EMPTY_SHA256,
        "contents_sha256": _EMPTY_SHA256,
    }

    assert _verified_snapshot(empty, 647, empty_verified=True)
    assert not _verified_snapshot(empty, 647, empty_verified=False)
    assert not _verified_snapshot({**empty, "contents_sha256": _digest(b"unknown")}, 647, empty_verified=True)
    assert not _verified_snapshot(empty, 0, empty_verified=True)
    assert not _verified_snapshot(
        {"format_count": 1, "formats_sha256": _EMPTY_SHA256, "contents_sha256": _EMPTY_SHA256},
        647,
        empty_verified=False,
    )


@pytest.mark.unit
def test_verified_empty_clipboard_backup_does_not_issue_a_clipboard_write(tmp_path: Path) -> None:
    empty = {
        "format_count": 0,
        "formats_sha256": _EMPTY_SHA256,
        "contents_sha256": _EMPTY_SHA256,
    }
    spy = ClipboardSpy(
        {
            "ok": True,
            "op": "snapshot",
            "snapshot": dict(empty),
            "sequence": 647,
            "empty_clipboard_verified": True,
        },
        {
            "restore": {
                "ok": True,
                "op": "restore",
                "restored": True,
                "snapshot": dict(empty),
                "original_sequence": 647,
                "owned_sequence": 647,
                "restored_sequence": 647,
                "empty_clipboard_verified": True,
                "clipboard_write_skipped": True,
            }
        },
    )

    with ClipboardBroker(tmp_path, _backend=spy) as broker:
        pass

    assert broker.restored is True
    assert spy.operations == ["snapshot", "restore"]
    assert spy.close_count == 1


@pytest.mark.unit
@pytest.mark.skipif(os.name != "nt", reason="the PowerShell STA actor is Windows-only")
def test_helper_actor_starts_from_runtime_file_and_answers_ping_without_clipboard_ops(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe") or "powershell.exe"
    script_path = _write_helper_script(tmp_path)
    command = _helper_command(powershell, script_path)
    assert "-File" in command
    assert "-EncodedCommand" not in command
    assert command[-1] == str(script_path.resolve())
    ping_branch = _POWERSHELL.split("      'ping' {", 1)[1].split("      'snapshot' {", 1)[0]
    assert "Clipboard" not in ping_branch and "Get-Sequence" not in ping_branch
    command_line = subprocess.list2cmdline(command)
    assert len(command_line.encode("utf-16le")) // 2 + 1 <= 32767
    assert script_path.parent == tmp_path.resolve()

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        bufsize=1,
    )
    rows: queue.Queue[str | None] = queue.Queue()

    def read_stdout() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                rows.put(line)
        finally:
            rows.put(None)

    reader = threading.Thread(target=read_stdout, name="clipboard-helper-ping-test", daemon=True)
    reader.start()
    sent_ops: list[str] = []
    try:
        assert process.stdin is not None
        sent_ops.append("ping")
        process.stdin.write(json.dumps({"op": "ping", "request_id": "startup-ping"}) + "\n")
        process.stdin.flush()
        response_line = rows.get(timeout=20)
        if response_line is None:
            process.wait(timeout=5)
            error_output = process.stderr.read() if process.stderr is not None else ""
            pytest.fail(f"PowerShell actor exited before ping (exit={process.returncode}): {error_output}")
        response = json.loads(response_line)
        assert response["ok"] is True and response["op"] == "ping"
        assert response["request_id"] == "startup-ping"

        sent_ops.append("quit")
        process.stdin.write(json.dumps({"op": "quit", "request_id": "startup-quit"}) + "\n")
        process.stdin.flush()
        quit_line = rows.get(timeout=5)
        assert quit_line is not None, "PowerShell actor exited before returning the pure quit response"
        quit_response = json.loads(quit_line)
        assert quit_response["ok"] is True and quit_response["op"] == "quit"
        assert process.wait(timeout=5) == 0
        assert sent_ops == ["ping", "quit"]
        assert not any(op in {"snapshot", "set_files", "set_text", "set_image", "clear", "restore"} for op in sent_ops)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        reader.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
