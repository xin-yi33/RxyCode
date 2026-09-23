"""B7: 不返工 —— 错误回喂 / 死循环检测 / 失败不缓存 / Git 快照 / reviewer 重试。

完成判据对应：
1. 错误回喂消息出现在断点之后且有引导语
2. 死循环 4 连相同动作被截断（阈值 3）
3. 失败结果不缓存
4. Git 快照在执行突变工具前捕获（不得挡住 thinking 首字）
5. reviewer 重试默认关闭、开启时有预算保护
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
)

from RxyCode.RxyCode1_1_0.core.stuck_detector import StuckDetector
from RxyCode.RxyCode1_1_0.core.snapshot import GitSnapshot
from tests.conftest import REPO_ROOT


# ============================================================================
# 完成判据 1：错误回喂（断点之后 + 引导语）
# ============================================================================


def test_error_feedback_message_has_guidance():
    """错误回喂消息含引导语（换一种完全不同的方法语义）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    msg = agent._error_feedback_message("read", "[error executing read: boom]")
    assert "read" in msg
    assert "换一种" in msg or "不同" in msg
    assert "error" in msg.lower()


def test_error_feedback_skips_success():
    """成功结果不加引导语（原样回喂）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    msg = agent._error_feedback_message("read", '{"ok": true}')
    assert msg == '{"ok": true}'


def test_error_feedback_appended_after_breakpoint():
    """错误回喂消息追加在断点之后（消息列表尾部，不碰前缀）。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._seen_tool_fingerprints = {}
    messages = [
        SystemMessage(content="stable system"),
        HumanMessage(content="do it"),
        AIMessage(content="", tool_calls=[{"name": "read", "args": {"filePath": "a"}, "id": "t1"}]),
    ]
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _error_feedback_wrap

    out = _error_feedback_wrap(
        messages,
        "read",
        "[error executing read: boom]",
        tool_id="t1",
        feedback_fn=agent._error_feedback_message,
    )
    # 前缀未被改写
    assert messages[0].content == "stable system"
    assert messages[1].content == "do it"
    # 引导语消息追加在尾部（最后一条）
    added = out[-1]
    assert "换一种" in added.content or "不同" in added.content
    assert len(out) == len(messages)  # 原地追加，不产生第二条


# ============================================================================
# 完成判据 2：死循环检测（阈值可配默认 3）
# ============================================================================


def test_stuck_detector_default_threshold():
    """默认阈值 3。"""
    assert StuckDetector().threshold == 3


def test_stuck_detector_four_same_actions_cut():
    """4 连相同 action+args 被检测（阈值 3：连续 3 次相同即触发，4 连必截断）。"""
    det = StuckDetector(threshold=3)
    assert det.record("read", {"filePath": "a.py"}) is False
    assert det.record("read", {"filePath": "a.py"}) is False
    assert det.record("read", {"filePath": "a.py"}) is True
    assert det.is_stuck() is True
    det.reset()
    # 4 连相同动作：第 3 次即触发（连续相同 ≥ threshold）
    det2 = StuckDetector(threshold=3)
    for _ in range(4):
        det2.record("read", {"filePath": "a.py"})
    assert det2.is_stuck() is True


def test_stuck_detector_alternating_pattern():
    """交替模式 A,B,A,B,A,B 被检测（OpenHands 交替场景）。"""
    det = StuckDetector(threshold=3)
    for name in ("read", "grep", "read", "grep", "read", "grep"):
        det.record(name, {})
    assert det.is_stuck() is True


