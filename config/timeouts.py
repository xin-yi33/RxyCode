"""超时时钟单一注册表（Phase-Fix4 F4-7）。

废弃代码（2026-10-08 版）：20/180/300/60 硬编码于 core/agent_v2.py:224-231，
stall/max_time/check 散读于 core/graph.py:434-445，1800/120 于
execution/tool_orchestrator.py:612/626，heartbeat/stall env 直读于
appserver/watchdog.py:11-18，pipeline 预算散读于 agent_v2.py:8067-8070 ——
全部已路由到 TIMEOUT_REGISTRY：call site 只许 resolve_timeout(name, cfg)，
禁止再写时钟字面量。ERROR_LIMIT（loop_exit.py:29）是策略不是时钟，不进表。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeoutSpec:
    name: str
    default: float
    cap: float | None = None          # cap 语义保留：解析结果再大也被 cap
    env: str | None = None            # env 覆盖（appserver 侧现状 env 保留）
    cfg_path: tuple[str, ...] | None = None  # config.yaml 覆盖路径（优先级最高）


TIMEOUT_REGISTRY: dict[str, TimeoutSpec] = {
    "stream.connect_seconds": TimeoutSpec("stream.connect_seconds", 20.0),
    "stream.idle_seconds": TimeoutSpec("stream.idle_seconds", 180.0, cap=300.0),
    "stream.tool_argument_idle_seconds": TimeoutSpec("stream.tool_argument_idle_seconds", 60.0),
    "pipeline.soft_budget_seconds": TimeoutSpec(
        "pipeline.soft_budget_seconds", 3600.0,
        cfg_path=("execution", "pipeline_soft_budget_seconds"),
    ),
    "graph.task_stall_timeout_seconds": TimeoutSpec(
        "graph.task_stall_timeout_seconds", 0.0,
        cfg_path=("execution", "task_stall_timeout_seconds"),
    ),
    "graph.task_max_time_seconds": TimeoutSpec(
        "graph.task_max_time_seconds", 7200.0,
        cfg_path=("execution", "task_max_time_seconds"),
    ),
    "graph.heartbeat_interval_seconds": TimeoutSpec(
        "graph.heartbeat_interval_seconds", 15.0,
        cfg_path=("execution", "heartbeat_interval_seconds"),
    ),
    "tool.timeout_seconds": TimeoutSpec(
        "tool.timeout_seconds", 1800.0,
        cfg_path=("execution", "tool_timeout_seconds"),
    ),
    "tool.stall_timeout_seconds": TimeoutSpec(
        "tool.stall_timeout_seconds", 120.0,
        cfg_path=("execution", "tool_stall_timeout_seconds"),
    ),
    "appserver.heartbeat_seconds": TimeoutSpec(
        "appserver.heartbeat_seconds", 15.0,
        env="RXYCODE_APPSERVER_HEARTBEAT_SECONDS",
    ),
    "appserver.stall_seconds": TimeoutSpec(
        "appserver.stall_seconds", 120.0,
        env="RXYCODE_APPSERVER_STALL_SECONDS",
    ),
    "appserver.stall_grace_seconds": TimeoutSpec(
        "appserver.stall_grace_seconds", 20.0,
        env="RXYCODE_APPSERVER_STALL_GRACE_SECONDS",
        cfg_path=("appserver", "stall_grace_seconds"),
    ),
}


def _dig(cfg: dict, path: tuple[str, ...]):
    node = cfg
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def with_legacy_falsy(
    cfg: dict | None,
    section: str,
    key: str,
    replacement: float,
) -> dict:
    """Keep the old ``raw or replacement`` read for a present but falsy value.

    A missing key stays missing, so ``resolve_timeout`` still applies the
    registry default. ``None`` / ``0`` / ``""`` used to fall through ``or``
    and must not be treated as "missing".
    """
    if not isinstance(cfg, dict):
        return {}
    section_node = cfg.get(section)
    if not isinstance(section_node, dict) or key not in section_node:
        return cfg
    if section_node[key]:
        return cfg
    copied = dict(cfg)
    copied_section = dict(section_node)
    copied_section[key] = replacement
    copied[section] = copied_section
    return copied


def resolve_timeout(name: str, cfg: dict | None = None) -> float:
    """cfg 覆盖 > env 覆盖 > default → cap 钳制。

    cfg 键 = spec.cfg_path 或 name 派生路径；未知 name → KeyError；
    env 不可解析 → ValueError（与现状 float() 自然行为一致）。
    """
    spec = TIMEOUT_REGISTRY[name]  # fail-fast：未知旋钮绝不静默兜底
    raw = _dig(cfg or {}, spec.cfg_path or tuple(name.split(".")))
    if raw is None and spec.env:
        raw = os.environ.get(spec.env)
    value = float(raw) if raw is not None else spec.default
    if spec.cap is not None:
        value = min(value, spec.cap)
    return value
