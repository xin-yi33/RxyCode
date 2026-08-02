"""Build subprocess environment for live AgentV2 appserver tests."""

from __future__ import annotations

import os
from pathlib import Path

_ISOLATION_KEYS = (
    "RXYCODE_DATA_DIR",
    "RXYCODE_V2_CONFIG_DIR",
    "HOME",
    "USERPROFILE",
)


def _with_real_user_config():
    """Temporarily drop pytest-isolated paths so config loads from ~/.RxyCode."""
    saved = {key: os.environ.get(key) for key in _ISOLATION_KEYS}
    for key in _ISOLATION_KEYS:
        os.environ.pop(key, None)
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _real_user_paths() -> tuple[Path, Path]:
    """Return (user_home, rxycode_data_dir) bypassing pytest HOME isolation."""
    saved = _with_real_user_config()
    try:
        from config.settings import get_data_dir

        data_dir = get_data_dir()
        user_home = data_dir.parent
        return user_home, data_dir
    finally:
        _restore_env(saved)


def resolve_live_model_credentials() -> tuple[str | None, str | None, str]:
    """Return (env_var_name, api_key, source_label) without logging secrets."""
    saved = _with_real_user_config()
    try:
        from config.settings import get_active_model_config, load_config, resolve_model_config

        model = get_active_model_config()
        env_name = model.get("api_key_env")
        if not isinstance(env_name, str):
            env_name = None
        api_key = (model.get("api_key") or "").strip()
        if api_key:
            if model.get("api_key_secret"):
                source = "credential store (~/.RxyCode)"
            elif env_name and os.environ.get(env_name) == api_key:
                source = f"environment ({env_name})"
            else:
                source = "~/.RxyCode config"
            return env_name, api_key, source

        if env_name:
            cfg = load_config()
            for name, entry in (cfg.get("models") or {}).items():
                if not isinstance(entry, dict) or not entry.get("api_key_secret"):
                    continue
                resolved = resolve_model_config(entry)
                fallback = (resolved.get("api_key") or "").strip()
                if fallback:
                    return (
                        env_name,
                        fallback,
                        f"credential store (model {name!r})",
                    )
            return env_name, None, f"missing — set {env_name} or store key in ~/.RxyCode"
        return None, None, "missing — no api_key_env on active model"
    except Exception as exc:
        return None, None, f"error: {exc}"
    finally:
        _restore_env(saved)


def build_live_appserver_env(*, project_root: Path) -> dict[str, str]:
    """Subprocess env: real ~/.RxyCode config + injected model API key."""
    env = os.environ.copy()
    for key in _ISOLATION_KEYS:
        env.pop(key, None)
    env.pop("RXYCODE_APPSERVER_STUB", None)

    user_home, data_dir = _real_user_paths()
    env["USERPROFILE"] = str(user_home)
    env["HOME"] = str(user_home)
    env["RXYCODE_DATA_DIR"] = str(data_dir)
    env["RXYCODE_V2_CONFIG_DIR"] = str(data_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(project_root.resolve())

    env_name, api_key, _source = resolve_live_model_credentials()
    if api_key and env_name:
        env[env_name] = api_key
    return env


def live_credentials_status() -> str:
    """Human-readable credential status for monitor scripts."""
    env_name, api_key, source = resolve_live_model_credentials()
    active_hint = env_name or "active model"
    if api_key:
        return f"OK ({active_hint} via {source})"
    return f"MISSING ({active_hint}: {source})"
