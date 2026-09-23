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


def is_recent_data_dir(path: Path) -> bool:
    return path.name.lower() == ".rxycode"


def prepare_session_workspace(raw: str | Path) -> tuple[Path, bool]:
    """Canonicalize a session workspace.

    ``~/.RxyCode`` (the Recent inbox) is created on demand and must not be
    registered as a named project. Real project folders still have to exist.
    """
    path = canonicalize(raw)
    if is_recent_data_dir(path) or _is_scratch_workspace(path):
        path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.R_OK):
            raise PathBoundaryError("PATH_NOT_ACCESSIBLE", f"path not readable: {path}")
        return path, False
    return assert_exists(path), True


_PROJECT_MARKERS = (
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "composer.json",
    ".rxycode-project",
)

_HOME_DUMP_NAMES = frozenset(
    {
        "desktop",
        "documents",
        "downloads",
        "pictures",
        "videos",
        "music",
        "桌面",
        "文档",
        "下载",
        "图片",
        "视频",
        "音乐",
    }
)


def _is_scratch_workspace(path: Path) -> bool:
    return path.name.lower() == "workspace" and is_recent_data_dir(path.parent)


def default_scratch_workspace() -> Path:
    """No-project default: ``~/.RxyCode/workspace``."""
    try:
        from ..config.settings import get_data_dir
    except ImportError:
        from RxyCode.RxyCode1_1_0.config.settings import get_data_dir

    path = get_data_dir() / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return canonicalize(path)


def looks_like_project(path: Path) -> bool:
    root = canonicalize(path)
    if not root.is_dir():
        return False
    if any((root / marker).exists() for marker in _PROJECT_MARKERS):
        return True
    if (root / "index.html").is_file() and (
        (root / "js").is_dir() or (root / "css").is_dir() or (root / "src").is_dir()
    ):
        return True
    return False


def is_home_dump(path: Path) -> bool:
    """True for the user home folder or Desktop/Documents/Downloads dumps."""
    root = canonicalize(path)
    home = canonicalize(Path.home())
    if root == home:
        return True
    if root.name.lower() not in _HOME_DUMP_NAMES:
        return False
    try:
        root.relative_to(home)
    except ValueError:
        return False
    return True


def resolve_launch_workspace(cwd: str | Path | None = None) -> Path:
    """Pick the session workspace: project if cwd is one, else ``~/.RxyCode/workspace``.

    Launching from Desktop/home is not a project and must not dump generated
    files onto the Desktop.
    """
    current = canonicalize(cwd or Path.cwd())
    if looks_like_project(current) and not is_home_dump(current):
        return current
    for parent in current.parents:
        if is_home_dump(parent) or parent == canonicalize(Path.home()):
            break
        if looks_like_project(parent):
            return parent
    return default_scratch_workspace()


def is_inside(root: Path, target: Path) -> bool:
    """True when ``target`` is ``root`` or a descendant. Uses OS case rules.

    Rejects prefix siblings (``C:\\workspace2`` is not inside ``C:\\workspace``).
    """
    try:
        target.relative_to(root)
        return True
    except ValueError:
        pass
    if os.name != "nt":
        return False
    root_s = os.path.normcase(os.path.normpath(str(root))).rstrip("\\/")
    target_s = os.path.normcase(os.path.normpath(str(target)))
    return target_s == root_s or target_s.startswith(root_s + os.sep)


def assert_inside_workspace(workspace: Path, raw: str | Path) -> Path:
    root = canonicalize(workspace)
    target = canonicalize(raw)
    if not is_inside(root, target):
        raise PathBoundaryError(
            "PATH_OUTSIDE_WORKSPACE",
            f"{target} is outside workspace {root}",
        )
    if target.is_symlink():
        real = target.resolve()
        if not is_inside(root, real):
            raise PathBoundaryError(
                "PATH_OUTSIDE_WORKSPACE",
                f"symlink {target} escapes workspace {root}",
            )
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
