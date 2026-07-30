"""
Tests for tools/edit.py - File editing with exact match replacement.

Covers: single replace, replaceAll, fuzzy matching hints, edge cases.
"""
import pytest
from pathlib import Path


class TestEditFile:
    def _edit(self, filePath, oldString, newString, replaceAll=False):
        from RxyCode.RxyCode1_1_0.tools.edit import edit_file
        return edit_file(filePath, oldString, newString, replaceAll)

    def _setup_file(self, tmp_path, content):
        f = tmp_path / "edit_test.txt"
        f.write_text(content, encoding="utf-8")
        return f

    def test_simple_replace(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world")
        result = self._edit(str(f), "hello", "hi")
        assert f.read_text(encoding="utf-8") == "hi world"
        assert "edited" in result.lower()

    def test_replace_multiline(self, tmp_path):
        f = self._setup_file(tmp_path, "line1\nline2\nline3")
        result = self._edit(str(f), "line2", "replaced")
        assert "replaced" in f.read_text(encoding="utf-8")

    def test_file_not_found(self, tmp_path):
        result = self._edit(str(tmp_path / "nonexistent.txt"), "a", "b")
        assert "not found" in result.lower()

    def test_old_string_not_found(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world")
        result = self._edit(str(f), "nonexistent", "replacement")
        assert "not found" in result.lower()
        assert "searched for" in result.lower()

    def test_identical_old_and_new(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world")
        result = self._edit(str(f), "hello", "hello")
        assert "identical" in result.lower()

    def test_multiple_matches_without_replace_all(self, tmp_path):
        f = self._setup_file(tmp_path, "a a a")
        result = self._edit(str(f), "a", "b")
        assert "found 3 matches" in result.lower() or "3" in result

    def test_replace_all(self, tmp_path):
        f = self._setup_file(tmp_path, "a a a")
        result = self._edit(str(f), "a", "b", replaceAll=True)
        assert f.read_text(encoding="utf-8") == "b b b"

    def test_replace_all_no_matches(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world")
        result = self._edit(str(f), "xyz", "abc", replaceAll=True)
        assert "not found" in result.lower()

    def test_replace_preserves_other_content(self, tmp_path):
        f = self._setup_file(tmp_path, "keep1\nreplace_me\nkeep2")
        self._edit(str(f), "replace_me", "done")
        content = f.read_text(encoding="utf-8")
        assert "keep1" in content
        assert "done" in content
        assert "keep2" in content

    def test_replace_with_empty_string(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world")
        self._edit(str(f), "hello ", "")
        assert f.read_text(encoding="utf-8") == "world"

    def test_replace_with_newlines(self, tmp_path):
        f = self._setup_file(tmp_path, "single line")
        self._edit(str(f), "single line", "line1\nline2")
        assert "line1" in f.read_text(encoding="utf-8")
        assert "line2" in f.read_text(encoding="utf-8")

    def test_error_message_shows_searched_text(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world")
        result = self._edit(str(f), "notfound", "x")
        assert "searched for" in result.lower() or repr("notfound"[:200]) in result

    def test_error_message_shows_similar_lines(self, tmp_path):
        f = self._setup_file(tmp_path, "hello world\nhello earth")
        # Use a first line that partially matches existing lines
        result = self._edit(str(f), "hello universe\nextra line", "x")
        assert "similar" in result.lower() or "file starts with" in result.lower()

    def test_replace_unicode(self, tmp_path):
        f = self._setup_file(tmp_path, "你好世界")
        self._edit(str(f), "你好", "再见")
        assert "再见世界" == f.read_text(encoding="utf-8")

    def test_replace_special_regex_chars(self, tmp_path):
        f = self._setup_file(tmp_path, "price: $100")
        self._edit(str(f), "$100", "$200")
        assert "$200" in f.read_text(encoding="utf-8")

    def test_replace_at_file_start(self, tmp_path):
        f = self._setup_file(tmp_path, "start\nmiddle\nend")
        self._edit(str(f), "start", "BEGIN")
        assert "BEGIN" in f.read_text(encoding="utf-8")

    def test_replace_at_file_end(self, tmp_path):
        f = self._setup_file(tmp_path, "start\nmiddle\nend")
        self._edit(str(f), "end", "END")
        assert "END" in f.read_text(encoding="utf-8")

    def test_replace_entire_file(self, tmp_path):
        f = self._setup_file(tmp_path, "entire content here")
        self._edit(str(f), "entire content here", "completely new")
        assert f.read_text(encoding="utf-8") == "completely new"

    def test_replace_preserves_trailing_newline(self, tmp_path):
        f = self._setup_file(tmp_path, "line1\nline2\n")
        self._edit(str(f), "line2", "replaced")
        content = f.read_text(encoding="utf-8")
        assert content.endswith("\n")

    def test_single_match_replaces_first_occurrence(self, tmp_path):
        f = self._setup_file(tmp_path, "unique_string here")
        self._edit(str(f), "unique_string", "REPLACED")
        assert "REPLACED" in f.read_text(encoding="utf-8")

    def test_replace_preserves_file_encoding(self, tmp_path):
        f = self._setup_file(tmp_path, "hello")
        self._edit(str(f), "hello", "你好")
        content = f.read_text(encoding="utf-8")
        assert "你好" in content

    def test_error_shows_file_preview(self, tmp_path):
        f = self._setup_file(tmp_path, "line1\nline2\nline3")
        result = self._edit(str(f), "notfound", "x")
        assert "file starts with" in result.lower() or "line1" in result


class TestEditTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.edit import edit_tool
        assert edit_tool.name == "edit"

    def test_tool_has_description(self):
        from RxyCode.RxyCode1_1_0.tools.edit import edit_tool
        assert len(edit_tool.description) > 5

    def test_tool_args_schema_default(self):
        from RxyCode.RxyCode1_1_0.tools.edit import EditInput
        schema = EditInput(filePath="/t", oldString="a", newString="b")
        assert schema.replaceAll is False
