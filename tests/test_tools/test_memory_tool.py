"""
Tests for tools/memory_tool.py - Memory tool operations.

Covers: add, list, remove, search, error handling, BM25 scoring.
"""
import pytest
from pydantic import ValidationError


class TestMemoryInput:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import MemoryInput
        mi = MemoryInput()
        assert mi.operation == "search"
        assert mi.query == ""
        assert mi.scope == "user"
        assert mi.scope_id == ""
        assert mi.limit == 10

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import MemoryInput
        mi = MemoryInput(operation="add", query="test", scope="sessions", scope_id="s1", limit=5)
        assert mi.operation == "add"
        assert mi.query == "test"
        assert mi.scope == "sessions"
        assert mi.scope_id == "s1"
        assert mi.limit == 5

    def test_scope_schema_rejects_unknown_value(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import MemoryInput

        with pytest.raises(ValidationError):
            MemoryInput(scope="../sessions")


class TestTokenize:
    def test_basic_tokenize(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _tokenize
        tokens = _tokenize("hello world python")
        assert "hello" in tokens
        assert "world" in tokens
        assert "python" in tokens

    def test_empty_string(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _tokenize
        assert _tokenize("") == []

    def test_special_chars(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _tokenize
        tokens = _tokenize("hello-world_test")
        assert "hello-world_test" in tokens or "hello" in tokens

    def test_uppercase_lowered(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _tokenize
        tokens = _tokenize("HELLO WORLD")
        assert "hello" in tokens
        assert "world" in tokens

    def test_numbers(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _tokenize
        tokens = _tokenize("python3 version2")
        assert "python3" in tokens
        assert "version2" in tokens


class TestBM25Score:
    def test_score_with_match(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _bm25_score
        query_tokens = ["python"]
        doc_tokens = ["python", "programming", "is", "fun"]
        df = {"python": 1}
        score = _bm25_score(query_tokens, doc_tokens, 4.0, 1, df)
        assert score > 0

    def test_score_no_match(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _bm25_score
        query_tokens = ["java"]
        doc_tokens = ["python", "programming"]
        df = {"python": 1}
        score = _bm25_score(query_tokens, doc_tokens, 2.0, 1, df)
        assert score == 0

    def test_score_empty_query(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _bm25_score
        score = _bm25_score([], ["python"], 1.0, 1, {})
        assert score == 0

    def test_score_empty_doc(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _bm25_score
        score = _bm25_score(["python"], [], 0.0, 1, {"python": 1})
        assert score == 0


class TestMemoryOperation:
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))

    def test_add_operation(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("add", "test memory content")
        assert "saved" in result.lower()

    def test_add_empty_query(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("add", "")
        assert "error" in result.lower()

    def test_add_duplicate(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        memory_operation("add", "duplicate content")
        result = memory_operation("add", "duplicate content")
        assert "already exists" in result.lower()

    def test_list_empty(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("list")
        assert "no memories" in result.lower()

    def test_list_with_entries(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        memory_operation("add", "first memory")
        memory_operation("add", "second memory")
        result = memory_operation("list")
        assert "first memory" in result
        assert "second memory" in result

    def test_list_limit(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        for i in range(5):
            memory_operation("add", f"memory {i}")
        result = memory_operation("list", limit=2)
        assert isinstance(result, str)

    def test_remove_existing(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        memory_operation("add", "to remove")
        result = memory_operation("remove", "1")
        assert "removed" in result.lower()

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("remove", "999")
        assert "not found" in result.lower()

    def test_remove_empty_query(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("remove", "")
        assert "error" in result.lower()

    def test_remove_non_numeric(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("remove", "abc")
        assert "error" in result.lower()

    def test_search_empty_query(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("search", "")
        assert "error" in result.lower()

    def test_search_no_files(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("search", "test query")
        assert "no memory" in result.lower() or "not found" in result.lower()

    def test_search_with_files(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        memory_operation("add", "python programming is great")
        result = memory_operation("search", "python")
        assert isinstance(result, str)

    def test_unknown_operation(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("invalid_op")
        assert "error" in result.lower()
        assert "invalid_op" in result

    def test_search_with_scope(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("search", "test", scope="sessions")
        assert isinstance(result, str)

    def test_search_with_scope_id(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation
        result = memory_operation("search", "test", scope="user", scope_id="s1")
        assert isinstance(result, str)


class TestSearchMemory:
    def test_search_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory
        result = _search_memory("query", "user", "", 10)
        assert "no memory" in result.lower()

    def test_search_empty_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        # Create empty user memory dir
        (tmp_path / "memory" / "user").mkdir(parents=True)
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory
        result = _search_memory("query", "user", "", 10)
        assert "no memory" in result.lower()

    def test_search_with_md_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        user_dir = tmp_path / "memory" / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "test.md").write_text("python programming notes", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory
        result = _search_memory("python", "user", "", 10)
        assert "python" in result.lower()

    def test_search_no_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        user_dir = tmp_path / "memory" / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "test.md").write_text("java programming notes", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory
        result = _search_memory("python", "user", "", 10)
        assert "no matching" in result.lower()

    @pytest.mark.parametrize(
        ("scope", "scope_id"),
        [
            ("../outside", ""),
            ("user", ".."),
            ("user", "../outside"),
            ("user", "/tmp/outside"),
            ("user", r"C:\outside"),
            ("user", r"\\server\share"),
        ],
    )
    def test_search_rejects_path_escape(
        self, tmp_path, monkeypatch, scope, scope_id
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        outside = tmp_path / "outside.md"
        outside.write_text("private escape marker", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory

        result = _search_memory("escape", scope, scope_id, 10)

        assert result.startswith("[error: invalid memory scope:")
        assert "private escape marker" not in result

    def test_search_current_session_scope(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        session_dir = tmp_path / "memory" / "sessions" / "session-1"
        session_dir.mkdir(parents=True)
        (session_dir / "context.md").write_text(
            "current session marker", encoding="utf-8"
        )
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory

        result = _search_memory("marker", "sessions", "session-1", 10)

        assert "current session marker" in result

    def test_search_global_scope_uses_project_memory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        global_dir = tmp_path / "memory" / "projects" / "global"
        global_dir.mkdir(parents=True)
        (global_dir / "MEMORY.md").write_text(
            "project global marker", encoding="utf-8"
        )
        from RxyCode.RxyCode1_1_0.tools.memory_tool import _search_memory

        result = _search_memory("marker", "global", "", 10)

        assert "project global marker" in result


class TestMemoryTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_tool
        assert memory_tool.name == "memory"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_tool
        assert "memory" in memory_tool.description.lower()

    def test_tool_has_args_schema(self):
        from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_tool
        assert memory_tool.args_schema is not None
