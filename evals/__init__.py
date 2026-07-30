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

__all__ = ["__version__"]

__version__ = "0.1.0"
