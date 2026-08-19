"""PhaseG-B4 recent projects. Remove does not delete user code."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import PathBoundaryError, assert_exists, canonicalize

try:
    from config.settings import get_data_dir
except ImportError:
    from config.settings import get_data_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProjectStore:
    def __init__(self, path: Path | None = None, *, persistent: bool = True) -> None:
        self.persistent = persistent
        self.path = path or (get_data_dir() / "desktop" / "projects.json")
        if persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"projects": {}, "active_id": None}
        self._load()

    def _load(self) -> None:
        if not self.persistent:
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(value, dict):
            self._data.update(value)
            if not isinstance(self._data.get("projects"), dict):
                self._data["projects"] = {}

    def _save(self) -> None:
        if not self.persistent:
            return
        payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(prefix="projects-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def add(self, raw_path: str, *, display_name: str | None = None) -> dict[str, Any]:
        real = assert_exists(canonicalize(raw_path))
        if not real.is_dir():
            raise PathBoundaryError("PATH_NOT_FOUND", f"not a directory: {real}")
        project_id = str(real)
        project = {
            "project_id": project_id,
            "display_name": (display_name or real.name).strip() or real.name,
            "path": str(real),
            "updated_at": _now(),
        }
        self._data["projects"][project_id] = project
        self._data["active_id"] = project_id
        self._save()
        return dict(project)

    def list(self) -> list[dict[str, Any]]:
        values = list(self._data["projects"].values())
        return sorted(values, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    def remove(self, project_id: str) -> None:
        if project_id not in self._data["projects"]:
            raise PathBoundaryError("PATH_NOT_FOUND", f"unknown project: {project_id}")
        del self._data["projects"][project_id]
        if self._data.get("active_id") == project_id:
            remaining = self.list()
            self._data["active_id"] = remaining[0]["project_id"] if remaining else None
        self._save()

    def set_active(self, project_id: str) -> dict[str, Any]:
        project = self._data["projects"].get(project_id)
        if not isinstance(project, dict):
            raise PathBoundaryError("PATH_NOT_FOUND", f"unknown project: {project_id}")
        self._data["active_id"] = project_id
        project["updated_at"] = _now()
        self._save()
        return dict(project)

    def get(self, project_id: str) -> dict[str, Any] | None:
        item = self._data["projects"].get(project_id)
        return dict(item) if isinstance(item, dict) else None

    def active(self) -> dict[str, Any] | None:
        active_id = self._data.get("active_id")
        if not active_id:
            return None
        return self.get(str(active_id))
