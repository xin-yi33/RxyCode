"""Verify no shell leaks after a session-like lifecycle.

Note: ``acquire_shell`` is lazy -- it registers the identity but does NOT spawn
the process until the first command (that is the "nothing starts before the
first command" requirement).  So these tests call ``ensure_started()`` before
asserting on ``active_identities()``, which reports only live processes.
"""

from __future__ import annotations

import os

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

pytestmark = pytest.mark.asyncio


async def test_acquire_is_lazy_then_spawns():
    await ps.release_all()
    shell = await ps.acquire_shell(identity="lazy", cwd=os.getcwd())
    # Registered but not spawned yet.  ``active_identities`` reports registered
    # shells -- that is what makes one identity mean one shell under concurrent
    # first use; ``started_identities`` reports live processes only.
    assert ps.active_identities() == ["lazy"]
    assert ps.started_identities() == []
    assert shell.pid is None
    await shell.ensure_started()
    assert ps.started_identities() == ["lazy"]
    assert shell.pid is not None
    await ps.release_all()


async def test_no_leak_after_release_all():
    await ps.release_all()
    for i in range(3):
        shell = await ps.acquire_shell(identity=f"leak-{i}", cwd=os.getcwd())
        await shell.ensure_started()
    assert len(ps.active_identities()) == 3

    released = await ps.release_all()
    assert released == 3
    assert ps.active_identities() == []
    assert ps._SHELLS == {}


async def test_release_one_leaves_others():
    await ps.release_all()
    a = await ps.acquire_shell(identity="keep-a", cwd=os.getcwd())
    b = await ps.acquire_shell(identity="keep-b", cwd=os.getcwd())
    await a.ensure_started()
    await b.ensure_started()
    assert sorted(ps.active_identities()) == ["keep-a", "keep-b"]

    await ps.release_shell("keep-a")
    assert ps.active_identities() == ["keep-b"]
    await ps.release_all()


async def test_dead_shell_is_not_reported_active():
    shell = await ps.acquire_shell(identity="dead-check", cwd=os.getcwd())
    await shell.ensure_started()
    assert ps.active_identities() == ["dead-check"]
    await shell.close()
    assert ps.active_identities() == []
    await ps.release_all()
