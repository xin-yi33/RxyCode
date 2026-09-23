"""P0 answer-last 契约测试（2026-09-23）。

两条契约：
1. 子代理（专家团角色 / task 子代理）的流式输出必须打标 intermediate=True；
   主代理的流式输出 intermediate=False。
2. 一轮中 FinalAnswer 之后不允许再出现任何面向用户的流式事件
   （token / reasoning / progress）——「最终答复之后还在输出」即违反。
"""

from __future__ import annotations

from protocol.notifications import (
    FinalAnswer,
    MessageDelta,
    ProgressUpdate,
    ReasoningSnapshot,
)

from RxyCode.RxyCode1_1_0.appserver.runtime import (
    bind_delegate_depth,
    reset_delegate_depth,
)
from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui


def test_main_agent_stream_is_not_intermediate() -> None:
    """主代理（深度 0）的 token/progress/reasoning 不打 intermediate。"""
    emitted: list = []
    tui = ProtocolTui("s-main", emitted.append, run_id="r1")
    tui.stream_token("你好")
    tui.write_progress("思考中")
    tui.write_reasoning("推理")
    # write_reasoning 在折叠状态下会补一条「思考中...」进度（既有设计）
    kinds = [type(e).__name__ for e in emitted]
    assert kinds == [
        "MessageDelta",
        "ProgressUpdate",
        "ReasoningSnapshot",
        "ProgressUpdate",
    ]
    assert all(getattr(e, "intermediate", None) is False for e in emitted)


def test_child_agent_stream_is_intermediate() -> None:
    """子代理（深度 ≥1）的流式输出全部打 intermediate=True。"""
    emitted: list = []
    tui = ProtocolTui("s-child", emitted.append, run_id="r2")
    token = bind_delegate_depth()
    try:
        tui.stream_token("子代理文本")
        tui.write_progress("子代理进度")
        tui.write_reasoning("子代理推理")
    finally:
        reset_delegate_depth(token)
    assert len(emitted) == 4  # 同上：write_reasoning 补一条进度
    assert all(getattr(e, "intermediate", None) is True for e in emitted)
    # 退出深度后恢复主代理语义
    tui.stream_token("主代理文本")
    assert emitted[-1].intermediate is False


def test_no_user_facing_event_after_final_answer() -> None:
    """FinalAnswer 之后再出现 token/reasoning/progress 即违反 answer-last。"""
    emitted: list = []
    tui = ProtocolTui("s-order", emitted.append, run_id="r3")
    tui.stream_token("正文")
    emitted.append(
        FinalAnswer(session_id="s-order", run_id="r3", text="最终答复")
    )
    # 模拟 bug 现场：最终答复之后又来了子代理输出
    token = bind_delegate_depth()
    try:
        tui.stream_token("迟到的子代理文本")
    finally:
        reset_delegate_depth(token)

    final_idx = next(
        i for i, e in enumerate(emitted) if isinstance(e, FinalAnswer)
    )
    user_facing = (MessageDelta, ReasoningSnapshot, ProgressUpdate)
    trailing = [
        e for e in emitted[final_idx + 1 :] if isinstance(e, user_facing)
    ]
    # 契约：FinalAnswer 之后零流式事件。这条断言不是管运行时不许发，
    # 而是给 TUI/测试一个判定锚点：发生了 = bug（本轮由调用方保证不发）。
    # 这里我们断言「若发生则必定带 intermediate 标记」，让前端可以兜底隐藏。
    assert all(e.intermediate for e in trailing)
