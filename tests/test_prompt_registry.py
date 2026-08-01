"""core/prompts 注册表的结构性回归测试。

原先这些断言写在 evals/tasks/readcode-prompt-registry.yaml 里，作为 LLM
评测任务的 check。那是错的：它们检查的是仓库源码结构，与模型能力无关，
而且在空临时工作目录里恒失败。
"""
from __future__ import annotations

import importlib
import inspect

import pytest

from RxyCode.RxyCode1_1_0.core.prompts import (
    PromptSpec,
    build_user_message,
    get_prompt_version,
    get_role_prompt,
    get_system_prompt,
    list_stages,
)

EXPECTED_STAGES = {
    "goal_planner",
    "decomposer",
    "executor",
    "validator",
    "re_planner",
    "synthesizer",
    "subagent_decompose",
    "compose_plan",
    "compose_build",
}


def test_all_expected_stages_registered():
    missing = EXPECTED_STAGES - set(list_stages())
    assert not missing, f"missing stages: {sorted(missing)}"


@pytest.mark.parametrize("stage", sorted(EXPECTED_STAGES))
def test_role_prompt_has_xml_tags(stage):
    prompt = get_role_prompt(stage, include_few_shot=False)
    assert "<ROLE>" in prompt
    assert "</ROLE>" in prompt


@pytest.mark.parametrize("stage", sorted(EXPECTED_STAGES))
def test_every_stage_has_a_version(stage):
    version = get_prompt_version(stage)
    assert isinstance(version, str) and version


def test_few_shot_coverage():
    from RxyCode.RxyCode1_1_0.core.prompts.few_shot import FEW_SHOT_EXAMPLES

    missing = [
        s
        for s in EXPECTED_STAGES
        if not FEW_SHOT_EXAMPLES.get(s)
    ]
    assert not missing, f"stages without few-shot examples: {missing}"


def test_i18n_locales():
    from RxyCode.RxyCode1_1_0.core.prompts.i18n import I18N_TEXTS, SUPPORTED_LOCALES

    assert {"zh", "en"} <= set(SUPPORTED_LOCALES)
    for locale in ("zh", "en"):
        assert "language_requirement" in I18N_TEXTS[locale]


def test_tool_list_uses_registry_as_single_source():
    from RxyCode.RxyCode1_1_0.core.prompts.tool_list import get_tool_descriptions

    src = inspect.getsource(get_tool_descriptions)
    assert "get_descriptions" in src, (
        "tool_list must derive from ToolRegistry.get_descriptions(), "
        "not maintain its own copy"
    )


def test_re_planner_uses_shared_prompt_infrastructure():
    from RxyCode.RxyCode1_1_0.validation import re_planner

    src = inspect.getsource(re_planner)
    assert "get_system_prompt" in src
    assert "build_user_message" in src
    assert "get_role_prompt" in src
    assert "_REPLAN_PROMPT_TEMPLATE" not in src


def test_validator_node_reads_memory_from_state():
    from RxyCode.RxyCode1_1_0.core import graph

    src = inspect.getsource(graph.validator_node)
    assert 'state["_memory"]' in src or "state['_memory']" in src


@pytest.mark.parametrize(
    "module_path,forbidden",
    [
        ("RxyCode.RxyCode1_1_0.planning.goal_planner", "_GOAL_ROLE"),
        ("RxyCode.RxyCode1_1_0.planning.decomposer", "_DECOMPOSE_ROLE"),
        ("RxyCode.RxyCode1_1_0.execution.executor", "_EXECUTOR_ROLE"),
        ("RxyCode.RxyCode1_1_0.validation.validator", "_VALIDATION_ROLE"),
        ("RxyCode.RxyCode1_1_0.synthesis.synthesizer", "_SYNTHESIZE_ROLE"),
    ],
)
def test_no_inline_role_constants_left(module_path, forbidden):
    module = importlib.import_module(module_path)
    assert forbidden not in inspect.getsource(module), (
        f"{module_path} still defines {forbidden} inline; "
        f"role prompts must come from core.prompts"
    )


def test_agent_v2_uses_prompt_registry():
    from RxyCode.RxyCode1_1_0.core import agent_v2

    src = inspect.getsource(agent_v2)
    assert "get_role_prompt" in src, "agent_v2 should use get_role_prompt"
    assert "compose_plan" in src
    assert "compose_build" in src
    assert "subagent_decompose" not in src, (
        "subagent_decompose is registered but not wired in agent_v2 yet"
    )


def test_backward_compatible_api():
    from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT

    assert isinstance(UNIFIED_SYSTEM_PROMPT, str)
    assert get_system_prompt() == UNIFIED_SYSTEM_PROMPT
    assert isinstance(build_user_message("role", "content"), str)
    assert isinstance(get_role_prompt("goal_planner"), str)
    assert len(list_stages()) >= 9
    assert PromptSpec(name="t", version="1.0.0", template="t").version == "1.0.0"