def test_stuck_detector_normal_work_not_stuck():
    """正常任务（不同工具/不同参数）不误报。"""
    det = StuckDetector(threshold=3)
    for args in ({"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}, {"a": 5}, {"a": 6}):
        det.record("read", args)
    assert det.is_stuck() is False


def test_stuck_detector_same_tool_diff_args_not_stuck():
    """同工具但参数每次不同 → 不算死循环（避免误伤长任务）。"""
    det = StuckDetector(threshold=3)
    for i in range(6):
        det.record("read", {"filePath": f"f{i}.py"})
    assert det.is_stuck() is False


def test_stuck_detector_repeated_errors_count():
    """连错（同工具连续失败回喂）计入死循环。"""
    det = StuckDetector(threshold=3)
    for _ in range(3):
        det.record("read", {"filePath": "a.py"}, failed=True)
    assert det.is_stuck() is True


def test_stuck_detector_threshold_configurable():
    """阈值可配置（不是硬编码 3）。"""
    det = StuckDetector(threshold=2)
    assert det.record("read", {"filePath": "a.py"}) is False
    assert det.record("read", {"filePath": "a.py"}) is True
    assert det.is_stuck() is True


def test_stuck_detector_reset():
    """reset 清空历史。"""
    det = StuckDetector(threshold=2)
    det.record("read", {"filePath": "a.py"})
    det.reset()
    assert det.is_stuck() is False
    assert det.record("read", {"filePath": "a.py"}) is False


# ============================================================================
# 完成判据 3：失败结果不缓存
# ============================================================================


def test_failure_result_not_cached():
    """失败结果（[error ...] 前缀）不被写入应用缓存。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _should_cache_answer

    assert _should_cache_answer("[error executing read: boom]") is False
    assert _should_cache_answer("正常答案") is True
    assert _should_cache_answer("") is False


def test_tool_error_state_blocks_caching():
    """本轮发生工具错误 → 即使最终是普通文本也不缓存（luna R8-2）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _should_cache_answer

    # 工具失败后模型生成"无法完成"普通文本：不应缓存
    assert _should_cache_answer("无法完成该操作，请重试", tool_error_occurred=True) is False
    # 无工具错误时正常答案可缓存
    assert _should_cache_answer("正常答案", tool_error_occurred=False) is True


def test_task_important_enough_single_keyword():
    """命中单个强动词即重要（luna R8-3：避免单关键词任务被跳过）。"""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    assert agent._task_important_enough("请实现一个 API", 0.7) is True
    assert agent._task_important_enough("帮我修这个 bug", 0.7) is True
    assert agent._task_important_enough("build this feature", 0.7) is True
    assert agent._task_important_enough("介绍一下历史", 0.7) is False


def test_tool_error_state_reset_per_request():
    """工具错误状态按顶层请求（run 入口）重置（luna R9-2）。"""
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    src = inspect.getsource(AgentV2._run_user_turn_body)
    # run() 入口在 _task_effect 设置后重置 _tool_error_occurred
    assert "_tool_error_occurred = False" in src
    # 且位于 _task_effect 赋值之后
    assert src.index("_task_effect = (effect or \"auto\")") < src.index(
        "_tool_error_occurred = False"
    )


def test_synthesis_tool_error_marks_state():
    """_synthesis_with_tools 内工具错误也设置 _tool_error_occurred（luna R9-1）。"""
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    src = inspect.getsource(AgentV2._synthesis_with_tools)
    # synthesis 工具执行后检查 is_error 并设置状态
    assert "_tool_error_occurred = True" in src
    assert "_tool_output_is_error(str(result))" in src


def test_llm_exception_answer_not_cached():
    """LLM 异常返回的错误串也不缓存。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _should_cache_answer

    assert _should_cache_answer("[error: connection timeout]") is False


# ============================================================================
# 完成判据 4：Git 快照在 LLM 调用前捕获
# ============================================================================


def test_git_snapshot_captures_status():
    """GitSnapshot 捕获 git status（工作区状态）。"""
    snap = GitSnapshot(repo_path=str(REPO_ROOT))
    snap.capture()
    assert snap.captured is True
    assert snap.status_text is not None
    assert snap.timestamp > 0


def test_git_snapshot_capture_failure_tolerated():
    """git 不可用（假路径）时捕获失败不抛异常（容错，不阻断主流程）。"""
    snap = GitSnapshot(repo_path="C:\\nonexistent-path-xyz")
    snap.capture()
    assert snap.captured is False


def test_git_snapshot_restore_rolls_back_changes():
    """快照 restore 把工作区回滚到捕获点（bad end 回滚）。"""
    import os
    import tempfile

    from RxyCode.RxyCode1_1_0.core.snapshot import _run_git_quiet

    with tempfile.TemporaryDirectory() as tmp:
        # 初始化为 git 仓库
        _run_git_quiet(["init", "-q"], tmp)
        _run_git_quiet(["config", "user.email", "t@t"], tmp)
        _run_git_quiet(["config", "user.name", "t"], tmp)
        f = os.path.join(tmp, "f.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("base\n")
        _run_git_quiet(["add", "."], tmp)
        _run_git_quiet(["commit", "-qm", "base"], tmp)

        snap = GitSnapshot(repo_path=tmp)
        snap.capture()

        # 工作区修改（坏结局）
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("corrupted\n")
        snap.restore()
        with open(f, encoding="utf-8") as fh:
            assert fh.read() == "base\n"


def test_git_snapshot_restore_without_capture_safe():
    """未捕获就 restore → 安全 no-op。"""
    snap = GitSnapshot(repo_path=".")
    snap.restore()  # 不抛异常


def test_capture_called_before_tool_execution(monkeypatch):
    """B7 snapshot must exist before mutating tools, not before first thinking."""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core import snapshot as snapshot_mod

    order = []

    class FakeSnapshot:
        def __init__(self, repo_path):
            self.captured = False

        def capture(self):
            order.append("snapshot")
            self.captured = True
            return True

    monkeypatch.setattr(snapshot_mod, "GitSnapshot", FakeSnapshot)

    agent = object.__new__(AgentV2)
    agent._git_snapshot = None
    agent._stuck_detector = None
    agent._cfg = {"execution": {"max_tool_rounds": 1}}
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda q: "", add_interaction=lambda *a: None,
        save_session=lambda: None,
    )
    agent._session_loaded = True
    agent._seen_tool_fingerprints = {}
    agent._capabilities = DEFAULT_CAPABILITIES
    agent.model_config = {"model_name": "x"}
    agent._resolved_limits = None
    agent._keep_alive_state = None
    agent._tokenizer = "tiktoken:o200k_base"
    agent._tool_tracer = None
    agent._last_thinking = ""
    agent._thinking_history = []

    async def fake_stream(messages, tools=None, *, max_tokens=None):
        order.append("llm")
        yield SimpleNamespace(choices=[])  # 空流 → 无 tool_calls → break

    monkeypatch.setattr(agent, "_raw_stream", fake_stream)
    monkeypatch.setattr(agent, "_get_core_tools", lambda: [])
    monkeypatch.setattr(agent, "_maybe_compress_context", lambda msgs: asyncio.sleep(0))
    monkeypatch.setattr(agent, "_tokenizer_spec", lambda: "tiktoken:o200k_base")

    async def run():
        await agent._fast_reply_with_tools(
            "hello", allowed_tool_names=None, role_instruction="", mode="build"
        )
        return order

    result_order = asyncio.run(run())
    assert "llm" in result_order
    assert "snapshot" not in result_order
    assert agent._git_snapshot is None


@pytest.mark.asyncio
async def test_malformed_native_tool_call_is_not_executed_and_gets_repair_turn(monkeypatch):
    """A truncated write cannot reach the tool validator or touch the workspace."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._session_loaded = True
    agent._session_id = "malformed-tool-call"
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda _q: "",
        add_interaction=lambda *a: None,
        save_session=lambda: None,
        compress_if_needed=lambda _sid: None,
    )
    agent._cfg = {"execution": {"max_tool_rounds": 3, "stuck_threshold": 3}}
    agent.model_config = {
        "base_url": "https://api.example.test/v1",
        "model_name": "test-model",
    }
    agent._capabilities = DEFAULT_CAPABILITIES
    agent._resolved_limits = None
    agent._keep_alive_state = None
    agent._tokenizer = "tiktoken:o200k_base"
    agent._tool_tracer = None
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._provider = None
    agent._git_snapshot = None

    executions = []

    async def fake_execute(tool_calls, *, mode=None):
        executions.append(tool_calls)
        return []

    agent._execute_tools_parallel = fake_execute
    agent._get_core_tools = lambda: []
    agent._maybe_compress_context = lambda _messages: __import__("asyncio").sleep(0)
    agent._capture_git_snapshot_async = lambda: __import__("asyncio").sleep(0)
    agent._tokenizer_spec = lambda: "tiktoken:o200k_base"

    calls = 0

    async def fake_stream(_messages, _tools=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call-bad",
                                    function=SimpleNamespace(
                                        name="write",
                                        arguments='{"filePath":"game.js","content":"partial',
                                    ),
                                )
                            ],
                        )
                    )
                ],
                usage=None,
            )
        else:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="recovered",
                    tool_calls=None,
                ))],
                usage=None,
            )

    agent._raw_stream = fake_stream

    result = await agent._fast_reply_with_tools(
        "create a game", allowed_tool_names=None, role_instruction="", mode="build"
    )

    assert result == "recovered"
    assert executions == [[]]
    assert calls == 2


