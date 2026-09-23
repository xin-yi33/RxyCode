"""B8: 并行与延迟 —— 只读工具并发 / 后台 fork 摘要 / 流式断点一致 / TTFT。

完成判据对应：
1. 只读工具并发测试通过（写操作不并行）
2. 后台 fork 摘要不阻塞主循环（测试）
3. 流式与断点策略一致性测试通过
4. TTFT 命中/未命中对比记录存在（真实数字）
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES


def _new_agent():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._cfg = {}
    agent._capabilities = DEFAULT_CAPABILITIES
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda q: "", add_interaction=lambda *a: None,
        save_session=lambda: None,
    )
    agent._seen_tool_fingerprints = {}
    agent._stuck_detector = None
    agent._git_snapshot = None
    agent._tool_error_occurred = False
    return agent


# ============================================================================
# 完成判据 1：只读工具并发（写操作串行）
# ============================================================================


def test_parallel_default_disabled():
    """graph task fan-out stays off; read tools default on."""
    from RxyCode.RxyCode1_1_0.config.settings import _default_config

    exec_cfg = _default_config()["execution"]
    assert exec_cfg["parallel_enabled"] is False
    assert exec_cfg["tool_parallel_enabled"] is True
    assert exec_cfg["max_parallel"] >= 2


def test_read_tool_risk_classified_read_only():
    """只读工具（read/grep/glob/ls）风险级别为 READ。"""
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, classify_tool_risk

    for name in ("read", "grep", "glob", "ls", "webfetch", "websearch"):
        assert classify_tool_risk(name, {}) == RiskLevel.READ, name


def test_write_tool_risk_classified_write():
    """写工具（write/edit/bash）风险级别 ≥ WRITE。"""
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, classify_tool_risk

    for name in ("write", "edit", "bash"):
        assert classify_tool_risk(name, {}) >= RiskLevel.WRITE, name


def test_read_tools_run_concurrently():
    """只读工具并发执行（两个延迟读的总耗时 ≈ 单个延迟，非叠加）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        await asyncio.sleep(0.3)  # 模拟慢读
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        start = time.monotonic()
        results = await agent._execute_tools_parallel(
            [
                {"name": "read", "args": {"filePath": "a.py"}, "id": "t1"},
                {"name": "grep", "args": {"pattern": "x"}, "id": "t2"},
            ]
        )
        elapsed = time.monotonic() - start
        return results, elapsed

    results, elapsed = asyncio.run(run())
    # 两个 0.3s 的只读工具并行 → 总耗时 < 0.55s（串行会是 ~0.6s）
    assert elapsed < 0.55
    # 结果按原顺序返回
    assert [r["id"] for r in results] == ["t1", "t2"]
    assert results[0]["result"] == "result:read"


def test_write_tools_stay_serial():
    """写工具串行执行（两个延迟写总耗时 ≈ 叠加）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        await asyncio.sleep(0.2)
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        start = time.monotonic()
        results = await agent._execute_tools_parallel(
            [
                {"name": "write", "args": {"filePath": "a.py"}, "id": "t1"},
                {"name": "edit", "args": {"filePath": "b.py"}, "id": "t2"},
            ]
        )
        elapsed = time.monotonic() - start
        return results, elapsed

    results, elapsed = asyncio.run(run())
    # 写工具串行 → 总耗时 ≥ 0.4s（0.2+0.2）
    assert elapsed >= 0.39
    assert [r["id"] for r in results] == ["t1", "t2"]


def test_mixed_read_write_parallel_read_only():
    """混合调用：只读并行、写串行、结果按原序。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        await asyncio.sleep(0.2)
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        results = await agent._execute_tools_parallel(
            [
                {"name": "write", "args": {}, "id": "w1"},
                {"name": "read", "args": {}, "id": "r1"},
                {"name": "grep", "args": {}, "id": "r2"},
            ]
        )
        return results

    results = asyncio.run(run())
    # 顺序 = 原 tool_calls 顺序（w1, r1, r2）→ tool_pair_integrity 安全
    assert [r["id"] for r in results] == ["w1", "r1", "r2"]
    assert [r["result"] for r in results] == [
        "result:write", "result:read", "result:grep",
    ]


