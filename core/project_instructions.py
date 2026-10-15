"""Read project instruction files that apply to one target path.

Discovery walks from the workspace root down to the target's ancestors.
It does not scan the whole tree. A nested AGENTS.md applies only inside
its directory. Symlinks that leave the workspace are ignored.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

_NAMES = ("AGENTS.md", "CLAUDE.md", ".cursorrules")


@dataclass(frozen=True)
class InstructionFile:
    path: str
    scope: str
    version: str
    text: str


@dataclass
class InstructionCache:
    """Remember instruction versions so an unchanged continuation is not re-read."""

    entries: dict[str, tuple[int, int, InstructionFile]] = field(default_factory=dict)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def bind_instruction_permissions(allowlist, files=()) -> tuple[str, ...]:
    """Instruction files describe the project. They never add tools or directories."""
    del files
    return tuple(allowlist)


def _cache_hit(
    cache: InstructionCache | None,
    key: str,
    path: Path,
) -> InstructionFile | None:
    if cache is None or key not in cache.entries:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    mtime, size, item = cache.entries[key]
    if stat.st_mtime_ns == mtime and stat.st_size == size:
        return item
    return None


def discover_instructions(
    workspace: Path,
    target: Path | None = None,
    cache: InstructionCache | None = None,
) -> tuple[InstructionFile, ...]:
    """Return instruction files from the workspace root through *target*."""
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        return ()
    cursor = (target or root).expanduser()
    if not cursor.is_absolute():
        cursor = root / cursor
    try:
        cursor = cursor.resolve()
    except OSError:
        return ()
    if not _inside(root, cursor):
        return ()
    if cursor.is_file():
        cursor = cursor.parent
    chain: list[Path] = []
    seen: set[Path] = set()
    current = cursor
    while True:
        if current in seen:
            break
        seen.add(current)
        if _inside(root, current):
            chain.append(current)
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    chain.reverse()
    found: list[InstructionFile] = []
    for directory in chain:
        for name in _NAMES:
            path = directory / name
            if path.is_symlink():
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if not _inside(root, resolved):
                    continue
            if not path.is_file():
                continue
            key = str(path.resolve()).replace("\\", "/")
            cached = _cache_hit(cache, key, path)
            if cached is not None:
                found.append(cached)
                continue
            try:
                text = path.read_text(encoding="utf-8")
                stat = path.stat()
            except OSError:
                continue
            version = hashlib.sha256(text.encode("utf-8")).hexdigest()
            item = InstructionFile(
                path=str(path.relative_to(root)).replace("\\", "/"),
                scope=str(directory.relative_to(root)).replace("\\", "/") or ".",
                version=version,
                text=text,
            )
            if cache is not None:
                cache.entries[key] = (stat.st_mtime_ns, stat.st_size, item)
            found.append(item)
    return tuple(found)
