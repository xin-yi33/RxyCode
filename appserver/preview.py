"""PhaseG-B9 read-only file preview. Never writes user files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .workspace import PathBoundaryError, assert_inside_workspace, canonicalize

MAX_PREVIEW_BYTES = 256_000
TEXT_EXT = {".md", ".txt", ".py", ".ts", ".tsx", ".js", ".json", ".yml", ".yaml", ".toml", ".css", ".html"}


def _inside(workspace: Path, raw: str) -> Path:
    root = canonicalize(workspace)
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / raw
    return assert_inside_workspace(root, candidate)


def preview_file(workspace: Path, raw: str) -> dict[str, Any]:
    root = canonicalize(workspace)
    target = _inside(root, raw)
    if not target.exists() or not target.is_file():
        raise PathBoundaryError("PATH_NOT_FOUND", f"not a file: {target}")
    size = target.stat().st_size
    rel = str(target.relative_to(root)).replace("\\", "/")
    if size > MAX_PREVIEW_BYTES:
        return {
            "path": rel,
            "kind": "too_large",
            "size": size,
            "content": None,
            "placeholder": "file too large to preview",
        }
    data = target.read_bytes()
    sample = data[:8000]
    if b"\0" in sample or (sample and sum(1 for byte in sample if byte < 9 and byte not in (9, 10, 13)) / len(sample) > 0.3):
        return {
            "path": rel,
            "kind": "binary",
            "size": size,
            "content": None,
            "placeholder": "binary file",
        }
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "path": rel,
            "kind": "encoding",
            "size": len(data),
            "content": None,
            "placeholder": "unsupported encoding",
        }
    return {
        "path": rel,
        "kind": "text",
        "size": len(data),
        "suffix": target.suffix.lower(),
        "content": text,
        "placeholder": None,
    }


def prepare_open_external(workspace: Path, raw: str, *, confirm: bool) -> dict[str, Any]:
    """Never launches an editor. Confirm is required; Desktop must act."""
    if not confirm:
        raise PathBoundaryError("USER_ACTION_REQUIRED", "explicit user confirm required")
    root = canonicalize(workspace)
    target = _inside(root, raw)
    if not target.exists() or not target.is_file():
        raise PathBoundaryError("PATH_NOT_FOUND", f"not a file: {target}")
    return {
        "ok": True,
        "path": str(target.relative_to(root)).replace("\\", "/"),
        "action": "open_external",
        "launched": False,
        "opened": False,
        "requires_user_action": True,
    }


def list_tree(workspace: Path, raw: str | None = None) -> list[dict[str, Any]]:
    root = canonicalize(workspace)
    base = root if not raw else _inside(root, raw)
    if not base.is_dir():
        raise PathBoundaryError("PATH_NOT_FOUND", f"not a directory: {base}")
    rows: list[dict[str, Any]] = []
    for item in sorted(base.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
        if item.name.startswith("."):
            continue
        rel = str(item.relative_to(root)).replace("\\", "/")
        rows.append({"path": rel, "name": item.name, "is_dir": item.is_dir()})
    return rows