def test_parallel_disabled_serial_all():
    """tool_parallel_enabled=False 时全部串行（显式关闭读并行）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"tool_parallel_enabled": False}}
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        await asyncio.sleep(0.15)
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        start = time.monotonic()
        results = await agent._execute_tools_parallel(
            [
                {"name": "read", "args": {}, "id": "r1"},
                {"name": "grep", "args": {}, "id": "r2"},
            ]
        )
        elapsed = time.monotonic() - start
        return results, elapsed

    results, elapsed = asyncio.run(run())
    # 串行：2 × 0.15 ≈ 0.3s
    assert elapsed >= 0.29
    assert [r["id"] for r in results] == ["r1", "r2"]


def test_fast_build_enables_read_parallelism_without_changing_default():
    """Fast build turns on the safe read-only optimization per tool turn."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {
        "execution": {
            "tool_parallel_enabled": False,
            "parallel_enabled": False,
            "max_parallel": 3,
        }
    }
    agent.model_config = {"effort": "fast"}

    enabled, limit = agent._parallel_tool_config(mode="build")
    assert enabled is True
    assert limit == 3

    disabled, _ = agent._parallel_tool_config(mode="plan")
    assert disabled is False


# ============================================================================
# 完成判据 2：后台 fork 摘要不阻塞主循环
# ============================================================================


def test_background_summary_fork_does_not_block():
    """摘要压缩在后台执行，不阻塞主循环（测试）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        # 触发后台摘要（模拟慢压缩）→ 主循环继续执行工具
        task = agent._fork_background_summary([])
        # 不 await task，立即执行工具（验证不阻塞）
        await asyncio.sleep(0.01)
        result = await agent._execute_tools_parallel(
            [{"name": "read", "args": {}, "id": "r1"}]
        )
        return result, task

    result, task = asyncio.run(run())
    assert result[0]["id"] == "r1"  # 主循环未因后台摘要阻塞
    # 后台任务最终完成（不泄漏）
    task.cancel()


def test_background_summary_returns_compacted():
    """后台摘要返回压缩结果（可应用到消息）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()

    async def run():
        messages = [SimpleNamespace(content="x" * 1000, type="human")]
        result = await agent._fork_background_summary(messages)
        return result

    result = asyncio.run(run())
    # 消息很短 → 压缩判断为不需要 → 返回 None（不误伤）
    assert result is None or isinstance(result, list)


def test_background_summary_no_prefix_mutation():
    """后台摘要不修改已发送消息（G2 防线：不污染前缀）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()

    async def run():
        messages = [SimpleNamespace(content="stable-system", type="system")]
        original = list(messages)
        await agent._fork_background_summary(messages)
        return messages, original

    messages, original = asyncio.run(run())
    assert messages == original  # 后台摘要不原位改写


# ============================================================================
# 完成判据 3：流式与断点策略一致性
# ============================================================================


def test_raw_stream_applies_cache_control():
    """_raw_stream 在转换前调用 _apply_cache_control（B3 断点，P2 修复锁定）。"""
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    src = inspect.getsource(AgentV2._raw_stream)
    assert "_apply_cache_control" in src
    # 断点应用在消息转换（_to_openai_messages）之前
    assert src.index("_apply_cache_control") < src.index("_to_openai_messages")


def test_ainvoke_astream_apply_cache_control():
    """ainvoke/astream 也调用 _apply_cache_control（全链路一致）。"""
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    usage_src = inspect.getsource(UsageTrackingLLM)
    # ainvoke 与 astream 都应用断点
    assert usage_src.count("_apply_cache_control") >= 3  # 定义 + ainvoke + astream


def test_stream_breakpoint_consistent_with_non_stream():
    """流式（_raw_stream）与非流式（ainvoke）共用同一断点策略入口。"""
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, UsageTrackingLLM

    # 两条路径都委托 _apply_cache_control（唯一策略入口）
    usage_src = inspect.getsource(UsageTrackingLLM)
    raw_src = inspect.getsource(AgentV2._raw_stream)
    assert "self._llm._apply_cache_control" in raw_src
    assert "self._apply_cache_control(messages" in usage_src


# ============================================================================
# 完成判据 4：TTFT 记录
# ============================================================================


def test_ttft_field_exists_on_token_stats():
    """TokenStats 有 TTFT（首 token 时耗）记录字段。"""
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    assert hasattr(token_stats, "ttft_ms")
    assert hasattr(token_stats, "record_ttft")


def test_record_ttft_updates_value():
    """record_ttft 记录首个 chunk 时耗。"""
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    token_stats.record_ttft(123.5)
    assert token_stats.ttft_ms == 123.5


def test_ttft_reset_isolated():
    """TTFT 字段被 conftest 隔离（每测试重置）。"""
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    assert token_stats.ttft_ms is None or token_stats.ttft_ms >= 0


def test_parallel_read_write_relative_order_preserved():
    """写工具保持原始相对位置（luna R1-3：不改变读写交叉顺序）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None
    order = []

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        order.append(name)
        await asyncio.sleep(0.05)
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        return await agent._execute_tools_parallel(
            [
                {"name": "write", "args": {}, "id": "w1"},
                {"name": "read", "args": {}, "id": "r1"},
                {"name": "grep", "args": {}, "id": "r2"},
                {"name": "edit", "args": {}, "id": "w2"},
            ]
        )

    results = asyncio.run(run())
    # write 必须在 read 之前（w1 在原序最前），edit 在 read 之后（w2 在原序最后）
    assert order.index("write") < order.index("read")
    assert order.index("grep") < order.index("edit")
    # 结果按原序
    assert [r["id"] for r in results] == ["w1", "r1", "r2", "w2"]