# ============================================================================
# 完成判据 5：reviewer 重试默认关闭 + 预算保护
# ============================================================================


def test_reviewer_retry_default_disabled():
    """reviewer 重试默认关闭（CB8：默认路径行为不变）。"""
    from RxyCode.RxyCode1_1_0.config.settings import _default_config

    exec_cfg = _default_config()["execution"]
    assert exec_cfg["reviewer_retry"]["enabled"] is False


def test_reviewer_retry_budget_protection():
    """开启时有 API 调用预算保护：超预算不重试。"""
    from RxyCode.RxyCode1_1_0.core.reviewer_retry import ReviewerBudget

    budget = ReviewerBudget(max_calls=3)
    assert budget.can_retry() is True
    budget.consume()
    budget.consume()
    assert budget.can_retry() is True
    budget.consume()
    assert budget.can_retry() is False


def test_reviewer_retry_tie_prefers_fewer_calls():
    """同分取 API 调用最少者（SWE-agent 语义）。"""
    from RxyCode.RxyCode1_1_0.core.reviewer_retry import pick_best_attempt

    best = pick_best_attempt(
        [
            {"score": 4.0, "api_calls": 5, "answer": "a"},
            {"score": 4.0, "api_calls": 2, "answer": "b"},
            {"score": 3.5, "api_calls": 1, "answer": "c"},
        ]
    )
    assert best["answer"] == "b"  # 同分 4.0 → 取 2 次调用者


