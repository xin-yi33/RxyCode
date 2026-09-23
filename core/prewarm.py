"""FX4 · isomorphic prewarm archives (PHASE-FIX §5 FX4).

Two archive slots per session_id. Both now write the frozen core tools
with thinking ON so a greeting hits the same provider prefix as an
encoding turn (S1 / 97% / user thinking-TTFT clock).
"""

from __future__ import annotations

import asyncio
from typing import Any

from RxyCode.RxyCode1_1_0.core.cache_policy import build_prewarm_signature
from RxyCode.RxyCode1_1_0.core.prefix_profile import digest_tools

PrewarmKind = str  # "chat" | "agent"

# Must match AgentV2.CHAT_STREAM_MAX_TOKENS_CAP / first user _raw_stream.
# max_tokens=1 is a different provider request and does not warm thinking-TTFT.
PREWARM_MAX_TOKENS = 4096

#: Serializes the temporary _capabilities swap so the chat slot (thinking
#: off) and the agent slot (thinking on) never race on the shared agent.
_PREWARM_CAPS_LOCK = asyncio.Lock()


def _mcp_signature(agent: Any) -> str:
    import json

    try:
        cfg = getattr(agent, "_cfg", None) or {}
        servers = cfg.get("mcpServers") or {}
        if not servers:
            return ""
        return json.dumps(
            servers,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except Exception:  # pragma: no cover - config shape varies
        return ""


def core_tools_for(agent: Any, kind: PrewarmKind):
    """Tools bound to the prewarm request.

    Both slots now send the frozen core tool list with thinking ON so a
    greeting hits the same provider prefix as an encoding turn (S1 / 97%).
    """
    fn = getattr(agent, "_get_core_tools", None)
    if fn is None:
        return None
    return fn()


def prewarm_signature(agent: Any, kind: PrewarmKind = "agent") -> str:
    """Signature for one archive slot: model/cwd/mcp/kind/thinking/tools."""
    model = str((getattr(agent, "model_config", {}) or {}).get("model_name") or "")
    cwd = str(getattr(agent, "_workspace_root", "") or "")
    tools = core_tools_for(agent, kind)
    return build_prewarm_signature(
        model=model,
        cwd=cwd,
        mcp=_mcp_signature(agent),
        kind=kind,
        thinking_enabled=True,
        tools_digest=digest_tools(tools),
    )


def session_prewarm_messages(agent: Any, kind: PrewarmKind = "agent") -> list:
    """Prewarm messages for one slot: same S1 + user wrapping as ``_fast_reply``.

    Fresh System + Human only — never append to a live transcript (that would
    leak the ``warm`` suffix into the first real user turn).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from RxyCode.RxyCode1_1_0.core.prompts.registry import (
        build_user_message,
        get_system_prompt,
    )

    variant = "default"
    fn = getattr(agent, "_prompt_variant", None)
    if fn is not None:
        try:
            variant = fn()
        except Exception:  # pragma: no cover
            variant = "default"
    system = ""
    try:
        system = get_system_prompt(variant=variant, tools=False)
    except Exception:  # pragma: no cover
        system = ""
    user_msg = build_user_message("", "warm", "")
    msgs: list = []
    if system:
        msgs.append(SystemMessage(content=system))
    msgs.append(HumanMessage(content=user_msg))
    return msgs


def keepalive_messages(agent: Any) -> list:
    """FX5: keep-alive rides the frozen agent archive — same system + core
    tools as the agent prewarm slot, user text ``keep-alive``. Never a
    bare HumanMessage body (that would be a third prefix)."""
    from langchain_core.messages import HumanMessage

    msgs = session_prewarm_messages(agent, "agent")
    out: list = []
    for m in msgs:
        if m.__class__.__name__ == "HumanMessage":
            out.append(HumanMessage(content="keep-alive"))
        else:
            out.append(m)
    return out


def _chunk_has_thinking(agent: Any, chunk: Any) -> bool:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return False
    delta = getattr(choices[0], "delta", None)
    extract = getattr(agent, "_provider_reasoning", None)
    if callable(extract):
        try:
            return bool(extract(delta))
        except Exception:  # pragma: no cover
            return False
    return bool(getattr(delta, "reasoning_content", None) or "")


async def prewarm_archive(agent: Any, kind: PrewarmKind) -> None:
    """Send one Session.prompt-shaped prewarm and stop at first thinking token.

    Thinking stays ON, frozen core tools, effort=fast, max_tokens matches
    the first user turn. Consuming until the first reasoning byte writes the
    same provider prefix the user clock measures; do not use max_tokens=1.
    """
    raw_stream = getattr(agent, "_raw_stream", None)
    if raw_stream is None:
        return
    msgs = session_prewarm_messages(agent, kind)
    tools = core_tools_for(agent, kind)
    was_disabled = bool(getattr(agent, "_thinking_disabled_this_turn", False))
    cfg = getattr(agent, "model_config", None)
    if isinstance(cfg, dict) and not cfg.get("effort"):
        agent.model_config = dict(cfg)
        agent.model_config["effort"] = "fast"
    async with _PREWARM_CAPS_LOCK:
        agent._thinking_disabled_this_turn = False
        agent._prewarm_request_active = True
        try:
            async for chunk in raw_stream(
                msgs,
                tools=tools,
                max_tokens=PREWARM_MAX_TOKENS,
                through_breaker=False,
            ):
                if _chunk_has_thinking(agent, chunk):
                    break
        finally:
            agent._prewarm_request_active = False
            agent._thinking_disabled_this_turn = was_disabled
    confirm = getattr(agent, "_confirm_prewarm", None)
    if confirm is not None:
        confirm(kind)


async def prewarm_all(agent: Any) -> None:
    """Warm both archive slots in parallel (chat + agent)."""
    await asyncio.gather(
        prewarm_archive(agent, "chat"),
        prewarm_archive(agent, "agent"),
    )
