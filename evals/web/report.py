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
  ``failed``/``error`` — and with ``--taskset`` every designed-fail task must
  have a non-blocked record somewhere (blocked is not coverage);
* every declared cell must produce records — unless ``blocked_cells`` carries
  an honest, non-empty reason (provider outage, database down);
* when the manifest declares ``cells``, every declared cell must appear in
  ``results.cells`` (and then produce records or an honest blocked reason);
  a results cell the manifest never declared is unaccounted provenance;
* every record's own ``cell`` must be declared too — in ``results.cells``
  and, when the manifest lists ``cells``, in the manifest as well. Records
  in undeclared cells would otherwise inflate ``overall`` while dodging
  per-cell coverage; the report still counts their real spend but lists and
  flags the undeclared cell instead of hiding it;
* duplicate ``(cell, task_id)`` rows are violations — stats de-duplicate to
  the first row per pair so repeats cannot inflate the success rate;
* with ``--taskset``, every taskset task_id must appear per declared
  non-blocked cell; unknown task_ids are violations; and coverage counts
  DISTINCT task_ids — duplicate rows do not count;
* each non-blocked cell must attempt at least ``--min-tasks`` distinct tasks
  (default 30: the full taskset);
* an empty records list is always a violation;

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


def _stats(records: list[dict], budget: int | None = None) -> dict[str, Any]:
    # Duplicate (cell, task_id) rows are a gate violation; rates, status
    # counts and durations are computed on the FIRST row per pair so repeats
    # cannot inflate success. Token and cost totals still sum every row —
    # repeated rows burned real spend and must not vanish from the totals.
    deduped: list[dict] = []
    seen: set[tuple[Any, Any]] = set()
    for r in records:
        key = (r.get("cell"), str(r.get("task_id")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    by_status = Counter(str(r.get("status") or "error") for r in deduped)
    attempted = [r for r in deduped if r.get("status") != "blocked"]
    blocked = [r for r in records if r.get("status") == "blocked"]
    durations = sorted(float(r.get("duration_s") or 0.0) for r in attempted)
    # Token totals are REAL spend: blocked records consumed tokens too and
    # their spend must land in the totals even though they stay excluded from
    # the success-rate denominator.
    def _tokens(rs: list[dict]) -> dict[str, int]:
        return {
            "input": sum(int((r.get("token_usage") or {}).get("input") or 0) for r in rs),
            "output": sum(int((r.get("token_usage") or {}).get("output") or 0) for r in rs),
            "total": sum(int((r.get("token_usage") or {}).get("total") or 0) for r in rs),
        }

    tokens_all = _tokens(records)
    tokens_attempted = _tokens(attempted)
    tokens_blocked = _tokens(blocked)
    cost_amounts: list[Decimal] = []
    blocked_costs: list[Decimal] = []
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
        if r.get("status") == "blocked":
            blocked_costs.append(value)
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
    attempted_tokens_total = tokens_attempted["total"]
    largest_task_tokens = max(
        (int((r.get("token_usage") or {}).get("total") or 0) for r in records),
        default=0,
    )
    overrun = max(0, tokens_all["total"] - int(budget)) if budget else 0
    return {
        "n": len(records),
        "distinct_pairs": len(deduped),
        "duplicate_rows": len(records) - len(deduped),
        "attempted": attempted_n,
        "blocked": len(deduped) - attempted_n,
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
            "input": tokens_all["input"],
            "output": tokens_all["output"],
            "total": tokens_all["total"],
            "attempted_total": attempted_tokens_total,
            "blocked_total": tokens_blocked["total"],
            "mean_total": (
                round(attempted_tokens_total / attempted_n, 1) if attempted_n else None
            ),
        },
        # Spend by blocked records: excluded from the rate, never from totals.
        "blocked_spend": {
            "records": len(blocked),
            "tokens": tokens_blocked["total"],
            "cost": str(sum(blocked_costs, Decimal(0))),
            "currency": "USD",
        },
        "budget": {
            "declared": int(budget) if budget else None,
            "overrun_tokens": overrun,
            "largest_single_task_tokens": largest_task_tokens,
            # overrun beyond one in-flight task's spend means more than the
            # documented bound leaked — flag it rather than letting it pass.
            "suspicious_overrun": bool(
                budget and overrun > largest_task_tokens
            ),
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
    declared = list(results.get("cells") or [])
    record_cells = {r.get("cell") for r in records}
    # A record can carry a cell results.cells never declared — unaccounted
    # provenance the gate rejects. List it in the per-cell table (flagged)
    # rather than letting it vanish into the "overall" line.
    undeclared_cells = (
        sorted((c for c in record_cells if c not in set(declared)), key=str)
        if declared
        else []
    )
    cells = declared + undeclared_cells if declared else sorted(record_cells, key=str)
    manifest = manifest if manifest is not None else results.get("manifest") or {}
    declared_budget = int(manifest.get("budget") or 0) or None
    per_cell = {
        cell: _stats(_records_for_cell(records, cell), budget=declared_budget)
        for cell in cells
    }
    for cell in undeclared_cells:
        per_cell[cell]["undeclared_cell"] = True
    # The declared cap is per declared cell; the overall line compares
    # against the sum of those — undeclared cells earn no cap allowance.
    overall_budget = (
        declared_budget * len(declared or cells)
        if declared_budget and (declared or cells)
        else None
    )
    spine_errors = [
        {
            "task_id": r.get("task_id"),
            "cell": r.get("cell"),
            "spine_errors": list(r.get("spine_errors") or []),
        }
        for r in records
        if r.get("spine_errors")
    ]
    overall = _stats(list(records), budget=overall_budget)
    # Undeclared-cell records stay in the totals — their spend was real — but
    # the share is enumerable instead of silently inflating the line.
    overall["undeclared_records"] = sum(
        1 for r in records if r.get("cell") in set(undeclared_cells)
    )
    return {
        "schema": "evals-web-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "taskset_sha256": manifest.get("taskset_sha256"),
        "code_commit": manifest.get("code_commit"),
        "model": manifest.get("model"),
        "price_version": manifest.get("price_version"),
        "mode_map": manifest.get("mode_map"),
        "executed_sources": manifest.get("executed_sources"),
        "budget": manifest.get("budget"),
        "cells": per_cell,
        "undeclared_cells": undeclared_cells,
        "overall": overall,
        "blocked_cells": dict(results.get("blocked_cells") or {}),
        "spine_errors": spine_errors,
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
    """Task ids covered by records that were designed to fail.

    With a taskset the designed-fail set is authoritative — it does NOT need
    the task to appear in records to count (coverage is checked separately).
    """
    if taskset_path:
        from evals.web.run import load_taskset

        return {
            t.task_id for t in load_taskset(taskset_path) if t.expect == "fail"
        }
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
    """The card's quality gate. Returns a list of violations ([] = pass).

    With ``--taskset`` the gate is strict: every taskset task must produce a
    record per declared non-blocked cell, unknown task_ids are violations,
    coverage counts DISTINCT task_ids (duplicate rows do not help), empty
    records are rejected, and ``blocked_cells`` needs a non-empty reason.
    Without it, the weaker pre-existing checks stay — except that an empty
    records list is still a violation. Always enforced, with or without a
    taskset: duplicate (cell, task_id) rows are violations, a manifest that
    declares ``cells`` is reconciled against ``results.cells`` in both
    directions, and every record's own ``cell`` must be declared (in
    ``results.cells``, and in ``manifest.cells`` when the manifest lists
    cells) — a record in an undeclared cell is unaccounted work.
    """
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

    # --- manifest <-> results cell reconciliation -----------------------------
    # When the manifest declares its cells the declaration binds in BOTH
    # directions: a declared cell absent from results.cells silently dropped
    # out of the run (per-cell coverage below then requires its records or an
    # honest blocked reason), and a results cell the manifest never declared
    # is unaccounted provenance.
    manifest_cells = manifest.get("cells") if isinstance(manifest, dict) else None
    if isinstance(manifest_cells, list):
        declared_cells = {str(c) for c in manifest_cells}
        present_cells = {str(c) for c in cells}
        for cell in sorted(declared_cells - present_cells):
            violations.append(
                f"manifest declares cell {cell} but results.cells omits it — "
                "a declared cell cannot silently drop out of the run"
            )
        for cell in sorted(present_cells - declared_cells):
            violations.append(
                f"results contain cell {cell} which the manifest cells list "
                "does not declare — unaccounted cell provenance"
            )

    # --- per-record cell provenance -------------------------------------------
    # The cell LISTS reconcile above, but each record's own ``cell`` field is
    # provenance too: it must be declared in results.cells, and in the
    # manifest's cells list when the manifest declares one. Records in an
    # undeclared cell used to slip past the list-level check — silently
    # inflating "overall" while dodging per-cell coverage and the table.
    declared_results_cells = {str(c) for c in cells}
    manifest_cell_set = (
        {str(c) for c in manifest_cells}
        if isinstance(manifest_cells, list)
        else None
    )
    undeclared_results: Counter[str] = Counter()
    undeclared_manifest: Counter[str] = Counter()
    for r in records:
        rec_cell = str(r.get("cell"))
        if rec_cell not in declared_results_cells:
            undeclared_results[rec_cell] += 1
        if manifest_cell_set is not None and rec_cell not in manifest_cell_set:
            undeclared_manifest[rec_cell] += 1
    for cell in sorted(undeclared_results):
        violations.append(
            f"{undeclared_results[cell]} record(s) carry cell {cell} which "
            "results.cells does not declare — records in an undeclared cell "
            "cannot inflate overall stats or dodge per-cell coverage"
        )
    for cell in sorted(undeclared_manifest):
        violations.append(
            f"{undeclared_manifest[cell]} record(s) carry cell {cell} which "
            "the manifest cells list does not declare — unaccounted cell "
            "provenance"
        )

    # --- empty results -------------------------------------------------------
    if not records:
        violations.append(
            "results contain no records — an empty run is not evidence"
        )

    # --- duplicate (cell, task_id) rows --------------------------------------
    # One pair, one row: repeats let a single execution masquerade as many
    # and inflate the success rate. Listed so the results can be fixed; stats
    # already de-duplicate, so the violation is what carries the signal.
    pair_counts = Counter(
        (str(r.get("cell")), str(r.get("task_id"))) for r in records
    )
    dup_pairs = sorted(p for p, n in pair_counts.items() if n > 1)
    if dup_pairs:
        shown = ", ".join(
            f"{cell}/{task_id} x{pair_counts[(cell, task_id)]}"
            for cell, task_id in dup_pairs[:5]
        ) + (" ..." if len(dup_pairs) > 5 else "")
        violations.append(
            f"{len(dup_pairs)} duplicate (cell, task_id) pair(s) — repeated "
            f"rows cannot inflate coverage or the success rate: {shown}"
        )

    # --- blocked_cells honesty ------------------------------------------------
    # An empty reason is no reason: the cell is NOT excused from coverage and
    # the empty claim is itself a violation.
    honestly_blocked = set()
    for cell, reason in blocked_cells.items():
        if str(reason or "").strip():
            honestly_blocked.add(cell)
        else:
            violations.append(
                f"blocked_cells[{cell}] has an empty reason — a blocked claim "
                "needs a concrete cause"
            )

    # --- taskset-anchored coverage --------------------------------------------
    taskset_ids: set[str] | None = None
    designed_fail: set[str] = set()
    if taskset_path is not None:
        from evals.web.run import load_taskset

        taskset = load_taskset(taskset_path)
        taskset_ids = {t.task_id for t in taskset}
        designed_fail = {t.task_id for t in taskset if t.expect == "fail"}
        recorded_ids = {str(r.get("task_id")) for r in records}
        unknown = sorted(recorded_ids - taskset_ids)
        if unknown:
            shown = ", ".join(unknown[:5]) + (" ..." if len(unknown) > 5 else "")
            violations.append(
                f"{len(unknown)} record task_id(s) are not in the taskset "
                f"(unknown provenance): {shown}"
            )
        for cell in cells:
            if cell in honestly_blocked:
                continue
            present = {
                str(r.get("task_id"))
                for r in _records_for_cell(records, cell)
            }
            missing = sorted(taskset_ids - present)
            if missing:
                shown = ", ".join(missing[:5]) + (
                    " ..." if len(missing) > 5 else ""
                )
                violations.append(
                    f"cell {cell} is missing coverage for "
                    f"{len(missing)}/{len(taskset_ids)} taskset task(s): {shown}"
                )
    else:
        designed_fail = _expected_fail_ids(records, None)

    # --- designed-failure sanity --------------------------------------------
    if designed_fail:
        for r in records:
            if r.get("task_id") in designed_fail and r.get("status") == "passed":
                violations.append(
                    f"designed-to-fail task {r.get('task_id')} reported passed "
                    f"in cell {r.get('cell')} — oracle/gate broken"
                )
        attempted_fail = {
            str(r.get("task_id"))
            for r in records
            if r.get("task_id") in designed_fail and r.get("status") != "blocked"
        }
        has_live_cell = any(cell not in honestly_blocked for cell in cells)
        if has_live_cell:
            for task_id in sorted(designed_fail - attempted_fail):
                violations.append(
                    f"designed-to-fail task {task_id} was never attempted — "
                    "no non-blocked record exists, so failure detection is "
                    "unproven"
                )
            if attempted_fail and not any(
                r.get("task_id") in designed_fail
                and r.get("status") in {"failed", "error"}
                for r in records
            ):
                violations.append(
                    "zero failures recorded although the covered taskset includes "
                    "known-failing tasks — failure-detection blind spot"
                )

    # --- per-cell coverage ---------------------------------------------------
    for cell in cells:
        if cell in honestly_blocked:
            continue
        recs = _records_for_cell(records, cell)
        if not recs:
            violations.append(
                f"cell {cell} produced no records and is not marked blocked "
                "(blocked_cells has no non-empty entry) — silent gap"
            )
            continue
        attempted_ids = {
            str(r.get("task_id"))
            for r in recs
            if r.get("status") != "blocked"
        }
        if len(attempted_ids) < min_tasks:
            violations.append(
                f"cell {cell} attempted {len(attempted_ids)} distinct tasks — "
                f"below the required min_tasks={min_tasks}"
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
                cell=(
                    f"{cell} (undeclared)"
                    if stats.get("undeclared_cell")
                    else cell
                ),
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
    blocked_spend = [
        (cell, (stats.get("blocked_spend") or {}))
        for cell, stats in cells.items()
        if (stats.get("blocked_spend") or {}).get("tokens")
        or Decimal(str((stats.get("blocked_spend") or {}).get("cost") or "0")) > 0
    ]
    if blocked_spend:
        lines += [
            "",
            "## Blocked spend (excluded from success rate, counted in totals)",
            "",
        ]
        for cell, spend in blocked_spend:
            lines.append(
                f"- `{cell}`: {spend.get('tokens')} tokens / "
                f"${spend.get('cost')} across {spend.get('records')} "
                "blocked record(s)"
            )
    duplicate_rows = int(overall.get("duplicate_rows") or 0)
    if duplicate_rows:
        lines += [
            "",
            "## Duplicate rows",
            "",
            f"- {duplicate_rows} repeated (cell, task_id) row(s) ignored for "
            "rates/counts (stats use distinct pairs) — a gate violation; "
            "their token/cost spend still counts in the totals above.",
        ]
    undeclared_cells = report.get("undeclared_cells") or []
    if undeclared_cells:
        lines += [
            "",
            "## Undeclared cells (records outside results.cells — gate "
            "violation)",
            "",
        ]
        for cell in undeclared_cells:
            stats = cells.get(cell) or {}
            lines.append(
                f"- `{cell}`: {stats.get('n') or 0} record(s) of unaccounted "
                "provenance — their spend stays in the totals above and they "
                "are flagged in the cells table, but they earn no declared-"
                "cell coverage and the gate fails on them."
            )
    budget = report.get("budget")
    if budget:
        lines += [
            "",
            f"## Budget (declared per-cell cap: {int(budget):,} tokens)",
            "",
        ]
        for cell, stats in cells.items():
            binfo = stats.get("budget") or {}
            overrun = int(binfo.get("overrun_tokens") or 0)
            largest = int(binfo.get("largest_single_task_tokens") or 0)
            total = int((stats.get("tokens") or {}).get("total") or 0)
            note = (
                "OVERRUN BEYOND ONE-IN-FLIGHT BOUND — investigate"
                if binfo.get("suspicious_overrun")
                else "within one in-flight overrun bound"
            )
            lines.append(
                f"- `{cell}`: {total:,} tokens recorded; overrun "
                f"{overrun:,} vs cap (largest single task {largest:,}) — {note}"
            )
    spine_errors = report.get("spine_errors") or []
    if spine_errors:
        lines += ["", "## Spine errors (durable-path failures)", ""]
        for item in spine_errors:
            for err in item.get("spine_errors") or []:
                lines.append(f"- {item.get('task_id')} [{item.get('cell')}]: {err}")
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
        "`blocked` tasks are excluded from the rate but their token/cost spend is",
        "counted in the totals above. Web cost rows come from `usage_records`",
        "(ledger); CLI cost rows are price-table estimates.",
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
