"""WEB-W3-C03. The shipped reducer orders events once and keeps the final answer clean."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REDUCER = REPO / "apps" / "web" / "src" / "features" / "runs" / "eventReducer.ts"
_SCRATCH = Path(tempfile.gettempdir()) / "rxy-w3c03"


def _bun() -> str:
    from tests.support.pgurl import bun_path

    found = bun_path()
    if found:
        return found
    raise FileNotFoundError("bun")


def reduce_events(events: list[dict], initial_status: str = "", watermark: int = 0) -> dict:
    """Run the shipped reducer. The assertions stay in this test."""
    assert REDUCER.is_file(), "eventReducer.ts is missing"
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    driver = _SCRATCH / "c03-reduce.ts"
    driver.write_text(
        "import { reduceEvents } from "
        + json.dumps(REDUCER.as_posix())
        + "\nconst events = "
        + json.dumps(events)
        + "\nconsole.log(JSON.stringify(reduceEvents(events, "
        + json.dumps(initial_status)
        + ", "
        + str(int(watermark))
        + ")))\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_bun(), str(driver)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_w3_c03_thinking_accumulates_chain_of_thought() -> None:
    """思维链按事件计步并累积进 thinking.text —— 前端折叠展示原文；
    activity 只放行已知安全的 CLI 状态行，子代理中间态仍不进时间线。"""
    done = reduce_events(
        [
            {
                "seq": 1,
                "type": "assistant.delta",
                "payload": {
                    "text": "Analyzing your request...",
                    "intermediate": True,
                    "channel": "status",
                },
            },
            {
                "seq": 2,
                "type": "assistant.delta",
                "payload": {
                    "text": "Thinking... (round 1)",
                    "intermediate": True,
                    "channel": "status",
                },
            },
            {
                "seq": 3,
                "type": "assistant.delta",
                "payload": {"text": "思考中...", "intermediate": True, "channel": "status"},
            },
            {
                "seq": 4,
                "type": "assistant.delta",
                "payload": {
                    "text": "先看文件",
                    "intermediate": False,
                    "channel": "reasoning",
                    "snapshot": False,
                },
            },
            {
                "seq": 5,
                "type": "assistant.delta",
                "payload": {
                    "text": "再改测试",
                    "intermediate": False,
                    "channel": "reasoning",
                    "snapshot": False,
                },
            },
            {
                "seq": 6,
                "type": "assistant.delta",
                "payload": {
                    "text": "子代理的内部输出不应出现",
                    "intermediate": True,
                    "channel": "assistant",
                },
            },
        ]
    )
    thoughts = [item for item in done["view"]["timeline"] if item["kind"] == "thinking"]
    # 思维链原文累积进 text：相邻 reasoning delta 合并为一块。
    assert thoughts == [
        {"kind": "thinking", "seq": 4, "steps": 2, "text": "先看文件再改测试"}
    ]
    timeline_json = json.dumps(done["view"]["timeline"], ensure_ascii=False)
    assert "先看文件" in timeline_json
    assert "再改测试" in timeline_json
    assert "子代理的内部输出" not in timeline_json
    # activity 只保留状态行文案；非状态行的中间态被通用标签替代。
    assert done["view"]["activity"] == "处理中…"
    assert done["answer"] == ""


def test_w3_c03_thinking_filters_placeholders_and_snapshots() -> None:
    """liveness 占位文案不是思维内容（与 OpenTUI THOUGHT_PLACEHOLDERS
    同表）；snapshot 是累计快照 → 替换而非追加。"""
    done = reduce_events(
        [
            {
                "seq": 1,
                "type": "assistant.delta",
                "payload": {
                    "text": "思考中...",
                    "intermediate": False,
                    "channel": "reasoning",
                    "snapshot": False,
                },
            },
            {
                "seq": 2,
                "type": "assistant.delta",
                "payload": {
                    "text": "先分析",
                    "intermediate": False,
                    "channel": "reasoning",
                    "snapshot": False,
                },
            },
            {
                "seq": 3,
                "type": "assistant.delta",
                "payload": {
                    "text": "先分析再动手",
                    "intermediate": False,
                    "channel": "reasoning",
                    "snapshot": True,
                },
            },
            {
                "seq": 4,
                "type": "assistant.delta",
                "payload": {
                    "text": "尾巴",
                    "intermediate": False,
                    "channel": "reasoning",
                    "snapshot": False,
                },
            },
        ]
    )
    thoughts = [item for item in done["view"]["timeline"] if item["kind"] == "thinking"]
    assert thoughts == [
        {"kind": "thinking", "seq": 2, "steps": 3, "text": "先分析再动手尾巴"}
    ]


def test_w3_c03_contract() -> None:
    """Events 1,2,2,4,3 become 1,2,3,4, and seq 2 is kept once."""
    prefix = reduce_events(
        [
            {"seq": 1, "type": "assistant.delta", "payload": {"text": "one"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "two"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "dup"}},
            {"seq": 4, "type": "assistant.final", "payload": {"text": "four"}},
        ]
    )
    assert prefix["order"] == [1, 2]
    assert prefix["order"].count(2) == 1
    assert 4 not in prefix["order"]
    done = reduce_events(
        [
            {"seq": 1, "type": "assistant.delta", "payload": {"text": "one"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "two"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": "dup"}},
            {"seq": 4, "type": "assistant.final", "payload": {"text": "four"}},
            {"seq": 3, "type": "assistant.delta", "payload": {"text": "three"}},
        ]
    )
    assert done["order"] == [1, 2, 3, 4]
    assert done["order"].count(2) == 1


def test_w3_c03_negative() -> None:
    """Out-of-order intermediate text stays out of the final answer."""
    done = reduce_events(
        [
            {
                "seq": 2,
                "type": "assistant.delta",
                "payload": {"text": "child thought", "intermediate": True},
            },
            {
                "seq": 1,
                "type": "assistant.delta",
                "payload": {"text": "earlier thought", "intermediate": True},
            },
            {
                "seq": 3,
                "type": "assistant.final",
                "payload": {"text": "final user answer"},
            },
        ]
    )
    assert done["answer"] == "final user answer"
    assert done["answer"].endswith("final user answer")
    assert "thought" not in done["answer"]
    assert done["intermediate"] == ["earlier thought", "child thought"]
    streamed = reduce_events(
        [
            {"seq": 1, "type": "assistant.delta", "payload": {"text": "Hello"}},
            {"seq": 2, "type": "assistant.delta", "payload": {"text": " there"}},
        ]
    )
    assert streamed["answer"] == "Hello there"
    resolved = reduce_events(
        [
            {"seq": 1, "type": "approval.requested", "payload": {"approval_id": "appr-9"}},
            {
                "seq": 2,
                "type": "approval.resolved",
                "payload": {"approval_id": "appr-9", "decision": "rejected"},
            },
        ]
    )
    assert resolved["approvals"][0]["status"] == "rejected"
    failed = reduce_events(
        [
            {"seq": 1, "type": "run.started", "payload": {}},
            {"seq": 2, "type": "run.failed", "payload": {}},
        ]
    )
    assert failed["runStatus"] == "failed"
    history = [
        {"seq": 1, "type": "run.started", "payload": {}},
        {"seq": 2, "type": "approval.requested", "payload": {"approval_id": "appr-2"}},
    ]
    assert reduce_events(history)["runStatus"] == "running"
    assert reduce_events(history, "waiting_approval", 2)["runStatus"] == "waiting_approval"


def test_w3_c03_tasks_merge_plan_and_todo_updates() -> None:
    """plan.updated/todo.updated 合并进唯一 tasks 块，按 id 覆盖状态。"""
    done = reduce_events(
        [
            {
                "seq": 1,
                "type": "plan.updated",
                "payload": {"plan_id": "plan-0", "title": "读取需求", "status": "pending"},
            },
            {
                "seq": 2,
                "type": "todo.updated",
                "payload": {"todo_id": "t1", "title": "写实现", "status": "in_progress"},
            },
            {
                "seq": 3,
                "type": "todo.updated",
                "payload": {"todo_id": "t1", "title": "写实现", "status": "completed"},
            },
            {
                "seq": 4,
                "type": "plan.updated",
                "payload": {"plan_id": "plan-0", "title": "读取需求", "status": "completed"},
            },
        ]
    )
    blocks = [item for item in done["view"]["timeline"] if item["kind"] == "tasks"]
    assert len(blocks) == 1
    assert blocks[0]["items"] == [
        {"id": "plan-0", "title": "读取需求", "status": "completed"},
        {"id": "t1", "title": "写实现", "status": "completed"},
    ]
