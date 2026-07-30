"""
Tests for evals/runner.py and evals/report.py - Evaluation harness.

Covers:
- TaskResult / SuiteReport dataclasses
- Code-block extraction from LLM responses
- Check execution (file_exists, file_contains, file_not_contains,
  command_succeeds, output_contains)
- run_task with mock LLM (readcode + bugfix scenarios)
- run_suite with mock LLMs and optional judge
- save_results / load_results persistence
- generate_markdown report
- save_baseline / load_baseline / diff_baseline

All tests use mock LLMs - no real API key needed.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from RxyCode.RxyCode1_1_0.evals.runner import (
    TaskResult,
    SuiteReport,
    run_task,
    run_suite,
    run_checks,
    save_results,
    load_results,
    extract_code_blocks,
    apply_code_blocks,
    setup_workdir,
    collect_artifacts,
    _extract_token_usage,
    _extract_filename_from_info,
    _extract_filename_from_comment,
)
from RxyCode.RxyCode1_1_0.evals.tasks import EvalTask, Check
from RxyCode.RxyCode1_1_0.evals.judge import JudgeScore
from RxyCode.RxyCode1_1_0.evals import report as report_mod
from RxyCode.RxyCode1_1_0.evals import runner as runner_mod
from RxyCode.RxyCode1_1_0.evals.report import (
    generate_markdown,
    save_baseline,
    load_baseline,
    diff_baseline,
    list_baselines,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_llm(response_text: str, usage_metadata=None):
    """Create a mock LLM whose ainvoke returns *response_text*."""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = response_text
    if usage_metadata:
        mock_resp.usage_metadata = usage_metadata
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
    return mock_llm


def _make_mock_judge_llm(score_json: str):
    """Create a mock judge LLM that returns a JSON score string."""
    mock = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = score_json
    mock.ainvoke = AsyncMock(return_value=mock_resp)
    return mock


def _readcode_task():
    """A readcode task that only checks output_contains (no workdir)."""
    return EvalTask(
        id="test-readcode-pipeline",
        category="readcode",
        prompt="What are the pipeline nodes?",
        checks=[
            Check(type="output_contains", pattern="goal_planner"),
            Check(type="output_contains", pattern="executor"),
            Check(type="output_contains", pattern="validator"),
        ],
    )


def _bugfix_task():
    """A bugfix task that needs a workdir and file_contains checks."""
    return EvalTask(
        id="test-bugfix-offbyone",
        category="bugfix",
        prompt="Fix the off-by-one bug in calc.py: range(1, n) should be range(1, n+1).",
        setup_files={
            "calc.py": (
                "def sum_up_to(n):\n"
                "    total = 0\n"
                "    for i in range(1, n):  # BUG\n"
                "        total += i\n"
                "    return total\n"
            ),
        },
        checks=[
            Check(type="file_exists", path="calc.py"),
            Check(type="file_contains", path="calc.py", pattern="n + 1"),
        ],
    )


# ---------------------------------------------------------------------------
# TaskResult
# ---------------------------------------------------------------------------


class TestTaskResult:
    def test_defaults(self):
        r = TaskResult(task_id="t1", category="bugfix")
        assert r.task_id == "t1"
        assert r.category == "bugfix"
        assert r.passed is False
        assert r.duration_s == 0.0
        assert r.token_usage == {}
        assert r.judge_score is None
        assert r.error == ""
        assert r.agent_answer == ""
        assert r.check_details == []

    def test_custom_values(self):
        r = TaskResult(
            task_id="t2",
            category="feature",
            passed=True,
            duration_s=1.5,
            token_usage={"input": 100, "output": 50, "total": 150},
            judge_score={"mean": 4.5, "ok": True},
            error="",
            agent_answer="Here is the answer",
            check_details=[{"type": "file_exists", "passed": True}],
        )
        assert r.passed is True
        assert r.duration_s == 1.5
        assert r.token_usage["total"] == 150
        assert r.judge_score["mean"] == 4.5
        assert len(r.check_details) == 1

    def test_to_dict(self):
        r = TaskResult(
            task_id="t3",
            category="refactor",
            passed=True,
            duration_s=2.34,
            token_usage={"input": 10, "output": 5, "total": 15},
            agent_answer="answer text",
        )
        d = r.to_dict()
        assert d["task_id"] == "t3"
        assert d["passed"] is True
        assert d["duration_s"] == 2.34
        assert d["token_usage"]["total"] == 15
        assert d["agent_answer"] == "answer text"

    def test_to_dict_truncates_long_answer(self):
        r = TaskResult(
            task_id="t4",
            category="readcode",
            agent_answer="x" * 5000,
        )
        d = r.to_dict()
        assert len(d["agent_answer"]) <= 2000


# ---------------------------------------------------------------------------
# SuiteReport
# ---------------------------------------------------------------------------


class TestSuiteReport:
    def test_empty_report(self):
        report = SuiteReport()
        s = report.compute_summary()
        assert s["total_tasks"] == 0
        assert s["passed"] == 0
        assert s["failed"] == 0
        assert s["pass_rate"] == 0.0

    def test_summary_with_results(self):
        report = SuiteReport(results=[
            TaskResult(task_id="a", category="bugfix", passed=True),
            TaskResult(task_id="b", category="bugfix", passed=False),
            TaskResult(task_id="c", category="feature", passed=True),
        ])
        s = report.compute_summary()
        assert s["total_tasks"] == 3
        assert s["passed"] == 2
        assert s["failed"] == 1
        assert s["pass_rate"] == pytest.approx(2 / 3)

    def test_summary_judge_scores(self):
        report = SuiteReport(results=[
            TaskResult(
                task_id="a", category="bugfix", passed=True,
                judge_score={"mean": 4.0, "ok": True},
            ),
            TaskResult(
                task_id="b", category="bugfix", passed=True,
                judge_score={"mean": 5.0, "ok": True},
            ),
            TaskResult(
                task_id="c", category="bugfix", passed=True,
                judge_score={"mean": 0, "ok": False},
            ),
        ])
        s = report.compute_summary()
        # Only ok=True scores are counted: (4 + 5) / 2 = 4.5
        assert s["mean_judge_score"] == 4.5

    def test_summary_token_aggregation(self):
        report = SuiteReport(results=[
            TaskResult(task_id="a", category="x", token_usage={"total": 100}),
            TaskResult(task_id="b", category="x", token_usage={"total": 200}),
        ])
        s = report.compute_summary()
        assert s["total_tokens"] == 300

    def test_summary_by_category(self):
        report = SuiteReport(results=[
            TaskResult(task_id="a", category="bugfix", passed=True),
            TaskResult(task_id="b", category="bugfix", passed=False),
            TaskResult(task_id="c", category="feature", passed=True),
        ])
        s = report.compute_summary()
        cats = s["by_category"]
        assert "bugfix" in cats
        assert cats["bugfix"]["total"] == 2
        assert cats["bugfix"]["passed"] == 1
        assert "feature" in cats
        assert cats["feature"]["passed"] == 1

    def test_to_dict(self):
        report = SuiteReport(results=[
            TaskResult(task_id="a", category="bugfix", passed=True),
        ])
        d = report.to_dict()
        assert "results" in d
        assert "summary" in d
        assert len(d["results"]) == 1
        assert d["summary"]["total_tasks"] == 1


# ---------------------------------------------------------------------------
# Code-block extraction
# ---------------------------------------------------------------------------


class TestExtractFilenameFromInfo:
    def test_empty(self):
        assert _extract_filename_from_info("") == ""

    def test_bare_filename(self):
        assert _extract_filename_from_info("calc.py") == "calc.py"

    def test_colon_syntax(self):
        assert _extract_filename_from_info(":calc.py") == "calc.py"

    def test_title_equals(self):
        assert _extract_filename_from_info('title="calc.py"') == "calc.py"
        assert _extract_filename_from_info("title=calc.py") == "calc.py"

    def test_no_filename(self):
        assert _extract_filename_from_info("python") == ""


class TestExtractFilenameFromComment:
    def test_no_comment(self):
        assert _extract_filename_from_comment("def foo(): pass") == ""

    def test_filename_comment(self):
        assert _extract_filename_from_comment("# calc.py") == "calc.py"

    def test_filename_in_comment_text(self):
        assert _extract_filename_from_comment("# This is calc.py file") == "calc.py"

    def test_comment_without_filename(self):
        assert _extract_filename_from_comment("# This is a comment") == ""


class TestExtractCodeBlocks:
    def test_simple_block(self):
        text = "```python\ndef foo(): pass\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert "def foo" in blocks[0][1]

    def test_block_with_filename_in_comment(self):
        text = "```python\n# calc.py\ndef foo(): pass\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "calc.py"

    def test_block_with_filename_in_info(self):
        text = "```python:calc.py\ndef foo(): pass\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "calc.py"

    def test_block_with_title(self):
        text = '```python title="calc.py"\ndef foo(): pass\n```'
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "calc.py"

    def test_no_code_blocks(self):
        blocks = extract_code_blocks("Just plain text, no code.")
        assert blocks == []

    def test_multiple_blocks(self):
        text = (
            "```python\n# a.py\npass\n```\n"
            "Some text\n"
            "```python\n# b.py\npass\n```"
        )
        blocks = extract_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0][0] == "a.py"
        assert blocks[1][0] == "b.py"


class TestApplyCodeBlocks:
    def test_writes_file(self, tmp_path):
        text = "```python\n# calc.py\ndef foo(): pass\n```"
        written = apply_code_blocks(text, tmp_path)
        assert "calc.py" in written
        assert (tmp_path / "calc.py").is_file()
        assert "def foo" in (tmp_path / "calc.py").read_text()

    def test_skips_no_filename(self, tmp_path):
        text = "```\nsome code\n```"
        written = apply_code_blocks(text, tmp_path)
        assert written == []

    def test_path_traversal_blocked(self, tmp_path):
        text = "```python\n# ../../etc/evil.py\npass\n```"
        written = apply_code_blocks(text, tmp_path)
        assert written == []

    def test_creates_subdirectories(self, tmp_path):
        text = "```python\n# sub/dir/file.py\npass\n```"
        written = apply_code_blocks(text, tmp_path)
        assert "sub/dir/file.py" in written
        assert (tmp_path / "sub" / "dir" / "file.py").is_file()


# ---------------------------------------------------------------------------
# Check execution
# ---------------------------------------------------------------------------


class TestRunChecks:
    def test_file_exists_pass(self, tmp_path):
        (tmp_path / "calc.py").write_text("x = 1")
        task = EvalTask(
            id="t", category="bugfix", prompt="x",
            checks=[Check(type="file_exists", path="calc.py")],
        )
        passed, details = run_checks(task, workdir=tmp_path)
        assert passed is True
        assert details[0]["passed"] is True

    def test_file_exists_fail(self, tmp_path):
        task = EvalTask(
            id="t", category="bugfix", prompt="x",
            checks=[Check(type="file_exists", path="missing.py")],
        )
        passed, details = run_checks(task, workdir=tmp_path)
        assert passed is False
        assert "not found" in details[0]["message"]

    def test_file_contains_pass(self, tmp_path):
        (tmp_path / "calc.py").write_text("for i in range(1, n + 1):")
        task = EvalTask(
            id="t", category="bugfix", prompt="x",
            checks=[Check(type="file_contains", path="calc.py", pattern="n + 1")],
        )
        passed, _ = run_checks(task, workdir=tmp_path)
        assert passed is True

    def test_file_contains_fail(self, tmp_path):
        (tmp_path / "calc.py").write_text("for i in range(1, n):")
        task = EvalTask(
            id="t", category="bugfix", prompt="x",
            checks=[Check(type="file_contains", path="calc.py", pattern="n + 1")],
        )
        passed, details = run_checks(task, workdir=tmp_path)
        assert passed is False

    def test_file_not_contains_pass(self, tmp_path):
        (tmp_path / "code.py").write_text("good code")
        task = EvalTask(
            id="t", category="refactor", prompt="x",
            checks=[Check(type="file_not_contains", path="code.py", pattern="BUG")],
        )
        passed, _ = run_checks(task, workdir=tmp_path)
        assert passed is True

    def test_file_not_contains_fail(self, tmp_path):
        (tmp_path / "code.py").write_text("# BUG here")
        task = EvalTask(
            id="t", category="refactor", prompt="x",
            checks=[Check(type="file_not_contains", path="code.py", pattern="BUG")],
        )
        passed, _ = run_checks(task, workdir=tmp_path)
        assert passed is False

    def test_output_contains_pass(self):
        task = EvalTask(
            id="t", category="readcode", prompt="x",
            checks=[Check(type="output_contains", pattern="goal_planner")],
        )
        passed, _ = run_checks(task, workdir=None, agent_answer="The goal_planner node...")
        assert passed is True

    def test_output_contains_fail(self):
        task = EvalTask(
            id="t", category="readcode", prompt="x",
            checks=[Check(type="output_contains", pattern="goal_planner")],
        )
        passed, _ = run_checks(task, workdir=None, agent_answer="Nothing relevant here.")
        assert passed is False

    def test_command_succeeds_pass(self, tmp_path):
        (tmp_path / "hello.py").write_text("print('hello')")
        task = EvalTask(
            id="t", category="feature", prompt="x",
            checks=[
                Check(
                    type="command_succeeds",
                    run="python {workdir}/hello.py",
                ),
            ],
        )
        passed, _ = run_checks(task, workdir=tmp_path)
        assert passed is True

    def test_command_succeeds_fail(self, tmp_path):
        task = EvalTask(
            id="t", category="feature", prompt="x",
            checks=[
                Check(
                    type="command_succeeds",
                    run="python -c \"import sys; sys.exit(1)\"",
                ),
            ],
        )
        passed, details = run_checks(task, workdir=tmp_path)
        assert passed is False

    def test_multiple_checks_mixed(self, tmp_path):
        (tmp_path / "calc.py").write_text("for i in range(1, n + 1):")
        task = EvalTask(
            id="t", category="bugfix", prompt="x",
            checks=[
                Check(type="file_exists", path="calc.py"),
                Check(type="file_contains", path="calc.py", pattern="n + 1"),
                Check(type="output_contains", pattern="done"),
            ],
        )
        passed, details = run_checks(
            task, workdir=tmp_path, agent_answer="done",
        )
        assert passed is True
        assert len(details) == 3

    def test_no_workdir_for_file_check(self):
        task = EvalTask(
            id="t", category="bugfix", prompt="x",
            checks=[Check(type="file_exists", path="calc.py")],
        )
        passed, details = run_checks(task, workdir=None)
        assert passed is False
        assert "no workdir" in details[0]["message"]


# ---------------------------------------------------------------------------
# Workdir helpers
# ---------------------------------------------------------------------------


class TestWorkdirHelpers:
    def test_setup_workdir_creates_files(self, tmp_path):
        task = EvalTask(
            id="my-task",
            category="bugfix",
            prompt="x",
            setup_files={"calc.py": "print(1)", "test_calc.py": "assert True"},
            checks=[Check(type="output_contains", pattern="ok")],
        )
        wd = setup_workdir(task, tmp_path)
        assert wd == tmp_path / "my-task"
        assert (wd / "calc.py").is_file()
        assert (wd / "test_calc.py").is_file()
        assert (wd / "calc.py").read_text() == "print(1)"

    def test_collect_artifacts(self, tmp_path):
        (tmp_path / "a.py").write_text("content_a")
        (tmp_path / "b.py").write_text("content_b")
        result = collect_artifacts(tmp_path)
        assert "content_a" in result
        assert "content_b" in result
        assert "--- a.py ---" in result

    def test_collect_artifacts_empty(self):
        assert collect_artifacts(None) == ""

    def test_collect_artifacts_truncates(self, tmp_path):
        (tmp_path / "big.py").write_text("x" * 10000)
        result = collect_artifacts(tmp_path)
        assert len(result) <= 8000


# ---------------------------------------------------------------------------
# Token usage extraction
# ---------------------------------------------------------------------------


class TestExtractTokenUsage:
    def test_from_usage_metadata(self):
        resp = MagicMock()
        resp.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        llm = MagicMock()
        usage = _extract_token_usage(llm, resp)
        assert usage["input"] == 100
        assert usage["output"] == 50
        assert usage["total"] == 150

    def test_from_token_stats(self):
        resp = MagicMock()
        resp.usage_metadata = None
        llm = MagicMock()
        ts = MagicMock()
        ts.input_tokens = 200
        ts.output_tokens = 80
        llm.token_stats = ts
        usage = _extract_token_usage(llm, resp)
        assert usage["input"] == 200
        assert usage["output"] == 80
        assert usage["total"] == 280

    def test_defaults_to_zero(self):
        resp = MagicMock()
        resp.usage_metadata = None
        llm = MagicMock()
        del llm.token_stats
        usage = _extract_token_usage(llm, resp)
        assert usage == {"input": 0, "output": 0, "total": 0}


# ---------------------------------------------------------------------------
# run_task
# ---------------------------------------------------------------------------


class TestRunTask:
    def test_readcode_task_pass(self):
        """A readcode task whose mock answer contains the expected keywords."""
        task = _readcode_task()
        mock_llm = _make_mock_llm(
            "The pipeline has goal_planner, decomposer, executor, validator nodes."
        )
        result = asyncio.run(run_task(task, mock_llm, workdir=None))
        assert result.passed is True
        assert result.error == ""
        assert "goal_planner" in result.agent_answer

    def test_readcode_task_fail(self):
        """A readcode task whose mock answer is missing required keywords."""
        task = _readcode_task()
        mock_llm = _make_mock_llm("I don't know the answer.")
        result = asyncio.run(run_task(task, mock_llm, workdir=None))
        assert result.passed is False
        assert result.error != ""

    def test_bugfix_task_pass(self, tmp_path):
        """A bugfix task where the mock LLM returns a code block that fixes the file."""
        task = _bugfix_task()
        wd = setup_workdir(task, tmp_path)
        mock_llm = _make_mock_llm(
            "Here's the fix:\n```python\n# calc.py\n"
            "def sum_up_to(n):\n"
            "    total = 0\n"
            "    for i in range(1, n + 1):\n"
            "        total += i\n"
            "    return total\n"
            "```\n"
        )
        result = asyncio.run(run_task(task, mock_llm, workdir=wd))
        assert result.passed is True
        # The code block should have been written to the workdir.
        content = (wd / "calc.py").read_text()
        assert "n + 1" in content

    def test_bugfix_task_fail_wrong_fix(self, tmp_path):
        """A bugfix task where the mock LLM returns code without the fix."""
        task = _bugfix_task()
        wd = setup_workdir(task, tmp_path)
        mock_llm = _make_mock_llm(
            "```python\n# calc.py\n"
            "def sum_up_to(n):\n"
            "    total = 0\n"
            "    for i in range(1, n):\n"
            "        total += i\n"
            "    return total\n"
            "```\n"
        )
        result = asyncio.run(run_task(task, mock_llm, workdir=wd))
        assert result.passed is False
        assert "n + 1" not in (wd / "calc.py").read_text()

    def test_task_records_duration(self):
        task = _readcode_task()
        mock_llm = _make_mock_llm("goal_planner executor validator")
        result = asyncio.run(run_task(task, mock_llm, workdir=None))
        assert result.duration_s >= 0.0

    def test_task_records_token_usage(self):
        task = _readcode_task()
        mock_llm = _make_mock_llm(
            "goal_planner executor validator",
            usage_metadata={"input_tokens": 50, "output_tokens": 30},
        )
        result = asyncio.run(run_task(task, mock_llm, workdir=None))
        assert result.token_usage["input"] == 50
        assert result.token_usage["output"] == 30
        assert result.token_usage["total"] == 80

    def test_task_handles_llm_error(self):
        task = _readcode_task()
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("API down"))
        result = asyncio.run(run_task(task, mock_llm, workdir=None))
        assert result.passed is False
        assert "RuntimeError" in result.error
        assert "API down" in result.error

    def test_task_check_details_populated(self):
        task = _readcode_task()
        mock_llm = _make_mock_llm("goal_planner executor validator")
        result = asyncio.run(run_task(task, mock_llm, workdir=None))
        assert len(result.check_details) == 3
        for d in result.check_details:
            assert d["passed"] is True

    def test_task_no_workdir_for_readcode(self):
        """readcode tasks don't need_workdir."""
        task = _readcode_task()
        assert task.needs_workdir is False

    def test_task_needs_workdir_for_bugfix(self):
        task = _bugfix_task()
        assert task.needs_workdir is True


