"""WEB-W7-C03. Contract and negative checks for the reproducible eval harness.

Contract: the taskset hash and manifest are deterministic — the same
``evals/web/taskset.jsonl`` always produces the same normalized sha256, and the
manifest carries every field needed to reproduce the run (model, provider,
price version, code commit, budget, mode map).

Negative: the report gate must refuse happy-path-only output — a results file
below the task threshold, a missing manifest/hash, and a run where the
taskset's designed-to-fail task reports ``passed``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RUN_PY = REPO / "evals" / "web" / "run.py"
REPORT_PY = REPO / "evals" / "web" / "report.py"
TASKSET = REPO / "evals" / "web" / "taskset.jsonl"

ALLOWED_CATEGORIES = {"coding", "browser", "recovery", "remote"}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass string annotations resolve through sys.modules[cls.__module__]
    # — register before exec or dataclasses crashes on Optional[...] fields.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def web_run():
    return _load_module("w7c03_web_run", RUN_PY)


@pytest.fixture(scope="module")
def web_report():
    return _load_module("w7c03_web_report", REPORT_PY)


def _record(task_id: str, cell: str, status: str) -> dict:
    return {
        "task_id": task_id,
        "cell": cell,
        "status": status,
        "expect": "pass",
        "duration_s": 1.0,
        "token_usage": {"input": 10, "output": 5, "total": 15},
        "cost": None,
        "run_id": None,
        "error": "",
        "check_details": [],
    }


def test_w7_c03_contract(web_run) -> None:
    """Manifest built twice from the fixed taskset carries identical hashes."""
    tasks = web_run.load_taskset(TASKSET)
    assert len(tasks) >= 30, f"taskset has {len(tasks)} tasks; need >= 30"
    ids = [task.task_id for task in tasks]
    assert len(ids) == len(set(ids)), "duplicate task_id in taskset"
    categories = {task.category for task in tasks}
    assert categories <= ALLOWED_CATEGORIES, categories - ALLOWED_CATEGORIES
    assert categories == ALLOWED_CATEGORIES, f"under-covered categories: {categories}"
    known_failures = [task for task in tasks if task.expect == "fail"]
    assert known_failures, "taskset needs at least one designed-to-fail task"

    # Checks reuse the runner's check-type vocabulary so the same scorer works.
    from evals.tasks import CHECK_TYPES

    for task in tasks:
        assert task.source_commit or task.pinned_ref, task.task_id
        for check in task.checks:
            assert check.type in CHECK_TYPES, f"{task.task_id}: {check.type}"

    cells = ["cli-solo", "cli-team", "web-solo", "web-team"]
    first = web_run.build_manifest(
        taskset_path=TASKSET,
        tasks=tasks,
        cells=cells,
        budget=2000000,
        model=None,
        database_url="postgresql+psycopg://postgres@127.0.0.1:55432/rxycode",
    )
    second = web_run.build_manifest(
        taskset_path=TASKSET,
        tasks=tasks,
        cells=cells,
        budget=2000000,
        model=None,
        database_url="postgresql+psycopg://postgres@127.0.0.1:55432/rxycode",
    )
    digest = web_run.taskset_sha256(TASKSET)
    assert first["taskset_sha256"] == second["taskset_sha256"] == digest
    assert len(digest) == 64

    for field in (
        "taskset_sha256",
        "model",
        "provider",
        "price_version",
        "code_commit",
        "budget",
        "mode_map",
        "python",
        "platform",
        "started_at",
        "task_ids",
    ):
        assert first.get(field) not in (None, ""), f"manifest missing {field}"
    for cell in cells:
        assert cell in first["mode_map"], cell
        entry = first["mode_map"][cell]
        assert entry.get("mode") in {"solo", "team"}, entry
        assert entry.get("forcing"), entry
    assert "api_key" not in json.dumps(first).lower()


def test_w7_c03_negative(web_report, tmp_path: Path, web_run) -> None:
    """The gate refuses happy-path-only reports and missing provenance."""
    tasks = web_run.load_taskset(TASKSET)
    fail_id = next(task.task_id for task in tasks if task.expect == "fail")
    pass_id = next(task.task_id for task in tasks if task.expect != "fail")

    # A single happy-path record is far below the task threshold.
    tiny = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [_record(pass_id, "cli-solo", "passed")],
    }
    manifest = {"taskset_sha256": web_run.taskset_sha256(TASKSET)}
    violations = web_report.gate_report(
        tiny, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert violations, "gate accepted a one-record happy-path report"
    assert any("fewer than" in v or "below" in v or "min_tasks" in v for v in violations), violations

    # Full coverage but zero failures while a designed-to-fail task was
    # exercised — and that task reporting ``passed`` — is synthetic evidence.
    happy = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [
            {**_record(task.task_id, "cli-solo", "passed"), "expect": task.expect}
            for task in tasks
        ],
    }
    violations = web_report.gate_report(
        happy, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert any("designed-to-fail" in v or "known-failing" in v for v in violations), violations
    assert any(fail_id in v for v in violations), violations

    # Missing manifest and missing hash are both rejected.
    assert web_report.gate_report(
        tiny, manifest=None, taskset_path=TASKSET, min_tasks=1
    ), "gate accepted a missing manifest"
    assert web_report.gate_report(
        tiny, manifest={}, taskset_path=TASKSET, min_tasks=1
    ), "gate accepted a manifest without taskset_sha256"
    bad_hash = {"taskset_sha256": "0" * 64}
    assert web_report.gate_report(
        tiny, manifest=bad_hash, taskset_path=TASKSET, min_tasks=1
    ), "gate accepted a manifest hash that does not match the taskset"

    # An empty cell with no blocked justification is rejected; with one it is not.
    two_cells = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo", "web-solo"],
        "blocked_cells": {},
        "records": [
            {**_record(task.task_id, "cli-solo", "failed"), "expect": task.expect}
            for task in tasks
        ],
    }
    violations = web_report.gate_report(
        two_cells, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert any("web-solo" in v and "blocked" in v.lower() for v in violations), violations
    two_cells["blocked_cells"] = {"web-solo": "postgres unreachable: tcp 55432 refused"}
    violations = web_report.gate_report(
        two_cells, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert not any("web-solo" in v for v in violations), violations

    # --- audit round-1 probes: each must produce gate violations ------------

    # 30 copies of one happy record: row count is not distinct-task coverage.
    dup = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [_record(pass_id, "cli-solo", "passed") for _ in range(30)],
    }
    violations = web_report.gate_report(
        dup, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert violations, "gate accepted 30 duplicate rows of a single task"
    assert any(
        "missing" in v or "distinct" in v or "coverage" in v or "min_tasks" in v
        for v in violations
    ), violations

    # Records whose task_ids are not in the taskset have unknown provenance.
    unknown_id = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [
            {**_record(task.task_id, "cli-solo", "failed"), "expect": task.expect}
            for task in tasks
        ]
        + [_record("w7c03-zzz-not-in-taskset", "cli-solo", "passed")],
    }
    violations = web_report.gate_report(
        unknown_id, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert any(
        "w7c03-zzz-not-in-taskset" in v or "unknown" in v.lower() or "provenance" in v
        for v in violations
    ), violations

    # An empty-string blocked_cells reason is not an honest block — and the
    # cell is not excused from coverage either.
    empty_reason = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo", "web-solo"],
        "blocked_cells": {"web-solo": ""},
        "records": [
            {**_record(task.task_id, "cli-solo", "failed"), "expect": task.expect}
            for task in tasks
        ],
    }
    violations = web_report.gate_report(
        empty_reason, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert any(
        "web-solo" in v and "reason" in v.lower() for v in violations
    ), violations
    assert any("web-solo" in v and ("missing" in v or "coverage" in v) for v in violations), (
        violations
    )

    # An entirely empty results set is a violation even when cells declare work.
    empty_results = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [],
    }
    violations = web_report.gate_report(
        empty_results, manifest=manifest, taskset_path=TASKSET, min_tasks=1
    )
    assert violations, "gate accepted an empty results set"
    # Empty records are rejected even without a taskset.
    assert web_report.gate_report(
        empty_results, manifest=manifest, taskset_path=None, min_tasks=1
    ), "gate accepted an empty results set without taskset"

    # Missing designed-fail coverage: the designed-to-fail task present only as
    # `blocked` was never attempted — the oracle-blindness check has no teeth.
    blocked_fail = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [
            {
                **_record(
                    task.task_id,
                    "cli-solo",
                    "blocked" if task.expect == "fail" else "failed",
                ),
                "expect": task.expect,
            }
            for task in tasks
        ],
    }
    violations = web_report.gate_report(
        blocked_fail, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert any(fail_id in v for v in violations), violations

    # --- audit round-2 probes -------------------------------------------------

    # Manifest declares 4 cells but results only ran cli-solo — declared cells
    # must not silently drop out of the gate (previously: zero violations
    # because the gate only looked at results["cells"]).
    manifest4 = dict(manifest)
    manifest4["cells"] = ["cli-solo", "cli-team", "web-solo", "web-team"]
    cli_only = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": [
            {**_record(task.task_id, "cli-solo", "failed"), "expect": task.expect}
            for task in tasks
        ],
    }
    violations = web_report.gate_report(
        cli_only, manifest=manifest4, taskset_path=TASKSET, min_tasks=30
    )
    for missing in ("cli-team", "web-solo", "web-team"):
        assert any(missing in v for v in violations), (
            f"gate let manifest-declared cell {missing} vanish: {violations}"
        )

    # An honest blocked claim excuses the coverage but NOT the cells entry:
    # a declared cell must still appear in results.cells.
    blocked_only = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {
            "cli-team": "provider outage",
            "web-solo": "postgres unreachable",
            "web-team": "postgres unreachable",
        },
        "records": cli_only["records"],
    }
    violations = web_report.gate_report(
        blocked_only, manifest=manifest4, taskset_path=TASKSET, min_tasks=30
    )
    for missing in ("cli-team", "web-solo", "web-team"):
        assert any(missing in v for v in violations), violations

    # The reconciliation is two-way: a results cell the manifest never
    # declared is unaccounted provenance.
    manifest1 = dict(manifest)
    manifest1["cells"] = ["cli-solo"]
    extra_cell = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo", "cli-team"],
        "blocked_cells": {},
        "records": [
            {**_record(task.task_id, cell, "failed"), "expect": task.expect}
            for cell in ("cli-solo", "cli-team")
            for task in tasks
        ],
    }
    violations = web_report.gate_report(
        extra_cell, manifest=manifest1, taskset_path=TASKSET, min_tasks=30
    )
    assert any("cli-team" in v for v in violations), violations

    # --- audit round-3 probes -------------------------------------------------

    # The auditor's exact probe: 29 passed records carrying cell "web-team"
    # while BOTH results.cells and manifest.cells declare only cli-solo. The
    # gate reconciled the two cell LISTS but never each record's own cell —
    # zero violations, overall success inflated 96.67% -> 98.31%, and web-team
    # vanished from the per-cell report. A record in an undeclared cell is a
    # violation, and the report must list/flag the cell honestly.
    manifest_solo = dict(manifest)
    manifest_solo["cells"] = ["cli-solo"]
    honest_records = [
        {
            **_record(
                t.task_id, "cli-solo", "failed" if t.expect == "fail" else "passed"
            ),
            "expect": t.expect,
        }
        for t in tasks
    ]
    pass_task_ids = [t.task_id for t in tasks if t.expect != "fail"]
    probe = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": honest_records
        + [_record(tid, "web-team", "passed") for tid in pass_task_ids[:29]],
    }
    violations = web_report.gate_report(
        probe, manifest=manifest_solo, taskset_path=TASKSET, min_tasks=30
    )
    assert violations, "gate accepted 29 records in an undeclared cell"
    assert any("web-team" in v and "declare" in v for v in violations), violations
    # The check binds even without a taskset (the declarations are enough).
    violations = web_report.gate_report(
        probe, manifest=manifest_solo, taskset_path=None, min_tasks=3
    )
    assert any("web-team" in v for v in violations), violations

    # The undeclared cell is listed and flagged in the per-cell report instead
    # of vanishing into "overall"; its records' real spend still counts.
    report = web_report.build_report(probe)
    assert "web-team" in report["cells"], sorted(report["cells"])
    assert report["cells"]["web-team"].get("undeclared_cell") is True
    assert "web-team" in (report.get("undeclared_cells") or [])
    assert report["overall"]["n"] == len(tasks) + 29
    assert report["overall"]["undeclared_records"] == 29
    rendered = web_report.render_markdown(report, probe, manifest_solo)
    assert "web-team" in rendered and "ndeclared" in rendered

    # The CLI exits non-zero on a gate failure.
    results_path = tmp_path / "happy.json"
    results_path.write_text(json.dumps(tiny), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPORT_PY),
            "--results",
            str(results_path),
            "--manifest",
            str(manifest_path),
            "--taskset",
            str(TASKSET),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "GATE" in proc.stdout.upper() or "GATE" in proc.stderr.upper()


def test_w7_c03_duplicate_rows(web_report, web_run) -> None:
    """Duplicate (cell, task_id) rows are a gate violation and cannot inflate stats.

    100 copies of one passed record appended to a complete 30-task run used to
    pass the gate and lift the success rate (96.67% -> 99.23%). Now the gate
    lists the duplicated pair, and _stats computes rates/counts on distinct
    (cell, task_id) pairs — while token totals still count every row's real
    spend.
    """
    tasks = web_run.load_taskset(TASKSET)
    pass_id = next(t.task_id for t in tasks if t.expect != "fail")

    base = [
        {
            **_record(
                t.task_id, "cli-solo", "failed" if t.expect == "fail" else "passed"
            ),
            "expect": t.expect,
        }
        for t in tasks
    ]
    honest = web_report._stats(base)

    inflated = base + [_record(pass_id, "cli-solo", "passed") for _ in range(100)]
    results = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": inflated,
    }
    manifest = {"taskset_sha256": web_run.taskset_sha256(TASKSET)}
    violations = web_report.gate_report(
        results, manifest=manifest, taskset_path=TASKSET, min_tasks=30
    )
    assert any(
        "duplicate" in v.lower() and pass_id in v for v in violations
    ), violations

    # Stats stay honest: the success rate/attempted count are computed on
    # distinct pairs, exactly as if the 100 repeats never happened.
    stats = web_report._stats(inflated)
    assert stats["success_rate"] == honest["success_rate"], stats
    assert stats["attempted"] == honest["attempted"], stats
    assert stats["duplicate_rows"] == 100
    assert stats["distinct_pairs"] == len(tasks)
    # The repeated rows still burned real spend — totals keep counting it.
    assert stats["tokens"]["total"] == 15 * (len(tasks) + 100)

    # The duplicates are surfaced in the report, not hidden.
    report = web_report.build_report(results)
    assert report["overall"]["duplicate_rows"] == 100
    rendered = web_report.render_markdown(report, results, manifest)
    assert "uplicate" in rendered


def test_w7_c03_budget_enforced(web_run, monkeypatch, tmp_path: Path) -> None:
    """The declared per-cell token budget is enforced DURING execution.

    A scripted task that burns tokens faster than the remaining budget is
    cancelled in-flight and reported ``blocked`` with a ``budget_exceeded``
    reason; once a cell crosses the cap, later tasks never start.
    """
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    # -- in-flight cancellation ---------------------------------------------
    async def _burn_forever() -> str:
        token_stats.input_tokens += 5_000
        await asyncio.sleep(30)
        return "done"

    token0 = web_run._token_start()

    async def _run_budgeted() -> None:
        task = asyncio.ensure_future(_burn_forever())
        await web_run._await_budgeted(
            task,
            timeout=60,
            budget_remaining=100,
            used_tokens=lambda: web_run._token_delta(token0)["total"],
            poll_interval=0.02,
        )

    with pytest.raises(web_run._CellBudgetExceeded):
        asyncio.run(_run_budgeted())
    # Cancellation does not erase the spend — the delta is still visible.
    assert web_run._token_delta(token0)["total"] >= 5_000

    # -- run_cli_task honours the remaining budget mid-run -------------------
    import evals.backends as _backends

    class _HungryBackend:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run(self, prompt, workdir, *, effect=None):
            token_stats.input_tokens += 2_500_000
            await asyncio.sleep(30)
            return _backends.BackendResult(
                answer="", token_usage={"input": 0, "output": 0, "total": 0}
            )

    monkeypatch.setattr(_backends, "AgentBackend", _HungryBackend)

    task = web_run.WebEvalTask.from_dict(
        {
            "task_id": "w7c03budget",
            "category": "coding",
            "prompt": "noop",
            "checks": [{"type": "file_exists", "path": "answer.txt"}],
            "source_commit": "w7c03-unit",
        }
    )
    record = asyncio.run(
        web_run.run_cli_task(
            cell="cli-solo",
            task=task,
            workdir=tmp_path,
            model=None,
            task_timeout=60,
            budget_remaining=1_000_000,
        )
    )
    assert record["status"] == "blocked", record
    assert "budget_exceeded" in record["error"], record["error"]
    assert record["token_usage"]["total"] >= 2_500_000

    # -- run_matrix stops the cell once the cap is crossed --------------------
    calls: list[str] = []

    async def _fake_cli_task(
        *, cell, task, workdir, model, task_timeout, budget_remaining=None
    ):
        calls.append(task.task_id)
        rec = web_run._base_record(cell, task)
        rec["status"] = "passed"
        rec["token_usage"] = {"input": 0, "output": 0, "total": 1_500_000}
        return rec

    monkeypatch.setattr(web_run, "run_cli_task", _fake_cli_task)
    tasks = [
        web_run.WebEvalTask.from_dict(
            {
                "task_id": f"w7c03budget-{i}",
                "category": "coding",
                "prompt": "noop",
                "checks": [{"type": "file_exists", "path": "answer.txt"}],
                "source_commit": "w7c03-unit",
            }
        )
        for i in range(3)
    ]
    results = asyncio.run(
        web_run.run_matrix(
            tasks=tasks,
            cells=["cli-solo"],
            model=None,
            budget=2_000_000,
            task_timeout=5,
            database_url=None,
            workdir_base=tmp_path,
            log=lambda _m: None,
        )
    )
    # Task 1 spends 1.5M (< 2M cap); task 2 pushes the cell to 3.0M; task 3 is
    # never started.
    assert calls == ["w7c03budget-0", "w7c03budget-1"], calls
    last = results["records"][2]
    assert last["task_id"] == "w7c03budget-2"
    assert last["status"] == "blocked"
    assert "budget_exceeded" in last["error"], last["error"]


def test_w7_c03_fresh_workdir(web_run, tmp_path: Path) -> None:
    """A stale artifact from an earlier run must not satisfy the next oracle."""
    from evals.runner import run_checks

    task = web_run.WebEvalTask.from_dict(
        {
            "task_id": "w7c03fresh",
            "category": "coding",
            "prompt": "create answer.txt",
            "checks": [{"type": "file_exists", "path": "answer.txt"}],
            "setup": {"files": {"seed.txt": "fresh-seed"}},
            "source_commit": "w7c03-unit",
        }
    )
    # Pre-seed the exact workdir run.py reuses with a stale oracle-satisfier.
    stale_dir = tmp_path / "cli-solo" / task.task_id
    stale_dir.mkdir(parents=True)
    (stale_dir / "answer.txt").write_text("stale artifact", encoding="utf-8")

    workdir = web_run._setup_workdir(task, tmp_path, "cli-solo")
    assert not (workdir / "answer.txt").exists(), "stale artifact survived setup"
    assert (workdir / "seed.txt").read_text(encoding="utf-8") == "fresh-seed"

    # The oracle correctly fails — nothing satisfies file_exists anymore.
    passed, details = run_checks(
        task.to_eval_task(), workdir=workdir, agent_answer="", tools_used=[]
    )
    assert not passed, details


def test_w7_c03_blocked_spend_in_totals(web_report) -> None:
    """Spend from blocked records is real: tokens/cost reach report totals."""
    records = [
        _record("t-ok", "cli-solo", "passed"),
        {
            **_record("t-blocked", "cli-solo", "blocked"),
            "token_usage": {"input": 700, "output": 77, "total": 777},
            "cost": {
                "amount": "0.00155400",
                "currency": "USD",
                "source": "usage_records",
            },
            "error": "provider infra: error code: 429",
        },
    ]
    results = {
        "schema": "evals-web-results/v1",
        "cells": ["cli-solo"],
        "blocked_cells": {},
        "records": records,
    }
    report = web_report.build_report(results)
    stats = report["cells"]["cli-solo"]
    assert stats["tokens"]["total"] == 15 + 777, stats["tokens"]
    assert stats["blocked_spend"]["tokens"] == 777
    assert stats["blocked_spend"]["cost"] == "0.00155400"
    # Blocked stays out of the success-rate denominator but spend is visible.
    assert stats["success_rate"] == 1.0
    rendered = web_report.render_markdown(report, results, None)
    assert "777" in rendered and "0.00155400" in rendered


def test_w7_c03_executed_sources(web_run) -> None:
    """The manifest pins sha256 of the exact executed source files."""
    tasks = web_run.load_taskset(TASKSET)
    manifest = web_run.build_manifest(
        taskset_path=TASKSET,
        tasks=tasks,
        cells=["cli-solo"],
        budget=2_000_000,
        model=None,
        database_url=None,
    )
    sources = manifest.get("executed_sources") or {}
    for rel in (
        "evals/web/run.py",
        "evals/web/report.py",
        "evals/web/taskset.jsonl",
    ):
        expected = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        assert sources.get(rel) == expected, f"executed_sources[{rel}] missing/wrong"
    # Dirty worktrees must also carry the bounded evals/web diff + dirty paths.
    if manifest.get("worktree_dirty"):
        assert "evals_web_diff" in manifest
        assert "evals_web_dirty_paths" in manifest
        assert len(manifest["evals_web_diff"]) <= 200_100


def _mk_task(web_run, task_id: str) -> object:
    return web_run.WebEvalTask.from_dict(
        {
            "task_id": task_id,
            "category": "coding",
            "prompt": "noop",
            "checks": [{"type": "file_exists", "path": "answer.txt"}],
            "source_commit": "w7c03-unit",
        }
    )


def test_w7_c03_runner_crash_keeps_spend(web_run, monkeypatch, tmp_path: Path) -> None:
    """An escaped runner failure must still carry the tokens it burned.

    Auditor probe (audit r3 finding): stub drivers record 1,000 tokens each
    then raise; under a 500-token cap the pre-fix catch-all wrote a fresh
    record with ZERO tokens — the spend vanished from the cell budget and the
    second task was wrongly "allowed". The record must now carry the measured
    spend (the token_stats delta AND any ctx.outcome/runtime counter the
    runner recorded via the spend sink), it must count toward the cell budget,
    and the cost must fall back to the estimate, never $0-for-burned-tokens.
    """
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    tasks = [_mk_task(web_run, f"w7c03crash-{i}") for i in range(2)]

    # -- CLI cell: spend visible through the process-global token_stats delta --
    calls: list[str] = []

    async def _burn_then_raise(
        *, cell, task, workdir, model, task_timeout, budget_remaining=None
    ):
        calls.append(task.task_id)
        token_stats.input_tokens += 1_000
        raise RuntimeError("runner exploded after burning tokens")

    monkeypatch.setattr(web_run, "run_cli_task", _burn_then_raise)
    results = asyncio.run(
        web_run.run_matrix(
            tasks=tasks,
            cells=["cli-solo"],
            model=None,
            budget=500,
            task_timeout=5,
            database_url=None,
            workdir_base=tmp_path,
            log=lambda _m: None,
        )
    )
    records = results["records"]
    assert records[0]["task_id"] == "w7c03crash-0"
    assert records[0]["status"] == "error", records[0]
    # Never 0 tokens when tokens were consumed.
    assert records[0]["token_usage"]["total"] >= 1_000, records[0]
    assert records[0]["cost"] is not None, records[0]
    assert Decimal(str(records[0]["cost"]["amount"])) > 0
    assert records[0]["spine_errors"], records[0]
    # The 1,000 spent tokens count against the 500 cap: task 2 never starts.
    assert records[1]["status"] == "blocked"
    assert "budget_exceeded" in records[1]["error"], records[1]
    assert calls == ["w7c03crash-0"], calls

    # -- web cell: spend recorded only in ctx.outcome reaches the record too --
    async def _sink_then_raise(**kwargs):
        sink = kwargs.get("spend_sink")
        if sink is not None:
            sink["ctx"] = SimpleNamespace(
                outcome={"tokens": {"input": 700, "output": 300, "total": 1_000}},
                runtime=None,
                agent_id="eval-primary",
            )
        raise RuntimeError("web runner exploded after journaling spend")

    monkeypatch.setattr(web_run, "run_web_task", _sink_then_raise)
    # The matrix probes/seed the web cell before tasks run — stub those out so
    # the test needs no live database.
    monkeypatch.setattr(web_run, "probe_web", lambda _url: None)
    monkeypatch.setattr(
        web_run,
        "seed_eval_tenant",
        lambda _url, _tag: {
            "tenant_id": "t",
            "org_id": "o",
            "project_id": "p",
        },
    )
    results2 = asyncio.run(
        web_run.run_matrix(
            tasks=tasks,
            cells=["web-solo"],
            model=None,
            budget=500,
            task_timeout=5,
            database_url="postgresql+psycopg://stubbed.invalid/db",
            workdir_base=tmp_path,
            log=lambda _m: None,
        )
    )
    crashed = results2["records"][0]
    assert crashed["status"] == "error", crashed
    assert crashed["token_usage"]["total"] >= 1_000, crashed["token_usage"]
    assert crashed["token_usage"]["input"] >= 700, crashed["token_usage"]
    assert crashed["cost"] is not None, crashed
    assert results2["records"][1]["status"] == "blocked"
    assert "budget_exceeded" in results2["records"][1]["error"], results2["records"][1]


def test_w7_c03_orphaned_run_finalized(web_run, monkeypatch, tmp_path: Path) -> None:
    """An escaped web failure must close out the leased run it orphaned.

    Audit r4 finding: pre-fix the matrix catch-all wrote a FRESH record —
    null run_id/session_id, no trace — and never touched the leased Run row
    (no usage write, no terminal commit), leaving the durable spine
    leased-but-unfinalized. The spend sink now carries the run identity as
    soon as it is known, the error record keeps run_id/session_id/trace, and
    the catch-all attempts failure finalization: a record_terminal_usage
    write plus a terminal commit — with any resulting failure collected into
    spine_errors.
    """
    from types import SimpleNamespace

    tasks = [_mk_task(web_run, "w7c03orphan-1")]

    async def _sink_then_raise(**kwargs):
        sink = kwargs.get("spend_sink")
        record = web_run._base_record(kwargs["cell"], kwargs["task"])
        record["run_id"] = "run-orphan"
        record["session_id"] = "sess-orphan"
        if sink is not None:
            sink.update(
                {
                    "record": record,
                    "database_url": "postgresql+psycopg://stubbed.invalid/db",
                    "tenant_id": "tenant-x",
                    "ledger_model": "eval-stub",
                    "session_id": "sess-orphan",
                    "worker_id": "eval-worker-x",
                    "run_id": "run-orphan",
                    "epoch": 3,
                    "lease_ttl_seconds": 720,
                    "ctx": SimpleNamespace(
                        outcome={
                            "tokens": {"input": 700, "output": 300, "total": 1000}
                        },
                        runtime=None,
                        agent_id="eval-primary",
                    ),
                }
            )
        raise RuntimeError("web runner exploded after claim")

    calls: dict[str, list] = {"usage": [], "commit": []}

    def _fake_persist(database_url, tenant_id, run_id, model, outcome, **kw):
        calls["usage"].append(
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "tokens_hint": kw.get("tokens_hint"),
            }
        )
        return {"id": "u1", "amount": "0.00200000", "tokens": 1000}

    def _fake_commit(database_url, run_id, worker_id, epoch, status):
        calls["commit"].append(
            {
                "run_id": run_id,
                "worker_id": worker_id,
                "epoch": epoch,
                "status": status,
            }
        )
        return None

    monkeypatch.setattr(web_run, "run_web_task", _sink_then_raise)
    # The matrix probes/seeds the web cell before tasks run — stub those so
    # the test needs no live database.
    monkeypatch.setattr(web_run, "probe_web", lambda _url: None)
    monkeypatch.setattr(
        web_run,
        "seed_eval_tenant",
        lambda _url, _tag: {"tenant_id": "t", "org_id": "o", "project_id": "p"},
    )
    monkeypatch.setattr(web_run, "_persist_usage", _fake_persist)
    monkeypatch.setattr(web_run, "_safe_commit", _fake_commit)
    monkeypatch.setattr(web_run, "_run_status", lambda _url, _rid: "leased")
    monkeypatch.setattr(
        web_run,
        "_web_trace",
        lambda _url, _tenant, rid: {"kind": "postgres", "run_id": rid},
    )
    monkeypatch.setattr(
        web_run,
        "_ledger_cost",
        lambda _url, _rid, *, spine_errors=None: {
            "amount": "0.00200000",
            "source": "usage_records",
        },
    )

    def _drive() -> dict:
        return asyncio.run(
            web_run.run_matrix(
                tasks=tasks,
                cells=["web-solo"],
                model=None,
                budget=0,
                task_timeout=5,
                database_url="postgresql+psycopg://stubbed.invalid/db",
                workdir_base=tmp_path,
                log=lambda _m: None,
            )
        )

    results = _drive()
    crashed = results["records"][0]
    assert crashed["status"] == "error", crashed
    # The record keeps the run identity — never a fresh null-identity record.
    assert crashed["run_id"] == "run-orphan", crashed
    assert crashed["session_id"] == "sess-orphan", crashed
    assert crashed["trace"]["run_id"] == "run-orphan", crashed["trace"]
    assert crashed["token_usage"]["total"] >= 1_000, crashed["token_usage"]
    # Failure finalization was attempted on the orphaned lease: terminal
    # usage write + a "failed" terminal commit carrying the lease epoch.
    assert calls["usage"] == [
        {"run_id": "run-orphan", "tenant_id": "tenant-x", "tokens_hint": 1000}
    ], calls
    assert calls["commit"] == [
        {
            "run_id": "run-orphan",
            "worker_id": "eval-worker-x",
            "epoch": 3,
            "status": "failed",
        }
    ], calls["commit"]
    assert crashed["cost"]["amount"] == "0.00200000", crashed["cost"]
    assert any("unhandled task exception" in e for e in crashed["spine_errors"])

    # A failed finalization attempt is collected into spine_errors — never
    # silently dropped, and the commit is still attempted.
    calls["commit"].clear()

    def _boom_commit(database_url, run_id, worker_id, epoch, status):
        calls["commit"].append(
            {
                "run_id": run_id,
                "worker_id": worker_id,
                "epoch": epoch,
                "status": status,
            }
        )
        return "terminal commit failed: LeaseRejected"

    monkeypatch.setattr(web_run, "_safe_commit", _boom_commit)
    crashed2 = _drive()["records"][0]
    assert crashed2["status"] == "error", crashed2
    assert calls["commit"], "commit was never attempted"
    assert any(
        "LeaseRejected" in str(e) for e in crashed2["spine_errors"]
    ), crashed2["spine_errors"]


def test_w7_c03_workdir_prep_failure_keeps_records(
    web_run, monkeypatch, tmp_path: Path
) -> None:
    """A workdir-prep crash must not abort the matrix or lose prior records.

    _setup_workdir used to run BEFORE the per-task try: an rmtree failure on a
    locked file escaped run_matrix entirely, destroying every record already
    collected. Setup now runs inside the per-task containment — a prep failure
    becomes that task's status=error record and the matrix continues.
    """
    tasks = [_mk_task(web_run, f"w7c03prep-{i}") for i in range(3)]

    async def _ok_cli_task(
        *, cell, task, workdir, model, task_timeout, budget_remaining=None
    ):
        rec = web_run._base_record(cell, task)
        rec["status"] = "passed"
        rec["token_usage"] = {"input": 5, "output": 5, "total": 10}
        return rec

    real_setup = web_run._setup_workdir

    def _flaky_setup(task, base, cell):
        if task.task_id == "w7c03prep-1":
            raise PermissionError("locked file (injected)")
        return real_setup(task, base, cell)

    monkeypatch.setattr(web_run, "run_cli_task", _ok_cli_task)
    monkeypatch.setattr(web_run, "_setup_workdir", _flaky_setup)
    results = asyncio.run(
        web_run.run_matrix(
            tasks=tasks,
            cells=["cli-solo"],
            model=None,
            budget=0,
            task_timeout=5,
            database_url=None,
            workdir_base=tmp_path,
            log=lambda _m: None,
        )
    )
    by_id = {r["task_id"]: r for r in results["records"]}
    assert set(by_id) == {"w7c03prep-0", "w7c03prep-1", "w7c03prep-2"}, results
    # Task 1's already-completed record survived; task 3 still ran.
    assert by_id["w7c03prep-0"]["status"] == "passed", by_id["w7c03prep-0"]
    assert by_id["w7c03prep-2"]["status"] == "passed", by_id["w7c03prep-2"]
    failed = by_id["w7c03prep-1"]
    assert failed["status"] == "error", failed
    assert "PermissionError" in failed["error"] or "locked file" in failed["error"]
    assert failed["spine_errors"], failed
    # The results still write out — completed records are not lost.
    out = tmp_path / "results.json"
    out.write_text(json.dumps(results), encoding="utf-8")
    assert len(json.loads(out.read_text(encoding="utf-8"))["records"]) == 3
