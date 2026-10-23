"""WEB-W7-C03 reproducible agent-eval runner: cli|web x solo|team cells.

Each cell runs the same fixed taskset (``evals/web/taskset.jsonl``) under the
same budget, producing one record per (cell, task):

* ``cli-solo`` — the existing eval path: ``evals.backends.AgentBackend`` drives
  a real ``AgentV2.run`` inside ``_headless_eval_runtime``.
* ``cli-team`` — the same real ``AgentV2`` driven through ``Session.prompt``
  with a ``/team`` prefix. ``AgentV2.run`` cannot reach the Coordinator (the
  ModeRouter lives in ``Session._dispatch_user_turn``), and ``Session.prompt``
  is exactly what the appserver worker calls for CLI turns — so this is the
  production CLI dispatch path, not a modeled one.
* ``web-solo`` / ``web-team`` — the real durable web run spine:
  ``create_run`` -> worker ``claim`` -> ``Session.prompt`` (``/solo`` or
  ``/team`` prefix; the prefix is also stored in the durable ``run.created``
  message) -> ``appserver`` AgentTask journals ``event/agent_started`` /
  ``event/agent_done`` into PostgreSQL -> ``eval.checks`` verdict event ->
  ``record_terminal_usage`` (usage_records + ``usage.updated``) ->
  ``commit_terminal``.  Token totals are read back from the durable
  ``event/agent_done`` snapshot via ``replay()``.

There is no Run.mode column — the mode is forced by the slash prefix in the
durable run message and recorded in the manifest ``mode_map``.  Team numbers
come from real Coordinator execution, never ``evals.team_metrics.project_team``.

Standalone usage (no ``evals.web`` package required):

    python evals/web/run.py --cells cli-solo --sample 3 \
        --out out.json --manifest manifest.json --task-timeout 300
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------
# Standalone bootstrap: run directly as ``python evals/web/run.py`` — bind the
# checkout like ``evals/__init__._bind_checkout`` and tests/conftest.py so the
# editable install can never shadow this worktree's AgentV2.
# --------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[2]
_PACKAGE_SRC = (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
    REPO / "packages" / "rxycode-protocol" / "src",
)
for _entry in (REPO, *_PACKAGE_SRC):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

import evals as _evals_pkg  # noqa: E402

_evals_pkg._bind_checkout()

from evals.tasks import Check, EvalTask, TaskSchemaError  # noqa: E402

#: Every supported (surface x mode) cell.
CELLS = ("cli-solo", "cli-team", "web-solo", "web-team")

#: Categories allowed in the web taskset (card WEB-W7-C03).
WEB_CATEGORIES = ("coding", "browser", "recovery", "remote")

#: The price book published by rxycode_server.usage.service (_PRICE_PER_TOKEN).
PRICE_VERSION = "2026-10"
PRICE_PER_TOKEN_USD = "0.000002"

#: How each cell forces its execution mode.  Recorded verbatim in the manifest
#: so a reviewer can audit *how* solo/team was selected — Run rows have no mode
#: field, so this manifest is the source of truth for the forcing method.
MODE_MAP = {
    "cli-solo": {
        "mode": "solo",
        "forcing": "agent.run-direct",
        "detail": "AgentBackend calls AgentV2.run() directly — inherent solo path.",
    },
    "cli-team": {
        "mode": "team",
        "forcing": "slash_prefix",
        "prefix": "/team",
        "detail": "Session.prompt('/team ...') -> ModeRouter (decided_by=user) -> Coordinator.run_team.",
    },
    "web-solo": {
        "mode": "solo",
        "forcing": "slash_prefix",
        "prefix": "/solo",
        "detail": "create_run message + Session.prompt carry '/solo ...'; user-forced SOLO.",
    },
    "web-team": {
        "mode": "team",
        "forcing": "slash_prefix",
        "prefix": "/team",
        "detail": "create_run message + Session.prompt carry '/team ...'; user-forced TEAM.",
    },
}

DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"

_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]*$")


class _CellBudgetExceeded(Exception):
    """In-flight token spend crossed the remaining per-cell budget.

    Raised by ``_await_budgeted`` after it has cancelled the in-flight task;
    ``spent``/``remaining`` are recorded so the record can show exactly how
    far past the cap the cancelled task ran.
    """

    def __init__(self, spent: int, remaining: int) -> None:
        self.spent = int(spent)
        self.remaining = int(remaining)
        super().__init__(
            f"budget_exceeded: in-flight spend {self.spent} tokens crossed the "
            f"remaining cell budget {self.remaining}"
        )


async def _await_budgeted(
    task: "asyncio.Task[Any]",
    *,
    timeout: float | None,
    budget_remaining: int | None,
    used_tokens,
    poll_interval: float = 1.0,
) -> Any:
    """Await *task* with a wall-clock cap AND a live token budget.

    The declared budget used to be consulted only between tasks; here the
    in-flight task is cancelled at the first poll where cumulative spend
    exceeds ``budget_remaining`` (overrun bound: one task's spend between
    polls — documented in the manifest ``budget_scope``).  ``used_tokens``
    is a zero-arg callable returning tokens burned by this task so far
    (``token_stats`` delta for real drivers; the runtime counter for stubs).

    Returns ``task.result()`` — including when the task completed inside the
    cancel race window.  Raises ``asyncio.TimeoutError`` or
    ``_CellBudgetExceeded`` after the task has been cancelled and gathered.
    """
    deadline = None if timeout is None else time.monotonic() + float(timeout)
    while True:
        slice_s = max(0.0, float(poll_interval))
        if deadline is not None:
            slice_s = min(slice_s, max(0.0, deadline - time.monotonic()))
        done, _pending = await asyncio.wait({task}, timeout=slice_s)
        if done:
            return task.result()
        if deadline is not None and time.monotonic() >= deadline:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise asyncio.TimeoutError()
        if budget_remaining is not None:
            spent = int(used_tokens() or 0)
            if spent > int(budget_remaining):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if task.cancelled():
                    raise _CellBudgetExceeded(spent, int(budget_remaining))
                exc = task.exception()
                if exc is not None:
                    raise exc
                return task.result()  # completed inside the cancel race window


# ---------------------------------------------------------------------------
# Taskset loading
# ---------------------------------------------------------------------------


@dataclass
class WebEvalTask:
    """One fixed task from ``taskset.jsonl`` (same check vocabulary as EvalTask)."""

    task_id: str
    category: str
    prompt: str
    checks: list[Check] = field(default_factory=list)
    setup_files: dict[str, str] = field(default_factory=dict)
    requires: list[str] = field(default_factory=list)
    expect: str = "pass"
    effect: Optional[str] = None
    source_commit: Optional[str] = None
    pinned_ref: Optional[str] = None
    note: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict, *, source: str = "<dict>") -> "WebEvalTask":
        if not isinstance(data, dict):
            raise TaskSchemaError(f"{source}: JSONL record must be a mapping")
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
            raise TaskSchemaError(f"{source}: invalid task_id {task_id!r}")
        category = data.get("category")
        if category not in WEB_CATEGORIES:
            raise TaskSchemaError(
                f"{source}: category must be one of {list(WEB_CATEGORIES)}, got {category!r}"
            )
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise TaskSchemaError(f"{source}: missing or empty 'prompt'")
        raw_checks = data.get("checks") or []
        if not isinstance(raw_checks, list) or not raw_checks:
            raise TaskSchemaError(f"{source}: 'checks' must be a non-empty list")
        checks = [Check.from_dict(c, task_id=task_id) for c in raw_checks]
        setup = data.get("setup") or {}
        setup_files = (setup.get("files") or {}) if isinstance(setup, dict) else {}
        if not isinstance(setup_files, dict):
            raise TaskSchemaError(f"{source}: 'setup.files' must be a mapping")
        for rel, content in setup_files.items():
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise TaskSchemaError(f"{source}: setup path {rel!r} must stay inside the workdir")
            if not isinstance(content, str):
                raise TaskSchemaError(f"{source}: setup file {rel!r} content must be a string")
        requires = data.get("requires") or []
        if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
            raise TaskSchemaError(f"{source}: 'requires' must be a list of strings")
        expect = data.get("expect") or "pass"
        if expect not in {"pass", "fail"}:
            raise TaskSchemaError(f"{source}: expect must be 'pass' or 'fail', got {expect!r}")
        source_commit = data.get("source_commit") or None
        pinned_ref = data.get("pinned_ref") or None
        if not source_commit and not pinned_ref:
            raise TaskSchemaError(
                f"{source}: task needs a pinned reference ('source_commit' or 'pinned_ref')"
            )
        return cls(
            task_id=task_id,
            category=category,
            prompt=prompt.strip(),
            checks=checks,
            setup_files=dict(setup_files),
            requires=list(requires),
            expect=expect,
            effect=(data.get("effect") or None),
            source_commit=source_commit,
            pinned_ref=pinned_ref,
            note=(data.get("note") or None),
            raw=dict(data),
        )

    @property
    def needs_workdir(self) -> bool:
        return self.to_eval_task().needs_workdir

    def to_eval_task(self) -> EvalTask:
        """Adapt to the evals scorer: identical Check objects, same semantics."""
        return EvalTask(
            id=self.task_id,
            category=self.category,
            prompt=self.prompt,
            setup_files=dict(self.setup_files),
            checks=list(self.checks),
            effect=self.effect,
        )


def load_taskset(path: Path | str) -> list[WebEvalTask]:
    """Load the fixed JSONL taskset, validating every record."""
    path = Path(path)
    tasks: list[WebEvalTask] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        task = WebEvalTask.from_dict(
            json.loads(line), source=f"{path.name}:{lineno}"
        )
        if task.task_id in seen:
            raise TaskSchemaError(f"{path.name}:{lineno}: duplicate task_id {task.task_id!r}")
        seen.add(task.task_id)
        tasks.append(task)
    if not tasks:
        raise TaskSchemaError(f"{path}: empty taskset")
    return tasks


def _canonical_taskset_payload(path: Path | str) -> bytes:
    """Normalize the file: parse each JSONL record and re-serialize it with
    sorted keys and compact separators so key order / whitespace in the source
    file never changes the hash."""
    records = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    text = (
        "\n".join(
            json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            for rec in records
        )
        + "\n"
    )
    return text.encode("utf-8")


def taskset_sha256(path: Path | str) -> str:
    """sha256 of the normalized taskset file — the taskset manifest hash."""
    return hashlib.sha256(_canonical_taskset_payload(path)).hexdigest()


def select_tasks(
    tasks: list[WebEvalTask],
    *,
    sample: int | None = None,
    task_ids: list[str] | None = None,
) -> list[WebEvalTask]:
    """Deterministic selection: explicit --task-ids win, else the first --sample N."""
    selected = list(tasks)
    if task_ids:
        wanted = set(task_ids)
        missing = wanted - {t.task_id for t in selected}
        if missing:
            raise TaskSchemaError(f"unknown task id(s): {sorted(missing)}")
        selected = [t for t in selected if t.task_id in wanted]
    if sample is not None and sample > 0:
        selected = selected[:sample]
    return selected


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    # Decode ourselves: locale codecs (e.g. GBK) cannot read diff bytes.
    return (out.stdout or b"").decode("utf-8", errors="replace").strip()


def _mask_url(url: str) -> str:
    """Keep the URL shape but never persist a password."""
    if not url or "@" not in url:
        return url
    head, _, tail = url.rpartition("@")
    scheme, _, userinfo = head.partition("://")
    user = userinfo.split(":", 1)[0]
    return f"{scheme}://{user}:***@{tail}"


def _sha256_file(path: Path | str) -> str | None:
    """sha256 of the file's bytes on disk — identifies the executed source even
    when the worktree is dirty (a commit hash alone cannot)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


