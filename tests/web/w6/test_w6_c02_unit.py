"""WEB-W6-C02. A real edit plus pytest changes the file. A failure is not success."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_CORE = REPO / "packages" / "rxycode-core" / "src"
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
for _entry in (REPO, _CORE):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _repo(root: Path, source: str, test_body: str) -> tuple[Path, Path]:
    sample = root / "sample.py"
    test_file = root / "test_sample.py"
    sample.write_text(source, encoding="utf-8")
    test_file.write_text(test_body, encoding="utf-8")
    return sample, test_file


def test_w6_c02_contract() -> None:
    """The broken function is edited through the tool path and pytest exits 0."""
    from rxycode_core.tools.coding_workflow import repair_and_test

    root = Path(tempfile.mkdtemp(prefix="rxy-w6c02-", dir=REPO))
    try:
        sample, test_file = _repo(
            root,
            "def add(a, b):\n    return a - b\n",
            "from sample import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
        )
        before = sample.read_text(encoding="utf-8")
        result = repair_and_test(
            root=root,
            file_path=sample,
            old="return a - b",
            new="return a + b  # fixed-by-edit",
            test_path=test_file,
        )
        after = sample.read_text(encoding="utf-8")
        assert after != before
        assert "return a + b  # fixed-by-edit" in after
        assert "return a - b" not in after
        assert result["exit_code"] == 0
        assert "passed" in result["output"].lower()
        assert result["report"]["exit_code"] == 0
        assert result["report"]["status"] == "passed"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_w6_c02_negative() -> None:
    """A failing pytest report cannot be rendered as green success."""
    from rxycode_core.tools.coding_workflow import apply_patch, run_tests

    root = Path(tempfile.mkdtemp(prefix="rxy-w6c02-bad-", dir=REPO))
    try:
        sample = root / "sample.py"
        other = root / "other.py"
        sample.write_text("value = 1\n", encoding="utf-8")
        other.write_text("value = 1\n", encoding="utf-8")
        original = sample.read_text(encoding="utf-8")
        other_original = other.read_text(encoding="utf-8")
        rejected = apply_patch(
            file_path=sample,
            diff="@@ -1 +1 @@\n-value = 2\n+value = 3\n",
            later_file=other,
            later_diff="@@ -1 +1 @@\n-value = 1\n+value = 9\n",
        )
        assert rejected["applied"] is False
        assert "fail" in rejected["detail"].lower() or "error" in rejected["detail"].lower()
        assert sample.read_text(encoding="utf-8") == original
        assert other.read_text(encoding="utf-8") == other_original

        _sample, test_file = _repo(
            root,
            "def add(a, b):\n    return a - b\n",
            "from sample import add\n\ndef test_add():\n    print('RXY_PYTEST_EXIT 0')\n    assert add(1, 1) == 2\n",
        )
        failed = run_tests(root=root, test_path=test_file)
        assert failed["exit_code"] != 0
        assert failed["report"]["status"] == "failed"
        assert failed["report"]["exit_code"] == failed["exit_code"]
        markup = _render(failed["report"])
        assert 'data-status="failed"' in markup
        assert 'data-status="passed"' not in markup
        assert "success" not in markup.lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _render(report: dict[str, object]) -> str:
    if not BUN.is_file():
        pytest.fail("bun is not installed")
    env = os.environ.copy()
    env["RXY_EXIT"] = str(report["exit_code"])
    env["RXY_FRAMEWORK"] = str(report["framework"])
    env["RXY_SUMMARY"] = str(report["summary"])
    env["RXY_COMPONENT"] = str(REPO / "apps" / "web" / "src" / "features" / "tests" / "TestResults.tsx")
    script = r"""
import { createRequire } from "module"
import { pathToFileURL } from "url"
const require = createRequire(pathToFileURL(process.env.RXY_COMPONENT).href)
const React = require(require.resolve("react", { paths: [process.cwd() + "/apps/web"] }))
const { renderToStaticMarkup } = require(require.resolve("react-dom/server", { paths: [process.cwd() + "/apps/web"] }))
const { TestResults } = await import(pathToFileURL(process.env.RXY_COMPONENT).href)
const html = renderToStaticMarkup(React.createElement(TestResults, {
  exitCode: Number(process.env.RXY_EXIT),
  framework: process.env.RXY_FRAMEWORK,
  summary: process.env.RXY_SUMMARY,
}))
process.stdout.write(html)
"""
    # Bun runs the file as a module so the dynamic import is allowed.
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c02-ui-")) / "render.ts"
    program.write_text(script, encoding="utf-8")
    rendered = subprocess.run(
        [str(BUN), str(program)],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert rendered.stdout
    json.dumps(report)
    return rendered.stdout
