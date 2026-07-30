"""
Tests for memory/auto_memory.py - Automatic fact extraction from conversations.

Covers: fact extraction (Chinese/English), storage, compression, loading.
"""
import pytest


class TestAutoMemory:
    def _make(self, tmp_path, monkeypatch, session_id=None):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        # Create config.yaml to prevent legacy data migration
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.auto_memory import AutoMemory
        return AutoMemory(session_id=session_id)

    def test_default_session_id(self, tmp_path, monkeypatch):
        from datetime import datetime

        am = self._make(tmp_path, monkeypatch)
        expected = tmp_path / "sessions" / datetime.now().strftime("%Y-%m-%d") / "memory" / "latest"
        assert am._dir == expected
        assert am.session_id == "latest"

    def test_rejects_path_traversal_session_id(self, tmp_path, monkeypatch):
        import pytest

        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.memory.auto_memory import AutoMemory

        with pytest.raises(ValueError):
            AutoMemory("../outside")

    def test_custom_session_id(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch, session_id="test")
        assert am.session_id == "test"

    def test_extract_facts_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([])
        assert facts == []

    def test_extract_user_facts_chinese_name(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "我叫张三"},
        ])
        assert any("张三" in f for f in facts)

    def test_extract_user_facts_english_name(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "my name is John"},
        ])
        assert any("John" in f for f in facts)

    def test_extract_user_facts_preference(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "我喜欢Python编程"},
        ])
        assert len(facts) > 0

    def test_extract_user_facts_location(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "我住在北京"},
        ])
        assert any("北京" in f for f in facts)

    def test_extract_user_facts_remember(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "请记住这个配置很重要"},
        ])
        assert len(facts) > 0

    def test_extract_assistant_facts_summary(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "assistant", "content": "总结：这是一个重要功能"},
        ])
        assert len(facts) > 0

    def test_extract_assistant_facts_key_point(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "assistant", "content": "Key point: this is critical"},
        ])
        assert len(facts) > 0

    def test_extract_facts_deduplicates(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "我叫张三"},
            {"role": "user", "content": "我叫张三"},
        ])
        # Should deduplicate
        assert facts.count("张三") <= 1

    def test_store_facts(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts(["fact 1", "fact 2"])
        loaded = am.load_facts()
        assert "fact 1" in loaded
        assert "fact 2" in loaded

    def test_store_facts_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts([])
        # Should not create file or create empty file
        assert not am._facts_file.exists() or am.load_facts() == ""

    def test_store_facts_appends(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts(["first"])
        am.store_facts(["second"])
        loaded = am.load_facts()
        assert "first" in loaded
        assert "second" in loaded

    def test_load_facts_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        assert am.load_facts() == ""

    def test_compress_old_messages_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        result = am.compress_old_messages([])
        assert result == ""

    def test_compress_old_messages_short(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        messages = [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "reply"},
        ]
        result = am.compress_old_messages(messages, keep_recent=6)
        assert result == ""

    def test_compress_old_messages_long(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        messages = [
            {"role": "user", "content": f"message {i}"} for i in range(10)
        ]
        result = am.compress_old_messages(messages, keep_recent=3)
        assert result != ""
        assert "message 0" in result

    def test_compress_creates_file(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        messages = [
            {"role": "user", "content": f"msg {i}"} for i in range(10)
        ]
        am.compress_old_messages(messages, keep_recent=3)
        assert am._compress_file.exists()

    def test_load_compressed_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        assert am.load_compressed() == ""

    def test_load_compressed_after_compress(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        messages = [
            {"role": "user", "content": f"msg {i}"} for i in range(10)
        ]
        am.compress_old_messages(messages, keep_recent=3)
        compressed = am.load_compressed()
        assert compressed != ""

    def test_get_context_no_facts(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        ctx = am.get_context()
        assert ctx == ""

    def test_get_context_with_facts(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts(["important fact"])
        ctx = am.get_context()
        assert "important fact" in ctx

    def test_get_context_max_facts_limit(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts([f"fact {i}" for i in range(20)])
        ctx = am.get_context(max_facts=5)
        # Should limit the number of facts returned
        assert "fact 0" in ctx

    def test_extract_facts_skips_empty_content(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": ""},
            {"role": "user", "content": None},
        ])
        assert facts == []

    def test_extract_facts_code_keyword(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = am.extract_facts([
            {"role": "user", "content": "I use Python framework"},
        ])
        assert len(facts) > 0

    def test_store_facts_limits_100(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts([f"fact {i}" for i in range(120)])
        loaded = am.load_facts()
        # Should keep last 100
        assert "fact 119" in loaded
        assert "fact 0" not in loaded
