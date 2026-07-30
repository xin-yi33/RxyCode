"""End-to-end test of the file-operation tools RxyCode uses to modify files.

This is the backend equivalent of the user's request:
"文件操作，就你随便写一份文件或者是抄一份文件到本地，然后交给他去改，去试"
  -> create a local file, then have RxyCode's file tools modify it.

It drives the REAL tools.write / tools.edit / tools.read functions against
real files on disk and asserts the modifications actually land.
"""
import os
import tempfile

from RxyCode.RxyCode1_1_0.tools.write import write_file
from RxyCode.RxyCode1_1_0.tools.edit import edit_file
from RxyCode.RxyCode1_1_0.tools.read import read_file


def _tmp():
    return tempfile.mkdtemp(prefix="rxycode_fileops_")


def test_write_creates_file_and_verifies_python_syntax():
    d = _tmp()
    p = os.path.join(d, "hello.py")
    code = "def hello():\n    return 'hi'\n"
    res = write_file(p, code)
    assert "wrote" in res
    assert "syntax check: OK" in res
    assert os.path.exists(p)
    with open(p, encoding="utf-8") as f:
        assert f.read() == code


def test_write_detects_python_syntax_error():
    d = _tmp()
    p = os.path.join(d, "bad.py")
    res = write_file(p, "def broken(:\n    pass\n")
    assert "SYNTAX_ERROR" in res  # tool surfaces the error instead of silently writing bad code


def test_edit_fixes_bug_in_local_file():
    # 1) "随便写一份文件到本地"
    d = _tmp()
    p = os.path.join(d, "demo_config.py")
    original = "HOST = '127.0.0.1'\n# PORT = 8080\nDEBUG = True\n"
    write_file(p, original)

    # 2) "交给他去改" -> the edit tool repairs the missing PORT config
    res = edit_file(p, "# PORT = 8080", "PORT = 8080")
    assert "edited" in res
    content = read_file(p)
    assert "PORT = 8080" in content
    assert "# PORT = 8080" not in content


def test_edit_reports_helpful_error_when_oldstring_missing():
    d = _tmp()
    p = os.path.join(d, "x.py")
    write_file(p, "a = 1\n")
    res = edit_file(p, "nonexistent_string", "replacement")
    assert "not found" in res          # actionable error, not a silent no-op
    assert "similar content" in res or "file starts with" in res


def test_edit_rejects_identical_strings():
    d = _tmp()
    p = os.path.join(d, "x.py")
    write_file(p, "a = 1\n")
    res = edit_file(p, "a = 1", "a = 1")
    assert "identical" in res          # prevents meaningless no-op edits


def test_edit_rejects_ambiguous_oldstring_without_replace_all():
    d = _tmp()
    p = os.path.join(d, "dup.py")
    write_file(p, "x = 1\nx = 1\n")
    res = edit_file(p, "x = 1", "x = 2")
    assert "found 2 matches" in res    # forces the caller to disambiguate


def test_read_returns_file_contents():
    d = _tmp()
    p = os.path.join(d, "r.py")
    write_file(p, "print('hi')\n")
    out = read_file(p)
    assert "print('hi')" in out
