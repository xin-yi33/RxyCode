"""FXC2: cache_control 只信 catalog 三族，禁止每 tool 打点，保留 human 断点。"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from RxyCode.RxyCode1_1_0.core.catalog import (
    get_contract,
    injects_cache_control,
    injects_prompt_cache_key,
    reset_contract_cache,
)


def test_unknown_never_injects():
    assert injects_cache_control(None) is False
    assert injects_prompt_cache_key(None) is False


def test_explicit_aliases_are_rejected():
    assert injects_cache_control({"cache_mode": "explicit", "breakpoints_max": 4}) is False
    assert injects_cache_control(
        {"cache_mode": "breakpoints", "breakpoints_max": 4}
    ) is False
    assert (
        injects_cache_control(
            {"cache_mode": "explicit_breakpoints", "breakpoints_max": 4}
        )
        is True
    )
    assert (
        injects_cache_control(
            {"cache_mode": "explicit_breakpoints", "breakpoints_max": 0}
        )
        is False
    )


def test_deepseek_never_injects_control():
    reset_contract_cache()
    c = get_contract("deepseek", "deepseek-v4-flash")
    assert injects_cache_control(c) is False


def test_minimax_m3_never_injects_control():
    reset_contract_cache()
    assert injects_cache_control(get_contract("minimax", "minimax-m3")) is False


def test_to_openai_messages_keeps_human_cache_control():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    msgs = AgentV2._to_openai_messages(
        [
            HumanMessage(
                content="hi",
                additional_kwargs={"cache_control": {"type": "ephemeral"}},
            ),
        ]
    )
    assert msgs[0]["role"] == "user"
    assert msgs[0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(msgs[0]["content"], list)
    assert msgs[0]["content"][0]["type"] == "text"
    assert msgs[0]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_implicit_family_content_stays_string():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    msgs = AgentV2._to_openai_messages(
        [SystemMessage(content="sys"), HumanMessage(content="hi")]
    )
    assert msgs[0]["content"] == "sys"
    assert msgs[1]["content"] == "hi"
    assert "cache_control" not in json.dumps(msgs)


def test_does_not_stamp_thinking_blocks():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    msgs = AgentV2._to_openai_messages(
        [
            HumanMessage(
                content=[
                    {"type": "thinking", "thinking": "secret"},
                    {"type": "text", "text": "hi"},
                ],
                additional_kwargs={"cache_control": {"type": "ephemeral"}},
            )
        ]
    )
    dumped = json.dumps(msgs)
    assert '"type": "thinking"' in dumped
    thinking = msgs[0]["content"][0]
    assert thinking["type"] == "thinking"
    assert "cache_control" not in thinking


def _capture_raw_stream(model_name: str, provider: str, tools):
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
        cache_breakpoints=("tools", "system", "tail"),
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc2"
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
    return [
        StructuredTool.from_function(lambda: "ok", name="read", description="read"),
        StructuredTool.from_function(lambda: "ok", name="bash", description="bash"),
    ]


def test_raw_stream_marks_only_last_tool():
    """Construct anthropic-family payload tools and assert only [-1] has cache_control.
    用最小 fake contract：cache_mode=`explicit_breakpoints`、breakpoints_max>0。不要打真实网。不要写 cache_mode=`explicit`。"""
    payload = _capture_raw_stream("claude-sonnet-4.5", "anthropic", _two_tools())
    tools = payload.get("tools") or []
    assert len(tools) == 2
    assert "cache_control" not in tools[0]
    assert tools[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert json.dumps(payload["tools"]).count("cache_control") == 1


def test_deepseek_raw_payload_has_no_cache_control():
    payload = _capture_raw_stream("deepseek-v4-flash", "deepseek", _two_tools())
    assert "cache_control" not in json.dumps(payload)


def test_minimax_m3_raw_payload_has_no_cache_control():
    payload = _capture_raw_stream("minimax-m3", "minimax", _two_tools())
    assert "cache_control" not in json.dumps(payload)


def test_unknown_model_raw_payload_has_no_cache_control():
    payload = _capture_raw_stream("totally-unknown-model", "unknown", _two_tools())
    assert "cache_control" not in json.dumps(payload)


def test_dispatch_uses_injects_cache_control_not_anthropic_heuristic():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, UsageTrackingLLM

    apply_src = inspect.getsource(UsageTrackingLLM._apply_cache_control)
    raw_src = inspect.getsource(AgentV2._raw_stream)
    assert "injects_cache_control" in apply_src
    assert "injects_cache_control" in raw_src
    assert 'provider_name != "anthropic"' not in apply_src
    assert 'actual_provider == "anthropic"' not in raw_src
    assert "for tool_def in payload[\"tools\"]" not in raw_src
    assert 'if "claude" in' not in apply_src
    assert 'if "claude" in' not in raw_src


def test_no_cache_family_module():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "core" / "cache_family.py").exists()


def _apply_wrapper(provider: str, model_name: str, breakpoints=()):
    from dataclasses import replace
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider=provider,
        cache_breakpoints=breakpoints,
        supports_prompt_cache=True,
    )
    wrapper = object.__new__(UsageTrackingLLM)
    wrapper._cache_enabled = True
    wrapper._provider = SimpleNamespace(
        name=provider,
        supports_prompt_cache=lambda _c: True,
    )
    wrapper._capabilities = caps
    wrapper._cfg = {}
    wrapper.model_config = {"model_name": model_name}
    return wrapper


def test_explicit_apply_then_serialize_promotes_blocks():
    """Production path: _apply_cache_control then _to_openai_messages → block arrays."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    wrapper = _apply_wrapper(
        "anthropic",
        "claude-sonnet-4.5",
        breakpoints=("system", "tail"),
    )
    out = wrapper._apply_cache_control(
        [SystemMessage(content="sys"), HumanMessage(content="hi")]
    )
    serialized = AgentV2._to_openai_messages(out)
    assert isinstance(serialized[0]["content"], list)
    assert serialized[0]["content"][0]["type"] == "text"
    assert serialized[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert serialized[0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(serialized[1]["content"], list)
    assert serialized[1]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_implicit_apply_then_serialize_keeps_string():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    wrapper = _apply_wrapper("deepseek", "deepseek-v4-flash")
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi")]
    out = wrapper._apply_cache_control(msgs)
    serialized = AgentV2._to_openai_messages(out)
    assert serialized[0]["content"] == "sys"
    assert serialized[1]["content"] == "hi"
    assert "cache_control" not in json.dumps(serialized)

