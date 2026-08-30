"""agents/settings_get|set — persist agents.* including multi_model."""

from __future__ import annotations

from typing import Any

from RxyCode.RxyCode1_1_0.config.settings import load_config, save_config

_ROUTE_MODES = {"solo", "auto", "team"}


def _agents_block(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("agents")
    if not isinstance(raw, dict):
        raw = {}
        cfg["agents"] = raw
    mm = raw.get("multi_model")
    if not isinstance(mm, dict):
        mm = {"enabled": False, "master_model": None, "role_models": {}}
        raw["multi_model"] = mm
    if not isinstance(mm.get("role_models"), dict):
        mm["role_models"] = {}
    return raw


def _snapshot(agents: dict[str, Any]) -> dict[str, Any]:
    mm = agents.get("multi_model") if isinstance(agents.get("multi_model"), dict) else {}
    roles = mm.get("role_models") if isinstance(mm.get("role_models"), dict) else {}
    return {
        "enabled": bool(agents.get("enabled")),
        "team": str(agents.get("team") or "software_dev"),
        "route_mode": str(agents.get("route_mode") or "auto"),
        "router_model": agents.get("router_model"),
        "total_token_budget": int(agents.get("total_token_budget") or 500_000),
        "total_timeout_s": float(agents.get("total_timeout_s") or 1800),
        "multi_model": {
            "enabled": bool(mm.get("enabled")),
            "master_model": mm.get("master_model"),
            "role_models": {str(role): str(model) for role, model in roles.items() if str(model).strip()},
        },
    }


def agents_settings_get() -> dict[str, Any]:
    cfg = load_config()
    return _snapshot(_agents_block(cfg))


def agents_settings_set(params: dict[str, Any] | None) -> dict[str, Any]:
    cfg = load_config()
    agents = _agents_block(cfg)
    payload = params or {}
    if "enabled" in payload and payload["enabled"] is not None:
        agents["enabled"] = bool(payload["enabled"])
    if isinstance(payload.get("team"), str) and payload["team"].strip():
        agents["team"] = payload["team"].strip()
    route = payload.get("route_mode")
    if route in _ROUTE_MODES:
        agents["route_mode"] = route
    if payload.get("clear_router_model") is True:
        agents["router_model"] = None
    elif "router_model" in payload:
        raw = payload["router_model"]
        agents["router_model"] = None if raw in (None, "", "none") else str(raw)
    if payload.get("total_token_budget") is not None:
        agents["total_token_budget"] = int(payload["total_token_budget"])
    if payload.get("total_timeout_s") is not None:
        agents["total_timeout_s"] = float(payload["total_timeout_s"])
    mm_in = payload.get("multi_model")
    if isinstance(mm_in, dict):
        mm = agents.setdefault("multi_model", {})
        if not isinstance(mm, dict):
            mm = {}
            agents["multi_model"] = mm
        if "enabled" in mm_in:
            mm["enabled"] = bool(mm_in["enabled"])
        if "master_model" in mm_in:
            master = mm_in["master_model"]
            mm["master_model"] = None if master in (None, "", "none") else str(master)
        if "role_models" in mm_in and isinstance(mm_in["role_models"], dict):
            mm["role_models"] = {
                str(role): str(model)
                for role, model in mm_in["role_models"].items()
                if str(model).strip()
            }
    save_config(cfg)
    return _snapshot(agents)
