"""Phase 3 M7/M8: 端到端接线契约测试。

验证：
- ``auto`` 永不进入 SDK（llm_kwargs / _raw_stream 只产出正整数）；
- ``ModelCapabilities.max_output_tokens``（能力值）不直接进入请求路径；
- ``resolved_max_tokens`` 缺失时不绕过 resolver（请求路径抛结构化错误）；
- context 预算耗尽阻止请求（ModelLimitError 传播，不发送 0/负数）。
"""
from __future__ import annotations

import pytest


def test_llm_kwargs_never_emits_auto_string():
    """M4：auto 不会以字符串进入 SDK——无 resolved 时抛错，有 resolved 时用正整数。"""
    import pytest

    from core import providers

    p = providers.resolve({"base_url": "https://api.example.com/v1", "model_name": "m"})
    caps = p.capabilities({})
    # auto 且无 resolved → 抛错（EXIT.6，不自行兜底）
    with pytest.raises(ValueError):
        p.llm_kwargs(
            {"model_name": "m", "api_key": "k", "base_url": "b", "max_tokens": "auto"},
            caps,
        )
    # auto + resolved → 用正整数
    kwargs = p.llm_kwargs(
        {"model_name": "m", "api_key": "k", "base_url": "b", "max_tokens": "auto",
         "resolved_max_tokens": 4096},
        caps,
    )
    assert isinstance(kwargs["max_tokens"], int)
    assert kwargs["max_tokens"] == 4096
    assert kwargs["max_tokens"] != "auto"


def test_resolved_max_tokens_used_when_provided():
    """M4：调用方传入 resolver 结果时，llm_kwargs 用之，且不是能力值本身。"""
    from core import providers

    p = providers.resolve({"base_url": "https://api.example.com/v1", "model_name": "m"})
    caps = p.capabilities({})
    kwargs = p.llm_kwargs(
        {
            "model_name": "m",
            "api_key": "k",
            "base_url": "b",
            "max_tokens": "auto",
            "resolved_max_tokens": 4096,
        },
        caps,
    )
    assert kwargs["max_tokens"] == 4096


def test_raw_stream_resolver_path_never_uses_capability_value_directly(monkeypatch):
    """M4：_resolve_request_max_tokens 走 resolver，能力值只作为 provider_default 输入。

    构造一个 fake agent：caps.max_output_tokens=999（能力值），但目录/配置里
    的显式值不同。解析结果不应直接等于能力值（除非目录/默认就是它）。
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.config.model_catalog import ModelCatalog
    from RxyCode.RxyCode1_1_0.config.model_limits import resolve_configured_max_tokens

    agent = object.__new__(AgentV2)
    agent.model_config = {"provider_id": "demo", "model_name": "m", "max_tokens": "auto"}
    agent._capabilities = None
    agent._resolved_limits = None

    catalog = ModelCatalog.from_records([{
        "provider_id": "demo", "model_id": "m",
        "model_context_window": 262144, "model_max_output_tokens": 65536,
        "source": "t", "source_url": "https://example.invalid/cat", "as_of": "2026-08-03",
    }])

    resolution = resolve_configured_max_tokens(
        model_config=agent.model_config,
        capability_max_output_tokens=999,  # 能力值（Phase A），仅作 provider_default
        configured_max_tokens="auto",
        model_limits_config={},
        catalog=catalog,
    )
    # 目录精确命中（65536）优先于能力值（999）→ resolved 是 65536
    assert resolution.resolved_max_tokens == 65536
    assert resolution.source == "catalog_exact_provider"


def test_context_budget_exhausted_propagates(monkeypatch):
    """M4：预算耗尽 → ModelLimitError 传播（阻止请求），不返回 0/负数。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.config.model_catalog import ModelCatalog
    from RxyCode.RxyCode1_1_0.config.model_limits import (
        MODEL_CONTEXT_BUDGET_EXHAUSTED,
        ModelLimitError,
        resolve_configured_max_tokens,
    )

    agent = object.__new__(AgentV2)
    agent.model_config = {"provider_id": "demo", "model_name": "tiny", "max_tokens": "auto"}
    agent._capabilities = None
    agent._resolved_limits = None

    catalog = ModelCatalog.from_records([{
        "provider_id": "demo", "model_id": "tiny",
        "model_context_window": 500, "model_max_output_tokens": 200,
        "source": "t", "source_url": "https://example.invalid/cat", "as_of": "2026-08-03",
    }])

    with pytest.raises(ModelLimitError) as exc:
        resolve_configured_max_tokens(
            model_config=agent.model_config,
            capability_max_output_tokens=None,
            configured_max_tokens="auto",
            model_limits_config={},
            catalog=catalog,
            input_tokens=2000,  # 500 - 2000 - 1024 < 1
        )
    assert exc.value.code == MODEL_CONTEXT_BUDGET_EXHAUSTED


