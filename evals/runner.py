"""Evaluation runner: execute the full RxyCode pipeline against eval tasks.

Stitched from OpenHands evaluation runner structure:
- Serial execution to avoid API rate limits
- Per-task timing, token cost, and validator pass/fail
- --tag flag persists results to evals/results/{tag}.json
- LLM-as-judge scoring via evals.judge.judge_task()

Adapted from OpenHands (MIT) evaluation/ runner pattern.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .tasks import EvalTask, load_tasks, load_task, TASKS_DIR, TaskSchemaError
from .judge import judge_task, JudgeScore

#: Directory for persisted run results.
RESULTS_DIR = Path(__file__).parent / "results"

#: Regex for fenced code blocks: ```lang info-string\n code ```
_CODE_BLOCK_RE = re.compile(
    r"```(\w+)?([^\n]*)\n(.*?)```",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskResult:
    """Result of running a single eval task."""

    task_id: str
    category: str
    passed: bool = False
    duration_s: float = 0.0
    token_usage: dict = field(default_factory=dict)
    judge_score: Optional[dict] = None
    error: str = ""
    # Extra fields (not in the minimal spec) used by judge / debugging.
    agent_answer: str = ""
    check_details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "passed": self.passed,
            "duration_s": round(self.duration_s, 3),
            "token_usage": self.token_usage,
            "judge_score": self.judge_score,
            "error": self.error,
            "agent_answer": self.agent_answer[:2000],
            "check_details": self.check_details,
        }


@dataclass
class SuiteReport:
    """Aggregated report for an entire eval suite run."""

    results: list[TaskResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def compute_summary(self) -> dict:
        total = len(self.results)
        if total == 0:
            self.summary = {
                "pass_rate": 0.0,
                "mean_judge_score": 0.0,
                "total_tokens": 0,
                "total_duration_s": 0.0,
                "total_tasks": 0,
                "passed": 0,
                "failed": 0,
                "by_category": {},
            }
            return self.summary

        passed = sum(1 for r in self.results if r.passed)
        total_tokens = sum(
            r.token_usage.get("total", 0) for r in self.results
        )
        total_duration = sum(r.duration_s for r in self.results)

        judge_scores = [
            r.judge_score.get("mean", 0)
            for r in self.results
            if r.judge_score and r.judge_score.get("ok")
        ]
        mean_judge = (
            sum(judge_scores) / len(judge_scores) if judge_scores else 0.0
        )

        # Per-category breakdown.
        categories: dict[str, dict] = {}
        for r in self.results:
            cat = r.category
            if cat not in categories:
                categories[cat] = {"total": 0, "passed": 0}
            categories[cat]["total"] += 1
            if r.passed:
                categories[cat]["passed"] += 1
        for cat_data in categories.values():
            cat_data["pass_rate"] = (
                cat_data["passed"] / cat_data["total"]
                if cat_data["total"] > 0
                else 0.0
            )

        self.summary = {
            "pass_rate": passed / total,
            "mean_judge_score": round(mean_judge, 3),
            "total_tokens": total_tokens,
            "total_duration_s": round(total_duration, 3),
            "total_tasks": total,
            "passed": passed,
            "failed": total - passed,
            "by_category": categories,
        }
        return self.summary

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "summary": self.compute_summary(),
        }


# ---------------------------------------------------------------------------
# Code-block extraction (apply LLM answer to workdir)
# ---------------------------------------------------------------------------


def _extract_filename_from_info(info: str) -> str:
    """Pull a filename from the text after ```` ```lang ```` on the fence line."""
    info = info.strip()
    if not info:
        return ""
    # title="filename" or title=filename
    m = re.search(r'title\s*=\s*["\']?([^"\'\s]+)["\']?', info)
    if m:
        return m.group(1)
    # filename after colon: python:calc.py
    if ":" in info:
        after = info.split(":", 1)[1].strip().strip("\"'")
        if after and ("." in after or "/" in after):
            return after
    # bare token with a file extension
    for tok in info.split():
        clean = tok.strip("\"'")
        if "." in clean and "/" not in clean:
            return clean
    return ""


def _extract_filename_from_comment(code: str) -> str:
    """Try to read a filename from the first-line ``# comment``."""
    first = code.strip().split("\n", 1)[0].strip()
    if not first.startswith("#"):
        return ""
    comment = first[1:].strip()
    if "." in comment and " " not in comment:
        return comment
    m = re.search(r"\b([\w-]+\.\w+)\b", comment)
    if m:
        return m.group(1)
    return ""


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extract fenced code blocks from an LLM response.

    Returns a list of ``(filename, code)`` pairs.  ``filename`` may be
    an empty string when no hint was found.
    """
    blocks: list[tuple[str, str]] = []
    for match in _CODE_BLOCK_RE.finditer(text):
        _lang = match.group(1) or ""
        info = match.group(2) or ""
        code = match.group(3).strip()

        filename = _extract_filename_from_info(info)
        if not filename:
            filename = _extract_filename_from_comment(code)
        blocks.append((filename, code))
    return blocks


def apply_code_blocks(text: str, workdir: Path) -> list[str]:
    """Write code blocks found in *text* into *workdir*.

    Only blocks with a resolvable filename are written.  Returns the
    list of filenames that were written.
    """
    written: list[str] = []
    for filename, code in extract_code_blocks(text):
        if not filename:
            continue
        # Security: stay inside workdir.
        target = (workdir / filename).resolve()
        try:
            target.relative_to(workdir.resolve())
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")
        written.append(filename)
    return written


# ---------------------------------------------------------------------------
# Check execution
# ---------------------------------------------------------------------------


def _run_single_check(
    check,
    *,
    workdir: Optional[Path],
    agent_answer: str,
) -> tuple[bool, str]:
    """Execute one check.  Returns ``(passed, message)``."""
    ct = check.type

    if ct == "file_exists":
        if not workdir:
            return False, "no workdir for file_exists check"
        target = workdir / check.path
        ok = target.is_file()
        return ok, "" if ok else f"file not found: {check.path}"

    if ct == "file_contains":
        if not workdir:
            return False, "no workdir for file_contains check"
        target = workdir / check.path
        if not target.is_file():
            return False, f"file not found: {check.path}"
        content = target.read_text(encoding="utf-8", errors="replace")
        ok = (check.pattern or "") in content
        return ok, "" if ok else f"pattern {check.pattern!r} not in {check.path}"

    if ct == "file_not_contains":
        if not workdir:
            return False, "no workdir for file_not_contains check"
        target = workdir / check.path
        if not target.is_file():
            return False, f"file not found: {check.path}"
        content = target.read_text(encoding="utf-8", errors="replace")
        ok = (check.pattern or "") not in content
        return ok, "" if ok else f"pattern {check.pattern!r} found in {check.path} (should not be)"

    if ct == "command_succeeds":
        if not workdir:
            return False, "no workdir for command_succeeds check"
        cmd = (check.run or "").replace("{workdir}", str(workdir))
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                timeout=60,
                cwd=str(workdir),
            )
            ok = result.returncode == 0
            msg = "" if ok else result.stderr.decode("utf-8", errors="replace")[:500]
            return ok, msg
        except subprocess.TimeoutExpired:
            return False, "command timed out (60s)"
        except Exception as e:
            return False, str(e)[:200]

    if ct == "output_contains":
        ok = (check.pattern or "") in (agent_answer or "")
        return ok, "" if ok else f"pattern {check.pattern!r} not in agent answer"

    return False, f"unknown check type: {ct}"


def run_checks(
    task: EvalTask,
    *,
    workdir: Optional[Path] = None,
    agent_answer: str = "",
) -> tuple[bool, list[dict]]:
    """Run all checks for *task*.  Returns ``(all_passed, details)``."""
    details: list[dict] = []
    all_passed = True
    for check in task.checks:
        ok, msg = _run_single_check(check, workdir=workdir, agent_answer=agent_answer)
        details.append({"type": check.type, "passed": ok, "message": msg})
        if not ok:
            all_passed = False
    return all_passed, details


# ---------------------------------------------------------------------------
# Workdir setup & artifact collection
# ---------------------------------------------------------------------------


def setup_workdir(task: EvalTask, base: Path) -> Path:
    """Create an isolated workdir for *task* under *base* and write setup files."""
    workdir = base / task.id
    workdir.mkdir(parents=True, exist_ok=True)
    for rel, content in task.setup_files.items():
        fp = workdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return workdir


def collect_artifacts(workdir: Optional[Path]) -> str:
    """Concatenate file contents from *workdir* for the judge prompt."""
    if not workdir:
        return ""
    parts: list[str] = []
    for p in sorted(workdir.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                rel = p.relative_to(workdir)
                parts.append(f"--- {rel} ---\n{content}")
            except Exception:
                pass
    return "\n\n".join(parts)[:8000]


# ---------------------------------------------------------------------------
# Token-usage extraction
# ---------------------------------------------------------------------------


def _extract_token_usage(llm, response) -> dict:
    """Best-effort token usage extraction from the LLM response or llm object."""
    usage: dict[str, int] = {"input": 0, "output": 0, "total": 0}

    # 1. LangChain AIMessage.usage_metadata
    um = getattr(response, "usage_metadata", None)
    if isinstance(um, dict):
        usage["input"] = um.get("input_tokens", 0) or um.get("prompt_tokens", 0)
        usage["output"] = um.get("output_tokens", 0) or um.get("completion_tokens", 0)
        usage["total"] = usage["input"] + usage["output"]
        return usage

    # 2. RxyCode UsageTrackingLLM.token_stats
    ts = getattr(llm, "token_stats", None)
    if ts is not None:
        try:
            inp = int(getattr(ts, "input_tokens", 0))
            out = int(getattr(ts, "output_tokens", 0))
            usage["input"] = inp
            usage["output"] = out
            usage["total"] = inp + out
            return usage
        except (TypeError, ValueError):
            pass

    return usage


# ---------------------------------------------------------------------------
# Core runner functions
# ---------------------------------------------------------------------------


async def run_task(
    task: EvalTask,
    llm,
    workdir: Optional[Path] = None,
) -> TaskResult:
    """Run a single eval task against *llm*.

    Steps:
    1. Build the prompt (include existing-file context for workdir tasks).
    2. Call ``llm.ainvoke()``.
    3. Extract code blocks from the response and write them to *workdir*.
    4. Run all checks.
    5. Return a :class:`TaskResult`.
    """
    from langchain_core.messages import HumanMessage

    start = time.monotonic()
    error = ""
    agent_answer = ""
    token_usage: dict[str, int] = {"input": 0, "output": 0, "total": 0}
    check_details: list[dict] = []

    try:
        prompt = task.prompt
        if task.needs_workdir and workdir and task.setup_files:
            file_ctx = "\n".join(
                f"--- {name} ---\n{content}"
                for name, content in task.setup_files.items()
            )
            prompt = f"{task.prompt}\n\nExisting files in your workdir:\n{file_ctx}"

        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        agent_answer = getattr(resp, "content", "") or ""
        token_usage = _extract_token_usage(llm, resp)

        # Apply code blocks to workdir.
        if task.needs_workdir and workdir:
            apply_code_blocks(agent_answer, workdir)

    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration = time.monotonic() - start

    # Run checks.
    passed = False
    if not error:
        checks_workdir = workdir if task.needs_workdir else None
        passed, check_details = run_checks(
            task, workdir=checks_workdir, agent_answer=agent_answer,
        )
        if not passed:
            failed_msgs = [
                d["message"] for d in check_details if not d["passed"] and d["message"]
            ]
            if failed_msgs:
                error = "; ".join(failed_msgs)
            else:
                error = "one or more checks failed"

    return TaskResult(
        task_id=task.id,
        category=task.category,
        passed=passed,
        duration_s=duration,
        token_usage=token_usage,
        error=error,
        agent_answer=agent_answer,
        check_details=check_details,
    )


async def run_suite(
    tasks: list[EvalTask],
    llm,
    judge_llm=None,
    tag: Optional[str] = None,
) -> SuiteReport:
    """Run the full eval suite **serially** (to avoid API rate limits).

    For each task:
    1. Create a workdir if needed.
    2. Call :func:`run_task`.
    3. If *judge_llm* is provided, call :func:`judge_task` and attach the score.
    """
    report = SuiteReport()

    with tempfile.TemporaryDirectory(prefix="rxycode-eval-") as tmpdir:
        base = Path(tmpdir)

        for idx, task in enumerate(tasks, 1):
            print(
                f"[{idx}/{len(tasks)}] {task.id} ({task.category}) ...",
                file=sys.stderr,
                flush=True,
            )

            workdir: Optional[Path] = None
            if task.needs_workdir:
                workdir = setup_workdir(task, base)

            result = await run_task(task, llm, workdir)

            # LLM-as-judge scoring.
            if judge_llm is not None:
                try:
                    artifacts = collect_artifacts(workdir)
                    score = await judge_task(
                        judge_llm,
                        task_prompt=task.prompt,
                        agent_answer=result.agent_answer,
                        artifacts=artifacts,
                    )
                    result.judge_score = score.to_dict()
                except Exception as e:
                    result.judge_score = JudgeScore(
                        ok=False, rationale=str(e)[:200],
                    ).to_dict()

            report.results.append(result)

    report.compute_summary()

    if tag:
        save_results(report, tag)

    return report


# ---------------------------------------------------------------------------
# Result persistence
# ---------------------------------------------------------------------------


def save_results(report: SuiteReport, tag: str) -> Path:
    """Save *report* to ``evals/results/{tag}.json``."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{tag}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    return path


def load_results(tag: str) -> dict:
    """Load a previously saved run by tag."""
    path = RESULTS_DIR / f"{tag}.json"
    if not path.is_file():
        raise FileNotFoundError(f"results not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_tasks_resilient(
    *,
    task_ids: Optional[list[str]] = None,
    category: Optional[str] = None,
) -> list[EvalTask]:
    """Load tasks one-by-one, skipping broken YAML files with a warning.

    Used as a fallback when :func:`load_tasks` fails because one or more
    task YAMLs don't conform to the schema.
    """
    from .tasks import CATEGORIES

    wanted = set(task_ids) if task_ids else None
    if category and category not in CATEGORIES:
        print(
            f"Error: category must be one of {list(CATEGORIES)}, "
            f"got {category!r}",
            file=sys.stderr,
        )
        return []

    tasks: list[EvalTask] = []
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        try:
            task = load_task(path)
        except (TaskSchemaError, Exception) as e:
            print(f"  Skipping {path.name}: {e}", file=sys.stderr)
            continue
        if wanted is not None and task.id not in wanted:
            continue
        if category is not None and task.category != category:
            continue
        tasks.append(task)

    if wanted is not None:
        found_ids = {t.id for t in tasks}
        missing = wanted - found_ids
        if missing:
            print(
                f"Warning: unknown task id(s): {sorted(missing)}",
                file=sys.stderr,
            )
    return tasks


# ---------------------------------------------------------------------------
# LLM construction (CLI only)
# ---------------------------------------------------------------------------


def _build_llm():
    """Build a ChatOpenAI LLM from env / config for the CLI runner."""
    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    model = os.environ.get("EVAL_MODEL", "gpt-4o")
    base_url = os.environ.get("EVAL_BASE_URL", None)

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": 0.0,
        "max_retries": 3,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point: ``python -m evals.run``."""
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="Run RxyCode evaluation suite against eval tasks.",
    )
    parser.add_argument(
        "--tag", type=str, default=None,
        help="Tag for this run; results saved to evals/results/{tag}.json",
    )
    parser.add_argument(
        "--task-ids", type=str, nargs="*", default=None,
        help="Specific task IDs to run (space-separated)",
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Filter tasks by category (readcode|bugfix|refactor|feature)",
    )
    parser.add_argument(
        "--judge", action="store_true",
        help="Enable LLM-as-judge scoring (uses the same model unless EVAL_JUDGE_MODEL is set)",
    )
    parser.add_argument(
        "--dry", action="store_true",
        help="Dry run: validate task setup without calling LLM",
    )
    args = parser.parse_args()

    # Load tasks (fall back to resilient loader if a YAML is broken).
    tasks: list[EvalTask] = []
    try:
        tasks = load_tasks(task_ids=args.task_ids, category=args.category)
    except Exception as e:
        print(
            f"Warning: batch load failed ({e}), trying individually...",
            file=sys.stderr,
        )
        tasks = _load_tasks_resilient(
            task_ids=args.task_ids, category=args.category,
        )

    if not tasks:
        print("No tasks to run.", file=sys.stderr)
        return 1

    print(f"Loaded {len(tasks)} task(s)")

    if args.dry:
        print("Dry run - task setup validated:")
        for t in tasks:
            print(
                f"  {t.id} [{t.category}] "
                f"- {len(t.checks)} check(s) "
                f"- needs_workdir={t.needs_workdir}"
            )
        return 0

    # Build LLM.
    try:
        llm = _build_llm()
    except Exception as e:
        print(f"Error building LLM: {e}", file=sys.stderr)
        print(
            "Hint: set OPENAI_API_KEY or configure evals in config.yaml",
            file=sys.stderr,
        )
        return 1

    judge_llm = None
    if args.judge:
        try:
            judge_llm = _build_llm()
        except Exception as e:
            print(f"Warning: could not build judge LLM: {e}", file=sys.stderr)

    # Run suite.
    report = asyncio.run(run_suite(tasks, llm, judge_llm=judge_llm, tag=args.tag))

    # Print summary.
    s = report.summary
    print(f"\n{'=' * 60}")
    print(
        f"Eval suite complete: {s['passed']}/{s['total_tasks']} passed "
        f"({s['pass_rate']:.1%})"
    )
    print(f"Duration: {s['total_duration_s']:.1f}s | Tokens: {s['total_tokens']}")
    if s.get("mean_judge_score"):
        print(f"Mean judge score: {s['mean_judge_score']:.2f}/5")
    print(f"{'=' * 60}")

    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.task_id} [{r.category}] {r.duration_s:.1f}s")
        if r.error:
            print(f"         error: {r.error[:120]}")

    if args.tag:
        print(f"\nResults saved to: {RESULTS_DIR / f'{args.tag}.json'}")

    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
