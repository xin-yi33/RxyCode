"""PhaseG-B13 release bind, update rollback, crash redaction, handshake."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.release import ReleaseError, ReleaseService, host_platform
from appserver.server import AppServer
from protocol.handshake import PackageCompatibility
from protocol.schema import export_schema
from protocol.version import APPSERVER_VERSION, PROTOCOL_VERSION


def test_compatibility_bind() -> None:
    service = ReleaseService()
    info = service.compatibility()
    assert info["platform"] in {"windows", "macos", "linux"}
    assert host_platform() == info["platform"]
    assert info["appserver_version"] == APPSERVER_VERSION
    assert info["protocol_version"] == PROTOCOL_VERSION
    assert info["schema_digest"].startswith("sha256:")
    assert set(info["runtimes"]) == {"windows", "macos", "linux"}
    assert info["compatible"] is True
    mismatch = service.diagnose_mismatch({"protocol_version": "9.9.9"})
    assert mismatch["ok"] is False
    assert "PROTOCOL_MISMATCH" in mismatch["reasons"]


def test_update_failure_keeps_previous(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path)
    service.stage_update({"version": "1"})
    first = service.stage_update({"label": "1"})
    old = (service.current_dir / "manifest.json").read_text(encoding="utf-8")
    with pytest.raises(ReleaseError) as exc:
        service.stage_update({"label": "2"}, fail=True)
    assert exc.value.code == "UPDATE_FAILED"
    assert (service.current_dir / "manifest.json").read_text(encoding="utf-8") == old
    assert first["previous_kept"] is True or (tmp_path / "CURRENT.txt").is_file()
    service.stage_update({"label": "2"})
    rolled = service.rollback()
    assert rolled["ok"] is True
    assert "label" in (service.current_dir / "manifest.json").read_text(encoding="utf-8")


def test_crash_report_redacts_secret_prompt_and_tool() -> None:
    service = ReleaseService()
    report = service.crash_report(
        secret="sk-b13-secret-zzzz",
        prompt="full user prompt text here",
        tool_output="cat /etc/passwd output",
        traceback="boom sk-b13-secret-zzzz full user prompt text here cat /etc/passwd output",
    )
    blob = str(report)
    assert "sk-b13-secret-zzzz" not in blob
    assert "full user prompt text here" not in blob
    assert "cat /etc/passwd output" not in blob
    assert report["prompt"] == "[REDACTED]"


def test_diagnose_bundle_has_checksums(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path)
    service.stage_update({"label": "1"})
    bundle = service.diagnose_bundle()
    assert "manifest.json" in bundle["checksums"]
    assert (service.current_dir / "CHECKSUMS.json").is_file()
    signed = service.sign_entry(service.current_dir / "manifest.json")
    assert signed["signed"] is False
    assert signed["digest"].startswith("sha256:")


@pytest.mark.asyncio
async def test_real_handshake_includes_package(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    await server._handle_initialize(
        {
            "client_name": "test",
            "client_version": "1.3.0",
            "protocol_version": PROTOCOL_VERSION,
        },
        1,
    )
    result = next(item["result"] for item in sent if "result" in item)
    assert result["package"]["appserver_version"] == APPSERVER_VERSION
    assert result["package"]["protocol_version"] == PROTOCOL_VERSION
    PackageCompatibility.model_validate(result["package"])


def test_process_handshake(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    env = dict(**__import__("os").environ)
    env.pop("RXYCODE_APPSERVER_STUB", None)
    env["RXYCODE_DATA_DIR"] = str(tmp_path)
    env["RXYCODE_APPSERVER_LOCK"] = str(tmp_path / "lock")
    proc = subprocess.Popen(
        [sys.executable, "-m", "appserver"],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "client_name": "release-test",
            "client_version": "1.3.0",
            "protocol_version": PROTOCOL_VERSION,
        },
    }
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        payload = None
        for _ in range(20):
            line = proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if "result" in message:
                payload = message
                break
        assert payload is not None
        assert payload["result"]["package"]["protocol_version"] == PROTOCOL_VERSION
        diag = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "release/diagnose",
            "params": {"protocol_version": "0.0.1"},
        }
        proc.stdin.write(json.dumps(diag) + "\n")
        proc.stdin.flush()
        diagnosed = None
        for _ in range(20):
            line = proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message.get("id") == 2:
                diagnosed = message
                break
        assert diagnosed is not None
        assert diagnosed["result"]["ok"] is False
    finally:
        proc.kill()


def test_schema_has_release_and_package() -> None:
    defs = export_schema()["$defs"]
    assert "PackageCompatibility" in defs
    assert "ReleaseStatusRequest" in defs
    assert "ReleaseDiagnoseRequest" in defs