#: Cap on the embedded evals/web diff so a dirty worktree cannot blow up the
#: manifest (the diff is context; ``executed_sources`` pins content exactly).
_DIFF_CAP = 200_000


def _evals_web_diff() -> str:
    """``git diff HEAD -- evals/web tests/web/w7`` — bounded, evals-web only."""
    diff = _git(["diff", "HEAD", "--", "evals/web", "tests/web/w7"])
    if len(diff) > _DIFF_CAP:
        diff = diff[:_DIFF_CAP] + "\n... <diff truncated at 200000 chars>"
    return diff


def _evals_web_dirty_paths() -> list[str]:
    """Porcelain lines scoped to the eval surface — catches untracked files,
    which ``git diff`` cannot show."""
    out = _git(["status", "--porcelain", "--", "evals/web", "tests/web/w7"])
    return [line for line in out.splitlines() if line.strip()]


def _active_model_info(model: str | None) -> dict[str, str]:
    """Read the configured model/provider WITHOUT ever copying the api key."""
    info: dict[str, str] = {"requested": model or "active"}
    try:
        from RxyCode.RxyCode1_1_0.config.settings import (
            get_active_model_config,
            get_model_config,
            load_config,
        )

        cfg = load_config()
        key = model or str(cfg.get("active_model") or "")
        if model and model in (cfg.get("models") or {}):
            model_cfg = get_model_config(model, cfg)
        else:
            model_cfg = get_active_model_config(cfg)
        info["config_key"] = key
        info["model_name"] = str(model_cfg.get("model_name") or key or "unknown")
        info["base_url"] = str(model_cfg.get("base_url") or "")
    except Exception as exc:
        # Exception text may name env vars like RXYCODE_API_KEY — keep only the
        # exception type so the manifest can never leak a secret reference.
        info["error"] = type(exc).__name__
    return info


