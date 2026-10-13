"""Deferred tool catalog + on-demand schema disclosure (2026-10-13, K例复审修订).

Design (AI-Agents-in-Depth §4.4 图 4-4): the request schema is a two-tier
frozen core (built-ins + the ``tool_search`` meta adapter).  Deferred tools
(``metadata["source"] in {"mcp","plugin"}`` and explicitly deferred rare
built-ins) never enter the request schema; the model discovers them through
``tool_search``, whose results carry full schemas inline in the tool-result
message (trajectory append-only).

K例复审修订点：

* 搜索结果按**完整项**打包（P1）：若有超出文本预算的命中，完整截断在块
  边界并明示剩余数量——绝不返回半截 schema 再把半成品标记为"已暴露"。
* 暴露记录绑定 ``(session_id, schema_hash)``（P1）：新会话、同名 schema
  更新都可以重新暴露，不会被陈旧的"已加载"记录污染。
* 首次发现消息带固定 pin 标记，普通压缩（microcompact 墓碑化）跳过它们（P1）。
* 查询分词 CJK 友好（P2）：中文短语直接子串命中，单字加权，修复
  "天气"查不到"查询城市天气"。

新发现的工具以 ``<tool_call>`` 自由形式派发（同一执行路径），解析器不维护
会话状态，调用方传入 ``start`` 保证跨轮调用 ID 唯一（P2）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

# 模块级导入：core/tool_search.py 计入 P7 懒导入预算；langchain_core 在
# agent_v2 路径必然已加载，mcp.tool_manifest 复用其 sha256 做 schema 版本绑定。
from langchain_core.tools import StructuredTool

from RxyCode.RxyCode1_1_0.mcp.tool_manifest import signature_for_tools

_logger = logging.getLogger(__name__)

DEFERRED_SOURCES = frozenset({"mcp", "plugin"})

#: 原生内置但低频/高危的安装类工具——按需加载而不是常驻冻结集（K3 复审
#: 「33 个内置不是高频筛选集」的落法）。
DEFERRED_BUILTIN_TOOL_NAMES = frozenset(
    {"download_skill", "download_mcp", "team_install"}
)

TOOL_SEARCH_NAME = "tool_search"

TOOL_SEARCH_DESCRIPTION = (
    "Search the on-demand external tool catalog (MCP servers, plugins, "
    "rare installer tools) by keyword — supports Chinese and English. "
    "Always-on built-in tools are NOT in this catalog. Returns the full "
    "JSON schema for the best matches plus the exact <tool_call> envelope "
    "used to invoke one. If the tool you need is not in your built-in "
    "list, call this first."
)

#: 普通压缩（microcompact）识别首次发现消息的固定标记：必须压在原位置。
DISCOVERY_PIN_MARKER = "[deferred tool disclosure — keep this message and its position]"

_MAX_RESULTS_TEXT = 4000
_MAX_DESC_CHARS = 500


def is_deferred_tool(tool: Any) -> bool:
    """True for tools that live in the on-demand catalog, not the frozen schema."""
    name = str(getattr(tool, "name", "") or "")
    if name and name in DEFERRED_BUILTIN_TOOL_NAMES:
        return True
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


def _fenced_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
    )


def _split_tokens(query: str) -> tuple[list[str], list[str], str]:
    """Return (ascii_tokens, cjk_chars, lowered_phrase)."""
    ascii_tokens = [
        token
        for token in re.split(r"[^a-z0-9_]+", (query or "").lower())
        if token
    ]
    cjk_chars = [c for c in (query or "") if _is_cjk(c)]
    phrase = (query or "").strip().lower()
    return ascii_tokens, cjk_chars, phrase


def _rank(tool: Any, query: str) -> int:
    name = str(getattr(tool, "name", "") or "").lower()
    desc = str(getattr(tool, "description", "") or "").lower()
    ascii_tokens, cjk_chars, phrase = _split_tokens(query)
    query_norm = " ".join(ascii_tokens)
    score = 0
    if name == query_norm.replace(" ", "_") or name == query_norm:
        score += 120
    if query_norm and query_norm in name:
        score += 60
    if phrase and phrase in name:
        score += 80
    if phrase and phrase in desc:
        score += 50
    token_hits = sum(1 for token in ascii_tokens if token in name)
    if ascii_tokens and token_hits == len(ascii_tokens):
        score += 30
    score += sum(5 for token in ascii_tokens if token in desc)
    # CJK：查询短语里每个汉字在名称/描述中出现即加权（"天气"⇒"查询城市天气"）。
    score += sum(3 for ch in cjk_chars if ch in name or ch in desc)
    return score


class DeferredToolSearch:
    """Search facade over the deferred catalog with (session, schema_hash) dedup."""

    def __init__(
        self,
        get_registry: Callable[[], dict[str, Any]],
        get_session_id: Callable[[], str] | None = None,
    ) -> None:
        self._get_registry = get_registry
        self._get_session_id = get_session_id or (lambda: "")
        # name → (session_id, schema_hash):context 是会场票根，不是全局记账。
        self._exposed: dict[str, tuple[str, str]] = {}

    @property
    def exposed(self) -> frozenset[str]:
        return frozenset(self._exposed)

    def _schema_hash(self, name: str, tool: Any) -> str:
        return signature_for_tools({name: tool}).get(name, "")

    def _is_already_exposed(self, name: str, tool: Any) -> bool:
        record = self._exposed.get(name)
        if record is None:
            return False
        session, digest = record
        return session == self._get_session_id() and digest == self._schema_hash(name, tool)

    def _mark_exposed(self, name: str, tool: Any) -> None:
        self._exposed[name] = (self._get_session_id(), self._schema_hash(name, tool))

    def search(self, query: str, top_k: int = 5) -> str:
        registry = self._get_registry() or {}
        deferred = {k: v for k, v in registry.items() if is_deferred_tool(v)}
        if not deferred:
            return (
                "No deferred tools are available right now (no MCP server or "
                "plugin is connected)."
            )
        ranked = sorted(
            deferred.values(),
            key=lambda tool: (
                -_rank(tool, query or ""),
                str(getattr(tool, "name", "") or ""),
            ),
        )
        try:
            top_k = max(1, min(10, int(top_k)))
        except (TypeError, ValueError):
            top_k = 5

        candidates: list[tuple[Any, bool]] = []  # (tool, already_exposed)
        for tool in ranked:
            if _rank(tool, query or "") <= 0:
                continue
            name = str(getattr(tool, "name", "") or "")
            candidates.append((tool, self._is_already_exposed(name, tool)))
        if not candidates:
            return (
                f'No deferred tool matches "{_trim(query or "", 80)}". '
                "Try Chinese or English keywords, or list servers via the mcp status surface."
            )

        parts: list[str] = []
        emitted = 0
        remainder = 0
        for tool, already in candidates:
            name = str(getattr(tool, "name", "") or "")
            if already:
                block = (
                    f"- {name} — ALREADY AVAILABLE (its schema was returned earlier "
                    "in this conversation; call it now with the <tool_call> envelope; "
                    "a normal function call to it will NOT be executed)."
                )
            else:
                if emitted >= top_k:
                    remainder += 1
                    continue
                already = False
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
                    f"IMPORTANT: '{name}' is NOT in your function-calling tool list. "
                    "A normal tool call to it will NOT be executed. To invoke it, "
                    "output this envelope as plain text (exactly one per call):\n"
                    f'<tool_call>{{"name": "{name}", "arguments": {{...}}}}</tool_call>\n'
                    f"{DISCOVERY_PIN_MARKER}"
                )
            # P1: 按完整项打包——预算不足就不塞这一块，也绝不标记已暴露。
            joined = "\n\n".join([*parts, block])
            if len(joined) > _MAX_RESULTS_TEXT:
                remainder += 1
                continue
            parts.append(block)
            if not already:
                self._mark_exposed(name, tool)
                emitted += 1
        if remainder:
            parts.append(
                f"…{remainder} more match(es) withheld; narrow the query to reveal them "
                "(never emitted as a partial schema)."
            )
        if not parts:
            return (
                "Found matches but none fit the result budget; narrow the query "
                "(one named tool at a time)."
            )
        return "\n\n".join(parts)

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
_ORPHAN_TAIL_RE = re.compile(r"<tool_call(?![\s\S]*</tool_call>)", re.DOTALL)
_MAX_DEFERRED_CALLS = 8


def parse_deferred_tool_json_calls(
    answer: str,
    *,
    start: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Parse free-form ``<tool_call>`` envelopes from assistant content.

    Returns ``(calls, malformed)`` where ``calls`` are dispatch dicts in the
    normal loop shape (``{"name", "args", "id", "type"}``) and ``malformed``
    maps synthetic call ids to a human-readable error for envelopes that
    could not be decoded.  ``start`` makes ids unique ACROSS ROUNDS (P2):
    pass the running per-session counter so ids never repeat (message
    correlation and compaction protection key off them).  An unterminated
    ``<tool_call>`` tail is reported explicitly instead of leaking to the
    final answer as if it were plain text.
    """
    calls: list[dict[str, Any]] = []
    malformed: dict[str, str] = {}
    if not answer or "<tool_call" not in answer:
        return calls, malformed
    decoder = json.JSONDecoder()
    seq = start
    for match in _ENVELOPE_RE.finditer(answer):
        if seq - start >= _MAX_DEFERRED_CALLS:
            break
        payload = match.group(1)
        call_id = f"defercall_{seq}"
        seq += 1
        try:
            value, _end = decoder.raw_decode(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            malformed[call_id] = (
                f"bad <tool_call> JSON: {exc}; re-emit a single valid envelope"
            )
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

    consumed_end = answer.rfind("</tool_call>")
    if _ORPHAN_TAIL_RE.search(answer[consumed_end + 1 :]):
        orphan_id = f"defercall_{seq}"
        malformed[orphan_id] = (
            "unterminated <tool_call> envelope: the call was NOT executed; "
            "re-emit one complete, closed envelope as the only tool call this round"
        )
        calls.append({"name": "<invalid>", "args": {}, "id": orphan_id, "type": "tool_call"})
    return calls, malformed
