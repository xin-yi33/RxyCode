"""Plan-tree checks run only when the local planning docs are present.

``docs/plans/`` is gitignored, so a published checkout does not contain it.
Skip only those tests. A module-level pytest.skip aborts every suite that
collects the tests tree, including serial and regression.
"""

from pathlib import Path

import pytest

_PLAN = Path(__file__).resolve().parents[2] / "docs" / "plans" / "opus5-plan"
_DOCS = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    del config
    if _PLAN.is_dir():
        return
    skip = pytest.mark.skip(reason="docs/plans is not part of the published checkout")
    for item in items:
        try:
            path = Path(str(item.fspath))
        except TypeError:
            continue
        if path.is_relative_to(_DOCS):
            item.add_marker(skip)
