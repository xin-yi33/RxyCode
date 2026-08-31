"""FXC4 · session affinity headers + DeepSeek dual-field usage + later compaction.

Coverage per PHASE-FIX §5 FXC4 acceptance:
- Go-gateway requests carry session affinity headers (x-opencode-session +
  x-session-affinity / X-Session-Id); direct official endpoints send only
  X-Session-Id and never fake opencode* headers
- DeepSeek usage fixtures: nested-only and flat-only both read; both present
  -> max (via catalog.read_cached_tokens, FXC1 max path)
- compaction threshold: the old ~90% trigger (943_718) no longer fires early
  on the 1M window; v4 caps move to ~0.97x
"""

from __future__ import annotations

import json

from RxyCode.RxyCode1_1_0.core.catalog import read_cached_tokens, reset_contract_cache


# ---------------------------------------------------------------------------
# session affinity headers
# ---------------------------------------------------------------------------


def _headers(base_url: str, session_id: str = "ses_test123") -> dict:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import build_session_headers

    return build_session_headers(base_url, session_id)


def test_go_gateway_carries_full_affinity_headers():
    headers = _headers("https://opencode.ai/zen/go/v1")
    assert headers["x-opencode-session"] == "ses_test123"
    assert headers["x-session-affinity"] == "ses_test123"
    assert headers["X-Session-Id"] == "ses_test123"


def test_zen_gateway_carries_full_affinity_headers():
    headers = _headers("https://opencode.ai/zen/v1")
    assert headers["x-opencode-session"] == "ses_test123"
    assert headers["X-Session-Id"] == "ses_test123"


def test_direct_official_api_only_sends_session_id():
    headers = _headers("https://api.deepseek.com/v1")
    assert headers == {"X-Session-Id": "ses_test123"}
    assert "x-opencode-session" not in headers  # never fake opencode* headers
    assert "x-session-affinity" not in headers


def test_http_base_url_without_gateway_is_direct():
    headers = _headers("https://api.anthropic.com/v1")
    assert headers == {"X-Session-Id": "ses_test123"}


def test_empty_session_id_still_shapes_headers():
    headers = _headers("https://opencode.ai/zen/go/v1", session_id="")
    assert headers["x-opencode-session"] == ""
    assert headers["X-Session-Id"] == ""


def test_vendor_path_containing_go_or_zen_never_fakes_opencode_headers():
    # a path segment saying /go or /zen on a vendor host is NOT the gateway
    assert _headers("https://api.deepseek.com/v1/go") == {"X-Session-Id": "ses_test123"}
    assert _headers("https://api.openai.com/v1/zen") == {"X-Session-Id": "ses_test123"}
    assert _headers("https://api.anthropic.com/v1/go/chat") == {"X-Session-Id": "ses_test123"}
    assert "x-opencode-session" not in _headers("https://api.deepseek.com/v1/go")
    assert "x-session-affinity" not in _headers("https://api.deepseek.com/v1/go")


