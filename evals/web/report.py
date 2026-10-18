"""WEB-W7-C03 report: aggregates run.py results across cells and gates them.

Reads the JSON produced by ``evals/web/run.py`` (records + embedded or sibling
manifest), computes per-cell and overall statistics — success rate (failures
stay in the denominator; ``blocked`` records are excluded AND reported),
duration p50/p95 (nearest-rank), token and cost totals (Decimal-accurate) —
then applies the card's quality gate:

* the manifest must exist and pin ``taskset_sha256``;
* when ``--taskset`` is given, its hash must match the manifest;
* a covered task designed to fail (``expect == "fail"``) must never come back
  ``passed`` — that means the gate machinery is blind;
* if designed-fail tasks were covered, at least one record must actually be
  ``failed``/``error``;
* every declared cell must produce records — unless ``blocked_cells`` carries
  an honest reason (provider outage, database down);
* each non-blocked cell must attempt at least ``--min-tasks`` tasks
  (default 30: the full taskset);

and lists every cost row above the abnormal threshold instead of silently
averaging it away.

Standalone usage:

    python evals/web/report.py --results out.json [--manifest manifest.json] \
        [--taskset evals/web/taskset.jsonl] [--min-tasks 30] [--out report.md]

Exit code 0 when the gate passes, 1 with violations otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: A per-task billed amount above this is abnormal for the eval taskset and
#: must be surfaced, never averaged into silence.
ABNORMAL_COST_USD = Decimal("1.0")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_results(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError(f"{path}: results file must be an object with a 'records' list")
    return data


def load_manifest(
    results: dict[str, Any], *, path: Path | str | None = None
) -> dict[str, Any] | None:
    """Manifest lookup order: explicit --manifest, embedded copy, sibling file."""
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    embedded = results.get("manifest")
    if isinstance(embedded, dict) and embedded:
        return embedded
    ref = results.get("manifest_ref")
    if ref and results.get("_results_path"):
        candidate = Path(results["_results_path"]).parent / ref
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile; deterministic and dependency-free."""
    if not sorted_values:
        return 0.0
    rank = math.ceil(q / 100.0 * len(sorted_values)) - 1
    rank = min(max(rank, 0), len(sorted_values) - 1)
    return round(float(sorted_values[rank]), 3)


def _records_for_cell(records: Iterable[dict], cell: str | None) -> list[dict]:
    return [r for r in records if cell is None or r.get("cell") == cell]


def _stats(records: list[dict]) -> dict[str, Any]:
    by_status = Counter(str(r.get("status") or "error") for r in records)
    attempted = [r for r in records if r.get("status") != "blocked"]
    durations = sorted(float(r.get("duration_s") or 0.0) for r in attempted)
    tokens_in = sum(int((r.get("token_usage") or {}).get("input") or 0) for r in attempted)
    tokens_out = sum(int((r.get("token_usage") or {}).get("output") or 0) for r in attempted)
    tokens_total = sum(int((r.get("token_usage") or {}).get("total") or 0) for r in attempted)
    cost_amounts: list[Decimal] = []
    abnormal: list[dict[str, Any]] = []
    cost_sources: set[str] = set()
    for r in records:
        cost = r.get("cost") or {}
        amount = cost.get("amount")
        if amount in (None, ""):
            continue
        cost_sources.add(str(cost.get("source") or "unknown"))
        value = Decimal(str(amount))
        cost_amounts.append(value)
        if value > ABNORMAL_COST_USD:
            abnormal.append(
                {
                    "task_id": r.get("task_id"),
                    "cell": r.get("cell"),
                    "amount": str(value),
                    "currency": cost.get("currency", "USD"),
                    "source": cost.get("source"),
                }
            )
    attempted_n = len(attempted)
    return {
        "n": len(records),
        "attempted": attempted_n,
        "blocked": len(records) - attempted_n,
        "by_status": dict(by_status),
        "passed": int(by_status.get("passed", 0)),
        "failed": int(by_status.get("failed", 0)),
        "error": int(by_status.get("error", 0)),
        # Failures stay in the denominator; blocked tasks are excluded but
        # counted separately above. Unrounded — the fraction is the honest value.
        "success_rate": (
            by_status.get("passed", 0) / attempted_n if attempted_n else None
        ),
        "duration_s": {
            "p50": percentile(durations, 50),
            "p95": percentile(durations, 95),
            "total": round(sum(durations), 3),
        },
        "tokens": {
            "input": tokens_in,
            "output": tokens_out,
            "total": tokens_total,
            "mean_total": round(tokens_total / attempted_n, 1) if attempted_n else None,
        },
        "cost": {
            "total": str(sum(cost_amounts, Decimal(0))),
            "currency": "USD",
            "priced_records": len(cost_amounts),
            "sources": sorted(cost_sources),
            "abnormal": abnormal,
        },
        "designed_failures": [
            {
                "task_id": r.get("task_id"),
                "cell": r.get("cell"),
                "status": r.get("status"),
            }
            for r in attempted
            if r.get("expected_failure")
        ],
    }


