"""Spawn, cancel, message, and list primitives for isolated child agents.

These sit on the child-session manager. They do not construct a primary
AgentV2 and they do not copy the primary transcript.
"""

from __future__ import annotations

from protocol.subagents import ContextEnvelope, TaskRequest, TriggerKind

from ..session_runtime import current_session_id
from .prompt import FROM_MAIN_AGENT
from .registry_provider import get_manager

_MODES = frozenset({"sync", "async", "stream"})


def _manager():
    return get_manager()


def _caller_session_id() -> str:
    try:
        return str(current_session_id() or "").strip()
    except Exception:
        return ""


def _request(
    agent_id: str,
    prompt: str,
    *,
    parent_session_id: str,
    trigger: TriggerKind = TriggerKind.AUTOMATIC,
) -> TaskRequest:
    context = ContextEnvelope(parent_session_id=parent_session_id, task=prompt)
    return TaskRequest(
        parent_session_id=parent_session_id,
        agent_id=agent_id,
        prompt=prompt,
        context=context,
        trigger=trigger,
    )


async def spawn_subagent(
    agent_id: str,
    prompt: str,
    *,
    mode: str = "sync",
    parent_session_id: str = "",
    manager=None,
) -> str:
    """Start a child. sync waits; async and stream return the session id."""
    chosen = (mode or "sync").strip().lower()
    if chosen not in _MODES:
        return f"[spawn error: mode must be sync, async, or stream; got {mode}]"
    owner = manager or _manager()
    parent = parent_session_id or _caller_session_id() or owner.primary_session_id()
    request = _request(agent_id, prompt, parent_session_id=parent)
    try:
        if chosen == "sync":
            result = await owner.dispatch(request)
            status = result.status.value
            if result.error is not None:
                return (
                    f"[spawn sync {status}] session={result.child_session_id} "
                    f"{result.summary} — error: {result.error.message}"
                )
            return f"[spawn sync {status}] session={result.child_session_id} {result.summary}"
        session_id = owner.begin_child(request, stream=chosen == "stream")
    except Exception as exc:
        return f"[spawn error: {exc}]"
    if chosen == "stream":
        return (
            f"[spawn stream accepted] session={session_id} "
            "工具调用和进度记在该子会话的 child_session 事件上；"
            "父会话只在结束时收到摘要。"
        )
    return (
        f"[spawn async accepted] session={session_id} "
        "完成后摘要进入父会话收件箱，也可在 list_agents 里按该会话 ID 读取。"
    )


async def cancel_subagent(session_id: str, *, manager=None) -> str:
    owner = manager or _manager()
    try:
        return owner.cancel_child(session_id)
    except Exception as exc:
        return f"[cancel error: {exc}]"


async def send_message_to_subagent(
    session_id: str,
    text: str,
    *,
    sender_session_id: str = "",
    manager=None,
) -> str:
    """Route one note. The caller cannot choose a privilege source tag."""
    owner = manager or _manager()
    sender = (sender_session_id or _caller_session_id()).strip()
    target = (session_id or "").strip()
    sender_session = owner._find_session(sender) if sender else None
    try:
        if target.lower() in {"", "main", "primary"}:
            if sender_session is None:
                return f"unknown sender: {sender or 'missing'}"
            return owner.report_to_parent(sender_session.session_id, text)
        if sender_session is None:
            return owner.post_to_child(target, text, source=FROM_MAIN_AGENT)
        return owner.post_collaboration(
            target, text, sender_id=sender_session.session_id
        )
    except Exception as exc:
        return f"[send error: {exc}]"


def list_agents(*, manager=None) -> str:
    owner = manager or _manager()
    return owner.describe_agents()
