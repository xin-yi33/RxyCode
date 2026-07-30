"""Per-tool success/failure contract matrices under tools/."""

from __future__ import annotations

import itertools
from pathlib import Path
from unittest.mock import patch

import pytest


_TOOL_IMPORTS = {
    "read": ("RxyCode.RxyCode1_1_0.tools.read", "read_file"),
    "write": ("RxyCode.RxyCode1_1_0.tools.write", "write_file"),
    "grep": ("RxyCode.RxyCode1_1_0.tools.grep_tool", "grep_files"),
    "glob": ("RxyCode.RxyCode1_1_0.tools.glob_tool", "glob_files"),
    "ls": ("RxyCode.RxyCode1_1_0.tools.ls", "run_ls"),
    "view": ("RxyCode.RxyCode1_1_0.tools.view", "run_view"),
    "datetime": ("RxyCode.RxyCode1_1_0.tools.datetime_tool", "get_datetime"),
    "patch": ("RxyCode.RxyCode1_1_0.tools.patch", "run_patch"),
    "edit": ("RxyCode.RxyCode1_1_0.tools.edit", "edit_file"),
    "open_file": ("RxyCode.RxyCode1_1_0.tools.open_file", "open_file"),
    "git": ("RxyCode.RxyCode1_1_0.tools.git_tool", "run_git"),
    "websearch": ("RxyCode.RxyCode1_1_0.tools.websearch", "search_web"),
    "webfetch": ("RxyCode.RxyCode1_1_0.tools.webfetch", "fetch_url"),
    "memory": ("RxyCode.RxyCode1_1_0.tools.memory_tool", "memory_operation"),
    "task": ("RxyCode.RxyCode1_1_0.tools.task_tool", "manage_tasks"),
    "workflow": ("RxyCode.RxyCode1_1_0.tools.workflow_tool", "manage_workflow"),
    "question": ("RxyCode.RxyCode1_1_0.tools.question_tool", "ask_questions"),
    "vision": ("RxyCode.RxyCode1_1_0.tools.vision", "run_vision"),
    "bash": ("RxyCode.RxyCode1_1_0.tools.bash", "run_bash"),
    "change_directory": ("RxyCode.RxyCode1_1_0.tools.change_directory", "change_directory"),
    "format": ("RxyCode.RxyCode1_1_0.tools.format_tool", "run_format"),
    "diagnostics": ("RxyCode.RxyCode1_1_0.tools.diagnostics", "run_diagnostics"),
    "history": ("RxyCode.RxyCode1_1_0.tools.history_tool", "search_history"),
    "download": ("RxyCode.RxyCode1_1_0.tools.download_tool", "download_skill"),
    "file_download": ("RxyCode.RxyCode1_1_0.tools.file_download", "download_file"),
    "agent": ("RxyCode.RxyCode1_1_0.tools.agent_tool", "run_agent"),
    "skill": ("RxyCode.RxyCode1_1_0.tools.skill_tool", "load_skill"),
}


def _load(tool: str):
    import importlib

    mod_name, fn_name = _TOOL_IMPORTS[tool]
    mod = importlib.import_module(mod_name)
    return getattr(mod, fn_name)


_INVALID_PATHS = (
    "/nonexistent/rxycode/file.py",
    "missing/entity.txt",
    "Z:/no/such/path.py",
)

_INVALID_REGEX = ("[", "(?", "*", "\\", "([)")

_DATETIME_FORMATS = ("%Y-%m-%d", "%H:%M:%S", "%Y/%m/%d %H:%M", "invalid%%%")


@pytest.mark.parametrize("tool", sorted(_TOOL_IMPORTS))
def test_tool_callable_importable(tool: str):
    fn = _load(tool)
    assert callable(fn)


@pytest.mark.parametrize("tool", ("read", "view", "grep", "ls"))
@pytest.mark.parametrize("bad_path", _INVALID_PATHS)
def test_read_family_missing_paths_error(tool: str, bad_path: str):
    fn = _load(tool)
    if tool == "read":
        out = fn(bad_path)
    elif tool == "view":
        out = fn(bad_path)
    elif tool == "grep":
        out = fn("pattern", bad_path)
    else:
        out = fn(bad_path)
    assert "error" in out.lower() or "not found" in out.lower()


