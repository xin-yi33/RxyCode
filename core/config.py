# 废弃代码（2026-09-22）：v2 时代的 ~/.rxycode-v2 配置。现网配置在 config/settings.py。本模块没有任何导入方。禁止再引用。

# """Configuration management for RxyCode v2.
#
# Loads config from ~/.rxycode-v2/config.yaml with sensible defaults.
# """
#
# # NOTE: This module is legacy v2-era configuration (A11). The current
# # configuration system lives in config/settings.py. LLMConfig was dead
# # code (no importers anywhere) and was removed in A11; the module is kept
# # for the remaining legacy classes until they are migrated.
#
# from __future__ import annotations
#
# import os
# from pathlib import Path
# from typing import Optional
#
# import yaml
# from pydantic import BaseModel, Field
#
#
# # ---------------------------------------------------------------------------
# # Config models
# # ---------------------------------------------------------------------------
#
# class MemoryConfig(BaseModel):
#     """Configuration for the memory system."""
#
#     # Redis (short-term)
#     redis_url: str = "redis://localhost:6379/0"
#     short_term_window: int = 20          # 最近 N 轮对话
#
#     # Vector DB (long-term)
#     vector_provider: str = "chromadb"    # chromadb | qdrant
#     vector_collection: str = "rxycode"
#     vector_persist_dir: str = ""         # 空=内存模式
#
#     # SQLite (structured)
#     sqlite_path: str = ""                # 空=自动在 data_dir 下创建
#
#     # Compression
#     context_threshold: int = 258_000     # token 阈值，超过触发压缩
#
#
# class ExecutorConfig(BaseModel):
#     """Configuration for the executor."""
#
#     max_react_iterations: int = 12       # 单任务内 ReAct 最大循环次数
#     max_task_retries: int = 3            # 任务最大重试次数
#     max_tree_depth: int = 4              # 最大拆解深度
#
#
# class AppConfig(BaseModel):
#     """Top-level application configuration."""
#
#     memory: MemoryConfig = Field(default_factory=MemoryConfig)
#     executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
#     language: str = "zh"                 # zh | en
#     data_dir: str = ""                   # 空=自动
#
#
# # ---------------------------------------------------------------------------
# # Paths
# # ---------------------------------------------------------------------------
#
# _DEFAULT_CONFIG_DIR = Path.home() / ".rxycode-v2"
#
#
# def get_config_dir() -> Path:
#     """Return the user-level config directory, creating it if needed."""
#     env = os.environ.get("RXYCODE_V2_CONFIG_DIR")
#     p = Path(env) if env else _DEFAULT_CONFIG_DIR
#     p.mkdir(parents=True, exist_ok=True)
#     return p
#
#
# def get_data_dir(cfg: AppConfig) -> Path:
#     """Return the data directory, creating it if needed."""
#     if cfg.data_dir:
#         p = Path(cfg.data_dir)
#     else:
#         p = get_config_dir() / "data"
#     p.mkdir(parents=True, exist_ok=True)
#     return p
#
#
# def get_config_path() -> Path:
#     return get_config_dir() / "config.yaml"
#
#
# # ---------------------------------------------------------------------------
# # Load / save
# # ---------------------------------------------------------------------------
#
# def load_config(path: Optional[Path] = None) -> AppConfig:
#     """Load config from YAML file, falling back to defaults."""
#     path = path or get_config_path()
#     if not path.exists():
#         return AppConfig()
#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             raw = yaml.safe_load(f) or {}
#         return AppConfig.model_validate(raw)
#     except Exception:
#         return AppConfig()
#
#
# def save_config(cfg: AppConfig, path: Optional[Path] = None) -> None:
#     """Persist config to YAML file."""
#     path = path or get_config_path()
#     path.parent.mkdir(parents=True, exist_ok=True)
#     with open(path, "w", encoding="utf-8") as f:
#         yaml.dump(cfg.model_dump(), f, allow_unicode=True, default_flow_style=False)
