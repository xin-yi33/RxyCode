"""FXC6 · unknown-model five-point fallback (PHASE-FIX §5 FXC6 / §15.3).

Unknown models (``get_contract`` -> None) must behave explicitly like:
  1. Prompt -> default variant
  2. Protocol -> openai-compatible
  3. NEVER inject cache_control
  4. still sort tools and send session affinity headers (FXC4)
  5. prompt_cache_key is NOT sent by default

The injection layer documents these through ``unknown_fallback_contract()``
and the wire payload for an unknown model carries no cache_control / no
prompt_cache_key.
"""

from __future__ import annotations

import json

from RxyCode.RxyCode1_1_0.core.catalog import (
    get_contract,
    injects_cache_control,
    injects_prompt_cache_key,
    reset_contract_cache,
    unknown_fallback_contract,
)


def test_unknown_contract_is_none():
    reset_contract_cache()
    assert get_contract("no-such", "mystery") is None


def test_unknown_fallback_contract_is_documented_and_explicit():
    """The fallback contract constant exists and spells out the five points."""
    fb = unknown_fallback_contract()
    assert fb is not None
    assert fb.get("cache_mode") == "auto"  # implicit prefix, never explicit
    assert fb.get("breakpoints_max") == 0
    assert fb.get("prompt_cache_key_required") is False
    assert fb.get("prompt_variant") == "default"
    assert fb.get("protocol") == "openai-compatible"


def test_unknown_fallback_forces_default_variant_in_raw_stream():
    """FXC6 R1: an unknown model with a non-default variant capability is
    forced back to the default variant by the injection layer (fallback rule
    1), instead of raising or guessing."""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            payload.pop("timeout", None)
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider="unknown",
        prompt_variant="guessed-variant",  # would be an id-based guess
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc6"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": "totally-mystery", "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
    try:
        asyncio.run(agent._raw_stream([sys_msg, user_msg], tools=None).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise
    # fallback rule 1: variant forced to default, never guessed by id
    assert getattr(agent._capabilities, "prompt_variant", None) == "default"


def test_unknown_never_injects_control_or_key():
    reset_contract_cache()
    contract = get_contract("no-such", "mystery")
    assert injects_cache_control(contract) is False
    assert injects_prompt_cache_key(contract) is False


def test_unknown_prompt_variant_is_default():
    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES

    assert DEFAULT_CAPABILITIES.prompt_variant == "default"


def test_unknown_model_wire_payload_has_no_cache_control_or_key():
    """The real _raw_stream payload for an unknown model: no cache_control,
    no prompt_cache_key; tools still sorted; session header still present."""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            payload.pop("timeout", None)
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider="unknown",
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc6"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": "totally-mystery", "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()

    tools = [
        StructuredTool.from_function(lambda: "ok", name="bash", description="bash"),
        StructuredTool.from_function(lambda: "ok", name="read", description="read"),
    ]
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
    try:
        asyncio.run(agent._raw_stream([sys_msg, user_msg], tools=tools).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise

    payload = captured["payload"]
    wire = json.dumps(payload)
    assert "cache_control" not in wire  # point 3
    extra = payload.get("extra_body") or {}
    assert "prompt_cache_key" not in extra  # point 5

    # point 4a: tools sorted by name (read before bash would be wrong)
    tool_names = [t.get("function", {}).get("name", "") for t in (payload.get("tools") or [])]
    assert tool_names == sorted(tool_names)


# ---------------------------------------------------------------------------
# FXC6 audit R1: five-point fallback fully exercised at the wire level
# ---------------------------------------------------------------------------


def test_unknown_fallback_contract_carries_variant_and_protocol():
    fb = unknown_fallback_contract()
    assert fb["prompt_variant"] == "default"
    assert fb["protocol"] == "openai-compatible"
    assert fb["cache_mode"] == "auto"
    assert fb["prompt_cache_key_required"] is False


def test_unknown_model_request_sends_session_affinity_header(monkeypatch):
    """The real production build path (AgentV2._build_llm_from_config) sends
    X-Session-Id for an unknown model via the chat client."""
    import asyncio

    import httpx

    import RxyCode.RxyCode1_1_0.core.agent_v2 as av2

    captured: dict = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "id": "x", "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "hi"},
                             "finish_reason": "stop", "index": 0}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    class _FakeProvider:
        name = "openai"

        def capabilities(self, model_config):
            from RxyCode.RxyCode1_1_0.config.model_capabilities import (
                DEFAULT_CAPABILITIES,
            )

            return DEFAULT_CAPABILITIES

        def supports_prompt_cache(self, caps):
            return True

        def extract_cache_read(self, usage, caps):
            return 0

        def extract_reasoning(self, payload, caps):
            return ""

        def llm_kwargs(self, model_config, caps):
            return {
                "model": "mystery",
                "api_key": "sk-test",
                "http_async_client": httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ),
            }

    def fake_resolve(model_config):
        return _FakeProvider()

    monkeypatch.setattr(av2.providers, "resolve", fake_resolve)

    agent = av2.AgentV2.__new__(av2.AgentV2)
    agent._session_id = "sess_fxc6_unknown"
    agent._rate_limiter = None
    agent._rate_limit_timeout = None
    agent._rate_provider = None
    agent._rate_model = None
    agent._rate_reserved_output_tokens = 0

    llm = agent._build_llm_from_config(
        {"base_url": "https://api.unknown-vendor.example/v1", "api_key": "sk-test",
         "model_name": "totally-mystery"}
    )
    asyncio.run(llm.ainvoke("hi"))
    h = captured["headers"]
    assert any(k.casefold() == "x-session-id" for k in h)  # point 4: session header
    assert not any("x-opencode-session" in k.casefold() for k in h)


