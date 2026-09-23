"""layer=e2e 打开文档 SOP：prompt 包可粘贴，cheap-check 与拦截路由一致。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from RxyCode.RxyCode1_1_0.tools.launch_intent import classify_shell_launch

pytestmark = pytest.mark.e2e
REPO = Path(__file__).resolve().parents[3]
PACK = REPO / "evals" / "baselines" / "open-file-launch-e2e.json"
PROMPTS = REPO / "evals" / "prompts" / "open-file-launch-e2e.md"


def _pack() -> dict:
    return json.loads(PACK.read_text(encoding="utf-8"))


EXPECTED_IDS = [
    "e1-write-html-open",
    "e2-open-existing-md",
    "e3-missing-path-errors",
    "e4-notepad-intercept",
    "e5-start-docx-or-html",
    "e6-echo-stays-foreground",
    "e7-block-executable",
    "e8-websearch-two-queries",
    "e9-webfetch-static",
    "e10-playwright-virtual-browser",
    "e11-chrome-attach-cdp",
    "e12-computer-use-observe",
    "e13-inspect-grep-read",
    "e14-edit-or-patch-then-bash",
    "e15-git-status-diff-no-push",
    "e16-question-before-write",
    "e17-memory-add-search",
    "e18-vision-image-or-honest-miss",
    "e19-download-file",
    "e20-format-diagnostics-datetime",
    "e21-history-and-ls",
    "e22-explore-subagent-readonly",
    "e23-complex-rxyboard-product",
    "e24-simple-skip-todolist",
    "e25-complex-optional-todolist",
    "e26-named-test-file-must-land",
    "e27-readonly-no-todolist",
    "e28-syntax-error-not-done",
    "e29-full-directive-stays-on-harness",
    "e30-plan-then-finish-same-turn",
    "e31-open-todos-not-fake-complete",
]


def test_e2e_prompt_pack_has_full_tool_coverage_cases():
    data = _pack()
    ids = [case["id"] for case in data["cases"]]
    assert ids == EXPECTED_IDS
    for case in data["cases"]:
        prompt = case["prompt"].strip()
        assert len(prompt) > 40
        assert case["pass"] and case["fail"]


def test_e2e_last_case_is_complex_product_task():
    by_id = {case["id"]: case for case in _pack()["cases"]}
    last = by_id["e23-complex-rxyboard-product"]
    assert last["id"] == "e23-complex-rxyboard-product"
    prompt = last["prompt"]
    assert len(prompt) > 800
    for needle in (
        "RxyBoard",
        "websearch",
        "webfetch",
        "browser_navigate",
        "browser_snapshot",
        "chrome_attach",
        "list_apps",
        "open_file",
        "pytest",
        "git status",
        "question",
        "memory",
    ):
        assert needle in prompt, needle
    assert "不要只给计划" in prompt
    assert "禁止 commit" in prompt


def test_e2e_browser_and_cu_cases_exist():
    by_id = {case["id"]: case for case in _pack()["cases"]}
    assert "browser_navigate" in by_id["e10-playwright-virtual-browser"]["prompt"]
    assert "chrome_attach" in by_id["e11-chrome-attach-cdp"]["prompt"]
    assert "list_apps" in by_id["e12-computer-use-observe"]["prompt"]
    assert "Computer Use 未启用" in by_id["e12-computer-use-observe"]["prompt"]


def test_e2e_markdown_contains_every_paste_prompt():
    text = PROMPTS.read_text(encoding="utf-8")
    for case in _pack()["cases"]:
        assert case["prompt"] in text, case["id"]


def test_e2e_human_pack_forbids_waiting_for_gui_close():
    text = PROMPTS.read_text(encoding="utf-8")
    assert "[running]" in text
    assert "15" in text
    assert "E23" in text
    assert "E24" in text
    assert "EX1" in text
    assert "自研 harness" in text


def test_e2e_harness_track_l_cases():
    by_id = {case["id"]: case for case in _pack()["cases"]}
    skip = by_id["e24-simple-skip-todolist"]
    assert "task_manage" in skip["forbidden_tools"]
    assert "不要调用 task / task_manage" in skip["prompt"]
    named = by_id["e26-named-test-file-must-land"]
    assert "tests/test_eh26_lru.py" in named["prompt"]
    assert "禁止说任务完成" in named["prompt"]
    readonly = by_id["e27-readonly-no-todolist"]
    assert "不要 write/edit/bash" in readonly["prompt"]
    syntax = by_id["e28-syntax-error-not-done"]
    assert "def broken(:" in syntax["prompt"]
    full = by_id["e29-full-directive-stays-on-harness"]
    assert full["prompt"].startswith("/full")
    assert "LangGraph" in full["prompt"]
    plan = by_id["e30-plan-then-finish-same-turn"]
    assert "不要停下来等我确认" in plan["prompt"]
    leftover = by_id["e31-open-todos-not-fake-complete"]
    assert "禁止说「全部完成」" in leftover["prompt"]
    assert leftover["id"] == _pack()["cases"][-1]["id"]


def test_e4_notepad_classifies_as_detach_not_foreground_wait():
    plan = classify_shell_launch(r"notepad C:\tmp\open_e2e_note.txt")
    assert plan is not None
    assert plan.kind == "detach"


def test_e5_start_html_classifies_as_open_preview():
    plan = classify_shell_launch(r'start "" "open_e2e_demo.html"')
    assert plan is not None
    assert plan.kind == "open_preview"
    assert plan.path.endswith("open_e2e_demo.html")


def test_e6_echo_is_not_intercepted():
    assert classify_shell_launch("echo OPEN_E2E_OK") is None
    assert classify_shell_launch("python app.py") is None


def test_e3_named_docx_refuses_notes_md_substitute():
    from RxyCode.RxyCode1_1_0.tools.open_file import (
        mismatched_open_error,
        named_preview_files,
    )

    by_id = {case["id"]: case for case in _pack()["cases"]}
    prompt = by_id["e3-missing-path-errors"]["prompt"]
    assert named_preview_files(prompt) == ("open_e2e_missing_no_such_file.docx",)
    err = mismatched_open_error("notes.md", prompt)
    assert err is not None
    assert "file not found" in err
    assert "notes.md" in err
    assert "open_e2e_missing_no_such_file.docx" in err


def test_eval_yaml_tasks_load_and_require_open_file():
    for name in (
        "open-file-html.yaml",
        "open-file-existing-md.yaml",
        "open-file-missing.yaml",
    ):
        data = yaml.safe_load((REPO / "evals" / "tasks" / name).read_text(encoding="utf-8"))
        tools = [c.get("tool") for c in data["checks"] if c.get("type") == "tool_used"]
        assert "open_file" in tools, name
        assert "open_file" in data["prompt"]
