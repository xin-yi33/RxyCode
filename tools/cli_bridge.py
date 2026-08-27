"""Frozen agent tools for CLI-Hub (N13/HN2).

``cli_list`` and ``cli_run`` are the only two tool names. Software ids such as
``cli:demo`` are parameter values, not entries in ``tools/registry.py``.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class CliListInput(BaseModel):
    query: str | None = Field(default=None, description="Optional software id/name filter")


class CliRunInput(BaseModel):
    name: str = Field(description="Software id, e.g. cli:demo")
    args: list[str] | None = Field(default=None, description="CLI arguments")


def _hub():
    from appserver.cli_hub_service import CliHubService

    return CliHubService()


def cli_list(query: str | None = None) -> dict[str, Any]:
    return _hub().cli_list(query)


def cli_run(name: str, args: list[str] | None = None) -> dict[str, Any]:
    return _hub().cli_run(name, args)


def bind_agent_tools(hub: Any) -> list[StructuredTool]:
    """Bind the frozen two-tool surface to one CliHubService instance."""

    def _list(query: str | None = None) -> dict[str, Any]:
        return hub.cli_list(query)

    def _run(name: str, args: list[str] | None = None) -> dict[str, Any]:
        return hub.cli_run(name, args)

    return [
        StructuredTool(
            name="cli_list",
            description="List CLI-Hub software ids. Names are parameters, not registry tools.",
            func=_list,
            args_schema=CliListInput,
        ),
        StructuredTool(
            name="cli_run",
            description="Run one CLI-Hub software id in its isolated venv.",
            func=_run,
            args_schema=CliRunInput,
        ),
    ]


cli_list_tool = StructuredTool(
    name="cli_list",
    description="List CLI-Hub software ids. Names are parameters, not registry tools.",
    func=cli_list,
    args_schema=CliListInput,
)
cli_run_tool = StructuredTool(
    name="cli_run",
    description="Run one CLI-Hub software id in its isolated venv.",
    func=cli_run,
    args_schema=CliRunInput,
)
AGENT_TOOLS = (cli_list_tool, cli_run_tool)
