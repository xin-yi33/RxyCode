"""Deferred tool catalog + on-demand schema disclosure (2026-10-13, K例复审修订).

Design (AI-Agents-in-Depth §4.4 图 4-4): the request schema is a two-tier
frozen core (built-ins + the ``tool_search`` meta adapter, registered at
agent start).  Deferred tools (``metadata["source"] in {"mcp","plugin"}``
and explicitly deferred rare built-ins) never enter the request schema; the
model discovers them through ``tool_search``.  The catalog is one flat
keyword list (``mcp_{server}_{tool}``), not a server-then-tool walk.
Results carry full schemas inline in the tool-result message (trajectory
append-only).  Generic output dedupe and the 2000-character tool-output
cut do not rewrite a full discovery.

K例复审修订点：

* 搜索结果按**完整项**打包（P1）：若有超出文本预算的命中，完整截断在块
  边界并明示剩余数量——绝不返回半截 schema 再把半成品标记为"已暴露"。
* 暴露记录按实际上下文加 ``schema_hash``（P1）：同一上下文不重复给
  schema；Executor 的每个隔离子任务是新上下文，必须重新得到定义。
  不按名字全局清空，并发任务各自保留自己的记录。
* 首次发现消息带固定 pin 标记，普通压缩（microcompact 墓碑化）跳过它们（P1）。
* 查询分词 CJK 友好（P2）：中文短语直接子串命中，单字加权，修复
  "天气"查不到"查询城市天气"。

新发现的工具以 ``<tool_call>`` 自由形式派发（同一执行路径），解析器不维护
会话状态，调用方传入 ``start`` 保证跨轮调用 ID 唯一（P2）。
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
import weakref
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

#: 当前执行上下文。未设置时退回 session_id（Fast 路径同一会话共享历史）。
#: Executor 每个隔离子任务设置自己的值；contextvars 按任务隔离，不清全局表。
_disclosure_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rxycode_disclosure_context",
    default=None,
)


def push_disclosure_context(context_id: str | None = None):
    """Bind later tool_search calls to one message context. Returns the reset token."""
    return _disclosure_context.set(context_id or uuid.uuid4().hex)


def reset_disclosure_context(token) -> None:
    _disclosure_context.reset(token)


# 活着的 facade。隔离任务结束时按 context id 删记录，不把表清成空。
_live_facades: weakref.WeakSet = weakref.WeakSet()


def current_disclosure_context_id() -> str | None:
    return _disclosure_context.get()


def release_finished_disclosure_context(context_id: str | None) -> None:
    """Drop one finished isolated context. Fast keys and other tasks stay."""
    if not context_id:
        return
    for facade in list(_live_facades):
        facade.release_context(context_id)


_DISCOVERY_TOOL_RE = re.compile(r"^=== tool: (.+?) ===\s*$", re.MULTILINE)


def discovery_tool_names(messages) -> set[str]:
    """Tool names whose full schema disclosure is still inside these messages."""
    names: set[str] = set()
    for message in messages or []:
        text = _message_text(message)
        if DISCOVERY_PIN_MARKER not in text:
            continue
        names.update(
            name.strip()
            for name in _DISCOVERY_TOOL_RE.findall(text)
            if name.strip()
        )
    return names


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "\n".join(parts)
    return str(content or "")

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
#: 单项完整块硬上限：只有这一个命中时可以完整放行（K3-2 #6
#: 「单个大 schema 永远发现不了」——不返回半截定义，允许稍大但完整的单块）。
_MAX_SINGLE_RESULT_TEXT = 12000
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


def _normalize_args_schema(value: Any) -> dict:
    """#5：把参数 schema 归一成 JSON Schema 字典。

    优先级：metadata 里存的原始 MCP schema（dict）> pydantic 类的
    ``model_json_schema()`` > dict 原样 > 空。旧实现把 pddantic 类对象直接
    ``default=str`` 序列化成类 repr，模型只能猜参数（K3-2 #5）。
    """
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    model_json_schema = getattr(value, "model_json_schema", None)
    if callable(model_json_schema):
        try:
            schema = model_json_schema()
            if isinstance(schema, dict):
                return schema
        except Exception:  # noqa: BLE001 — degrate to empty, message stays visible
            pass
    return {}


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
        get_message_context_id: Callable[[], str] | None = None,
    ) -> None:
        self._get_registry = get_registry
        self._get_session_id = get_session_id or (lambda: "")
        # Fast 路径没有 ContextVar。标识跟着持久消息上下文走，清空或重建历史时
        # 由调用方换成新值。不在这里清整张表，避免扫掉并发任务的记录。
        self._get_message_context_id = get_message_context_id
        # name → {context_id: schema_hash}。只记当前上下文，不覆盖其他任务。
        self._exposed: dict[str, dict[str, str]] = {}
        _live_facades.add(self)

    def release_context(self, context_key: str) -> None:
        """删除一个已经结束的上下文。别的 key 保留。"""
        if not context_key:
            return
        empty: list[str] = []
        for name, bucket in self._exposed.items():
            bucket.pop(context_key, None)
            if not bucket:
                empty.append(name)
        for name in empty:
            del self._exposed[name]

    def revoke_names(self, names: set[str] | frozenset[str]) -> None:
        """局部回退：只撤销当前上下文里这些工具的暴露记录。"""
        key = self._context_key()
        for name in names:
            bucket = self._exposed.get(name)
            if not bucket:
                continue
            bucket.pop(key, None)
            if not bucket:
                del self._exposed[name]

    def _context_key(self) -> str:
        bound = _disclosure_context.get()
        if bound:
            return bound
        session = self._get_session_id()
        getter = self._get_message_context_id
        message_ctx = str(getter() or "") if getter is not None else ""
        if message_ctx:
            return f"session:{session}:msg:{message_ctx}"
        return f"session:{session}"

    @property
    def exposed(self) -> frozenset[str]:
        key = self._context_key()
        return frozenset(
            name for name, bucket in self._exposed.items() if key in bucket
        )

    def _schema_hash(self, name: str, tool: Any) -> str:
        return signature_for_tools({name: tool}).get(name, "")

    def _is_already_exposed(self, name: str, tool: Any) -> bool:
        bucket = self._exposed.get(name)
        if not bucket:
            return False
        digest = bucket.get(self._context_key())
        return digest is not None and digest == self._schema_hash(name, tool)

    def _mark_exposed(self, name: str, tool: Any) -> None:
        bucket = self._exposed.setdefault(name, {})
        bucket[self._context_key()] = self._schema_hash(name, tool)

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
                schema_doc = _normalize_args_schema(
                    raw_schema if raw_schema is not None
                    else getattr(tool, "args_schema", None)
                )
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
            # K3-2 #6：唯一命中时允许一个**完整**单块超过共享预算到硬上限
            # （否则 4k 预算会让单个 schema 永远发现不了）；半块永不返回。
            joined = "\n\n".join([*parts, block])
            if len(joined) > _MAX_RESULTS_TEXT:
                single_fresh = not parts and not already
                if not (single_fresh and len(block) <= _MAX_SINGLE_RESULT_TEXT):
                    remainder += 1
                    continue
            parts.append(block)
            if not already:
                self._mark_exposed(name, tool)
                emitted += 1
        if remainder:
            parts.append(
                f"…{remainder} more match(es) withheld; narrow the query to reveal them "
                "(never emitted as a partial schema). Single oversized tools can be "
                f"requested by exact name up to {_MAX_SINGLE_RESULT_TEXT} chars."
            )
        if not parts:
            return (
                "Found matches but none fit the result budget; narrow the query "
                "(one named tool at a time). Single complete tool definitions are "
                f"allowed up to {_MAX_SINGLE_RESULT_TEXT} chars unpadded."
            )
        return "\n\n".join(parts)

    def as_tool(self) -> Any:
        """Return the StructuredTool adapter with frozen naming/description.

        同步实现会走 orchestrator 的线程池，ContextVar 进不了工作线程，
        隔离任务会退回同一个 session key。异步适配留在当前任务里调用同一个 facade。
        """
        def _run(query: str, top_k: int = 5) -> str:
            """Search on-demand (MCP/plugin) tools by keyword and return schemas."""
            return self.search(query, top_k)

        async def _arun(query: str, top_k: int = 5) -> str:
            return self.search(query, top_k)

        return StructuredTool.from_function(
            func=_run,
            coroutine=_arun,
            name=TOOL_SEARCH_NAME,
            description=TOOL_SEARCH_DESCRIPTION,
        )


# payload 任意形态都先接住再校验——<tool_call>[]</tool_call> 这类坏包装
# 也必须产生显式 malformed 反馈（K3-2 #7），不能因正则不匹配而当 Final 放出。
_ENVELOPE_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
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
    dropped_overflow = 0

    def allocate() -> str:
        nonlocal seq
        call_id = f"defercall_{seq}"
        seq += 1
        return call_id

    accepted = 0
    for match in _ENVELOPE_RE.finditer(answer):
        if accepted >= _MAX_DEFERRED_CALLS:
            dropped_overflow += 1
            continue
        payload = match.group(1)
        call_id = allocate()
        accepted += 1
        if not payload.strip():
            malformed[call_id] = (
                "empty <tool_call> envelope: the call was NOT executed; "
                "re-emit one complete JSON object"
            )
            calls.append({"name": "<invalid>", "args": {}, "id": call_id, "type": "tool_call"})
            continue
        try:
            value, end = decoder.raw_decode(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            malformed[call_id] = (
                f"bad <tool_call> JSON: {exc}; re-emit a single valid envelope"
            )
            calls.append({"name": "<invalid>", "args": {}, "id": call_id, "type": "tool_call"})
            continue
        # K3-2 #7：一个 envelope 里塞两个连续 JSON——只接第一个必须显式拒。
        if payload[end:].strip():
            malformed[call_id] = (
                "<tool_call> has trailing content after the first JSON object; "
                "emit one complete envelope per call"
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

    # K3-2 #7：超过上限的第 N+1 个调用显式拒绝，不再被静默吞掉。
    if dropped_overflow:
        overflow_id = allocate()
        malformed[overflow_id] = (
            f"mixed: {_MAX_DEFERRED_CALLS}-envelope limit reached; "
            f"{dropped_overflow} further envelope(s) were NOT executed. "
            "Split them across rounds."
        )
        calls.append(
            {
                "name": "<invalid>",
                "args": {},
                "id": overflow_id,
                "type": "tool_call",
            }
        )

    consumed_end = answer.rfind("</tool_call>")
    if _ORPHAN_TAIL_RE.search(answer[consumed_end + 1 :]):
        orphan_id = allocate()
        malformed[orphan_id] = (
            "unterminated <tool_call> envelope: the call was NOT executed; "
            "re-emit one complete, closed envelope as the only tool call this round"
        )
        calls.append({"name": "<invalid>", "args": {}, "id": orphan_id, "type": "tool_call"})
    return calls, malformed
