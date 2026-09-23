from __future__ import annotations

import os

from RxyCode.RxyCode1_1_0.utils.atomic_file import _replace_with_retry, atomic_write_text


def test_batch_script_is_written_with_crlf_for_cmd(tmp_path):
    target = tmp_path / "run.bat"

    atomic_write_text(target, "@echo off\nREM test\nexit /b 0\n")

    assert target.read_bytes() == b"@echo off\r\nREM test\r\nexit /b 0\r\n"


def test_non_batch_text_keeps_supplied_line_endings(tmp_path):
    target = tmp_path / "notes.txt"
    content = "first\nsecond\r\n"

    atomic_write_text(target, content)

    with open(target, encoding="utf-8", newline="") as f:
        assert f.read() == content


def test_replace_retries_windows_access_denied(tmp_path, monkeypatch):
    src = tmp_path / "a.tmp"
    dest = tmp_path / "a.json"
    src.write_text("new", encoding="utf-8")
    dest.write_text("old", encoding="utf-8")
    calls = {"n": 0}
    real = os.replace

    def flaky(source, target):
        calls["n"] += 1
        if calls["n"] == 1:
            err = OSError(13, "Access is denied")
            err.winerror = 5
            raise err
        return real(source, target)

    monkeypatch.setattr("RxyCode.RxyCode1_1_0.utils.atomic_file.os.replace", flaky)
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.utils.atomic_file.os.name", "nt")
    _replace_with_retry(str(src), str(dest), attempts=4)
    assert dest.read_text(encoding="utf-8") == "new"
    assert calls["n"] == 2