def build_manifest(
    *,
    taskset_path: Path | str,
    tasks: list[WebEvalTask],
    cells: list[str],
    budget: int,
    model: str | None,
    database_url: str | None,
    started_at: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Everything needed to reproduce a run: taskset hash, code commit, model,
    provider endpoint (never the key), price version, budget, and the mode map.

    ``executed_sources`` pins sha256 of the executed harness files — a dirty
    worktree can no longer hide what actually ran behind a bare commit hash.
    When the worktree is dirty the manifest also carries the bounded
    ``git diff HEAD`` for the eval surface and its dirty path list.
    """
    dirty = bool(_git(["status", "--porcelain"]))
    return {
        "schema": "evals-web-manifest/v1",
        "taskset_sha256": taskset_sha256(taskset_path),
        "taskset_path": str(taskset_path),
        "task_ids": [t.task_id for t in tasks],
        "task_count": len(tasks),
        "cells": list(cells),
        "budget": int(budget),
        "budget_scope": (
            "max total tokens per cell; 0 = unlimited; enforced in-flight: an "
            "in-flight task is cancelled at the first poll where cumulative "
            "cell spend exceeds the cap, so recorded cell usage may exceed "
            "budget by at most one in-flight task's overrun between polls"
        ),
        "model": (model or _active_model_info(model).get("model_name") or "active"),
        "provider": _active_model_info(model),
        "price_version": PRICE_VERSION,
        "code_commit": _git(["rev-parse", "HEAD"]) or "unknown",
        "code_branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown",
        "worktree_dirty": dirty,
        "executed_sources": {
            "evals/web/run.py": _sha256_file(REPO / "evals" / "web" / "run.py"),
            "evals/web/report.py": _sha256_file(REPO / "evals" / "web" / "report.py"),
            "evals/web/taskset.jsonl": _sha256_file(taskset_path),
        },
        "evals_web_diff": _evals_web_diff() if dirty else "",
        "evals_web_dirty_paths": _evals_web_dirty_paths() if dirty else [],
        "mode_map": {cell: dict(MODE_MAP[cell]) for cell in cells},
        "python": sys.version.split()[0],
        "platform": _platform.platform(),
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "database_url": _mask_url(database_url) if database_url else None,
        **(dict(extra) if extra else {}),
    }


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


def _token_delta(start: tuple[int, int]) -> dict[str, int]:
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    inp = max(0, int(token_stats.input_tokens) - start[0])
    out = max(0, int(token_stats.output_tokens) - start[1])
    return {"input": inp, "output": out, "total": inp + out}


def _token_start() -> tuple[int, int]:
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    return (int(token_stats.input_tokens), int(token_stats.output_tokens))


def _usage(*, total: int, input_tokens: int = 0, output_tokens: int = 0) -> dict[str, int]:
    return {"input": int(input_tokens), "output": int(output_tokens), "total": int(total)}


def _estimate_cost(tokens: int, *, source: str = "price_table") -> dict[str, Any]:
    """Price-table estimate when no durable ledger row can be trusted.

    CLI cells always estimate (``price_table``); web cells fall back here
    when the usage_records write or read failed (``estimate/ledger_failed``)
    — consumed tokens must never report $0.  The source label lets the report
    separate ledger rows from estimates.
    """
    from decimal import Decimal

    amount = (Decimal(int(tokens)) * Decimal(PRICE_PER_TOKEN_USD)).quantize(
        Decimal("0.00000001")
    )
    return {
        "amount": format(amount, "f"),
        "currency": "USD",
        "source": source,
        "price_version": PRICE_VERSION,
    }


def _base_record(cell: str, task: WebEvalTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "cell": cell,
        "category": task.category,
        "status": "error",
        "oracle_status": None,
        "spine_errors": [],
        "expect": task.expect,
        "expected_failure": task.expect == "fail",
        "duration_s": 0.0,
        "token_usage": {"input": 0, "output": 0, "total": 0},
        "cost": None,
        "run_id": None,
        "session_id": None,
        "trace": None,
        "mode_forcing": dict(MODE_MAP[cell]),
        "error": "",
        "check_details": [],
        "answer_excerpt": "",
    }


def _blocked_record(cell: str, task: WebEvalTask, reason: str) -> dict[str, Any]:
    record = _base_record(cell, task)
    record["status"] = "blocked"
    record["error"] = reason
    return record


# ---------------------------------------------------------------------------
# CLI cells
# ---------------------------------------------------------------------------


async def run_cli_task(
    *,
    cell: str,
    task: WebEvalTask,
    workdir: Path,
    model: str | None,
    task_timeout: int,
    budget_remaining: int | None = None,
) -> dict[str, Any]:
    """One task through the real CLI path (AgentBackend / Session.prompt /team).

    ``budget_remaining`` is the cell's remaining token budget: the in-flight
    turn is cancelled at the first poll where the task's spend exceeds it
    (status ``blocked``, reason ``budget_exceeded``; spend up to cancellation
    is still recorded).
    """
    from evals.backends import (
        AgentBackend,
        BackendResult,
        _extract_agent_tools,
        _headless_eval_runtime,
        make_agent_factory,
    )
    from evals.runner import is_provider_infra_error, run_checks
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        clear_session_runtime,
        reset_session_binding,
        set_working_directory,
    )

    record = _base_record(cell, task)
    start = time.monotonic()
    token0 = _token_start()
    emitted: list[Any] = []
    session_id = f"eval-{cell}-{uuid.uuid4().hex[:12]}"
    local_run_id = f"cli-{uuid.uuid4().hex}"
    budget_hit: _CellBudgetExceeded | None = None

    try:
        if cell == "cli-solo":
            backend = AgentBackend(make_agent_factory(model_name=model))
            inner = asyncio.ensure_future(
                backend.run(task.prompt, workdir, effect=task.effect)
            )
            try:
                result = await _await_budgeted(
                    inner,
                    timeout=task_timeout,
                    budget_remaining=budget_remaining,
                    used_tokens=lambda: _token_delta(token0)["total"],
                )
            except asyncio.TimeoutError:
                result = BackendResult(
                    answer="",
                    token_usage=_token_delta(token0),
                    error=f"task timed out after {task_timeout}s",
                )
            except _CellBudgetExceeded as exc:
                budget_hit = exc
                result = BackendResult(
                    answer="",
                    token_usage=_token_delta(token0),
                    error=str(exc),
                )
            answer = result.answer
            tools_used = result.tools_used
            error = result.error
            usage = result.token_usage or _token_delta(token0)
        else:  # cli-team — Session.prompt dispatch (production CLI turn path)
            from RxyCode.RxyCode1_1_0.core.session import Session
            from RxyCode.RxyCode1_1_0.main import dispatch_surface_prompt

            agent = make_agent_factory(model_name=model)(session_id=session_id)
            session_token = bind_session(session_id)
            result_status = "failed"
            try:
                with _headless_eval_runtime(
                    workspace_root=workdir,
                    extra_write_paths=[str(workdir)],
                ):
                    session = Session(
                        session_id=session_id,
                        workspace_root=workdir,
                        emit=emitted.append,
                    )
                    set_working_directory(workdir)
                    latest_token = bind_session("latest")
                    try:
                        set_working_directory(workdir)
                    finally:
                        reset_session_binding(latest_token)
                    try:
                        prompt_result = await _await_budgeted(
                            asyncio.ensure_future(
                                dispatch_surface_prompt(
                                    "cli",
                                    session,
                                    agent,
                                    f"/team {task.prompt}",
                                    mode="build",
                                    run_id=local_run_id,
                                )
                            ),
                            timeout=task_timeout,
                            budget_remaining=budget_remaining,
                            used_tokens=lambda: _token_delta(token0)["total"],
                        )
                        result_status = prompt_result.status
                        answer = prompt_result.answer or ""
                        error = (
                            ""
                            if result_status == "succeeded"
                            else (prompt_result.detail or f"prompt status {result_status}")
                        )
                    except asyncio.TimeoutError:
                        answer = ""
                        error = f"task timed out after {task_timeout}s"
                    except _CellBudgetExceeded as exc:
                        budget_hit = exc
                        answer = ""
                        error = str(exc)
                usage = _token_delta(token0)
                tools_used = _extract_agent_tools(agent)
            except Exception as exc:
                usage = _token_delta(token0)
                tools_used = _extract_agent_tools(agent)
                answer = ""
                error = f"{type(exc).__name__}: {exc}"
            finally:
                reset_session_binding(session_token)
                clear_session_runtime(session_id)
                clear_session_runtime("latest")
        duration = time.monotonic() - start
        record["duration_s"] = round(duration, 3)
        record["token_usage"] = _usage(
            total=usage.get("total", 0),
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
        )
        record["session_id"] = session_id
        record["run_id"] = local_run_id
        record["trace"] = {
            "kind": "in-process",
            "local_run_id": local_run_id,
            "session_id": session_id,
            "notifications": len(emitted),
            "note": "CLI cells have no durable store; see manifest mode_map.",
        }
        record["cost"] = _estimate_cost(record["token_usage"]["total"])
        record["answer_excerpt"] = (answer or "")[:500]

        if budget_hit is not None:
            # Cancelled mid-flight at the declared cap — blocked, never counted
            # as an oracle outcome; the spend up to cancellation stays above.
            record["status"] = "blocked"
            record["error"] = str(budget_hit)
            return record
        if error and is_provider_infra_error(error):
            record["status"] = "blocked"
            record["error"] = f"provider infra: {error}"
            return record
        timed_out = bool(error) and error.startswith("task timed out")
        if error and not timed_out:
            record["status"] = "error"
            record["error"] = error
            return record

        # The turn finished — or the wall-clock cap cut it mid-flight. Either
        # way the oracle runs on the final workspace state: a timed-out task
        # whose artifacts are complete is a pass (with the timeout annotated),
        # not a silent error.
        eval_task = task.to_eval_task()
        passed, details = run_checks(
            eval_task,
            workdir=workdir,
            agent_answer=answer or "",
            tools_used=tools_used or [],
        )
        record["check_details"] = details
        record["oracle_status"] = "passed" if passed else "failed"
        record["status"] = record["oracle_status"]
        msgs = [d["message"] for d in details if not d["passed"] and d["message"]]
        if timed_out:
            note = error + " — oracle evaluated on the final workspace state"
            record["error"] = (note + ("; " + "; ".join(msgs)[:300] if msgs else ""))[:500]
        elif not passed:
            record["error"] = "; ".join(msgs)[:500] or "one or more checks failed"
        return record
    except Exception as exc:  # harness-level failure
        record["duration_s"] = round(time.monotonic() - start, 3)
        record["token_usage"] = _usage(total=_token_delta(token0)["total"])
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["cost"] = _estimate_cost(record["token_usage"]["total"])
        return record


# ---------------------------------------------------------------------------
# Web cells — durable run spine
# ---------------------------------------------------------------------------


def seed_eval_tenant(database_url: str, tag: str) -> dict[str, str]:
    """Create a fresh tenant/org/project under which eval sessions hang."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import Organization, Project, User

    suffix = uuid.uuid4().hex[:8]
    tenant = f"eval-w7c03-{tag}-{suffix}"
    org_id = f"org-{tenant}"
    project_id = f"prj-{tenant}"
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with SASession(engine) as db:
            db.add(User(id=f"user-{tenant}", github_id=None, kind="local"))
            db.add(Organization(id=org_id, tenant_id=tenant))
            db.add(
                Project(
                    id=project_id,
                    tenant_id=tenant,
                    name=f"w7c03-{tag}",
                    repo_config={},
                )
            )
            db.commit()
    finally:
        engine.dispose()
    return {"tenant_id": tenant, "org_id": org_id, "project_id": project_id}


def probe_web(database_url: str) -> str | None:
    """None when the database is reachable and migrated; an error string else."""
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    except Exception as exc:
        return f"postgres unreachable: {type(exc).__name__}: {exc}"
    try:
        from rxycode_server.persistence.migrate import upgrade_head

        upgrade_head(database_url)
    except Exception as exc:
        return f"alembic upgrade_head failed: {type(exc).__name__}: {exc}"
    return None


@dataclass
class WebRunCtx:
    """What a prompt driver sees: the journaled runtime plus run coordinates."""

    runtime: Any
    agent_id: str
    workdir: Path
    message: str
    run_id: str
    session_id: str
    session: Any = None
    agent: Any = None
    emitted: list = field(default_factory=list)
    outcome: dict = field(default_factory=dict)


async def _default_web_driver(ctx: WebRunCtx) -> str:
    """The real turn: Session.prompt inside the headless eval config."""
    from evals.backends import _extract_agent_tools, _headless_eval_runtime
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        clear_session_runtime,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.main import dispatch_surface_prompt

    token0 = _token_start()
    session_token = bind_session(ctx.session_id)
    result = None
    try:
        with _headless_eval_runtime(
            workspace_root=ctx.workdir,
            extra_write_paths=[str(ctx.workdir)],
        ):
            set_working_directory(ctx.workdir)
            # Mirror AgentBackend: tool threads that lose the ContextVar
            # binding resolve to "latest" — seed the same cwd there too.
            latest_token = bind_session("latest")
            try:
                set_working_directory(ctx.workdir)
            finally:
                reset_session_binding(latest_token)
            result = await dispatch_surface_prompt(
                "web",
                ctx.session,
                ctx.agent,
                ctx.message,
                mode="build",
                run_id=ctx.run_id,
            )
    finally:
        reset_session_binding(session_token)
        clear_session_runtime(ctx.session_id)
        clear_session_runtime("latest")
        # Token accounting runs in finally: on timeout the main task is
        # cancelled mid-prompt, but the partial delta is real spend and must
        # reach the runtime snapshot + record, never be written as 0.
        delta = _token_delta(token0)
        ctx.runtime.record_token_usage(ctx.agent_id, delta["total"])
        ctx.outcome["tokens"] = delta
        ctx.outcome["tools"] = _extract_agent_tools(ctx.agent)
    if result is None:
        raise RuntimeError("prompt produced no result")
    ctx.outcome["prompt_status"] = getattr(result, "status", "")
    ctx.outcome["detail"] = getattr(result, "detail", "")
    if getattr(result, "status", "") != "succeeded":
        raise RuntimeError(ctx.outcome["detail"] or f"prompt status {result.status}")
    return result.answer or ""


def _agent_done_event_id(database_url: str, run_id: str) -> str:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import RunEvent

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with SASession(engine) as db:
            row = db.scalars(
                select(RunEvent.event_id)
                .where(RunEvent.run_id == run_id, RunEvent.type == "event/agent_done")
                .order_by(RunEvent.seq.desc())
                .limit(1)
            ).first()
    finally:
        engine.dispose()
    return str(row) if row else uuid.uuid4().hex


async def run_web_task(
    *,
    database_url: str,
    org: dict[str, str],
    task: WebEvalTask,
    workdir: Path,
    cell: str,
    model: str | None,
    task_timeout: int,
    request_nonce: str,
    prompt_driver=None,
    journal_cap: int = 100,
    budget_remaining: int | None = None,
    spend_sink: dict | None = None,
) -> dict[str, Any]:
    """Execute one task through the real durable web-run spine.

    Order (production order): SessionRow -> create_run -> claim -> journal ->
    prompt -> checks -> eval.checks event -> record_terminal_usage ->
    commit_terminal.  ``prompt_driver`` overrides only the model interaction
    (deterministic tests); everything around it — rows, events, usage ledger —
    is the real production machinery.

    ``budget_remaining`` is the cell's remaining token budget: the in-flight
    turn is cancelled at the first poll where its spend exceeds it (status
    ``blocked``, reason ``budget_exceeded``).  Every required durable write —
    the terminal eval event, the ``usage_records`` row, the terminal commit —
    is tracked in ``spine_errors``; if any of them did not land the record is
    ``error`` regardless of the oracle verdict (``oracle_status`` keeps it).

    ``spend_sink`` (optional): a caller-owned dict that receives the run
    identity (``record``, ``run_id``, ``session_id``, ``worker_id``,
    ``epoch``, lease ttl, ``tenant_id``, ``ledger_model``) as it becomes
    known, plus ``ctx`` once the run context exists. If an exception escapes
    this function entirely (e.g. an oracle file-read failure during
    finalization), the caller can still recover the spend the runner
    journaled — ``ctx.outcome["tokens"]`` and the runtime token counter —
    keep the run identity on the error record, and attempt failure
    finalization on the orphaned lease instead of writing a 0-token
    null-identity record.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.events.store import append_event
    from rxycode_server.persistence.models import SessionRow
    from rxycode_server.runs.service import create_run
    from rxycode_worker.agent_events import (
        clear_web_run,
        publish_database_url,
        remember_web_run,
    )
    from rxycode_worker.supervisor import claim

    tenant_id = org["tenant_id"]
    prefix = MODE_MAP[cell]["prefix"]
    # The usage ledger records the resolved model name, never the bare "active"
    # alias — the manifest already maps that alias to the configured provider.
    ledger_model = (
        model
        or _active_model_info(model).get("model_name")
        or "active"
    )
    message = f"{prefix} {task.prompt}"
    record = _base_record(cell, task)
    session_id = uuid.uuid4().hex
    worker_id = f"eval-worker-{uuid.uuid4().hex[:8]}"
    emitted: list[Any] = []
    run_id = ""
    epoch = None
    start = time.monotonic()
    answer = ""
    turn_error = ""
    budget_hit: _CellBudgetExceeded | None = None
    # Hoisted so every exit path — including setup-failure cleanup and a
    # mid-flight budget cancel — can persist the spend actually consumed.
    outcome: dict[str, Any] = {}
    ctx: WebRunCtx | None = None
    poll_token0 = _token_start()
    if spend_sink is not None:
        # Publish the run identity as it becomes known so even a fully
        # escaping failure lets the caller keep run_id/session_id/lease
        # coordinates (and the partially-built record — including whatever
        # trace refs were set) instead of writing a fresh null-identity
        # record.
        spend_sink.update(
            {
                "record": record,
                "database_url": database_url,
                "tenant_id": tenant_id,
                "ledger_model": ledger_model,
                "session_id": session_id,
                "worker_id": worker_id,
            }
        )

    try:
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with SASession(engine) as db:
                db.add(
                    SessionRow(
                        id=session_id,
                        tenant_id=tenant_id,
                        project_id=org["project_id"],
                        title=task.task_id,
                    )
                )
                db.commit()
        finally:
            engine.dispose()

        accepted = create_run(
            database_url,
            tenant_id=tenant_id,
            session_id=session_id,
            message=message,
            target_id=f"local:{task.task_id}",
            permission_profile="full_auto",
            request_id=f"w7c03-{request_nonce}-{cell}-{task.task_id}",
        )
        run_id = accepted.run_id
        record["run_id"] = run_id
        record["session_id"] = session_id
        if spend_sink is not None:
            spend_sink["run_id"] = run_id
        lease_ttl = max(600, int(task_timeout) + 120)
        epoch = claim(
            database_url,
            run_id,
            worker_id,
            ttl_seconds=lease_ttl,
        )
        if epoch is None:
            raise RuntimeError("worker lease refused for a fresh run")
        if spend_sink is not None:
            # The lease is held from here on — worker/epoch/ttl are exactly
            # what a terminal commit needs if a later stage escapes.
            spend_sink["epoch"] = epoch
            spend_sink["lease_ttl_seconds"] = lease_ttl

        publish_database_url(database_url)
        remember_web_run(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            session_id=session_id,
        )

        journaled = {"count": 0}

        def _emit(notification: Any) -> None:
            emitted.append(notification)
            method = getattr(notification, "method", None)
            if (
                isinstance(method, str)
                and method.startswith("event/")
                and journaled["count"] < journal_cap
            ):
                journaled["count"] += 1
                try:
                    append_event(
                        database_url,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        event_type=f"notify.{method}",
                        payload={"text": str(notification)[:1500]},
                    )
                except Exception:
                    pass

        from appserver.agent_runtime import AgentConfig, AgentRuntime
        from appserver.agent_task import LifecycleState
        from appserver.eventbus import AppendOnlyLog, EventBus

        session = None
        agent = None
        if prompt_driver is None:
            from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
            from RxyCode.RxyCode1_1_0.core.session import Session

            session = Session(
                session_id=session_id,
                workspace_root=workdir,
                emit=_emit,
            )
            agent = AgentV2(model_name=model, session_id=session_id)
            from evals.backends import bind_eval_session

            bind_eval_session(agent, session_id)

        ctx = WebRunCtx(
            runtime=None,  # filled after AgentRuntime exists
            agent_id="eval-primary",
            workdir=workdir,
            message=message,
            run_id=run_id,
            session_id=session_id,
            session=session,
            agent=agent,
            emitted=emitted,
            outcome=outcome,
        )
        if spend_sink is not None:
            # Publish the run context so the matrix can recover journaled
            # spend (outcome tokens / runtime counter) even if an exception
            # escapes this function entirely.
            spend_sink["ctx"] = ctx
            spend_sink["outcome"] = outcome
        driver = prompt_driver or _default_web_driver

        async def _target(_task_str: str, checkpoint: object | None = None) -> str:
            return await driver(ctx)

        runtime = AgentRuntime(
            EventBus(AppendOnlyLog()),
            run_factory=lambda _cfg: _target,
        )
        ctx.runtime = runtime
        agent_task = await runtime.spawn(
            AgentConfig(
                agent_id=ctx.agent_id,
                model=model or "active",
                # The declared eval cap, not a decorative ceiling: 0 selects
                # the runtime's shared pool (uncapped here means the eval ran
                # with --budget 0), otherwise the remaining cell budget.
                budget_tokens=(
                    max(0, int(budget_remaining))
                    if budget_remaining is not None
                    else 0
                ),
            )
        )
        main_task = agent_task._main_task
        assert main_task is not None
        try:
            answer = await _await_budgeted(
                main_task,
                timeout=task_timeout,
                budget_remaining=budget_remaining,
                # Real drivers burn via token_stats; stub drivers journal
                # through the runtime counter — the honest in-flight spend
                # is whichever counter is larger.
                used_tokens=lambda: max(
                    _token_delta(poll_token0)["total"],
                    int(ctx.runtime.token_usage(ctx.agent_id))
                    if ctx.runtime is not None
                    else 0,
                ),
            ) or ""
            # _run_main swallows target exceptions into state FAILED; recover
            # the real error so the record is honest.
            if agent_task.state != LifecycleState.DONE:
                last = getattr(agent_task, "_last_error", None)
                turn_error = (
                    f"{type(last).__name__}: {last}"
                    if last is not None
                    else f"agent ended in state {agent_task.state}"
                )
                answer = ""
        except asyncio.TimeoutError:
            turn_error = f"task timed out after {task_timeout}s"
            try:
                await agent_task.interrupt()
            except Exception:
                pass
        except _CellBudgetExceeded as exc:
            # The declared cap tripped mid-flight: cancel the turn like a
            # timeout, but keep the distinct reason for the record.
            budget_hit = exc
            try:
                await agent_task.interrupt()
            except Exception:
                pass
        except Exception as exc:
            turn_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        # The run row still exists — close it out so the durable log ends in a
        # terminal state and any consumed tokens reach the ledger.
        record["duration_s"] = round(time.monotonic() - start, 3)
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        spine_errors: list[str] = []
        try:
            _finalize_orphaned_web_run(
                record,
                database_url=database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                worker_id=worker_id,
                epoch=epoch,
                ledger_model=ledger_model,
                ctx=ctx,
                outcome=outcome,
                tokens_hint=_token_delta(poll_token0)["total"],
                spine_errors=spine_errors,
            )
        except Exception as finalize_exc:
            spine_errors.append(
                f"orphan finalization raised: "
                f"{type(finalize_exc).__name__}: {finalize_exc}"
            )
        record["spine_errors"] = spine_errors
        return record
    finally:
        try:
            clear_web_run()
        except Exception:
            pass

    try:
        return _finalize_turn_record(
            record,
            task=task,
            workdir=workdir,
            answer=answer,
            turn_error=turn_error,
            budget_hit=budget_hit,
            outcome=outcome,
            ctx=ctx,
            poll_token0=poll_token0,
            start=start,
            database_url=database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            worker_id=worker_id,
            epoch=epoch,
            ledger_model=ledger_model,
        )
    except Exception as exc:
        # The turn's finalization crashed AFTER the run was claimed — the
        # lease is still held and no terminal status was committed. Keep the
        # record's run identity and attempt failure finalization on the
        # orphaned lease so the durable spine never stays
        # leased-but-unfinalized; the matrix catch-all is the same backstop
        # if even this fails to land.
        record["duration_s"] = round(time.monotonic() - start, 3)
        record["status"] = "error"
        prior_error = str(record.get("error") or "")
        record["error"] = (
            f"post-claim finalization crashed: {type(exc).__name__}: {exc}"
            + (f" | prior: {prior_error}" if prior_error else "")
        )[:500]
        spine_errors = list(record.get("spine_errors") or [])
        spine_errors.append(
            f"post-claim crash contained: {type(exc).__name__}: {exc}"
        )
        try:
            _finalize_orphaned_web_run(
                record,
                database_url=database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                worker_id=worker_id,
                epoch=epoch,
                ledger_model=ledger_model,
                ctx=ctx,
                outcome=outcome,
                tokens_hint=_token_delta(poll_token0)["total"],
                spine_errors=spine_errors,
            )
        except Exception as finalize_exc:
            spine_errors.append(
                f"orphan finalization raised: "
                f"{type(finalize_exc).__name__}: {finalize_exc}"
            )
        record["spine_errors"] = spine_errors
        if record.get("cost") is None:
            record["cost"] = _estimate_cost(
                int((record.get("token_usage") or {}).get("total") or 0),
                source="estimate/ledger_failed",
            )
        return record


def _finalize_turn_record(
    record: dict[str, Any],
    *,
    task: WebEvalTask,
    workdir: Path,
    answer: str,
    turn_error: str,
    budget_hit: _CellBudgetExceeded | None,
    outcome: dict[str, Any],
    ctx: "WebRunCtx | None",
    poll_token0: tuple[int, int],
    start: float,
    database_url: str,
    tenant_id: str,
    run_id: str,
    worker_id: str,
    epoch: int | None,
    ledger_model: str,
) -> dict[str, Any]:
    """Turn a finished/cancelled/errored web turn into the final record.

    Runs after the agent task resolved: budget-cancel ``blocked``, provider
    infra ``blocked``, turn error ``error``, otherwise the oracle verdict —
    and every path journals its durable spine (eval events, usage_records,
    terminal commit, trace).  An exception escaping anywhere in here leaves
    the run leased-but-unfinalized; the caller's containment converts that
    into a failure-finalization attempt via ``_finalize_orphaned_web_run``.
    """
    from evals.runner import is_provider_infra_error, run_checks

    record["duration_s"] = round(time.monotonic() - start, 3)
    record["answer_excerpt"] = (answer or "")[:500]

    if budget_hit is not None:
        # Cancelled at the declared cap mid-flight: blocked (excluded from the
        # rate) with the spend so far journaled into the durable spine.
        measured = dict(outcome.get("tokens") or {})
        consumed = max(
            int(measured.get("total") or 0),
            int(ctx.runtime.token_usage(ctx.agent_id))
            if ctx is not None and ctx.runtime is not None
            else 0,
            _token_delta(poll_token0)["total"],
        )
        record["status"] = "blocked"
        record["error"] = str(budget_hit)
        record["token_usage"] = _usage(
            total=consumed,
            input_tokens=int(measured.get("input") or 0),
            output_tokens=int(measured.get("output") or 0),
        )
        spine_errors = []
        _append_spine_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="eval.budget_exceeded",
            payload={
                "task_id": task.task_id,
                "spent": consumed,
                "remaining": budget_hit.remaining,
            },
            spine_errors=spine_errors,
        )
        usage_record = _persist_usage(
            database_url, tenant_id, run_id, ledger_model, outcome,
            tokens_hint=consumed,
        )
        if usage_record is None:
            spine_errors.append("usage_records write did not durably land")
        commit_err = _safe_commit(
            database_url, run_id, worker_id, epoch, "cancelled"
        )
        if commit_err:
            spine_errors.append(commit_err)
        record["trace"] = _web_trace(database_url, tenant_id, run_id)
        record["cost"] = _ledger_cost(
            database_url, run_id, spine_errors=spine_errors
        ) or _estimate_cost(consumed, source="estimate/ledger_failed")
        record["spine_errors"] = spine_errors
        if spine_errors:
            record["status"] = "error"
            record["error"] = (record["error"] + " | spine: " + "; ".join(spine_errors))[:500]
        return record

    if turn_error and is_provider_infra_error(turn_error):
        record["status"] = "blocked"
        record["error"] = f"provider infra: {turn_error}"
        # Spend consumed before the provider died is real — persist it instead
        # of dropping it, and keep every required spine write honest.
        spine_errors = []
        _append_spine_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="eval.turn_failed",
            payload={
                "error": turn_error,
                "task_id": task.task_id,
                "provider_infra": True,
            },
            spine_errors=spine_errors,
        )
        usage_record = _persist_usage(
            database_url, tenant_id, run_id, ledger_model, outcome
        )
        if usage_record is None:
            spine_errors.append("usage_records write did not durably land")
        commit_err = _safe_commit(
            database_url, run_id, worker_id, epoch, "failed"
        )
        if commit_err:
            spine_errors.append(commit_err)
        record["trace"] = _web_trace(database_url, tenant_id, run_id)
        record["cost"] = _ledger_cost(
            database_url, run_id, spine_errors=spine_errors
        )
        measured = dict(outcome.get("tokens") or {})
        done_tokens = int(record["trace"].get("agent_done_tokens") or 0)
        total = max(
            done_tokens,
            int(measured.get("total") or 0),
            _token_delta(poll_token0)["total"],
        )
        record["token_usage"] = _usage(
            total=total,
            input_tokens=int(measured.get("input") or 0),
            output_tokens=int(measured.get("output") or 0),
        )
        if record["cost"] is None:
            record["cost"] = _estimate_cost(
                total, source="estimate/ledger_failed"
            )
        record["spine_errors"] = spine_errors
        if spine_errors:
            # The durable claim ("blocked by provider outage") itself did not
            # land — the record is an error, not a clean blocked verdict.
            record["status"] = "error"
            record["error"] = (record["error"] + " | spine: " + "; ".join(spine_errors))[:500]
        return record
    timed_out = bool(turn_error) and turn_error.startswith("task timed out")
    if turn_error and not timed_out:
        spine_errors = []
        _append_spine_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="eval.turn_failed",
            payload={"error": turn_error, "task_id": task.task_id},
            spine_errors=spine_errors,
        )
        usage_record = _persist_usage(
            database_url, tenant_id, run_id, ledger_model, outcome
        )
        if usage_record is None:
            spine_errors.append("usage_records write did not durably land")
        commit_err = _safe_commit(
            database_url, run_id, worker_id, epoch, "failed"
        )
        if commit_err:
            spine_errors.append(commit_err)
        record["status"] = "error"
        record["error"] = turn_error
        record["trace"] = _web_trace(database_url, tenant_id, run_id)
        record["cost"] = _ledger_cost(
            database_url, run_id, spine_errors=spine_errors
        )
        done_tokens = int(record["trace"].get("agent_done_tokens") or 0)
        measured = dict(outcome.get("tokens") or {})
        record["token_usage"] = _usage(
            total=done_tokens or int(measured.get("total") or 0),
            input_tokens=int(measured.get("input") or 0),
            output_tokens=int(measured.get("output") or 0),
        )
        if record["cost"] is None:
            record["cost"] = _estimate_cost(
                record["token_usage"]["total"], source="estimate/ledger_failed"
            )
        record["spine_errors"] = spine_errors
        if spine_errors:
            record["error"] = (record["error"] + " | spine: " + "; ".join(spine_errors))[:500]
        return record

    # The turn completed — or hit the wall-clock cap (the agent task was
    # interrupted above). Either way the oracle runs on the final workspace
    # state; a timeout stays visible in ``error`` and the durable run commits
    # "failed" (the turn never finished), while the record reflects the oracle.
    eval_task = task.to_eval_task()
    passed, details = run_checks(
        eval_task,
        workdir=workdir,
        agent_answer=answer or "",
        tools_used=list(outcome.get("tools") or []),
    )
    record["check_details"] = details
    record["oracle_status"] = "passed" if passed else "failed"
    record["status"] = record["oracle_status"]
    msgs = [d["message"] for d in details if not d["passed"] and d["message"]]
    if timed_out:
        note = turn_error + " — oracle evaluated on the final workspace state"
        record["error"] = (note + ("; " + "; ".join(msgs)[:300] if msgs else ""))[:500]
    elif not passed:
        record["error"] = "; ".join(msgs)[:500] or "one or more checks failed"

    spine_errors = []
    if timed_out:
        # agent_done never journals on a cancelled turn — mark why, durably.
        _append_spine_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="eval.turn_timeout",
            payload={
                "task_id": task.task_id,
                "error": turn_error,
                "tokens": int((outcome.get("tokens") or {}).get("total") or 0),
            },
            spine_errors=spine_errors,
        )
    _append_spine_event(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type="eval.checks",
        payload={
            "task_id": task.task_id,
            "status": record["status"],
            "expect": task.expect,
            "timed_out": timed_out,
            "checks": details[:20],
        },
        spine_errors=spine_errors,
    )
    usage_record = _persist_usage(database_url, tenant_id, run_id, ledger_model, outcome)
    if usage_record is None:
        spine_errors.append("usage_records write did not durably land")
    commit_err = _safe_commit(
        database_url, run_id, worker_id, epoch, "failed" if timed_out else "succeeded"
    )
    if commit_err:
        spine_errors.append(commit_err)
    trace = _web_trace(database_url, tenant_id, run_id)
    record["trace"] = trace
    record["cost"] = _ledger_cost(database_url, run_id, spine_errors=spine_errors)

    # Token totals come from the durable event/agent_done snapshot (via
    # replay); the measured delta is kept as an input/output split detail.
    done_tokens = int(trace.get("agent_done_tokens") or 0)
    measured = dict(outcome.get("tokens") or {})
    total = done_tokens or int(measured.get("total") or 0)
    record["token_usage"] = _usage(
        total=total,
        input_tokens=int(measured.get("input") or 0),
        output_tokens=int(measured.get("output") or 0),
    )
    if usage_record:
        record["cost"] = {
            "amount": usage_record.get("amount"),
            "currency": usage_record.get("currency", "USD"),
            "source": "usage_records",
            "price_version": PRICE_VERSION,
            "usage_record_id": usage_record.get("id"),
        }
    elif record["cost"] is None:
        # The ledger write/read failed but tokens WERE consumed — fall back
        # to the price-table estimate (labelled) rather than reporting $0,
        # same pattern as the budget/provider-failure paths.
        record["cost"] = _estimate_cost(total, source="estimate/ledger_failed")
    record["spine_errors"] = spine_errors
    if spine_errors:
        # The oracle ran, but part of the durable spine (eval.checks event /
        # usage_records row / terminal commit) never landed — the record is
        # an error, not a pass/fail on oracle verdict alone.
        record["status"] = "error"
        record["error"] = (
            (record["error"] + " | " if record["error"] else "")
            + "spine: "
            + "; ".join(spine_errors)
        )[:500]
    return record


def _append_spine_event(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    event_type: str,
    payload: dict,
    spine_errors: list[str],
) -> None:
    """Journal a REQUIRED durable event; a write failure lands in spine_errors
    so the caller can mark the record ``error`` instead of trusting the
    oracle verdict alone."""
    from rxycode_server.events.store import append_event

    try:
        append_event(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )
    except Exception as exc:
        spine_errors.append(
            f"{event_type} event write failed: {type(exc).__name__}: {exc}"
        )


def _persist_usage(
    database_url: str,
    tenant_id: str,
    run_id: str,
    model: str | None,
    outcome: dict,
    *,
    tokens_hint: int | None = None,
) -> dict[str, Any] | None:
    """Harness-owned terminal accounting: production has no caller today.

    ``None`` means the ``usage_records`` row did NOT durably land — callers
    must treat that as a spine failure, not as zero spend.  ``tokens_hint``
    carries the driver's own measurement when no ``agent_done`` snapshot or
    ``ctx.outcome`` total exists (e.g. a budget-cancelled turn).
    """
    from rxycode_server.events.store import replay
    from rxycode_server.usage.service import record_terminal_usage

    tokens = 0
    try:
        events = replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)[
            "events"
        ]
        for event in events:
            if event["type"] == "event/agent_done":
                tokens = int(event["payload"].get("tokens_used") or 0)
    except Exception:
        tokens = 0
    if not tokens:
        tokens = max(
            int((outcome.get("tokens") or {}).get("total") or 0),
            int(tokens_hint or 0),
        )
    try:
        return record_terminal_usage(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            model_id=model or "active",
            price_version=PRICE_VERSION,
            tokens=tokens,
            event_id=_agent_done_event_id(database_url, run_id),
        )
    except Exception:
        return None


def _safe_commit(
    database_url: str,
    run_id: str,
    worker_id: str,
    epoch: int | None,
    status: str,
) -> str | None:
    """Commit a terminal status; returns None on success, else the failure —
    a run left non-terminal is a spine failure the caller must record."""
    if not run_id or epoch is None:
        return None
    from rxycode_worker.supervisor import commit_terminal

    try:
        commit_terminal(database_url, run_id, worker_id, epoch, status)
    except Exception as exc:
        return f"terminal commit failed: {type(exc).__name__}: {exc}"
    return None


def _ledger_cost(
    database_url: str,
    run_id: str,
    *,
    spine_errors: list[str] | None = None,
) -> dict[str, Any] | None:
    """Read the durable usage_records row for cost. Never raises a DB error:
    a read failure during finalization is a spine error on that record
    (``status`` flips to ``error``), not a crash that could abort the matrix
    and lose the records already collected."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import UsageRecord

    try:
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with SASession(engine) as db:
                row = db.scalars(
                    select(UsageRecord).where(UsageRecord.run_id == run_id)
                ).first()
        finally:
            engine.dispose()
    except Exception as exc:
        if spine_errors is not None:
            spine_errors.append(
                f"usage_records read failed: {type(exc).__name__}: {exc}"
            )
        return None
    if row is None:
        return None
    return {
        "amount": row.amount,
        "currency": row.currency,
        "source": "usage_records",
        "price_version": row.price_version,
        "usage_record_id": row.id,
    }


def _web_trace(database_url: str, tenant_id: str, run_id: str) -> dict[str, Any]:
    """Durable trace refs for the record: replayed event seqs + token snapshot."""
    from rxycode_server.events.store import replay

    trace: dict[str, Any] = {
        "kind": "postgres",
        "run_id": run_id,
        "events_url": f"/api/v1/runs/{run_id}/events",
    }
    try:
        events = replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)[
            "events"
        ]
    except Exception as exc:
        trace["replay_error"] = f"{type(exc).__name__}: {exc}"
        return trace
    trace["event_count"] = len(events)
    trace["last_seq"] = max((int(e["seq"]) for e in events), default=0)
    for event in events:
        if event["type"] == "event/agent_done":
            trace["agent_done_seq"] = int(event["seq"])
            trace["agent_done_tokens"] = int(
                event["payload"].get("tokens_used") or 0
            )
        if event["type"] == "usage.updated":
            trace["usage_event_seq"] = int(event["seq"])
        if event["type"] == "eval.checks":
            trace["eval_checks_seq"] = int(event["seq"])
    return trace


