"""Load a GitHub plugin PAT without putting it in config.yaml or logs."""

from __future__ import annotations

import json
import os
from pathlib import Path


def read_github_user_token(user_json: Path) -> str:
    """Read ``token`` / ``github_token`` from a plugin ``user.json``."""
    path = Path(user_json)
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("token") or raw.get("github_token") or "").strip()


def read_github_plugin_token() -> str:
    """Process env first, then the installed github plugin's ``user.json``."""
    env_token = (
        os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or os.environ.get("GH_TOKEN") or ""
    ).strip()
    if env_token:
        return env_token
    try:
        from config.settings import get_data_dir
    except ImportError:
        return ""
    return read_github_user_token(get_data_dir() / "plugins" / "github" / "user.json")


def inject_github_plugin_token(env: dict[str, str], server_name: str) -> None:
    """Fill ``GITHUB_PERSONAL_ACCESS_TOKEN`` for GitHub MCP stdio servers."""
    if "github" not in (server_name or "").lower():
        return
    if (env.get("GITHUB_PERSONAL_ACCESS_TOKEN") or env.get("GH_TOKEN") or "").strip():
        return
    token = read_github_plugin_token()
    if token:
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
