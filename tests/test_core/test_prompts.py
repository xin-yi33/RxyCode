"""Tests for the prompt registry system.

Covers: PromptRegistry, get_system_prompt, build_user_message,
get_role_prompt, i18n, few_shot, tool_list, backward compatibility.
"""

import pytest


# ---------------------------------------------------------------------------
# Backward compatibility: UNIFIED_SYSTEM_PROMPT constant
# ---------------------------------------------------------------------------

class TestUnifiedSystemPrompt:
    def test_is_string(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        assert isinstance(UNIFIED_SYSTEM_PROMPT, str)

    def test_non_empty(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        assert len(UNIFIED_SYSTEM_PROMPT) > 100

    def test_mentions_rxycode(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        assert "RxyCode" in UNIFIED_SYSTEM_PROMPT

    def test_mentions_capabilities(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        assert "Code generation" in UNIFIED_SYSTEM_PROMPT
        assert "Debugging" in UNIFIED_SYSTEM_PROMPT
        assert "File operations" in UNIFIED_SYSTEM_PROMPT

    def test_defines_general_agent_identity(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        assert "general-purpose AI agent" in UNIFIED_SYSTEM_PROMPT
        assert "Research and analysis" in UNIFIED_SYSTEM_PROMPT
        assert "General task execution" in UNIFIED_SYSTEM_PROMPT
        assert "coding assistant" not in UNIFIED_SYSTEM_PROMPT.lower()

    def test_uses_markdown(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        assert "Markdown" in UNIFIED_SYSTEM_PROMPT

    def test_has_language_requirement(self):
        from RxyCode.RxyCode1_1_0.core.prompts import UNIFIED_SYSTEM_PROMPT
        # Default locale is zh
        assert "中文" in UNIFIED_SYSTEM_PROMPT


class TestGetSystemPrompt:
    def test_returns_unified_prompt(self):
        """get_system_prompt() with no args == UNIFIED_SYSTEM_PROMPT."""
        from RxyCode.RxyCode1_1_0.core.prompts import (
            get_system_prompt, UNIFIED_SYSTEM_PROMPT
        )
        result = get_system_prompt()
        assert result == UNIFIED_SYSTEM_PROMPT

    def test_with_tools_true(self):
        """get_system_prompt(tools=True) includes tool descriptions or placeholder."""
        from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt
        result = get_system_prompt(tools=True)
        # Either tool descriptions are injected, or placeholder text appears
        assert "<TOOLS>" in result
        assert "</TOOLS>" in result

    def test_with_tools_false(self):
        """get_system_prompt(tools=False) has placeholder for tools."""
        from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt
        result = get_system_prompt(tools=False)
        assert "<TOOLS>" in result
        # Without tools registered, placeholder text appears
        assert "no tools registered" in result or "- " in result

    def test_locale_override(self):
        """get_system_prompt(locale='en') has English language requirement."""
        from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt
        result = get_system_prompt(locale="en")
        assert "English" in result

    def test_locale_zh(self):
        """get_system_prompt(locale='zh') has Chinese language requirement."""
        from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt
        result = get_system_prompt(locale="zh")
        assert "中文" in result


class TestBuildUserMessage:
    def test_basic_message(self):
        from RxyCode.RxyCode1_1_0.core.prompts import build_user_message
        result = build_user_message("Test role", "Hello")
        assert "Test role" in result
        assert "Hello" in result

    def test_includes_timestamp(self):
        from RxyCode.RxyCode1_1_0.core.prompts import build_user_message
        result = build_user_message("", "Hello")
        assert "当前时间" in result  # zh default

    def test_with_memory_context(self):
        from RxyCode.RxyCode1_1_0.core.prompts import build_user_message
        result = build_user_message("", "Hello", memory_context="ctx")
        assert "ctx" in result
        assert "对话上下文" in result  # zh default

    def test_locale_en(self):
        from RxyCode.RxyCode1_1_0.core.prompts import build_user_message
        result = build_user_message("", "Hello", locale="en")
        assert "Current time" in result

    def test_separator(self):
        from RxyCode.RxyCode1_1_0.core.prompts import build_user_message
        result = build_user_message("Role", "Content")
        assert "---" in result


# ---------------------------------------------------------------------------
# New: PromptRegistry tests
# ---------------------------------------------------------------------------

class TestPromptRegistry:
    def test_list_stages(self):
        from RxyCode.RxyCode1_1_0.core.prompts import list_stages
        stages = list_stages()
        assert "goal_planner" in stages
        assert "decomposer" in stages
        assert "executor" in stages
        assert "validator" in stages
        assert "re_planner" in stages
        assert "reflection" in stages
        assert "synthesizer" in stages

    def test_get_role_prompt(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("goal_planner")
        assert "<ROLE>" in prompt
        assert "Goal Planner" in prompt
        assert "<INSTRUCTIONS>" in prompt
        assert "<OUTPUT_FORMAT>" in prompt

    def test_get_role_prompt_with_few_shot(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("goal_planner", include_few_shot=True)
        assert "<EXAMPLES>" in prompt
        assert "Example 1" in prompt

    def test_get_role_prompt_without_few_shot(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("goal_planner", include_few_shot=False)
        assert "Example 1" not in prompt

    def test_get_role_prompt_unknown_key(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        with pytest.raises(KeyError):
            get_role_prompt("nonexistent_stage")

    def test_get_role_prompt_locale_en(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("validator", locale="en")
        assert "<ROLE>" in prompt
        assert "Validator" in prompt

    def test_re_planner_template_format(self):
        """re_planner prompt accepts format kwargs for task details."""
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt(
            "re_planner",
            title="Test Task",
            description="Test Description",
            requirement="Test Requirement",
            validation_issues="Issue 1",
            suggestion="Fix it",
            result="Previous result",
        )
        assert "Test Task" in prompt
        assert "Test Description" in prompt
        assert "Issue 1" in prompt
        assert "Fix it" in prompt
        assert "Previous result" in prompt

    def test_reflection_template_classifies_failures(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt

        prompt = get_role_prompt(
            "reflection",
            task="Build feature",
            result="Tests failed",
            validation_issues=["Missing behavior"],
            error_history=["tool timeout"],
            include_few_shot=False,
        )

        assert "planning_error" in prompt
        assert "reasoning_error" in prompt
        assert "tool_error" in prompt
        assert "Build feature" in prompt

    def test_all_stages_have_xml_tags(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt, list_stages
        for stage in list_stages():
            prompt = get_role_prompt(stage, include_few_shot=False)
            assert "<ROLE>" in prompt, f"Stage {stage} missing <ROLE> tag"
            assert "</ROLE>" in prompt, f"Stage {stage} missing </ROLE> tag"


# ---------------------------------------------------------------------------
# New: i18n tests
# ---------------------------------------------------------------------------

class TestI18N:
    def test_get_locale_default(self):
        from RxyCode.RxyCode1_1_0.core.prompts.i18n import get_locale
        locale = get_locale()
        assert locale in ("zh", "en")

    def test_translate_zh(self):
        from RxyCode.RxyCode1_1_0.core.prompts.i18n import t
        assert "中文" in t("language_requirement", "zh")

    def test_translate_en(self):
        from RxyCode.RxyCode1_1_0.core.prompts.i18n import t
        assert "English" in t("language_requirement", "en")

    def test_supported_locales(self):
        from RxyCode.RxyCode1_1_0.core.prompts.i18n import SUPPORTED_LOCALES
        assert "zh" in SUPPORTED_LOCALES
        assert "en" in SUPPORTED_LOCALES

    def test_translate_missing_key(self):
        from RxyCode.RxyCode1_1_0.core.prompts.i18n import t
        # Missing key returns the key itself
        assert t("nonexistent_key", "zh") == "nonexistent_key"


# ---------------------------------------------------------------------------
# New: few-shot tests
# ---------------------------------------------------------------------------

class TestFewShot:
    def test_get_few_shot(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import get_few_shot
        examples = get_few_shot("goal_planner")
        assert len(examples) >= 1
        assert "input" in examples[0]
        assert "output" in examples[0]

    def test_get_few_shot_unknown_key(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import get_few_shot
        assert get_few_shot("nonexistent") == []

    def test_format_few_shot(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import format_few_shot
        text = format_few_shot("goal_planner")
        assert "Example 1" in text
        assert "Input:" in text
        assert "Output:" in text

    def test_format_few_shot_empty(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import format_few_shot
        assert format_few_shot("nonexistent") == ""

    def test_all_stages_have_examples(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import FEW_SHOT_EXAMPLES
        from RxyCode.RxyCode1_1_0.core.prompts import list_stages
        stages_with_examples = set(list_stages()) - {"reflection"}
        for stage in stages_with_examples:
            assert stage in FEW_SHOT_EXAMPLES, f"Stage {stage} has no few-shot examples"
            assert len(FEW_SHOT_EXAMPLES[stage]) >= 1


# ---------------------------------------------------------------------------
# New: tool_list tests
# ---------------------------------------------------------------------------

class TestToolList:
    def test_get_tool_descriptions_no_registry(self):
        """When ToolRegistry has no tools, returns empty string."""
        from RxyCode.RxyCode1_1_0.core.prompts.tool_list import get_tool_descriptions
        # This test runs without tool registration, should return empty or descriptions
        result = get_tool_descriptions()
        assert isinstance(result, str)

    def test_get_tool_names(self):
        from RxyCode.RxyCode1_1_0.core.prompts.tool_list import get_tool_names
        names = get_tool_names()
        assert isinstance(names, list)


# ---------------------------------------------------------------------------
# New: PromptSpec versioning tests (plan requirement)
# ---------------------------------------------------------------------------

class TestPromptSpec:
    def test_prompt_spec_is_frozen(self):
        from RxyCode.RxyCode1_1_0.core.prompts import PromptSpec
        spec = PromptSpec(name="test", version="1.0.0", template="Hello")
        # frozen dataclass
        with pytest.raises(Exception):
            spec.name = "changed"

    def test_prompt_spec_fields(self):
        from RxyCode.RxyCode1_1_0.core.prompts import PromptSpec
        spec = PromptSpec(name="decomposer", version="1.0.0", template="tmpl")
        assert spec.name == "decomposer"
        assert spec.version == "1.0.0"
        assert spec.template == "tmpl"
        assert spec.few_shots == ()

    def test_all_stages_have_version(self):
        """Every registered stage must have a non-empty version string."""
        from RxyCode.RxyCode1_1_0.core.prompts import list_stages, get_prompt_version
        for stage in list_stages():
            v = get_prompt_version(stage)
            assert isinstance(v, str) and len(v) > 0, f"Stage {stage} has no version"

    def test_get_prompt_version_known_stage(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_prompt_version
        assert get_prompt_version("goal_planner") == "1.0.0"

    def test_get_prompt_version_unknown_stage(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_prompt_version
        with pytest.raises(KeyError):
            get_prompt_version("nonexistent")

    def test_registry_uses_get_descriptions(self):
        """tool_list.py should use registry.get_descriptions() as single source."""
        import inspect
        from RxyCode.RxyCode1_1_0.core.prompts.tool_list import get_tool_descriptions
        src = inspect.getsource(get_tool_descriptions)
        assert "get_descriptions" in src, "tool_list should use registry.get_descriptions()"

    def test_prompt_cache_deleted(self):
        """cache/prompt_cache.py should be deleted (merged into registry)."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "cache", "prompt_cache.py"
        )
        assert not os.path.exists(path), "cache/prompt_cache.py should be deleted"


# ---------------------------------------------------------------------------
# New: compose / subagent template tests
# ---------------------------------------------------------------------------

class TestSubagentDecomposeTemplate:
    def test_registered(self):
        from RxyCode.RxyCode1_1_0.core.prompts import list_stages
        assert "subagent_decompose" in list_stages()

    def test_xml_tags(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("subagent_decompose", include_few_shot=False)
        assert "<ROLE>" in prompt
        assert "<INSTRUCTIONS>" in prompt
        assert "<OUTPUT_FORMAT>" in prompt

    def test_user_input_injected(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt(
            "subagent_decompose",
            user_input="实现一个TODO应用",
            include_few_shot=False,
        )
        assert "实现一个TODO应用" in prompt

    def test_has_few_shot(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import FEW_SHOT_EXAMPLES
        assert "subagent_decompose" in FEW_SHOT_EXAMPLES
        assert len(FEW_SHOT_EXAMPLES["subagent_decompose"]) >= 1

    def test_few_shot_included(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("subagent_decompose", include_few_shot=True)
        assert "<EXAMPLES>" in prompt
        assert "Example 1" in prompt


class TestComposePlanTemplate:
    def test_registered(self):
        from RxyCode.RxyCode1_1_0.core.prompts import list_stages
        assert "compose_plan" in list_stages()

    def test_xml_tags(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt("compose_plan", include_few_shot=False)
        assert "<ROLE>" in prompt
        assert "<INSTRUCTIONS>" in prompt
        assert "<OUTPUT_FORMAT>" in prompt

    def test_user_input_injected(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt(
            "compose_plan",
            user_input="重构配置管理模块",
            include_few_shot=False,
        )
        assert "重构配置管理模块" in prompt

    def test_has_few_shot(self):
        from RxyCode.RxyCode1_1_0.core.prompts.few_shot import FEW_SHOT_EXAMPLES
        assert "compose_plan" in FEW_SHOT_EXAMPLES
        assert len(FEW_SHOT_EXAMPLES["compose_plan"]) >= 1


class TestComposeBuildTemplate:
    def test_registered(self):
        from RxyCode.RxyCode1_1_0.core.prompts import list_stages
        assert "compose_build" in list_stages()

    def test_xml_tags(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt(
            "compose_build",
            user_input="test",
            plan_file="/tmp/plan.md",
            plan_content="step 1",
            include_few_shot=False,
        )
        assert "<ROLE>" in prompt
        assert "<INSTRUCTIONS>" in prompt

    def test_plan_content_injected(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt
        prompt = get_role_prompt(
            "compose_build",
            user_input="原始任务",
            plan_file="/tmp/plan.md",
            plan_content="1. 第一步\n2. 第二步",
            include_few_shot=False,
        )
        assert "原始任务" in prompt
        assert "/tmp/plan.md" in prompt
        assert "第一步" in prompt


class TestOpenDeliverableGuidance:
    """Regression guard for issue 7: a request to make AND open a file
    (e.g. "make a game and open it") must keep the open step in
    the plan/execution so open_file is actually invoked."""

    def test_decomposer_folds_open_into_single_atomic_task(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt

        prompt = get_role_prompt("decomposer", include_few_shot=False)
        lowered = prompt.lower()
        assert "open_file" in lowered
        # It must NOT instruct splitting create+open into separate (often
        # unstable) sub-tasks; the fold-into-one guidance is required.
        assert "one atomic" in lowered or "do not split" in lowered
        assert "open" in lowered and "preview" in lowered

    def test_executor_is_told_to_open_produced_file(self):
        from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt

        prompt = get_role_prompt("executor", include_few_shot=False)
        lowered = prompt.lower()
        assert "open_file" in lowered
        assert "open" in lowered


class TestAgentV2Migration:
    """Verify agent_v2.py no longer has inline prompt f-strings."""

    def test_uses_get_role_prompt(self):
        import inspect
        from RxyCode.RxyCode1_1_0.core import agent_v2
        src = inspect.getsource(agent_v2)
        assert "get_role_prompt" in src

    def test_legacy_subagent_execution_is_disabled(self):
        import inspect
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        src = inspect.getsource(AgentV2._run_with_subagents)
        assert "legacy sub-agent execution is disabled" in src
        assert "subagent_decompose" not in src

    def test_uses_compose_plan(self):
        import inspect
        from RxyCode.RxyCode1_1_0.core import agent_v2
        src = inspect.getsource(agent_v2)
        assert "compose_plan" in src

    def test_uses_compose_build(self):
        import inspect
        from RxyCode.RxyCode1_1_0.core import agent_v2
        src = inspect.getsource(agent_v2)
        assert "compose_build" in src