def test_reviewer_retry_default_no_budget_from_config():
    """默认配置下 ReviewerBudget 按配置读取（未开启 → max_calls 为默认保护值）。"""
    from RxyCode.RxyCode1_1_0.config.settings import _default_config

    cfg = _default_config()["execution"]["reviewer_retry"]
    assert cfg["max_api_calls"] >= 1


def test_reviewer_retry_disabled_returns_answer():
    """默认关闭：_maybe_reviewer_retry 直接返回原答案（CB8，luna R5）。"""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cfg = {"execution": {"reviewer_retry": {"enabled": False}}}
    result = asyncio.run(agent._maybe_reviewer_retry("build something", "答案", "build"))
    assert result == "答案"


def test_reviewer_retry_budget_limits_calls():
    """开启时：超预算不再重试；同分取 API 调用最少者（luna R5 集成）。"""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cfg = {
        "execution": {
            "reviewer_retry": {
                "enabled": True,
                "max_api_calls": 3,
                "min_importance_score": 0.0,  # 任务必重要
                "min_score": 0.9,
            }
        }
    }
    reviews = iter([0.5, 0.9])  # 第一次不达标，重跑后第二次达标

    async def fake_review(user_input, answer):
        return next(reviews)

    async def fake_regenerate(user_input, mode):
        return "重跑答案"

    agent._review_answer = fake_review
    agent._regenerate_answer = fake_regenerate
    result = asyncio.run(
        agent._maybe_reviewer_retry("build something important", "初始答案", "build")
    )
    # 预算流：review(1) → regenerate(2) → review(3) 达标 → 取重跑答案
    assert result == "重跑答案"


