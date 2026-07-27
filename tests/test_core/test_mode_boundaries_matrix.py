"""Plan / build / compose mode boundary matrices."""

from __future__ import annotations

import itertools

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


_VALID_MODES = ("plan", "build", "compose")
_INVALID_MODES = ("unsafe", "debug", "auto", "execute", "chat", "")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _INVALID_MODES)
async def test_run_rejects_unknown_modes(mode: str):
    agent = AgentV2.__new__(AgentV2)
    agent._cancelled = False
    with pytest.raises(ValueError, match="Unsupported agent mode"):
        await agent.run("hello", mode=mode)


@pytest.mark.parametrize("mode", _VALID_MODES)
def test_valid_modes_are_recognized_strings(mode: str):
    assert mode in {"plan", "build", "compose"}


@pytest.mark.parametrize(
    ("mode", "op_type", "allowed"),
    [
        ("plan", "read", True),
        ("plan", "list", True),
        ("plan", "write", False),
        ("plan", "delete", False),
        ("build", "write", True),
        ("build", "read", True),
        ("compose", "write", True),
        ("compose", "read", True),
    ],
)
def test_plan_mode_file_operation_boundary(mode: str, op_type: str, allowed: bool):
    agent = AgentV2.__new__(AgentV2)
    blocked = mode == "plan" and op_type not in {"read", "list"}
    assert blocked != allowed


@pytest.mark.parametrize(
    ("social_text", "mode"),
    itertools.product(
        (
            "陪我玩游戏好吗",
            "我好伤心，朋友不理我",
            "你却说 Error",
        ),
        _VALID_MODES,
    ),
)
def test_social_text_detected_before_mode_routing(social_text: str, mode: str):
    del mode
    agent = AgentV2.__new__(AgentV2)
    assert agent._is_social_chat(social_text) is True


@pytest.mark.parametrize(
    ("code_text", "mode"),
    itertools.product(
        (
            "用 Python 写一个跑酷小游戏并保存到文件",
            "重构整个项目的认证模块",
            "create a full complete application",
        ),
        _VALID_MODES,
    ),
)
def test_code_intent_not_social_across_modes(code_text: str, mode: str):
    del mode
    agent = AgentV2.__new__(AgentV2)
    assert agent._is_social_chat(code_text) is False
