from __future__ import annotations

import pytest

from tests.e2e.phase_p.helpers import ART_DIR, dump_artifact

pytestmark = pytest.mark.e2e


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        ART_DIR.mkdir(parents=True, exist_ok=True)
        extra = getattr(item, "_phase_p_dump", {})
        dump_artifact(item.nodeid, **extra)
        print(f"\nE2E_FAIL id={item.name}")
        print(f"artifact={ART_DIR}/{item.nodeid}")
