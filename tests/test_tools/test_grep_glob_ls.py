"""
Tests for tools/grep_tool.py, glob_tool.py, ls.py, view.py.

Covers: pattern matching, directory traversal, file filtering, formatting.
"""
class TestGrepFiles:
    def _grep(self, pattern, path="", include=""):
        from RxyCode.RxyCode1_1_0.tools.grep_tool import grep_files
        return grep_files(pattern, path, include)

    def test_grep_finds_pattern_in_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")
        result = self._grep("hello", str(tmp_path))
        assert "hello" in result
        assert "def hello" in result

    def test_grep_no_matches(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("nothing here\n", encoding="utf-8")
        result = self._grep("xyz", str(tmp_path))
        assert "no matches" in result.lower()

    def test_grep_invalid_regex(self, tmp_path):
        result = self._grep("[invalid", str(tmp_path))
        assert "error" in result.lower()

    def test_grep_nonexistent_path(self):
        result = self._grep("test", "/nonexistent/path")
        assert "not found" in result.lower()

    def test_grep_in_specific_file(self, tmp_path):
        f = tmp_path / "target.txt"
        f.write_text("match this line\n", encoding="utf-8")
        result = self._grep("match", str(f))
        assert "match" in result

    def test_grep_with_include_filter(self, tmp_path):
        (tmp_path / "test.py").write_text("hello\n", encoding="utf-8")
        (tmp_path / "test.txt").write_text("hello\n", encoding="utf-8")
        result = self._grep("hello", str(tmp_path), include="*.py")
        assert ".py" in result
        assert ".txt" not in result

    def test_grep_multiple_matches(self, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_text("match\nmatch\nmatch\n", encoding="utf-8")
        result = self._grep("match", str(f))
        assert result.count("match") >= 3

    def test_grep_returns_file_and_line(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nmatch here\nline3\n", encoding="utf-8")
        result = self._grep("match", str(f))
        assert "2:" in result

    def test_grep_truncates_at_100_results(self, tmp_path):
        f = tmp_path / "many.txt"
        f.write_text("\n".join(["match"] * 150) + "\n", encoding="utf-8")
        result = self._grep("match", str(f))
        assert "truncated" in result.lower() or result.count("\n") <= 101

    def test_grep_regex_pattern(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("abc123def\nxyz\n456abc\n", encoding="utf-8")
        result = self._grep(r"\d+", str(f))
        assert "123" in result
        assert "456" in result

    def test_grep_case_sensitive(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello\nhello\nHELLO\n", encoding="utf-8")
        result = self._grep("Hello", str(f))
        lines = [line for line in result.split("\n") if line.strip()]
        assert len(lines) == 1

    def test_grep_empty_pattern(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("some text\n", encoding="utf-8")
        result = self._grep("", str(f))
        # Empty pattern matches everything
        assert isinstance(result, str)

    def test_grep_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.grep_tool import grep_tool
        assert grep_tool.name == "grep"

    def test_grep_recursive_search(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("found me\n", encoding="utf-8")
        result = self._grep("found", str(tmp_path))
        assert "found me" in result


class TestGlobFiles:
    def _glob(self, pattern, path=""):
        from RxyCode.RxyCode1_1_0.tools.glob_tool import glob_files
        return glob_files(pattern, path)

    def test_glob_finds_py_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.py").write_text("x", encoding="utf-8")
        (tmp_path / "c.txt").write_text("x", encoding="utf-8")
        result = self._glob("*.py", str(tmp_path))
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_glob_no_matches(self, tmp_path):
        result = self._glob("*.xyz", str(tmp_path))
        assert "no matches" in result.lower()

    def test_glob_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("x", encoding="utf-8")
        result = self._glob("**/*.py", str(tmp_path))
        assert "deep.py" in result

    def test_glob_sorted_results(self, tmp_path):
        (tmp_path / "c.py").write_text("x", encoding="utf-8")
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.py").write_text("x", encoding="utf-8")
        result = self._glob("*.py", str(tmp_path))
        lines = [line for line in result.split("\n") if line.strip()]
        assert lines == sorted(lines)

    def test_glob_default_path_uses_session_cwd(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )

        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
        (tmp_path / "test.py").write_text("x", encoding="utf-8")
        token = bind_session("glob-default")
        try:
            set_working_directory(tmp_path)
            result = self._glob("*.py")
        finally:
            reset_session_binding(token)
        assert "test.py" in result

    def test_glob_specific_file(self, tmp_path):
        (tmp_path / "target.py").write_text("x", encoding="utf-8")
        result = self._glob("target.py", str(tmp_path))
        assert "target.py" in result

    def test_glob_multiple_extensions(self, tmp_path):
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        result_py = self._glob("*.py", str(tmp_path))
        result_txt = self._glob("*.txt", str(tmp_path))
        assert "a.py" in result_py
        assert "a.txt" in result_txt

    def test_glob_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.glob_tool import glob_tool
        assert glob_tool.name == "glob"


class TestRunLs:
    def _ls(self, path=".", ignore=None):
        from RxyCode.RxyCode1_1_0.tools.ls import run_ls
        return run_ls(path, ignore or [])

    def test_ls_empty_directory(self, tmp_path):
        result = self._ls(str(tmp_path))
        assert "empty" in result.lower()

    def test_ls_with_files(self, tmp_path):
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        result = self._ls(str(tmp_path))
        assert "file.txt" in result

    def test_ls_with_directories(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        result = self._ls(str(tmp_path))
        assert "subdir/" in result

    def test_ls_nonexistent_path(self):
        result = self._ls("/nonexistent/path")
        assert "not found" in result.lower()

    def test_ls_file_path_returns_filename(self, tmp_path):
        f = tmp_path / "single.txt"
        f.write_text("x", encoding="utf-8")
        result = self._ls(str(f))
        assert result == str(f)

    def test_ls_with_ignore_pattern(self, tmp_path):
        (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
        (tmp_path / "kept.txt").write_text("x", encoding="utf-8")
        result = self._ls(str(tmp_path), ["ignored"])
        assert "kept.txt" in result
        assert "ignored.txt" not in result

    def test_ls_tree_structure(self, tmp_path):
        (tmp_path / "dir1").mkdir()
        (tmp_path / "dir1" / "file.py").write_text("x", encoding="utf-8")
        result = self._ls(str(tmp_path))
        assert "dir1" in result
        assert "file.py" in result

    def test_ls_shows_file_sizes(self, tmp_path):
        (tmp_path / "sized.txt").write_text("hello world", encoding="utf-8")
        result = self._ls(str(tmp_path))
        assert "B" in result or "KB" in result or "MB" in result


class TestFormatSize:
    def test_bytes(self):
        from RxyCode.RxyCode1_1_0.tools.ls import _format_size
        assert _format_size(0) == "0B"
        assert _format_size(512) == "512B"
        assert _format_size(1023) == "1023B"

    def test_kilobytes(self):
        from RxyCode.RxyCode1_1_0.tools.ls import _format_size
        assert _format_size(1024) == "1.0KB"
        assert _format_size(2048) == "2.0KB"
        assert _format_size(1536) == "1.5KB"

    def test_megabytes(self):
        from RxyCode.RxyCode1_1_0.tools.ls import _format_size
        assert _format_size(1048576) == "1.0MB"
        assert _format_size(2097152) == "2.0MB"
        assert _format_size(1572864) == "1.5MB"

    def test_boundary_values(self):
        from RxyCode.RxyCode1_1_0.tools.ls import _format_size
        assert _format_size(1024) == "1.0KB"
        assert _format_size(1024 * 1024) == "1.0MB"


class TestRunView:
    def _view(self, filePath, offset=1, limit=2000):
        from RxyCode.RxyCode1_1_0.tools.view import run_view
        return run_view(filePath, offset, limit)

    def test_view_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content\n", encoding="utf-8")
        result = self._view(str(f))
        assert "content" in result

    def test_view_nonexistent_file(self):
        result = self._view("/nonexistent/file")
        assert "error" in result.lower() or "not found" in result.lower()

    def test_view_with_offset(self, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = self._view(str(f), offset=2)
        assert "line2" in result
        assert "line1" not in result

    def test_view_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.view import view_tool
        assert view_tool.name == "view"
