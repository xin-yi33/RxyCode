"""Reproduce the diagnostics audit findings (checker crash reported as pass)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

pytestmark = pytest.mark.asyncio


def show(claim: str, reproduced: bool, detail: str = "") -> None:
    tag = "REPRODUCED" if reproduced else "not reproduced"
    print(f"  [{tag}] {claim}" + (f" :: {detail}" if detail else ""))


async def test_eslint_crash_is_not_pass(tmp_path: Path):
    """A config-broken eslint exits 2; that must not read as 'no problems'."""
    eslint = shutil.which("eslint")
    local = tmp_path / "node_modules" / ".bin" / ("eslint.cmd" if os.name == "nt" else "eslint")
    if not eslint and not local.exists():
        pytest.skip("eslint not installed")

    # Break the project config so eslint exits 2 without producing JSON.
    (tmp_path / "eslint.config.js").write_text("this is not javascript!!!", encoding="utf-8")
    target = tmp_path / "a.js"
    target.write_text("const a = 1;\n", encoding="utf-8")

    report = await diag.diagnose(target, "const a = 1;\n")
    print(f"\n  eslint crash report: status={report.status} checker={report.checker}")
    show(
        "broken eslint config reported as pass",
        report.status == "pass" and report.ok,
        f"status={report.status}",
    )
    assert report.status != "pass", "a crashed checker must not count as a pass"


async def test_ruff_crash_is_not_pass(tmp_path: Path):
    ruff = shutil.which("ruff")
    if not ruff:
        pytest.skip("ruff not installed")

    # A ruff.toml with an invalid setting makes ruff exit non-zero with no JSON.
    (tmp_path / "ruff.toml").write_text("[tool.ruff\nbroken = \n", encoding="utf-8")
    target = tmp_path / "b.py"
    target.write_text("x = 1\n", encoding="utf-8")
    report = await diag.diagnose(target, "x = 1\n")
    print(f"\n  ruff crash report: status={report.status} checker={report.checker}")
    assert report.status != "pass", "a crashed ruff must not count as a pass"


async def test_stale_report_not_used_for_newer_content(tmp_path: Path):
    """A report for version A must be marked stale once B is on disk."""
    target = tmp_path / "v.py"
    good = "x = 1\n"
    target.write_text(good, encoding="utf-8")
    report = await diag.diagnose(target, good, operation="write")

    # Version B is written after the check started.
    broken = "def f(:\n"
    target.write_text(broken, encoding="utf-8")

    current = diag.content_fingerprint(broken)
    stale = diag.mark_stale(report, current)
    print(f"\n  stale check: before={report.status} after={stale.status}")
    assert stale.status == "stale"
    assert stale.ok is False


async def test_ts_uses_project_config(tmp_path: Path):
    """tsc must run with the project's tsconfig, not ad-hoc flags."""
    tsc = shutil.which("tsc")
    local = tmp_path / "node_modules" / ".bin" / ("tsc.cmd" if os.name == "nt" else "tsc")
    if not tsc and not local.exists():
        pytest.skip("tsc not installed")

    (tmp_path / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2020",
                    "lib": ["ES2020", "DOM"],
                    "strict": True,
                    "jsx": "react-jsx",
                    "noEmit": True,
                }
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "a.tsx"
    content = "export const A = () => <div>hi</div>;\n"
    target.write_text(content, encoding="utf-8")

    report = await diag.diagnose(target, content)
    print(f"\n  tsx report: status={report.status} issues={len(report.issues)}")
    if report.issues:
        print(f"    first: {report.issues[0].message[:120]}")
    show(
        "valid TSX reported as problems because tsconfig was ignored",
        report.status == "problems",
        f"status={report.status}",
    )
