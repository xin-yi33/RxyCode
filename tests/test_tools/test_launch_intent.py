"""Classify and intercept GUI-launch shell commands.

Opening a document is OS-launch success, not waiting for the window to close.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.tools.launch_intent import classify_shell_launch


class TestClassifyShellLaunch:
    def test_start_docx_is_open_preview(self):
        plan = classify_shell_launch(r'start "" "C:\tmp\notes.docx"')
        assert plan is not None
        assert plan.kind == "open_preview"
        assert plan.path.endswith("notes.docx")

    def test_xdg_open_pdf(self):
        plan = classify_shell_launch("xdg-open ./report.pdf")
        assert plan is not None
        assert plan.kind == "open_preview"
        assert plan.path.endswith("report.pdf")

    def test_macos_open_html(self):
        plan = classify_shell_launch("open ./index.html")
        assert plan is not None
        assert plan.kind == "open_preview"

    def test_macos_open_wait_stays_foreground(self):
        assert classify_shell_launch("open -W ./index.html") is None

    def test_start_process_previewable(self):
        plan = classify_shell_launch("Start-Process 'C:\\tmp\\a.xlsx'")
        assert plan is not None
        assert plan.kind == "open_preview"
        assert plan.path.endswith("a.xlsx")

    def test_cmd_wrapper_start_docx(self):
        plan = classify_shell_launch(r'cmd /c start "" "D:\out\game.html"')
        assert plan is not None
        assert plan.kind == "open_preview"
        assert plan.path.endswith("game.html")

    def test_powershell_start_process(self):
        plan = classify_shell_launch(
            r"powershell -NoProfile -Command Start-Process 'C:\tmp\a.md'"
        )
        assert plan is not None
        assert plan.kind == "open_preview"

    def test_notepad_with_file_detaches_not_rewritten(self):
        plan = classify_shell_launch(r"notepad C:\tmp\a.txt")
        assert plan is not None
        assert plan.kind == "detach"

    def test_typora_detaches(self):
        plan = classify_shell_launch(r"typora C:\tmp\notes.md")
        assert plan is not None
        assert plan.kind == "detach"

    def test_start_wait_not_intercepted(self):
        assert classify_shell_launch("start /wait notepad") is None

    def test_start_b_not_intercepted(self):
        assert classify_shell_launch("start /b npm run dev") is None

    def test_python_not_intercepted(self):
        assert classify_shell_launch("python app.py") is None
        assert classify_shell_launch("git status") is None
        assert classify_shell_launch("echo hello") is None
        assert classify_shell_launch("npm start") is None
        assert classify_shell_launch("pytest tests/") is None

    def test_gio_list_not_intercepted(self):
        assert classify_shell_launch("gio list") is None

    def test_gio_open_pdf(self):
        plan = classify_shell_launch("gio open ./a.pdf")
        assert plan is not None
        assert plan.kind == "open_preview"

    def test_empty(self):
        assert classify_shell_launch("") is None
        assert classify_shell_launch("   ") is None

    def test_tokenize_empty_quoted_title(self):
        from RxyCode.RxyCode1_1_0.tools.launch_intent import tokenize_shell

        tokens = tokenize_shell(r'start "" "C:\tmp\notes.docx"')
        assert tokens[0].casefold() == "start"
        assert tokens[1] == ""
        assert tokens[2].endswith("notes.docx")


class TestRunBashLaunchIntercept:
    def test_start_docx_calls_open_file_not_executor(self, tmp_path, monkeypatch):
        target = tmp_path / "notes.docx"
        target.write_bytes(b"PK")
        calls: dict[str, str] = {}

        def fake_open(path: str) -> str:
            calls["path"] = path
            return f"[opened {path}]"

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.open_file", fake_open
        )
        execute = MagicMock()
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.shell_executor.execute", execute
        )
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash

        out = run_bash(f'start "" "{target}"')
        assert "[opened" in out
        assert "notes.docx" in calls["path"]
        execute.assert_not_called()

    def test_notepad_detaches_without_waiting(self, monkeypatch):
        execute = MagicMock()
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.shell_executor.execute", execute
        )
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash._detach_gui",
            lambda command, workdir="": (
                "[launched] OS accepted the start request. "
                "The GUI app's lifetime is not waited on; continue with the Final Answer."
            ),
        )
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash

        out = run_bash(r"notepad C:\tmp\a.txt")
        assert "[launched]" in out
        assert "not waited" in out
        execute.assert_not_called()

    def test_echo_still_uses_executor(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash

        assert "hello_launch" in run_bash("echo hello_launch")

    def test_start_wait_still_uses_executor(self, monkeypatch):
        execute = MagicMock(
            return_value={
                "stdout": "waited",
                "stderr": "",
                "success": True,
                "exit_code": 0,
            }
        )
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.shell_executor.execute", execute
        )
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash

        out = run_bash("start /wait notepad")
        execute.assert_called_once()
        assert "waited" in out

    def test_detach_spawn_failure_is_error(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise OSError("access denied")

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.subprocess.Popen", boom
        )
        from RxyCode.RxyCode1_1_0.tools.bash import _detach_gui

        out = _detach_gui("notepad")
        assert out.startswith("[error launching command:")
        assert "access denied" in out

    @pytest.mark.asyncio
    async def test_async_xdg_open_skips_executor(self, tmp_path, monkeypatch):
        target = tmp_path / "page.html"
        target.write_text("<html></html>", encoding="utf-8")

        async def fake_open(path: str) -> str:
            return f"[opened {path}]"

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.open_file_async", fake_open
        )
        execute = AsyncMock()
        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.tools.bash.shell_executor.execute_async",
            execute,
        )
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async

        out = await run_bash_async(f'xdg-open "{target}"')
        assert "[opened" in out
        execute.assert_not_called()


def test_open_file_launch_eval_fixture_exists():
    root = Path(__file__).resolve().parents[2]
    path = root / "evals" / "baselines" / "open-file-launch.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"].startswith("open-file-launch")
    assert "open_file" in json.dumps(data)
    assert data["kind"] == "trace-fixture"
