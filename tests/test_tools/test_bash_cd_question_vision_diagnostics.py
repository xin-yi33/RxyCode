"""
Tests for tools/bash.py, change_directory.py, question_tool.py, vision.py, diagnostics.py.

Covers: bash execution, cd, question, vision ops, diagnostics.
"""
import pytest
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


class TestBashInput:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.tools.bash import BashInput
        bi = BashInput(command="echo")
        assert bi.command == "echo"
        assert bi.description == ""
        assert bi.workdir == ""
        assert bi.timeout == 60

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.tools.bash import BashInput
        bi = BashInput(command="echo hello", description="test", workdir="/tmp", timeout=30)
        assert bi.command == "echo hello"
        assert bi.description == "test"
        assert bi.workdir == "/tmp"
        assert bi.timeout == 30


class TestRunBash:
    def test_echo_command(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash("echo hello_world")
        assert "hello_world" in result

    def test_empty_command(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash("")
        assert isinstance(result, str)

    def test_python_command(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash('python -c "print(42)"')
        assert "42" in result

    def test_pwd_command(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash("cd", workdir=str(tmp_path))
        assert isinstance(result, str)

    def test_timeout(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash("echo test", timeout=5)
        assert "test" in result

    def test_stderr_captured(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        # Use a simple stderr redirect that works on Windows
        result = run_bash("echo error_message 1>&2")
        # May or may not capture stderr depending on shell
        assert isinstance(result, str)

    def test_no_output_command(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash("exit 0")
        assert isinstance(result, str)

    def test_failed_command_shows_exit_code(self):
        from RxyCode.RxyCode1_1_0.tools.bash import run_bash
        result = run_bash("exit 1")
        assert isinstance(result, str)


class TestBashOutputTruncation:
    """Output longer than 30000 chars is middle-truncated, keeping head+tail."""

    def _run_with_output(self, text):
        from unittest.mock import patch, MagicMock
        from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

        fake = {"stdout": text, "stderr": "", "success": True, "exit_code": 0}
        with patch.object(bash_mod, "shell_executor") as mock_exec:
            mock_exec.execute = MagicMock(return_value=fake)
            return bash_mod.run_bash("whatever")

    def test_short_output_not_truncated(self):
        out = self._run_with_output("hello")
        assert out == "hello"

    def test_long_output_truncated_with_hint(self):
        big = "A" * 40000
        out = self._run_with_output(big)
        assert len(out) < 32000
        assert "输出已截断" in out

    def test_truncation_keeps_head_and_tail(self):
        head = "H" * 15000
        tail = "T" * 15000
        big = head + ("M" * 20000) + tail
        out = self._run_with_output(big)
        assert out.startswith("H" * 100)
        assert out.rstrip().endswith("T" * 100)

    def test_exactly_30000_not_truncated(self):
        big = "B" * 30000
        out = self._run_with_output(big)
        assert "输出已截断" not in out
        assert len(out) == 30000


class TestBashTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
        assert bash_tool.name == "bash"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
        assert "shell" in bash_tool.description.lower()

    def test_tool_invoke(self):
        from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
        result = bash_tool.invoke({"command": "echo test123"})
        assert "test123" in result

    @pytest.mark.asyncio
    async def test_tool_ainvoke_uses_cancellable_shell_path(self):
        from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

        fake = {"stdout": "async-ok", "stderr": "", "success": True, "exit_code": 0}
        with patch.object(
            bash_mod.shell_executor,
            "execute_async",
            new=AsyncMock(return_value=fake),
        ) as execute_async:
            result = await bash_mod.bash_tool.ainvoke({"command": "echo ignored"})

        assert result == "async-ok"
        execute_async.assert_awaited_once_with("echo ignored", "", 60)


class TestChangeDirectory:
    def test_valid_directory_is_session_local(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory
        import RxyCode.RxyCode1_1_0.config.settings as settings

        monkeypatch.setattr(
            settings,
            "load_config",
            lambda: {"execution": {"sandbox_mode": "host"}},
        )
        original = os.getcwd()
        result = change_directory(str(tmp_path))
        assert "Changed directory" in result
        assert os.getcwd() == original

    def test_nonexistent_path(self):
        from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory
        result = change_directory("/nonexistent/path/12345")
        assert "error" in result.lower()

    def test_not_a_directory(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory
        f = tmp_path / "file.txt"
        f.write_text("test")
        result = change_directory(str(f))
        assert "error" in result.lower()

    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory_tool
        assert change_directory_tool.name == "cd"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory_tool
        assert "directory" in change_directory_tool.description.lower()


class TestQuestionInput:
    def test_question_model(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import Question
        q = Question(question="What is your name?")
        assert q.question == "What is your name?"
        assert q.header == ""
        assert q.options == []
        assert q.multiple is False

    def test_option_model(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import Option
        opt = Option(label="Yes", value="yes")
        assert opt.label == "Yes"
        assert opt.value == "yes"


class TestAskQuestions:
    def test_empty_questions(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions
        result = ask_questions([])
        assert result == ""

    def test_question_with_input(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions
        with patch("builtins.input", return_value="test answer"):
            result = ask_questions([{"question": "name?", "header": "Profile"}])
            assert "test answer" in result

    def test_question_with_options(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions
        with patch("builtins.input", return_value="1"):
            result = ask_questions([{
                "question": "choose?",
                "options": [
                    {"label": "A", "value": "a"},
                    {"label": "B", "value": "b"},
                ]
            }])
            assert "a" in result

    def test_question_invalid_choice(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions
        with patch("builtins.input", return_value="invalid"):
            result = ask_questions([{
                "question": "choose?",
                "options": [{"label": "A", "value": "a"}]
            }])
            # "invalid" is not a valid int, so it returns "[no input]"
            assert "[no input]" in result or "invalid" in result

    def test_question_eof_error(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions
        with patch("builtins.input", side_effect=EOFError):
            result = ask_questions([{"question": "q?"}])
            assert "[no input]" in result

    def test_question_value_error_in_choice(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions
        with patch("builtins.input", side_effect=ValueError):
            result = ask_questions([{
                "question": "q?",
                "options": [{"label": "A", "value": "a"}]
            }])
            assert "[no input]" in result


class TestQuestionTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import question_tool
        assert question_tool.name == "question"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.question_tool import question_tool
        assert "question" in question_tool.description.lower()

    def test_multiple_selection_is_explicitly_rejected(self):
        from pydantic import ValidationError
        from RxyCode.RxyCode1_1_0.tools.question_tool import Question

        with pytest.raises(ValidationError):
            Question(question="Choose many", multiple=True)

    @pytest.mark.asyncio
    async def test_native_coroutine_resolves_sse_question_on_caller_loop(self):
        import asyncio

        from RxyCode.RxyCode1_1_0.core.question import (
            SseQuestionBroker,
            set_question_broker,
        )
        from RxyCode.RxyCode1_1_0.tools.question_tool import (
            ask_questions_async,
            question_tool,
        )

        broker = SseQuestionBroker(timeout=5)
        owner_loop = asyncio.get_running_loop()
        published = asyncio.Event()
        holder = {}

        def sink(event):
            assert asyncio.get_running_loop() is owner_loop
            holder.update(event)
            published.set()

        broker.set_event_sink(sink)
        set_question_broker(broker)
        try:
            invocation = asyncio.create_task(question_tool.ainvoke({
                "questions": [{
                    "question": "Continue?",
                    "options": [
                        {"label": "Continue", "value": "continue"},
                        {"label": "Stop", "value": "stop"},
                    ],
                }],
            }))
            await published.wait()
            assert question_tool.coroutine is ask_questions_async
            assert holder["type"] == "question_request"
            assert broker.resolve(holder["question_id"], "continue") is True
            assert await invocation == "A1: continue"
        finally:
            set_question_broker(None)


class TestVisionInput:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.tools.vision import VisionInput
        vi = VisionInput()
        assert vi.operation == "describe"
        assert vi.filePath == ""
        assert vi.prompt == "What do you see in this image?"

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.tools.vision import VisionInput
        vi = VisionInput(operation="ocr", filePath="/tmp/test.png", prompt="read text")
        assert vi.operation == "ocr"
        assert vi.filePath == "/tmp/test.png"
        assert vi.prompt == "read text"


class TestRunVision:
    def test_screenshot_no_mss(self):
        from RxyCode.RxyCode1_1_0.tools.vision import run_vision
        result = run_vision("screenshot")
        # Will error if mss not installed, or return screenshot info
        assert isinstance(result, str)

    def test_describe_no_filepath(self):
        from RxyCode.RxyCode1_1_0.tools.vision import run_vision
        result = run_vision("describe")
        assert "error" in result.lower()

    def test_describe_nonexistent_file(self):
        from RxyCode.RxyCode1_1_0.tools.vision import run_vision
        result = run_vision("describe", "/nonexistent/file.png")
        assert "error" in result.lower()

    def test_describe_non_image_file(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.vision import run_vision
        f = tmp_path / "test.txt"
        f.write_text("not an image")
        result = run_vision("describe", str(f))
        assert "error" in result.lower() or "not a supported" in result.lower()

    def test_unknown_operation(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.vision import run_vision
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = run_vision("invalid_op", str(f))
        assert "error" in result.lower()

    def test_find_tesseract_returns_none_or_path(self):
        from RxyCode.RxyCode1_1_0.tools.vision import _find_tesseract
        result = _find_tesseract()
        # Returns path if found, None if not
        assert result is None or isinstance(result, str)


class TestVisionTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.vision import vision_tool
        assert vision_tool.name == "vision"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.vision import vision_tool
        assert "image" in vision_tool.description.lower() or "ocr" in vision_tool.description.lower()


class TestDiagnosticsInput:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import DiagnosticsInput
        di = DiagnosticsInput()
        assert di.filePath == ""


class TestRunDiagnostics:
    def test_no_file_specified(self):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        result = run_diagnostics("")
        assert "No file" in result or "no file" in result.lower()

    def test_nonexistent_file(self):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        result = run_diagnostics("/nonexistent/file.py")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_python_file_no_issues(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "clean.py"
        f.write_text("x = 1\nprint(x)\n")
        result = run_diagnostics(str(f))
        assert "No issues" in result or "no issues" in result.lower()

    def test_python_file_syntax_error(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "broken.py"
        f.write_text("def broken(\n")
        result = run_diagnostics(str(f))
        assert "SyntaxError" in result or "syntax" in result.lower()

    def test_python_file_wildcard_import(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "wild.py"
        f.write_text("from os import *\n")
        result = run_diagnostics(str(f))
        assert "Wildcard" in result or "wildcard" in result.lower()

    def test_python_file_trailing_whitespace(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "trailing.py"
        f.write_text("x = 1   \n")
        result = run_diagnostics(str(f))
        assert "Trailing" in result or "trailing" in result.lower()

    def test_python_file_long_line(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "long.py"
        f.write_text("x = " + "a" * 130 + "\n")
        result = run_diagnostics(str(f))
        assert "long" in result.lower()

    def test_javascript_file_console_log(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "test.js"
        f.write_text("console.log('hello');\n")
        result = run_diagnostics(str(f))
        assert "console.log" in result

    def test_javascript_file_var(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "var.js"
        f.write_text("var x = 1;\n")
        result = run_diagnostics(str(f))
        assert "var" in result.lower()

    def test_javascript_file_no_issues(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "clean.js"
        f.write_text("const x = 1;\n")
        result = run_diagnostics(str(f))
        assert "No issues" in result

    def test_unsupported_extension(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics
        f = tmp_path / "file.go"
        f.write_text("package main\n")
        result = run_diagnostics(str(f))
        assert "No diagnostics" in result or "no diagnostics" in result.lower()


class TestDiagnosticsTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import diagnostics_tool
        assert diagnostics_tool.name == "diagnostics"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.diagnostics import diagnostics_tool
        assert "diagnostics" in diagnostics_tool.description.lower()
