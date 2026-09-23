"""ReAct exit diamond: four conditions, any one stops the loop."""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.agent_v2 import _should_nudge_build_to_write
from RxyCode.RxyCode1_1_0.core.loop_exit import (
    ERROR_LIMIT,
    ReactExit,
    bump_consecutive_errors,
    claimed_final_answer,
    decide_react_turn,
    drop_tools_after_final_answer,
    has_final_answer_call,
    quoted_tool_result,
)


E3_ANSWER = (
    "open_file 返回了错误原文：\n"
    "[error: file not found or invalid path: [WinError 2] 系统找不到指定的文件。]\n\n"
    "最终结果：当前目录没有 open_e2e_missing_no_such_file.docx，无法打开。"
)


def test_claimed_final_answer_drops_trailing_tools() -> None:
    decision = decide_react_turn(
        tool_calls=[{"name": "ls", "args": {}, "id": "1"}],
        answer=E3_ANSWER,
    )
    assert decision.exit is ReactExit.FINAL_ANSWER_CALL
    assert decision.drop_tools is True
    assert claimed_final_answer(E3_ANSWER) is True


def test_quoted_tool_error_is_task_complete_without_heading() -> None:
    answer = (
        "工具返回原文：[error: file not found or invalid path: missing.docx]。"
        "文件不存在，所以打不开。"
    )
    decision = decide_react_turn(tool_calls=[], answer=answer)
    assert quoted_tool_result(answer) is True
    assert decision.exit is ReactExit.TASK_COMPLETE
    assert decision.drop_tools is False


def test_task_complete_drops_trailing_tools() -> None:
    decision = decide_react_turn(
        tool_calls=[{"name": "ls", "args": {}, "id": "1"}],
        answer="任务已完成。文件已经用系统默认程序打开。",
    )
    assert decision.exit is ReactExit.TASK_COMPLETE
    assert decision.drop_tools is True


def test_final_answer_tool_is_kept_for_exec() -> None:
    calls = [
        {"name": "ls", "args": {}, "id": "1"},
        {"name": "final_answer", "args": {"result": "done"}, "id": "2"},
        {"name": "read", "args": {"path": "x"}, "id": "3"},
    ]
    decision = decide_react_turn(tool_calls=calls, answer="")
    assert decision.exit is None
    assert decision.reason == "final_answer_tool"
    assert has_final_answer_call(calls) is True
    kept = drop_tools_after_final_answer(calls)
    assert [c["name"] for c in kept] == ["ls", "final_answer"]


def test_llm_requests_exit() -> None:
    decision = decide_react_turn(
        tool_calls=[{"name": "ls", "args": {}, "id": "1"}],
        answer="结束本轮，不再调用工具。",
    )
    assert decision.exit is ReactExit.LLM_REQUESTS_EXIT
    assert decision.drop_tools is True


def test_error_count_4_does_not_exit() -> None:
    decision = decide_react_turn(
        tool_calls=[{"name": "open_file", "args": {"filePath": "a.docx"}, "id": "1"}],
        answer="文件不存在，再试一次。",
        error_count=4,
    )
    assert ERROR_LIMIT == 5
    assert decision.exit is None
    assert decision.reason == "acting"


def test_error_count_5_exits_even_with_tools() -> None:
    decision = decide_react_turn(
        tool_calls=[{"name": "open_file", "args": {"filePath": "a.docx"}, "id": "1"}],
        answer="文件不存在，再试一次。",
        error_count=5,
    )
    assert decision.exit is ReactExit.ERROR_LIMIT
    assert decision.drop_tools is True
    assert "consecutive" in decision.reason


def test_consecutive_errors_reset_on_success() -> None:
    n = 0
    for _ in range(4):
        n = bump_consecutive_errors(n, failed=True)
    assert n == 4
    n = bump_consecutive_errors(n, failed=False)
    assert n == 0
    n = bump_consecutive_errors(n, failed=True)
    assert n == 1
    assert ERROR_LIMIT == 5


def test_markdown_final_heading_stops_before_write_nudge() -> None:
    answer = (
        "命令执行成功。\n\n---\n\n**最终结果**\n\n"
        "终端完整输出如下：\n\n```\nOPEN_E2E_OK\n```"
    )
    decision = decide_react_turn(tool_calls=[], answer=answer)
    assert decision.exit is ReactExit.FINAL_ANSWER_CALL
    assert decision.drop_tools is False
    assert claimed_final_answer(answer) is True
    assert (
        _should_nudge_build_to_write(
            "build",
            False,
            0,
            answer=answer,
            user_input="请用 bash 执行：echo OPEN_E2E_OK。把终端的完整输出贴进最终回答。不要打开任何文档或窗口。",
        )
        is False
    )


def test_bash_echo_is_not_nudged_to_write_source() -> None:
    assert (
        _should_nudge_build_to_write(
            "build",
            False,
            0,
            answer="命令执行成功。",
            user_input="请用 bash 执行：echo OPEN_E2E_OK。把终端的完整输出贴进最终回答。不要打开任何文档或窗口。",
        )
        is False
    )


def test_bare_no_tool_answer_is_not_an_exit() -> None:
    decision = decide_react_turn(
        tool_calls=[],
        answer="先看一下目录结构再决定下一步。",
    )
    assert decision.exit is None
    assert decision.reason == "no_tools_pending_nudge"


def test_commentary_plus_tools_is_not_exit() -> None:
    decision = decide_react_turn(
        tool_calls=[{"name": "open_file", "args": {"filePath": "a.docx"}, "id": "1"}],
        answer="先调用 open_file 打开这个文件。",
    )
    assert decision.exit is None
    assert decision.drop_tools is False
    assert decision.reason == "acting"


def test_write_nudge_does_not_override_claimed_final() -> None:
    assert (
        _should_nudge_build_to_write(
            "build",
            False,
            0,
            answer=E3_ANSWER,
            user_input=(
                "请打开当前目录下这个不存在的文件：open_e2e_missing_no_such_file.docx。"
                "如果打不开，把工具返回的错误原文告诉我，然后给出最终结果。"
            ),
        )
        is False
    )


def test_incomplete_build_still_not_an_exit() -> None:
    decision = decide_react_turn(
        tool_calls=[],
        answer="Entities done. Now the repositories and the controllers.",
    )
    assert decision.exit is None
    assert decision.reason == "incomplete_build"
