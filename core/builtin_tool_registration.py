"""Register built-in tools at module scope (P7: remove lazy imports from agent_v2)."""

from __future__ import annotations

from typing import Any, Protocol

from RxyCode.RxyCode1_1_0.tools.read import read_tool
from RxyCode.RxyCode1_1_0.tools.write import write_tool
from RxyCode.RxyCode1_1_0.tools.edit import edit_tool
from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
from RxyCode.RxyCode1_1_0.tools.grep_tool import grep_tool
from RxyCode.RxyCode1_1_0.tools.glob_tool import glob_tool
from RxyCode.RxyCode1_1_0.tools.ls import ls_tool
from RxyCode.RxyCode1_1_0.tools.view import view_tool
from RxyCode.RxyCode1_1_0.tools.webfetch import webfetch_tool
from RxyCode.RxyCode1_1_0.tools.websearch import websearch_tool
from RxyCode.RxyCode1_1_0.tools.git_tool import git_tool
from RxyCode.RxyCode1_1_0.tools.datetime_tool import datetime_tool
from RxyCode.RxyCode1_1_0.tools.history_tool import history_tool
from RxyCode.RxyCode1_1_0.tools.question_tool import question_tool
from RxyCode.RxyCode1_1_0.tools.skill_tool import skill_tool
from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory_tool
from RxyCode.RxyCode1_1_0.tools.diagnostics import diagnostics_tool
from RxyCode.RxyCode1_1_0.tools.format_tool import format_tool
from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_tool
from RxyCode.RxyCode1_1_0.tools.vision import vision_tool
from RxyCode.RxyCode1_1_0.tools.workflow_tool import workflow_tool
from RxyCode.RxyCode1_1_0.tools.task_tool import task_tool
from RxyCode.RxyCode1_1_0.tools.patch import patch_tool
from RxyCode.RxyCode1_1_0.tools.open_file import open_file_tool
from RxyCode.RxyCode1_1_0.tools.download_tool import download_mcp_tool, download_skill_tool
from RxyCode.RxyCode1_1_0.tools.file_download import file_download_tool


class ToolRegistry(Protocol):
    def register(self, tool: Any, *, risk: str = ...) -> None: ...
    def get_names(self) -> list[str]: ...
    def get(self, name: str) -> Any: ...


class ToolOrchestrator(Protocol):
    def register(self, name: str, tool: Any) -> None: ...


def register_builtin_tools(
    registry: ToolRegistry,
    orchestrator: ToolOrchestrator,
    *,
    rag_enabled: bool,
) -> None:
    """Populate registry and orchestrator with built-in tools."""
    read_tools = [
        read_tool,
        grep_tool,
        glob_tool,
        ls_tool,
        view_tool,
        datetime_tool,
        websearch_tool,
        webfetch_tool,
        history_tool,
        diagnostics_tool,
        format_tool,
    ]
    write_tools = [
        write_tool,
        edit_tool,
        patch_tool,
        open_file_tool,
        memory_tool,
        change_directory_tool,
        skill_tool,
        workflow_tool,
        task_tool,
        vision_tool,
    ]
    danger_tools = [bash_tool, git_tool, question_tool]

    for tool in read_tools:
        registry.register(tool, risk="read")
    for tool in write_tools:
        registry.register(tool, risk="write")
    for tool in danger_tools:
        registry.register(tool, risk="danger")

    registry.register(download_skill_tool, risk="danger")
    registry.register(download_mcp_tool, risk="danger")

    if rag_enabled:
        try:
            import RxyCode.RxyCode1_1_0.rag.search  # noqa: F401
        except ImportError:
            pass

    registry.register(file_download_tool)

    for name in registry.get_names():
        if name == "code_search" and not rag_enabled:
            continue
        tool = registry.get(name)
        if tool:
            orchestrator.register(name, tool)
