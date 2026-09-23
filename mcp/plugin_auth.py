"""Load plugin OAuth/PAT tokens without putting them in config.yaml or logs."""

from __future__ import annotations

import json
import os
from pathlib import Path

_TOKEN_KEYS = ("token", "access_token", "github_token")


def read_plugin_user_token(user_json: Path) -> str:
    path = Path(user_json)
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    for key in _TOKEN_KEYS:
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return ""


def _data_dir() -> Path | None:
    try:
        from config.settings import get_data_dir
    except ImportError:
        return None
    return get_data_dir()


def read_installed_plugin_token(plugin_name: str) -> str:
    root = _data_dir()
    if root is None:
        return ""
    return read_plugin_user_token(root / "plugins" / plugin_name / "user.json")


def inject_plugin_token(env: dict[str, str], server_name: str, *, env_key: str, plugin_name: str) -> None:
    if plugin_name not in (server_name or "").lower():
        return
    if (env.get(env_key) or "").strip():
        return
    token = read_installed_plugin_token(plugin_name)
    if token:
        env[env_key] = token


def inject_oauth_plugin_tokens(env: dict[str, str], server_name: str) -> None:
    inject_plugin_token(env, server_name, env_key="GITHUB_PERSONAL_ACCESS_TOKEN", plugin_name="github")
    inject_plugin_token(env, server_name, env_key="CANVA_ACCESS_TOKEN", plugin_name="canva")
    github_env = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if github_env.strip() and "github" in (server_name or "").lower():
        env.setdefault("GITHUB_PERSONAL_ACCESS_TOKEN", github_env.strip())
