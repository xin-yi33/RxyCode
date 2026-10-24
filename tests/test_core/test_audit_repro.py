"""Reproduce every audit finding against the CURRENT code.

Prints PASS/FAIL per claim. Run with pytest so the checkout-local package
binding in conftest.py is applied:

    python -m pytest tests/test_core/test_audit_repro.py -q -s
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


def show(claim: str, reproduced: bool, detail: str = "") -> None:
    tag = "REPRODUCED" if reproduced else "not reproduced"
    print(f"  [{tag}] {claim}" + (f" :: {detail}" if detail else ""))


async def test_p1_exit_code_leaks_from_previous_command():
    await ps.release_all()
    sh = await ps.acquire_shell(identity="rc-leak", cwd=os.getcwd())
    try:
        if WINDOWS:
            first = await sh.run("cmd /c exit 7", timeout=30)
            second = await sh.run("Write-Output ok", timeout=30)
        else:
            # Bare `exit 7` would kill the persistent shell itself; a
            # subshell produces the failing rc while the shell lives on.
            first = await sh.run("( exit 7 )", timeout=30)
            second = await sh.run("echo ok", timeout=30)
        leaked = second.exit_code not in (0,)
        show(
            "exit code carries over from the previous command",
            leaked,
            f"first={first.exit_code} second={second.exit_code}",
        )
    finally:
        await ps.release_all()


async def test_p1_write_error_reports_success():
    await ps.release_all()
    sh = await ps.acquire_shell(identity="write-error", cwd=os.getcwd())
    try:
        if WINDOWS:
            r = await sh.run("Write-Error 'boom'; Write-Output done", timeout=30)
            ok = r.exit_code == 0
            show("Write-Error reported as success", ok, f"rc={r.exit_code}")
    finally:
        await ps.release_all()


async def test_p1_invalid_workdir_still_runs_command(tmp_path: Path):
    await ps.release_all()
    sh = await ps.acquire_shell(identity="bad-workdir", cwd=os.getcwd())
    marker = tmp_path / "RAN.txt"
    bad = tmp_path / "does-not-exist"
    try:
        if WINDOWS:
            cmd = f"Set-Content -LiteralPath '{marker}' -Value ran"
        else:
            cmd = f"touch '{marker}'"
        r = await sh.run(cmd, timeout=30, workdir=str(bad))
        show(
            "command runs even though workdir does not exist",
            marker.exists(),
            f"rc={r.exit_code} marker_exists={marker.exists()}",
        )
    finally:
        await ps.release_all()


async def test_p1_output_without_trailing_newline_hangs():
    await ps.release_all()
    sh = await ps.acquire_shell(identity="no-newline", cwd=os.getcwd())
    try:
        started = time.perf_counter()
        try:
            if WINDOWS:
                await sh.run("Write-Host -NoNewline 'partial'", timeout=6)
                timed_out = False
            else:
                await sh.run("printf 'partial'", timeout=6)
                timed_out = False
        except ps.ShellLostError:
            timed_out = True
        elapsed = time.perf_counter() - started
        show(
            "output without trailing newline makes the command hang",
            timed_out,
            f"elapsed={elapsed:.1f}s",
        )
    finally:
        await ps.release_all()


async def test_p1_very_long_single_line():
    await ps.release_all()
    sh = await ps.acquire_shell(identity="long-line", cwd=os.getcwd())
    try:
        if WINDOWS:
            cmd = "Write-Output ('A' * 70000)"
        else:
            cmd = "printf 'A%.0s' $(seq 1 70000); echo"
        error = None
        try:
            await sh.run(cmd, timeout=30)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        show("70k single line breaks the reader", error is not None, error or "no error")
    finally:
        await ps.release_all()


async def test_p1_first_concurrent_call_creates_two_shells():
    await ps.release_all()
    results = await asyncio.gather(
        ps.acquire_shell(identity="race", cwd=os.getcwd()),
        ps.acquire_shell(identity="race", cwd=os.getcwd()),
    )
    same = results[0] is results[1]
    show(
        "concurrent first acquire creates two shells for one identity",
        not same,
        f"same_object={same}",
    )
    for shell in results:
        await shell.close()
    await ps.release_all()


async def test_p1_cancel_leaves_child_process_tree():
    """A cancelled command must not leave its descendants running."""
    await ps.release_all()
    sh = await ps.acquire_shell(identity="cancel-tree", cwd=os.getcwd())
    marker = Path(os.getcwd()) / "_cancel_probe_marker.txt"
    marker.unlink(missing_ok=True)
    try:
        if WINDOWS:
            # Start a detached python child that writes the marker after 4s.
            code = (
                "import time,pathlib;time.sleep(4);"
                f"pathlib.Path(r'{marker}').write_text('alive')"
            )
            task = asyncio.create_task(
                sh.run(f"Start-Process python -ArgumentList '-c','{code}'", timeout=60)
            )
        else:
            code = (
                "import time,pathlib;time.sleep(4);"
                f"pathlib.Path(r'{marker}').write_text('alive')"
            )
            task = asyncio.create_task(
                sh.run(f"python -c \"{code}\" &", timeout=60)
            )
        await asyncio.sleep(1.0)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await asyncio.sleep(5.0)
        show(
            "cancelled command leaves a descendant running",
            marker.exists(),
            f"marker_created_after_cancel={marker.exists()}",
        )
    finally:
        marker.unlink(missing_ok=True)
        await ps.release_all()


async def test_p2_chinese_output_encoding():
    await ps.release_all()
    sh = await ps.acquire_shell(identity="encoding", cwd=os.getcwd())
    try:
        if WINDOWS:
            r = await sh.run("Write-Output '中文测试'", timeout=30)
        else:
            r = await sh.run("echo '中文测试'", timeout=30)
        broken = "中文测试" not in r.stdout
        show("Chinese output is garbled", broken, repr(r.stdout.strip()[:40]))
    finally:
        await ps.release_all()