#: Run statuses from which a lease can still be claimed or a terminal status
#: committed — mirrors ``rxycode_worker.supervisor._ACTIVE``.
_RUN_OPEN_STATUSES = {"pending", "leased", "running", "cancel_requested"}


def _run_status(database_url: str, run_id: str) -> str | None:
    """The Run row's status — ``None`` when the row or the read is missing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import Run

    try:
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with SASession(engine) as db:
                row = db.get(Run, run_id)
        finally:
            engine.dispose()
    except Exception:
        return None
    return getattr(row, "status", None) if row is not None else None


def _finalize_orphaned_web_run(
    record: dict[str, Any],
    *,
    database_url: str | None,
    tenant_id: str | None,
    run_id: str | None,
    worker_id: str | None,
    epoch: int | None,
    ledger_model: str | None,
    ctx: "WebRunCtx | None" = None,
    outcome: dict[str, Any] | None = None,
    tokens_hint: int = 0,
    spine_errors: list[str] | None = None,
) -> None:
    """Best-effort failure finalization for a leased run after a crash.

    An exception that escapes the normal turn-finalization path leaves the
    Run row leased: nothing persisted the consumed spend and nothing
    committed a terminal status.  This helper makes the same attempt every
    other failure path makes — ``record_terminal_usage`` for the consumed
    tokens, a fenced ``failed`` terminal commit (skipped when the row is
    already terminal, and reported when the lease metadata needed for the
    fence is missing), and durable trace refs — and fills ``record`` with the
    run identity, tokens, and cost (``estimate/ledger_failed`` fallback so
    burned tokens never report $0).  Every write failure lands in
    ``spine_errors`` so the caller marks the record ``error``; nothing here
    may raise the failure away a second time.
    """
    errors = spine_errors if spine_errors is not None else []
    if not (database_url and run_id):
        return  # no run was ever created — nothing leased to finalize
    if outcome is None:
        outcome = getattr(ctx, "outcome", None) or {}
    measured = dict(outcome.get("tokens") or {})
    runtime_tokens = 0
    runtime = getattr(ctx, "runtime", None) if ctx is not None else None
    if runtime is not None:
        try:
            runtime_tokens = int(runtime.token_usage(ctx.agent_id) or 0)
        except Exception:
            runtime_tokens = 0
    consumed = max(
        int(measured.get("total") or 0),
        runtime_tokens,
        int(tokens_hint or 0),
        int((record.get("token_usage") or {}).get("total") or 0),
    )
    try:
        usage_record = _persist_usage(
            database_url,
            tenant_id,
            run_id,
            ledger_model,
            outcome,
            tokens_hint=consumed,
        )
        if usage_record is None:
            errors.append("usage_records write did not durably land")
    except Exception as exc:
        errors.append(f"usage_records write raised: {type(exc).__name__}: {exc}")
    status = _run_status(database_url, run_id)
    if status is not None and status not in _RUN_OPEN_STATUSES:
        pass  # already terminal — a fenced retry would only produce noise
    elif not worker_id or epoch is None:
        errors.append(
            "orphaned run could not be committed: lease metadata missing "
            "(never claimed or claim crashed)"
        )
    else:
        try:
            commit_err = _safe_commit(
                database_url, run_id, worker_id, epoch, "failed"
            )
        except Exception as exc:
            commit_err = f"terminal commit raised: {type(exc).__name__}: {exc}"
        if commit_err:
            errors.append(commit_err)
    record["run_id"] = record.get("run_id") or run_id
    try:
        record["trace"] = record.get("trace") or _web_trace(
            database_url, tenant_id, run_id
        )
    except Exception as exc:
        errors.append(f"trace read failed: {type(exc).__name__}: {exc}")
    if consumed:
        record["token_usage"] = _usage(
            total=consumed,
            input_tokens=int(measured.get("input") or 0),
            output_tokens=int(measured.get("output") or 0),
        )
    if record.get("cost") is None:
        record["cost"] = _ledger_cost(
            database_url, run_id, spine_errors=errors
        ) or _estimate_cost(consumed, source="estimate/ledger_failed")


# ---------------------------------------------------------------------------
# Matrix driver
# ---------------------------------------------------------------------------


def _setup_workdir(task: WebEvalTask, base: Path, cell: str) -> Path:
    """A FRESH workdir per (cell, task): a stale artifact left by an earlier
    run would otherwise satisfy the next run's oracle."""
    workdir = base / cell / task.task_id
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for rel, content in task.setup_files.items():
        fp = workdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return workdir


