"""A23: DoubaoProvider registration and capability declaration."""

from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
from RxyCode.RxyCode1_1_0.core import providers
from RxyCode.RxyCode1_1_0.core.providers.doubao import DoubaoProvider

_ARK = "https://ark.cn-beijing.volces.com/api/coding/v3"


def test_matches_doubao_models_on_ark():
    p = DoubaoProvider()
    assert p.matches(_ARK, "doubao-seed-2.1-turbo")
    assert p.matches(_ARK, "doubao-seed-2.1-pro")


def test_does_not_steal_other_ark_models():
    p = DoubaoProvider()
    assert not p.matches(_ARK, "minimax-m3")
    assert not p.matches(_ARK, "glm-5.2")
    assert not p.matches("https://api.deepseek.com/v1", "doubao-seed-2.1-turbo")
    assert not p.matches("https://api.openai.com/v1", "gpt-4o")


def test_resolve_returns_doubao_for_doubao_config():
    resolved = providers.resolve(
        {"base_url": _ARK, "model_name": "doubao-seed-2.1-turbo"}
    )
    assert isinstance(resolved, DoubaoProvider)


def test_capabilities_match_research():
    p = DoubaoProvider()
    caps = p.capabilities({"base_url": _ARK, "model_name": "doubao-seed-2.1-turbo"})
    assert caps.provider == "doubao"
    assert caps.supports_reasoning is True
    assert caps.supports_function_calling is True
    assert caps.usage_fields.reasoning == ("reasoning_content",)
    assert caps.tokenizer == "chars:2.0"
    assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000


def test_overrides_apply():
    p = DoubaoProvider()
    caps = p.capabilities(
        {"base_url": _ARK, "model_name": "doubao-seed-2.1-turbo", "tokenizer": "tiktoken:o200k_base"}
    )
    assert caps.tokenizer == "tiktoken:o200k_base"
