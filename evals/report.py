"""Markdown report generation + baseline diff for eval runs.

Adapted from OpenHands (MIT) evaluation report pattern.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .runner import SuiteReport, TaskResult, RESULTS_DIR

#: Directory for baseline snapshots.
BASELINES_DIR = Path(__file__).parent / "baselines"


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------


def generate_markdown(report: SuiteReport) -> str:
    """Render a :class:`SuiteReport` as a human-readable markdown string."""
    s = report.compute_summary()

    lines: list[str] = [
        "# Eval Suite Report",
        "",
        "## Summary",
        "",
        f"- **Pass rate**: {s['passed']}/{s['total_tasks']} "
        f"({s['pass_rate']:.1%})",
        f"- **Mean judge score**: {s.get('mean_judge_score', 0):.2f}/5",
        f"- **Total tokens**: {s['total_tokens']:,}",
        f"- **Total duration**: {s['total_duration_s']:.1f}s",
        "",
    ]

    # Per-category breakdown.
    by_cat = s.get("by_category", {})
    if by_cat:
        lines += [
            "## By Category",
            "",
            "| Category | Passed | Total | Pass Rate |",
            "|----------|--------|-------|-----------|",
        ]
        for cat in sorted(by_cat):
            d = by_cat[cat]
            lines.append(
                f"| {cat} | {d['passed']} | {d['total']} | "
                f"{d['pass_rate']:.1%} |"
            )
        lines.append("")

    # Per-task table.
    lines += [
        "## Task Results",
        "",
        "| Task ID | Category | Status | Duration | Tokens | Judge | Error |",
        "|---------|----------|--------|----------|--------|-------|-------|",
    ]
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        judge = (
            f"{r.judge_score.get('mean', 0):.1f}"
            if r.judge_score and r.judge_score.get("ok")
            else "N/A"
        )
        tokens = r.token_usage.get("total", 0)
        err = (r.error[:50] + "...") if len(r.error) > 50 else r.error
        # Escape pipe characters for markdown table safety.
        err = err.replace("|", "\\|")
        lines.append(
            f"| {r.task_id} | {r.category} | {status} | "
            f"{r.duration_s:.1f}s | {tokens} | {judge} | {err} |"
        )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baseline persistence
# ---------------------------------------------------------------------------


def save_baseline(report: SuiteReport, name: str) -> Path:
    """Save *report* as a baseline named *name* under ``evals/baselines/``."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINES_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    return path


def load_baseline(name: str) -> dict:
    """Load a baseline snapshot by name."""
    path = BASELINES_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"baseline not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_baselines() -> list[str]:
    """Return the names of all saved baselines (without extension)."""
    if not BASELINES_DIR.is_dir():
        return []
    return sorted(p.stem for p in BASELINES_DIR.glob("*.json"))


# ---------------------------------------------------------------------------
# Baseline diff
# ---------------------------------------------------------------------------


def diff_baseline(current: SuiteReport, baseline_name: str) -> str:
    """Compare *current* against a saved baseline.

    Produces a markdown string highlighting:
    - Summary metric deltas (pass rate, tokens, duration, judge score).
    - Per-task regressions (previously PASS, now FAIL).
    - Per-task improvements (previously FAIL, now PASS).
    """
    baseline = load_baseline(baseline_name)

    cur_s = current.summary
    base_s = baseline.get("summary", {})

    lines: list[str] = [
        f"# Baseline Diff: {baseline_name}",
        "",
        "## Summary Changes",
        "",
        "| Metric | Baseline | Current | Delta |",
        "|--------|----------|---------|-------|",
    ]

    metrics: list[tuple[str, str, str]] = [
        ("pass_rate", "Pass Rate", "pct"),
        ("mean_judge_score", "Mean Judge", "float"),
        ("total_tokens", "Tokens", "int"),
        ("total_duration_s", "Duration", "dur"),
    ]

    for key, label, fmt in metrics:
        b = base_s.get(key, 0)
        c = cur_s.get(key, 0)
        delta = c - b
        sign = "+" if delta >= 0 else ""

        if fmt == "pct":
            lines.append(
                f"| {label} | {b:.1%} | {c:.1%} | {sign}{delta:+.1%} |"
            )
        elif fmt == "int":
            lines.append(
                f"| {label} | {b:,} | {c:,} | {sign}{delta:+,} |"
            )
        elif fmt == "dur":
            lines.append(
                f"| {label} | {b:.1f}s | {c:.1f}s | {sign}{delta:+.1f}s |"
            )
        else:
            lines.append(
                f"| {label} | {b:.2f} | {c:.2f} | {sign}{delta:+.2f} |"
            )

    lines.append("")

    # Per-task regressions & improvements.
    base_results = {r["task_id"]: r for r in baseline.get("results", [])}
    cur_results = {r.task_id: r for r in current.results}

    regressions: list[str] = []
    improvements: list[str] = []

    for task_id, cur_r in cur_results.items():
        base_r = base_results.get(task_id)
        if base_r is None:
            continue
        if base_r["passed"] and not cur_r.passed:
            regressions.append(task_id)
        elif not base_r["passed"] and cur_r.passed:
            improvements.append(task_id)

    if regressions:
        lines += ["## Regressions", ""]
        for tid in regressions:
            lines.append(f"- **{tid}**: PASS -> FAIL")
        lines.append("")

    if improvements:
        lines += ["## Improvements", ""]
        for tid in improvements:
            lines.append(f"- **{tid}**: FAIL -> PASS")
        lines.append("")

    if not regressions and not improvements:
        lines += ["No per-task status changes.", ""]

    return "\n".join(lines)