def test_unknown_model_five_points_on_raw_stream_path():
    """Five-point fallback exercised on the real _raw_stream injection path:
    contract None -> default variant + openai-compatible shape + no
    cache_control + no prompt_cache_key + sorted tools. (Session header lives
    on the HTTP client layer, covered by the production-path test above.)"""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.catalog import get_contract, reset_contract_cache

    reset_contract_cache()
    # rule 0: the REAL catalog lookup returns None for this unknown model,
    # and it flows into _raw_stream untouched (no monkeypatching)
    assert get_contract("no-such", "mystery") is None

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            payload.pop("timeout", None)
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider="unknown",
        prompt_variant="guessed-by-id",
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc6"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": "totally-mystery", "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()
    tools = [
        StructuredTool.from_function(lambda: "ok", name="bash", description="bash"),
        StructuredTool.from_function(lambda: "ok", name="read", description="read"),
    ]
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
    try:
        asyncio.run(agent._raw_stream([sys_msg, user_msg], tools=tools).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise

    # rule 1: variant forced to default
    assert getattr(agent._capabilities, "prompt_variant", None) == "default"
    # rule 2: openai-compatible shape
    assert "messages" in captured["payload"] and "stream" in captured["payload"]
    # rule 3: no cache_control
    assert "cache_control" not in json.dumps(captured["payload"])
    # rule 5: no prompt_cache_key anywhere in the payload
    assert "prompt_cache_key" not in json.dumps(captured["payload"])
    # rule 4: tools sorted by name
    names = [t.get("function", {}).get("name", "") for t in (captured["payload"].get("tools") or [])]
    assert names == sorted(names)
    # rule 4 (headers): session affinity is carried by the HTTP client layer
    # (_build_llm_from_config -> ChatOpenAI default_headers, FXC4) — the same
    # AgentV2 instance; the dedicated production-path test above captures the
    # actual request headers. Here we assert the header shape for an unknown
    # vendor base_url stays X-Session-Id-only.
    from RxyCode.RxyCode1_1_0.core.agent_v2 import build_session_headers

    hdr = build_session_headers("https://api.unknown-vendor.example/v1", "sess-fxc6")
    assert hdr.get("X-Session-Id") == "sess-fxc6"
    assert "x-opencode-session" not in hdr  # never faked on vendor hosts


def test_unknown_model_full_wire_has_no_key_or_control():
    """The whole serialized payload (not just extra_body) must be free of
    cache_control and prompt_cache_key."""
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    captured: dict = {}

    class FakeClient:
        def create(self, **payload):
            payload.pop("timeout", None)
            captured["payload"] = payload
            raise RuntimeError("stop-after-capture")

    caps = replace(
        DEFAULT_CAPABILITIES,
        provider="unknown",
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc6"
    agent._llm = SimpleNamespace()
    agent._rate_limiter = None
    agent.model_config = {"model_name": "totally-mystery", "timeout": 5.0}
    agent._capabilities = caps
    agent._provider = None
    agent._resolve_request_max_tokens = lambda _n: 2048
    agent._openai_client = lambda: FakeClient()

    tools = [
        StructuredTool.from_function(lambda: "ok", name="bash", description="bash"),
        StructuredTool.from_function(lambda: "ok", name="read", description="read"),
    ]
    sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
    user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
    try:
        asyncio.run(agent._raw_stream([sys_msg, user_msg], tools=tools).__anext__())
    except RuntimeError as exc:
        if "stop-after-capture" not in str(exc):
            raise

    wire = json.dumps(captured["payload"])
    assert "cache_control" not in wire
    assert "prompt_cache_key" not in wire
    # fallback rule 2: OpenAI chat.completions shape (openai-compatible)
    assert "messages" in captured["payload"]
    assert "model" in captured["payload"]
    assert "stream" in captured["payload"]
    assert "system" not in captured["payload"]  # no Anthropic top-level system


# ---------------------------------------------------------------------------
# FXC6 audit R6: fallback variant applies BEFORE prompt assembly
# ---------------------------------------------------------------------------


def test_unknown_model_prompt_variant_resolves_default_before_assembly():
    """_prompt_variant() (used by get_system_prompt) must resolve to the
    fallback default for an unknown model — the real catalog returns None."""
    from dataclasses import replace
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.catalog import reset_contract_cache

    reset_contract_cache()
    agent = AgentV2.__new__(AgentV2)
    agent._capabilities = replace(
        DEFAULT_CAPABILITIES, provider="unknown", prompt_variant="guessed"
    )
    agent._provider = SimpleNamespace(name="unknown")
    agent.model_config = {"model_name": "totally-mystery"}
    assert agent._prompt_variant() == "default"


def test_known_model_prompt_variant_unchanged():
    """A model WITH a catalog record keeps its catalog variant."""
    from dataclasses import replace
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.catalog import reset_contract_cache

    reset_contract_cache()
    agent = AgentV2.__new__(AgentV2)
    agent._capabilities = replace(
        DEFAULT_CAPABILITIES, provider="deepseek", prompt_variant="deepseek"
    )
    agent._provider = SimpleNamespace(name="deepseek")
    agent.model_config = {"model_name": "deepseek-v4-flash"}
    assert agent._prompt_variant() == "deepseek"