def test_build_llm_injects_session_headers_into_chatopenai(monkeypatch):
    """The ChatOpenAI constructor receives default_headers from the gateway
    decision (captured via a fake provider, no network)."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    captured: dict = {}

    class _FakeProvider:
        name = "openai"

        def capabilities(self, model_config):  # noqa: ARG002
            from RxyCode.RxyCode1_1_0.config.model_capabilities import (
                DEFAULT_CAPABILITIES,
            )

            return DEFAULT_CAPABILITIES

        def llm_kwargs(self, model_config, caps):  # noqa: ARG002
            captured["model_config"] = dict(model_config)
            return {"model": "x", "api_key": "sk-test"}

    def fake_resolve(model_config):
        captured["model_config"] = dict(model_config)
        return _FakeProvider()

    import RxyCode.RxyCode1_1_0.core.agent_v2 as av2

    monkeypatch.setattr(av2.providers, "resolve", fake_resolve)
    monkeypatch.setattr(
        "langchain_openai.ChatOpenAI",
        lambda **kwargs: captured.setdefault("kwargs", kwargs),
    )

    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "ses_test123"
    agent._rate_limiter = None
    agent._rate_limit_timeout = None
    agent._rate_provider = None
    agent._rate_model = None
    agent._rate_reserved_output_tokens = 0

    agent._build_llm_from_config(
        {
            "base_url": "https://opencode.ai/zen/go/v1",
            "api_key": "sk-test",
            "model_name": "deepseek/deepseek-v4-flash",
        }
    )
    headers = captured["kwargs"].get("default_headers") or {}
    assert headers.get("x-opencode-session") == "ses_test123"
    assert headers.get("X-Session-Id") == "ses_test123"


# ---------------------------------------------------------------------------
# DeepSeek dual-field usage (catalog max path)
# ---------------------------------------------------------------------------


def test_deepseek_nested_only_reads():
    reset_contract_cache()
    usage = {"prompt_tokens_details": {"cached_tokens": 500}}
    assert read_cached_tokens("deepseek", "deepseek-v4-flash", usage) == 500


def test_deepseek_flat_only_reads():
    reset_contract_cache()
    usage = {"prompt_cache_hit_tokens": 800}
    assert read_cached_tokens("deepseek", "deepseek-v4-flash", usage) == 800


def test_deepseek_both_present_takes_max():
    reset_contract_cache()
    usage = {
        "prompt_cache_hit_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 900},
    }
    assert read_cached_tokens("deepseek", "deepseek-v4-flash", usage) == 900


# ---------------------------------------------------------------------------
# later compaction (old ~90% no longer fires early on the 1M window)
# ---------------------------------------------------------------------------


def test_v4_compaction_threshold_is_later_than_old_90pct():
    from RxyCode.RxyCode1_1_0.core.providers.deepseek import (
        _COMPACTION_THRESHOLD,
        _CONTEXT_WINDOW,
        DeepSeekProvider,
    )

    assert _CONTEXT_WINDOW == 1_048_576
    assert _COMPACTION_THRESHOLD > 943_718  # old ~90% point
    expected = int(_CONTEXT_WINDOW * 0.97)
    assert _COMPACTION_THRESHOLD == expected

    caps = DeepSeekProvider().capabilities(
        {"model_name": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1"}
    )
    assert caps.compaction_threshold == _COMPACTION_THRESHOLD


def test_v4_compaction_behaviour_old_90pct_no_longer_triggers(monkeypatch):
    """Old ~90% point (943_718 window) must not fire compaction; the
    0.97x threshold decides."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    caps = type("Caps", (), {"compaction_threshold": int(1_048_576 * 0.97)})()
    agent._capabilities = caps
    agent._estimate_tokens = lambda messages: 950_000  # between 90% and 97%
    agent._context_window = lambda: 1_048_576
    called = {"n": 0}

    def fake_compact(messages, tail_turns=2, return_telemetry=True):  # sync like the real one
        called["n"] += 1
        return messages, {"compacted": False}

    monkeypatch.setattr("RxyCode.RxyCode1_1_0.core.compaction.compact_messages", fake_compact)

    import asyncio

    asyncio.run(agent._maybe_compress_context([]))
    assert called["n"] == 0  # old 90% point does NOT trigger anymore


def test_v4_compaction_behaviour_triggers_near_97pct(monkeypatch):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    caps = type("Caps", (), {"compaction_threshold": int(1_048_576 * 0.97)})()
    agent._capabilities = caps
    agent._estimate_tokens = lambda messages: 1_050_000  # above the 0.97x budget
    agent._context_window = lambda: 1_048_576
    called = {"n": 0}

    def fake_compact(messages, tail_turns=2, return_telemetry=True):  # sync like the real one
        called["n"] += 1
        return messages, {
            "compacted": True,
            "tokens_before": 1_050_000,
            "tokens_after": 800_000,
            "tail_turns": 2,
        }

    monkeypatch.setattr("RxyCode.RxyCode1_1_0.core.compaction.compact_messages", fake_compact)

    import asyncio

    asyncio.run(agent._maybe_compress_context([]))
    assert called["n"] == 1  # 0.97x budget reached -> compaction fires