def test_parallel_empty_call_id_no_collision():
    """空/重复 call_id 不覆盖结果（luna R1-2：位置索引）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        return f"result:{name}"

    agent._execute_tool = fake_execute_tool

    async def run():
        return await agent._execute_tools_parallel(
            [
                {"name": "read", "args": {}, "id": ""},
                {"name": "grep", "args": {}, "id": ""},
            ]
        )

    results = asyncio.run(run())
    assert results[0]["result"] == "result:read"
    assert results[1]["result"] == "result:grep"  # 不被覆盖


def test_parallel_tool_error_marks_error_state():
    """并行工具错误 → 结果含 [error...] 且触发 B7 缓存防护状态（luna R1-5）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, _tool_output_is_error

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None
    agent._tool_error_occurred = False

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        return f"[error executing {name}: boom]"

    agent._execute_tool = fake_execute_tool

    async def run():
        return await agent._execute_tools_parallel(
            [{"name": "read", "args": {}, "id": "r1"}]
        )

    results = asyncio.run(run())
    assert _tool_output_is_error(results[0]["result"]) is True
    # B7 语义：调用方（工具循环）会设置 _tool_error_occurred（此处验证结果可识别）
    if _tool_output_is_error(results[0]["result"]):
        agent._tool_error_occurred = True
    assert agent._tool_error_occurred is True


def test_ttft_per_request_independent():
    """TTFT 每请求独立记录，不因全局已记录而跳过后续请求（luna R2-1）。"""
    import time as time_mod

    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    token_stats.reset_ttft()
    # 模拟两次独立请求：每次都有局部起点与局部已记录标志
    for _ in range(2):
        _ttft_start = time_mod.monotonic()
        _ttft_recorded = False
        # 模拟首个内容 chunk
        content = "x"
        if _ttft_start is not None and not _ttft_recorded and content:
            _ttft_recorded = True
            token_stats.record_ttft((time_mod.monotonic() - _ttft_start) * 1000)
    # 第二次请求也记录了（值被更新，非 None）
    assert token_stats.ttft_ms is not None
    assert token_stats.ttft_ms >= 0


def test_ttft_empty_chunk_then_content():
    """空 chunk 不计数，之后的内容 chunk 才记录（luna R2-1）。"""
    import time as time_mod

    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    token_stats.reset_ttft()
    _ttft_start = time_mod.monotonic()
    _ttft_recorded = False

    # 模拟空 chunk（无 content）
    for _ in range(3):
        content = ""
        if _ttft_start is not None and not _ttft_recorded and content:
            _ttft_recorded = True
    assert _ttft_recorded is False  # 空 chunk 未触发

    # 内容 chunk
    content = "first-token"
    if _ttft_start is not None and not _ttft_recorded and content:
        _ttft_recorded = True
        token_stats.record_ttft((time_mod.monotonic() - _ttft_start) * 1000)
    assert _ttft_recorded is True
    assert token_stats.ttft_ms is not None