def build_report(results: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    records = results.get("records") or []
    cells = results.get("cells") or sorted({r.get("cell") for r in records})
    manifest = manifest if manifest is not None else results.get("manifest") or {}
    per_cell = {cell: _stats(_records_for_cell(records, cell)) for cell in cells}
    return {
        "schema": "evals-web-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "taskset_sha256": manifest.get("taskset_sha256"),
        "code_commit": manifest.get("code_commit"),
        "model": manifest.get("model"),
        "price_version": manifest.get("price_version"),
        "mode_map": manifest.get("mode_map"),
        "cells": per_cell,
        "overall": _stats(list(records)),
        "blocked_cells": dict(results.get("blocked_cells") or {}),
        "abnormal_cost": [
            item for cell in cells for item in per_cell[cell]["cost"]["abnormal"]
        ],
    }


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def _expected_fail_ids(
    records: list[dict], taskset_path: Path | str | None
) -> set[str]:
    """Task ids covered by records that were designed to fail."""
    recorded_ids = {r.get("task_id") for r in records}
    if taskset_path:
        from evals.web.run import load_taskset

        designed = {
            t.task_id for t in load_taskset(taskset_path) if t.expect == "fail"
        }
        return designed & recorded_ids
    return {
        str(r.get("task_id"))
        for r in records
        if r.get("expect") == "fail" or r.get("expected_failure")
    }


def gate_report(
    results: dict[str, Any],
    *,
    manifest: dict[str, Any] | None,
    taskset_path: Path | str | None = None,
    min_tasks: int = 30,
) -> list[str]:
    """The card's quality gate. Returns a list of violations ([] = pass)."""
    violations: list[str] = []
    records = results.get("records") or []
    cells = results.get("cells") or sorted({r.get("cell") for r in records})
    blocked_cells = dict(results.get("blocked_cells") or {})

    # --- manifest integrity -------------------------------------------------
    if manifest is None:
        violations.append(
            "manifest missing — run.py must write --manifest for every results file"
        )
    elif not manifest.get("taskset_sha256"):
        violations.append("manifest missing taskset_sha256 — taskset not pinned")
    if taskset_path is not None and manifest is not None:
        from evals.web.run import taskset_sha256

        actual = taskset_sha256(taskset_path)
        if manifest.get("taskset_sha256") != actual:
            violations.append(
                "manifest taskset_sha256 does not match --taskset file "
                f"({manifest.get('taskset_sha256')} != {actual})"
            )

    # --- designed-failure sanity --------------------------------------------
    covered_fail = _expected_fail_ids(records, taskset_path)
    if covered_fail:
        for r in records:
            if r.get("task_id") in covered_fail and r.get("status") == "passed":
                violations.append(
                    f"designed-to-fail task {r.get('task_id')} reported passed "
                    f"in cell {r.get('cell')} — oracle/gate broken"
                )
        if not any(r.get("status") in {"failed", "error"} for r in records):
            violations.append(
                "zero failures recorded although the covered taskset includes "
                "known-failing tasks — failure-detection blind spot"
            )

    # --- per-cell coverage ---------------------------------------------------
    for cell in cells:
        if cell in blocked_cells:
            continue
        recs = _records_for_cell(records, cell)
        if not recs:
            violations.append(
                f"cell {cell} produced no records and is not marked blocked "
                "(blocked_cells has no entry) — silent gap"
            )
            continue
        attempted = [r for r in recs if r.get("status") != "blocked"]
        if len(attempted) < min_tasks:
            violations.append(
                f"cell {cell} attempted {len(attempted)} tasks — below the "
                f"required min_tasks={min_tasks}"
            )

    return violations


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _rate(value: float | None) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "n/a"


def render_markdown(
    report: dict[str, Any],
    results: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> str:
    cells = report.get("cells") or {}
    overall = report.get("overall") or {}
    manifest = manifest or {}
    lines = [
        "# WEB-W7-C03 Agent Eval Report",
        "",
        f"- generated: {report.get('generated_at')}",
        f"- model: {report.get('model') or manifest.get('model')}",
        f"- code_commit: {report.get('code_commit')}",
        f"- taskset_sha256: {report.get('taskset_sha256')}",
        f"- price_version: {report.get('price_version')}",
        "",
        "## Cells",
        "",
        "| cell | attempted | blocked | passed | failed | error | success | "
        "p50 (s) | p95 (s) | tok in | tok out | tok total | cost USD |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cell, stats in cells.items():
        lines.append(
            "| {cell} | {att} | {blk} | {ok} | {fail} | {err} | {rate} | "
            "{p50} | {p95} | {tin} | {tout} | {ttot} | {cost} |".format(
                cell=cell,
                att=stats.get("attempted"),
                blk=stats.get("blocked"),
                ok=stats.get("passed"),
                fail=stats.get("failed"),
                err=stats.get("error"),
                rate=_rate(stats.get("success_rate")),
                p50=(stats.get("duration_s") or {}).get("p50"),
                p95=(stats.get("duration_s") or {}).get("p95"),
                tin=(stats.get("tokens") or {}).get("input"),
                tout=(stats.get("tokens") or {}).get("output"),
                ttot=(stats.get("tokens") or {}).get("total"),
                cost=(stats.get("cost") or {}).get("total"),
            )
        )
    lines.append(
        "| **overall** | {att} | {blk} | {ok} | {fail} | {err} | {rate} | "
        "{p50} | {p95} | {tin} | {tout} | {ttot} | {cost} |".format(
            att=overall.get("attempted"),
            blk=overall.get("blocked"),
            ok=overall.get("passed"),
            fail=overall.get("failed"),
            err=overall.get("error"),
            rate=_rate(overall.get("success_rate")),
            p50=(overall.get("duration_s") or {}).get("p50"),
            p95=(overall.get("duration_s") or {}).get("p95"),
            tin=(overall.get("tokens") or {}).get("input"),
            tout=(overall.get("tokens") or {}).get("output"),
            ttot=(overall.get("tokens") or {}).get("total"),
            cost=(overall.get("cost") or {}).get("total"),
        )
    )
    lines += ["", "## Mode forcing (manifest)", ""]
    for cell, info in (report.get("mode_map") or {}).items():
        lines.append(
            f"- `{cell}`: mode={info.get('mode')} forcing={info.get('forcing')}"
            + (f" prefix={info.get('prefix')}" if info.get("prefix") else "")
        )
    blocked = report.get("blocked_cells") or {}
    if blocked:
        lines += ["", "## Blocked cells", ""]
        for cell, reason in blocked.items():
            lines.append(f"- `{cell}`: {reason}")
    abnormal = report.get("abnormal_cost") or []
    if abnormal:
        lines += ["", "## Abnormal cost rows (>$1/task)", ""]
        for item in abnormal:
            lines.append(
                f"- {item.get('task_id')} [{item.get('cell')}]: "
                f"${item.get('amount')} via {item.get('source')}"
            )
    designed = [
        item
        for stats in cells.values()
        for item in (stats.get("designed_failures") or [])
    ]
    if designed:
        lines += ["", "## Designed-failure tasks", ""]
        for item in designed:
            lines.append(f"- {item.get('task_id')} [{item.get('cell')}]: {item.get('status')}")
    lines += [
        "",
        "Notes: `success` counts passed/(attempted) with failures in the denominator;",
        "`blocked` tasks are excluded from the rate but reported above. Web cost rows",
        "come from `usage_records` (ledger); CLI cost rows are price-table estimates.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python evals/web/report.py",
        description="Aggregate run.py results and apply the W7-C03 quality gate.",
    )
    parser.add_argument("--results", type=str, required=True, help="run.py results JSON")
    parser.add_argument(
        "--manifest",
        type=str,
        default=None,
        help="run.py manifest JSON (default: embedded copy or sibling of results)",
    )
    parser.add_argument(
        "--taskset",
        type=str,
        default=None,
        help="Re-verify manifest taskset_sha256 and designed-fail coverage",
    )
    parser.add_argument(
        "--min-tasks",
        type=int,
        default=30,
        help="Required attempted tasks per non-blocked cell (default 30)",
    )
    parser.add_argument("--out", type=str, default=None, help="Write markdown report here")
    args = parser.parse_args(argv)

    results = load_results(args.results)
    results["_results_path"] = args.results
    manifest = load_manifest(results, path=args.manifest)
    report = build_report(results, manifest)
    markdown = render_markdown(report, results, manifest)
    violations = gate_report(
        results,
        manifest=manifest,
        taskset_path=args.taskset,
        min_tasks=args.min_tasks,
    )

    print(markdown)
    print("## Gate")
    print()
    if violations:
        print("GATE: FAIL")
        for v in violations:
            print(f"- {v}")
    else:
        print("GATE: PASS")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        gate_lines = "\n".join(["## Gate", ""] + (
            ["GATE: FAIL"] + [f"- {v}" for v in violations]
            if violations
            else ["GATE: PASS"]
        ))
        out_path.write_text(markdown + gate_lines + "\n", encoding="utf-8")

    # Stash a machine-readable copy next to the markdown for evidence.
    if args.out:
        json_path = Path(args.out).with_suffix(".report.json")
        json_path.write_text(
            json.dumps(
                {"report": report, "gate": {"passed": not violations, "violations": violations}},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
