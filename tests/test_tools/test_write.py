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

    def test_write_new_relative_file_uses_current_workspace(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
        monkeypatch.chdir(workspace)

        result = self._write("new.txt", "hello world")

        generated = workspace / "new.txt"
        assert generated.read_text(encoding="utf-8") == "hello world"
        assert not list((data_dir / "output").glob("**/new.txt"))
        assert str(generated) in result

    def test_write_new_relative_file_uses_explicit_session_workspace(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )

        data_dir = tmp_path / "data"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
        token = bind_session("desktop-workspace-write")
        try:
            set_working_directory(workspace)
            result = self._write("src/new.txt", "desktop workspace")
            target = workspace / "src" / "new.txt"
            assert target.read_text(encoding="utf-8") == "desktop workspace"
            assert str(target) in result
            assert not list((data_dir / "output").glob("**/new.txt"))
        finally:
            reset_session_binding(token)

    def test_relative_write_does_not_reuse_a_same_named_historical_output(
        self, tmp_path, monkeypatch
    ):
        from datetime import datetime

        data_dir = tmp_path / "data"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        historical = data_dir / "output" / "2020-01-01" / "cache.py"
        historical.parent.mkdir(parents=True)
        historical.write_text("old output", encoding="utf-8")
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
        monkeypatch.chdir(workspace)

        self._write("cache.py", "new workspace")

        assert (workspace / "cache.py").read_text(encoding="utf-8") == "new workspace"
        assert historical.read_text(encoding="utf-8") == "old output"

    def test_write_overwrite_existing(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old content", encoding="utf-8")
        self._write(str(f), "new content")
        assert f.read_text(encoding="utf-8") == "new content"

    def test_write_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "c" / "file.txt"
        target = self._target(str(f))
        self._write(str(f), "deep")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "deep"

    def test_absolute_write_keeps_nonexistent_parent_in_explicit_workspace(
        self, tmp_path, monkeypatch
    ):
        """An absolute target must not fall back to the dated output directory."""
        data_dir = tmp_path / "data"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))

        target = workspace / "nested" / "new.txt"
        result = self._write(str(target), "workspace target")

        assert target.read_text(encoding="utf-8") == "workspace target"
        assert str(target) in result
        assert not list((data_dir / "output").glob("**/new.txt"))

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

    def test_write_rejects_too_many_test_functions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bloated = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(17))
        result = self._write("tests/test_lru_cache.py", bloated)
        assert "error writing file" in result
        assert "17 test_ functions" in result
        four = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(4))
        too_many = self._write("tests/test_lru_cache.py", four)
        assert "error writing file" in too_many
        three = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(3))
        ok_lru = self._write("tests/test_lru_cache.py", three)
        assert "error writing file" not in ok_lru
        assert (tmp_path / "tests" / "test_lru_cache.py").is_file()
        login = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(4))
        ok_login = self._write("tests/test_login.py", login)
        assert "error writing file" not in ok_login
        six = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(6))
        ok = self._write("tests/test_calc.py", six)
        assert "error writing file" not in ok
        assert (tmp_path / "tests" / "test_calc.py").is_file()

    def test_write_rejects_test_module_at_workspace_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._write("test_simple.py", "def test_ok():\n    assert True\n")
        assert "belongs under tests/" in result
        assert not (tmp_path / "test_simple.py").exists()
        result2 = self._write("test.py", "def test_ok():\n    assert True\n")
        assert "belongs under tests/" in result2
        assert not (tmp_path / "test.py").exists()
        result3 = self._write("_min_test.py", "print(1)\n")
        assert "belongs under tests/" in result3
        assert not (tmp_path / "_min_test.py").exists()
        result4 = self._write("_quick_test.py", "print(1)\n")
        assert "belongs under tests/" in result4
        assert not (tmp_path / "_quick_test.py").exists()
        result5 = self._write("smoke_test.py", "print(1)\n")
        assert "belongs under tests/" in result5
        assert not (tmp_path / "smoke_test.py").exists()


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
        f = tmp_path / "sample.py"
        result = write_file(str(f), "x = 1\n")
        assert "syntax check" in result.lower()

    def test_write_no_syntax_check_for_txt(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.write import write_file
        f = tmp_path / "test.txt"
        result = write_file(str(f), "just text")
        assert "syntax check" not in result.lower()
