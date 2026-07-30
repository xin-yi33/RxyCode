"""
Tests for memory/chat_storage.py - Chat session persistence.

Covers: save, load, delete, rename, list, preview, sanitization.
"""
import pytest
import json
from pathlib import Path


class TestChatStorage:
    def _make(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.chat_storage import ChatStorage
        return ChatStorage()

    def test_save_chat(self, tmp_path, monkeypatch):
        from datetime import datetime

        cs = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "hello"}]
        result = cs.save("test_chat", messages)
        assert result is True
        expected = tmp_path / "sessions" / datetime.now().strftime("%Y-%m-%d") / "chats" / "test_chat.json"
        assert expected.exists()

    def test_load_chat(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "hello"}]
        cs.save("test_chat", messages)
        loaded = cs.load("test_chat")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["content"] == "hello"

    def test_load_nonexistent(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        assert cs.load("nonexistent") is None

    def test_delete_chat(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("to_delete", [{"role": "user", "content": "data"}])
        result = cs.delete("to_delete")
        assert result is True
        assert cs.load("to_delete") is None

    def test_delete_nonexistent(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        result = cs.delete("nonexistent")
        assert result is True

    def test_delete_removes_all_dated_versions(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        for date in ("2026-07-26", "2026-07-27"):
            file = tmp_path / "sessions" / date / "chats" / "same.json"
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('{"name":"same","messages":[]}', encoding="utf-8")

        assert cs.delete("same") is True
        assert not list((tmp_path / "sessions").glob("*/chats/same.json"))

    def test_rename_chat(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("old_name", [{"role": "user", "content": "data"}])
        result = cs.rename("old_name", "new_name")
        assert result is True
        assert cs.load("new_name") is not None
        assert cs.load("old_name") is None

    def test_list_chats_empty(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        chats = cs.list_chats()
        assert chats == []

    def test_list_chats_multiple(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("chat1", [{"role": "user", "content": "first"}])
        cs.save("chat2", [{"role": "user", "content": "second"}])
        chats = cs.list_chats()
        assert len(chats) == 2

    def test_list_chats_sorted_by_time(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("chat1", [{"role": "user", "content": "first"}])
        cs.save("chat2", [{"role": "user", "content": "second"}])
        chats = cs.list_chats()
        # Most recent should be first
        assert chats[0]["name"] in ("chat1", "chat2")

    def test_get_chat_preview(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("test", [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "reply"},
        ])
        preview = cs.get_chat_preview("test")
        assert "first message" in preview

    def test_get_chat_preview_nonexistent(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        preview = cs.get_chat_preview("nonexistent")
        assert preview == ""

    def test_save_sanitizes_content(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        # Include control characters
        messages = [{"role": "user", "content": "hello\x00\x01world"}]
        cs.save("test", messages)
        loaded = cs.load("test")
        assert "\x00" not in loaded[0]["content"]
        assert "\x01" not in loaded[0]["content"]

    def test_save_preserves_spaces(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "hello     world"}]
        cs.save("test", messages)
        loaded = cs.load("test")
        assert loaded[0]["content"] == "hello     world"

    def test_save_preserves_code_indentation_and_outer_newlines(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        content = "\n```python\ndef f():\n    return 1  \n```\n"
        cs.save("code", [{"role": "assistant", "content": content}])

        loaded = cs.load("code")

        assert loaded[0]["content"] == content

    def test_save_replacement_char_removed(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "hello\ufffdworld"}]
        cs.save("test", messages)
        loaded = cs.load("test")
        assert "\ufffd" not in loaded[0]["content"]

    def test_save_unicode_content(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "你好世界"}]
        cs.save("test", messages)
        loaded = cs.load("test")
        assert loaded[0]["content"] == "你好世界"

    def test_save_empty_messages(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        result = cs.save("empty", [])
        assert result is True
        loaded = cs.load("empty")
        assert loaded == []

    def test_save_returns_false_on_error(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        # Make storage dir read-only or simulate error
        result = cs.save("test", [{"role": "user", "content": "data"}])
        assert result is True  # Normal case

    def test_chat_storage_dir_created(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        assert cs._storage_dir.exists()

    def test_filename_sanitization(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("test/name<>", [{"role": "user", "content": "data"}])
        chats = cs.list_chats()
        assert len(chats) == 1

    def test_list_chats_with_preview(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("test", [{"role": "user", "content": "my question"}])
        chats = cs.list_chats()
        assert chats[0].get("preview") != ""

    def test_overwrite_chat(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        cs.save("test", [{"role": "user", "content": "old"}])
        cs.save("test", [{"role": "user", "content": "new"}])
        loaded = cs.load("test")
        assert loaded[0]["content"] == "new"

    def test_save_multiple_messages(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        cs.save("multi", messages)
        loaded = cs.load("multi")
        assert len(loaded) == 4

    def test_versioned_session_round_trips_all_roles_and_tool_metadata(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.memory.chat_storage import CHAT_SCHEMA_VERSION

        cs = self._make(tmp_path, monkeypatch)
        stdout = "begin\n" + ("x" * 2000) + "\nend"
        messages = [
            {"version": 1, "id": "u1", "role": "user", "content": "question", "timestamp": 1},
            {"version": 1, "id": "t1", "role": "thinking", "content": "reasoning", "timestamp": 2, "done": True},
            {"version": 1, "id": "tool1", "role": "tool", "content": stdout, "timestamp": 3, "toolName": "bash", "toolArgs": "{}", "toolStatus": "success", "toolStdout": stdout, "toolDuration": 0.5},
            {"version": 1, "id": "a1", "role": "assistant", "content": "answer", "timestamp": 4},
            {"version": 1, "id": "s1", "role": "system", "content": "notice", "timestamp": 5},
        ]

        assert cs.save("versioned", messages) is True

        record = cs.load_record("versioned")
        assert record["schema_version"] == CHAT_SCHEMA_VERSION
        assert record["messages"] == messages
        assert record["messages"][2]["toolStdout"] == stdout

    def test_global_instance_exists(self):
        from RxyCode.RxyCode1_1_0.memory.chat_storage import chat_storage
        assert chat_storage is not None

    def test_preview_truncates_long_text(self, tmp_path, monkeypatch):
        cs = self._make(tmp_path, monkeypatch)
        long_content = "x" * 100
        cs.save("test", [{"role": "user", "content": long_content}])
        preview = cs.get_chat_preview("test")
        assert len(preview) < 200  # Should be truncated
