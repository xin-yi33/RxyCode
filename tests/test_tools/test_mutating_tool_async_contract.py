"""Long-running and mutating tools must avoid the thread fallback path."""

import inspect

import pytest


@pytest.mark.parametrize(
    "tool",
    [
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.write", fromlist=["write_tool"]).write_tool,
            id="write",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.edit", fromlist=["edit_tool"]).edit_tool,
            id="edit",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.patch", fromlist=["patch_tool"]).patch_tool,
            id="patch",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.bash", fromlist=["bash_tool"]).bash_tool,
            id="bash",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.git_tool", fromlist=["git_tool"]).git_tool,
            id="git",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.format_tool", fromlist=["format_tool"]).format_tool,
            id="format",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.open_file", fromlist=["open_file_tool"]).open_file_tool,
            id="open_file",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.change_directory", fromlist=["change_directory_tool"]).change_directory_tool,
            id="change_directory",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.memory_tool", fromlist=["memory_tool"]).memory_tool,
            id="memory",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.task_tool", fromlist=["task_tool"]).task_tool,
            id="task",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.workflow_tool", fromlist=["workflow_tool"]).workflow_tool,
            id="workflow",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.download_tool", fromlist=["download_skill_tool"]).download_skill_tool,
            id="download_skill",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.download_tool", fromlist=["download_mcp_tool"]).download_mcp_tool,
            id="download_mcp",
        ),
        pytest.param(
            __import__("RxyCode.RxyCode1_1_0.tools.file_download", fromlist=["file_download_tool"]).file_download_tool,
            id="file_download",
        ),
    ],
)
def test_mutating_tool_has_native_coroutine(tool):
    assert inspect.iscoroutinefunction(tool.coroutine), tool.name


def test_atomic_write_failure_preserves_existing_file(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools.write import write_file
    from RxyCode.RxyCode1_1_0.utils import atomic_file

    target = tmp_path / "state.txt"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("simulated publish failure")

    monkeypatch.setattr(atomic_file.os, "replace", fail_replace)
    result = write_file(str(target), "new")

    assert result.startswith("[error writing file:")
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.txt.*.tmp"))
