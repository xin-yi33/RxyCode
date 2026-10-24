"""Post-write diagnostics: real checkers, honest status, version binding.

Covers acceptance group C (write -> diagnose loop) at the unit level.  These
execute real checker processes (python compile / ruff / node --check) where
available and assert the *honest* report when one is missing.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core.post_write_diagnostics import (
    DiagnosticReport,
    content_fingerprint,
    diagnose,
    mark_stale,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def ws_dir():
    """A scratch directory INSIDE the execution workspace.

    Checkers now run through the controlled execution entry (audit P1-03), and
    the workspace sandbox refuses a cwd outside ``execution.workspace_root``.
    Temp dirs elsewhere would make every report "unavailable", so these tests
    work inside the workspace and clean up afterwards.
    """
    root = Path(os.getcwd()) / f"_diagws_{uuid.uuid4().hex[:8]}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


class TestPython:
    async def test_valid_python_passes(self, ws_dir: Path):
        p = ws_dir / "ok.py"
        content = "def f():\n    return 1\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        assert report.status == "pass"
        assert report.written is True
        assert "python:compile" in report.checker

    async def test_syntax_error_is_problems_not_write_failure(self, ws_dir: Path):
        p = ws_dir / "bad.py"
        content = "def f(:\n    pass\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        assert report.status == "problems"
        # The write still happened; the file is on disk.
        assert report.written is True
        assert p.exists()
        assert report.issues[0].line == 1

    async def test_report_without_ruff_says_so(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        p = tmp_path / "noruff.py"
        content = "x = 1\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        assert report.status == "pass"
        assert "ruff not installed" in report.note

    async def test_syntax_is_checked_without_executing(self, ws_dir: Path):
        p = ws_dir / "danger.py"
        marker = ws_dir / "executed.txt"
        # If this ran, the marker file would appear.
        content = f"open(r'{marker}', 'w').write('ran')\n"
        p.write_text(content, encoding="utf-8")
        await diagnose(p, content)
        assert not marker.exists()


class TestJavaScript:
    async def test_broken_js_is_problems(self, ws_dir: Path):
        if not shutil.which("node"):
            pytest.skip("node not installed")
        p = ws_dir / "bad.js"
        content = "const a = ;\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        assert report.status == "problems"
        assert report.checker

    async def test_jsx_without_checker_is_unavailable(self, tmp_path: Path, monkeypatch):
        """JSX is not valid JS, so it must never be judged by node --check."""
        monkeypatch.setattr(shutil, "which", lambda name: None)
        p = tmp_path / "comp.jsx"
        content = "const A = () => <div/>;\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        assert report.status == "unavailable"
        assert report.ok is False

    async def test_tsx_unavailable_never_counts_as_pass(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        p = tmp_path / "comp.tsx"
        content = "const A = () => <div/>;\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        assert report.status == "unavailable"
        assert report.ok is False


class TestUnchecked:
    async def test_unknown_extension_is_not_checked(self, tmp_path: Path):
        p = tmp_path / "notes.md"
        p.write_text("# hi\n", encoding="utf-8")
        report = await diagnose(p, "# hi\n")
        assert report.status == "not_checked"
        assert report.ok is False

    async def test_statuses_other_than_pass_are_not_ok(self):
        for status in ("problems", "unavailable", "timeout", "cancelled", "stale", "not_checked"):
            report = DiagnosticReport(path="x", status=status)  # type: ignore[arg-type]
            assert report.ok is False, status


class TestVersionBinding:
    async def test_fingerprint_tracks_content_not_mtime(self):
        a = content_fingerprint("x = 1\n")
        b = content_fingerprint("x = 2\n")
        assert a != b

    async def test_overwritten_version_marks_previous_report_stale(self, tmp_path: Path):
        p = tmp_path / "v.py"
        old = "x = 1\n"
        new = "y = 2\n"
        p.write_text(old, encoding="utf-8")
        report = await diagnose(p, old)
        p.write_text(new, encoding="utf-8")
        stale = mark_stale(report, content_fingerprint(new))
        assert stale.status == "stale"
        assert stale.ok is False

    async def test_same_version_stays_valid(self):
        content = "x = 1\n"
        report = DiagnosticReport(path="p", fingerprint=content_fingerprint(content), status="pass")
        same = mark_stale(report, content_fingerprint(content))
        assert same.status == "pass"


class TestRendering:
    async def test_problems_block_shows_position(self, ws_dir: Path):
        p = ws_dir / "r.py"
        content = "def f(:\n    pass\n"
        p.write_text(content, encoding="utf-8")
        report = await diagnose(p, content)
        text = report.render()
        assert "problem" in text
        assert "line 1" in text


class TestWriteAndEditShareOnePath:
    async def test_write_then_edit_reports_both(self, ws_dir: Path):
        from RxyCode.RxyCode1_1_0.tools.edit import edit_file_async
        from RxyCode.RxyCode1_1_0.tools.write import write_file_async

        target = ws_dir / "flow.py"
        written = await write_file_async(str(target), "x = 1\n")
        assert "[wrote" in written
        assert "syntax check: OK" in written

        broken = await edit_file_async(str(target), "x = 1", "x = (")
        assert "[edited" in broken
        assert "problem" in broken

        fixed = await edit_file_async(str(target), "x = (", "x = 2")
        assert "syntax check: OK" in fixed

    async def test_edit_checks_exactly_once(self, ws_dir: Path, monkeypatch):
        from RxyCode.RxyCode1_1_0.tools import edit as edit_mod
        from RxyCode.RxyCode1_1_0.tools import write as write_mod

        calls = []
        real = write_mod.post_write_report_async

        async def counting(path, content, *, operation="write"):
            calls.append(operation)
            return await real(path, content, operation=operation)

        monkeypatch.setattr(write_mod, "post_write_report_async", counting)
        monkeypatch.setattr(
            edit_mod, "post_write_report_async", counting, raising=False
        )

        target = ws_dir / "once.py"
        await write_mod.write_file_async(str(target), "x = 1\n")
        await edit_mod.edit_file_async(str(target), "x = 1", "x = 2")
        assert calls == ["write", "edit"]
