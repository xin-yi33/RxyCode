import os
import re
import shutil
import threading
import yaml
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional

from .credential_store import (
    atomic_write_text,
    delete_credential,
    load_credential,
    restrict_file_permissions,
    store_credential,
)


_ENV_REFERENCE = re.compile(r"^(?:env:|\$\{)([A-Za-z_][A-Za-z0-9_]*)\}?$")
_CONFIG_LOCK = threading.RLock()

# User-level data directory. Keeps config/history/memory out of the source
# tree so that `pip uninstall` / deleting the repo does not lose user data,
# and so that secrets (API keys) never land inside a git-tracked folder.
DEFAULT_CONFIG_DIR = Path.home() / ".RxyCode"
LEGACY_USER_DATA_DIR = Path.home() / ".rxycode"
# Legacy data dir inside the package (used by older versions). Only kept for
# one-time migration; new installs never write here.
LEGACY_DATA_DIR = Path(__file__).parent.parent / "data"


def get_data_dir() -> Path:
    env = os.environ.get("RXYCODE_DATA_DIR")
    if env:
        p = Path(env)
    else:
        p = DEFAULT_CONFIG_DIR
    p.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data_if_needed(p)
    return p


def _copy_missing_items(source: Path, target: Path) -> None:
    if not source.exists() or source.resolve() == target.resolve():
        return
    for item in source.iterdir():
        dst = target / item.name
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            _copy_missing_items(item, dst)
        elif not dst.exists():
            shutil.copy2(item, dst)


def _migrate_legacy_data_if_needed(target: Path) -> None:
    """Best-effort migration from previous user and in-repo data roots."""
    try:
        if target == DEFAULT_CONFIG_DIR:
            _copy_missing_items(LEGACY_USER_DATA_DIR, target)
            _copy_missing_items(LEGACY_DATA_DIR, target)
    except Exception:
        # Migration is best-effort; never block startup on it.
        pass


def get_date_stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now()).strftime("%Y-%m-%d")


def get_dated_data_dir(category: str, *, create: bool = True) -> Path:
    path = get_data_dir() / category / get_date_stamp()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_path() -> Path:
    return get_data_dir() / "config.yaml"


