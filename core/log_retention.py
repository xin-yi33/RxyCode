"""Best-effort retention helpers for runtime JSONL observability data."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from pathlib import Path


_RETENTION_LOCK = threading.RLock()


def prune_run_files(
    directory: Path,
    *,
    keep_runs: int,
    protected: Iterable[Path] = (),
) -> None:
    """Keep the newest run JSONL files without deleting active paths."""
    if keep_runs <= 0 or not directory.exists() or not directory.is_dir():
        return
    protected_paths = {path.resolve() for path in protected}
    try:
        with _RETENTION_LOCK:
            candidates = [
                path
                for path in directory.glob("*.jsonl")
                if path.is_file() and path.resolve() not in protected_paths
            ]
            candidates.sort(
                key=lambda path: (path.stat().st_mtime_ns, path.name),
                reverse=True,
            )
            unprotected_to_keep = max(0, keep_runs - len(protected_paths))
            for stale in candidates[unprotected_to_keep:]:
                try:
                    stale.unlink()
                except OSError:
                    continue
    except OSError:
        return


def rotate_file(
    path: Path,
    *,
    incoming_bytes: int,
    max_bytes: int,
    backup_count: int,
) -> None:
    """Rotate ``path`` before an append that would exceed its size budget."""
    if max_bytes <= 0 or backup_count <= 0 or not path.exists():
        return
    try:
        if path.stat().st_size + max(0, incoming_bytes) <= max_bytes:
            return
        with _RETENTION_LOCK:
            oldest = path.with_name(f"{path.name}.{backup_count}")
            try:
                oldest.unlink(missing_ok=True)
            except OSError:
                pass
            for index in range(backup_count - 1, 0, -1):
                source = path.with_name(f"{path.name}.{index}")
                target = path.with_name(f"{path.name}.{index + 1}")
                if source.exists():
                    try:
                        os.replace(source, target)
                    except OSError:
                        continue
            os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        return


__all__ = ["prune_run_files", "rotate_file"]
