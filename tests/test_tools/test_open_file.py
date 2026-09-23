from __future__ import annotations

import asyncio
import webbrowser
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, get_tool_risk
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools import open_file as open_file_module
from RxyCode.RxyCode1_1_0.utils import shell as shell_module


def _mock_host_openers(monkeypatch):
    startfile = MagicMock()
    subprocess_run = MagicMock(return_value=SimpleNamespace(returncode=0, stderr=""))
    popen = MagicMock()
    popen.return_value = SimpleNamespace(pid=4242)
    browser_open = MagicMock()
    async_opener = AsyncMock(return_value={"success": True, "stdout": "", "stderr": ""})
    monkeypatch.setattr(open_file_module.os, "startfile", startfile, raising=False)
    monkeypatch.setattr(open_file_module.subprocess, "run", subprocess_run)
    monkeypatch.setattr(open_file_module.subprocess, "Popen", popen)
    monkeypatch.setattr(webbrowser, "open", browser_open)
    monkeypatch.setattr(shell_module.shell_executor, "execute_argv_async", async_opener)
    return startfile, subprocess_run, popen, browser_open, async_opener


def _assert_windows_split_start(popen, target):
    popen.assert_called_once()
    args, kwargs = popen.call_args
    argv = args[0]
    assert argv[:4] == ["cmd.exe", "/c", "start", "RxyCode Open"]
    opened = argv[4]
    assert opened.endswith(target.name)
    assert opened != "\\\\"
    assert not opened.startswith("\\\\?\\")
    assert "/s" not in argv
    assert kwargs["stdin"] is open_file_module.subprocess.DEVNULL
    flags = int(kwargs["creationflags"])
    no_window = int(getattr(open_file_module.subprocess, "CREATE_NO_WINDOW", 0x08000000))
    assert flags & no_window == 0


def test_open_file_rejects_missing_path(monkeypatch, tmp_path):
    startfile, subprocess_run, popen, browser_open, _ = _mock_host_openers(monkeypatch)

    result = open_file_module.open_file(str(tmp_path / "missing.html"))

    assert "file not found" in result
    startfile.assert_not_called()
    subprocess_run.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()


@pytest.mark.parametrize(
    ("platform", "opener"),
    [("win32", None), ("darwin", "open"), ("linux", "xdg-open")],
)
def test_open_file_uses_platform_default_application(
    monkeypatch, tmp_path, platform, opener
):
    target = tmp_path / "page.HTML"
    target.write_text("<html><body>ok</body></html>", encoding="utf-8")
    startfile, subprocess_run, popen, browser_open, _ = _mock_host_openers(monkeypatch)
    monkeypatch.setattr(open_file_module.sys, "platform", platform)

    result = open_file_module.open_file(str(target))

    assert result.startswith("[opened ")
    browser_open.assert_not_called()
    if platform == "win32":
        startfile.assert_not_called()
        subprocess_run.assert_not_called()
        _assert_windows_split_start(popen, target)
    else:
        startfile.assert_not_called()
        popen.assert_not_called()
        assert subprocess_run.call_count == 1
        args, kwargs = subprocess_run.call_args
        assert args[0] == [opener, str(target.resolve())]
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 10


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize(
    "filename",
    [
        "payload.exe",
        "payload.EXE",
        "payload.bat",
        "payload.cmd",
        "payload.ps1",
        "payload.lnk",
        "payload.sh",
        "payload.py",
        "payload.js",
        "report.pdf.exe",
        "payload.cmd.HTML",
        "payload.ExE.pdf",
        "archive.unknown",
        "README",
    ],
)
def test_open_file_rejects_non_previewable_files_before_any_host_call(
    monkeypatch, tmp_path, platform, filename
):
    target = tmp_path / filename
    target.write_text("untrusted", encoding="utf-8")
    startfile, subprocess_run, popen, browser_open, async_opener = _mock_host_openers(
        monkeypatch
    )
    monkeypatch.setattr(open_file_module.sys, "platform", platform)

    result = open_file_module.open_file(str(target))

    assert result.startswith("[blocked:")
    startfile.assert_not_called()
    subprocess_run.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()
    async_opener.assert_not_awaited()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_open_file_rejects_directory_before_any_host_call(
    monkeypatch, tmp_path, platform
):
    directory = tmp_path / "report.pdf"
    directory.mkdir()
    startfile, subprocess_run, popen, browser_open, async_opener = _mock_host_openers(
        monkeypatch
    )
    monkeypatch.setattr(open_file_module.sys, "platform", platform)

    result = open_file_module.open_file(str(directory))

    assert "not a regular file" in result
    startfile.assert_not_called()
    subprocess_run.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()
    async_opener.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
