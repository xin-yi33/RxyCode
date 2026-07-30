"""MCP Manager - Add, remove, and manage MCP servers from CLI."""

import os
import tempfile
import threading
import yaml

from ..config.settings import get_config_path


_MCP_CONFIG_LOCK = threading.RLock()


def get_mcp_config() -> dict:
    """Get current MCP configuration from config.yaml."""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("mcpServers", {})
    except Exception:
        return {}


def save_mcp_config(mcp_servers: dict) -> tuple[bool, str]:
    """Save MCP configuration to config.yaml."""
    config_path = get_config_path()
    try:
        with _MCP_CONFIG_LOCK:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
            else:
                cfg = {}

            cfg["mcpServers"] = mcp_servers
            config_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=config_path.parent,
                prefix=f".{config_path.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    yaml.safe_dump(
                        cfg,
                        f,
                        default_flow_style=False,
                        allow_unicode=True,
                    )
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_name, config_path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

        return True, f"Saved MCP config to {config_path}"
    except Exception as e:
        return False, f"Failed to save config: {e}"


def add_mcp_server(name: str, command: str, args: list[str] = None, env: dict = None) -> tuple[bool, str]:
    """Add an MCP server to the configuration."""
    with _MCP_CONFIG_LOCK:
        mcp_servers = get_mcp_config()

        if name in mcp_servers:
            return False, f"MCP server '{name}' already exists. Use remove first."

        mcp_servers[name] = {
            "command": command,
            "args": args or [],
        }
        if env:
            mcp_servers[name]["env"] = env

        success, msg = save_mcp_config(mcp_servers)
    if success:
        return True, f"Added MCP server '{name}' ({command})"
    return False, msg


def remove_mcp_server(name: str) -> tuple[bool, str]:
    """Remove an MCP server from the configuration."""
    with _MCP_CONFIG_LOCK:
        mcp_servers = get_mcp_config()
        if name not in mcp_servers:
            return False, f"MCP server '{name}' not found"
        del mcp_servers[name]
        success, msg = save_mcp_config(mcp_servers)
    if success:
        return True, f"Removed MCP server '{name}'"
    return False, msg


def list_mcp_servers() -> list[dict]:
    """List all configured MCP servers."""
    mcp_servers = get_mcp_config()
    result = []
    for name, config in mcp_servers.items():
        result.append({
            "name": name,
            "command": config.get("command", ""),
            "args": config.get("args", []),
            "env": config.get("env", {}),
        })
    return result


def install_mcp_from_npm(package_name: str, server_name: str = None) -> tuple[bool, str]:
    """Install an MCP server from npm package."""
    if not server_name:
        server_name = package_name.replace("@", "").replace("/", "-")

    try:
        import subprocess
        # Check if npx is available
        result = subprocess.run(
            ["npx", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return False, "npx not found. Please install Node.js first."

        # Add as MCP server using npx
        return add_mcp_server(
            name=server_name,
            command="npx",
            args=["-y", package_name],
        )
    except Exception as e:
        return False, f"Failed to install MCP: {e}"


def install_mcp_from_pip(package_name: str, server_name: str = None) -> tuple[bool, str]:
    """Install an MCP server from pip package."""
    if not server_name:
        server_name = package_name

    try:
        import subprocess
        import sys

        # Install the package
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return False, f"pip install failed: {result.stderr}"

        # Try to find the entry point
        module_name = package_name.replace("-", "_")
        return add_mcp_server(
            name=server_name,
            command=sys.executable,
            args=["-m", module_name],
        )
    except Exception as e:
        return False, f"Failed to install MCP: {e}"
