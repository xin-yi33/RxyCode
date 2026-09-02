"""FXC5 · per-model thinking / echo contracts (PHASE-FIX §5 FXC5).

Covers the decision table rows with payload / serialized-message assertions:
- DeepSeek (mandatory_echo): echo reasoning_content only when tool_calls are
  present; plain-text assistant turns never get a forced reasoning field
- Kimi / MiMo / GLM (mandatory_echo): echo across user turns, empty allowed
- Qwen (no_thinking): reasoning_content is NEVER put back into messages
- GPT / Doubao / Grok (none): no raw CoT echo
- provider extra_body goldens (thinking/reasoning_effort/enable_thinking)
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, _should_echo_reasoning


def _convert(msgs, reasoning_contract=None, provider_id=None):
    return AgentV2._to_openai_messages(
        msgs, reasoning_contract=reasoning_contract, provider_id=provider_id
    )


# ---------------------------------------------------------------------------
# echo decision helper (unit level)
# ---------------------------------------------------------------------------


def test_thinking_blocks_echo_echoes_captured_thinking():
    # MiniMax M3 / Anthropic (thinking_blocks_echo): the captured thinking
    # is echoed back.  On OpenAI-compatible endpoints it rides
    # reasoning_content; the signature attribute belongs to the native
    # Anthropic classification (not this path).
    assert _should_echo_reasoning("thinking_blocks_echo", "minimax", True, "thinking") is True
    assert _should_echo_reasoning("thinking_blocks_echo", "minimax", False, "thinking") is True
    assert _should_echo_reasoning("thinking_blocks_echo", "minimax", True, None) is False


def test_qwen_never_echoes_reasoning():
    assert _should_echo_reasoning("no_thinking", "qwen", True, "reasoning") is False
    assert _should_echo_reasoning("no_thinking", "qwen", False, "reasoning") is False


def test_none_contract_never_echoes():
    for provider in ("openai", "doubao", "grok"):
        assert _should_echo_reasoning("none", provider, True, "reasoning") is False


def test_deepseek_echoes_only_with_tool_calls():
    assert _should_echo_reasoning("mandatory_echo", "deepseek", True, "reasoning") is True
    assert _should_echo_reasoning("mandatory_echo", "deepseek", False, "reasoning") is False


def test_kimi_mimo_glm_echo_across_turns_empty_ok():
    for provider in ("kimi", "mimo", "glm"):
        assert _should_echo_reasoning("mandatory_echo", provider, False, "") is True
        assert _should_echo_reasoning("mandatory_echo", provider, True, "") is True


def test_unknown_contract_falls_back_to_old_behaviour():
    # legacy path keeps echoing captured reasoning when present
    assert _should_echo_reasoning(None, "deepseek", False, "reasoning") is True


# ---------------------------------------------------------------------------
# serialized messages (the wire contract)
# ---------------------------------------------------------------------------


def test_qwen_serialized_messages_never_contain_reasoning_content():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="think then answer", reasoning_content="hidden chain"),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs, reasoning_contract="no_thinking", provider_id="qwen")
    assert all("reasoning_content" not in m for m in out)


def test_deepseek_plain_text_assistant_has_no_reasoning_field():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="plain answer", reasoning_content="thinking but no tools"),
        HumanMessage(content="go on"),
    ]
    out = _convert(msgs, reasoning_contract="mandatory_echo", provider_id="deepseek")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert "reasoning_content" not in assistant  # no tool_calls -> no echo


def test_deepseek_tool_call_echoes_reasoning():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(
            content="",
            reasoning_content="decided to search",
            tool_calls=[
                {
                    "name": "websearch",
                    "args": {"q": "x"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs, reasoning_contract="mandatory_echo", provider_id="deepseek")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant["reasoning_content"] == "decided to search"


def test_kimi_empty_reasoning_still_echoed():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="ok", reasoning_content=""),
        HumanMessage(content="continue"),
    ]
    out = _convert(msgs, reasoning_contract="mandatory_echo", provider_id="kimi")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == ""


def test_gpt_serialized_messages_no_reasoning_echo():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="answer", reasoning_content="chain"),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs, reasoning_contract="none", provider_id="openai")
    assert all("reasoning_content" not in m for m in out)


# ---------------------------------------------------------------------------
# provider extra_body golden contracts
# ---------------------------------------------------------------------------


def _provider_llm_kwargs(provider_cls, model_name, model_config=None):
    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES

    caps = provider_cls().capabilities({"model_name": model_name})
    cfg = {
        "model_name": model_name,
        "effort": "balanced",
        "api_key": "sk-test",
        "resolved_max_tokens": 2048,
    }
    if model_config:
        cfg.update(model_config)
    return provider_cls().llm_kwargs(cfg, caps)


def test_mimo_sends_thinking_object_and_no_effort():
    from RxyCode.RxyCode1_1_0.core.providers.mimo import MIMOProvider

    kwargs = _provider_llm_kwargs(MIMOProvider, "mimo-v2.5-pro")
    body = kwargs.get("extra_body") or {}
    assert body.get("thinking") == {"type": "enabled"}
    assert "reasoning_effort" not in kwargs


def test_minimax_m3_sends_adaptive_thinking():
    from RxyCode.RxyCode1_1_0.core.providers.minimax import MiniMaxProvider

    kwargs = _provider_llm_kwargs(MiniMaxProvider, "minimax-m3")
    body = kwargs.get("extra_body") or {}
    assert body.get("thinking") == {"type": "adaptive"}


def test_qwen_sends_enable_thinking_not_type_disabled():
    from RxyCode.RxyCode1_1_0.core.providers.qwen import QwenProvider

    kwargs = _provider_llm_kwargs(QwenProvider, "qwen3.7-max")
    body = kwargs.get("extra_body") or {}
    assert body.get("enable_thinking") is True
    assert "thinking" not in body  # never {type: disabled}


def test_kimi_k3_sends_reasoning_effort_not_thinking_object():
    from RxyCode.RxyCode1_1_0.core.providers.kimi import KimiProvider

    kwargs = _provider_llm_kwargs(KimiProvider, "kimi-k3", {"effort": "max"})
    assert kwargs.get("reasoning_effort") == "max"
    body = kwargs.get("extra_body") or {}
    # k3 must not carry a thinking object ({type: enabled} 400s on k3)
    assert body.get("thinking") is None


# ---------------------------------------------------------------------------
# FXC5 audit R1: decision-table rows + contract-gated empty placeholder
# ---------------------------------------------------------------------------


def test_qwen_tool_call_turn_has_no_reasoning_content():
    """no_thinking: even a tool-bearing Qwen turn must not carry
    reasoning_content (including the empty placeholder)."""
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(
            content="",
            reasoning_content="thinking but qwen",
            tool_calls=[{"name": "bash", "args": {}, "id": "c1", "type": "tool_call"}],
        ),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs, reasoning_contract="no_thinking", provider_id="qwen")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert "reasoning_content" not in assistant


def test_gpt_tool_call_turn_has_no_reasoning_content():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(
            content="",
            reasoning_content="chain",
            tool_calls=[{"name": "bash", "args": {}, "id": "c1", "type": "tool_call"}],
        ),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs, reasoning_contract="none", provider_id="openai")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert "reasoning_content" not in assistant


def test_legacy_unknown_contract_tool_call_keeps_empty_placeholder():
    """Unknown/legacy callers keep the old behaviour: empty reasoning is
    still emitted on tool-bearing turns (provider chain validity)."""
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {}, "id": "c1", "type": "tool_call"}],
        ),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs)  # no contract -> legacy
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == ""


def test_kimi_k27_thinking_object_no_effort():
    from RxyCode.RxyCode1_1_0.core.providers.kimi import KimiProvider

    kwargs = _provider_llm_kwargs(KimiProvider, "kimi-k2.7-code", {"effort": "max"})
    body = kwargs.get("extra_body") or {}
    assert body.get("thinking") == {"type": "enabled"}  # k2.x keeps thinking
    assert "reasoning_effort" not in kwargs  # k2.x sends no effort


def test_mimo_echoes_reasoning_across_turns():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="ok", reasoning_content=""),
        HumanMessage(content="continue"),
    ]
    out = _convert(msgs, reasoning_contract="mandatory_echo", provider_id="mimo")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == ""


def test_glm_echoes_reasoning_across_turns():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="ok", reasoning_content="thinking"),
        HumanMessage(content="continue"),
    ]
    out = _convert(msgs, reasoning_contract="mandatory_echo", provider_id="glm")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == "thinking"


# ---------------------------------------------------------------------------
# FXC5 audit R2: GLM / DeepSeek payload / MiniMax / MiMo / Doubao rows
# ---------------------------------------------------------------------------


def test_glm_sends_clear_thinking_false_and_no_thinking_object():
    from RxyCode.RxyCode1_1_0.core.providers.glm import GLMProvider

    kwargs = _provider_llm_kwargs(GLMProvider, "glm-5.2")
    body = kwargs.get("extra_body") or {}
    assert body.get("clear_thinking") is False
    assert "thinking" not in body  # GLM's live contract uses clear_thinking only


def test_glm_opencode_go_does_not_send_vendor_extras():
    from RxyCode.RxyCode1_1_0.core.providers.glm import GLMProvider

    kwargs = _provider_llm_kwargs(
        GLMProvider, "glm-5.2", {"base_url": "https://opencode.ai/zen/go/v1"}
    )
    assert "reasoning_effort" not in kwargs
    body = kwargs.get("extra_body") or {}
    assert "clear_thinking" not in body
    assert "thinking" not in body


def test_glm_51_sends_no_reasoning_effort():
    from RxyCode.RxyCode1_1_0.core.providers.glm import GLMProvider

    kwargs = _provider_llm_kwargs(GLMProvider, "glm-5.1")
    assert "reasoning_effort" not in kwargs


def test_deepseek_thinking_payload_kept_no_cache_control():
    from RxyCode.RxyCode1_1_0.core.providers.deepseek import DeepSeekProvider

    kwargs = _provider_llm_kwargs(DeepSeekProvider, "deepseek-v4-flash")
    assert json.dumps(kwargs).count("cache_control") == 0
    # DeepSeek keeps its current thinking (no {type} object needed in kwargs)


def test_minimax_m3_no_cache_control_and_adaptive():
    from RxyCode.RxyCode1_1_0.core.providers.minimax import MiniMaxProvider

    kwargs = _provider_llm_kwargs(MiniMaxProvider, "minimax-m3")
    assert "cache_control" not in json.dumps(kwargs)
    body = kwargs.get("extra_body") or {}
    assert body.get("thinking") == {"type": "adaptive"}


def test_minimax_m3_payload_no_signature_concept_on_openai_path():
    """MiniMax M3 (OpenAI-compatible endpoint) has no Anthropic thinking
    block / signature on the wire here; the signature attribute belongs to the
    native Anthropic classification used by the Go gateway. Assert the OpenAI
    path carries adaptive thinking and no cache_control / signature."""
    from RxyCode.RxyCode1_1_0.core.providers.minimax import MiniMaxProvider

    kwargs = _provider_llm_kwargs(MiniMaxProvider, "minimax-m3")
    extra = kwargs.get("extra_body") or {}
    assert extra.get("thinking") == {"type": "adaptive"}
    assert "cache_control" not in json.dumps(kwargs)
    assert "signature" not in json.dumps(kwargs)
    payload = _capture_raw_stream("minimax-m3", "minimax", _two_tools())
    assert "cache_control" not in json.dumps(payload)
    assert "signature" not in json.dumps(payload)


def test_minimax_m3_serialized_assistant_echoes_thinking():
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="answer", reasoning_content="m3 thinking step"),
        HumanMessage(content="continue"),
    ]
    out = _convert(msgs, reasoning_contract="thinking_blocks_echo", provider_id="minimax")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == "m3 thinking step"


def test_mimo_no_effort_no_cache_control():
    from RxyCode.RxyCode1_1_0.core.providers.mimo import MIMOProvider

    kwargs = _provider_llm_kwargs(MIMOProvider, "mimo-v2.5-pro")
    assert "reasoning_effort" not in kwargs
    assert "cache_control" not in json.dumps(kwargs)
    body = kwargs.get("extra_body") or {}
    assert body.get("thinking") == {"type": "enabled"}


def test_doubao_no_reasoning_echo_and_no_cache_control():
    from RxyCode.RxyCode1_1_0.core.providers.doubao import DoubaoProvider

    kwargs = _provider_llm_kwargs(DoubaoProvider, "doubao-seed-2.1-turbo")
    assert "cache_control" not in json.dumps(kwargs)
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="ok", reasoning_content="chain"),
        HumanMessage(content="ok"),
    ]
    out = _convert(msgs, reasoning_contract="none", provider_id="doubao")
    assert all("reasoning_content" not in m for m in out)


# ---------------------------------------------------------------------------
# FXC5 audit R2: integrated _raw_stream path (catalog -> contract -> echo)
# ---------------------------------------------------------------------------


def test_integrated_qwen_raw_stream_never_echoes_reasoning():
    """The real _raw_stream path reads reasoning_contract from the catalog,
    so a Qwen turn with captured reasoning must not carry reasoning_content
    on the wire."""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider="qwen",
        cache_breakpoints=(),
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc5"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": "qwen3.7-max", "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    asst = SimpleNamespace(
        type="ai",
        content="answer",
        reasoning_content="captured chain",
        tool_calls=None,
        additional_kwargs={},
    )
    try:
        asyncio.run(agent._raw_stream([sys_msg, asst], tools=None).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise
    messages = captured["payload"].get("messages") or []
    assert any(m.get("role") == "assistant" for m in messages)
    for m in messages:
        assert "reasoning_content" not in m  # Qwen: never echoed, even integrated


# ---------------------------------------------------------------------------
# FXC5 audit R4: real payload assertions for DeepSeek / GPT rows
# ---------------------------------------------------------------------------


def test_deepseek_raw_payload_thinking_no_cache_control():
    """DeepSeek keeps its current thinking params; the wire payload must not
    contain cache_control (implicit family)."""
    from RxyCode.RxyCode1_1_0.core.providers.deepseek import DeepSeekProvider

    kwargs = _provider_llm_kwargs(DeepSeekProvider, "deepseek-v4-flash")
    extra = kwargs.get("extra_body") or {}
    assert extra.get("thinking") == {"type": "enabled"}  # current thinking kept
    assert "cache_control" not in json.dumps(kwargs)
    payload = _capture_raw_stream("deepseek-v4-flash", "deepseek", _two_tools())
    assert "cache_control" not in json.dumps(payload)


def test_gpt_raw_payload_has_no_anthropic_params():
    """GPT (none contract) must not carry Anthropic thinking or cache fields."""
    payload = _capture_raw_stream("gpt-5.6-luna", "openai", _two_tools())
    assert "cache_control" not in json.dumps(payload)
    assert "thinking" not in json.dumps(payload)
    assert "reasoning_content" not in json.dumps(payload.get("messages", []))


def _capture_raw_stream(model_name, provider, tools):
    """Capture the real _raw_stream request payload (FXC2-style, no network)."""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider=provider,
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc5"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": model_name, "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
    try:
        asyncio.run(agent._raw_stream([sys_msg, user_msg], tools=tools).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise
    return captured["payload"]


def _two_tools():
    from langchain_core.tools import StructuredTool

    return [
        StructuredTool.from_function(lambda: "ok", name="read", description="read"),
        StructuredTool.from_function(lambda: "ok", name="bash", description="bash"),
    ]


# ---------------------------------------------------------------------------
# FXC5 audit R9: unknown-model no-inject, GLM/MiMo wire payload rows
# ---------------------------------------------------------------------------


def test_unknown_model_llm_kwargs_inject_nothing():
    """FX-CB11 / FXC6: a model without a catalog record must not inherit
    vendor thinking/reasoning params through base llm_kwargs."""
    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.providers.openai import OpenAIProvider

    kwargs = OpenAIProvider().llm_kwargs(
        {"model_name": "mystery-model", "resolved_max_tokens": 2048,
         "api_key": "sk-test", "effort": "balanced"},
        DEFAULT_CAPABILITIES,
    )
    assert kwargs.get("extra_body") is None
    assert "reasoning_effort" not in kwargs
    assert "thinking" not in json.dumps(kwargs)


def test_glm_wire_payload_serialized_messages():
    """GLM (mandatory_echo) echoes reasoning across turns at the message level."""
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="glm answer", reasoning_content="glm thinking"),
        HumanMessage(content="continue"),
    ]
    out = _convert(msgs, reasoning_contract="mandatory_echo", provider_id="glm")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == "glm thinking"


def test_minimax_m3_thinking_echo_boundary():
    """MiniMax M3 (official OpenAI-compatible endpoint, api.minimaxi.com
    /v1/chat/completions, per platform.minimaxi.com/docs/api-reference/
    text-chat-openai): thinking adaptive, response carries reasoning_content /
    reasoning_details (format MiniMax-response-v1). The Anthropic `signature`
    attribute does not exist on the official MiniMax OpenAI API — it belongs
    to Anthropic Messages protocol only, so no signature is invented here."""
    msgs = [
        SystemMessage(content="SYS"),
        AIMessage(content="m3 answer", reasoning_content="m3 thinking step"),
        HumanMessage(content="continue"),
    ]
    out = _convert(msgs, reasoning_contract="thinking_blocks_echo", provider_id="minimax")
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant.get("reasoning_content") == "m3 thinking step"
    assert "signature" not in json.dumps(out)  # no invented signature on this path


# ---------------------------------------------------------------------------
# FXC5 audit R10: integrated echo rows (real _raw_stream + catalog)
# ---------------------------------------------------------------------------


def _integrated_reasoning(model_name, provider, reasoning_text):
    """Drive the real _raw_stream with an assistant carrying captured
    reasoning; return the serialized assistant message dict."""
    import asyncio
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from dataclasses import replace

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider=provider,
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc5"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": model_name, "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    asst = SimpleNamespace(
        type="ai", content="answer", reasoning_content=reasoning_text,
        tool_calls=None, additional_kwargs={},
    )
    try:
        asyncio.run(agent._raw_stream([sys_msg, asst], tools=None).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise
    for m in captured["payload"].get("messages", []):
        if m.get("role") == "assistant":
            return m
    raise AssertionError("no assistant message")


def test_integrated_deepseek_plain_turn_no_reasoning():
    """DeepSeek (mandatory_echo): a plain-text assistant turn with reasoning
    must NOT echo it on the wire (echo only on tool-bearing turns)."""
    asst = _integrated_reasoning("deepseek-v4-flash", "deepseek", "captured thinking")
    assert "reasoning_content" not in asst


def test_integrated_glm_echoes_reasoning_across_turns():
    asst = _integrated_reasoning("glm-5.2", "glm", "glm captured")
    assert asst.get("reasoning_content") == "glm captured"


def test_integrated_mimo_echoes_reasoning_across_turns():
    asst = _integrated_reasoning("mimo-v2.5-pro", "mimo", "mimo captured")
    assert asst.get("reasoning_content") == "mimo captured"


def test_integrated_kimi_echoes_reasoning_across_turns():
    asst = _integrated_reasoning("kimi-k3", "kimi", "kimi captured")
    assert asst.get("reasoning_content") == "kimi captured"


def test_integrated_unknown_model_keeps_legacy_echo():
    """Unknown model: legacy fallback keeps echoing captured reasoning."""
    asst = _integrated_reasoning("totally-mystery", "unknown", "legacy chain")
    assert asst.get("reasoning_content") == "legacy chain"
