"""Deferred tool catalog + on-demand schema disclosure (2026-10-13).

Problem: every registered tool's full JSON schema rides every LLM request
(~5k tokens for the 33 built-ins alone).  That was tolerable while the set
was our own stable core, but MCP servers can add tens to hundreds of tools
(GitHub MCP alone is ~90), multiplying prefix cost and burying the model in
flat choices.

Model (matches AI-Agents-in-Depth 图4-4 "层次化组织与主动工具发现"——
静态前缀只保留核心工具 + 工具搜索元工具；发现的工具 schema 以 tool_result
消息进入轨迹并保持原位，append-only 不破坏前缀缓存）:

1. Built-in core tools stay FROZEN in the request schema (byte-stable for
   the provider prefix cache).  Deferred tools (metadata["source"] in
   {"mcp", "plugin"}) never appear in the request schema at all.
2. ``tool_search`` is the single meta tool that exposes the deferred catalog:
   the model queries it, receives the full schema of matching tools inline in
   the tool result (which becomes ordinary trajectory history), and then
   invokes the discovered tool via the free-form ``<tool_call>`` envelope.
3. ``parse_deferred_tool_json_calls`` converts that envelope into the agent's
   normal dispatch dicts, so deferred calls flow through the standard
   approval/audit path of ToolOrchestrator — no second invoke channel.
4. Same-session dedup: schemas already returned once are not re-emitted in
   full (book rule "同一工具无需重复加载"); only a short availability hint
   is returned.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

# 模块级导入：core/tool_search.py 计入 P7 懒导入预算；langchain_core 在
# agent_v2 路径必然已加载，本模块不增加新成本。
from langchain_core.tools import StructuredTool

_logger = logging.getLogger(__name__)

DEFERRED_SOURCES = frozenset({"mcp", "plugin"})
TOOL_SEARCH_NAME = "tool_search"

TOOL_SEARCH_DESCRIPTION = (
    "Search the on-demand external tool catalog (MCP servers, plugins) by "
    "keyword. Always-on built-in tools are NOT in this catalog. Returns the "
    "full JSON schema for the best matches plus the exact <tool_call> "
    "envelope used to invoke one. If the tool you need is not in your "
    "built-in list, call this first."
)

_MAX_RESULTS_TEXT = 4000
_MAX_DESC_CHARS = 500


def is_deferred_tool(tool: Any) -> bool:
    """True for tools that live in the on-demand catalog, not the frozen schema."""
    meta = getattr(tool, "metadata", None)
    source = meta.get("source") if isinstance(meta, dict) else None
    return source in DEFERRED_SOURCES


def deferred_names(tools_by_name: dict[str, Any]) -> list[str]:
    return sorted(
        name for name, tool in tools_by_name.items() if is_deferred_tool(tool)
    )


def _trim(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "…[truncated]"


def _rank(tool: Any, query: str, query_tokens: list[str]) -> int:
    name = str(getattr(tool, "name", "") or "").lower()
    desc = str(getattr(tool, "description", "") or "").lower()
    query_norm = re.sub(r"[^a-z0-9_]+", " ", query.lower()).strip()
    score = 0
    if name == query_norm.replace(" ", "_") or name == query_norm:
        score += 120
    if query_norm and query_norm in name:
        score += 60
    if query_norm and query_norm in desc:
        score += 40
    token_hits = sum(1 for token in query_tokens if token in name)
    if query_tokens and token_hits == len(query_tokens):
        score += 30
    score += sum(5 for token in query_tokens if token in desc)
    return score


def _fenced_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class DeferredToolSearch:
    """Search facade over the deferred catalog with per-session dedup."""

    def __init__(self, get_registry: Callable[[], dict[str, Any]]) -> None:
        self._get_registry = get_registry
        self._exposed: set[str] = set()

    @property
    def exposed(self) -> frozenset[str]:
        return frozenset(self._exposed)

    def search(self, query: str, top_k: int = 5) -> str:
        registry = self._get_registry() or {}
        deferred = {k: v for k, v in registry.items() if is_deferred_tool(v)}
        if not deferred:
            return (
                "No deferred tools are available right now (no MCP server or "
                "plugin is connected)."
            )
        query_tokens = [
            token for token in re.split(r"[^a-z0-9_]+", (query or "").lower()) if token
        ]
        ranked = sorted(
            deferred.values(),
            key=lambda tool: (
                -_rank(tool, query or "", query_tokens),
                str(getattr(tool, "name", "") or ""),
            ),
        )
        try:
            top_k = max(1, min(10, int(top_k)))
        except (TypeError, ValueError):
            top_k = 5
        parts: list[str] = []
        fresh: list[Any] = []
        repeat: list[str] = []
        for tool in ranked:
            score = _rank(tool, query or "", query_tokens)
            if score <= 0:
                continue  # 0 分不匹配：宁可 no-match 也不乱暴露 schema
            name = str(getattr(tool, "name", "") or "")
            if name in self._exposed:
                repeat.append(name)
                continue
            fresh.append(tool)
            self._exposed.add(name)
            if len(fresh) >= top_k:
                break
        if not fresh and not repeat:
            return (
                f'No deferred tool matches "{_trim(query or "", 80)}". '
                "Try a different keyword, or list servers with the mcp status surface."
            )
        for name in repeat:
            parts.append(
                f"- {name} — ALREADY AVAILABLE (its schema was returned earlier "
                "in this conversation; call it now with the <tool_call> envelope)."
            )
        for tool in fresh:
            name = str(getattr(tool, "name", "") or "")
            metadata = getattr(tool, "metadata", None)
            raw_schema = (
                metadata.get("mcp_input_schema")
                if isinstance(metadata, dict)
                else None
            )
            schema_doc = raw_schema or getattr(tool, "args_schema", None) or {}
            block = (
                f"=== tool: {name} ===\n"
                f"description: {_trim(getattr(tool, 'description', ''), _MAX_DESC_CHARS)}\n"
                f"parameters: {_fenced_json(schema_doc)}\n"
                "call_format: emit exactly one envelope per call:\n"
                f'<tool_call>{{"name": "{name}", "arguments": {{...}}}}</tool_call>'
            )
            parts.append(block)
        text = "\n\n".join(parts)
        if len(text) > _MAX_RESULTS_TEXT:
            text = text[:_MAX_RESULTS_TEXT] + "\n…[search results truncated]"
        return text

    def as_tool(self) -> Any:
        """Return the StructuredTool adapter with frozen naming/description."""
        def _run(query: str, top_k: int = 5) -> str:
            """Search on-demand (MCP/plugin) tools by keyword and return schemas."""
            return self.search(query, top_k)

        return StructuredTool.from_function(
            func=_run,
            name=TOOL_SEARCH_NAME,
            description=TOOL_SEARCH_DESCRIPTION,
        )


_ENVELOPE_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_MAX_DEFERRED_CALLS = 8


def parse_deferred_tool_json_calls(
    answer: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Parse free-form ``<tool_call>`` envelopes from assistant content.

    Returns ``(calls, malformed)`` where ``calls`` are dispatch dicts in the
    normal loop shape (``{"name", "args", "id", "type"}``) and ``malformed``
    maps synthetic call ids to a human-readable error for envelopes that
    could not be decoded.  The plain-text (non-function-calling) channel is
    the contract introduced by ``tool_search`` discovery (book 图 4-4).
    """
    calls: list[dict[str, Any]] = []
    malformed: dict[str, str] = {}
    if not answer or "<tool_call" not in answer:
        return calls, malformed
    decoder = json.JSONDecoder()
    for seq, match in enumerate(_ENVELOPE_RE.finditer(answer)):
        if seq >= _MAX_DEFERRED_CALLS:
            break
        payload = match.group(1)
        call_id = f"defercall_{seq}"
        try:
            value, _end = decoder.raw_decode(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            malformed[call_id] = f"bad <tool_call> JSON: {exc}; re-emit a single valid envelope"
            calls.append({"name": "<invalid>", "args": {}, "id": call_id, "type": "tool_call"})
            continue
        if not isinstance(value, dict):
            malformed[call_id] = "<tool_call> payload must be a JSON object"
            calls.append({"name": "<invalid>", "args": {}, "id": call_id, "type": "tool_call"})
            continue
        name = str(value.get("name") or "").strip()
        args = value.get("arguments", {})
        if not name:
            malformed[call_id] = "<tool_call> is missing a non-empty 'name'"
            calls.append({"name": "<invalid>", "args": {}, "id": call_id, "type": "tool_call"})
            continue
        if not isinstance(args, dict):
            malformed[call_id] = "<tool_call>.arguments must be a JSON object"
            calls.append({"name": name, "args": {}, "id": call_id, "type": "tool_call"})
            continue
        calls.append({"name": name, "args": args, "id": call_id, "type": "tool_call"})
    return calls, malformed
