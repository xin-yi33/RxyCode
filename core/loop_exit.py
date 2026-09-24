"""ReAct loop exit diamond.

Stop when ANY of these holds (user contract 2026-09-21):

1. 任务完成
2. final-answer 调用 (tool ``final_answer`` / ``final-answer``, or labeled
   Final Answer / 最终结果 as the ReAct action)
3. 连续错误次数超限 — ``ERROR_LIMIT = 5``. 一次成功会清零连续计数；
   不是会话内错误总和，也不是第一次 ``[error]`` 就停
4. LLM 返回要求退出

「本轮没有工具调用」不是退出条件。单次 user turn 的 ``max_tool_rounds``
也不是退出条件：触顶时把空转/重复降级为 ``[error]`` 回喂 LLM，只有连续
错误满 5 才停。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# 废弃代码（2026-09-21）：曾经没有独立的退出判定，无工具轮默认落到
# write-nudge / research-prefetch 的 continue。禁止再靠隐式 break 当退出条件。
# 废弃代码（2026-09-21）：曾把 no_tool_calls / stuck@3 / 第一次 [error /
# MAX_ROUNDS 当退出。无工具不是退出；满轮次只降级为报错回喂。
# 错误退出只认连续次数 >= ERROR_LIMIT。

ERROR_LIMIT = 5

FINAL_ANSWER_TOOL_NAMES = frozenset({"final_answer", "final-answer"})


class ReactExit(str, Enum):
    """Why the ReAct loop must stop. ``None`` on the decision means continue."""

    TASK_COMPLETE = "task_complete"
    FINAL_ANSWER_CALL = "final_answer_call"
    ERROR_LIMIT = "error_limit"
    LLM_REQUESTS_EXIT = "llm_requests_exit"
    # 废弃代码（2026-09-21）：MAX_ROUNDS = "max_rounds"
    # 单次 user turn 触顶改为 [error] 回喂，不再作为独立退出枚举。


# ReAct Action form of final-answer 调用. Commentary such as "then give the
# Final Answer" without a heading does not match.
# 废弃代码（2026-09-22）：旧式只认行首「最终结果」或「最终结果：」。
# **最终结果** 这种 Markdown 标题匹配失败，write-nudge 会在最终结果之后继续 write。
# r"(?im)^(?:#{1,3}\s*)?(?:final\s*answer|最终结果|最终回答)\s*[:：]?"
_FINAL_ANSWER_LABEL = r"(?:final\s*answer|最终结果|最终回答)"
_FINAL_ANSWER_CALL_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:#{1,3}\s*)?(?:\*{1,2}|_{1,2})?"
    + _FINAL_ANSWER_LABEL
    + r"(?:\*{1,2}|_{1,2})?\s*[:：]?"
    r"|"
    + _FINAL_ANSWER_LABEL
    + r"\s*[:：]\s*\S"
    r"|(?:以上就是|这就是)(?:最终|全部)结果"
)

_TASK_COMPLETE_RE = re.compile(
    r"(?im)(?:任务(?:已)?完成|已完成用户(?:的)?要求|"
    r"(?:the )?task is complete|i have completed (?:the )?(?:task|request))"
    r"(?:[。.!！]|$)"
)

_LLM_EXIT_RE = re.compile(
    r"(?im)(?:请?(?:结束|退出)(?:本轮|本回合|任务|循环)|就此结束|"
    r"stop here|end this turn|no further (?:tools|actions?)|"
    r"i(?:'| a)?m done(?: here)?|"
    r"^(?:exit|quit)\s*$)"
)

_TOOL_RESULT_QUOTE_RE = re.compile(
    r"\[(?:error:|opened |blocked:|launched\b)",
    re.IGNORECASE,
)

_INCOMPLETE_BUILD_CONTINUATION_RE = re.compile(
    r"(请继续|let me write|i(?:'| a)?m going to write|i will write|"
    r"now the (?:repositories|controllers|resources|services)|"
    r"entities done|尚未写入|未写入|next i(?: will|'ll)|"
    r"powershell has quoting)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReactTurnDecision:
    """Result of the exit diamond after one model turn."""

    exit: ReactExit | None
    drop_tools: bool
    reason: str


def is_final_answer_tool(name: str) -> bool:
    folded = (name or "").strip().lower().replace("-", "_")
    return folded in {"final_answer"} or (name or "").strip().lower() in FINAL_ANSWER_TOOL_NAMES


def _call_name(tool_call: object) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "")
    return str(getattr(tool_call, "name", "") or "")


def has_final_answer_call(tool_calls: list | tuple | None) -> bool:
    return any(is_final_answer_tool(_call_name(tc)) for tc in (tool_calls or ()))


def drop_tools_after_final_answer(tool_calls: list | tuple | None) -> list:
    """Keep tools up to and including the first final_answer; drop the rest."""
    kept: list = []
    for tc in tool_calls or ():
        kept.append(tc)
        if is_final_answer_tool(_call_name(tc)):
            break
    return kept


def claimed_final_answer_call(answer: str) -> bool:
    """True when the model emitted the ReAct Final Answer action in text."""
    text = str(answer or "").strip()
    if not text:
        return False
    return bool(_FINAL_ANSWER_CALL_RE.search(text))


def task_complete_text(answer: str) -> bool:
    text = str(answer or "").strip()
    if not text:
        return False
    return bool(_TASK_COMPLETE_RE.search(text))


def llm_requests_exit(answer: str) -> bool:
    """True when the model text asks to end this turn (condition 4)."""
    text = str(answer or "").strip()
    if not text:
        return False
    return bool(_LLM_EXIT_RE.search(text))


def claimed_final_answer(answer: str) -> bool:
    """True when labeled text already satisfies any of 1 / 2 / 4.

    Used by write-nudge so none of the four exits are overridden.
    """
    return (
        claimed_final_answer_call(answer)
        or task_complete_text(answer)
        or llm_requests_exit(answer)
    )


def quoted_tool_result(answer: str) -> bool:
    """True when the answer pastes a tool return the user asked to see."""
    return bool(_TOOL_RESULT_QUOTE_RE.search(str(answer or "")))


SPIN_ERROR_MESSAGE = (
    "[error: this turn is spinning or repeating with no progress. "
    "If the task is done, call final_answer or label 最终结果. "
    "Otherwise take a different action; do not repeat the same step.]"
)


def bump_consecutive_errors(count: int, *, failed: bool) -> int:
    """Count a consecutive error streak. A success resets to 0."""
    if not failed:
        return 0
    return int(count or 0) + 1


def is_incomplete_build_continuation(answer: str) -> bool:
    text = str(answer or "").strip()
    if not text:
        return False
    return bool(_INCOMPLETE_BUILD_CONTINUATION_RE.search(text))


def react_exit_should_stop(
    decision: ReactTurnDecision,
    *,
    write_still_required: bool,
) -> bool:
    """Whether this exit ends the turn.

    A labeled 最终结果 / 任务完成 stops a read-only turn. It must not stop a
    build that asked for a file write and has not written one yet: the same
    prompt otherwise exits on the first prose reply and the evidence gate
    reports "no verified WRITE" with no tool cards.
    """
    if decision.exit is None:
        return False
    if decision.exit == ReactExit.ERROR_LIMIT:
        return True
    if write_still_required and decision.exit in {
        ReactExit.FINAL_ANSWER_CALL,
        ReactExit.TASK_COMPLETE,
    }:
        return False
    return True


def decide_react_turn(
    *,
    tool_calls: list | tuple,
    answer: str,
    incomplete_dsml: bool = False,
    error_count: int = 0,
    file_write_succeeded: bool = False,
    user_input: str = "",
) -> ReactTurnDecision:
    """Return whether this model turn stops the loop.

    Tool calls are dropped when the same turn also hit 任务完成 / labeled
    final-answer / LLM 要求退出. The ``final_answer`` tool itself is kept so
    the caller can execute it, then stop (condition 2).
    """
    n_tools = len(tool_calls or ())
    text = str(answer or "").strip()
    preview_task = False
    if user_input:
        from RxyCode.RxyCode1_1_0.core.agents.router import is_open_only_preview_task

        preview_task = is_open_only_preview_task(user_input)

    # 3. 连续错误次数超限（>= 5；成功会清零，不是会话累计）
    if int(error_count or 0) >= ERROR_LIMIT:
        return ReactTurnDecision(
            exit=ReactExit.ERROR_LIMIT,
            drop_tools=n_tools > 0,
            reason="consecutive errors >= 5",
        )

    # 2. final-answer 调用 — 保留工具供本轮执行，调用方执行后退出
    if has_final_answer_call(tool_calls):
        return ReactTurnDecision(
            exit=None,
            drop_tools=False,
            reason="final_answer_tool",
        )
    if claimed_final_answer_call(text):
        return ReactTurnDecision(
            exit=ReactExit.FINAL_ANSWER_CALL,
            drop_tools=n_tools > 0,
            reason="claimed Final Answer / 最终结果",
        )

    # 1. 任务完成
    if task_complete_text(text):
        return ReactTurnDecision(
            exit=ReactExit.TASK_COMPLETE,
            drop_tools=n_tools > 0,
            reason="task complete",
        )
    if (
        n_tools == 0
        and file_write_succeeded
        and text
        and not is_incomplete_build_continuation(text)
    ):
        return ReactTurnDecision(
            exit=ReactExit.TASK_COMPLETE,
            drop_tools=False,
            reason="write succeeded and task complete",
        )

    # 4. LLM 返回要求退出
    if llm_requests_exit(text):
        return ReactTurnDecision(
            exit=ReactExit.LLM_REQUESTS_EXIT,
            drop_tools=n_tools > 0,
            reason="llm requested exit",
        )

    if n_tools:
        return ReactTurnDecision(
            exit=None,
            drop_tools=False,
            reason="acting",
        )
    if incomplete_dsml:
        return ReactTurnDecision(
            exit=None,
            drop_tools=False,
            reason="incomplete_dsml",
        )
    if not text:
        return ReactTurnDecision(
            exit=None,
            drop_tools=False,
            reason="empty",
        )
    if quoted_tool_result(text) and (
        preview_task or not is_incomplete_build_continuation(text)
    ):
        return ReactTurnDecision(
            exit=ReactExit.TASK_COMPLETE,
            drop_tools=False,
            reason="quoted tool result is the answer",
        )
    if is_incomplete_build_continuation(text):
        return ReactTurnDecision(
            exit=None,
            drop_tools=False,
            reason="incomplete_build",
        )
    # 本轮没有工具调用不是退出。Caller 可 write-nudge / prefetch，
    # 都不适用则把空转降级为 [error] 回喂（计入连续错误）。
    return ReactTurnDecision(
        exit=None,
        drop_tools=False,
        reason="no_tools_pending_nudge",
    )