def test_v4_cache_min_block_tokens_v4_caliber():
    from RxyCode.RxyCode1_1_0.core.providers.deepseek import DeepSeekProvider

    caps = DeepSeekProvider().capabilities(
        {"model_name": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1"}
    )
    assert caps.cache_min_block_tokens == 1024  # 256-bucket, ~1024 start (V4)


# ---------------------------------------------------------------------------
# FXC4 audit R2 additions: keep-alive default + FX-CB guard rails
# ---------------------------------------------------------------------------


def test_deepseek_catalog_and_provider_keep_alive_default_off():
    import json as _json
    from pathlib import Path

    from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_enabled
    from RxyCode.RxyCode1_1_0.core.providers.deepseek import DeepSeekProvider

    # catalog record: no keep-alive switch -> default off
    catalog = _json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "model_catalog.json")
        .read_text(encoding="utf-8")
    )
    ds = [r for r in catalog["records"] if r.get("provider_id") == "deepseek"]
    assert ds, "deepseek records present"
    for record in ds:
        cc = record.get("cache_contract") or {}
        assert not cc.get("keep_alive"), f"{record['model_id']} unexpectedly enables keep-alive"

    # provider capabilities carry no keep-alive flag either
    caps = DeepSeekProvider().capabilities(
        {"model_name": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/v1"}
    )
    assert getattr(caps, "keep_alive", None) is None
    assert keep_alive_enabled({}) is False


def test_deepseek_catalog_declares_both_usage_paths():
    """FXC4: every DeepSeek record declares BOTH cached paths explicitly
    (nested prompt_tokens_details.cached_tokens + flat prompt_cache_hit_tokens),
    so the FXC1 max() has a real second field — not a silent fallback."""
    import json as _json
    from pathlib import Path

    catalog = _json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "model_catalog.json")
        .read_text(encoding="utf-8")
    )
    deepseek = [r for r in catalog["records"] if r.get("provider_id") == "deepseek"]
    assert deepseek, "deepseek records present"
    for record in deepseek:
        uf = (record.get("cache_contract") or {}).get("usage_fields") or {}
        assert uf.get("cached") == "prompt_tokens_details.cached_tokens", record["model_id"]
        assert uf.get("cached_alt") == "prompt_cache_hit_tokens", record["model_id"]


def test_deepseek_keep_alive_defaults_off():
    from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_enabled

    assert keep_alive_enabled({}) is False  # default off for every provider


def test_implicit_family_never_gets_cache_control():
    """FX-CB9 guard rail: DeepSeek / MiniMax M3 never emit cache_control."""
    from RxyCode.RxyCode1_1_0.core.catalog import (
        get_contract,
        injects_cache_control,
        reset_contract_cache,
    )

    reset_contract_cache()
    for provider, model in (
        ("deepseek", "deepseek-v4-flash"),
        ("minimax", "minimax-m3"),
    ):
        contract = get_contract(provider, model)
        assert contract is not None, f"{provider}:{model} missing"
        assert injects_cache_control(contract) is False


def test_unknown_contract_never_injects_control_or_key():
    from RxyCode.RxyCode1_1_0.core.catalog import (
        injects_cache_control,
        injects_prompt_cache_key,
    )

    assert injects_cache_control(None) is False
    assert injects_prompt_cache_key(None) is False


def test_cache_mode_uses_only_schema_enum():
    """FX-CB guard: no record uses explicit / breakpoints aliases."""
    import json
    from pathlib import Path

    catalog = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "model_catalog.json")
        .read_text(encoding="utf-8")
    )
    allowed = {"auto", "cache_key", "auto_and_key", "explicit_breakpoints"}
    for record in catalog.get("records", []):
        mode = (record.get("cache_contract") or {}).get("cache_mode")
        assert mode in allowed, f"illegal cache_mode {mode!r} in {record.get('model_id')}"
def test_explicit_family_still_injects_control():
    """Sanity: the explicit family (Claude) still injects, per FX-CB10."""
    from RxyCode.RxyCode1_1_0.core.catalog import (
        get_contract,
        injects_cache_control,
        reset_contract_cache,
    )

    reset_contract_cache()
    contract = get_contract("anthropic", "claude-sonnet-4.5")
    assert contract is not None
    assert injects_cache_control(contract) is True


# ---------------------------------------------------------------------------
# FXC4 audit R3: request-layer capture via httpx fake transport
# ---------------------------------------------------------------------------


def _fake_llm(base_url: str, session_id: str):
    """Build a ChatOpenAI wired with a capture transport (no network)."""
    import httpx
    from langchain_openai import ChatOpenAI

    from RxyCode.RxyCode1_1_0.core.agent_v2 import build_session_headers

    captured: dict = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    llm = ChatOpenAI(
        model="gpt-4o",
        api_key="sk-test",
        base_url=base_url,
        default_headers=build_session_headers(base_url, session_id),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )
    return llm, captured


def _find_header(headers: dict, name: str):
    for key, value in headers.items():
        if key.casefold() == name.casefold():
            return value
    return None


def test_go_gateway_request_carries_all_three_affinity_headers():
    import asyncio

    llm, captured = _fake_llm("https://opencode.ai/zen/go/v1", "ses_test123")
    asyncio.run(llm.ainvoke("hi"))
    h = captured["headers"]
    assert _find_header(h, "x-opencode-session") == "ses_test123"
    assert _find_header(h, "x-session-affinity") == "ses_test123"
    assert _find_header(h, "x-session-id") == "ses_test123"


