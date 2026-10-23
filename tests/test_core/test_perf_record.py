"""Recorded performance measurements for the 2026-10-23 CLI work.

Run with: python -m pytest tests/test_core/test_perf_record.py -q -s
Numbers are printed, not asserted (machine-dependent).
"""

from __future__ import annotations

import asyncio
import os
import statistics
import tempfile
import time
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.tools.bash import run_bash_async
from RxyCode.RxyCode1_1_0.tools.edit import edit_file_async
from RxyCode.RxyCode1_1_0.tools.write import write_file_async
from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

pytestmark = pytest.mark.asyncio

N = 8


def _stat(label: str, samples: list[float]) -> None:
    med = statistics.median(samples) * 1000
    lo, hi = min(samples) * 1000, max(samples) * 1000
    print(f"{label:<38} median={med:8.1f}ms  range={lo:.1f}-{hi:.1f}ms  n={len(samples)}")


async def test_record_perf():
    cmd = "Write-Output x" if os.name == "nt" else "echo x"

    # Pin a private session so a binding left by another test in the same
    # process cannot make this measurement reuse that test's shell.
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
    )

    await ps.release_all()
    token = bind_session("perf-record")
    try:
        await _measure(cmd)
    finally:
        reset_session_binding(token)
        await ps.release_all()


async def _measure(cmd: str) -> None:
    oneshot = []
    for _ in range(N):
        t = time.perf_counter()
        await shell_executor.execute_async(cmd, "", 60)
        oneshot.append(time.perf_counter() - t)

    t = time.perf_counter()
    await run_bash_async(cmd, "", "", 60)
    first = time.perf_counter() - t

    reused = []
    for _ in range(N):
        t = time.perf_counter()
        await run_bash_async(cmd, "", "", 60)
        reused.append(time.perf_counter() - t)

    print("\n=== bash command latency ===")
    _stat("one-shot (pre-change)", oneshot)
    print(f"{'managed first call (spawn incl.)':<38} {first * 1000:8.1f}ms")
    _stat("managed reused (post-change)", reused)

    a = await ps.acquire_shell(identity="perf-a", cwd=os.getcwd())
    b = await ps.acquire_shell(identity="perf-b", cwd=os.getcwd())
    t = time.perf_counter()
    await asyncio.gather(
        a.run("Start-Sleep -Milliseconds 700; Write-Output a", timeout=30),
        b.run("Start-Sleep -Milliseconds 700; Write-Output b", timeout=30),
    )
    parallel = (time.perf_counter() - t) * 1000
    print(f"\ntwo isolated sessions in parallel: {parallel:.0f}ms (serial ~1400ms)")
    print(f"live shells while 2 sessions active: {len(ps.active_identities())}")
    await ps.release_all()

    tmp = Path(tempfile.mkdtemp())
    py_w, py_e, js_w = [], [], []
    for i in range(N):
        p = tmp / f"b{i}.py"
        t = time.perf_counter()
        await write_file_async(str(p), "x = 1\n")
        py_w.append(time.perf_counter() - t)
        t = time.perf_counter()
        await edit_file_async(str(p), "x = 1", "x = 2")
        py_e.append(time.perf_counter() - t)
        q = tmp / f"b{i}.js"
        t = time.perf_counter()
        await write_file_async(str(q), "const a = 1;\n")
        js_w.append(time.perf_counter() - t)

    print("\n=== write/edit incl. diagnostics ===")
    _stat("write .py (compile+ruff)", py_w)
    _stat("edit .py (compile+ruff)", py_e)
    _stat("write .js (node --check)", js_w)

    s = await ps.acquire_shell(identity="perf-cancel", cwd=os.getcwd())
    task = asyncio.create_task(s.run("Start-Sleep -Seconds 20", timeout=60))
    await asyncio.sleep(0.5)
    t = time.perf_counter()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    cancel_ms = (time.perf_counter() - t) * 1000
    await ps.release_all()
    print(f"\ncancel -> returned: {cancel_ms:.0f}ms")
    print(f"shells after release: {len(ps.active_identities())}")

    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