async def test_open_file_async_rejects_before_any_host_call(
    monkeypatch, tmp_path, platform
):
    target = tmp_path / "payload.CmD.html"
    target.write_text("untrusted", encoding="utf-8")
    startfile, subprocess_run, popen, browser_open, async_opener = _mock_host_openers(
        monkeypatch
    )
    monkeypatch.setattr(open_file_module.sys, "platform", platform)

    result = await open_file_module.open_file_async(str(target))

    assert result.startswith("[blocked:")
    startfile.assert_not_called()
    subprocess_run.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()
    async_opener.assert_not_awaited()


def test_open_file_resolves_symlink_before_validating_extension(monkeypatch, tmp_path):
    payload = tmp_path / "payload.exe"
    payload.write_bytes(b"not really executable")
    link = tmp_path / "report.pdf"
    try:
        link.symlink_to(payload)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    startfile, subprocess_run, popen, browser_open, async_opener = _mock_host_openers(
        monkeypatch
    )
    monkeypatch.setattr(open_file_module.sys, "platform", "win32")

    result = open_file_module.open_file(str(link))

    assert "extension .exe" in result
    startfile.assert_not_called()
    subprocess_run.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()
    async_opener.assert_not_awaited()


def test_open_file_is_write_risk():
    assert get_tool_risk("open_file") == RiskLevel.WRITE


