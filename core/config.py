"""Configuration management for RxyCode v2.

Loads config from ~/.rxycode-v2/config.yaml with sensible defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    """Configuration for an LLM provider."""

    provider: str = "openai"
    model_name: str = "gpt-4o"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.7
    max_tokens: int = 8192


class MemoryConfig(BaseModel):
    """Configuration for the memory system."""

    # Redis (short-term)
    redis_url: str = "redis://localhost:6379/0"
    short_term_window: int = 20          # 最近 N 轮对话

    # Vector DB (long-term)
    vector_provider: str = "chromadb"    # chromadb | qdrant
    vector_collection: str = "rxycode"
    vector_persist_dir: str = ""         # 空=内存模式

    # SQLite (structured)
    sqlite_path: str = ""                # 空=自动在 data_dir 下创建

    # Compression
    context_threshold: int = 258_000     # token 阈值，超过触发压缩


class ExecutorConfig(BaseModel):
    """Configuration for the executor."""

    max_react_iterations: int = 12       # 单任务内 ReAct 最大循环次数
    max_task_retries: int = 3            # 任务最大重试次数
    max_tree_depth: int = 4              # 最大拆解深度


class AppConfig(BaseModel):
    """Top-level application configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    language: str = "zh"                 # zh | en
    data_dir: str = ""                   # 空=自动


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_DIR = Path.home() / ".rxycode-v2"


def get_config_dir() -> Path:
    """Return the user-level config directory, creating it if needed."""
    env = os.environ.get("RXYCODE_V2_CONFIG_DIR")
    p = Path(env) if env else _DEFAULT_CONFIG_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_data_dir(cfg: AppConfig) -> Path:
    """Return the data directory, creating it if needed."""
    if cfg.data_dir:
        p = Path(cfg.data_dir)
    else:
        p = get_config_dir() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_config_path() -> Path:
    return get_config_dir() / "config.yaml"


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load config from YAML file, falling back to defaults."""
    path = path or get_config_path()
    if not path.exists():
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig.model_validate(raw)
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> None:
    """Persist config to YAML file."""
    path = path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg.model_dump(), f, allow_unicode=True, default_flow_style=False)
