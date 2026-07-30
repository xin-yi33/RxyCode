"""Safety-gated skill and MCP configuration tools."""
from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class DownloadSkillInput(BaseModel):
    name: str = Field(description="Skill name")
    operation: str = Field(
        default="install",
        description="Operation: install, install_url, or remove",
    )
    url: str = Field(default="", description="Direct HTTP(S) URL for install_url")


class DownloadMCPInput(BaseModel):
    name: str = Field(description="Name of the MCP server")
    package: str = Field(
        default="",
        description="npm package name (e.g. '@modelcontextprotocol/server-filesystem')",
    )
    operation: str = Field(default="add", description="Operation: add or remove")
    command: str = Field(default="", description="Executable for a custom MCP server")
    args: list[str] = Field(default_factory=list, description="Arguments for a custom MCP server")


def download_skill(
    name: str,
    operation: str = "install",
    url: str = "",
) -> str:
    """Install or remove a skill after the safety gate has approved it."""
    from .skill_manager import (
        find_and_download_skill,
        install_skill_from_url,
        list_installed_skills,
        remove_skill,
    )

    operation = operation.strip().lower()
    if operation == "remove":
        ok, message = remove_skill(name)
        return (
            f"Successfully removed skill '{name}': {message}"
            if ok else f"Failed to remove skill '{name}': {message}"
        )
    if operation == "install_url":
        if not url:
            return "[error: url is required for install_url]"
        ok, message = install_skill_from_url(url, name)
        return (
            f"Successfully installed skill '{name}': {message}"
            if ok else f"Failed to install skill '{name}': {message}"
        )
    if operation != "install":
        return f"[error: unknown skill operation '{operation}']"

    for skill in list_installed_skills():
        if skill["name"].lower() == name.lower():
            return f"Skill '{name}' is already installed at {skill['path']}"

    ok, message = find_and_download_skill(name)
    if ok:
        return f"Successfully installed skill '{name}': {message}"
    return f"Failed to install skill '{name}': {message}"


async def download_skill_async(
    name: str,
    operation: str = "install",
    url: str = "",
) -> str:
    from .skill_manager import (
        find_and_download_skill_async,
        install_skill_from_url_async,
        list_installed_skills,
        remove_skill,
    )

    operation = operation.strip().lower()
    if operation == "remove":
        ok, message = remove_skill(name)
        return (
            f"Successfully removed skill '{name}': {message}"
            if ok else f"Failed to remove skill '{name}': {message}"
        )
    if operation == "install_url":
        if not url:
            return "[error: url is required for install_url]"
        ok, message = await install_skill_from_url_async(url, name)
        return (
            f"Successfully installed skill '{name}': {message}"
            if ok else f"Failed to install skill '{name}': {message}"
        )
    if operation != "install":
        return f"[error: unknown skill operation '{operation}']"

    for skill in list_installed_skills():
        if skill["name"].lower() == name.lower():
            return f"Skill '{name}' is already installed at {skill['path']}"
    ok, message = await find_and_download_skill_async(name)
    if ok:
        return f"Successfully installed skill '{name}': {message}"
    return f"Failed to install skill '{name}': {message}"


def download_mcp(
    name: str,
    package: str = "",
    operation: str = "add",
    command: str = "",
    args: list[str] | None = None,
) -> str:
    """Add or remove an MCP server configuration."""
    from .mcp_manager import add_mcp_server, list_mcp_servers, remove_mcp_server

    operation = operation.strip().lower()
    if operation == "remove":
        ok, message = remove_mcp_server(name)
        return (
            f"Successfully removed MCP server '{name}': {message}"
            if ok else f"Failed to remove MCP server '{name}': {message}"
        )
    if operation != "add":
        return f"[error: unknown MCP operation '{operation}']"

    if not command:
        if not package:
            return "[error: package or command is required for add operation]"
        command = "npx"
        args = ["-y", package]

    for server in list_mcp_servers():
        if server["name"].lower() == name.lower():
            return f"MCP server '{name}' is already configured"

    ok, message = add_mcp_server(name=name, command=command, args=args or [])
    if ok:
        return f"Successfully added MCP server '{name}': {message}"
    return f"Failed to add MCP server '{name}': {message}"


async def download_mcp_async(
    name: str,
    package: str = "",
    operation: str = "add",
    command: str = "",
    args: list[str] | None = None,
) -> str:
    # Configuration writes contain no network or process work and complete
    # atomically before the coroutine yields.
    return download_mcp(name, package, operation, command, args)


download_skill_tool = StructuredTool(
    name="download_skill",
    description="Install a skill from GitHub or a direct URL, or remove an installed skill.",
    func=download_skill,
    coroutine=download_skill_async,
    args_schema=DownloadSkillInput,
)


download_mcp_tool = StructuredTool(
    name="download_mcp",
    description="Add or remove an MCP server configuration.",
    func=download_mcp,
    coroutine=download_mcp_async,
    args_schema=DownloadMCPInput,
)
