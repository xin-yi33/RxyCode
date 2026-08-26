"""Import/export team packages. Hooks stay disabled unless created locally."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agents.registry import TeamRegistry, TeamRegistryError
from RxyCode.RxyCode1_1_0.core.agents.spec import validate_team
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team


class TeamImporter:
    def __init__(self, registry: TeamRegistry) -> None:
        self.registry = registry

    def import_directory(self, src: Path, *, group: str = "other", local: bool = False) -> str:
        team_yaml = src / "team.yaml"
        if not team_yaml.exists():
            raise TeamRegistryError("package missing team.yaml")
        dest = self.registry.root / src.name
        if dest.resolve() != src.resolve():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        else:
            dest = src
        hooks = dest / "hooks"
        if hooks.exists() and not local:
            (dest / "hooks.disabled").write_text("third-party hooks disabled\n", encoding="utf-8")
        self.registry.scan()
        if src.name not in self.registry.records:
            # scan uses folder name vs team.name
            self.registry.scan()
        team_name = next(iter(self.registry.records), src.name)
        # Prefer the name inside yaml
        for rec in self.registry.records.values():
            if rec.path.parent.name == dest.name:
                team_name = rec.team.name
                break
        self.registry.assign_group(team_name, group)
        self.registry.scan()
        return team_name

    def import_zip(self, archive: Path, *, group: str = "other") -> str:
        dest = self.registry.root / "_incoming"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
        # find team.yaml
        found = next(dest.rglob("team.yaml"), None)
        if found is None:
            raise TeamRegistryError("zip missing team.yaml")
        return self.import_directory(found.parent, group=group, local=False)

    def import_github(self, url: str, *, downloader, group: str = "other") -> str:
        target = self.registry.root / "_github"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        downloader(url, target)
        return self.import_directory(target, group=group, local=False)

    def export_directory(self, team_id: str, dest: Path) -> Path:
        rec = self.registry.records.get(team_id)
        if rec is None:
            raise TeamRegistryError(f"unknown team {team_id}")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(rec.path.parent, dest)
        return dest


def write_sample_package(dest: Path, *, name: str = "demo", disable_model: bool = False) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    base = load_builtin_team()
    extra = dict(base.extra)
    extra["ecosystem.category"] = "other"
    extra["ecosystem.version"] = "1.0"
    extra.pop("ecosystem.disable_model_invocation", None)
    if disable_model:
        extra["ecosystem.disable_model_invocation"] = True
    team_yaml = dest / "team.yaml"
    import yaml

    team_yaml.write_text(
        yaml.safe_dump(
            {
                "name": name,
                "display_name": name,
                "description": "何时使用：演示导入。用于测试注册表。",
                "entry_stage": base.entry_stage,
                "extra": extra,
                "members": [m.model_dump() for m in base.members],
                "stages": [s.model_dump() for s in base.stages],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    validate_team(base)
    return dest
