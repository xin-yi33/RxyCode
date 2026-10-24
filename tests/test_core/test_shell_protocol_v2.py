"""Focused validation of the rewritten persistent shell protocol."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


async def _shell(identity: str = "proto", cwd: str | None = None):
    await ps.release_all()
    return await ps.acquire_shell(identity=identity, cwd=cwd or os.getcwd())


async def test_basic_output_and_exit():
    sh = await _shell()
    try:
        if WINDOWS:
            r = await sh.run("Write-Output hi", timeout=30)
        else:
            r = await sh.run("echo hi", timeout=30)
        print(f"  basic: rc={r.exit_code} out={r.stdout.strip()!r}")
        assert r.exit_code == 0
        assert "hi" in r.stdout
    finally:
        await ps.release_all()


async def test_exit_code_is_per_command():
    sh = await _shell()
    try:
        if WINDOWS:
            await sh.run("cmd /c exit 7", timeout=30)
            r = await sh.run("Write-Output ok", timeout=30)
        else:
            # A failing child command leaves the persistent shell alive;
            # bare `exit` deliberately destroys its state (covered separately).
            await sh.run("(exit 7)", timeout=30)
            r = await sh.run("echo ok", timeout=30)
        print(f"  rc after previous failure: {r.exit_code}")
        assert r.exit_code == 0, "stale exit code leaked from the previous command"
    finally:
        await ps.release_all()


async def test_write_error_is_not_success():
    sh = await _shell()
    try:
        if WINDOWS:
            r = await sh.run("Write-Error 'boom'", timeout=30)
            print(f"  Write-Error: rc={r.exit_code} err={r.stderr_errors[:80]!r}")
            # Either a non-zero rc or a captured error stream, never silent OK.
            assert r.exit_code != 0 or r.stderr_errors
    finally:
        await ps.release_all()


async def test_output_without_newline():
    sh = await _shell()
    try:
        if WINDOWS:
            r = await sh.run("Write-Host -NoNewline 'partial'", timeout=20)
        else:
            r = await sh.run("printf 'partial'", timeout=20)
        print(f"  no-newline: rc={r.exit_code} out={r.stdout.strip()!r}")
        assert "partial" in r.stdout
    finally:
        await ps.release_all()


async def test_long_single_line():
    sh = await _shell()
    try:
        if WINDOWS:
            r = await sh.run("Write-Output ('A' * 70000)", timeout=30)
        else:
            r = await sh.run("printf 'A%.0s' $(seq 1 70000); echo", timeout=30)
        print(f"  long line: rc={r.exit_code} len={len(r.stdout)}")
        assert len(r.stdout) > 60000
    finally:
        await ps.release_all()


async def test_multiline_function():
    sh = await _shell()
    try:
        if WINDOWS:
            cmd = "function f {\n  Write-Output a\n  Write-Output b\n}\nf"
        else:
            cmd = "f() {\n  echo a\n  echo b\n}\nf"
        r = await sh.run(cmd, timeout=30)
        print(f"  multiline fn: rc={r.exit_code} out={r.stdout.strip()!r}")
        assert "a" in r.stdout and "b" in r.stdout
    finally:
        await ps.release_all()


async def test_state_persists():
    sh = await _shell()
    try:
        if WINDOWS:
            await sh.run("$p = 'kept'", timeout=30)
            r = await sh.run("Write-Output $p", timeout=30)
        else:
            await sh.run("p=kept", timeout=30)
            r = await sh.run("echo $p", timeout=30)
        print(f"  state: {r.stdout.strip()!r}")
        assert "kept" in r.stdout
    finally:
        await ps.release_all()


async def test_invalid_workdir_blocks_command(tmp_path: Path):
    sh = await _shell()
    marker = tmp_path / "RAN.txt"
    try:
        if WINDOWS:
            cmd = f"Set-Content -LiteralPath '{marker}' -Value ran"
        else:
            cmd = f"touch '{marker}'"
        r = await sh.run(cmd, timeout=30, workdir=str(tmp_path / "nope"))
        print(f"  bad workdir: rc={r.exit_code} err={r.error} marker={marker.exists()}")
        assert not marker.exists(), "command ran despite a failed workdir"
        assert r.exit_code == 126
    finally:
        await ps.release_all()


async def test_workdir_restores_and_keeps_state(tmp_path: Path):
    sh = await _shell()
    try:
        if WINDOWS:
            await sh.run("$w = 'keep'", timeout=30)
            inside = await sh.run("Write-Output (Get-Location).Path", timeout=30,
                                  workdir=str(tmp_path))
            after = await sh.run("Write-Output (Get-Location).Path; Write-Output $w", timeout=30)
        else:
            await sh.run("w=keep", timeout=30)
            inside = await sh.run("pwd", timeout=30, workdir=str(tmp_path))
            after = await sh.run("pwd; echo $w", timeout=30)
        print(f"  workdir inside={inside.stdout.strip()!r} after={after.stdout.strip()!r}")
        assert str(tmp_path) in inside.stdout
        assert "keep" in after.stdout
    finally:
        await ps.release_all()


async def test_chinese_output():
    sh = await _shell()
    try:
        if WINDOWS:
            r = await sh.run("Write-Output '中文测试'", timeout=30)
        else:
            r = await sh.run("echo '中文测试'", timeout=30)
        print(f"  chinese: {r.stdout.strip()!r}")
        assert "中文测试" in r.stdout
    finally:
        await ps.release_all()


async def test_concurrent_first_acquire_single_instance():
    await ps.release_all()
    a, b = await asyncio.gather(
        ps.acquire_shell(identity="race2", cwd=os.getcwd()),
        ps.acquire_shell(identity="race2", cwd=os.getcwd()),
    )
    print(f"  same object: {a is b}")
    assert a is b
    await ps.release_all()
