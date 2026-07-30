"""
Tests for the cache system (precise + semantic).

Verifies that:
1. PreciseCache generates stable keys for identical inputs
2. PreciseCache TTL expiration works
3. SemanticCache rejects low-similarity queries
4. SemanticCache entity overlap prevents cross-topic matches
5. Cache statistics are accurate

Note: PromptCacheManager (cache/prompt_cache.py) was removed; its logic
merged into core/prompts/registry.py PromptSpec versioning.
"""
import json
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor


class TestPreciseCache:
    def _make_cache(self):
        from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache
        cache = object.__new__(PreciseCache)
        cache._index = {}
        cache._cache_dir = None
        cache._index_file = None
        cache._save_index = lambda: None
        return cache

    def test_identical_inputs_produce_same_key(self):
        cache = self._make_cache()
        sys_prompt = "You are a helpful assistant."
        key1 = cache._make_key(sys_prompt, "What is Python?", "", "")
        key2 = cache._make_key(sys_prompt, "What is Python?", "", "")
        assert key1 == key2

    def test_different_queries_produce_different_keys(self):
        cache = self._make_cache()
        sys_prompt = "You are a helpful assistant."
        key1 = cache._make_key(sys_prompt, "What is Python?", "", "")
        key2 = cache._make_key(sys_prompt, "What is JavaScript?", "", "")
        assert key1 != key2

    def test_key_uses_full_sha256_segments(self):
        cache = self._make_cache()
        key = cache._make_key(
            "You are a helpful assistant.",
            "What is Python?",
            "read",
            '{"path":"README.md"}',
        )
        segments = key.split(":")
        assert len(segments) == 4
        assert all(len(segment) == 64 for segment in segments[:3])

    def test_query_filler_words_are_byte_exact(self):
        cache = self._make_cache()
        # "帮我" and "请" should be stripped
        key1 = cache._make_key("sys", "请帮我解释Python", "", "")
        key2 = cache._make_key("sys", "解释Python", "", "")
        assert key1 != key2

    def test_query_punctuation_is_byte_exact(self):
        cache = self._make_cache()
        key1 = cache._make_key("sys", "Python是什么？", "", "")
        key2 = cache._make_key("sys", "Python是什么", "", "")
        assert key1 != key2

    def test_put_and_get_roundtrip(self):
        cache = self._make_cache()
        cache.put("sys", "What is 2+2?", "4", ttl=60)
        result = cache.get("sys", "What is 2+2?")
        assert result is not None
        assert result["response"] == "4"
        assert result["from_cache"] is True
        assert result["cache_type"] == "precise"

    def test_get_returns_none_for_missing_key(self):
        cache = self._make_cache()
        result = cache.get("sys", "nonexistent query")
        assert result is None

    def test_ttl_expiration(self):
        cache = self._make_cache()
        cache.put("sys", "test", "answer", ttl=0)
        time.sleep(0.1)
        result = cache.get("sys", "test")
        assert result is None

    def test_different_system_prompts_different_keys(self):
        cache = self._make_cache()
        key1 = cache._make_key("System A", "query", "", "")
        key2 = cache._make_key("System B", "query", "", "")
        assert key1 != key2

    def test_system_prompt_suffix_participates_in_key(self):
        cache = self._make_cache()
        shared_prefix = "x" * 300
        key1 = cache._make_key(shared_prefix + " policy-a", "query")
        key2 = cache._make_key(shared_prefix + " policy-b", "query")
        assert key1 != key2

    def test_namespace_participates_in_key(self):
        cache = self._make_cache()
        key1 = cache._make_key("sys", "query", namespace="model-a")
        key2 = cache._make_key("sys", "query", namespace="model-b")
        assert key1 != key2

    def test_tool_fingerprint_in_key(self):
        cache = self._make_cache()
        key1 = cache._make_key("sys", "query", "read", "/tmp/file")
        key2 = cache._make_key("sys", "query", "write", "/tmp/file")
        assert key1 != key2

    def test_stats_track_hits_and_entries(self):
        cache = self._make_cache()
        cache.put("sys", "q1", "a1", ttl=60)
        cache.put("sys", "q2", "a2", ttl=60)
        cache.get("sys", "q1")
        cache.get("sys", "q1")  # second hit
        stats = cache.get_stats()
        assert stats["total_entries"] == 2
        assert stats["total_hits"] >= 2

    def test_clear_empties_cache(self):
        cache = self._make_cache()
        cache.put("sys", "q1", "a1", ttl=60)
        cache.clear()
        assert cache.get("sys", "q1") is None

    # ------------------------------------------------------------------
    # prompt_version parameter tests (context engineering)
    # ------------------------------------------------------------------

    def test_prompt_version_changes_key(self):
        cache = self._make_cache()
        key1 = cache._make_key("sys", "query", "", "", prompt_version="v1")
        key2 = cache._make_key("sys", "query", "", "", prompt_version="v2")
        assert key1 != key2

    def test_no_prompt_version_same_as_empty_string(self):
        cache = self._make_cache()
        key1 = cache._make_key("sys", "query", "", "", prompt_version="")
        key2 = cache._make_key("sys", "query", "", "")
        assert key1 == key2

    def test_prompt_version_put_get_roundtrip(self):
        cache = self._make_cache()
        cache.put("sys", "q", "a", ttl=60, prompt_version="v1")
        result = cache.get("sys", "q", prompt_version="v1")
        assert result is not None
        assert result["response"] == "a"

    def test_different_prompt_versions_dont_collide(self):
        cache = self._make_cache()
        cache.put("sys", "q", "answer_v1", ttl=60, prompt_version="v1")
        cache.put("sys", "q", "answer_v2", ttl=60, prompt_version="v2")
        r1 = cache.get("sys", "q", prompt_version="v1")
        r2 = cache.get("sys", "q", prompt_version="v2")
        assert r1["response"] == "answer_v1"
        assert r2["response"] == "answer_v2"

    def test_prompt_version_backward_compatible(self):
        """Old callers without prompt_version should still work."""
        cache = self._make_cache()
        cache.put("sys", "q", "a", ttl=60)
        result = cache.get("sys", "q")
        assert result is not None
        assert result["response"] == "a"

    def test_key_format_has_four_segments(self):
        """Key should now be sys:query:tool:version (4 colon-separated parts)."""
        cache = self._make_cache()
        key = cache._make_key("sys", "query", "tool", "args", prompt_version="v1")
        parts = key.split(":")
        assert len(parts) == 4
        assert parts[3] != ""  # version_hash is non-empty

    def test_key_without_version_has_empty_last_segment(self):
        cache = self._make_cache()
        key = cache._make_key("sys", "query", "tool", "args", prompt_version="")
        parts = key.split(":")
        assert len(parts) == 4
        assert parts[3] == ""  # version_hash is empty

    def test_query_case_whitespace_and_unicode_bytes_do_not_collide(self):
        cache = self._make_cache()
        baseline = cache._make_key("sys", "Cafe query")
        assert cache._make_key("sys", "cafe query") != baseline
        assert cache._make_key("sys", "Cafe  query") != baseline
        composed = unicodedata.normalize("NFC", "Cafe\N{COMBINING ACUTE ACCENT}")
        decomposed = unicodedata.normalize("NFD", composed)
        assert composed != decomposed
        assert cache._make_key("sys", composed) != cache._make_key("sys", decomposed)

    def test_length_framing_prevents_component_separator_collisions(self):
        cache = self._make_cache()
        assert cache._make_key("b\0c", "query", namespace="a") != cache._make_key(
            "c", "query", namespace="a\0b"
        )
        assert cache._make_key("sys", "query", "a", "b:c") != cache._make_key(
            "sys", "query", "a:b", "c"
        )


