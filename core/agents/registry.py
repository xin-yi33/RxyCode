"""TeamRegistry: scan, validate, group, route index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir
from RxyCode.RxyCode1_1_0.core.agents.spec import AgentSpecError, validate_team
from RxyCode.RxyCode1_1_0.core.agents.teams import load_team_from_mapping
from RxyCode.RxyCode1_1_0.protocol.agents import TeamSpec

BUILTIN_GROUPS = ("builtin", "other")
DESCRIPTION_LIMIT = 1536


class TeamRegistryError(ValueError):
    """Invalid team package or group operation."""


@dataclass
class TeamRecord:
    team: TeamSpec
    path: Path
    group: str = "other"


def teams_root() -> Path:
    root = get_data_dir() / "teams"
    root.mkdir(parents=True, exist_ok=True)
    return root


def groups_path() -> Path:
    return teams_root() / "teams.groups.yaml"


def _load_team_yaml(path: Path) -> TeamSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TeamRegistryError(f"{path} is not a team mapping")
    try:
        return load_team_from_mapping(raw)
    except (AgentSpecError, TypeError, KeyError, ValueError) as exc:
        raise TeamRegistryError(f"{path} is not a team mapping") from exc


def route_blurb(team: TeamSpec) -> str:
    text = (team.description or "").strip()
    return text[:DESCRIPTION_LIMIT]


def model_may_see(team: TeamSpec) -> bool:
    extra = team.extra or {}
    return extra.get("ecosystem.disable_model_invocation") not in {True, "true", "1"}


class TeamRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or teams_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.records: dict[str, TeamRecord] = {}
        self.groups: dict[str, list[str]] = {name: [] for name in BUILTIN_GROUPS}
        self._load_groups()
        self.scan()

    def _load_groups(self) -> None:
        path = self.root / "teams.groups.yaml"
        if not path.exists():
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups = raw.get("groups") if isinstance(raw, dict) else raw
        if isinstance(groups, dict):
            for name, members in groups.items():
                self.groups[str(name)] = [str(m) for m in (members or [])]

    def _save_groups(self) -> None:
        path = self.root / "teams.groups.yaml"
        path.write_text(
            yaml.safe_dump({"groups": self.groups}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def scan(self) -> None:
        self.records.clear()
        for team_yaml in self.root.glob("*/team.yaml"):
            try:
                team = _load_team_yaml(team_yaml)
            except (AgentSpecError, TeamRegistryError, Exception) as exc:
                raise TeamRegistryError(f"reject {team_yaml}: {exc}") from exc
            group = self._group_of(team.name)
            self.records[team.name] = TeamRecord(team=team, path=team_yaml, group=group)
        self._scan_builtins()

    def _scan_builtins(self) -> None:
        from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team

        builtin_dir = Path(__file__).resolve().parent / "teams"
        found: list[Path] = []
        found.extend(sorted(builtin_dir.glob("*/team.yaml")))
        found.extend(sorted(builtin_dir.glob("*.yaml")))
        seen: set[str] = set()
        for path in found:
            name = path.parent.name if path.name == "team.yaml" else path.stem
            if name in seen or name in self.records:
                continue
            seen.add(name)
            try:
                team = load_builtin_team(name)
            except Exception:
                continue
            self.records[team.name] = TeamRecord(team=team, path=path, group="builtin")
            members = self.groups.setdefault("builtin", [])
            if team.name not in members:
                members.append(team.name)

    def _group_of(self, team_id: str) -> str:
        for name, members in self.groups.items():
            if team_id in members:
                return name
        self.groups.setdefault("other", []).append(team_id)
        return "other"

    def register(self, team: TeamSpec, *, group: str = "other") -> None:
        validate_team(team)
        dest = self.root / team.name
        dest.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "name": team.name,
            "display_name": team.display_name,
            "description": team.description,
            "entry_stage": team.entry_stage,
            "total_token_budget": team.total_token_budget,
            "total_timeout_s": team.total_timeout_s,
            "max_delegations": team.max_delegations,
            "extra": dict(team.extra),
            "members": [m.model_dump() for m in team.members],
            "stages": [s.model_dump() for s in team.stages],
        }
        (dest / "team.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self.assign_group(team.name, group)
        self.scan()

    def assign_group(self, team_id: str, group: str) -> None:
        for members in self.groups.values():
            if team_id in members:
                members.remove(team_id)
        self.groups.setdefault(group, []).append(team_id)
        self._save_groups()

    def rename_group(self, old: str, new: str) -> None:
        if old in BUILTIN_GROUPS:
            raise TeamRegistryError("builtin groups cannot be renamed")
        if old not in self.groups:
            raise TeamRegistryError(f"unknown group {old}")
        self.groups[new] = self.groups.pop(old)
        self._save_groups()

    def delete_group(self, name: str) -> None:
        if name in BUILTIN_GROUPS:
            raise TeamRegistryError("builtin groups cannot be deleted")
        members = self.groups.pop(name, [])
        self.groups.setdefault("other", []).extend(members)
        self._save_groups()
        self.scan()

    def auto_visible(self) -> list[TeamSpec]:
        return [record.team for record in self.records.values() if model_may_see(record.team)]

    def match(self, query: str) -> list[TeamSpec]:
        needle = (query or "").lower()
        hits = []
        for record in self.records.values():
            if not model_may_see(record.team):
                continue
            blurb = route_blurb(record.team).lower()
            if needle in blurb or needle in record.team.name.lower():
                hits.append(record.team)
        return hits
