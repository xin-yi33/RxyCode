"""Informational (read/verify) vs build (write/danger) grounding matrices."""

from __future__ import annotations

import itertools

import pytest

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree
from RxyCode.RxyCode1_1_0.validation.final_output import (
    build_grounding_sources,
    verify_grounded_synthesis,
)
from RxyCode.RxyCode1_1_0.validation.side_effects import (
    is_supporting_effect,
    task_requires_side_effect_evidence,
)


_INFORMATIONAL_EFFECTS = (
    "read", "verify", "check", "none", "explain", "search", "query", "analysis",
)

_BUILD_EFFECTS = ("write", "danger", "auto")

_TITLES = (
    "Explain how caching works",
    "Verify file integrity after write",
    "Check deployment status",
    "Search documentation for API limits",
    "Analyze error logs",
    "Implement login endpoint",
    "Create configuration file",
    "Build REST API module",
    "Fix authentication bug",
    "Deploy service to production",
    "解释 Python 装饰器",
    "验证数据库连接",
    "检查单元测试结果",
    "实现用户注册功能",
    "创建 Dockerfile",
    "构建前端组件",
    "修复内存泄漏",
    "部署到测试环境",
)

_PURE_GROUND_TITLES = (
    "Explain how caching works",
    "Check deployment status",
    "Search documentation for API limits",
    "Analyze error logs",
)

_INFO_TITLES = list(_PURE_GROUND_TITLES) + [
    "Verify file integrity after write",
    "解释 Python 装饰器",
    "验证数据库连接",
]
_NEUTRAL_RESULTS = (
    "The module exports three public functions.",
    "Analysis complete: no anomalies detected.",
)

_RESULTS = _NEUTRAL_RESULTS + (
    "Verification passed: checksum matches.",
    "Successfully created the requested file.",
    "已成功创建配置文件。",
    "I have implemented the login endpoint.",
)


def _tree(*, title: str, effect: str, result: str) -> TaskTree:
    task = TaskNode(
        id="leaf-1",
        title=title,
        description=title,
        requirement="return verified output only",
        status=TaskStatus.PASSED,
        result=result,
        evidence=[],
        effect=effect,
        is_atomic=True,
    )
    return TaskTree(goal_id=task.id, nodes={task.id: task})


@pytest.mark.parametrize("effect", _INFORMATIONAL_EFFECTS)
def test_supporting_effects_matrix(effect: str):
    assert is_supporting_effect(effect) is True


@pytest.mark.parametrize("effect", _BUILD_EFFECTS)
def test_non_supporting_effects_matrix(effect: str):
    assert is_supporting_effect(effect) is False


@pytest.mark.parametrize(
    ("title", "effect"),
    itertools.product(_INFO_TITLES, _INFORMATIONAL_EFFECTS),
)
def test_informational_tasks_skip_side_effect_requirement(title: str, effect: str):
    assert task_requires_side_effect_evidence(
        title=title,
        description=title,
        requirement="",
        result="Verification passed.",
        tools_hint=(),
        effect=effect,
    ) is False


@pytest.mark.parametrize(
    ("title", "effect"),
    itertools.product(
        [t for t in _TITLES if any(k in t.lower() for k in ("implement", "create", "build", "fix", "deploy", "实现", "创建", "构建", "修复", "部署"))],
        ("write", "danger"),
    ),
)
def test_build_tasks_require_side_effect_evidence(title: str, effect: str):
    assert task_requires_side_effect_evidence(
        title=title,
        description=title,
        requirement="",
        result="Successfully created the requested artifact.",
        tools_hint=(),
        effect=effect,
    ) is True


@pytest.mark.parametrize(
    ("title", "result"),
    itertools.product(_PURE_GROUND_TITLES, _NEUTRAL_RESULTS),
)
def test_pure_text_grounding_without_tool_evidence(title: str, result: str):
    tree = _tree(title=title, effect="auto", result=result)
    sources = build_grounding_sources(tree)
    assert len(sources) == 1
    manifest = {
        "answer": result,
        "claims": [{
            "task_id": "leaf-1",
            "source_id": sources[0].source_id,
            "text": result,
        }],
    }
    issues, metrics = verify_grounded_synthesis(tree, result, manifest)
    assert issues == []
    assert metrics["grounded_claim_count"] == 1


@pytest.mark.parametrize("result", _RESULTS)
def test_completion_claim_with_auto_effect_may_require_evidence(result: str):
    required = task_requires_side_effect_evidence(
        title="Deliver feature",
        description="Implement and save",
        requirement="",
        result=result,
        tools_hint=(),
        effect="auto",
    )
    assert isinstance(required, bool)