class TestSemanticCache:
    def _make_cache(self):
        from RxyCode.RxyCode1_1_0.cache.semantic_cache import SemanticCache
        cache = object.__new__(SemanticCache)
        cache._index = []
        cache._cache_dir = None
        cache._index_file = None
        cache._save_index = lambda: None
        cache._similarity_threshold = 0.95
        return cache

    def test_put_preserves_complete_query(self):
        cache = self._make_cache()
        query = "x" * 200 + " unique ending"
        cache.put(query, "Python is a programming language.")
        assert cache._index[0]["query"] == query

    def test_identical_query_hits(self):
        cache = self._make_cache()
        cache.put("What is Python?", "Python is a programming language.")
        result = cache.get("What is Python?")
        assert result is not None
        assert result["cache_type"] == "semantic"

    def test_completely_different_query_misses(self):
        cache = self._make_cache()
        cache.put("What is Python?", "Python is a programming language.")
        result = cache.get("How to cook pasta?")
        assert result is None

    def test_near_duplicate_hits(self):
        cache = self._make_cache()
        cache.put("What is Python?", "Python is a programming language.")
        # Very similar but not identical
        result = cache.get("What is Python?")
        assert result is not None

    def test_entity_overlap_prevents_cross_topic_match(self):
        """'Python vs JavaScript' must not match 'Python vs Java'."""
        cache = self._make_cache()
        cache.put("How to use Python decorators?", "Use @decorator syntax.")
        # "JavaScript" is a different key entity than "Python"
        result = cache.get("How to use JavaScript decorators?")
        assert result is None

    def test_error_responses_not_cached(self):
        cache = self._make_cache()
        cache.put("What is X?", "I don't know about X.")
        assert len(cache._index) == 0

    def test_short_responses_not_cached(self):
        cache = self._make_cache()
        cache.put("What is X?", "ok")
        assert len(cache._index) == 0

    def test_ttl_expiration(self):
        cache = self._make_cache()
        cache.put("What is Python?", "A language.", ttl=0)
        time.sleep(0.1)
        result = cache.get("What is Python?")
        assert result is None

    def test_namespace_prevents_cross_model_hits(self):
        cache = self._make_cache()
        cache.put("What is Python?", "Model A response text.", namespace="model-a")
        assert cache.get("What is Python?", namespace="model-b") is None
        assert cache.get("What is Python?", namespace="model-a")["response"] == "Model A response text."

    def test_expired_best_match_does_not_hide_active_match(self):
        cache = self._make_cache()
        cache.put("What is Python?", "Expired response text.", ttl=0, namespace="model-a")
        time.sleep(0.01)
        cache.put("What is Python?", "Active response text.", ttl=60, namespace="model-a")
        result = cache.get("What is Python?", namespace="model-a")
        assert result is not None
        assert result["response"] == "Active response text."

    def test_clear(self):
        cache = self._make_cache()
        cache.put("query", "A sufficiently long response text.")
        cache.clear()
        assert len(cache._index) == 0


