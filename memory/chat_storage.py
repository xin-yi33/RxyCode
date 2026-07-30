"""Persistent chat storage for RxyCode - with text sanitization."""

import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional
from RxyCode.RxyCode1_1_0.config.settings import get_data_dir, get_dated_data_dir
from RxyCode.RxyCode1_1_0.utils.atomic_file import atomic_write_text


CHAT_SCHEMA_VERSION = 2
CHAT_MESSAGE_VERSION = 1
CHAT_ROLES = frozenset({"user", "assistant", "tool", "thinking", "system"})


def _sanitize_text(text: str) -> str:
    """Remove unsafe control bytes without changing user-visible formatting."""
    if not text:
        return ""
    # Remove control characters except newline/tab
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    # Remove replacement characters
    text = text.replace('\ufffd', '')
    return text


def _truncate_preview(text: str, max_len: int = 40) -> str:
    """Truncate text for preview, clean and safe."""
    text = " ".join(_sanitize_text(text).split())
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


class ChatStorage:
    """Manages saved chat sessions with text sanitization."""

    def __init__(self):
        self._sessions_root = get_data_dir() / "sessions"
        self._legacy_storage_dir = get_data_dir() / "chats"
        self._storage_dir = Path()
        self._refresh_storage_dir()

    def _refresh_storage_dir(self) -> None:
        current = get_dated_data_dir("sessions") / "chats"
        current.mkdir(parents=True, exist_ok=True)
        self._storage_dir = current

    @staticmethod
    def _safe_name(name: str) -> str:
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_ \u4e00-\u9fff").strip()
        return safe_name or "unnamed"

    def _get_file(self, name: str) -> Path:
        self._refresh_storage_dir()
        return self._storage_dir / f"{self._safe_name(name)}.json"

    def _find_file(self, name: str) -> Path:
        current = self._get_file(name)
        if current.exists():
            return current
        safe_name = self._safe_name(name)
        matches = sorted(
            self._sessions_root.glob(f"*/chats/{safe_name}.json"),
            key=lambda item: item.parent.parent.name,
            reverse=True,
        )
        if matches:
            return matches[0]
        return self._legacy_storage_dir / f"{safe_name}.json"

    def _chat_files(self) -> list[Path]:
        files = list(self._sessions_root.glob("*/chats/*.json"))
        files.extend(self._legacy_storage_dir.glob("*.json"))
        return files

    def save(self, name: str, messages: list[dict]) -> bool:
        """Save a versioned chat session without dropping message metadata."""
        try:
            clean_messages = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                clean_msg = deepcopy(msg)
                clean_msg["role"] = str(msg.get("role", ""))
                clean_msg["content"] = _sanitize_text(str(msg.get("content", "")))
                clean_messages.append(clean_msg)

            file = self._get_file(name)
            data = {
                "schema_version": CHAT_SCHEMA_VERSION,
                "name": _sanitize_text(name).strip(),
                "messages": clean_messages,
                "saved_at": datetime.now().isoformat(),
            }
            atomic_write_text(
                file,
                json.dumps(data, ensure_ascii=False, indent=2),
            )
            return True
        except Exception:
            return False

    def load(self, name: str) -> Optional[list[dict]]:
        """Load a chat session."""
        record = self.load_record(name)
        return None if record is None else record["messages"]

    def load_record(self, name: str) -> Optional[dict]:
        """Load the complete versioned envelope, including legacy sessions."""
        try:
            file = self._find_file(name)
            if not file.exists():
                return None
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
            messages = data.get("messages", [])
            if not isinstance(messages, list):
                return None
            return {
                "schema_version": int(data.get("schema_version", 1)),
                "name": data.get("name", name),
                "saved_at": data.get("saved_at"),
                "messages": messages,
            }
        except Exception:
            return None

    def delete(self, name: str) -> bool:
        """Delete a chat session from all dated and legacy locations."""
        try:
            safe_name = self._safe_name(name)
            files = list(self._sessions_root.glob(f"*/chats/{safe_name}.json"))
            files.append(self._legacy_storage_dir / f"{safe_name}.json")
            for file in files:
                file.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a chat session."""
        try:
            old_file = self._find_file(old_name)
            new_file = self._get_file(new_name)
            if old_file.exists():
                with open(old_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["name"] = _sanitize_text(new_name).strip()
                atomic_write_text(
                    new_file,
                    json.dumps(data, ensure_ascii=False, indent=2),
                )
                old_file.unlink()
            return True
        except Exception:
            return False

    def list_chats(self) -> list[dict]:
        """List all saved chats with clean previews."""
        chats_by_name: dict[str, dict] = {}
        for file in sorted(self._chat_files(), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = _sanitize_text(data.get("name", file.stem)).strip()
                if name in chats_by_name:
                    continue
                messages = data.get("messages", [])
                preview = ""
                for msg in messages:
                    if msg.get("role") == "user":
                        preview = _truncate_preview(msg.get("content", ""), 40)
                        break
                chats_by_name[name] = {
                    "name": name,
                    "preview": preview,
                    "time": file.stat().st_mtime,
                    "schema_version": int(data.get("schema_version", 1)),
                }
            except Exception:
                continue
        return sorted(chats_by_name.values(), key=lambda x: x.get("time", 0), reverse=True)

    def get_chat_preview(self, name: str) -> str:
        """Get a preview of what was discussed in a chat."""
        messages = self.load(name)
        if not messages:
            return ""

        preview_parts = []
        for msg in messages[:3]:
            role = msg.get("role", "unknown")
            content = _truncate_preview(msg.get("content", ""), 60)
            preview_parts.append(f"{role}: {content}")

        return " | ".join(preview_parts)


# Global instance
chat_storage = ChatStorage()