def get_output_dir() -> Path:
    """Return today's directory for generated files and downloads."""
    env = os.environ.get("RXYCODE_OUTPUT_DIR")
    base = Path(env) if env else get_data_dir() / "output"
    path = base / get_date_stamp()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* onto a copy of *base*."""
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config() -> dict:
    path = get_config_path()
    with _CONFIG_LOCK:
        defaults = _default_config()
        if not path.exists():
            save_config(defaults)
            return deepcopy(defaults)
        restrict_file_permissions(path)
        with path.open("r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream) or {}
        sanitized, changed, created_references = _sanitize_model_credentials(
            loaded, path
        )
        if changed:
            try:
                _write_config(path, sanitized)
            except BaseException:
                _delete_credentials(created_references, path)
                raise
        return _deep_merge(defaults, sanitized)


def save_config(cfg: dict):
    path = get_config_path()
    with _CONFIG_LOCK:
        sanitized, _, created_references = _sanitize_model_credentials(cfg, path)
        try:
            _write_config(path, sanitized)
        except BaseException:
            _delete_credentials(created_references, path)
            raise


def _write_config(path: Path, cfg: dict) -> None:
    text = yaml.safe_dump(
        cfg,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    atomic_write_text(path, text)


def _sanitize_model_credentials(
    cfg: dict, path: Path
) -> tuple[dict, bool, list[str]]:
    """Move legacy inline model credentials to protected local storage."""
    sanitized = deepcopy(cfg)
    changed = False
    created_references: list[str] = []
    models = sanitized.get("models", {})
    if not isinstance(models, dict):
        return sanitized, changed, created_references

    try:
        for entry in models.values():
            if not isinstance(entry, dict) or "api_key" not in entry:
                continue
            raw_value = entry.pop("api_key")
            changed = True
            if entry.get("api_key_env") or entry.get("api_key_secret"):
                continue
            if not isinstance(raw_value, str) or not raw_value.strip():
                continue
            match = _ENV_REFERENCE.fullmatch(raw_value.strip())
            if match:
                entry["api_key_env"] = match.group(1)
            else:
                reference = store_credential(raw_value, path)
                entry["api_key_secret"] = reference
                created_references.append(reference)
    except BaseException:
        _delete_credentials(created_references, path)
        raise
    return sanitized, changed, created_references


def _delete_credentials(references: list[str], path: Path) -> None:
    for reference in references:
        delete_credential(reference, path)


def _default_config() -> dict:
    return {
        "models": {},
        "active_model": None,
        "language": "zh",
        "memory": {
            "short_term_window": 20,
            "long_term_threshold": 30,
            "experience_top_k": 4,
            "experience_max_chars": 3000,
            "experience_vector_dimension": 256,
            "experience_max_entries": 2000,
            "experience_cross_session": False,
        },
        "cache": {
            "enabled": True,
            "prompt_prefix_cache": True,
            "ttl": 3600,
        },
        "mcpServers": {},
        "lsp": {},
        "autoCompact": True,
        "scheduler": {
            "enabled": True,
            "check_interval": 30,
            "task_timeout_seconds": 0,
        },
        # Per-model pricing in USD per 1M tokens, e.g.
        #   pricing:
        #     deepseek-chat: {input: 0.27, output: 1.10}
        # When a model has no entry here, cost is not accumulated or shown
        # (avoids displaying a wrong hard-coded price).
        "pricing": {},
        "recovery": {
            "circuit_breaker_enabled": True,
        },
        "lifecycle": {
            "hook_timeout_seconds": 5,
        },
        "observability": {
            "trajectory_retention_runs": 200,
            "trace_retention_runs": 200,
            "audit_max_bytes": 10 * 1024 * 1024,
            "audit_backup_count": 5,
        },
        "governance": {
            "model_routes": {},  # planner/executor/reflection -> configured model name
            "rate_limit": {
                "enabled": True,
                "requests_per_period": 120,
                "tokens_per_period": 2_000_000,
                "period_seconds": 60,
                "request_burst": 120,
                "token_burst": 2_000_000,
                "wait_timeout_seconds": 30,
                "reserved_output_tokens": 8192,
            },
        },
        "execution": {
            "parallel_enabled": False,  # default off, gradual rollout
            "max_parallel": 3,          # Semaphore limit to prevent API rate limits
            "max_graph_steps": 60,      # hard state-machine step budget
            "max_tool_rounds": 10,      # hard fast-path tool loop budget
            "checkpoint_enabled": True,
            "checkpoint_retention": 50,
            "tool_journal_enabled": True,
            "tool_journal_retention": 100,
            "tool_journal_max_result_chars": 30000,
            # Workspace mode constrains the selected cwd. Docker mode adds an
            # OS boundary and defaults to no network; operators can opt into it
            # once the configured image contains their required toolchain.
            "sandbox_mode": "workspace",
            "workspace_root": ".",
            "docker_image": "python:3.12-slim",
            "docker_network": "none",
            "max_memory_mb": 4096,
            "max_cpus": 2.0,
            "max_processes": 128,
            "tool_retry_attempts": 3,  # transient failures, READ tools only
            "tool_retry_wait_multiplier": 1.0,
            "tool_timeout_seconds": 1800,
            "pipeline_soft_budget_seconds": 3600,
            # Disabled by default: a legitimate silent tool may run longer
            # than ten minutes. The explicit tool and task ceilings remain.
            "task_stall_timeout_seconds": 0,
            "task_max_time_seconds": 7200,
            "heartbeat_interval_seconds": 15,
        },
        "context": {
            "summarize_tool_output": False,   # default off
            "max_tool_output_chars": 30000,
            "max_task_result_chars": 12000,
            "max_context_compressions": 2,
            "graph_context_token_limit": 232000,
        },
        # 阶段二 safety gate: risk classification + approval + audit.
        # auto_approve entries: "read" | "write" | "danger" (level names).
        "safety": {
            "enabled": True,
            "auto_approve": [],
            "allowed_write_paths": [],
            "dry_run": False,
            "approval_timeout": 120,
        },
        # Codebase vector search RAG (缝合 mentat + aider).
        # embedding.base_url / api_key default to None, which means the
        # active model's credentials are reused automatically.
        "rag": {
            "enabled": False,
            "embedding": {
                "base_url": None,  # reuse model_manager's base_url
                "api_key": None,   # reuse model_manager's api_key
                "model": "text-embedding-3-small",
            },
            "top_k": 8,
            "max_context_chars": 6000,
            "context_cache_entries": 64,
            "context_cache_ttl_seconds": 30,
            "index_delay_seconds": 2,
            "refresh_debounce_seconds": 0.25,
        },
        # Evaluation harness settings.
        # judge_model: None means "use the active model" for LLM-as-judge.
        "evals": {
            "judge_model": None,
        },
    }


def get_mcp_config(cfg: Optional[dict] = None) -> dict:
    """Get MCP servers configuration."""
    if cfg is None:
        cfg = load_config()
    return cfg.get("mcpServers", {})


def get_scheduler_config(cfg: Optional[dict] = None) -> dict:
    """Get scheduler configuration."""
    if cfg is None:
        cfg = load_config()
    return cfg.get("scheduler", {"enabled": True, "check_interval": 30})


def resolve_model_config(entry: dict) -> dict:
    """Return a runtime model config with environment references resolved."""
    resolved = dict(entry)
    env_name = resolved.get("api_key_env")
    raw_value = resolved.get("api_key")
    if not env_name and isinstance(raw_value, str):
        match = _ENV_REFERENCE.fullmatch(raw_value.strip())
        if match:
            env_name = match.group(1)
    if env_name:
        if not isinstance(env_name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", env_name
        ):
            raise ValueError("Invalid api_key_env name")
        resolved["api_key_env"] = env_name
        resolved["api_key"] = os.environ.get(env_name, "")
    elif resolved.get("api_key_secret"):
        resolved["api_key"] = load_credential(
            resolved["api_key_secret"], get_config_path()
        )
    return resolved


def get_active_model_config(cfg: Optional[dict] = None) -> dict:
    if cfg is None:
        cfg = load_config()
    name = cfg.get("active_model")
    models = cfg.get("models", {})
    if not name or name not in models:
        available = list(models.keys())
        if available:
            name = available[0]
        else:
            raise ValueError(
                "No model configured. Run: python -m RxyCode config add-model"
            )
    return resolve_model_config(models[name])


def get_model_config(model_name: str, cfg: Optional[dict] = None) -> dict:
    if cfg is None:
        cfg = load_config()
    models = cfg.get("models", {})
    if model_name not in models:
        raise ValueError(f"Model '{model_name}' not found. Available: {list(models.keys())}")
    return resolve_model_config(models[model_name])
