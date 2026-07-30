"""Read tool path contract matrices: wildcards, directories, paging."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.tools.read import read_file


_WILDCARDS = ("*", "?", "[a]", "[0-9]", "**", "foo*", "*bar", "a?c", "[!x]")
_BASES = (
    "src/main.py",
    "logs/app.log",
    "data/readme.txt",
    "/tmp/file.txt",
    "C:/work/app.py",
    "./relative/path.py",
    "nested/deep/file.md",
    "file[1].txt",
    "dir/sub/file",
    "single",
)

_WILDCARD_PATHS = [
    f"{base.replace('.py', '')}{wc}{ext}"
    for base, wc, ext in itertools.product(
        _BASES[:6],
        _WILDCARDS,
        ("", ".py", ".log", ".txt"),
    )
]

_DIR_NAMES = (
    "src",
    "logs",
    "data",
    "nested/deep",
    "empty_dir",
    "build/output",
    ".git",
    "node_modules",
    "tests/fixtures",
    "tmp",
)


@pytest.mark.parametrize("path", _WILDCARD_PATHS)
def test_read_rejects_wildcard_paths(path: str):
    out = read_file(path)
    lowered = out.lower()
    assert "error" in lowered
    assert "glob" in lowered or "通配" in out or "wildcard" in lowered


@pytest.mark.parametrize("dirname", _DIR_NAMES)
def test_read_rejects_directory_paths(tmp_path, dirname: str):
    target = tmp_path / dirname
    target.mkdir(parents=True, exist_ok=True)
    out = read_file(str(target))
    lowered = out.lower()
    assert "error" in lowered
    assert "ls" in lowered or "glob" in lowered or "目录" in out


@pytest.mark.parametrize(
    ("offset", "limit"),
    itertools.product(range(1, 11), (0, 1, 3, 5, 10, 50)),
)
def test_read_paging_contract(tmp_path, offset: int, limit: int):
    f = tmp_path / "paged.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8")
    out = read_file(str(f), offset=offset, limit=limit)
    if limit == 0:
        assert out == ""
        return
    first_expected = min(offset, 20)
    if offset > 20:
        assert out == ""
        return
    assert f"{first_expected}:" in out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) <= limit


@pytest.mark.parametrize("missing", [p for p in _BASES if not any(ch in p for ch in ("*", "?", "["))])
def test_read_missing_path_reports_not_found(missing: str):
    out = read_file(f"/nonexistent/rxycode/{missing}")
    assert "not found" in out.lower()


def test_read_valid_file_returns_numbered_lines(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("alpha\nbeta\n", encoding="utf-8")
    out = read_file(str(f))
    assert "1: alpha" in out
    assert "2: beta" in out