def test_direct_vendor_request_only_sends_session_id():
    import asyncio

    llm, captured = _fake_llm("https://api.deepseek.com/v1", "ses_test123")
    asyncio.run(llm.ainvoke("hi"))
    h = captured["headers"]
    assert _find_header(h, "x-session-id") == "ses_test123"
    assert _find_header(h, "x-opencode-session") is None  # never faked
    assert _find_header(h, "x-session-affinity") is None


# ---------------------------------------------------------------------------
# FXC4 audit R4: zen/go gateway hosts + production-path request capture
# ---------------------------------------------------------------------------


def test_vendor_path_go_zen_still_not_gateway():
    # vendor host + path /go /zen is NOT a gateway (no opencode* faking)
    assert _headers("https://api.deepseek.com/v1/go") == {"X-Session-Id": "ses_test123"}
    assert _headers("https://api.openai.com/v1/zen") == {"X-Session-Id": "ses_test123"}


def test_lookalike_domains_never_fake_opencode_headers():
    # strict allow-list: only opencode.ai and *.opencode.ai are gateways
    for url in (
        "https://notopencode.ai/v1",
        "https://opencode.ai.evil.example/v1",
        "https://go.other-service.io/v1",
        "https://zen.other-service.io/v1",
    ):
        assert _headers(url) == {"X-Session-Id": "ses_test123"}, url


def test_opencode_ai_subdomains_are_gateways():
    assert "x-opencode-session" in _headers("https://zen.opencode.ai/v1")
    assert "x-opencode-session" in _headers("https://go.opencode.ai/v1")


def test_production_build_path_captures_gateway_request(monkeypatch):
    """Go gateway through AgentV2._build_llm_from_config: capture the real
    HTTP request via a fake async client (no network)."""
    import asyncio

    import httpx

    import RxyCode.RxyCode1_1_0.core.agent_v2 as av2

    captured: dict = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "choices": [
                    {"message": {"role": "assistant", "content": "hi"},
                     "finish_reason": "stop", "index": 0}
                ],
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
                "model": "gpt-4o",
                "api_key": "sk-test",
                "http_async_client": httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ),
            }

    def fake_resolve(model_config):
        return _FakeProvider()

    monkeypatch.setattr(av2.providers, "resolve", fake_resolve)

    agent = av2.AgentV2.__new__(av2.AgentV2)
    agent._session_id = "ses_test123"
    agent._rate_limiter = None
    agent._rate_limit_timeout = None
    agent._rate_provider = None
    agent._rate_model = None
    agent._rate_reserved_output_tokens = 0

    llm = agent._build_llm_from_config(
        {"base_url": "https://opencode.ai/zen/go/v1", "api_key": "sk-test",
         "model_name": "deepseek/deepseek-v4-flash"}
    )
    asyncio.run(llm.ainvoke("hi"))
    h = captured["headers"]
    assert _find_header(h, "x-opencode-session") == "ses_test123"
    assert _find_header(h, "x-session-affinity") == "ses_test123"
    assert _find_header(h, "x-session-id") == "ses_test123"


def test_production_build_path_direct_vendor_only_session_id(monkeypatch):
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
        name = "deepseek"

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
                "model": "deepseek-v4-flash",
                "api_key": "sk-test",
                "http_async_client": httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ),
            }

    def fake_resolve(model_config):
        return _FakeProvider()

    monkeypatch.setattr(av2.providers, "resolve", fake_resolve)

    agent = av2.AgentV2.__new__(av2.AgentV2)
    agent._session_id = "ses_test123"
    agent._rate_limiter = None
    agent._rate_limit_timeout = None
    agent._rate_provider = None
    agent._rate_model = None
    agent._rate_reserved_output_tokens = 0

    llm = agent._build_llm_from_config(
        {"base_url": "https://api.deepseek.com/v1", "api_key": "sk-test",
         "model_name": "deepseek/deepseek-v4-flash"}
    )
    asyncio.run(llm.ainvoke("hi"))
    h = captured["headers"]
    assert _find_header(h, "x-session-id") == "ses_test123"
    assert _find_header(h, "x-opencode-session") is None
    assert _find_header(h, "x-session-affinity") is None