# ---------------------------------------------------------------------------
# run_suite
# ---------------------------------------------------------------------------


class TestRunSuite:
    def test_serial_execution(self):
        """run_suite runs tasks one by one and collects results."""
        tasks = [_readcode_task(), _bugfix_task()]

        # For the readcode task, return text with the keywords.
        # For the bugfix task, return a code block with the fix.
        readcode_answer = "goal_planner executor validator"
        bugfix_answer = (
            "```python\n# calc.py\n"
            "def sum_up_to(n):\n"
            "    total = 0\n"
            "    for i in range(1, n + 1):\n"
            "        total += i\n"
            "    return total\n"
            "```\n"
        )

        responses = [readcode_answer, bugfix_answer]
        mock_llm = MagicMock()

        async def mock_ainvoke(msgs, **kw):
            resp = MagicMock()
            resp.content = responses.pop(0)
            resp.usage_metadata = None
            return resp

        mock_llm.ainvoke = mock_ainvoke

        report = asyncio.run(run_suite(tasks, mock_llm))
        assert len(report.results) == 2
        assert report.results[0].task_id == "test-readcode-pipeline"
        assert report.results[1].task_id == "test-bugfix-offbyone"
        # Both should pass.
        assert all(r.passed for r in report.results)

    def test_summary_computed(self):
        tasks = [_readcode_task()]
        mock_llm = _make_mock_llm("goal_planner executor validator")
        report = asyncio.run(run_suite(tasks, mock_llm))
        s = report.summary
        assert s["total_tasks"] == 1
        assert s["passed"] == 1
        assert s["pass_rate"] == 1.0

    def test_with_judge(self):
        tasks = [_readcode_task()]
        mock_llm = _make_mock_llm("goal_planner executor validator")
        judge_json = json.dumps({
            "correctness": 5, "style": 4, "efficiency": 4,
            "rationale": "Good answer.",
        })
        mock_judge = _make_mock_judge_llm(judge_json)

        report = asyncio.run(
            run_suite(tasks, mock_llm, judge_llm=mock_judge)
        )
        r = report.results[0]
        assert r.judge_score is not None
        assert r.judge_score["ok"] is True
        assert r.judge_score["correctness"] == 5
        assert r.judge_score["mean"] == pytest.approx(4.333, abs=0.01)

    def test_with_tag_saves_results(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner_mod, "RESULTS_DIR", tmp_path)
        tasks = [_readcode_task()]
        mock_llm = _make_mock_llm("goal_planner executor validator")
        report = asyncio.run(
            run_suite(tasks, mock_llm, tag="test-run-001")
        )
        result_file = tmp_path / "test-run-001.json"
        assert result_file.is_file()
        saved = json.loads(result_file.read_text())
        assert saved["summary"]["total_tasks"] == 1
        assert saved["results"][0]["task_id"] == "test-readcode-pipeline"

    def test_empty_tasks_list(self):
        report = asyncio.run(run_suite([], MagicMock()))
        s = report.summary
        assert s["total_tasks"] == 0
        assert s["pass_rate"] == 0.0

    def test_judge_failure_handled(self):
        """If the judge LLM crashes, the task result still has a judge_score."""
        tasks = [_readcode_task()]
        mock_llm = _make_mock_llm("goal_planner executor validator")
        mock_judge = MagicMock()
        mock_judge.ainvoke = AsyncMock(side_effect=RuntimeError("judge down"))

        report = asyncio.run(
            run_suite(tasks, mock_llm, judge_llm=mock_judge)
        )
        r = report.results[0]
        assert r.judge_score is not None
        assert r.judge_score["ok"] is False

    def test_setup_files_written_to_workdir(self):
        """bugfix task setup files should be present in the workdir."""
        task = _bugfix_task()
        bugfix_answer = (
            "```python\n# calc.py\n"
            "def sum_up_to(n):\n"
            "    total = 0\n"
            "    for i in range(1, n + 1):\n"
            "        total += i\n"
            "    return total\n"
            "```\n"
        )
        mock_llm = _make_mock_llm(bugfix_answer)

        report = asyncio.run(run_suite([task], mock_llm))
        assert report.results[0].passed is True