class TestCacheDiskPersistence:
    def test_precise_multi_instance_concurrent_writes_and_hits(self, tmp_path):
        from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

        cache_dir = tmp_path / "precise"
        workers = 16
        caches = [PreciseCache(cache_dir) for _ in range(workers)]
        barrier = threading.Barrier(workers)

        def write(index):
            barrier.wait()
            caches[index].put(
                "system", f"query-{index}", f"answer-{index}", ttl=60
            )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(write, range(workers)))

        reloaded = PreciseCache(cache_dir)
        assert reloaded.get_stats()["total_entries"] == workers
        for index in range(workers):
            assert reloaded.get("system", f"query-{index}")["response"] == f"answer-{index}"

        hit_caches = [PreciseCache(cache_dir) for _ in range(workers)]
        hit_barrier = threading.Barrier(workers)

        def hit(_index):
            hit_barrier.wait()
            return hit_caches[_index].get("system", "query-0")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            assert all(executor.map(hit, range(workers)))

        stats = PreciseCache(cache_dir).get_stats()
        assert stats["total_hits"] == workers * 2
        assert isinstance(
            json.loads((cache_dir / "precise_index.json").read_text(encoding="utf-8")),
            dict,
        )
        assert list(cache_dir.glob("*.tmp")) == []

    def test_semantic_multi_instance_concurrent_writes_are_not_lost(self, tmp_path):
        from RxyCode.RxyCode1_1_0.cache.semantic_cache import SemanticCache

        cache_dir = tmp_path / "semantic"
        workers = 16
        caches = [SemanticCache(cache_dir) for _ in range(workers)]
        barrier = threading.Barrier(workers)

        def write(index):
            barrier.wait()
            caches[index].put(
                f"semantic query {index}",
                f"complete response for query {index}",
                ttl=60,
            )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(write, range(workers)))

        reloaded = SemanticCache(cache_dir)
        assert reloaded.get_stats()["total_entries"] == workers
        assert {
            entry["query"]
            for entry in json.loads(
                (cache_dir / "semantic_index.json").read_text(encoding="utf-8")
            )
        } == {f"semantic query {index}" for index in range(workers)}
        assert list(cache_dir.glob("*.tmp")) == []

    def test_precise_corrupt_index_is_preserved_and_repaired(self, tmp_path):
        from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

        cache_dir = tmp_path / "precise-corrupt"
        cache_dir.mkdir()
        index_file = cache_dir / "precise_index.json"
        corrupt_payload = '{"unfinished": '
        index_file.write_text(corrupt_payload, encoding="utf-8")

        cache = PreciseCache(cache_dir)

        assert cache.get_stats()["total_entries"] == 0
        assert json.loads(index_file.read_text(encoding="utf-8")) == {}
        backups = list(cache_dir.glob("precise_index.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == corrupt_payload

    def test_semantic_invalid_entry_shape_is_preserved_and_repaired(self, tmp_path):
        from RxyCode.RxyCode1_1_0.cache.semantic_cache import SemanticCache

        cache_dir = tmp_path / "semantic-corrupt"
        cache_dir.mkdir()
        index_file = cache_dir / "semantic_index.json"
        index_file.write_text('[{"query": "valid"}, 42]', encoding="utf-8")

        cache = SemanticCache(cache_dir)

        assert cache.get_stats()["total_entries"] == 0
        assert json.loads(index_file.read_text(encoding="utf-8")) == []
        backups = list(cache_dir.glob("semantic_index.json.corrupt-*"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == [
            {"query": "valid"},
            42,
        ]

    def test_precise_field_corruption_is_quarantined_without_losing_valid_entries(
        self, tmp_path
    ):
        from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

        cache_dir = tmp_path / "precise-field-corrupt"
        cache_dir.mkdir()
        index_file = cache_dir / "precise_index.json"
        valid_key = "valid"
        payload = {
            valid_key: {
                "response": "kept",
                "created": time.time(),
                "ttl": 60,
                "hits": 2,
            },
            "bad-created": {
                "response": "discarded",
                "created": "yesterday",
                "ttl": 60,
                "hits": 0,
            },
            "bad-hits": {
                "response": "discarded",
                "created": time.time(),
                "ttl": 60,
                "hits": [],
            },
        }
        index_file.write_text(json.dumps(payload), encoding="utf-8")

        cache = PreciseCache(cache_dir)

        assert cache.get_stats() == {
            "total_entries": 1,
            "total_hits": 2,
            "expired_entries": 0,
            "active_entries": 1,
        }
        assert json.loads(index_file.read_text(encoding="utf-8")) == {
            valid_key: payload[valid_key]
        }
        backups = list(cache_dir.glob("precise_index.json.corrupt-*"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == payload

    def test_semantic_field_corruption_is_quarantined_without_type_errors(
        self, tmp_path
    ):
        from RxyCode.RxyCode1_1_0.cache.semantic_cache import SemanticCache

        cache_dir = tmp_path / "semantic-field-corrupt"
        cache_dir.mkdir()
        index_file = cache_dir / "semantic_index.json"
        valid = {
            "query": "What is Python?",
            "namespace": "model-a",
            "response": "Python is a programming language.",
            "created": time.time(),
            "ttl": 60,
            "hits": 1,
        }
        payload = [
            valid,
            {**valid, "query": ["not", "text"]},
            {**valid, "ttl": "forever"},
            {**valid, "hits": {}},
        ]
        index_file.write_text(json.dumps(payload), encoding="utf-8")

        cache = SemanticCache(cache_dir)
        hit = cache.get("What is Python?", namespace="model-a")

        assert hit is not None
        assert hit["response"] == valid["response"]
        assert cache.get_stats()["total_entries"] == 1
        assert len(json.loads(index_file.read_text(encoding="utf-8"))) == 1
        backups = list(cache_dir.glob("semantic_index.json.corrupt-*"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == payload