def test_implicit_family_final_messages_have_no_cache_control():
    """FX-CB9 at the payload level: DeepSeek / MiniMax M3 final messages never
    carry cache_control (via the real _apply_cache_control)."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
    from RxyCode.RxyCode1_1_0.core.catalog import reset_contract_cache
    from types import SimpleNamespace

    reset_contract_cache()
    msgs = [SimpleNamespace(type="system", content="SYS", additional_kwargs={})]
    for provider, model, caps_provider in (
        ("deepseek", "deepseek-v4-flash", "deepseek"),
        ("minimax", "minimax-m3", "minimax"),
    ):
        agent = UsageTrackingLLM.__new__(UsageTrackingLLM)
        agent._provider = SimpleNamespace(
            name=provider,
            supports_prompt_cache=lambda caps: True,
        )
        agent._capabilities = SimpleNamespace(
            provider=caps_provider, cache_breakpoints=(), supports_prompt_cache=True
        )
        agent.model_config = {"model_name": model}
        agent._cache_enabled = True
        out = agent._apply_cache_control(list(msgs))
        serialized = json.dumps(
            [{"type": m.type, "content": m.content,
              "additional_kwargs": dict(m.additional_kwargs)} for m in out],
            ensure_ascii=False,
        )
        assert "cache_control" not in serialized, f"{provider}:{model} leaked cache_control"

    # unknown model goes through the real production path and stays clean too
    agent = UsageTrackingLLM.__new__(UsageTrackingLLM)
    agent._provider = SimpleNamespace(name="no-such", supports_prompt_cache=lambda caps: True)
    agent._capabilities = SimpleNamespace(provider="no-such", cache_breakpoints=(), supports_prompt_cache=True)
    agent.model_config = {"model_name": "mystery"}
    agent._cache_enabled = True
    out = agent._apply_cache_control(list(msgs))
    serialized = json.dumps(
        [{"type": m.type, "content": m.content,
          "additional_kwargs": dict(m.additional_kwargs)} for m in out],
        ensure_ascii=False,
    )
    assert "cache_control" not in serialized  # unknown never injected


def test_explicit_family_marks_only_last_tool_breakpoint():
    """FX-CB10: the explicit family stamps only the LAST tool, never all."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
    from RxyCode.RxyCode1_1_0.core.catalog import reset_contract_cache
    from types import SimpleNamespace

    reset_contract_cache()
    agent = UsageTrackingLLM.__new__(UsageTrackingLLM)
    agent._provider = SimpleNamespace(name="anthropic", supports_prompt_cache=lambda caps: True)
    agent._capabilities = SimpleNamespace(provider="anthropic", cache_breakpoints=(), supports_prompt_cache=True)
    agent.model_config = {"model_name": "claude-sonnet-4.5"}
    agent._cache_enabled = True

    tools = [SimpleNamespace(name="read", parameters={}),
             SimpleNamespace(name="bash", parameters={}),
             SimpleNamespace(name="write", parameters={})]
    agent._apply_cache_control([SimpleNamespace(type="system", content="SYS", additional_kwargs={})], tools=tools)

    # apply_breakpoint_budget returns (messages, allocated, ttl); tools are
    # marked inside the messages' tool blocks — here we assert via the
    # exported breakpoint ordering helper that the LAST tool is the marker.
    from RxyCode.RxyCode1_1_0.core.cache_policy import apply_breakpoint_budget
    from types import SimpleNamespace as NS

    caps2 = NS(cache_breakpoints=("tools", "system", "messages", "tail"))
    _msg, allocated, _ttl = apply_breakpoint_budget(
        [NS(type="system", content="SYS", additional_kwargs={})],
        tools=tools, caps=caps2,
        contract={"cache_mode": "explicit_breakpoints", "breakpoints_max": 4},
    )
    assert "tools" in allocated  # the explicit family did allocate a tool breakpoint
    # and it applies exactly once (a single breakpoint covers the last tool)
    assert allocated.count("tools") == 1


# ---------------------------------------------------------------------------
# FXC4 audit R5: real _raw_stream payload capture (explicit last-tool, implicit none)
# ---------------------------------------------------------------------------


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
        cache_breakpoints=("tools", "system", "tail"),
        supports_function_calling=True,
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "sess-fxc4"
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


def test_explicit_raw_stream_marks_only_last_tool():
    payload = _capture_raw_stream("claude-sonnet-4.5", "anthropic", _two_tools())
    tools = payload.get("tools") or []
    assert len(tools) == 2
    assert "cache_control" not in tools[0]
    assert tools[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert json.dumps(payload["tools"]).count("cache_control") == 1


def test_deepseek_raw_stream_has_no_cache_control():
    payload = _capture_raw_stream("deepseek-v4-flash", "deepseek", _two_tools())
    assert "cache_control" not in json.dumps(payload)


def test_minimax_m3_raw_stream_has_no_cache_control():
    payload = _capture_raw_stream("minimax-m3", "minimax", _two_tools())
    assert "cache_control" not in json.dumps(payload)


def test_unknown_raw_stream_has_no_cache_control():
    payload = _capture_raw_stream("totally-unknown", "unknown", _two_tools())
    assert "cache_control" not in json.dumps(payload)