# ---------------------------------------------------------------------------
# save_results / load_results
# ---------------------------------------------------------------------------


class TestSaveLoadResults:
    def test_save_and_load(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner_mod, "RESULTS_DIR", tmp_path)
        report = SuiteReport(results=[
            TaskResult(task_id="a", category="bugfix", passed=True, duration_s=1.0),
        ])
        path = save_results(report, "my-tag")
        assert path == tmp_path / "my-tag.json"
        assert path.is_file()

        loaded = load_results("my-tag")
        assert loaded["summary"]["total_tasks"] == 1
        assert loaded["results"][0]["task_id"] == "a"

    def test_load_missing_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(runner_mod, "RESULTS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            load_results("nonexistent")

    def test_save_creates_dir(self, monkeypatch, tmp_path):
        target = tmp_path / "nested" / "results"
        monkeypatch.setattr(runner_mod, "RESULTS_DIR", target)
        report = SuiteReport(results=[])
        path = save_results(report, "tag2")
        assert path.is_file()


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


class TestGenerateMarkdown:
    def test_basic_report(self):
        report = SuiteReport(results=[
            TaskResult(
                task_id="t1", category="bugfix", passed=True,
                duration_s=1.2, token_usage={"total": 100},
            ),
            TaskResult(
                task_id="t2", category="feature", passed=False,
                duration_s=3.4, token_usage={"total": 200},
                error="something failed",
            ),
        ])
        md = generate_markdown(report)
        assert "# Eval Suite Report" in md
        assert "50.0%" in md  # 1/2 = 50%
        assert "| t1 |" in md
        assert "| t2 |" in md
        assert "PASS" in md
        assert "FAIL" in md

    def test_report_with_judge_scores(self):
        report = SuiteReport(results=[
            TaskResult(
                task_id="t1", category="bugfix", passed=True,
                judge_score={"mean": 4.5, "ok": True},
            ),
        ])
        md = generate_markdown(report)
        assert "4.5" in md

    def test_report_with_category_breakdown(self):
        report = SuiteReport(results=[
            TaskResult(task_id="a", category="bugfix", passed=True),
            TaskResult(task_id="b", category="bugfix", passed=False),
            TaskResult(task_id="c", category="feature", passed=True),
        ])
        md = generate_markdown(report)
        assert "## By Category" in md
        assert "bugfix" in md
        assert "feature" in md

    def test_empty_report(self):
        report = SuiteReport()
        md = generate_markdown(report)
        assert "# Eval Suite Report" in md
        assert "0/0" in md


# ---------------------------------------------------------------------------
# Baseline save / load / diff
# ---------------------------------------------------------------------------


class TestBaseline:
    def _make_report(self, passed_a=True, passed_b=False):
        return SuiteReport(results=[
            TaskResult(
                task_id="task-a", category="bugfix",
                passed=passed_a, duration_s=1.0,
                token_usage={"total": 100},
            ),
            TaskResult(
                task_id="task-b", category="feature",
                passed=passed_b, duration_s=2.0,
                token_usage={"total": 200},
            ),
        ])

    def test_save_and_load_baseline(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        report = self._make_report()
        path = save_baseline(report, "v1.0")
        assert path.is_file()

        loaded = load_baseline("v1.0")
        assert loaded["summary"]["total_tasks"] == 2

    def test_load_missing_baseline(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            load_baseline("nonexistent")

    def test_list_baselines(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        save_baseline(self._make_report(), "v1")
        save_baseline(self._make_report(), "v2")
        names = list_baselines()
        assert "v1" in names
        assert "v2" in names

    def test_diff_no_changes(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        baseline = self._make_report(passed_a=True, passed_b=False)
        save_baseline(baseline, "base")
        current = self._make_report(passed_a=True, passed_b=False)
        diff = diff_baseline(current, "base")
        assert "No per-task status changes" in diff

    def test_diff_with_regression(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        baseline = self._make_report(passed_a=True, passed_b=False)
        save_baseline(baseline, "base")
        # Current: task-a now fails (regression).
        current = self._make_report(passed_a=False, passed_b=False)
        diff = diff_baseline(current, "base")
        assert "Regressions" in diff
        assert "task-a" in diff
        assert "PASS -> FAIL" in diff

    def test_diff_with_improvement(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        baseline = self._make_report(passed_a=True, passed_b=False)
        save_baseline(baseline, "base")
        # Current: task-b now passes (improvement).
        current = self._make_report(passed_a=True, passed_b=True)
        diff = diff_baseline(current, "base")
        assert "Improvements" in diff
        assert "task-b" in diff
        assert "FAIL -> PASS" in diff

    def test_diff_summary_deltas(self, monkeypatch, tmp_path):
        monkeypatch.setattr(report_mod, "BASELINES_DIR", tmp_path)
        baseline = self._make_report(passed_a=True, passed_b=False)
        save_baseline(baseline, "base")
        current = self._make_report(passed_a=True, passed_b=True)
        diff = diff_baseline(current, "base")
        assert "Summary Changes" in diff
        assert "Pass Rate" in diff
        assert "Delta" in diff
