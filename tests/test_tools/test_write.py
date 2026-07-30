"""
Tests for tools/write.py - File writing and syntax verification.

Covers: write, syntax check, parent dir creation, overwrite, errors.
"""
import os
import pytest
from pathlib import Path


class TestWriteFile:
    def _write(self, filePath, content):
        from RxyCode.RxyCode1_1_0.tools.write import write_file
        return write_file(filePath, content)

    def _target(self, filePath):
        from RxyCode.RxyCode1_1_0.core.session_runtime import resolve_write_path
        return resolve_write_path(filePath)

    def test_write_new_relative_file_uses_dated_output(self, tmp_path, monkeypatch):
        from datetime import datetime

        data_dir = tmp_path / "data"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
        monkeypatch.chdir(workspace)

        result = self._write("new.txt", "hello world")

        generated = data_dir / "output" / datetime.now().strftime("%Y-%m-%d") / "new.txt"
        assert generated.read_text(encoding="utf-8") == "hello world"
        assert not (workspace / "new.txt").exists()
        assert str(generated) in result

    def test_write_overwrite_existing(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old content", encoding="utf-8")
        result = self._write(str(f), "new content")
        assert f.read_text(encoding="utf-8") == "new content"

    def test_write_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "c" / "file.txt"
        target = self._target(str(f))
        self._write(str(f), "deep")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "deep"

    def test_write_empty_content(self, tmp_path):
        f = tmp_path / "empty.txt"
        target = self._target(str(f))
        self._write(str(f), "")
        assert target.read_text(encoding="utf-8") == ""

    def test_write_unicode_content(self, tmp_path):
        f = tmp_path / "unicode.txt"
        target = self._target(str(f))
        content = "你好世界\nこんにちは\n안녕하세요"
        self._write(str(f), content)
        assert target.read_text(encoding="utf-8") == content

    def test_write_returns_byte_count(self, tmp_path):
        f = tmp_path / "test.txt"
        result = self._write(str(f), "hello")
        assert "5" in result  # len("hello") == 5

    def test_write_large_content(self, tmp_path):
        f = tmp_path / "large.txt"
        target = self._target(str(f))
        content = "x" * 100000
        self._write(str(f), content)
        assert target.read_text(encoding="utf-8") == content

    def test_write_multiline_content(self, tmp_path):
        f = tmp_path / "multi.txt"
        target = self._target(str(f))
        content = "line1\nline2\nline3\n"
        self._write(str(f), content)
        assert target.read_text(encoding="utf-8") == content

    def test_write_to_existing_path_overwrites(self, tmp_path):
        f = tmp_path / "test.txt"
        target = self._target(str(f))
        self._write(str(f), "first")
        self._write(str(target), "second")
        assert target.read_text(encoding="utf-8") == "second"

    def test_write_special_chars_in_content(self, tmp_path):
        f = tmp_path / "special.txt"
        target = self._target(str(f))
        content = 'content with "quotes" and \n tabs\tand symbols <>&'
        self._write(str(f), content)
        assert target.read_text(encoding="utf-8") == content


class TestVerifySyntax:
    def _verify(self, path, content):
        from RxyCode.RxyCode1_1_0.tools.write import _verify_syntax
        return _verify_syntax(path, content)

    def test_valid_python_syntax(self, tmp_path):
        result = self._verify(tmp_path / "test.py", "x = 1\nprint(x)\n")
        assert result == "OK"

    def test_invalid_python_syntax(self, tmp_path):
        result = self._verify(tmp_path / "test.py", "def f(\n")
        assert "SYNTAX_ERROR" in result

    def test_python_syntax_missing_colon(self, tmp_path):
        result = self._verify(tmp_path / "test.py", "if True\n    pass\n")
        assert "SYNTAX_ERROR" in result

    def test_python_syntax_missing_paren(self, tmp_path):
        result = self._verify(tmp_path / "test.py", "print('hello'\n")
        assert "SYNTAX_ERROR" in result

    def test_valid_js_brackets(self, tmp_path):
        result = self._verify(tmp_path / "test.js", "function f() { return 1; }\n")
        assert result == "OK"

    def test_invalid_js_bracket_mismatch(self, tmp_path):
        result = self._verify(tmp_path / "test.js", "function f() { return 1;\n")
        assert "BRACKET_MISMATCH" in result

    def test_valid_ts_syntax(self, tmp_path):
        result = self._verify(tmp_path / "test.ts", "const x: number = 1;\n")
        assert result == "OK"

    def test_invalid_ts_brackets(self, tmp_path):
        result = self._verify(tmp_path / "test.ts", "const arr = [1, 2;\n")
        assert "BRACKET_MISMATCH" in result

    def test_unsupported_extension(self, tmp_path):
        result = self._verify(tmp_path / "test.txt", "some content")
        assert result == ""

    def test_empty_python_file(self, tmp_path):
        result = self._verify(tmp_path / "empty.py", "")
        assert result == "OK"

    def test_python_with_class_and_imports(self, tmp_path):
        code = "import os\nclass Foo:\n    pass\n"
        result = self._verify(tmp_path / "test.py", code)
        assert result == "OK"

    def test_python_with_async(self, tmp_path):
        code = "async def main():\n    pass\n"
        result = self._verify(tmp_path / "test.py", code)
        assert result == "OK"

    def test_jsx_syntax_valid(self, tmp_path):
        code = "const App = () => { return <div>hello</div>; };\n"
        result = self._verify(tmp_path / "test.jsx", code)
        assert result == "OK"

    def test_jsx_syntax_bracket_mismatch(self, tmp_path):
        code = "const App = () => { return <div>hello;\n"
        result = self._verify(tmp_path / "test.jsx", code)
        assert "BRACKET_MISMATCH" in result

    def test_tsx_syntax_valid(self, tmp_path):
        code = "const x = <Component prop={1} />;\n"
        result = self._verify(tmp_path / "test.tsx", code)
        assert result == "OK"


class TestWriteTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.write import write_tool
        assert write_tool.name == "write"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.write import write_tool
        assert len(write_tool.description) > 5

    def test_tool_invocation(self, tmp_path):
        from RxyCode.RxyCode1_1_0.core.session_runtime import resolve_write_path
        from RxyCode.RxyCode1_1_0.tools.write import write_tool

        f = tmp_path / "tool_test.txt"
        target = resolve_write_path(str(f))
        write_tool.invoke({"filePath": str(f), "content": "test"})
        assert target.read_text(encoding="utf-8") == "test"

    def test_write_includes_syntax_check_for_py(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.write import write_file
        f = tmp_path / "test.py"
        result = write_file(str(f), "x = 1\n")
        assert "syntax check" in result.lower()

    def test_write_no_syntax_check_for_txt(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.write import write_file
        f = tmp_path / "test.txt"
        result = write_file(str(f), "just text")
        assert "syntax check" not in result.lower()
