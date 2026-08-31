"""Formal HY3 provider contracts."""

from config.model_capabilities import DEFAULT_CAPABILITIES
from core import providers
from core.providers.hy3 import Hy3Provider


_GO = "https://opencode.ai/zen/go/v1"


def _config(model_name="hy3", **extra):
    return {
        "base_url": _GO,
        "model_name": model_name,
        "api_key": "test-key",
        "resolved_max_tokens": 8192,
        **extra,
    }


def test_matches_only_formal_hy3_id():
    provider = Hy3Provider()
    assert provider.matches(_GO, "hy3")
    assert provider.matches(_GO, " HY3 ")
    for model in ("hy3-preview", "hy3-latest", "hy30", "hunyuan-role-latest"):
        assert not provider.matches(_GO, model)


def test_registry_resolves_formal_hy3_but_not_preview():
    assert isinstance(providers.resolve(_config()), Hy3Provider)
    assert not isinstance(providers.resolve(_config("hy3-preview")), Hy3Provider)


def test_hy3_keeps_chat_as_its_only_documented_go_transport():
    provider = Hy3Provider()
    assert provider.transport_candidates(_config()) == ("openai_chat",)
    assert provider.uses_responses_api(_config()) is False


def test_hy3_capabilities_and_user_override():
    provider = Hy3Provider()
    caps = provider.capabilities(_config())
    assert caps.provider == "hy3"
    assert caps.context_window == 256_000
    assert caps.compaction_threshold == 230_400
    assert caps.max_output_tokens == 128_000
    assert caps.supports_reasoning is True
    assert caps.supports_function_calling is True
    assert caps.effort_options == ()

    overridden = provider.capabilities(_config(context_window=64_000))
    assert overridden.context_window == 64_000
    assert overridden.max_output_tokens != DEFAULT_CAPABILITIES.max_output_tokens


def test_go_kwargs_do_not_forward_tokenhub_only_fields():
    cfg = _config(
        effort="high",
        extra_body={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "reasoning_content": "private",
            "mandatory_echo": True,
            "previous_response_id": "resp_x",
            "safe_flag": True,
        },
    )
    provider = Hy3Provider()
    kwargs = provider.llm_kwargs(cfg, provider.capabilities(cfg))
    assert "use_responses_api" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"safe_flag": True}
