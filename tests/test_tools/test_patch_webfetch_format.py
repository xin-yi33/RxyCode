"""
Tests for tools/patch.py, tools/webfetch.py, tools/format_tool.py.

Covers: diff application, HTML conversion, formatter detection.
"""
import os
import pytest
from pathlib import Path


class TestApplyDiff:
    def _apply(self, original, diff):
        from RxyCode.RxyCode1_1_0.tools.patch import _apply_diff
        return _apply_diff(original, diff)

    def test_simple_addition(self):
        original = "line1\nline2\nline3"
        diff = "@@ -1,3 +1,4 @@\n line1\n line2\n+inserted\n line3"
        result = self._apply(original, diff)
        assert "inserted" in result
        assert "line1" in result
        assert "line3" in result

    def test_simple_removal(self):
        original = "line1\nremove_me\nline3"
        diff = "@@ -1,3 +1,2 @@\n line1\n-remove_me\n line3"
        result = self._apply(original, diff)
        assert "remove_me" not in result
        assert "line1" in result
        assert "line3" in result

    def test_simple_replacement(self):
        original = "old_line"
        diff = "@@ -1,1 +1,1 @@\n-old_line\n+new_line"
        result = self._apply(original, diff)
        assert result == "new_line"

    def test_context_lines_preserved(self):
        original = "keep1\nchange\nkeep2"
        diff = "@@ -1,3 +1,3 @@\n keep1\n-change\n+changed\n keep2"
        result = self._apply(original, diff)
        assert "keep1" in result
        assert "changed" in result
        assert "keep2" in result

    def test_empty_diff(self):
        original = "unchanged"
        result = self._apply(original, "")
        assert "unchanged" in result

    def test_diff_with_metadata_lines(self):
        original = "line1\nline2"
        diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1,2 +1,2 @@\n line1\n-line2\n+new2"
        result = self._apply(original, diff)
        assert "new2" in result

    def test_multiple_hunks(self):
        original = "a\nb\nc\nd\ne"
        diff = "@@ -1,2 +1,2 @@\n-a\n+A\n b\n@@ -4,2 +4,2 @@\n d\n-e\n+E"
        result = self._apply(original, diff)
        assert "A" in result
        assert "E" in result

    def test_no_newline_marker(self):
        original = "line1\nline2"
        diff = "@@ -1,2 +1,2 @@\n line1\n-line2\n+line2\n\\ No newline at end of file"
        result = self._apply(original, diff)
        assert "line1" in result


class TestRunPatch:
    def _patch(self, filePath, diff):
        from RxyCode.RxyCode1_1_0.tools.patch import run_patch
        return run_patch(filePath, diff)

    def test_patch_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("old content\n", encoding="utf-8")
        diff = "@@ -1,1 +1,1 @@\n-old content\n+new content"
        result = self._patch(str(f), diff)
        assert "Patch applied" in result
        assert "new content" in f.read_text(encoding="utf-8")

    def test_patch_nonexistent_file(self):
        result = self._patch("/nonexistent/file.txt", "@@ -1,1 +1,1 @@\n-a\n+b")
        assert "not found" in result.lower()

    def test_patch_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.patch import patch_tool
        assert patch_tool.name == "patch"


class TestHtmlToText:
    def _html2text(self, html):
        from RxyCode.RxyCode1_1_0.tools.webfetch import _html_to_text
        return _html_to_text(html)

    def test_removes_script_tags(self):
        html = "<script>alert('xss')</script><p>content</p>"
        result = self._html2text(html)
        assert "alert" not in result
        assert "content" in result

    def test_removes_style_tags(self):
        html = "<style>body { color: red; }</style><p>visible</p>"
        result = self._html2text(html)
        assert "color" not in result
        assert "visible" in result

    def test_removes_all_html_tags(self):
        html = "<div><span><b>bold text</b></span></div>"
        result = self._html2text(html)
        assert "bold text" in result
        assert "<" not in result

    def test_collapses_whitespace(self):
        html = "<p>hello</p>    <p>world</p>"
        result = self._html2text(html)
        assert "  " not in result

    def test_empty_html(self):
        assert self._html2text("") == ""

    def test_plain_text_passthrough(self):
        result = self._html2text("just plain text")
        assert "just plain text" in result

    def test_nested_tags(self):
        html = "<div><div><div>deep</div></div></div>"
        result = self._html2text(html)
        assert "deep" in result


