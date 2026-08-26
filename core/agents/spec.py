"""Static validation for AgentSpec / TeamSpec.

Catch loops and unknown roles at config time, not after tokens are spent.
"""

from __future__ import annotations

import logging
import re

from RxyCode.RxyCode1_1_0.protocol.agents import TeamSpec

#: Hard cap on Coordinator -> member delegation depth (DC6).
#: This is **not** Phase D ``subagent_depth`` (0/1/2 on ChildSession).
#: The two counters are independent: D counts isolated child sessions,
#: F counts expert-team stage hops. See PHASE-F §3.2 DC6.
MAX_DELEGATE_DEPTH = 3

_ALLOWED_EXTRA_PREFIXES = ("pair.", "vision.", "persona.", "ecosystem.")
_SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_KNOWN_ECOSYSTEM_KEYS = frozenset(
    {
        "ecosystem.skill",
        "ecosystem.extra_skills",
        "ecosystem.mcp",
        "ecosystem.is_leader",
        "ecosystem.category",
        "ecosystem.version",
        "ecosystem.disable_model_invocation",
        "ecosystem.provenance",
        "ecosystem.feasibility",
        "ecosystem.data_sources",
        "ecosystem.disclaimer",
        "ecosystem.tags",
        "ecosystem.persona_name",
        "ecosystem.example_prompts",
        "ecosystem.requires_mcp",
        "ecosystem.requires_skills",
        "ecosystem.hooks",
    }
)
_log = logging.getLogger(__name__)


class AgentSpecError(ValueError):
    """Invalid AgentSpec / TeamSpec configuration."""


def validate_team(team: TeamSpec) -> None:
    """静态校验一支专家团。

    这些检查存在的意义是在配置时拦住错误，而不是等线上跑炸。
    """
    roles = {m.role for m in team.members}
    if len(roles) != len(team.members):
        raise AgentSpecError("duplicate role in team members")

    stage_names = {s.name for s in team.stages}
    if len(stage_names) != len(team.stages):
        raise AgentSpecError("duplicate stage name")

    if team.entry_stage not in stage_names:
        raise AgentSpecError(f"entry_stage {team.entry_stage!r} is not a stage")

    for stage in team.stages:
        if stage.role not in roles:
            raise AgentSpecError(
                f"stage {stage.name!r} references unknown role {stage.role!r}"
            )
        seen_parallel: set[str] = set()
        for extra_role in stage.parallel_members or ():
            if extra_role in seen_parallel:
                raise AgentSpecError(
                    f"stage {stage.name!r} has duplicate parallel member {extra_role!r}"
                )
            seen_parallel.add(extra_role)
            if extra_role not in roles:
                raise AgentSpecError(
                    f"stage {stage.name!r} parallel_members references "
                    f"unknown role {extra_role!r}"
                )
        for nxt in (stage.next_on_success, stage.next_on_failure):
            if nxt is not None and nxt not in stage_names:
                raise AgentSpecError(
                    f"stage {stage.name!r} points at unknown stage {nxt!r}"
                )

    leaders = 0
    for member in team.members:
        if member.role in member.may_consult:
            raise AgentSpecError(f"role {member.role!r} may not consult itself")
        for target in member.may_consult:
            if target not in roles:
                raise AgentSpecError(
                    f"role {member.role!r} may_consult unknown role {target!r}"
                )
        _check_extra_namespaces(member.extra, where=f"member {member.role!r}")
        _check_role_ecosystem(member.extra, where=f"member {member.role!r}")
        flag = member.extra.get("ecosystem.is_leader")
        if flag in {True, "true", "1"}:
            leaders += 1
    if leaders > 1:
        raise AgentSpecError("ecosystem.is_leader may be true on at most one member")

    _check_extra_namespaces(team.extra, where="team")
    _report_unknown_ecosystem_keys(team.extra, where="team")
    _check_stage_graph_terminates(team)
    _check_consult_graph_acyclic(team)


def _check_extra_namespaces(extra: dict[str, object], *, where: str) -> None:
    """Namespaced extra keys must use pair.* / vision.* / persona.* / ecosystem.*."""
    for key in extra:
        if "." not in key:
            continue
        if not any(key.startswith(prefix) for prefix in _ALLOWED_EXTRA_PREFIXES):
            raise AgentSpecError(
                f"{where} extra key {key!r} uses an unknown namespace "
                f"(allowed prefixes: {', '.join(_ALLOWED_EXTRA_PREFIXES)})"
            )
    _report_unknown_ecosystem_keys(extra, where=where)


def unknown_ecosystem_keys(extra: dict[str, object]) -> list[str]:
    """Keys under ecosystem.* that are not in the documented set (LC6)."""
    found: list[str] = []
    for key in extra:
        if key.startswith("ecosystem.") and key not in _KNOWN_ECOSYSTEM_KEYS:
            found.append(str(key))
    return found


def _report_unknown_ecosystem_keys(extra: dict[str, object], *, where: str) -> None:
    """Unknown ecosystem.* keys are reported and ignored, never rejected (LC6)."""
    for key in unknown_ecosystem_keys(extra):
        _log.warning("%s extra key %r is unknown; ignoring", where, key)


def _check_skill_name(name: object, *, where: str) -> None:
    text = str(name or "").strip()
    if not text or len(text) > 64 or _SKILL_NAME_RE.fullmatch(text) is None:
        raise AgentSpecError(f"{where} has invalid skill name {name!r}")


def _check_role_ecosystem(extra: dict[str, object], *, where: str) -> None:
    skill = extra.get("ecosystem.skill")
    if skill not in (None, ""):
        _check_skill_name(skill, where=where)
    extras = extra.get("ecosystem.extra_skills")
    if extras is None:
        return
    if not isinstance(extras, (list, tuple)):
        raise AgentSpecError(f"{where} ecosystem.extra_skills must be a list")
    for item in extras:
        _check_skill_name(item, where=where)
    # ecosystem.mcp names are recorded as todos when missing; never reject register.


def _check_stage_graph_terminates(team: TeamSpec) -> None:
    """确认 SOP 图存在可达的终点。

    全是环、没有 next=None 的出口，会让团队永远跑下去（预算会兜住，但那是
    最后一道防线，不该靠它）。
    """
    by_name = {stage.name: stage for stage in team.stages}
    seen: set[str] = set()
    stack = [team.entry_stage]
    has_exit = False
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stage = by_name[name]
        for nxt in (stage.next_on_success, stage.next_on_failure):
            if nxt is None:
                has_exit = True
            elif nxt not in seen:
                stack.append(nxt)
    if not has_exit:
        raise AgentSpecError("SOP graph has no reachable exit")


def _check_consult_graph_acyclic(team: TeamSpec) -> None:
    """确认咨询图无环。

    A 可咨询 B、B 可咨询 A 会导致互相甩锅的无限往返。DFS 三色找环。
    """
    graph = {member.role: list(member.may_consult) for member in team.members}
    white, gray, black = 0, 1, 2
    color = {role: white for role in graph}

    def dfs(node: str) -> None:
        color[node] = gray
        for nxt in graph.get(node, ()):
            state = color.get(nxt)
            if state is None:
                continue
            if state == gray:
                raise AgentSpecError("consult graph contains a cycle")
            if state == white:
                dfs(nxt)
        color[node] = black

    for role in graph:
        if color[role] == white:
            dfs(role)