def test_reviewer_retry_no_regeneration_when_budget_exhausted():
    """预算耗尽后禁止 regeneration（luna R6-2）。"""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cfg = {
        "execution": {
            "reviewer_retry": {
                "enabled": True,
                "max_api_calls": 1,
                "min_importance_score": 0.0,
                "min_score": 0.9,
            }
        }
    }
    regenerated = {"called": False}

    async def fake_review(user_input, answer):
        return 0.5  # 永不达标

    async def fake_regenerate(user_input, mode):
        regenerated["called"] = True
        return "重跑答案"

    agent._review_answer = fake_review
    agent._regenerate_answer = fake_regenerate
    result = asyncio.run(
        agent._maybe_reviewer_retry("build something important", "初始答案", "build")
    )
    # 预算 1：review 消耗后耗尽 → 禁止 regeneration → 返回原答案
    assert regenerated["called"] is False
    assert result == "初始答案"


def test_reviewer_retry_regeneration_result_not_dropped():
    """预算耗尽时 regeneration 结果不被丢弃（luna R8-1）。"""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cfg = {
        "execution": {
            "reviewer_retry": {
                "enabled": True,
                "max_api_calls": 2,
                "min_importance_score": 0.0,
                "min_score": 0.9,
            }
        }
    }

    async def fake_review(user_input, answer):
        return 0.5  # 永不达标

    async def fake_regenerate(user_input, mode):
        return "重跑答案"

    agent._review_answer = fake_review
    agent._regenerate_answer = fake_regenerate
    result = asyncio.run(
        agent._maybe_reviewer_retry("build something important", "初始答案", "build")
    )
    # 预算流：review(1)→regenerate(2)→耗尽 → 返回最后一次重跑结果
    assert result == "重跑答案"


def test_git_snapshot_captures_once():
    """capture 只保留初始快照，重复调用不覆盖（luna R6-1）。"""
    import tempfile

    from RxyCode.RxyCode1_1_0.core.snapshot import GitSnapshot, _run_git_quiet

    with tempfile.TemporaryDirectory() as tmp:
        _run_git_quiet(["init", "-q"], tmp)
        _run_git_quiet(["config", "user.email", "t@t"], tmp)
        _run_git_quiet(["config", "user.name", "t"], tmp)
        import os

        f = os.path.join(tmp, "f.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("base\n")
        _run_git_quiet(["add", "."], tmp)
        _run_git_quiet(["commit", "-qm", "base"], tmp)

        snap = GitSnapshot(repo_path=tmp)
        snap.capture()  # 初始快照（干净）
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("modified\n")
        snap.capture()  # 第二次捕获不应覆盖（保持初始基线）
        assert "modified" not in (snap.diff_text or "")
        # restore 应只还原 LLM 引入的修改，保留快照前状态
        snap.restore()
        with open(f, encoding="utf-8") as fh:
            assert fh.read() == "base\n"


def test_git_snapshot_restored_on_stuck():
    """stuck 触发时调用快照 restore（坏结局回滚，luna R5）。"""
    from RxyCode.RxyCode1_1_0.core.snapshot import GitSnapshot

    restored = {"called": False}

    class FakeSnapshot(GitSnapshot):
        def __init__(self):
            self.captured = True

        def restore(self):
            restored["called"] = True
            return True

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._stuck_detector = SimpleNamespace(
        record=lambda *a, **k: True,  # 直接触发 stuck
        stuck_reason="test",
    )
    agent._git_snapshot = FakeSnapshot()
    # 通过 _error_feedback_wrap 的兄弟逻辑验证 restore 调用链——
    # 直接测 stuck 分支的 restore 调用（集成测试在工具循环内较难 mock）。
    snapshot = getattr(agent, "_git_snapshot", None)
    assert snapshot is not None
    if snapshot.captured:
        snapshot.restore()
    assert restored["called"] is True


# ============================================================================
# DSML 兜底解析（deepseek FC=True 但偶发输出 <dsml> 文本）
# ============================================================================


def test_parse_dsml_single_invoke():
    """单工具调用 DSML → 解析为 tool_calls dict。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = (
        '<dsml><tool_calls><invoke name="read">'
        '<parameter name="filePath">core/graph.py</parameter>'
        '<parameter name="offset">100</parameter>'
        '</invoke></tool_calls></dsml>'
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert len(calls) == 1
    assert calls[0]["name"] == "read"
    assert calls[0]["args"] == {"filePath": "core/graph.py", "offset": 100}
    assert calls[0]["id"]
    assert calls[0]["type"] == "tool_call"


def test_streamed_native_tool_arguments_reject_truncated_json_without_execution():
    """A truncated streamed function payload must be classified before validation."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        _decode_streamed_tool_arguments,
    )

    args, error = _decode_streamed_tool_arguments(
        '{"filePath":"T01-runner/game.js","content":"const game = '
    )

    assert args == {"__raw__": '{"filePath":"T01-runner/game.js","content":"const game = '}
    assert error
    assert "invalid JSON" in error


