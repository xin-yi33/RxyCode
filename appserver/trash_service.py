"""PhaseG-B17 recycle bin: index exclusion and workspace-bound file purge."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .workspace import PathBoundaryError, canonicalize, is_inside


class TrashError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ThreadIndex:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._hits: dict[str, str] = {}
        if path and path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._hits = {str(k): str(v) for k, v in raw.items()}
            except (OSError, json.JSONDecodeError):
                self._hits = {}

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._hits, ensure_ascii=False), encoding="utf-8")

    def upsert(self, session_id: str, title: str, *, deleted: bool = False) -> None:
        if deleted:
            self.exclude(session_id)
            return
        self._hits[session_id] = title
        self._save()

    def reconcile(self, deleted_ids: list[str]) -> None:
        for session_id in deleted_ids:
            self._hits.pop(session_id, None)
        self._save()

    def exclude(self, session_id: str) -> None:
        self._hits.pop(session_id, None)
        self._save()

    def searchable(self, session_id: str) -> bool:
        return session_id in self._hits

    def search(self, query: str) -> list[str]:
        needle = (query or "").lower()
        return [sid for sid, title in self._hits.items() if needle in title.lower() or needle in sid.lower()]


class TrashService:
    def __init__(self, sessions: Any, index: ThreadIndex | None = None) -> None:
        self.sessions = sessions
        self.index = index or ThreadIndex()
        deleted = [record.session_id for record in sessions.list_deleted()] if hasattr(sessions, "list_deleted") else []
        self.index.reconcile(deleted)

    def associated_dir(self, workspace: Path, session_id: str) -> Path:
        if not session_id or any(part in session_id for part in ("/", "\\", "..")):
            raise TrashError("PATH_OUTSIDE_WORKSPACE", "invalid session_id for associated dir")
        root = canonicalize(workspace)
        folder = canonicalize(root / ".rxy-thread" / session_id)
        if not is_inside(root, folder):
            raise TrashError("PATH_OUTSIDE_WORKSPACE", "associated dir escaped workspace")
        return folder

    def _lexical_parts(self, workspace: Path, path: Path) -> tuple[Path, tuple[str, ...]]:
        root = canonicalize(workspace)
        raw = path if os.path.isabs(str(path)) else root / path
        lexical = Path(os.path.normpath(str(raw)))
        root_s = os.path.normpath(str(root))
        lex_s = os.path.normpath(str(lexical))
        if os.name == "nt":
            root_s = os.path.normcase(root_s)
            lex_s = os.path.normcase(lex_s)
        if lex_s == root_s:
            return root, ()
        if not lex_s.startswith(root_s + os.sep):
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"dir escaped workspace: {path}")
        remainder = str(lexical)[len(str(root)) :].lstrip("\\/")
        parts = tuple(part for part in Path(remainder).parts if part not in {"", ".", ".."})
        if ".." in Path(remainder).parts:
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"dir escaped workspace: {path}")
        return root, parts

    def _ensure_dir_inside(self, workspace: Path, path: Path) -> Path:
        root, parts = self._lexical_parts(workspace, path)
        if not parts:
            raise TrashError("PATH_OUTSIDE_WORKSPACE", "refuse to use workspace root as trash dir")
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise TrashError("PATH_OUTSIDE_WORKSPACE", f"refuse symlink dir: {current}")
        current.mkdir(parents=True, exist_ok=True)
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise TrashError("PATH_OUTSIDE_WORKSPACE", f"refuse symlink dir: {current}")
        resolved = canonicalize(current)
        if resolved == root or not is_inside(root, resolved):
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"dir escaped workspace: {path}")
        return resolved

    def _safe_write(self, workspace: Path, path: Path, text: str) -> Path:
        if path.is_symlink():
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"refuse to write through symlink: {path}")
        parent = self._ensure_dir_inside(workspace, path.parent)
        target = parent / path.name
        if target.is_symlink():
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"refuse to write through symlink: {target}")
        fd, tmp_name = tempfile.mkstemp(prefix="trash-", suffix=".tmp", dir=str(parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            if target.is_symlink():
                raise TrashError("PATH_OUTSIDE_WORKSPACE", f"refuse to write through symlink: {target}")
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        resolved = canonicalize(target)
        if resolved == canonicalize(workspace) or not is_inside(canonicalize(workspace), resolved):
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"write escaped workspace: {path}")
        return resolved

    def _resolve_in_workspace(self, workspace: Path, raw: str | Path) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = workspace / path
        try:
            resolved = canonicalize(path)
            if resolved.is_symlink():
                resolved = canonicalize(resolved.resolve())
        except (PathBoundaryError, OSError) as exc:
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"cannot resolve path: {raw}") from exc
        return resolved

    def _guard(self, workspace: Path, raw: str | Path) -> Path:
        resolved = self._resolve_in_workspace(workspace, raw)
        if resolved == workspace or not is_inside(workspace, resolved):
            raise TrashError("PATH_OUTSIDE_WORKSPACE", f"refuse to touch outside workspace: {raw}")
        return resolved

    def _inventory_paths(self, workspace: Path, session_id: str, extra_paths: list[str] | None = None) -> list[Path]:
        assoc = self.associated_dir(workspace, session_id)
        record = self.sessions.get(session_id)
        listed: list[str] = []
        if record is not None:
            listed.extend(getattr(record, "associated_files", None) or [])
        inventory: list[Path] = [assoc]
        if assoc.exists():
            for child in assoc.rglob("*"):
                inventory.append(child)
        for raw in list(listed) + list(extra_paths or []):
            inventory.append(self._guard(workspace, raw))
        unique: list[Path] = []
        seen: set[str] = set()
        for item in inventory:
            key = os.path.normcase(str(item))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _write_inventory(self, workspace: Path, folder: Path, session_id: str, paths: list[Path]) -> Path:
        manifest = folder / "associated_files.json"
        payload = {
            "session_id": session_id,
            "files": [str(path) for path in paths],
        }
        return self._safe_write(workspace, manifest, json.dumps(payload, ensure_ascii=False, indent=2))

    def delete(self, session_id: str) -> dict[str, Any]:
        record = self.sessions.trash(session_id)
        self.index.exclude(session_id)
        workspace = canonicalize(Path(record.workspace_root))
        folder = self._ensure_dir_inside(workspace, self.associated_dir(workspace, session_id))
        marker = self._safe_write(workspace, folder / "session.marker", session_id)
        paths = [folder, marker]
        if hasattr(self.sessions, "remember_associated"):
            record = self.sessions.remember_associated(session_id, [str(item) for item in paths])
            paths = [Path(item) for item in record.associated_files] or paths
        manifest = self._write_inventory(workspace, folder, session_id, paths)
        if hasattr(self.sessions, "remember_associated"):
            files = list(record.associated_files or [])
            if str(manifest) not in files:
                files.append(str(manifest))
            record = self.sessions.remember_associated(session_id, files)
        return {
            "session_id": record.session_id,
            "deleted_at": record.deleted_at or record.trashed_at,
            "restored_at": record.restored_at,
            "list_category": getattr(record, "list_category", None) or "recent",
            "associated_dir": str(folder),
            "associated_files": list(getattr(record, "associated_files", None) or [str(p) for p in paths]),
        }

    def restore(self, session_id: str) -> dict[str, Any]:
        record = self.sessions.restore(session_id)
        self.index.upsert(record.session_id, record.title, deleted=False)
        category = getattr(record, "list_category", None) or ("archive" if record.archived_at else "recent")
        return {
            "session_id": record.session_id,
            "deleted_at": record.deleted_at,
            "restored_at": record.restored_at,
            "list_category": category,
            "archived_at": record.archived_at,
        }

    def list_deleted(self) -> dict[str, Any]:
        rows = []
        for record in self.sessions.list_deleted():
            rows.append(
                {
                    "session_id": record.session_id,
                    "title": record.title,
                    "deleted_at": record.deleted_at or record.trashed_at,
                    "restored_at": record.restored_at,
                    "list_category": getattr(record, "list_category", None) or "recent",
                    "associated_files": list(getattr(record, "associated_files", None) or []),
                }
            )
        return {"threads": rows}

    def _remove_path(self, workspace: Path, assoc: Path, target: Path) -> None:
        checked = self._guard(workspace, target)
        if checked == workspace:
            raise TrashError("PATH_OUTSIDE_WORKSPACE", "refuse to delete workspace root")
        if checked.is_symlink() or checked.is_file():
            checked.unlink()
            return
        if checked.is_dir():
            if checked != assoc and not is_inside(assoc, checked):
                raise TrashError(
                    "PATH_OUTSIDE_WORKSPACE",
                    "refuse to rmtree workspace dirs outside associated dir",
                )
            shutil.rmtree(checked)

    def purge(self, session_id: str, *, confirm_purge: object, extra_paths: list[str] | None = None) -> dict[str, Any]:
        if confirm_purge is not True:
            raise TrashError("PURGE_UNCONFIRMED", "thread/purge requires confirm_purge=true")
        record = self.sessions.get(session_id)
        if record is None:
            raise TrashError("THREAD_NOT_FOUND", f"unknown session {session_id}")
        if not (record.deleted_at or record.trashed_at):
            raise TrashError("THREAD_NOT_DELETED", "purge only applies to soft-deleted threads")
        workspace = canonicalize(Path(record.workspace_root))
        assoc = self.associated_dir(workspace, session_id)
        targets = self._inventory_paths(workspace, session_id, extra_paths)
        journal_dir = self._ensure_dir_inside(workspace, workspace / ".rxy-thread" / ".purge-journal")
        journal = self._safe_write(
            workspace,
            journal_dir / f"{session_id}.json",
            json.dumps({"session_id": session_id, "files": [str(item) for item in targets]}, ensure_ascii=False),
        )
        removed: list[str] = []
        files = [item for item in targets if item.is_file() or item.is_symlink()]
        dirs = [item for item in targets if item.is_dir() and not item.is_symlink()]
        dirs.sort(key=lambda item: len(str(item)), reverse=True)
        try:
            for target in files + dirs:
                if not target.exists() and not target.is_symlink():
                    continue
                self._remove_path(workspace, assoc, target)
                removed.append(str(target))
            leftover = [str(item) for item in targets if item.exists()]
            if leftover:
                raise TrashError("PURGE_INCOMPLETE", f"associated files remain: {leftover}")
            self.index.exclude(session_id)
            self.sessions.purge(session_id)
        except TrashError:
            raise
        except OSError as exc:
            raise TrashError("PURGE_INCOMPLETE", f"file delete failed before record purge: {exc}") from exc
        else:
            if journal.exists():
                journal.unlink()
        return {
            "ok": True,
            "session_id": session_id,
            "removed": removed,
            "purged": True,
            "checked": [str(item) for item in targets],
        }
