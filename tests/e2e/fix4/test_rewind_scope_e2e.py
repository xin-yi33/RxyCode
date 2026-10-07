"""layer=e2e E-F4-E2E-04 rewind 三 scope。"""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from appserver.server import AppServer

pytestmark = pytest.mark.e2e


async def _prompt(server: AppServer, session_id: str, text: str, req_id: int) -> None:
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {"session_id": session_id, "text": text},
        }
    )
    for task in list(server._prompt_tasks):
        await task


async def _rig(tmp_path: Path, monkeypatch):
    """setup：真 AppServer(stub) + 真临时工作区文件 + 同形前缀 agent。"""
    async def capture(message: dict) -> None:
        capture.sent.append(message)

    capture.sent = []  # type: ignore[attr-defined]

    async def no_worker(**kwargs):
        return None

    monkeypatch.setattr("appserver.server.write_message", capture)
    root = tmp_path / "ws"
    root.mkdir()
    (root / "code.txt").write_text("v1\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    monkeypatch.setattr(server, "_run_prompt", no_worker)
    session = server._sessions.create(root, title="f4-e2e04")
    await _prompt(server, session.session_id, "turn one", 1)
    await _prompt(server, session.session_id, "turn two", 2)

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._agent_prefix_messages = [
        SystemMessage(content="S1-E2E"),
        HumanMessage(content="turn one"),
        AIMessage(content="answer one"),
        HumanMessage(content="turn two"),
        AIMessage(content="answer two"),
    ]
    return server, session, root, agent


def _rewind(server, session, *, checkpoint_id: str, scope: str, agent):
    return server._checkpoint_rewind.rewind(
        checkpoint_id=checkpoint_id,
        confirm=True,
        session_id=session.session_id,
        scope=scope,
        prefix_rewinder=lambda target: agent._rewind_agent_prefix(keep_human_messages=1),
    )


def _visible_texts(server, session) -> list[str]:
    items = server._checkpoint_rewind.visible_items(session.session_id)
    return [str((row.get("params") or {}).get("text") or "") for row in items]


@pytest.mark.asyncio
async def test_e2e_f4_04a_scope_code_only(tmp_path, monkeypatch):
    """layer=e2e E-F4-E2E-04（code）
    扰动：改 code.txt → v2，加第三轮 turn。断言（三断言）：git 回到 v1、
    事件投影隐藏第三轮、前缀长度不变（5）且仍记得 turn two。
    """
    server, session, root, agent = await _rig(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="cp"
    )
    (root / "code.txt").write_text("v2\n", encoding="utf-8")
    await _prompt(server, session.session_id, "turn three", 3)
    result = _rewind(server, session, checkpoint_id=named["checkpoint_id"], scope="code", agent=agent)
    assert result["scope"] == "code"
    assert (root / "code.txt").read_text(encoding="utf-8") == "v1\n"
    texts = _visible_texts(server, session)
    assert "turn one" in texts and "turn two" in texts
    assert "turn three" not in texts
    assert len(agent._agent_prefix_messages) == 5
    assert agent._agent_prefix_messages[-1].content == "answer two"


@pytest.mark.asyncio
async def test_e2e_f4_04b_scope_conversation_only(tmp_path, monkeypatch):
    """layer=e2e E-F4-E2E-04（conversation）
    断言（三断言）：git 保持 v2 不动、事件投影隐藏、前缀截到第一条 human 边界（3 条），
    回滚后续聊不再"记得" turn two。
    """
    server, session, root, agent = await _rig(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="cp"
    )
    (root / "code.txt").write_text("v2\n", encoding="utf-8")
    await _prompt(server, session.session_id, "turn three", 3)
    result = _rewind(server, session, checkpoint_id=named["checkpoint_id"], scope="conversation", agent=agent)
    assert result["prefix_truncated_messages"] == 2
    assert (root / "code.txt").read_text(encoding="utf-8") == "v2\n"
    texts = _visible_texts(server, session)
    assert "turn one" in texts and "turn two" in texts and "turn three" not in texts
    contents = [m.content for m in agent._agent_prefix_messages]
    assert contents == ["S1-E2E", "turn one", "answer one"]
    assert "turn two" not in contents                 # 回滚后被"遗忘"
    followup = agent._continue_agent_prefix("S1-E2E", "turn four follow-up")
    assert followup[0].content == "S1-E2E"
    assert "turn two" not in [m.content for m in followup]


@pytest.mark.asyncio
async def test_e2e_f4_04c_scope_both(tmp_path, monkeypatch):
    """layer=e2e E-F4-E2E-04（both）
    断言（三断言）：git 回到 v1、投影隐藏、前缀截断同时发生；restore_point 仍落盘。
    """
    server, session, root, agent = await _rig(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="cp"
    )
    (root / "code.txt").write_text("v2\n", encoding="utf-8")
    await _prompt(server, session.session_id, "turn three", 3)
    result = _rewind(server, session, checkpoint_id=named["checkpoint_id"], scope="both", agent=agent)
    assert result["scope"] == "both"
    assert (root / "code.txt").read_text(encoding="utf-8") == "v1\n"
    texts = _visible_texts(server, session)
    assert "turn three" not in texts
    assert result["prefix_truncated_messages"] == 2
    assert len(agent._agent_prefix_messages) == 3
    listed = server._reviews.list_checkpoints(session.session_id)
    ids = {item["checkpoint_id"] for item in listed}
    assert named["checkpoint_id"] in ids
    assert result["restore_point"] in ids
