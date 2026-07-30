"""
Tests for the RAG (codebase vector search) package.

Covers: chunker, vector store, repo map generation.
No real embedding API is used – all embeddings are mocked.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest


# ─── Test fixtures ──────────────────────────────────────────────

SAMPLE_PY = '''\
"""Module docstring."""
import os
from pathlib import Path


def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"


class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        return a + b

    def multiply(self, a: int, b: int) -> int:
        return a * b


async def async_task():
    """An async function."""
    pass
'''

SAMPLE_JS = '''\
const fs = require("fs");

function readFile(path) {
    return fs.readFileSync(path, "utf-8");
}

class Logger {
    constructor() {
        this.entries = [];
    }
    log(msg) {
        this.entries.push(msg);
    }
}

module.exports = { readFile, Logger };
'''


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a small sample project with Python and JS files."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text(SAMPLE_PY, encoding="utf-8")
    (project / "src" / "util.js").write_text(SAMPLE_JS, encoding="utf-8")
    (project / "src" / "data.json").write_text(
        '{"key": "value"}', encoding="utf-8"
    )
    (project / ".gitignore").write_text(
        "node_modules/\n*.pyc\n__pycache__/\n", encoding="utf-8"
    )
    return project


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch):
    """Isolate the RAG data directory to a tmp_path."""
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    return tmp_path


# ─── Chunker tests ──────────────────────────────────────────────

class TestChunker:

    def test_chunk_python_file(self, sample_project: Path):
        """Test that Python files are chunked by AST (functions/classes)."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file, CodeChunk

        chunks = chunk_file(sample_project / "src" / "main.py")
        assert len(chunks) > 0
        assert all(isinstance(c, CodeChunk) for c in chunks)

        # Should find top-level symbols: greet, Calculator, async_task
        # (methods inside Calculator are part of the class chunk)
        symbol_names = {c.symbol_name for c in chunks}
        assert "greet" in symbol_names
        assert "Calculator" in symbol_names
        assert "async_task" in symbol_names

    def test_chunk_python_metadata(self, sample_project: Path):
        """Test that Python chunks have correct path/symbol/line metadata."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file

        chunks = chunk_file(sample_project / "src" / "main.py")
        for c in chunks:
            assert c.path.endswith("main.py")
            assert c.language == "python"
            assert c.start_line > 0
            assert c.end_line >= c.start_line
            assert len(c.content) > 0
            assert len(c.hash) == 16

    def test_chunk_non_python_window(self, sample_project: Path):
        """Test that non-Python files use sliding window."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file

        chunks = chunk_file(sample_project / "src" / "util.js")
        assert len(chunks) > 0
        assert all(c.language == "javascript" for c in chunks)
        # Window chunks have symbol_name like "chunk_0"
        assert all(c.symbol_name.startswith("chunk_") for c in chunks)

    def test_chunk_skips_binary(self, tmp_path: Path):
        """Test that binary files are skipped."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file

        binary_file = tmp_path / "test.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
        chunks = chunk_file(binary_file)
        assert chunks == []

    def test_chunk_skips_large_file(self, tmp_path: Path):
        """Test that files >1MB are skipped."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file, MAX_FILE_SIZE

        large_file = tmp_path / "big.py"
        large_file.write_text("x = 1\n" * (MAX_FILE_SIZE // 4 + 100), encoding="utf-8")
        assert large_file.stat().st_size > MAX_FILE_SIZE
        chunks = chunk_file(large_file)
        assert chunks == []

    def test_chunk_directory_recursive(self, sample_project: Path):
        """Test recursive directory chunking."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_directory

        chunks = chunk_directory(sample_project)
        assert len(chunks) > 0
        # Should include both .py and .js files
        paths = {c.path for c in chunks}
        py_found = any("main.py" in p for p in paths)
        js_found = any("util.js" in p for p in paths)
        assert py_found
        assert js_found

    def test_chunk_directory_respects_gitignore(self, sample_project: Path):
        """Test that .gitignore patterns are respected."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_directory

        # Create a .pyc file that should be ignored
        (sample_project / "src" / "test.pyc").write_bytes(b"\x00\x00\x00pyc")
        chunks = chunk_directory(sample_project)
        paths = {c.path for c in chunks}
        assert not any("test.pyc" in p for p in paths)

    def test_chunk_content_hash_stable(self, sample_project: Path):
        """Test that hashing the same content produces the same hash."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file

        chunks1 = chunk_file(sample_project / "src" / "main.py")
        chunks2 = chunk_file(sample_project / "src" / "main.py")
        assert len(chunks1) == len(chunks2)
        for c1, c2 in zip(chunks1, chunks2):
            assert c1.hash == c2.hash

    def test_chunk_empty_file(self, tmp_path: Path):
        """Test that empty files produce no chunks."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file

        empty = tmp_path / "empty.py"
        empty.write_text("", encoding="utf-8")
        assert chunk_file(empty) == []

    def test_chunk_python_with_syntax_error(self, tmp_path: Path):
        """Test that syntax errors fall back to window chunking."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_file

        bad_py = tmp_path / "bad.py"
        bad_py.write_text("def broken(:\n    pass\n", encoding="utf-8")
        chunks = chunk_file(bad_py)
        # Should not raise, should still produce chunks
        assert len(chunks) > 0

    def test_codechunk_roundtrip(self):
        """Test CodeChunk to_dict / from_dict roundtrip."""
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk

        original = CodeChunk(
            path="/test/file.py",
            symbol_name="my_func",
            start_line=10,
            end_line=20,
            content="def my_func():\n    pass\n",
            language="python",
            mtime=1234567890.0,
            hash="abcdef0123456789",
        )
        d = original.to_dict()
        restored = CodeChunk.from_dict(d)
        assert restored.path == original.path
        assert restored.symbol_name == original.symbol_name
        assert restored.start_line == original.start_line
        assert restored.end_line == original.end_line
        assert restored.content == original.content
        assert restored.language == original.language
        assert restored.mtime == original.mtime
        assert restored.hash == original.hash


# ─── Vector store tests ─────────────────────────────────────────

class TestNumpyVectorStore:

    def test_add_and_search(self, isolated_data_dir: Path, tmp_path: Path):
        """Test that adding vectors and searching returns correct results."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk

        store = NumpyVectorStore(tmp_path / "test_project")

        # Create chunks
        chunks = [
            CodeChunk(
                path="a.py", symbol_name="func_a", start_line=1, end_line=5,
                content="def func_a():\n    return 42", language="python",
                mtime=1000.0, hash="aaaa1111",
            ),
            CodeChunk(
                path="b.py", symbol_name="func_b", start_line=1, end_line=5,
                content="def func_b():\n    return 'hello'", language="python",
                mtime=1000.0, hash="bbbb2222",
            ),
        ]

        # Create deterministic vectors
        vectors = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ], dtype=np.float32)

        store.add(chunks, vectors)
        assert store.size == 2

        # Search with a query similar to chunk 0
        query = np.array([0.9, 0.1, 0.0], dtype=np.float32)
        results = store.search(query, top_k=1)
        assert len(results) == 1
        assert results[0].chunk.symbol_name == "func_a"
        assert results[0].score > 0.5

    def test_search_empty_store(self, isolated_data_dir: Path, tmp_path: Path):
        """Test searching an empty store returns no results."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        store = NumpyVectorStore(tmp_path / "empty_project")
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        results = store.search(query, top_k=5)
        assert results == []

    def test_delete_files(self, isolated_data_dir: Path, tmp_path: Path):
        """Test that deleting files removes their chunks."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk

        store = NumpyVectorStore(tmp_path / "del_project")
        chunks = [
            CodeChunk(
                path="a.py", symbol_name="func_a", start_line=1, end_line=5,
                content="def func_a():\n    pass", language="python",
                mtime=1000.0, hash="aaaa1111",
            ),
            CodeChunk(
                path="b.py", symbol_name="func_b", start_line=1, end_line=5,
                content="def func_b():\n    pass", language="python",
                mtime=1000.0, hash="bbbb2222",
            ),
        ]
        vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        store.add(chunks, vectors)
        assert store.size == 2

        store.delete_files(["a.py"])
        assert store.size == 1
        assert store._chunks[0].path == "b.py"

    def test_incremental_update(self, isolated_data_dir: Path, tmp_path: Path):
        """Test that adding the same file replaces old chunks."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk

        store = NumpyVectorStore(tmp_path / "incr_project")

        chunks_v1 = [
            CodeChunk(
                path="a.py", symbol_name="func_a", start_line=1, end_line=5,
                content="def func_a():\n    pass", language="python",
                mtime=1000.0, hash="aaaa1111",
            ),
        ]
        vectors_v1 = np.array([[1.0, 0.0]], dtype=np.float32)
        store.add(chunks_v1, vectors_v1)
        assert store.size == 1

        # Update the same file with new content
        chunks_v2 = [
            CodeChunk(
                path="a.py", symbol_name="func_a_v2", start_line=1, end_line=10,
                content="def func_a_v2():\n    return 42", language="python",
                mtime=2000.0, hash="cccc3333",
            ),
        ]
        vectors_v2 = np.array([[0.5, 0.5]], dtype=np.float32)
        store.add(chunks_v2, vectors_v2)

        # Should still have 1 chunk (replaced, not appended)
        assert store.size == 1
        assert store._chunks[0].symbol_name == "func_a_v2"

    def test_persistence_roundtrip(self, isolated_data_dir: Path, tmp_path: Path):
        """Test that store data survives a reload."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk

        project_path = tmp_path / "persist_project"

        store1 = NumpyVectorStore(project_path)
        chunks = [
            CodeChunk(
                path="a.py", symbol_name="func_a", start_line=1, end_line=5,
                content="def func_a():\n    pass", language="python",
                mtime=1000.0, hash="aaaa1111",
            ),
        ]
        vectors = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        store1.add(chunks, vectors)

        # Create a new store instance pointing to the same project
        store2 = NumpyVectorStore(project_path)
        assert store2.size == 1
        assert store2._chunks[0].symbol_name == "func_a"

    def test_needs_reindex(self, isolated_data_dir: Path, tmp_path: Path):
        """Test the needs_reindex logic."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk
        import hashlib

        store = NumpyVectorStore(tmp_path / "reindex_project")
        chunks = [
            CodeChunk(
                path="a.py", symbol_name="func_a", start_line=1, end_line=5,
                content="def func_a():\n    pass", language="python",
                mtime=1000.0, hash="aaaa1111",
            ),
        ]
        vectors = np.array([[1.0]], dtype=np.float32)
        store.add(chunks, vectors)

        # The file index stores a combined hash (sha256 of chunk hashes joined by |)
        combined = "|".join(c.hash for c in chunks)
        file_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]

        # Same mtime + hash -> no reindex needed
        assert not store.needs_reindex("a.py", 1000.0, file_hash)

        # Different mtime -> needs reindex
        assert store.needs_reindex("a.py", 2000.0, file_hash)

        # Different hash -> needs reindex
        assert store.needs_reindex("a.py", 1000.0, "bbbb2222")

        # New file -> needs reindex
        assert store.needs_reindex("b.py", 1000.0, "cccc3333")

    def test_get_indexed_files(self, isolated_data_dir: Path, tmp_path: Path):
        """Test get_indexed_files returns all indexed file paths."""
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk
        import hashlib

        store = NumpyVectorStore(tmp_path / "files_project")
        chunks = [
            CodeChunk(
                path="a.py", symbol_name="func_a", start_line=1, end_line=5,
                content="def func_a():\n    pass", language="python",
                mtime=1000.0, hash="aaaa1111",
            ),
            CodeChunk(
                path="b.py", symbol_name="func_b", start_line=1, end_line=5,
                content="def func_b():\n    pass", language="python",
                mtime=1000.0, hash="bbbb2222",
            ),
        ]
        vectors = np.array([[1.0], [0.0]], dtype=np.float32)
        store.add(chunks, vectors)

        files = store.get_indexed_files()
        assert "a.py" in files
        assert "b.py" in files
        # The file index stores a combined hash, not the individual chunk hash
        combined = "|".join(c.hash for c in [chunks[0]])
        expected_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
        assert files["a.py"]["hash"] == expected_hash


# ─── Repo map tests ──────────────────────────────────────────────

class TestRepoMap:

    def test_generate_repomap_basic(self, sample_project: Path):
        """Test that repomap generates a markdown string."""
        from RxyCode.RxyCode1_1_0.rag.search import generate_repomap

        result = generate_repomap(sample_project, max_tokens=2000)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should mention file paths
        assert "main.py" in result or "util.js" in result

    def test_generate_repomap_has_symbols(self, sample_project: Path):
        """Test that repomap includes symbol names."""
        from RxyCode.RxyCode1_1_0.rag.search import generate_repomap

        result = generate_repomap(sample_project, max_tokens=2000)
        # Should mention at least some function/class names
        symbols_found = any(
            name in result
            for name in ["greet", "Calculator", "add", "multiply", "readFile", "Logger"]
        )
        assert symbols_found, f"Expected symbols in repomap, got: {result}"

    def test_generate_repomap_token_budget(self, sample_project: Path):
        """Test that repomap respects token budget."""
        from RxyCode.RxyCode1_1_0.rag.search import generate_repomap

        # Very small budget
        result = generate_repomap(sample_project, max_tokens=50)
        assert isinstance(result, str)
        # Should have truncation indicator or be short
        # (with max_tokens=50, the output should be limited)
        assert len(result) < 500  # rough check

    def test_generate_repomap_empty_dir(self, tmp_path: Path):
        """Test repomap on an empty directory."""
        from RxyCode.RxyCode1_1_0.rag.search import generate_repomap

        result = generate_repomap(tmp_path, max_tokens=2000)
        assert isinstance(result, str)
        # Should not crash, may return "[no source files found]"
        assert len(result) > 0

    def test_generate_repomap_nonexistent(self, tmp_path: Path):
        """Test repomap on a non-existent directory."""
        from RxyCode.RxyCode1_1_0.rag.search import generate_repomap

        result = generate_repomap(tmp_path / "nonexistent", max_tokens=2000)
        assert "error" in result.lower()


# ─── Embedding (mocked) tests ────────────────────────────────────

class TestEmbedding:

    def test_embedding_available_uses_active_model_credentials(
        self, isolated_data_dir: Path, monkeypatch
    ):
        """Unset RAG credentials inherit the resolved active model credentials."""
        import RxyCode.RxyCode1_1_0.config.settings as settings_mod
        import RxyCode.RxyCode1_1_0.rag.embed as embed_mod

        monkeypatch.setattr(
            embed_mod,
            "_get_rag_config",
            lambda: {
                "enabled": True,
                "embedding": {"model": "text-embedding-test"},
            },
        )
        monkeypatch.setattr(
            settings_mod,
            "get_active_model_config",
            lambda: {
                "base_url": "https://models.example.test/v1",
                "api_key": "resolved-secret",
            },
        )

        assert embed_mod.is_embedding_available() is True

    def test_get_embeddings_empty_input(self, isolated_data_dir: Path):
        """Test that empty input returns empty array."""
        from RxyCode.RxyCode1_1_0.rag.embed import get_embeddings

        result = get_embeddings([])
        assert len(result) == 0

    def test_get_embeddings_no_config(self, isolated_data_dir: Path, monkeypatch):
        """Test graceful degradation when embedding is not configured."""
        from RxyCode.RxyCode1_1_0.rag.embed import get_embeddings

        # No embedding config → should return empty array
        result = get_embeddings(["test text"], config={"base_url": None, "api_key": None, "model": None})
        assert len(result) == 0

    def test_get_embeddings_with_mock(self, isolated_data_dir: Path):
        """Test embedding with mocked API call."""
        from RxyCode.RxyCode1_1_0.rag.embed import get_embeddings, _cache

        # Clear cache to ensure clean test
        _cache.clear()

        mock_vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_response = {
            "data": [
                {"embedding": mock_vectors[0], "index": 0},
                {"embedding": mock_vectors[1], "index": 1},
            ]
        }

        config = {
            "base_url": "https://api.test.com/v1",
            "api_key": "test-key",
            "model": "text-embedding-3-small",
        }

        with patch("RxyCode.RxyCode1_1_0.rag.embed.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response_obj
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = get_embeddings(["hello world", "foo bar"], config=config)
            assert result.shape == (2, 3)
            np.testing.assert_allclose(result[0], [0.1, 0.2, 0.3], atol=1e-6)
            np.testing.assert_allclose(result[1], [0.4, 0.5, 0.6], atol=1e-6)

        # Clean up
        _cache.clear()

    def test_embedding_cache_is_namespaced_by_model(
        self, isolated_data_dir: Path
    ):
        """Identical text is re-embedded after an embedding model switch."""
        import RxyCode.RxyCode1_1_0.rag.embed as embed_mod

        embed_mod._cache.clear()

        def fake_api(texts, _base_url, _api_key, model):
            dimension = 2 if model == "model-a" else 4
            return [[1.0] * dimension for _ in texts]

        base = {
            "base_url": "https://embeddings.example.test/v1",
            "api_key": "test-key",
        }
        with patch.object(
            embed_mod, "_call_embeddings_api", side_effect=fake_api
        ) as api_call:
            first = embed_mod.get_embeddings(
                ["same text"], config={**base, "model": "model-a"}
            )
            second = embed_mod.get_embeddings(
                ["same text"], config={**base, "model": "model-b"}
            )

        assert first.shape == (1, 2)
        assert second.shape == (1, 4)
        assert api_call.call_count == 2
        embed_mod._cache.clear()


# ─── Index tests ────────────────────────────────────────────────

class TestIndex:

    @staticmethod
    def _configure_fake_embeddings(monkeypatch, *, model_state, dimension_state, calls):
        import RxyCode.RxyCode1_1_0.rag.index as index_mod

        monkeypatch.setattr(index_mod, "is_embedding_available", lambda: True)
        monkeypatch.setattr(
            index_mod,
            "get_embedding_config",
            lambda: {
                "base_url": "https://embeddings.example.test/v1",
                "api_key": "not-persisted",
                "model": model_state["value"],
            },
        )

        def fake_get_embeddings(texts, *args, **kwargs):
            calls.append(list(texts))
            return np.ones((len(texts), dimension_state["value"]), dtype=np.float32)

        monkeypatch.setattr(index_mod, "get_embeddings", fake_get_embeddings)

    def test_index_manifest_rebuilds_when_embedding_model_changes(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """An unchanged source tree is fully re-embedded after a model change."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_directory
        from RxyCode.RxyCode1_1_0.rag.index import index_project
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        model_state = {"value": "embedding-model-a"}
        dimension_state = {"value": 3}
        calls = []
        self._configure_fake_embeddings(
            monkeypatch,
            model_state=model_state,
            dimension_state=dimension_state,
            calls=calls,
        )

        index_project(sample_project)
        calls.clear()
        model_state["value"] = "embedding-model-b"
        index_project(sample_project)

        store = NumpyVectorStore(sample_project)
        manifest = store.get_manifest()
        assert len(calls) == 1
        assert len(calls[0]) == len(chunk_directory(sample_project))
        assert manifest["embedding_mode"] == "real"
        assert manifest["embedding_model"] == "embedding-model-b"
        assert manifest["embedding_dimension"] == 3
        assert manifest["schema_version"] == 1
        assert manifest["chunker_version"]
        assert "api_key" not in manifest

    def test_index_manifest_rebuilds_when_embedding_dimension_changes(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """A provider dimension change cannot mix incompatible vectors."""
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_directory
        from RxyCode.RxyCode1_1_0.rag.index import index_project
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        model_state = {"value": "embedding-model-a"}
        dimension_state = {"value": 3}
        calls = []
        self._configure_fake_embeddings(
            monkeypatch,
            model_state=model_state,
            dimension_state=dimension_state,
            calls=calls,
        )
        index_project(sample_project)

        source = sample_project / "src" / "main.py"
        source.write_text(source.read_text(encoding="utf-8") + "\nnew_value = 1\n", encoding="utf-8")
        calls.clear()
        dimension_state["value"] = 5
        index_project(sample_project)

        store = NumpyVectorStore(sample_project)
        assert store.get_manifest()["embedding_dimension"] == 5
        assert store._vectors.shape == (len(chunk_directory(sample_project)), 5)
        assert len(calls) == 2  # changed file probe, then full rebuild
        assert len(calls[-1]) == len(chunk_directory(sample_project))

    def test_index_manifest_rebuilds_when_switching_from_pseudo_to_real(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """Pseudo-vectors are never retained in a real embedding index."""
        import RxyCode.RxyCode1_1_0.rag.index as index_mod
        from RxyCode.RxyCode1_1_0.rag.chunker import chunk_directory
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        available = {"value": False}
        monkeypatch.setattr(index_mod, "is_embedding_available", lambda: available["value"])
        index_mod.index_project(sample_project)

        calls = []
        available["value"] = True
        monkeypatch.setattr(
            index_mod,
            "get_embedding_config",
            lambda: {
                "base_url": "https://embeddings.example.test/v1",
                "api_key": "not-persisted",
                "model": "embedding-model-a",
            },
        )

        def fake_get_embeddings(texts, *args, **kwargs):
            calls.append(list(texts))
            return np.ones((len(texts), 7), dtype=np.float32)

        monkeypatch.setattr(index_mod, "get_embeddings", fake_get_embeddings)
        index_mod.index_project(sample_project)

        store = NumpyVectorStore(sample_project)
        assert len(calls) == 1
        assert len(calls[0]) == len(chunk_directory(sample_project))
        assert store.get_manifest()["embedding_mode"] == "real"
        assert store._vectors.shape[1] == 7

    def test_index_manifest_rebuilds_when_chunker_version_changes(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """Chunking contract changes invalidate every stored chunk."""
        import RxyCode.RxyCode1_1_0.rag.index as index_mod
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        monkeypatch.setattr(index_mod, "is_embedding_available", lambda: False)
        monkeypatch.setattr(index_mod, "CHUNKER_VERSION", "test-v1")
        index_mod.index_project(sample_project)

        store = NumpyVectorStore(sample_project)
        monkeypatch.setattr(index_mod, "CHUNKER_VERSION", "test-v2")
        with patch.object(store, "reset", wraps=store.reset) as reset:
            index_mod.index_project(sample_project, store=store)

        reset.assert_called_once()
        assert store.get_manifest()["chunker_version"] == "test-v2"

    def test_legacy_index_without_manifest_is_fully_rebuilt(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """Pre-manifest indexes migrate through reset, never blind reuse."""
        import RxyCode.RxyCode1_1_0.rag.index as index_mod
        from RxyCode.RxyCode1_1_0.rag.chunker import CodeChunk, chunk_directory
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        store = NumpyVectorStore(sample_project)
        legacy_chunk = CodeChunk(
            path="legacy.py",
            symbol_name="legacy",
            start_line=1,
            end_line=1,
            content="legacy = True",
            language="python",
            mtime=1.0,
            hash="legacy-hash",
        )
        store.add(
            [legacy_chunk],
            np.ones((1, 64), dtype=np.float32),
        )
        assert store.get_manifest() is None

        monkeypatch.setattr(index_mod, "is_embedding_available", lambda: False)
        with patch.object(store, "reset", wraps=store.reset) as reset:
            index_mod.index_project(sample_project, store=store)

        reset.assert_called_once()
        assert store.get_manifest()["schema_version"] == 1
        assert store.size == len(chunk_directory(sample_project))

    def test_index_project_returns_count(
        self, sample_project: Path, isolated_data_dir: Path
    ):
        """Test that index_project returns the number of indexed chunks."""
        from RxyCode.RxyCode1_1_0.rag.index import index_project

        count = index_project(sample_project)
        assert count > 0

    def test_index_project_creates_store(
        self, sample_project: Path, isolated_data_dir: Path
    ):
        """Test that index_project creates a vector store with chunks."""
        from RxyCode.RxyCode1_1_0.rag.index import index_project
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        index_project(sample_project)
        store = NumpyVectorStore(sample_project)
        assert store.size > 0

    def test_index_project_incremental(
        self, sample_project: Path, isolated_data_dir: Path
    ):
        """Test that re-indexing unchanged files is a no-op."""
        from RxyCode.RxyCode1_1_0.rag.index import index_project
        from RxyCode.RxyCode1_1_0.rag.store import NumpyVectorStore

        first_count = index_project(sample_project)
        store = NumpyVectorStore(sample_project)
        first_size = store.size

        # first_count is the number of chunks just indexed; first_size is total
        # in store. They should be equal on first index.
        assert first_count == first_size

        # Re-index without changes
        second_count = index_project(sample_project)
        store2 = NumpyVectorStore(sample_project)

        # Second run should not add new chunks (all unchanged)
        # second_count == store.size (returned early when nothing to index)
        assert second_count == first_size
        assert store2.size == first_size

    def test_code_search_fallback(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """Test code_search falls back to keyword search without embeddings."""
        # Change CWD to the sample project so _get_project_root() finds it
        monkeypatch.chdir(sample_project)

        # Reset module-level globals so they pick up the new CWD
        import RxyCode.RxyCode1_1_0.rag.index as index_mod
        index_mod._cwd_store = None
        index_mod._cwd_root = None

        from RxyCode.RxyCode1_1_0.rag.index import index_project
        from RxyCode.RxyCode1_1_0.rag.search import code_search

        # Index the project first
        index_project(sample_project)

        # Search should work even without real embeddings
        result = code_search("calculator", top_k=3)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_bounded_retrieval_is_offline_and_respects_budgets(
        self, sample_project: Path, isolated_data_dir: Path, monkeypatch
    ):
        """Planner retrieval has a hard result/character budget and no default API cost."""
        import RxyCode.RxyCode1_1_0.rag.search as search_mod

        monkeypatch.setattr(
            search_mod,
            "is_embedding_available",
            lambda: (_ for _ in ()).throw(AssertionError("network gate was consulted")),
        )
        monkeypatch.setattr(
            search_mod,
            "get_embeddings",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("embedding API was called")
            ),
        )

        result = search_mod.retrieve_context(
            "return calculator logger",
            root=sample_project,
            top_k=1,
            max_chars=180,
        )

        assert isinstance(result, str)
        assert len(result) <= 180
        assert "[1]" in result
        assert "[2]" not in result

    def test_bounded_retrieval_rejects_non_positive_budgets(
        self, sample_project: Path, isolated_data_dir: Path
    ):
        from RxyCode.RxyCode1_1_0.rag.search import retrieve_context

        with pytest.raises(ValueError, match="top_k"):
            retrieve_context("calculator", root=sample_project, top_k=0)
        with pytest.raises(ValueError, match="max_chars"):
            retrieve_context("calculator", root=sample_project, max_chars=0)
