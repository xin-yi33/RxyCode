"""layer=unit/module F4-4 rewind scope 行为表。"""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from appserver.checkpoint_rewind import CheckpointRewindError
from appserver.server import AppServer


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    return tmp_path


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


def _fake_prefix_agent():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._agent_prefix_messages = [
        SystemMessage(content="S1"),
        HumanMessage(content="first prompt"),
        AIMessage(content="a1"),
        HumanMessage(content="second prompt"),
        AIMessage(content="a2"),
    ]
    return agent


async def _make_server(tmp_path, monkeypatch):
    async def capture(message: dict) -> None:
        capture.sent.append(message)

    capture.sent = []  # type: ignore[attr-defined]

    async def no_worker(**kwargs):
        return None

    monkeypatch.setattr("appserver.server.write_message", capture)
    root = _workspace(tmp_path)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    monkeypatch.setattr(server, "_run_prompt", no_worker)
    session = server._sessions.create(root, title="f44")
    await _prompt(server, session.session_id, "first prompt", 10)
    await _prompt(server, session.session_id, "second prompt", 11)
    return server, session, root, capture


def _rewind_call(server, session, *, checkpoint_id: str, scope: str, prefix_agent):
    return server._checkpoint_rewind.rewind(
        checkpoint_id=checkpoint_id,
        confirm=True,
        session_id=session.session_id,
        scope=scope,
        prefix_rewinder=(
            None
            if prefix_agent is None
            else (lambda target: prefix_agent._rewind_agent_prefix(
                keep_human_messages=1
            ))
        ),
    )


@pytest.mark.asyncio
async def test_u_f4_4_03_scope_code_byte_equal_current_behavior(tmp_path, monkeypatch):
    """layer=unit U-F4-4-03
    scope=code（默认）= 现状：git restore + 事件投影；prefix 不动、prefix_truncated_messages == 0。
    """
    server, session, root, capture = await _make_server(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="before-edit"
    )
    (root / "a.txt").write_text("two\n", encoding="utf-8")
    await _prompt(server, session.session_id, "third prompt", 12)
    agent = _fake_prefix_agent()
    before_prefix_len = len(agent._agent_prefix_messages)
    result = _rewind_call(server, session, checkpoint_id=named["checkpoint_id"], scope="code", prefix_agent=agent)
    assert result["scope"] == "code"
    assert result["prefix_truncated_messages"] == 0
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("one")
    assert len(agent._agent_prefix_messages) == before_prefix_len  # 前缀不动
    assert result["truncated_messages"] >= 1                       # 事件投影仍发生（现状）


@pytest.mark.asyncio
async def test_u_f4_4_04_scope_conversation_prefix_only(tmp_path, monkeypatch):
    """layer=unit U-F4-4-04
    scope=conversation：工作区不回滚；事件投影 + prefix 截断到最近 human 边界。
    """
    server, session, root, capture = await _make_server(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="before-edit"
    )
    (root / "a.txt").write_text("two\n", encoding="utf-8")
    await _prompt(server, session.session_id, "third prompt", 12)
    agent = _fake_prefix_agent()
    result = _rewind_call(server, session, checkpoint_id=named["checkpoint_id"], scope="conversation", prefix_agent=agent)
    assert result["scope"] == "conversation"
    assert result["prefix_truncated_messages"] == 2       # H(second)+A2 被截
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("two")  # 工作区不动
    assert agent._agent_prefix_messages[-1].content == "a1"
    assert result["truncated_messages"] >= 1              # 事件投影发生


@pytest.mark.asyncio
async def test_u_f4_4_05_scope_both_and_invalid_scope(tmp_path, monkeypatch):
    """layer=unit U-F4-4-05
    scope=both：工作区与对话都回滚；非法 scope 拒绝（match="scope"）。
    """
    server, session, root, capture = await _make_server(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="before-edit"
    )
    (root / "a.txt").write_text("two\n", encoding="utf-8")
    await _prompt(server, session.session_id, "third prompt", 12)
    agent = _fake_prefix_agent()
    result = _rewind_call(server, session, checkpoint_id=named["checkpoint_id"], scope="both", prefix_agent=agent)
    assert result["scope"] == "both"
    assert result["restored_files"] >= 1
    assert result["prefix_truncated_messages"] == 2
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("one")
    assert agent._agent_prefix_messages[-1].content == "a1"
    with pytest.raises(CheckpointRewindError, match="scope"):
        _rewind_call(server, session, checkpoint_id=named["checkpoint_id"], scope="everything", prefix_agent=agent)


@pytest.mark.asyncio
async def test_mo_f4_4_01_rewind_then_followup_forgets_rolled_back_turn(tmp_path, monkeypatch):
    """layer=module MO-F4-4-01
    回滚后续聊：prefix 里不再出现被回滚段（"second prompt"），而事件投影侧同样不可见。
    """
    server, session, root, capture = await _make_server(tmp_path, monkeypatch)
    named = server._checkpoint_rewind.snapshot_create(
        session_id=session.session_id, name="before-edit"
    )
    agent = _fake_prefix_agent()
    _rewind_call(server, session, checkpoint_id=named["checkpoint_id"], scope="conversation", prefix_agent=agent)
    kept_texts = [m.content for m in agent._agent_prefix_messages]
    assert "second prompt" not in kept_texts
    items = server._checkpoint_rewind.visible_items(session.session_id)
    texts = [str((row.get("params") or {}).get("text") or "") for row in items]
    assert "first prompt" in texts
    assert "third prompt" not in texts