class TestHtmlToMarkdown:
    def _html2md(self, html):
        from RxyCode.RxyCode1_1_0.tools.webfetch import _html_to_markdown
        return _html_to_markdown(html)

    def test_h1_conversion(self):
        result = self._html2md("<h1>Title</h1>")
        assert "# Title" in result

    def test_h2_conversion(self):
        result = self._html2md("<h2>Section</h2>")
        assert "## Section" in result

    def test_h3_conversion(self):
        result = self._html2md("<h3>Subsection</h3>")
        assert "### Subsection" in result

    def test_strong_to_bold(self):
        result = self._html2md("<strong>bold</strong>")
        assert "**bold**" in result

    def test_b_to_bold(self):
        result = self._html2md("<b>bold</b>")
        assert "**bold**" in result

    def test_em_to_italic(self):
        result = self._html2md("<em>italic</em>")
        assert "*italic*" in result

    def test_i_to_italic(self):
        result = self._html2md("<i>italic</i>")
        assert "*italic*" in result

    def test_code_to_backtick(self):
        result = self._html2md("<code>code</code>")
        assert "`code`" in result

    def test_link_conversion(self):
        result = self._html2md('<a href="https://example.com">link</a>')
        assert "[link](https://example.com)" in result

    def test_br_to_newline(self):
        result = self._html2md("line1<br>line2")
        assert "\n" in result

    def test_paragraph_to_double_newline(self):
        result = self._html2md("<p>para1</p><p>para2</p>")
        assert "\n\n" in result

    def test_removes_script(self):
        result = self._html2md("<script>alert(1)</script><p>ok</p>")
        assert "alert" not in result
        assert "ok" in result

    def test_removes_style(self):
        result = self._html2md("<style>.x{}</style><p>ok</p>")
        assert ".x" not in result
        assert "ok" in result

    def test_strips_remaining_tags(self):
        result = self._html2md("<div><span>text</span></div>")
        assert "<" not in result
        assert "text" in result

    def test_collapses_extra_newlines(self):
        result = self._html2md("<p>a</p><p>b</p><p>c</p>")
        assert "\n\n\n" not in result


class TestDetectFormatter:
    def _detect(self, file_path):
        from RxyCode.RxyCode1_1_0.tools.format_tool import _detect_formatter
        return _detect_formatter(file_path)

    def test_python_file(self):
        name, cmd = self._detect("test.py")
        assert name in ("ruff", "black", "autopep8")

    def test_js_file(self):
        name, cmd = self._detect("test.js")
        assert name == "prettier"

    def test_ts_file(self):
        name, cmd = self._detect("test.ts")
        assert name == "prettier"

    def test_json_file(self):
        name, cmd = self._detect("config.json")
        assert name == "prettier"

    def test_css_file(self):
        name, cmd = self._detect("style.css")
        assert name == "prettier"

    def test_rust_file(self):
        name, cmd = self._detect("main.rs")
        assert name == "rustfmt"

    def test_go_file(self):
        name, cmd = self._detect("main.go")
        assert name == "gofmt"

    def test_java_file(self):
        name, cmd = self._detect("Main.java")
        assert name == "google-java-format"

    def test_unknown_extension(self):
        name, cmd = self._detect("file.xyz")
        assert name is None

    def test_markdown_file(self):
        name, cmd = self._detect("readme.md")
        assert name == "prettier"

    def test_yaml_file(self):
        name, cmd = self._detect("config.yaml")
        assert name == "prettier"


class TestRunFormat:
    def _format(self, filePath="", tool="auto", checkOnly=False):
        from RxyCode.RxyCode1_1_0.tools.format_tool import run_format
        return run_format(filePath, tool, checkOnly)

    def test_empty_path_returns_error(self):
        result = self._format(filePath="")
        assert "error" in result.lower()

    def test_nonexistent_file(self):
        result = self._format(filePath="/nonexistent/file.py")
        assert "error" in result.lower()

    def test_file_too_large(self, tmp_path):
        f = tmp_path / "large.py"
        f.write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
        result = self._format(filePath=str(f))
        assert "too large" in result.lower()

    def test_unknown_formatter(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = self._format(filePath=str(f), tool="unknown_formatter")
        assert "error" in result.lower()

    def test_format_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.format_tool import format_tool
        assert format_tool.name == "format"

    def test_check_only_python(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = self._format(filePath=str(f), checkOnly=True)
        assert isinstance(result, str)

    def test_supported_extensions_in_error(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("content", encoding="utf-8")
        result = self._format(filePath=str(f))
        assert "no formatter" in result.lower() or "supported" in result.lower()