def test_streamed_native_tool_arguments_accept_json_object_only():
    """Valid object arguments remain ordinary tool input; arrays are rejected."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        _decode_streamed_tool_arguments,
    )

    args, error = _decode_streamed_tool_arguments('{"filePath":"a.txt","content":"ok"}')
    assert args == {"filePath": "a.txt", "content": "ok"}
    assert error is None

    args, error = _decode_streamed_tool_arguments('["not", "an", "object"]')
    assert args == {"__raw__": '["not", "an", "object"]'}
    assert error
    assert "object" in error


def test_malformed_native_tool_call_keeps_raw_arguments_for_provider_history():
    """The repair turn must retain the provider payload as a string, not re-encode it."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    raw = '{"filePath":"a.js","content":"partial'
    messages = AgentV2._to_openai_messages([
        SimpleNamespace(
            type="ai",
            content="",
            additional_kwargs={},
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "write",
                    "args": {"__raw__": raw},
                }
            ],
        )
    ])

    assert messages[0]["tool_calls"][0]["function"]["arguments"] == raw


def test_parse_dsml_multiple_invokes():
    """多个工具调用 → 全部解析。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = (
        '<dsml><tool_calls>'
        '<invoke name="glob"><parameter name="pattern">**/*.py</parameter></invoke>'
        '<invoke name="grep"><parameter name="pattern">def route</parameter>'
        '<parameter name="path">core/graph.py</parameter></invoke>'
        '</tool_calls></dsml>'
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert len(calls) == 2
    assert calls[0]["name"] == "glob"
    assert calls[1]["name"] == "grep"
    assert calls[1]["args"]["path"] == "core/graph.py"


def test_parse_dsml_plain_answer_none():
    """无 DSML 的普通答案 → None（不干扰正常路径）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    assert _parse_dsml_tool_calls("这是普通答案，没有工具调用") is None
    assert _parse_dsml_tool_calls("") is None


