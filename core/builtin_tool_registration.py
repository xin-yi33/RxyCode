"""Register built-in tools at module scope (P7: remove lazy imports from agent_v2)."""

from __future__ import annotations

from typing import Any, Protocol

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, register_tool_risk

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
from RxyCode.RxyCode1_1_0.tools.final_answer import final_answer_tool
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
from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import subagent_task_tool
from RxyCode.RxyCode1_1_0.tools.open_file import open_file_tool
from RxyCode.RxyCode1_1_0.tools.virtual_browser import (
    browser_click_tool,
    browser_navigate_tool,
    browser_snapshot_tool,
)
from RxyCode.RxyCode1_1_0.tools.download_tool import download_mcp_tool, download_skill_tool
from RxyCode.RxyCode1_1_0.tools.team_install_tool import team_install_tool
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
    subagents_enabled: bool = False,
    run_official_agent_enabled: bool = False,
) -> None:
    """Populate registry and orchestrator with built-in tools.

    When ``subagents_enabled`` is True, the ``task`` name is the isolated
    subagent dispatch tool and the task-list tool registers as
    ``task_manage``. When False (default), the legacy ``task`` task-list
    tool is registered and the subagent dispatch tool is NOT — guaranteeing
    single-agent zero regression. Exactly one tool may own the ``task`` name.

    When ``run_official_agent_enabled`` is True, the ``run_official_agent``
    bridge tool (official agent CLI as side subprocess) is registered with
    DANGER risk. Default False (CB8: default toolset unchanged).
    """
    from RxyCode.RxyCode1_1_0.tools.task_manage import task_manage_tool

    read_tools = [
        read_tool,
        grep_tool,
        glob_tool,
        ls_tool,
        view_tool,
        datetime_tool,
        final_answer_tool,
        websearch_tool,
        webfetch_tool,
        history_tool,
        diagnostics_tool,
        format_tool,
        # 虚拟浏览器进本轮 tools。废弃代码（2026-09-22）：以前只写在文档里，
        # 没有 register，模型只能回答「虚拟浏览器未进本轮」。
        browser_navigate_tool,
        browser_snapshot_tool,
        # question 是用户交互不是危险操作（policy.py 早已分类 READ）。
        # 废弃代码（2026-09-23）：注册为 danger，confirm_all/full_auto 下
        # 前置审批弹窗被自动批准吞掉，question 弹窗体验受损。
        question_tool,
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
        # Tool-name freeze (B13): `task` is either the task-list tool
        # (legacy, subagents off) or the subagent dispatch tool (subagents on).
        task_manage_tool if subagents_enabled else task_tool,
        vision_tool,
        browser_click_tool,
    ]
    danger_tools = [bash_tool, git_tool, team_install_tool]

    for tool in read_tools:
        registry.register(tool, risk="read")
    for tool in write_tools:
        registry.register(tool, risk="write")
    for tool in danger_tools:
        registry.register(tool, risk="danger")

    # Isolated subagent dispatch tool (name `task`) — ONLY when subagents on
    if subagents_enabled:
        # Dispatch itself does not write the workspace. The manager enforces
        # permission.task and child tools cross their own approval gates.
        register_tool_risk("task", RiskLevel.READ)
        registry.register(subagent_task_tool, risk="read")
    else:
        register_tool_risk("task", RiskLevel.WRITE)

    # B10: run_official_agent 桥接工具（官方 agent CLI 旁路）— ONLY when enabled
    if run_official_agent_enabled:
        from RxyCode.RxyCode1_1_0.tools.run_official_agent import (
            run_official_agent_tool,
        )

        registry.register(run_official_agent_tool(), risk="danger")

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
