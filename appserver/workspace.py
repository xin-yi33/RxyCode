"""PhaseG-B4 path canonicalize and workspace boundary. Never os.chdir."""

from __future__ import annotations

import os
from pathlib import Path


class PathBoundaryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonicalize(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise PathBoundaryError("PATH_NOT_ACCESSIBLE", str(exc)) from exc
    return resolved


def assert_exists(path: Path) -> Path:
    if not path.exists():
        raise PathBoundaryError("PATH_NOT_FOUND", f"path does not exist: {path}")
    if not os.access(path, os.R_OK):
        raise PathBoundaryError("PATH_NOT_ACCESSIBLE", f"path not readable: {path}")
    return path


def assert_inside_workspace(workspace: Path, raw: str | Path) -> Path:
    root = canonicalize(workspace)
    target = canonicalize(raw)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PathBoundaryError(
            "PATH_OUTSIDE_WORKSPACE",
            f"{target} is outside workspace {root}",
        ) from exc
    if target.is_symlink():
        real = target.resolve()
        try:
            real.relative_to(root)
        except ValueError as exc:
            raise PathBoundaryError(
                "PATH_OUTSIDE_WORKSPACE",
                f"symlink {target} escapes workspace {root}",
            ) from exc
    return target


def git_status(workspace: Path) -> dict[str, object]:
    root = canonicalize(workspace)
    git_dir = root / ".git"
    if not git_dir.exists():
        return {
            "is_git": False,
            "branch": None,
            "worktree": None,
            "error_code": "NOT_A_GIT_REPO",
        }
    head = git_dir / "HEAD"
    branch = None
    if head.is_file():
        text = head.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("ref: refs/heads/"):
            branch = text.split("refs/heads/", 1)[1]
    return {
        "is_git": True,
        "branch": branch,
        "worktree": str(root),
        "error_code": None,
    }
