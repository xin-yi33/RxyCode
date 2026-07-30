"""
Tests for memory/long_term.py - Persistent long-term memory storage.

Covers: session context, history, global memory, error logging, session listing.
"""
import pytest
import json
from pathlib import Path


class TestLongTermMemory:
    def _make(self, tmp_path, monkeypatch, session_id=None):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.long_term import LongTermMemory
        return LongTermMemory(session_id=session_id)

    def test_default_session_id(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm.session_id == "latest"

    def test_custom_session_id(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch, session_id="test-session")
        assert ltm.session_id == "test-session"

    def test_save_session_context(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        ltm.save_session_context("test context")
        assert ltm.load_session_context() == "test context"

    def test_load_session_context_empty(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm.load_session_context() == ""

    def test_append_session_context(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        ltm.save_session_context("first part")
        ltm.append_session_context("second part")
        result = ltm.load_session_context()
        assert "first part" in result
        assert "second part" in result

    def test_save_history(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "hello"}]
        ltm.save_history(messages)
        loaded = ltm.load_history()
        assert len(loaded) == 1
        assert loaded[0]["content"] == "hello"

    def test_load_history_empty(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm.load_history() == []

    def test_save_global_memory(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        ltm.save_global_memory("global content")
        assert ltm.load_global_memory() == "global content"

    def test_load_global_memory_empty(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm.load_global_memory() == ""

    def test_append_error_log(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        ltm.append_error_log("task-1", "something went wrong")
        error_file = ltm._session_dir / "errors.log"
        assert error_file.exists()
        content = error_file.read_text(encoding="utf-8")
        assert "task-1" in content
        assert "something went wrong" in content

    def test_append_multiple_errors(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        ltm.append_error_log("task-1", "error 1")
        ltm.append_error_log("task-2", "error 2")
        error_file = ltm._session_dir / "errors.log"
        content = error_file.read_text(encoding="utf-8")
        assert "error 1" in content
        assert "error 2" in content

    def test_clear_session_removes_all_dated_versions(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch, session_id="same")
        for date in ("2026-07-26", "2026-07-27"):
            session_dir = tmp_path / "sessions" / date / "memory" / "same"
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "history.json").write_text("[]", encoding="utf-8")
            (session_dir / "auto_facts.md").write_text("- fact", encoding="utf-8")

        assert ltm.clear_session() == 4
        assert not list((tmp_path / "sessions").glob("*/memory/same/*"))

    def test_list_sessions_empty(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        sessions = ltm.list_sessions()
        # The "latest" session was just created
        assert "latest" in sessions

    def test_list_sessions_multiple(self, tmp_path, monkeypatch):
        ltm1 = self._make(tmp_path, monkeypatch, session_id="session1")
        ltm2 = self._make(tmp_path, monkeypatch, session_id="session2")
        ltm3 = self._make(tmp_path, monkeypatch)
        sessions = ltm3.list_sessions()
        assert "session1" in sessions
        assert "session2" in sessions
        assert "latest" in sessions

    def test_overwrite_session_context(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        ltm.save_session_context("first")
        ltm.save_session_context("second")
        assert ltm.load_session_context() == "second"

    def test_save_unicode_history(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "你好世界"}]
        ltm.save_history(messages)
        loaded = ltm.load_history()
        assert loaded[0]["content"] == "你好世界"

    def test_history_with_complex_structure(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        ltm.save_history(messages)
        loaded = ltm.load_history()
        assert len(loaded) == 4

    def test_session_dir_created(self, tmp_path, monkeypatch):
        from datetime import datetime

        ltm = self._make(tmp_path, monkeypatch, session_id="custom")
        expected = tmp_path / "sessions" / datetime.now().strftime("%Y-%m-%d") / "memory" / "custom"
        assert ltm._session_dir == expected
        assert ltm._session_dir.exists()

    def test_context_file_path(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm._context_file.name == "context.md"

    def test_history_file_path(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm._history_file.name == "history.json"

    def test_corrupt_history_returns_empty(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        # Write invalid JSON
        ltm._history_file.write_text("not valid json {{{", encoding="utf-8")
        assert ltm.load_history() == []

    def test_global_file_path(self, tmp_path, monkeypatch):
        ltm = self._make(tmp_path, monkeypatch)
        assert ltm._global_file.name == "MEMORY.md"
