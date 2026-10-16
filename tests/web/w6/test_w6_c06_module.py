"""WEB-W6-C06. Local Full runs a harmless command and the page shows permission and target."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))


def test_w6_c06_integration(tmp_path: Path) -> None:
    """rxycode web local Full writes a real file. The page shows that permission and target."""
    from rxycode_server.release.journey import local_full_journey

    result = local_full_journey(tmp_path)
    assert result["permission"] == "full"
    assert result["target"] == "local"
    assert result["exit"] == 0
    assert (tmp_path / "harmless.txt").read_text(encoding="utf-8") == "local-full"
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
