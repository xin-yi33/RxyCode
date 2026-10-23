"""Controlled shell callers must expose bounded-output artifacts to tools."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


@pytest.fixture
def spill_result(tmp_path):
    spill = tmp_path / "data" / "spill" / "consumer-test"
    spill.mkdir(parents=True)
    artifact = spill / f"{uuid.uuid4().hex}.txt"
    artifact.write_bytes(b"complete raw output\n")
    return {
        "stdout": "bounded stdout preview",
        "stderr": "bounded stderr preview",
        "stdout_artifact": str(artifact),
        "stderr_artifact": None,
        "stdout_bytes": 100000,
        "stderr_bytes": 0,
        "stdout_truncated": True,
        "stderr_truncated": False,
        "capture_error": None,
        "exit_code": 0,
        "success": True,
        "error_type": None,
    }


def _assert_hint(output: str, spill_result) -> None:
    assert "bounded stdout preview" in output
    assert f"Full output saved to: {spill_result['stdout_artifact']}" in output


@pytest.mark.asyncio
async def test_workflow_consumes_artifact_metadata(tmp_path, monkeypatch, spill_result):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    monkeypatch.setattr(workflow, "_script_location", lambda: (tmp_path, str(tmp_path), ["python"]))
    monkeypatch.setattr(workflow, "load_config", lambda: {"execution": {"tool_timeout_seconds": 30}})

    async def execute(*_args, **_kwargs):
        return spill_result

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    output = await workflow._execute_script_async("pass", {}, timeout_seconds=10)

    _assert_hint(output, spill_result)


@pytest.mark.asyncio
async def test_git_consumes_artifact_metadata(tmp_path, monkeypatch, spill_result):
    from RxyCode.RxyCode1_1_0.tools import git_tool

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(git_tool, "resolve_session_path", lambda _path: repo)

    async def execute(*_args, **_kwargs):
        return spill_result

    monkeypatch.setattr(git_tool.shell_executor, "execute_argv_async", execute)
    output = await git_tool.run_git_async()

    _assert_hint(output, spill_result)


@pytest.mark.asyncio
async def test_formatter_consumes_artifact_metadata(tmp_path, monkeypatch, spill_result):
    from RxyCode.RxyCode1_1_0.tools import format_tool

    source = tmp_path / "example.py"
    source.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(format_tool, "resolve_session_path", lambda _path: source)
    from RxyCode.RxyCode1_1_0.utils import shell

    async def execute(*_args, **_kwargs):
        return spill_result

    monkeypatch.setattr(shell.shell_executor, "execute_argv_async", execute)
    output = await format_tool.run_format_async("example.py", tool="black")

    _assert_hint(output, spill_result)


@pytest.mark.asyncio
async def test_installer_consumes_artifact_metadata(monkeypatch, spill_result):
    from RxyCode.RxyCode1_1_0.tools import installer
    from RxyCode.RxyCode1_1_0.utils import shell

    async def execute(*_args, **_kwargs):
        return spill_result

    monkeypatch.setattr(shell.shell_executor, "execute_argv_async", execute)
    success, output = await installer.ToolInstaller().install_package_async("demo")

    assert success is True
    _assert_hint(output, spill_result)


@pytest.mark.asyncio
async def test_mcp_installs_consume_artifact_metadata(monkeypatch, spill_result):
    from RxyCode.RxyCode1_1_0.tools import mcp_manager
    from RxyCode.RxyCode1_1_0.utils import shell

    async def execute(*_args, **_kwargs):
        return spill_result

    monkeypatch.setattr(shell.shell_executor, "execute_argv_async", execute)
    monkeypatch.setattr(mcp_manager, "add_mcp_server", lambda **_kwargs: (True, "MCP server added"))

    npm_success, npm_output = await mcp_manager.install_mcp_from_npm_async("demo")
    pip_success, pip_output = await mcp_manager.install_mcp_from_pip_async("demo")

    assert npm_success and pip_success
    assert "MCP server added" in npm_output and "MCP server added" in pip_output
    assert f"Full output saved to: {spill_result['stdout_artifact']}" in npm_output
    assert f"Full output saved to: {spill_result['stdout_artifact']}" in pip_output


@pytest.mark.asyncio
async def test_vision_and_open_file_consume_artifact_metadata(
    tmp_path, monkeypatch, spill_result
):
    from RxyCode.RxyCode1_1_0.tools import open_file, vision
    from RxyCode.RxyCode1_1_0.utils import shell

    async def execute(*_args, **_kwargs):
        return spill_result

    monkeypatch.setattr(shell.shell_executor, "execute_argv_async", execute)
    monkeypatch.setattr(vision, "_interactive_desktop_available", lambda: True)
    monkeypatch.setattr(vision, "_capture_candidates", lambda: (["capture"], ["fallback"]))
    monkeypatch.delenv("RXYCODE_DISABLE_SCREEN_CAPTURE", raising=False)
    monkeypatch.setenv("RXYCODE_SCREEN_CAPTURE_TIMEOUT", "5")
    vision_output = await vision._capture_screenshot_async()

    target = tmp_path / "preview.txt"
    target.write_text("preview", encoding="utf-8")
    monkeypatch.setattr(open_file.sys, "platform", "linux")
    monkeypatch.setattr(open_file, "resolve_session_path", lambda _path: target)
    file_output = await open_file.open_file_async(str(target))

    _assert_hint(vision_output, spill_result)
    assert f"Full output saved to: {spill_result['stdout_artifact']}" in file_output
    assert file_output.startswith("[opened ")


def test_capture_hint_reports_failed_spill_without_claiming_an_artifact():
    from RxyCode.RxyCode1_1_0.utils.output_capture import append_capture_hints

    result = {
        "stdout_artifact": None,
        "stderr_artifact": None,
        "capture_error": "stdout spill write failed (OSError)",
    }

    output = append_capture_hints("bounded preview", result)

    assert output.startswith("bounded preview\n")
    assert "output capture failed" in output
    assert "Full output saved to:" not in output
