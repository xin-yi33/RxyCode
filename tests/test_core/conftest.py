"""Automatic managed-shell cleanup for tests in this package.

The managed-shell registry is process-global and every shell owns a real OS
process plus reader tasks.  Without a release after each test, a few thousand
tests exhaust threads ("can't start new thread").  This fixture is scoped to
``tests/test_core`` so it cannot affect unrelated suites.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reap_managed_shells():
    """Kill and forget any shell left behind by a test, then continue."""
    yield
    try:
        from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
    except Exception:
        return
    for shell in list(ps._SHELLS.values()):
        try:
            process = shell._process
            shell._closed = True
            shell._process = None
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
        except Exception:
            pass
    ps._SHELLS.clear()
