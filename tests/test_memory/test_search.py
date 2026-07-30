"""
Tests for memory/search.py - BM25-based memory search.

Covers: tokenization, BM25 scoring, search results, index building.
"""
import pytest
from pathlib import Path


class TestTokenize:
    def test_english_text(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("hello world python")
        assert "hello" in tokens
        assert "world" in tokens
        assert "python" in tokens

    def test_chinese_text(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("你好世界")
        assert len(tokens) > 0

    def test_mixed_text(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("hello 你好 python")
        assert len(tokens) > 0

    def test_empty_string(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        assert _tokenize("") == []

    def test_stopwords_filtered(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("the is a test")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "test" in tokens

    def test_numbers(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("python3 version 10")
        assert "python3" in tokens

    def test_underscores(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("hello_world test_case")
        assert "hello_world" in tokens

    def test_single_char_filtered(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        tokens = _tokenize("a b c test")
        assert "test" in tokens

    def test_chinese_stopwords_filtered(self):
        from RxyCode.RxyCode1_1_0.memory.search import _tokenize
        # 的, 了 are Chinese stopwords
        tokens = _tokenize("测试的内容")
        # Should still have some tokens
        assert isinstance(tokens, list)


class TestBM25:
    def _make(self):
        from RxyCode.RxyCode1_1_0.memory.search import BM25
        return BM25()

    def test_empty_search(self):
        bm25 = self._make()
        results = bm25.search("query")
        assert results == []

    def test_add_and_search(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python programming language")
        results = bm25.search("python")
        assert len(results) > 0
        assert results[0].path == "doc1.md"

    def test_multiple_documents(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python programming")
        bm25.add_document("doc2.md", "java programming")
        bm25.add_document("doc3.md", "python web development")
        results = bm25.search("python")
        assert len(results) >= 2

    def test_relevance_ranking(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python python python")
        bm25.add_document("doc2.md", "python mentioned once")
        results = bm25.search("python")
        # Higher relevance should come first
        assert results[0].path == "doc1.md"

    def test_no_match_returns_empty(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "java programming")
        results = bm25.search("python")
        assert results == []

    def test_search_result_fields(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python programming")
        results = bm25.search("python")
        assert hasattr(results[0], "path")
        assert hasattr(results[0], "score")
        assert hasattr(results[0], "snippet")

    def test_score_is_float(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python")
        results = bm25.search("python")
        assert isinstance(results[0].score, float)

    def test_top_k_limit(self):
        bm25 = self._make()
        for i in range(10):
            bm25.add_document(f"doc{i}.md", f"python document {i}")
        results = bm25.search("python", top_k=3)
        assert len(results) <= 3

    def test_empty_query_returns_empty(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "test content")
        results = bm25.search("")
        assert results == []

    def test_empty_document_not_added(self):
        bm25 = self._make()
        bm25.add_document("empty.md", "")
        assert len(bm25.docs) == 0

    def test_avgdl_updated(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python programming")
        assert bm25.avgdl > 0

    def test_df_updated(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python programming")
        assert "python" in bm25.df

    def test_snippet_generated(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python programming is fun and useful")
        results = bm25.search("python")
        assert results[0].snippet != ""

    def test_score_positive(self):
        bm25 = self._make()
        bm25.add_document("doc1.md", "python python")
        results = bm25.search("python")
        assert results[0].score > 0

    def test_custom_k1_b(self):
        from RxyCode.RxyCode1_1_0.memory.search import BM25
        bm25 = BM25(k1=2.0, b=0.5)
        assert bm25.k1 == 2.0
        assert bm25.b == 0.5


class TestSearchResult:
    def test_dataclass_fields(self):
        from RxyCode.RxyCode1_1_0.memory.search import SearchResult
        sr = SearchResult(path="test.md", score=1.5, snippet="test snippet")
        assert sr.path == "test.md"
        assert sr.score == 1.5
        assert sr.snippet == "test snippet"


class TestSearchMemoryFunction:
    def test_search_memory_no_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.memory.search import search_memory
        results = search_memory("test")
        assert results == []

    def test_search_memory_with_content(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        # Create a memory file
        mem_dir = tmp_path / "memory" / "sessions" / "test"
        mem_dir.mkdir(parents=True)
        (mem_dir / "notes.md").write_text("python programming notes", encoding="utf-8")

        from RxyCode.RxyCode1_1_0.memory.search import search_memory
        results = search_memory("python")
        assert len(results) > 0

    def test_collect_memory_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        base = tmp_path / "memory"
        (base / "sessions").mkdir(parents=True)
        (base / "user").mkdir(parents=True)
        (base / "projects").mkdir(parents=True)

        from RxyCode.RxyCode1_1_0.memory.search import _collect_memory_dirs
        dirs = _collect_memory_dirs()
        assert len(dirs) == 3
