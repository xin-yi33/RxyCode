"""User-managed memory - add/remove/list persistent memories."""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir


def _user_dir() -> Path:
    d = get_data_dir() / "memory" / "user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _user_dir() / "index.json"


def _load_index() -> list[dict]:
    p = _index_path()
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(entries: list[dict]):
    with open(_index_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _next_id(entries: list[dict]) -> int:
    if not entries:
        return 1
    return max(e.get("id", 0) for e in entries) + 1


class UserMemory:
    def __init__(self):
        self._dir = _user_dir()

    def add(self, text: str) -> dict:
        entries = _load_index()
        entry = {
            "id": _next_id(entries),
            "text": text.strip(),
            "created": datetime.now().isoformat(),
        }
        entries.append(entry)
        _save_index(entries)
        self._write_file(entry)
        return entry

    def remove(self, entry_id: int) -> bool:
        entries = _load_index()
        new_entries = [e for e in entries if e.get("id") != entry_id]
        if len(new_entries) == len(entries):
            return False
        _save_index(new_entries)
        fp = self._dir / f"{entry_id}.md"
        if fp.exists():
            fp.unlink()
        return True

    def list_all(self) -> list[dict]:
        return _load_index()

    def get(self, entry_id: int) -> Optional[dict]:
        for e in _load_index():
            if e.get("id") == entry_id:
                return e
        return None

    def _write_file(self, entry: dict):
        fp = self._dir / f"{entry['id']}.md"
        content = f"# Memory #{entry['id']}\n\n{entry['text']}\n\n_Created: {entry['created']}_\n"
        fp.write_text(content, encoding="utf-8")

    def get_all_text(self) -> str:
        entries = _load_index()
        if not entries:
            return ""
        parts = []
        for e in entries:
            parts.append(f"[{e['id']}] {e['text']}")
        return "\n".join(parts)
    def clear(self):
        """Clear all user memories."""
        entries = _load_index()
        for e in entries:
            fp = self._dir / f"{e['id']}.md"
            if fp.exists():
                fp.unlink()
        _save_index([])

