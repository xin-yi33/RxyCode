"""F13 client settings projection. Hidden when agents.enabled is false."""

from __future__ import annotations

from typing import Any

_NESTED_IDS = frozenset(
    {
        "agents_team",
        "agents_route",
        "agents_router_model",
        "agents_budget",
        "agents_timeout",
        "agents_multi_model",
    }
)

_ROUTE_LABEL = {
    "solo": "总是单 Agent",
    "auto": "自动判断",
    "team": "总是专家团",
}


def _agents(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("agents")
    return dict(raw) if isinstance(raw, dict) else {}


def settings_items(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Items for /settings. Nested multi-agent fields appear only when enabled."""
    agents = _agents(cfg)
    enabled = bool(agents.get("enabled"))
    items: list[dict[str, Any]] = [
        {
            "id": "permission",
            "label": "权限设置",
            "desc": "三档安全审批：全确认 / 写代码免批 / 全自动",
        },
        {
            "id": "language",
            "label": "界面语言",
            "desc": "中文 / English",
        },
        {
            "id": "agents_enabled",
            "label": "启用多 Agent 专家团",
            "desc": "开" if enabled else "关（默认关闭）",
            "value": enabled,
        },
    ]
    if not enabled:
        return items
    route = str(agents.get("route_mode") or "auto")
    items.extend(
        [
            {
                "id": "agents_team",
                "label": "专家团",
                "desc": str(agents.get("team") or "software_dev"),
            },
            {
                "id": "agents_route",
                "label": "路由模式",
                "desc": _ROUTE_LABEL.get(route, route),
                "value": route,
            },
            {
                "id": "agents_router_model",
                "label": "难度判断模型",
                "desc": str(agents.get("router_model") or "不使用"),
            },
            {
                "id": "agents_budget",
                "label": "token 预算",
                "desc": str(int(agents.get("total_token_budget") or 500_000)),
            },
            {
                "id": "agents_timeout",
                "label": "时长上限",
                "desc": f"{int(float(agents.get('total_timeout_s') or 1800))} 秒",
            },
            {
                "id": "agents_multi_model",
                "label": "启用多模型协作（每角色不同模型）",
                "desc": (
                    "开"
                    if bool((agents.get("multi_model") or {}).get("enabled"))
                    else "关（默认关闭）"
                ),
                "value": bool((agents.get("multi_model") or {}).get("enabled")),
                "disabled": False,
            },
        ]
    )
    return items


def hidden_when_disabled(items: list[dict[str, Any]]) -> bool:
    ids = {str(item.get("id")) for item in items}
    return ids.isdisjoint(_NESTED_IDS)


def apply_agents_args(cfg: dict[str, Any], args: str) -> tuple[dict[str, Any], str]:
    """Mutate cfg['agents'] from `/agents` arguments. Returns (agents, message)."""
    agents = cfg.setdefault("agents", {})
    if not isinstance(agents, dict):
        agents = {}
        cfg["agents"] = agents
    raw = (args or "").strip()
    if not raw:
        enabled = bool(agents.get("enabled"))
        return agents, (
            f"agents.enabled={enabled} team={agents.get('team') or 'software_dev'} "
            f"route={agents.get('route_mode') or 'auto'} "
            f"router_model={agents.get('router_model') or 'none'}"
        )
    parts = raw.split(None, 1)
    verb = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    if verb in {"on", "off"}:
        agents["enabled"] = verb == "on"
        return agents, f"agents.enabled={agents['enabled']}"
    if verb == "team" and rest:
        agents["team"] = rest
        return agents, f"agents.team={rest}"
    if verb == "route" and rest in {"solo", "auto", "team"}:
        agents["route_mode"] = rest
        return agents, f"agents.route_mode={rest}"
    if verb in {"router-model", "router_model"}:
        agents["router_model"] = None if rest in {"", "none", "不使用"} else rest
        return agents, f"agents.router_model={agents['router_model'] or 'none'}"
    if verb == "budget" and rest:
        agents["total_token_budget"] = int(rest)
        return agents, f"agents.total_token_budget={agents['total_token_budget']}"
    if verb == "timeout" and rest:
        agents["total_timeout_s"] = float(rest)
        return agents, f"agents.total_timeout_s={agents['total_timeout_s']}"
    if verb in {"multi-model", "multi_model"} and rest in {"on", "off"}:
        mm = agents.setdefault("multi_model", {})
        if not isinstance(mm, dict):
            mm = {}
            agents["multi_model"] = mm
        mm["enabled"] = rest == "on"
        return agents, f"agents.multi_model.enabled={mm['enabled']}"
    if verb in {"role-model", "role_model"} and rest:
        parts = rest.split(None, 1)
        role = parts[0]
        model = parts[1].strip() if len(parts) > 1 else ""
        mm = agents.setdefault("multi_model", {})
        if not isinstance(mm, dict):
            mm = {}
            agents["multi_model"] = mm
        roles = mm.setdefault("role_models", {})
        if not isinstance(roles, dict):
            roles = {}
            mm["role_models"] = roles
        if model in {"", "none"}:
            roles.pop(role, None)
        else:
            roles[role] = model
        return agents, f"agents.multi_model.role_models.{role}={roles.get(role) or 'none'}"
    return agents, (
        "用法: /agents on|off | team <name> | route solo|auto|team | "
        "router-model <id>|none | budget <n> | timeout <s> | "
        "multi-model on|off | role-model <role> <model>|none"
    )