def test_open_file_execution_produces_verifiable_evidence(monkeypatch, tmp_path):
    target = tmp_path / "page.html"
    target.write_text("<html><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setattr(open_file_module.sys, "platform", "win32")
    _mock_host_openers(monkeypatch)

    orch = ToolOrchestrator()
    orch.register("open_file", open_file_module.open_file_tool)
    token = orch.begin_evidence_capture()
    result = asyncio.run(
        orch.execute_tool(
            "open_file",
            {"filePath": str(target)},
            {"safety": {"enabled": False}},
        )
    )
    evidence = orch.end_evidence_capture(token)

    assert result.startswith("[opened ")
    assert len(evidence) == 1
    assert evidence[0].tool == "open_file"
    assert evidence[0].passed is True


def test_open_file_keeps_workspace_write_path_gate(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside" / "page.html"
    outside.parent.mkdir()
    outside.write_text("<html></html>", encoding="utf-8")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(open_file_module.sys, "platform", "win32")
    startfile, subprocess_run, popen, browser_open, async_opener = _mock_host_openers(
        monkeypatch
    )

    orch = ToolOrchestrator()
    orch.register("open_file", open_file_module.open_file_tool)
    result = asyncio.run(
        orch.execute_tool(
            "open_file",
            {"filePath": str(outside)},
            {"safety": {"enabled": True, "auto_approve": ["write"]}},
        )
    )

    assert "write path not allowed" in result
    startfile.assert_not_called()
    popen.assert_not_called()
    assert not any(
        call.args
        and isinstance(call.args[0], list)
        and call.args[0]
        and call.args[0][0] in {"open", "xdg-open"}
        for call in subprocess_run.call_args_list
    )
    browser_open.assert_not_called()
    async_opener.assert_not_awaited()


def test_windows_shell_path_strips_extended_prefix() -> None:
    assert open_file_module._windows_shell_path(
        r"\\?\C:\Users\Administrator\.rxycode\workspace\open_e2e_demo.html"
    ) == r"C:\Users\Administrator\.rxycode\workspace\open_e2e_demo.html"
    assert open_file_module._windows_shell_path(
        r"C:\Users\Administrator\.rxycode\workspace\open_e2e_demo.html"
    ) == r"C:\Users\Administrator\.rxycode\workspace\open_e2e_demo.html"
    assert open_file_module._windows_shell_path(
        r"\\?\UNC\server\share\file.html"
    ) == r"\\server\share\file.html"


def test_open_file_windows_uses_split_start_argv(monkeypatch, tmp_path) -> None:
    target = tmp_path / "open_e2e_demo.html"
    target.write_text(
        "<html><title>打开测试E1</title><body>打开测试E1</body></html>",
        encoding="utf-8",
    )
    startfile, subprocess_run, popen, browser_open, _ = _mock_host_openers(monkeypatch)
    monkeypatch.setattr(open_file_module.sys, "platform", "win32")

    result = open_file_module.open_file(str(target))

    assert result.startswith("[opened ")
    startfile.assert_not_called()
    subprocess_run.assert_not_called()
    browser_open.assert_not_called()
    _assert_windows_split_start(popen, target)


_E3_PROMPT = (
    "请打开当前目录下这个不存在的文件：open_e2e_missing_no_such_file.docx。"
    "如果打不开，把工具返回的错误原文告诉我，然后给出最终结果。"
)
_E2_PROMPT = "当前目录已经有 notes.md。请用系统默认程序打开 notes.md 给我预览。"


def test_named_preview_files_extracts_e3_docx() -> None:
    assert open_file_module.named_preview_files(_E3_PROMPT) == (
        "open_e2e_missing_no_such_file.docx",
    )
    assert open_file_module.named_preview_files(_E2_PROMPT) == ("notes.md",)
    assert open_file_module.named_preview_files("随便看看工作区") == ()


def test_open_file_refuses_substitute_when_user_named_missing_file(
    monkeypatch, tmp_path
) -> None:
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_turn_user_text,
        reset_turn_user_text,
    )

    notes = tmp_path / "notes.md"
    notes.write_text("leftover from E2", encoding="utf-8")
    startfile, subprocess_run, popen, browser_open, _ = _mock_host_openers(monkeypatch)
    monkeypatch.setattr(open_file_module.sys, "platform", "win32")
    token = bind_turn_user_text(_E3_PROMPT)
    try:
        result = open_file_module.open_file(str(notes))
    finally:
        reset_turn_user_text(token)

    assert "file not found" in result
    assert "notes.md" in result
    assert "open_e2e_missing_no_such_file.docx" in result
    startfile.assert_not_called()
    popen.assert_not_called()
    subprocess_run.assert_not_called()
    browser_open.assert_not_called()


def test_open_file_named_missing_docx_still_errors(monkeypatch, tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_turn_user_text,
        reset_turn_user_text,
    )

    startfile, subprocess_run, popen, browser_open, _ = _mock_host_openers(monkeypatch)
    token = bind_turn_user_text(_E3_PROMPT)
    try:
        result = open_file_module.open_file(
            str(tmp_path / "open_e2e_missing_no_such_file.docx")
        )
    finally:
        reset_turn_user_text(token)

    assert "file not found" in result
    startfile.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()


def test_open_file_allows_the_file_the_user_named(monkeypatch, tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_turn_user_text,
        reset_turn_user_text,
    )

    notes = tmp_path / "notes.md"
    notes.write_text("ok", encoding="utf-8")
    startfile, subprocess_run, popen, browser_open, _ = _mock_host_openers(monkeypatch)
    monkeypatch.setattr(open_file_module.sys, "platform", "win32")
    token = bind_turn_user_text(_E2_PROMPT)
    try:
        result = open_file_module.open_file(str(notes))
    finally:
        reset_turn_user_text(token)

    assert result.startswith("[opened ")
    _assert_windows_split_start(popen, notes)
