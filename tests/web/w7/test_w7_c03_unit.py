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
