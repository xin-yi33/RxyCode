"""Builtin TeamSpec loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from RxyCode.RxyCode1_1_0.core.agents.spec import validate_team
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec, SopStage, TeamSpec

_DIR = Path(__file__).resolve().parent


def load_team_from_mapping(raw: dict[str, Any]) -> TeamSpec:
    """Build and validate a TeamSpec from a team.yaml mapping."""
    if not isinstance(raw, dict):
        raise ValueError("team mapping must be a dict")
    members = [AgentSpec(**row) for row in raw.get("members") or []]
    stages = [SopStage(**row) for row in raw.get("stages") or []]
    team = TeamSpec(
        name=str(raw["name"]),
        display_name=str(raw.get("display_name") or raw["name"]),
        description=str(raw.get("description") or ""),
        members=members,
        stages=stages,
        entry_stage=str(raw.get("entry_stage") or (stages[0].name if stages else "")),
        total_token_budget=int(raw.get("total_token_budget", 500_000)),
        total_timeout_s=float(raw.get("total_timeout_s", 1800)),
        max_delegations=int(raw.get("max_delegations", 20)),
        extra=dict(raw.get("extra") or {}),
    )
    validate_team(team)
    return team


def builtin_team_path(name: str = "software_dev") -> Path:
    directory = _DIR / name / "team.yaml"
    if directory.is_file():
        return directory
    return _DIR / f"{name}.yaml"


def load_builtin_team(name: str = "software_dev") -> TeamSpec:
    path = builtin_team_path(name)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return load_team_from_mapping(raw)