async def run_matrix(
    *,
    tasks: list[WebEvalTask],
    cells: list[str],
    model: str | None,
    budget: int,
    task_timeout: int,
    database_url: str | None,
    workdir_base: Path,
    log=print,
) -> dict[str, Any]:
    """Serial execution over cells x tasks. Blocked is explicit, never silent."""
    records: list[dict[str, Any]] = []
    blocked_cells: dict[str, str] = {}
    web_probe: str | None = None
    web_checked = False
    org: dict[str, str] | None = None
    nonce = uuid.uuid4().hex[:8]

    for cell in cells:
        cell_tokens = 0
        cell_blocked_reason = ""
        if cell.startswith("web"):
            if not web_checked:
                web_checked = True
                if not database_url:
                    web_probe = "no --database-url and RXYCODE_WEB_DATABASE_URL unset"
                else:
                    web_probe = probe_web(database_url)
                    if web_probe is None:
                        try:
                            org = seed_eval_tenant(database_url, "suite")
                        except Exception as exc:
                            web_probe = f"tenant seed failed: {type(exc).__name__}: {exc}"
            if web_probe is not None:
                cell_blocked_reason = web_probe
                blocked_cells[cell] = web_probe
                for task in tasks:
                    records.append(_blocked_record(cell, task, web_probe))
                continue

        for index, task in enumerate(tasks, 1):
            if cell_blocked_reason:
                records.append(_blocked_record(cell, task, cell_blocked_reason))
                continue
            if budget and cell_tokens >= budget:
                reason = (
                    f"budget_exceeded: cell already spent {cell_tokens} tokens "
                    f"(cap {budget})"
                )
                records.append(_blocked_record(cell, task, reason))
                continue
            log(f"[{cell} {index}/{len(tasks)}] {task.task_id} ...")
            remaining = (budget - cell_tokens) if budget else None
            task_start = time.monotonic()
            # token_stats is process-global: the before/after delta measures
            # this task's real spend regardless of how the task exits —
            # including an exception escaping the runner.
            task_token0 = _token_start()
            # The web runner publishes its WebRunCtx here once it exists, so
            # even a fully-escaping failure lets the catch-all recover spend
            # journaled only in ctx.outcome / the runtime token counter.
            spend_sink: dict[str, Any] = {}
            try:
                # Workdir prep runs INSIDE the per-task containment: an
                # rmtree failure (e.g. a locked file) becomes this task's
                # error record instead of aborting the matrix and losing the
                # records already collected.
                workdir = _setup_workdir(task, workdir_base, cell)
                if cell.startswith("web"):
                    record = await run_web_task(
                        database_url=database_url,
                        org=org,
                        task=task,
                        workdir=workdir,
                        cell=cell,
                        model=model,
                        task_timeout=task_timeout,
                        request_nonce=nonce,
                        budget_remaining=remaining,
                        spend_sink=spend_sink,
                    )
                else:
                    record = await run_cli_task(
                        cell=cell,
                        task=task,
                        workdir=workdir,
                        model=model,
                        task_timeout=task_timeout,
                        budget_remaining=remaining,
                    )
            except Exception as exc:
                # Defense in depth: a harness failure that escapes the task
                # runner — a durable-store read during finalization, an
                # oracle file read, or the workdir prep above — must not
                # destroy the records already collected. Record this task as
                # an honest error and continue the matrix.
                #
                # The web runner publishes its in-flight record plus the run
                # identity (run_id/session_id/worker/epoch) into the spend
                # sink as they become known — reuse them so the escaped
                # failure keeps run_id / session_id / oracle_status / trace
                # refs instead of a fresh record with null identity.
                record = spend_sink.get("record") or _base_record(cell, task)
                record["status"] = "error"
                record["session_id"] = record.get("session_id") or spend_sink.get(
                    "session_id"
                )
                prior_error = str(record.get("error") or "")
                record["error"] = (
                    f"task setup/runner crashed: {type(exc).__name__}: {exc}"
                    + (f" | prior: {prior_error}" if prior_error else "")
                )[:500]
                record["duration_s"] = round(time.monotonic() - task_start, 3)
                # Spend consumed before the crash is real: recover it from
                # the token_stats delta and any ctx.outcome / runtime counter
                # the runner managed to record, so the record never shows 0
                # tokens for burned work and the cell budget (charged on
                # ``record["token_usage"]`` below) sees the true remaining
                # balance for subsequent tasks.
                delta = _token_delta(task_token0)
                measured: dict[str, Any] = {}
                runtime_tokens = 0
                ctx = spend_sink.get("ctx")
                if ctx is not None:
                    outcome = getattr(ctx, "outcome", None) or {}
                    measured = dict(outcome.get("tokens") or {})
                    runtime = getattr(ctx, "runtime", None)
                    if runtime is not None:
                        try:
                            runtime_tokens = int(
                                runtime.token_usage(ctx.agent_id) or 0
                            )
                        except Exception:
                            runtime_tokens = 0
                record["token_usage"] = _usage(
                    total=max(
                        delta["total"],
                        int(measured.get("total") or 0),
                        runtime_tokens,
                        int(
                            (record.get("token_usage") or {}).get("total") or 0
                        ),
                    ),
                    input_tokens=max(
                        delta["input"], int(measured.get("input") or 0)
                    ),
                    output_tokens=max(
                        delta["output"], int(measured.get("output") or 0)
                    ),
                )
                spine_errors = list(record.get("spine_errors") or [])
                spine_errors.append(
                    f"unhandled task exception (workdir setup or runner): "
                    f"{type(exc).__name__}: {exc}"
                )
                # A web run claimed before the crash is a LEASED row — the
                # runner's own containment normally finalizes it, but if the
                # failure escaped anyway (or that containment itself died),
                # make the same attempt here so the durable spine never shows
                # leased-but-unfinalized: usage ledger + terminal commit +
                # trace. Each resulting failure lands in spine_errors.
                if cell.startswith("web"):
                    try:
                        _finalize_orphaned_web_run(
                            record,
                            database_url=(
                                spend_sink.get("database_url") or database_url
                            ),
                            tenant_id=spend_sink.get("tenant_id"),
                            run_id=(
                                spend_sink.get("run_id")
                                or record.get("run_id")
                            ),
                            worker_id=spend_sink.get("worker_id"),
                            epoch=spend_sink.get("epoch"),
                            ledger_model=spend_sink.get("ledger_model"),
                            ctx=ctx,
                            outcome=spend_sink.get("outcome"),
                            tokens_hint=delta["total"],
                            spine_errors=spine_errors,
                        )
                    except Exception as finalize_exc:
                        spine_errors.append(
                            f"orphan finalization raised: "
                            f"{type(finalize_exc).__name__}: {finalize_exc}"
                        )
                record["spine_errors"] = spine_errors
                # Same fallback as every other failure path: burned tokens
                # must never report $0 / null cost — ledger_failed for web
                # cells, the plain price-table estimate for CLI cells.
                if record.get("cost") is None:
                    record["cost"] = _estimate_cost(
                        record["token_usage"]["total"],
                        source=(
                            "estimate/ledger_failed"
                            if cell.startswith("web")
                            else "price_table"
                        ),
                    )
            # A provider-level outage blocks the remainder of the cell: burning
            # through the taskset against a dead endpoint yields only noise.
            if str(record.get("error") or "").startswith("provider infra"):
                cell_blocked_reason = record["error"]
                blocked_cells[cell] = record["error"]
            records.append(record)
            # Spend is spend — a blocked/error record that still consumed
            # tokens (provider mid-flight failure, budget cancel) must count
            # toward the cell cap or the budget could be overrun repeatedly.
            cell_tokens += int(record["token_usage"].get("total") or 0)

    return {
        "schema": "evals-web-results/v1",
        "cells": list(cells),
        "blocked_cells": blocked_cells,
        "records": records,
        "tasks_per_cell": len(tasks),
        "workdir_base": str(workdir_base),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_cells(raw: str) -> list[str]:
    cells = [part.strip() for part in (raw or "").split(",") if part.strip()]
    unknown = [c for c in cells if c not in CELLS]
    if unknown:
        raise ValueError(f"unknown cells {unknown}; choose from {list(CELLS)}")
    if not cells:
        raise ValueError("no cells selected")
    return cells


def _parse_task_ids(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python evals/web/run.py",
        description="WEB-W7-C03 reproducible eval: cli|web x solo|team cells.",
    )
    parser.add_argument(
        "--taskset",
        type=str,
        default=str(REPO / "evals" / "web" / "taskset.jsonl"),
        help="Path to the fixed JSONL taskset.",
    )
    parser.add_argument(
        "--cells",
        type=str,
        default=",".join(CELLS),
        help=f"Comma-separated subset of {','.join(CELLS)}.",
    )
    parser.add_argument("--sample", type=int, default=None, help="First N tasks.")
    parser.add_argument(
        "--task-ids", type=str, default=None, help="Comma-separated task ids."
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=0,
        help="Max total tokens per cell (same for every cell; 0 = unlimited).",
    )
    parser.add_argument("--model", type=str, default=None, help="Model override.")
    parser.add_argument(
        "--task-timeout", type=int, default=600, help="Per-task seconds."
    )
    parser.add_argument("--out", type=str, required=True, help="Results JSON path.")
    parser.add_argument(
        "--manifest", type=str, required=True, help="Manifest JSON path."
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.environ.get("RXYCODE_WEB_DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL URL for web cells.",
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default=None,
        help="Base directory for per-task workdirs (default: temp dir).",
    )
    args = parser.parse_args()

    try:
        cells = _parse_cells(args.cells)
        tasks = select_tasks(
            load_taskset(args.taskset),
            sample=args.sample,
            task_ids=_parse_task_ids(args.task_ids),
        )
    except (TaskSchemaError, ValueError, FileNotFoundError) as exc:
        print(f"task/cell selection failed: {exc}", file=sys.stderr)
        return 2

    database_url = args.database_url or None
    manifest = build_manifest(
        taskset_path=args.taskset,
        tasks=tasks,
        cells=cells,
        budget=args.budget,
        model=args.model,
        database_url=database_url,
        extra={"sample": args.sample, "task_timeout": args.task_timeout},
    )
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"manifest -> {manifest_path}", file=sys.stderr)

    started = time.monotonic()

    async def _go(base: Path) -> dict[str, Any]:
        return await run_matrix(
            tasks=tasks,
            cells=cells,
            model=args.model,
            budget=args.budget,
            task_timeout=args.task_timeout,
            database_url=database_url,
            workdir_base=base,
            log=lambda m: print(m, file=sys.stderr, flush=True),
        )

    if args.workdir:
        results = asyncio.run(_go(Path(args.workdir)))
        results["workdir_base"] = args.workdir
    else:
        with tempfile.TemporaryDirectory(prefix="rxy-w7c03-") as tmpdir:
            results = asyncio.run(_go(Path(tmpdir)))

    results["manifest"] = manifest
    results["manifest_ref"] = manifest_path.name
    results["elapsed_s"] = round(time.monotonic() - started, 3)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for record in results["records"]:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print(f"results -> {out_path}", file=sys.stderr)
    print(
        "done:",
        ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no records",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
