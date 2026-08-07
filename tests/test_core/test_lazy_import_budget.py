"""P7 acceptance: lazy import count must stay under budget in scoped packages."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.count_lazy_imports import P7_BUDGET, count_lazy_imports

REPO_ROOT = Path(__file__).resolve().parents[2]

# Ratchet milestone — lower toward P7_BUDGET (50) as batches land.
# Phase B added core/subagents/ with legitimate function-scoped imports
# (namespace isolation, lazy provider resolution); raised to 55.
P7_MILESTONE = 55


def test_lazy_import_count_under_p7_milestone() -> None:
    counts = count_lazy_imports(REPO_ROOT)
    total = sum(counts.values())
    top = counts.most_common(5)
    detail = ", ".join(f"{path}={count}" for path, count in top)
    assert total < P7_MILESTONE, (
        f"P7 lazy import milestone exceeded: {total} >= {P7_MILESTONE}; top: {detail}"
    )


def test_lazy_import_count_under_p7_final_budget() -> None:
    counts = count_lazy_imports(REPO_ROOT)
    total = sum(counts.values())
    assert total < P7_BUDGET, f"P7 final budget exceeded: {total} >= {P7_BUDGET}"


def test_core_package_imports_without_cycle() -> None:
    """Smoke-import core modules that P7 must keep acyclic."""
    import importlib

    modules = [
        "core.session",
        "core.graph",
        "core.agent_v2",
        "core.safety.audit",
        "core.safety.policy",
        "core.builtin_tool_registration",
    ]
    for name in modules:
        importlib.import_module(name)