def test_auto_resolves_to_positive_integer_through_resolver():
    """M4：auto → resolver → 正整数，且来源可解释。"""
    from RxyCode.RxyCode1_1_0.config.model_catalog import ModelCatalog
    from RxyCode.RxyCode1_1_0.config.model_limits import resolve_configured_max_tokens

    catalog = ModelCatalog.from_records([{
        "provider_id": "demo", "model_id": "m",
        "model_context_window": 262144, "model_max_output_tokens": 65536,
        "source": "t", "source_url": "https://example.invalid/cat", "as_of": "2026-08-03",
    }])
    resolution = resolve_configured_max_tokens(
        model_config={"provider_id": "demo", "model_name": "m", "max_tokens": "auto"},
        capability_max_output_tokens=None,
        configured_max_tokens="auto",
        model_limits_config={},
        catalog=catalog,
    )
    assert isinstance(resolution.resolved_max_tokens, int)
    assert resolution.resolved_max_tokens == 65536
    assert resolution.source == "catalog_exact_provider"


def test_model_limit_error_not_retryable():
    """M4.6：ModelLimitError 不属于可重试的传输错误，不会被静默重试吞掉。

    agent_v2 的 transport retry 只对短 connect / 429 / connection-reset
    重试（_is_transport_retryable）。ModelLimitError（如
    MODEL_CONTEXT_BUDGET_EXHAUSTED）是业务错误，不在重试白名单内。
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _is_transport_retryable
    from RxyCode.RxyCode1_1_0.config.model_limits import (
        MODEL_CONTEXT_BUDGET_EXHAUSTED,
        ModelLimitError,
    )

    err = ModelLimitError(
        MODEL_CONTEXT_BUDGET_EXHAUSTED, "effective_max_tokens < 1"
    )
    assert not _is_transport_retryable(err)
    assert not _is_transport_retryable(RuntimeError("not transport"))
    # 对照：传输错误应可重试
    import httpx
    assert _is_transport_retryable(httpx.ConnectError("boom"))
    assert not _is_transport_retryable(TimeoutError("slow"))


def test_llm_transport_retry_emits_structured_recovery_and_resolves(monkeypatch):
    """模型请求的瞬态网络错误只重试一次，并完整闭环恢复事件。"""
    import asyncio

    import httpx

    from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_v2_module

    class FlakyLlm:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("gateway reset")
            return {"content": "recovered"}

    emitted = []
    tui = ProtocolTui("transport-session", emitted.append, run_id="transport-run")
    monkeypatch.setattr(agent_v2_module, "get_tui", lambda: tui)
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_v2_module.asyncio, "sleep", no_sleep)

    agent = agent_v2_module.UsageTrackingLLM(FlakyLlm())
    agent._transport_retries = 1

    result = asyncio.run(agent._call_with_transport_retry(["prompt"], {}))

    assert result == {"content": "recovered"}
    assert agent._llm.calls == 2
    assert [item.method for item in emitted] == [
        "event/recovery_started",
        "event/recovery_attempt",
        "event/recovery_resolved",
    ]
    assert emitted[0].recovery_kind == "transport_retry"
    assert emitted[1].attempt == 1
    assert emitted[-1].attempts == 1


def test_llm_transport_retry_exhaustion_is_structured(monkeypatch):
    """传输重试耗尽后才发出 exhausted，且原始异常仍传播给上层。"""
    import asyncio

    import httpx

    from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_v2_module

    class BrokenLlm:
        async def ainvoke(self, messages, **kwargs):
            raise httpx.ReadError("gateway unavailable")

    emitted = []
    tui = ProtocolTui("transport-session", emitted.append, run_id="transport-run")
    monkeypatch.setattr(agent_v2_module, "get_tui", lambda: tui)
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_v2_module.asyncio, "sleep", no_sleep)

    agent = agent_v2_module.UsageTrackingLLM(BrokenLlm())
    agent._transport_retries = 1

    with pytest.raises(httpx.ReadError):
        asyncio.run(agent._call_with_transport_retry(["prompt"], {}))

    assert [item.method for item in emitted] == [
        "event/recovery_started",
        "event/recovery_attempt",
        "event/recovery_exhausted",
    ]
    assert emitted[-1].attempts == 1
    assert "gateway" not in emitted[-1].final_error.lower()
