"""layer=unit bash CPU watchdog: probe at checkpoints, idle yield to the model."""
from __future__ import annotations

import sys

import pytest

from RxyCode.RxyCode1_1_0.utils.shell import (
    ShellExecutor,
    sample_process_tree,
    watchdog_is_busy,
)


def test_python_c_uses_this_interpreter_not_powershell():
    from RxyCode.RxyCode1_1_0.utils.shell import direct_python_c_argv

    argv = direct_python_c_argv(
        "python -c \"from e14_tiny import add; assert add(2, 3) == 5; print('E14_OK')\""
    )
    assert argv is not None
    assert argv[0] == sys.executable
    assert argv[1] == "-c"
    assert "E14_OK" in argv[2]
    assert direct_python_c_argv("git status") is None


def test_sample_process_tree_self():
    cpu, rss, live, io_bytes = sample_process_tree(None)
    assert (cpu, rss, live, io_bytes) == (0.0, 0, 0, 0)
    sample_process_tree(__import__("os").getpid())
    cpu, rss, live, io_bytes = sample_process_tree(__import__("os").getpid())
    assert live >= 1
    assert rss >= 0
    assert io_bytes >= 0


def test_watchdog_ignores_startup_io():
    assert watchdog_is_busy(
        cpu=0.0,
        rss=13_000_000,
        last_rss=13_000_000,
        io_bytes=574 * 1024,
        last_io=0,
        live=1,
        last_live=1,
    ) is False
    assert watchdog_is_busy(
        cpu=0.0,
        rss=13_000_000,
        last_rss=12_700_000,
        io_bytes=1000,
        last_io=1000,
        live=1,
        last_live=1,
    ) is False


def test_watchdog_treats_cpu_or_io_as_busy():
    assert watchdog_is_busy(
        cpu=12.0,
        rss=13_000_000,
        last_rss=13_000_000,
        io_bytes=1000,
        last_io=1000,
        live=1,
        last_live=1,
    ) is True
    assert watchdog_is_busy(
        cpu=0.0,
        rss=13_000_000,
        last_rss=13_000_000,
        io_bytes=3_000_000,
        last_io=1000,
        live=1,
        last_live=1,
    ) is True
    assert watchdog_is_busy(
        cpu=80.0,
        rss=13_000_000,
        last_rss=13_000_000,
        io_bytes=1000,
        last_io=1000,
        live=1,
        last_live=1,
        prev_cpu=0.0,
    ) is False
    assert watchdog_is_busy(
        cpu=80.0,
        rss=13_000_000,
        last_rss=13_000_000,
        io_bytes=1000,
        last_io=1000,
        live=1,
        last_live=1,
        prev_cpu=40.0,
    ) is True


@pytest.mark.asyncio
async def test_idle_sleep_is_stopped_after_checkpoint():
    executor = ShellExecutor()
    executor.watchdog_checkpoints = (0.4,)
    executor.watchdog_idle_kill_after = 0.4
    executor.watchdog_observe_seconds = 0.05
    result = await executor.execute_argv_async(
        [sys.executable, "-c", "import time; time.sleep(12)"],
        timeout=6,
    )
    assert result["success"] is False
    assert "watchdog idle" in result["stderr"]


@pytest.mark.asyncio
async def test_busy_loop_is_not_idle_killed():
    executor = ShellExecutor()
    executor.watchdog_checkpoints = (0.35,)
    executor.watchdog_idle_kill_after = 0.35
    executor.watchdog_observe_seconds = 0.05
    result = await executor.execute_argv_async(
        [sys.executable, "-c", "while True: pass"],
        timeout=1.2,
    )
    assert result["success"] is False
    assert "watchdog idle" not in result["stderr"]
    assert "timeout after" in result["stderr"]
