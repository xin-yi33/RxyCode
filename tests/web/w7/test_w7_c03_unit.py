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
