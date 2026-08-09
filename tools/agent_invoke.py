"""`@` mention trigger adapter — shared by CLI, OpenTUI, and Desktop.

B8 · Parses and dispatches ``@agent <prompt>`` user input. All permission,
session, and runtime decisions are delegated to ChildSessionManager — this
module NEVER decides permissions locally, creates sessions itself, runs a
model, or splices Primary history.

Entry name frozen: ``agent/invoke`` is the JSON-RPC method; this module
provides the shared parse + dispatch helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from protocol.subagents import (
    ContextEnvelope,
    TaskRequest,
    TriggerKind,
)


# ---------------------------------------------------------------------------
# Mention parsing
# ---------------------------------------------------------------------------

@dataclass
class ParsedMention:
    """Result of parsing an @mention input line."""

    agent_id: str
    prompt: str
    matched: bool = False

    @property
    def is_valid(self) -> bool:
        return self.matched and bool(self.agent_id)


# Valid agent id: lowercase start, alphanumeric/hyphen/underscore
_MENTION_RE = re.compile(r"^@([a-z][a-z0-9_-]{0,63})\b\s*(.*)$", re.DOTALL)


def parse_mention(user_input: str) -> ParsedMention:
    """Parse an ``@agent prompt`` input line.

    Returns ParsedMention with agent_id and remaining prompt. If the input
    does not start with a valid @mention, matched=False.
    """
    stripped = user_input.strip()
    match = _MENTION_RE.match(stripped)
    if not match:
        return ParsedMention(agent_id="", prompt=stripped)

    agent_id = match.group(1)
    prompt = match.group(2).strip()
    return ParsedMention(agent_id=agent_id, prompt=prompt, matched=True)


def list_mentionable_agents() -> list[dict]:
    """List agents visible in @ autocomplete.

    Only ``mode in {subagent, all}`` and ``hidden=false`` agents are listed.
    """
    from ..core.subagents.registry_provider import get_manager

    manager = get_manager()
    agents = manager.registry.list_visible()
    return [
        {
            "id": a.id,
            "description": a.description,
            "mode": a.mode.value,
        }
        for a in agents
    ]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def invoke_mention(
    agent_id: str,
    prompt: str,
    *,
    parent_session_id: str = "",
) -> object:
    """Dispatch a user @mention to a child session.

    Returns a TaskResult on success, or raises DispatchError subclasses on
    validation/permission/depth failures. The caller (CLI/Desktop/appserver)
    renders the error to the user.

    Raises:
        core.subagents.manager.AgentNotFoundError — unknown agent
        core.subagents.manager.ModeMismatchError — mode mismatch
        core.subagents.manager.FeatureDisabledError — feature disabled
        core.subagents.manager.DepthLimitExceededError — depth limit
    """
    from ..core.subagents.manager import ChildSessionManager, AgentNotFoundError, ModeMismatchError
    from ..core.subagents.registry_provider import get_manager

    manager: ChildSessionManager = get_manager()

    if not parent_session_id:
        parent_session_id = manager.primary_session_id()

    # Verify the agent exists and is mentionable BEFORE creating anything
    definition = manager.registry.get(agent_id)
    if definition is None:
        raise AgentNotFoundError(agent_id)

    if not definition.is_subagent_capable or definition.hidden:
        raise ModeMismatchError(
            agent_id,
            "agent is not mentionable (hidden or not subagent-capable)",
        )

    context = ContextEnvelope(
        parent_session_id=parent_session_id,
        task=prompt,
    )

    request = TaskRequest(
        parent_session_id=parent_session_id,
        agent_id=agent_id,
        prompt=prompt,
        context=context,
        trigger=TriggerKind.MENTION,
    )

    return await manager.dispatch(request)


async def invoke_mention_async(
    agent_id: str,
    prompt: str,
    *,
    parent_session_id: str = "",
) -> object:
    """Async entry for the @mention adapter."""
    return await invoke_mention(
        agent_id,
        prompt,
        parent_session_id=parent_session_id,
    )


def invoke_mention_sync(
    agent_id: str,
    prompt: str,
    *,
    parent_session_id: str = "",
) -> object:
    """Synchronous entry for callers without an event loop."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            invoke_mention(agent_id, prompt, parent_session_id=parent_session_id)
        )
    raise RuntimeError(
        "invoke_mention_sync cannot run inside an event loop; "
        "await invoke_mention_async"
    )