@pytest.mark.parametrize("bad_path", _INVALID_PATHS)
def test_glob_missing_path_returns_no_matches(bad_path: str):
    out = _load("glob")("*.py", bad_path)
    assert "no matches" in out.lower()


@pytest.mark.parametrize("pattern", _INVALID_REGEX)
def test_grep_invalid_regex_matrix(pattern: str, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello\n", encoding="utf-8")
    out = _load("grep")(pattern, str(tmp_path))
    assert "invalid regex" in out.lower()


@pytest.mark.parametrize("fmt", _DATETIME_FORMATS)
def test_datetime_format_matrix(fmt: str):
    out = _load("datetime")(fmt)
    assert isinstance(out, str)
    assert out.strip()


def test_write_rejects_invalid_python_syntax(tmp_path):
    target = tmp_path / "bad.py"
    out = _load("write")(str(target), "def broken(")
    assert "wrote" in out.lower()
    assert "syntax" in out.lower()


def test_write_success_roundtrip(tmp_path):
    target = tmp_path / "out.txt"
    out = _load("write")(str(target), "hello world")
    assert "error" not in out.lower()
    assert target.read_text(encoding="utf-8") == "hello world"


@pytest.mark.parametrize(
    ("operation", "expected_fragment"),
    [
        ("status", "error"),
        ("wait", "error"),
        ("cancel", "error"),
        ("unknown_op", "error"),
    ],
)
def test_workflow_unknown_or_missing_matrix(operation: str, expected_fragment: str):
    out = _load("workflow")(operation=operation, run_id="missing-run")
    assert expected_fragment in out.lower()


@pytest.mark.parametrize(
    ("operation", "expected_fragment"),
    [
        ("complete", "error"),
        ("delete", "error"),
        ("list", ""),
        ("unknown", "error"),
    ],
)
def test_task_tool_missing_id_matrix(operation: str, expected_fragment: str):
    out = _load("task")(operation=operation, id="missing-task-id")
    if expected_fragment:
        assert expected_fragment in out.lower()
    else:
        assert isinstance(out, str)


@pytest.mark.parametrize("url", ("not-a-url", "ftp://example.com/x", "http://127.0.0.1:1"))
def test_webfetch_invalid_or_blocked_url_matrix(url: str):
    with patch(
        "RxyCode.RxyCode1_1_0.tools.webfetch.fetch_public_response",
        side_effect=ValueError("blocked"),
    ):
        out = _load("webfetch")(url)
    assert "error" in out.lower()


@pytest.mark.parametrize("query", ("", "   ", "python asyncio tutorial"))
def test_websearch_query_matrix(query: str):
    fake_engine = lambda q, n: [f"result for {q or 'empty'}"]
    with patch(
        "RxyCode.RxyCode1_1_0.tools.websearch._engine_list",
        return_value=[("fake", fake_engine)],
    ):
        out = _load("websearch")(query or "test")
    assert isinstance(out, str)
    assert out.strip()


@pytest.mark.parametrize(
    ("operation", "suffix"),
    itertools.product(("describe", "ocr", "screenshot", "bad-op"), (".png", ".jpg", ".txt", ".exe")),
)
def test_vision_invalid_inputs_matrix(tmp_path, operation: str, suffix: str):
    p = tmp_path / f"img{suffix}"
    if suffix in {".png", ".jpg"}:
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
    else:
        p.write_text("not-image", encoding="utf-8")
    out = _load("vision")(operation=operation, filePath=str(p))
    if operation == "bad-op" or suffix not in {".png", ".jpg"}:
        assert "error" in out.lower()
    else:
        assert isinstance(out, str)


@pytest.mark.parametrize("questions", ([], [{"question": "q?", "options": []}]))
def test_question_tool_matrix(questions):
    with patch("RxyCode.RxyCode1_1_0.tools.question_tool._ask_questions_from_stdin", return_value="[]"):
        out = _load("question")(questions)
    assert isinstance(out, str)
