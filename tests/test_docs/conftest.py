"""Plan-tree checks run only when the local planning docs are present.

``docs/plans/`` is gitignored, so a published checkout does not contain it.
"""

from pathlib import Path

import pytest

_PLAN = Path(__file__).resolve().parents[2] / "docs" / "plans" / "opus5-plan"
if not _PLAN.is_dir():
    pytest.skip(
        "docs/plans is not part of the published checkout",
        allow_module_level=True,
    )
