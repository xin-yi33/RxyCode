"""A9: AgentV2 passes capabilities.prompt_variant into prompt lookups."""

from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES, ModelCapabilities
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def test_prompt_variant_helper_uses_capabilities():
    agent = AgentV2.__new__(AgentV2)
    agent._capabilities = ModelCapabilities(prompt_variant="deepseek-v4-flash")
    assert agent._prompt_variant() == "deepseek-v4-flash"


def test_prompt_variant_helper_defaults():
    agent = AgentV2.__new__(AgentV2)
    assert agent._prompt_variant() == DEFAULT_CAPABILITIES.prompt_variant == "default"
