"""
Tests for memory/user_memory.py - User-managed persistent memories.

Covers: add, remove, list, get, clear, get_all_text.
"""
import pytest


class TestUserMemory:
    def _make(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.memory.user_memory import UserMemory
        return UserMemory()

    def test_add_memory(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("remember this")
        assert entry["id"] == 1
        assert entry["text"] == "remember this"

    def test_add_multiple_memories(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        um.add("first memory")
        um.add("second memory")
        entries = um.list_all()
        assert len(entries) == 2
        assert entries[0]["id"] == 1
        assert entries[1]["id"] == 2

    def test_add_strips_whitespace(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("  spaced text  ")
        assert entry["text"] == "spaced text"

    def test_remove_existing(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("to be removed")
        result = um.remove(entry["id"])
        assert result is True
        assert len(um.list_all()) == 0

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        result = um.remove(999)
        assert result is False

    def test_list_empty(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        assert um.list_all() == []

    def test_get_existing(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("find me")
        found = um.get(entry["id"])
        assert found is not None
        assert found["text"] == "find me"

    def test_get_nonexistent(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        assert um.get(999) is None

    def test_get_all_text_empty(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        assert um.get_all_text() == ""

    def test_get_all_text_with_entries(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        um.add("first")
        um.add("second")
        text = um.get_all_text()
        assert "first" in text
        assert "second" in text

    def test_clear(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        um.add("first")
        um.add("second")
        um.clear()
        assert len(um.list_all()) == 0

    def test_clear_empty(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        um.clear()
        assert len(um.list_all()) == 0

    def test_add_returns_entry_with_created(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("test")
        assert "created" in entry

    def test_id_increments(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        e1 = um.add("a")
        e2 = um.add("b")
        e3 = um.add("c")
        assert e1["id"] == 1
        assert e2["id"] == 2
        assert e3["id"] == 3

    def test_id_continues_after_remove(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        e1 = um.add("a")
        e2 = um.add("b")
        um.remove(e1["id"])
        e3 = um.add("c")
        assert e3["id"] == 3

    def test_file_written(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        um.add("file content")
        # Check that the .md file exists
        files = list(um._dir.glob("*.md"))
        assert len(files) == 1

    def test_index_file_written(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        um.add("indexed")
        index_file = um._dir / "index.json"
        assert index_file.exists()

    def test_unicode_text(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("你好世界")
        assert entry["text"] == "你好世界"
        loaded = um.get(entry["id"])
        assert loaded["text"] == "你好世界"

    def test_persistence_across_instances(self, tmp_path, monkeypatch):
        um1 = self._make(tmp_path, monkeypatch)
        um1.add("persisted memory")
        # Create new instance with same data dir
        from RxyCode.RxyCode1_1_0.memory.user_memory import UserMemory
        um2 = UserMemory()
        entries = um2.list_all()
        assert len(entries) == 1
        assert entries[0]["text"] == "persisted memory"

    def test_remove_deletes_file(self, tmp_path, monkeypatch):
        um = self._make(tmp_path, monkeypatch)
        entry = um.add("to be deleted")
        md_file = um._dir / f"{entry['id']}.md"
        assert md_file.exists()
        um.remove(entry["id"])
        assert not md_file.exists()
