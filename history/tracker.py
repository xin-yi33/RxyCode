import threading
"""File change tracker - records file modifications with diff generation."""

import os
import difflib
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChangeRecord:
    """Record of a file change."""
    file_path: str
    old_content: Optional[str]
    new_content: str
    timestamp: float
    tool: str = ""
    additions: int = 0
    removals: int = 0
    diff: str = ""


class FileTracker:
    """Tracks file changes within a session."""

    def __init__(self):
        self._snapshots: dict[str, str] = {}  # path -> content at read time
        self._changes: list[ChangeRecord] = []
        self._read_times: dict[str, float] = {}

    def record_read(self, file_path: str, content: str):
        """Record that a file was read."""
        abs_path = os.path.abspath(file_path)
        self._snapshots[abs_path] = content
        self._read_times[abs_path] = time.time()

    def record_write(self, file_path: str, new_content: str, tool: str = "write") -> ChangeRecord:
        """Record a file write and generate diff."""
        abs_path = os.path.abspath(file_path)
        old_content = self._snapshots.get(abs_path)

        if old_content is None and os.path.exists(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    old_content = f.read()
            except Exception:
                old_content = ""

        if old_content is None:
            old_content = ""

        diff_lines = list(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(file_path)}",
            tofile=f"b/{os.path.basename(file_path)}",
            n=3,
        ))
        diff_text = "".join(diff_lines)

        additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removals = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

        record = ChangeRecord(
            file_path=abs_path,
            old_content=old_content,
            new_content=new_content,
            timestamp=time.time(),
            tool=tool,
            additions=additions,
            removals=removals,
            diff=diff_text,
        )
        self._changes.append(record)
        self._snapshots[abs_path] = new_content
        return record

    def record_edit(self, file_path: str, old_string: str, new_string: str, tool: str = "edit") -> Optional[ChangeRecord]:
        """Record an edit operation."""
        abs_path = os.path.abspath(file_path)

        if abs_path not in self._snapshots and os.path.exists(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    self._snapshots[abs_path] = f.read()
            except Exception:
                return None

        old_content = self._snapshots.get(abs_path, "")
        if old_string not in old_content:
            return None

        new_content = old_content.replace(old_string, new_string, 1)
        return self.record_write(file_path, new_content, tool)

    def get_changes(self) -> list[ChangeRecord]:
        """Get all recorded changes."""
        return self._changes.copy()

    def get_changes_for_file(self, file_path: str) -> list[ChangeRecord]:
        """Get changes for a specific file."""
        abs_path = os.path.abspath(file_path)
        return [c for c in self._changes if c.file_path == abs_path]

    def get_diff_summary(self) -> str:
        """Get a summary of all changes."""
        if not self._changes:
            return "No changes recorded."

        total_add = sum(c.additions for c in self._changes)
        total_rem = sum(c.removals for c in self._changes)
        files_changed = len(set(c.file_path for c in self._changes))

        lines = [
            f"Changes: {files_changed} files, +{total_add} -{total_rem} lines",
            "",
        ]
        for c in self._changes:
            name = os.path.basename(c.file_path)
            lines.append(f"  {name}: +{c.additions} -{c.removals} ({c.tool})")

        return "\n".join(lines)

    def get_last_diff(self) -> str:
        """Get the diff from the last change."""
        if not self._changes:
            return ""
        return self._changes[-1].diff

    def clear(self):
        """Clear all tracked changes."""
        self._snapshots.clear()
        self._changes.clear()
        self._read_times.clear()


# Global singleton
_file_tracker = None
_file_tracker_lock = threading.Lock()

def get_file_tracker() -> FileTracker:
    global _file_tracker
    with _file_tracker_lock:
        if _file_tracker is None:
            _file_tracker = FileTracker()
        return _file_tracker
