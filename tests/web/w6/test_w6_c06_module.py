"""WEB-W6-C06. Local Full runs a harmless command and the page shows permission and target."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-server" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")


def test_w6_c06_integration() -> None:
    """rxycode web local Full writes a real file. The page shows that permission and target."""
    from rxycode_server.release.journey import local_full_journey

    work = REPO / "tests" / "web" / "w6" / "_full_c06"
    work.mkdir(parents=True, exist_ok=True)
    try:
        result = local_full_journey(work)
        assert result["permission"] == "full"
        assert result["target"] == "local"
        assert result["exit"] == 0
        assert result["marker"] == "local-full"
        assert (work / "harmless.txt").read_text(encoding="utf-8") == "local-full"
    finally:
        for child in sorted(work.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        work.rmdir()
    markup = _render_journey(result["permission"], result["target"])
    assert 'data-permission="full"' in markup
    assert 'data-target="local"' in markup
    assert 'data-status="ready"' in markup


def _render_journey(permission: str, target: str) -> str:
    if not BUN.is_file():
        pytest.fail("bun is not installed")
    page = REPO / "apps" / "web" / "src" / "features" / "onboarding" / "journey.ts"
    env = os.environ.copy()
    env["RXY_PAGE"] = str(page)
    env["RXY_PERMISSION"] = permission
    env["RXY_TARGET"] = target
    script = r"""
import { pathToFileURL } from "url"
const page = await import(pathToFileURL(process.env.RXY_PAGE).href)
process.stdout.write(page.journeyMarkup({
  permission: process.env.RXY_PERMISSION,
  target: process.env.RXY_TARGET,
  status: "ready",
}))
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c06-")) / "journey.ts"
    program.write_text(script, encoding="utf-8")
    try:
        rendered = subprocess.run(
            [str(BUN), str(program)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
        program.parent.rmdir()
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout
