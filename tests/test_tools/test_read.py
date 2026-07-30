"""
Tests for tools/read.py - File reading and directory listing.

Covers: file read, directory listing, offset/limit, encoding, edge cases.
"""
import os
import tempfile
import pytest
from pathlib import Path


class TestReadFile:
    """Tests for read_file function."""

    def _read(self, filePath, offset=1, limit=2000):
        from RxyCode.RxyCode1_1_0.tools.read import read_file
        return read_file(filePath, offset, limit)

    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = self._read(str(f))
        assert "1: line1" in result
        assert "2: line2" in result
        assert "3: line3" in result

    def test_read_nonexistent_file(self):
        result = self._read("/nonexistent/path/file.txt")
        assert "not found" in result.lower()

    def test_read_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = self._read(str(f))
        assert result == ""

    def test_read_single_line_file(self, tmp_path):
        f = tmp_path / "single.txt"
        f.write_text("only line", encoding="utf-8")
        result = self._read(str(f))
        assert "1: only line" in result

    def test_read_with_offset(self, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
        result = self._read(str(f), offset=3)
        assert "3: line3" in result
        assert "2: line2" not in result

    def test_read_with_limit(self, tmp_path):
        f = tmp_path / "multi.txt"
        lines = [f"line{i}" for i in range(1, 21)]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self._read(str(f), limit=5)
        assert "1: line1" in result
        assert "5: line5" in result
        assert "6: line6" not in result

    def test_read_with_offset_and_limit(self, tmp_path):
        f = tmp_path / "multi.txt"
        lines = [f"line{i}" for i in range(1, 21)]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self._read(str(f), offset=5, limit=3)
        assert "5: line5" in result
        assert "7: line7" in result
        assert "4: line4" not in result
        assert "8: line8" not in result

    def test_read_offset_beyond_file(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("line1\nline2\n", encoding="utf-8")
        result = self._read(str(f), offset=100)
        assert result == ""

    def test_read_limit_zero(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content\n", encoding="utf-8")
        result = self._read(str(f), limit=0)
        assert result == ""

    def test_read_utf8_file(self, tmp_path):
        f = tmp_path / "utf8.txt"
        f.write_text("你好世界\nこんにちは\n안녕하세요\n", encoding="utf-8")
        result = self._read(str(f))
        assert "你好世界" in result
        assert "こんにちは" in result

    def test_read_binary_file_graceful(self, tmp_path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        result = self._read(str(f))
        # Should not crash, may have replacement chars
        assert isinstance(result, str)

    def test_read_large_file_truncated(self, tmp_path):
        f = tmp_path / "large.txt"
        lines = [f"line {i}" for i in range(5000)]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self._read(str(f), limit=100)
        lines_in_result = result.count("\n")
        assert lines_in_result <= 100

    def test_read_file_with_trailing_newline(self, tmp_path):
        f = tmp_path / "trailing.txt"
        f.write_text("content\n\n\n", encoding="utf-8")
        result = self._read(str(f))
        assert "1: content" in result

    def test_read_file_no_trailing_newline(self, tmp_path):
        f = tmp_path / "notrail.txt"
        f.write_text("no newline", encoding="utf-8")
        result = self._read(str(f))
        assert "1: no newline" in result

    def test_read_file_with_windows_line_endings(self, tmp_path):
        f = tmp_path / "crlf.txt"
        f.write_bytes(b"line1\r\nline2\r\nline3\r\n")
        result = self._read(str(f))
        assert "line1" in result
        assert "line2" in result

    def test_read_preserves_line_numbers(self, tmp_path):
        f = tmp_path / "numbered.txt"
        f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
        result = self._read(str(f))
        for i, letter in enumerate("abcde", 1):
            assert f"{i}: {letter}" in result

    def test_read_line_numbers_are_sequential(self, tmp_path):
        f = tmp_path / "seq.txt"
        f.write_text("\n".join([f"row{i}" for i in range(1, 51)]) + "\n", encoding="utf-8")
        result = self._read(str(f))
        numbers = [int(line.split(":")[0]) for line in result.split("\n") if line.strip()]
        assert numbers == list(range(1, 51))

    def test_read_negative_offset_clamped_to_zero(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld\n", encoding="utf-8")
        result = self._read(str(f), offset=-5)
        assert "1: hello" in result

    def test_read_default_offset_is_1(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("first\nsecond\n", encoding="utf-8")
        result = self._read(str(f))
        assert "1: first" in result

    def test_read_default_limit_is_800(self, tmp_path):
        f = tmp_path / "test.txt"
        lines = [f"line{i}" for i in range(1, 2500)]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.tools.read import read_file
        result = read_file(str(f))
        assert "800: line800" in result
        assert "801: line801" not in result

    def test_read_explicit_limit_overrides_default(self, tmp_path):
        f = tmp_path / "test.txt"
        lines = [f"line{i}" for i in range(1, 2500)]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self._read(str(f), limit=2000)
        assert "2000: line2000" in result
        assert "2001: line2001" not in result


class TestReadDirectory:
    """E5: read rejects directories; callers should use ls/glob."""

    def _read(self, path):
        from RxyCode.RxyCode1_1_0.tools.read import read_file
        return read_file(path)

    def test_read_empty_directory(self, tmp_path):
        result = self._read(str(tmp_path))
        assert "error" in result.lower()
        assert "目录" in result or "ls" in result.lower()

    def test_read_directory_with_files(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("b", encoding="utf-8")
        result = self._read(str(tmp_path))
        assert "error" in result.lower()
        assert "ls" in result.lower() or "glob" in result.lower() or "目录" in result

    def test_read_directory_with_subdirs(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("a", encoding="utf-8")
        result = self._read(str(tmp_path))
        assert "error" in result.lower()

    def test_read_directory_sorts_dirs_before_files(self, tmp_path):
        (tmp_path / "z_dir").mkdir()
        (tmp_path / "a_file.txt").write_text("a", encoding="utf-8")
        result = self._read(str(tmp_path))
        assert "error" in result.lower()

    def test_read_directory_adds_slash_suffix(self, tmp_path):
        (tmp_path / "mydir").mkdir()
        result = self._read(str(tmp_path))
        assert "error" in result.lower()

    def test_read_nested_directory(self, tmp_path):
        sub = tmp_path / "parent" / "child"
        sub.mkdir(parents=True)
        (sub / "deep.txt").write_text("deep", encoding="utf-8")
        result = self._read(str(tmp_path / "parent"))
        assert "error" in result.lower()

    def test_read_nonexistent_directory(self):
        result = self._read("/nonexistent/dir/path")
        assert "not found" in result.lower()


class TestReadTool:
    """Tests for the StructuredTool wrapper."""

    def test_tool_has_name(self):
        from RxyCode.RxyCode1_1_0.tools.read import read_tool
        assert read_tool.name == "read"

    def test_tool_has_description(self):
        from RxyCode.RxyCode1_1_0.tools.read import read_tool
        assert len(read_tool.description) > 10

    def test_tool_invocation(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.read import read_tool
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        result = read_tool.invoke({"filePath": str(f)})
        assert "hello" in result

    def test_tool_args_schema(self):
        from RxyCode.RxyCode1_1_0.tools.read import ReadInput
        schema = ReadInput(filePath="/tmp/test")
        assert schema.filePath == "/tmp/test"
        assert schema.offset == 1
        assert schema.limit == 800