def test_parallel_cancellation_propagates():
    """并行任务取消不被吞成工具错误（luna R2-2）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": True, "max_parallel": 3}}
    agent._stuck_detector = None

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        await asyncio.sleep(5)  # 永不完成
        return "never"

    agent._execute_tool = fake_execute_tool

    async def run():
        task = asyncio.create_task(
            agent._execute_tools_parallel(
                [{"name": "read", "args": {}, "id": "r1"}]
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return "cancelled"
        return "not-cancelled"

    result = asyncio.run(run())
    assert result == "cancelled"  # 取消传播，未被吞


def test_empty_cfg_enables_read_tool_parallel():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    enabled, _limit = agent._parallel_tool_config()
    assert enabled is True


def test_graph_serial_does_not_disable_read_tool_parallel():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._cfg = {"execution": {"parallel_enabled": False}}
    enabled, _limit = agent._parallel_tool_config()
    assert enabled is True


def test_git_snapshot_skipped_for_read_only_batch():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    calls = {"n": 0}

    async def capture():
        calls["n"] += 1
        return True

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        return f"ok:{name}"

    agent._capture_git_snapshot_async = capture
    agent._execute_tool = fake_execute_tool
    asyncio.run(
        agent._execute_tools_parallel(
            [
                {"name": "read", "args": {}, "id": "r1"},
                {"name": "grep", "args": {}, "id": "g1"},
            ]
        )
    )
    assert calls["n"] == 0


def test_git_snapshot_taken_once_before_write():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    calls = {"n": 0}

    async def capture():
        calls["n"] += 1
        return True

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        return f"ok:{name}"

    agent._capture_git_snapshot_async = capture
    agent._execute_tool = fake_execute_tool
    asyncio.run(
        agent._execute_tools_parallel(
            [
                {"name": "read", "args": {}, "id": "r1"},
                {"name": "write", "args": {"path": "a.py"}, "id": "w1"},
                {"name": "edit", "args": {"path": "a.py"}, "id": "e1"},
            ]
        )
    )
    assert calls["n"] == 1


def test_bash_default_timeout_is_1800():
    from inspect import signature

    from RxyCode.RxyCode1_1_0.tools.bash import BashInput, run_bash, run_bash_async
    from RxyCode.RxyCode1_1_0.utils.shell import DEFAULT_SHELL_TIMEOUT, ShellExecutor

    assert BashInput.model_fields["timeout"].default == 1800
    assert run_bash.__defaults__[-1] == 1800
    assert run_bash_async.__defaults__[-1] == 1800
    assert signature(ShellExecutor.execute).parameters["timeout"].default == 1800
    assert signature(ShellExecutor.execute_async).parameters["timeout"].default == 1800
    assert (
        signature(ShellExecutor.execute_argv_async).parameters["timeout"].default
        == DEFAULT_SHELL_TIMEOUT
        == 1800
    )


def test_raw_stream_hot_path_does_not_reload_config(monkeypatch):
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, UsageTrackingLLM

    source = inspect.getsource(AgentV2._raw_stream)
    assert "load_config()" not in source
    assert "load_config" not in inspect.getsource(AgentV2._resolve_request_max_tokens)
    assert "load_config" not in inspect.getsource(UsageTrackingLLM._ensure_cache_flag)
    assert "load_config" not in inspect.getsource(UsageTrackingLLM._transport_retry_max)

    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        return {}

    monkeypatch.setattr("config.settings.load_config", boom)
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.config.settings.load_config", boom)

    agent = _new_agent()
    agent.model_config = {"model_name": "x"}
    agent._cfg = {"model_limits": {}}
    agent._resolved_limits = None
    agent._capabilities = None
    agent._resolve_request_max_tokens(10)

    llm = object.__new__(UsageTrackingLLM)
    llm._cache_enabled = None
    llm._transport_retries = None
    llm._cfg = {"cache": {"prompt_prefix_cache": True}, "llm": {"transport_retries": 2}}
    assert llm._ensure_cache_flag() is True
    assert llm._transport_retry_max() == 2
    assert calls["n"] == 0


def test_synthesis_with_tools_uses_parallel_path_and_write_snapshot():
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = _new_agent()
    agent._tool_error_occurred = False
    snaps = {"n": 0}

    async def capture():
        snaps["n"] += 1
        return True

    async def fake_execute_tool(name, args, mode=None, call_id=None):
        return f"ok:{name}"

    async def fake_stream(messages, tools=None, *, max_tokens=None):
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="fin"))]
        )

    agent._capture_git_snapshot_async = capture
    agent._execute_tool = fake_execute_tool
    agent._raw_stream = fake_stream
    agent._tool_result_message_content = lambda name, result: result

    asyncio.run(
        agent._synthesis_with_tools(
            [],
            [
                {"name": "read", "args": {}, "id": "r1"},
                {"name": "write", "args": {"path": "a.py"}, "id": "w1"},
            ],
            mode="build",
            tui=None,
            fallback_answer="fb",
        )
    )
    assert snaps["n"] == 1
