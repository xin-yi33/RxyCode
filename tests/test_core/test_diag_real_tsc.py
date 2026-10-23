"""Real-toolchain TS checks against the repository's actual tsc.

The Bun-provided ``tsc.exe`` only works from inside its own node_modules
(it is a Bun bin shim), so these tests create a scratch project INSIDE
``frontend/opentui-app`` and point the checker at it.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

pytestmark = pytest.mark.asyncio

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "frontend" / "opentui-app"
TSC = APP / "node_modules" / ".bin" / "tsc.exe"
NODE = APP / "node_modules" / ".bin" / "tsc"


def _toolchain_available() -> bool:
    return TSC.exists() or NODE.exists()


TSCONFIG = {
    "compilerOptions": {
        "target": "ES2020",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "lib": ["ES2020", "DOM"],
        "strict": True,
        "jsx": "react-jsx",
        "noEmit": True,
        "skipLibCheck": True,
        "allowJs": False,
    }
}


@pytest.fixture()
def scratch_project():
    """A throwaway project dir inside the app so the Bun shim still resolves."""
    if not _toolchain_available():
        pytest.skip("repo tsc not installed")
    name = f"_diagcheck_{uuid.uuid4().hex[:8]}"
    root = APP / name
    root.mkdir()
    (root / "tsconfig.json").write_text(json.dumps(TSCONFIG, indent=2), encoding="utf-8")
    # The checker resolves node tools relative to the project root.
    bin_dir = root / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    try:
        yield root, bin_dir
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _link_tsc(bin_dir: Path) -> Path:
    """Expose tsc at <project>/node_modules/.bin without copying the shim."""
    import os

    name = "tsc.cmd" if os.name == "nt" else "tsc"
    link = bin_dir / name
    if os.name == "nt":
        # A .cmd wrapper that calls the real binary in place.
        link.write_text(f'@echo off\r\n"{TSC}" %*\r\n', encoding="utf-8")
    else:
        link.write_text(f'#!/bin/sh\nexec "{NODE}" "$@"\n', encoding="utf-8")
        link.chmod(0o755)
    return link


@pytest.mark.skipif(not _toolchain_available(), reason="repo tsc not installed")
async def test_valid_tsx_is_not_flagged(scratch_project):
    root, bin_dir = scratch_project
    _link_tsc(bin_dir)
    source = "export const A = () => <div>hi</div>;\n"
    file = root / "comp.tsx"
    file.write_text(source, encoding="utf-8")

    report = await diag.diagnose(file, source)
    print(f"\n  status={report.status} checker={report.checker} note={report.note!r}")
    for issue in report.issues[:3]:
        print(f"    {issue.code}: {issue.message[:110]}")
    assert report.status != "problems", (
        f"valid TSX flagged: {[i.message[:80] for i in report.issues]}"
    )


@pytest.mark.skipif(not _toolchain_available(), reason="repo tsc not installed")
async def test_real_type_error_detected_with_position(scratch_project):
    root, bin_dir = scratch_project
    _link_tsc(bin_dir)
    source = "export const n: number = 'not a number';\n"
    file = root / "bad.ts"
    file.write_text(source, encoding="utf-8")

    report = await diag.diagnose(file, source)
    print(f"\n  status={report.status} issues={len(report.issues)}")
    for issue in report.issues[:3]:
        print(f"    {issue.code} line={issue.line} {issue.message[:110]}")
    assert report.status == "problems"
    assert any(i.code.startswith("TS") for i in report.issues)


@pytest.mark.skipif(not _toolchain_available(), reason="repo tsc not installed")
async def test_other_files_errors_not_attributed(scratch_project):
    """Only the checked file's diagnostics belong in its report."""
    root, bin_dir = scratch_project
    _link_tsc(bin_dir)
    (root / "other.ts").write_text(
        "export const x: number = 'wrong';\n", encoding="utf-8"
    )
    good = "export const ok: number = 1;\n"
    file = root / "good.ts"
    file.write_text(good, encoding="utf-8")

    report = await diag.diagnose(file, good)
    print(f"\n  status={report.status} issues={len(report.issues)}")
    for issue in report.issues[:3]:
        print(f"    {issue.code} {issue.message[:110]}")
    # The neighbouring file is broken, but THIS file is fine.
    assert report.status != "problems"


@pytest.mark.skipif(not _toolchain_available(), reason="repo tsc not installed")
async def test_no_tsconfig_is_unavailable(tmp_path: Path):
    """Without a tsconfig we must NOT invent compiler options."""
    source = "export const x: number = 1;\n"
    file = tmp_path / "a.ts"
    file.write_text(source, encoding="utf-8")
    report = await diag.diagnose(file, source)
    print(f"\n  status={report.status} note={report.note!r}")
    # Outside a TS project there is no local tsc either, so the honest answer
    # is "unavailable"; inside one it is specifically "no tsconfig".
    assert report.status == "unavailable"
    assert report.ok is False
