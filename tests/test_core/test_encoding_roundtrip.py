"""Verify Chinese round-trip actually matches, not just "no exception"."""

from __future__ import annotations

import asyncio
import os

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps


@pytest.mark.asyncio
async def test_chinese_exact():
    await ps.release_all()
    sh = await ps.acquire_shell(identity="cn", cwd=os.getcwd())
    try:
        expected = "中文测试"
        r = await sh.run(f"Write-Output '{expected}'", timeout=30)
        print(f"\nEXPECTED={expected!r}")
        print(f"ACTUAL  ={r.stdout.strip()!r}")
        print(f"REPR    ={r.stdout.encode('utf-8', errors='replace')!r}")
        assert expected in r.stdout, f"got {r.stdout.strip()!r}"
    finally:
        await ps.release_all()


@pytest.mark.asyncio
async def test_unicode_input_survives():
    """A command containing non-ASCII must reach PowerShell intact."""
    await ps.release_all()
    sh = await ps.acquire_shell(identity="cn2", cwd=os.getcwd())
    try:
        marker = "标记"
        r = await sh.run(f"Write-Output '前缀{marker}后缀'", timeout=30)
        print(f"\nACTUAL={r.stdout.strip()!r}")
        assert f"前缀{marker}后缀" in r.stdout
    finally:
        await ps.release_all()
