"""RxyCode evaluation harness (阶段三).

Real-LLM evaluation for the LangGraph pipeline
(goal_planner → decomposer → executor → validator → synthesizer).

Design stitched from (移植设计，不 vendoring 代码):
- SWE-bench harness (https://github.com/swe-bench/SWE-bench):
  task definition → run → verify flow; per-instance structured result
  records (passed / timing / cost) written as JSON.
- Terminal-Bench task schema: task directory + instruction + check
  script/assertions; here flattened into a single YAML file per task
  (setup fixture files + checks list).
- OpenHands evaluation/ bench runner structure: a serial run loop with
  per-task isolation, result collection and a separate report step.
- OpenAI evals LLM-as-judge scoring template pattern: fixed rubric
  prompt, JSON output, dimension scores.

This package runs REAL LLM calls and is therefore kept OUT of the
pytest suite. Run it explicitly:

    python -m evals.run --tag myrun
    python -m evals.run --dry
    python -m evals.report --tag myrun
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"


def _bind_checkout() -> None:
    """Resolve ``RxyCode.RxyCode1_1_0`` to this worktree, not the editable install.

    ``pip install -e`` maps the canonical package at the main working tree.
    ``python -m evals.cli`` from a quality worktree would otherwise score the
    wrong ``AgentV2``. Mirror ``tests/conftest.py`` so evals and pytest agree.
    """
    import os
    import sys
    import types
    from pathlib import Path

    checkout = Path(__file__).resolve().parent.parent
    os.environ["RXYCODE_CHECKOUT_ROOT"] = str(checkout)
    os.environ["_RXYCODE_TEST_CHECKOUT"] = str(checkout)
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if type(finder).__name__ != "_EditableFinder"
    ]
    pkg_root = checkout / "_package_root"
    for entry in (pkg_root, checkout):
        text = str(entry)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    init = checkout / "__init__.py"
    existing = sys.modules.get("RxyCode.RxyCode1_1_0")
    existing_file = getattr(existing, "__file__", None) if existing is not None else None
    bound = False
    if existing_file:
        try:
            bound = Path(existing_file).resolve().parent == checkout
        except OSError:
            bound = False
    if bound:
        return
    parent = sys.modules.get("RxyCode")
    if parent is None:
        parent = types.ModuleType("RxyCode")
        sys.modules["RxyCode"] = parent
    module = types.ModuleType("RxyCode.RxyCode1_1_0")
    module.__file__ = str(init)
    module.__path__ = [str(checkout)]
    module.__package__ = "RxyCode.RxyCode1_1_0"
    sys.modules["RxyCode.RxyCode1_1_0"] = module
    parent.RxyCode1_1_0 = module
    if init.exists():
        source = init.read_text(encoding="utf-8-sig")
        exec(compile(source, str(init), "exec"), module.__dict__)
    unify = getattr(module, "unify_bare_package_aliases", None)
    if callable(unify):
        unify()
