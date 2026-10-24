"""Cross-event-loop ownership for managed shells.

pytest-asyncio (and any second worker loop) gives each test its own loop.
A ManagedShell's subprocess transports bind to the loop that spawned them;
reusing one from a different loop previously died deep in ``stdout.read``
with "Future attached to a different loop" or "Event loop is closed".

Each test spawns its "foreign" shell inside a worker thread running its own
``asyncio.run`` — the only way to get a shell whose owner loop is genuinely
different (and dead) while the test loop stays alive.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

pytestmark = pytest.mark.asyncio

ECHO = "Write-Output ok" if os.name == "nt" else "echo ok"


def _spawn_on_own_loop(identity: str, holder: list) -> None:
    """Create a registered shell inside a throwaway event loop."""

    async def go() -> None:
        shell = await ps.acquire_shell(identity=identity, cwd=os.getcwd())
        holder.append(shell)
        await shell.run(ECHO, timeout=30)

    asyncio.run(go())


async def test_acquire_evicts_shell_owned_by_dead_loop():
    """A shell spawned on a closed loop must be discarded and respawned."""
    identity = "cross-loop-evict"
    await ps.release_all()
    await asyncio.to_thread(_spawn_on_own_loop, identity, [])

    # The registered shell belongs to the thread's now-closed loop.
    shell = await ps.acquire_shell(identity=identity, cwd=os.getcwd())
    try:
        result = await shell.run(ECHO, timeout=30)
        assert "ok" in result.stdout
    finally:
        await ps.release_all()


async def test_run_on_foreign_loop_raises_shell_lost():
    """Direct run() on another loop reports ShellLostError, not Future errors."""
    identity = "cross-loop-run"
    await ps.release_all()
    holder: list = []
    await asyncio.to_thread(_spawn_on_own_loop, identity, holder)

    foreign = holder[0]
    with pytest.raises(ps.ShellLostError):
        await foreign.run(ECHO, timeout=30)
    # The lost shell must be evictable: next acquire gets a fresh live shell.
    fresh = await ps.acquire_shell(identity=identity, cwd=os.getcwd())
    try:
        result = await fresh.run(ECHO, timeout=30)
        assert "ok" in result.stdout
    finally:
        await ps.release_all()


async def test_release_all_survives_foreign_loop_shells():
    """release_all() on a different loop must not raise."""
    identity = "cross-loop-release"
    await ps.release_all()
    await asyncio.to_thread(_spawn_on_own_loop, identity, [])

    # Called from this test's loop while the shell belongs to a dead one.
    await ps.release_all()
    assert identity not in ps._SHELLS