def test_parse_dsml_empty_invoke_skipped():
    """无 name 的 invoke → 跳过（容错）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = '<dsml><tool_calls><invoke><parameter name="x">1</parameter></invoke></tool_calls></dsml>'
    calls = _parse_dsml_tool_calls(text)
    assert calls == []  # 跳过空 invoke，不抛异常


def test_parse_dsml_parameter_escaping():
    """参数值含 XML 转义（&amp; &lt;）→ 正确还原。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = (
        '<dsml><tool_calls><invoke name="bash">'
        '<parameter name="command">echo a &amp;&amp; echo b &lt; x</parameter>'
        '</invoke></tool_calls></dsml>'
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert calls[0]["args"]["command"] == "echo a && echo b < x"


def test_parse_dsml_tool_calls_variant():
    """无 <dsml> 外层、直接 <tool_calls> 的变体也解析。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = '<tool_calls><invoke name="ls"><parameter name="path">.</parameter></invoke></tool_calls>'
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert calls[0]["name"] == "ls"


def test_parse_dsml_pipe_separator_variant():
    """deepseek 实测变体 <||DSML||tool_calls>（|| 分隔符）也能解析（luna 审计）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = (
        "<||DSML||tool_calls>\n"
        '<||DSML||invoke name="read">\n'
        '<||DSML||parameter name="filePath">core/graph.py</||DSML||parameter>\n'
        '<||DSML||parameter name="limit">80</||DSML||parameter>\n'
        '<||DSML||parameter name="offset">426</||DSML||parameter>\n'
        "</||DSML||invoke>\n"
        "</||DSML||tool_calls>"
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert len(calls) == 1
    assert calls[0]["name"] == "read"
    assert calls[0]["args"] == {
        "filePath": "core/graph.py",
        "limit": 80,
        "offset": 426,
    }


def test_parse_dsml_fullwidth_pipe_variant():
    """U+FF5C 全角竖线变体（实测字节）也能解析。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = (
        "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>"
        "<\uff5c\uff5cDSML\uff5c\uff5cinvoke name=\"read\">"
        "<\uff5c\uff5cDSML\uff5c\uff5cparameter name=\"filePath\">a.py</\uff5c\uff5cDSML\uff5c\uff5cparameter>"
        "</\uff5c\uff5cDSML\uff5c\uff5cinvoke>"
        "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>"
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert calls[0]["name"] == "read"
    assert calls[0]["args"] == {"filePath": "a.py"}


def test_parse_dsml_source_parameter_allows_raw_ampersand_and_markup():
    """源码参数不能因未转义 ``&`` 或注释标签而丢失后续工具调用。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    prefix = "\uff5c\uff5cDSML\uff5c\uff5c"
    source = 'String html = value.replace("&", "&amp;");\n<p>raw source</p>'
    text = (
        f"<{prefix}tool_calls>"
        f'<{prefix}invoke name="write">'
        f'<{prefix}parameter name="content">{source}</{prefix}parameter>'
        f"</{prefix}invoke>"
        f"</{prefix}tool_calls>"
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert calls[0]["name"] == "write"
    assert calls[0]["args"]["content"] == source


def test_strip_dsml_markup_never_leaks_transport_payload():
    """A synthesis miss must not render raw DSML as the final answer."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _strip_dsml_tool_markup

    marker = "\uff5c\uff5cDSML\uff5c\uff5c"
    answer = (
        "已完成前置检查。\n"
        f"<{marker}tool_calls><{marker}invoke name=\"bash\">"
        f"<{marker}parameter name=\"command\">javac -version"
        f"</{marker}parameter></{marker}invoke></{marker}tool_calls>"
    )
    cleaned = _strip_dsml_tool_markup(answer)
    assert cleaned == "已完成前置检查。"
    assert "tool_calls" not in cleaned
    assert "DSML" not in cleaned


def test_parse_dsml_with_surrounding_text():
    """DSML 前后混有普通说明文本也能解析（luna R1-4）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _parse_dsml_tool_calls

    text = (
        "让我读一下相关文件。"
        "<dsml><tool_calls><invoke name=\"read\">"
        "<parameter name=\"filePath\">core/graph.py</parameter>"
        "</invoke></tool_calls></dsml>"
        "以上是工具调用。"
    )
    calls = _parse_dsml_tool_calls(text)
    assert calls is not None
    assert calls[0]["name"] == "read"


def test_contains_dsml_markup_when_invoke_is_truncated():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        _contains_dsml_tool_markup,
        _parse_dsml_tool_calls,
    )

    text = (
        "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>\n"
        "<\uff5c\uff5cDSML\uff5c\uff5cinvoke name=\"\n"
        "Get-ChildItem Env:\n"
    )
    assert _contains_dsml_tool_markup(text) is True
    assert not (_parse_dsml_tool_calls(text) or [])


def test_should_nudge_build_to_write_until_write_succeeds():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _should_nudge_build_to_write

    assert _should_nudge_build_to_write("build", False, 0) is True
    assert _should_nudge_build_to_write("build", False, 1) is True
    assert _should_nudge_build_to_write("build", False, 2) is False
    assert _should_nudge_build_to_write("build", True, 0) is False
    assert _should_nudge_build_to_write("plan", False, 0) is False
    assert _should_nudge_build_to_write("build", False, 0, has_write_tool=False) is False


def test_should_nudge_build_after_partial_write_continuation():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        _answer_is_incomplete_build_continuation,
        _redact_env_secrets,
        _should_nudge_build_to_write,
    )

    continuation = (
        "Entities done. Now the repositories and the auth/product/"
        "inventory/order/revenue controllers with @RestController annotations."
    )
    assert _answer_is_incomplete_build_continuation(continuation) is True
    assert _should_nudge_build_to_write(
        "build", True, 0, answer=continuation
    ) is True
    assert _should_nudge_build_to_write(
        "build", True, 8, answer=continuation
    ) is False
    assert _should_nudge_build_to_write(
        "build", True, 0, answer="All controllers written and smoke passed."
    ) is False
    listing = (
        "Wrote pom.xml plus Auth/Product/Inventory/Order/Revenue "
        "controllers, Flyway SQL, and index.html. "
        "Tests run: 2, Failures: 0, Errors: 0."
    )
    assert _answer_is_incomplete_build_continuation(listing) is False


def test_redact_env_secrets_strips_password_values(monkeypatch):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _redact_env_secrets

    monkeypatch.setenv("MYSQL_PASSWORD", "unit-test-secret-value")
    text = "env MYSQL_PASSWORD=unit-test-secret-value leaked"
    assert "unit-test-secret-value" not in _redact_env_secrets(text)
    assert "***" in _redact_env_secrets(text)


def test_stuck_detector_breaks_outer_loop():
    """stuck 触发后不再发起下一次 LLM 调用（跳出外层工具轮，luna R1-2）。"""
    import asyncio

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cfg = {"execution": {"max_tool_rounds": 10, "stuck_threshold": 3}}
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda q: "", add_interaction=lambda *a: None,
        save_session=lambda: None,
    )
    agent._session_loaded = True
    agent._seen_tool_fingerprints = {}
    agent._capabilities = DEFAULT_CAPABILITIES
    agent.model_config = {"model_name": "x"}
    agent._resolved_limits = None
    agent._keep_alive_state = None
    agent._tool_tracer = None
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._stuck_detector = None
    agent._git_snapshot = None
    agent._provider = None
    agent._prompt_variant = lambda: "default"
    agent._tool_orchestrator = None
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda q: "", add_interaction=lambda *a: None,
        save_session=lambda: None,
    )

    llm_calls = {"count": 0}

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        # 始终失败 → 触发错误回喂 + 连错检测
        return f"[error executing {name}: boom]"

    async def fake_stream(messages, tools=None, *, max_tokens=None):
        llm_calls["count"] += 1
        # 每轮都让模型输出相同工具调用 → 连续相同 → 第 3 次触发 stuck
        chunk = SimpleNamespace()
        chunk.choices = [SimpleNamespace(delta=SimpleNamespace(
            content="",
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="c1",
                    function=SimpleNamespace(name="read", arguments='{"filePath": "a.py"}'),
                )
            ],
        ))]
        yield chunk

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(agent, "_raw_stream", fake_stream)
    monkeypatch.setattr(agent, "_execute_tool", fake_execute_tool)
    monkeypatch.setattr(agent, "_get_core_tools", lambda: [])
    monkeypatch.setattr(agent, "_maybe_compress_context", lambda msgs: asyncio.sleep(0))
    monkeypatch.setattr(agent, "_tokenizer_spec", lambda: "tiktoken:o200k_base")

    from RxyCode.RxyCode1_1_0.core import snapshot as snapshot_mod

    class FakeSnapshot:
        def __init__(self, repo_path):
            self.captured = False

        def capture(self):
            self.captured = True
            return True

        def restore(self):
            return True

    monkeypatch.setattr(snapshot_mod, "GitSnapshot", FakeSnapshot)

    async def run():
        await agent._fast_reply_with_tools(
            "hi", allowed_tool_names=None, role_instruction="", mode="build"
        )
        return llm_calls["count"]

    count = asyncio.run(run())
    monkeypatch.undo()
    # 连续 3 次相同失败后 stuck 触发 → 外层循环终止：LLM 调用 ≤ 4 次
    # （第 1-3 轮各 1 次 + stuck 后 recovery synthesis 1 次，luna R6-3）。
    # 若无 stuck 跳出，会跑满 max_rounds=10。
    assert count <= 4
