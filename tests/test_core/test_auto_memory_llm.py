"""
Tests for memory/auto_memory.py - LLM-based fact extraction.

Stitched from mem0 extraction prompt + update/delete decision flow.

Verifies:
1. extract_facts_llm calls the LLM and parses JSON response
2. Falls back to regex extraction when LLM is None
3. Falls back to regex extraction when LLM raises an exception
4. store_facts_llm handles facts (append), updates (replace), deletes (remove)
5. 100-fact cap and deduplication are preserved
6. _parse_llm_response handles various JSON formats (raw, fenced, embedded)
"""
import asyncio
import json

import pytest


class TestExtractFactsLLM:
    def _make(self, tmp_path, monkeypatch, session_id=None):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.auto_memory import AutoMemory
        return AutoMemory(session_id=session_id)

    def _make_mock_llm(self, response_text: str):
        """Create a mock LLM that returns a fixed response."""
        class MockLLM:
            def __init__(self, response):
                self.response = response
                self.call_count = 0
                self.last_messages = None

            async def chat(self, messages):
                self.call_count += 1
                self.last_messages = messages
                return self.response

        return MockLLM(response_text)

    # ------------------------------------------------------------------
    # LLM extraction with valid JSON response
    # ------------------------------------------------------------------

    def test_extract_facts_llm_returns_facts(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        llm = self._make_mock_llm(json.dumps({
            "facts": ["User prefers Python", "Project uses FastAPI"],
            "updates": [],
            "deletes": [],
        }))
        messages = [{"role": "user", "content": "I use Python and FastAPI"}]
        facts = asyncio.run(am.extract_facts_llm(messages, llm))
        assert "User prefers Python" in facts
        assert "Project uses FastAPI" in facts

    def test_llm_is_called_with_extraction_prompt(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        llm = self._make_mock_llm(json.dumps({"facts": [], "updates": [], "deletes": []}))
        messages = [{"role": "user", "content": "hello"}]
        asyncio.run(am.extract_facts_llm(messages, llm))
        assert llm.call_count == 1
        assert llm.last_messages is not None
        # System message should contain the extraction prompt
        sys_msg = llm.last_messages[0]
        assert "Extract key facts" in sys_msg["content"]
        assert "facts" in sys_msg["content"]

    def test_extract_facts_llm_merges_with_regex(self, tmp_path, monkeypatch):
        """LLM facts and regex facts should both be returned."""
        am = self._make(tmp_path, monkeypatch)
        llm = self._make_mock_llm(json.dumps({
            "facts": ["LLM extracted fact"],
            "updates": [],
            "deletes": [],
        }))
        messages = [{"role": "user", "content": "my name is Alice"}]
        facts = asyncio.run(am.extract_facts_llm(messages, llm))
        assert "LLM extracted fact" in facts
        # Regex should also catch "Alice"
        assert any("Alice" in f for f in facts)

    # ------------------------------------------------------------------
    # Fallback tests
    # ------------------------------------------------------------------

    def test_fallback_to_regex_when_llm_none(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        messages = [{"role": "user", "content": "my name is Bob"}]
        facts = asyncio.run(am.extract_facts_llm(messages, None))
        # Should fall back to regex extraction
        assert any("Bob" in f for f in facts)

    def test_fallback_to_regex_on_llm_exception(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)

        class BrokenLLM:
            async def chat(self, messages):
                raise RuntimeError("LLM unavailable")

        messages = [{"role": "user", "content": "my name is Charlie"}]
        facts = asyncio.run(am.extract_facts_llm(messages, BrokenLLM()))
        assert any("Charlie" in f for f in facts)

    def test_empty_messages_returns_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        llm = self._make_mock_llm(json.dumps({"facts": [], "updates": [], "deletes": []}))
        facts = asyncio.run(am.extract_facts_llm([], llm))
        assert facts == []

    # ------------------------------------------------------------------
    # Sync LLM support
    # ------------------------------------------------------------------

    def test_sync_llm_supported(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)

        class SyncLLM:
            def chat(self, messages):
                return json.dumps({"facts": ["sync fact"], "updates": [], "deletes": []})

        messages = [{"role": "user", "content": "test"}]
        facts = asyncio.run(am.extract_facts_llm(messages, SyncLLM()))
        assert "sync fact" in facts

    def test_callable_llm_supported(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)

        def llm_callable(messages):
            return json.dumps({"facts": ["callable fact"], "updates": [], "deletes": []})

        messages = [{"role": "user", "content": "test"}]
        facts = asyncio.run(am.extract_facts_llm(messages, llm_callable))
        assert "callable fact" in facts


class TestParseLLMResponse:
    def _make(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.auto_memory import AutoMemory
        return AutoMemory(session_id="test-parse")

    def test_parse_clean_json(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        response = json.dumps({
            "facts": ["f1", "f2"],
            "updates": [{"old": "old_f", "new": "new_f"}],
            "deletes": ["outdated"],
        })
        facts, updates, deletes = am._parse_llm_response(response)
        assert facts == ["f1", "f2"]
        assert updates == [{"old": "old_f", "new": "new_f"}]
        assert deletes == ["outdated"]

    def test_parse_markdown_fenced_json(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        response = '```json\n{"facts": ["f1"], "updates": [], "deletes": []}\n```'
        facts, updates, deletes = am._parse_llm_response(response)
        assert facts == ["f1"]
        assert updates == []
        assert deletes == []

    def test_parse_json_embedded_in_text(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        response = 'Here are the facts:\n{"facts": ["embedded"], "updates": [], "deletes": []}\nDone.'
        facts, updates, deletes = am._parse_llm_response(response)
        assert facts == ["embedded"]

    def test_parse_invalid_json_returns_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts, updates, deletes = am._parse_llm_response("not json at all")
        assert facts == []
        assert updates == []
        assert deletes == []

    def test_parse_missing_fields_defaults_empty(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        response = json.dumps({"facts": ["only facts"]})
        facts, updates, deletes = am._parse_llm_response(response)
        assert facts == ["only facts"]
        assert updates == []
        assert deletes == []

    def test_parse_non_list_fields_handled(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        response = json.dumps({"facts": "not a list", "updates": "also not", "deletes": 42})
        facts, updates, deletes = am._parse_llm_response(response)
        assert facts == []
        assert updates == []
        assert deletes == []

    def test_parse_facts_converted_to_strings(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        response = json.dumps({"facts": [123, True, "text"]})
        facts, _, _ = am._parse_llm_response(response)
        assert all(isinstance(f, str) for f in facts)
        assert "123" in facts
        assert "True" in facts


class TestStoreFactsLLM:
    def _make(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.auto_memory import AutoMemory
        return AutoMemory(session_id="test-store")

    def test_store_new_facts(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts_llm(["new fact 1", "new fact 2"])
        loaded = am._load_facts()
        assert "new fact 1" in loaded
        assert "new fact 2" in loaded

    def test_store_facts_deduplicates(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts_llm(["dup", "dup", "unique"])
        loaded = am._load_facts()
        assert loaded.count("dup") == 1
        assert "unique" in loaded

    def test_update_replaces_existing_fact(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts(["old version of fact"])
        am.store_facts_llm(
            facts=[],
            updates=[{"old": "old version of fact", "new": "updated fact"}],
        )
        loaded = am._load_facts()
        assert "old version of fact" not in loaded
        assert "updated fact" in loaded

    def test_update_appends_new_when_old_not_found(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts_llm(
            facts=[],
            updates=[{"old": "nonexistent", "new": "brand new fact"}],
        )
        loaded = am._load_facts()
        assert "brand new fact" in loaded

    def test_delete_removes_existing_fact(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts(["keep this", "delete this"])
        am.store_facts_llm(facts=[], deletes=["delete this"])
        loaded = am._load_facts()
        assert "keep this" in loaded
        assert "delete this" not in loaded

    def test_combined_operations(self, tmp_path, monkeypatch):
        """Test add + update + delete in a single call."""
        am = self._make(tmp_path, monkeypatch)
        am.store_facts(["existing old", "to be deleted"])
        am.store_facts_llm(
            facts=["brand new"],
            updates=[{"old": "existing old", "new": "existing new"}],
            deletes=["to be deleted"],
        )
        loaded = am._load_facts()
        assert "brand new" in loaded
        assert "existing new" in loaded
        assert "existing old" not in loaded
        assert "to be deleted" not in loaded

    def test_100_fact_cap_preserved(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        facts = [f"fact {i}" for i in range(120)]
        am.store_facts_llm(facts)
        loaded = am._load_facts()
        assert len(loaded) <= 100
        assert "fact 119" in loaded
        assert "fact 0" not in loaded

    def test_empty_inputs_noop(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        am.store_facts_llm([], [], [])
        # Should not create a file (or create empty)
        assert not am._facts_file.exists() or am._load_facts() == []

    def test_none_updates_and_deletes_handled(self, tmp_path, monkeypatch):
        am = self._make(tmp_path, monkeypatch)
        # Should not raise
        am.store_facts_llm(["safe fact"], None, None)
        loaded = am._load_facts()
        assert "safe fact" in loaded
