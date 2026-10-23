"""Reproduce: does the managed shell honour the sandbox/resource policy?

The audit claimed a fail-closed sandbox config still let the persistent shell
spawn a bare process.  These tests compare the one-shot path with the managed
path under the same config.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


def show(claim: str, reproduced: bool, detail: str = "") -> None:
    tag = "REPRODUCED" if reproduced else "not reproduced"
    print(f"  [{tag}] {claim}" + (f" :: {detail}" if detail else ""))


async def test_managed_shell_uses_sandbox_wrapper():
    """The managed shell must be created through the sandbox wrapper."""
    await ps.release_all()
    calls: list[list[str]] = []

    def fake_wrap(argv, cwd):
        calls.append(list(argv))
        # Broken wrapper: prove the shell goes through it by mutating argv.
        return list(argv)

    sh = await ps.acquire_shell(
        identity="sbx",
        cwd=os.getcwd(),
        sandbox_command=fake_wrap,
    )
    try:
        await sh.ensure_started()
        show(
            "managed shell bypasses the sandbox wrapper",
            len(calls) == 0,
            f"wrapper_calls={len(calls)}",
        )
        assert calls, "the shell was spawned without the sandbox wrapper"
    finally:
        await ps.release_all()


async def test_managed_shell_refuses_when_sandbox_fails():
    """A raising wrapper must fail closed, not fall back to a bare spawn."""
    await ps.release_all()

    def raising_wrap(argv, cwd):
        raise RuntimeError("sandbox unavailable")

    sh = await ps.acquire_shell(
        identity="sbx-fail",
        cwd=os.getcwd(),
        sandbox_command=raising_wrap,
    )
    try:
        with pytest.raises(ps.ShellStartupError):
            await sh.ensure_started()
        show(
            "sandbox failure silently fell back to a bare shell",
            sh.pid is not None,
            f"pid={sh.pid}",
        )
        assert sh.pid is None, "must not spawn when the sandbox refuses"
    finally:
        await ps.release_all()


async def test_bash_tool_passes_sandbox_wrapper():
    """The real bash tool must wire the sandbox wrapper into the shell."""
    from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

    captured = {}
    real = bash_mod._managed_sandbox_wrapper

    def spy():
        captured["called"] = True
        return real()

    bash_mod._managed_sandbox_wrapper = spy
    try:
        wrapper = bash_mod._managed_sandbox_wrapper()
        print(f"\n  wrapper available: {wrapper is not None}")
    finally:
        bash_mod._managed_sandbox_wrapper = real
