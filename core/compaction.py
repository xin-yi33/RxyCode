"""压缩不毁前缀（PHASE-B §5 B4，opencode compaction 语义移植）。

核心纪律（CB1/CB4）：
- **压缩=唯一的 cache-reset point**：平时严格 append-only；前缀只能在
  压缩那一刻变。本模块是唯一压缩入口（工具循环、research、会话恢复
  全部走这里），压缩之外任何"改写历史"的调用都是 bug。
- **断点前不可变**：system + 前缀区消息逐字节保留；压缩只折叠断点之后
  的 assistant/tool 中间段，构造摘要消息**追加**到断点之后。
- **摘要模板** Objective / Work State / Next Move（opencode
  session/compaction.ts:16-46），必须携带任务状态（防返工，共性 5）。
- **尾部保留** tail_turns=2 / preserveRecentBudget 25%；system 永不裁剪。
- **不拆 assistant↔tool 对**：配对守恒（孤儿 tool_call → API 400 防线）。
- **遥测** tokens_before/after（原则 8），供命中率对比。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Mapping
from typing import Callable, Optional

from langchain_core.messages import HumanMessage

from .cache_policy import tool_pair_integrity

_logger = logging.getLogger(__name__)

#: 尾部保留轮数（opencode tail_turns=2 语义；调用方可覆盖）。
DEFAULT_TAIL_TURNS = 2

#: 尾部保留预算比例（opencode preserveRecentBudget 25%）。
TAIL_BUDGET_RATIO = 0.25

#: 输出预留（opencode overflow.ts:22-33 的 reserved，默认 20k）。
DEFAULT_RESERVED_TOKENS = 20_000

#: UPDATE-01 U3：旧 tool result 墓碑。文件仍在磁盘，模型可再 Read。
TOOL_RESULT_TOMBSTONE = "[tool result cleared]"
KEEP_RECENT_TOOL_RESULTS = 2


def occupancy_tokens(
    messages,
    *,
    count: Callable[[str], int] | None = None,
) -> int:
    """Current window occupancy for TUI and compact (UPDATE-01 OU2 / UPI-2).

    Counts message content **and** assistant tool_call argument JSON. Compact
    used to skip tool_calls, so the status bar and the trigger disagreed.
    """
    estimate = count or (lambda text: len(text or "") // 3)
    total = 0
    for message in messages or []:
        content = getattr(message, "content", "") or ""
        if isinstance(content, str):
            total += estimate(content)
        else:
            total += estimate(json.dumps(content, ensure_ascii=False, default=str))
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            extra = getattr(message, "additional_kwargs", None) or {}
            if isinstance(extra, dict):
                tool_calls = extra.get("tool_calls")
        for call in tool_calls or []:
            total += estimate(json.dumps(call, ensure_ascii=False, default=str))
    return total


def _is_tool_result(message) -> bool:
    return getattr(message, "type", None) == "tool"


def microcompact_messages(
    messages: list,
    *,
    keep_recent: int = KEEP_RECENT_TOOL_RESULTS,
) -> tuple[list, dict]:
    """Tombstone old tool **results**. Keep humans and assistant tool_calls.

    UPDATE-01 U3 / UPI-3: do not delete user messages or tool_call skeletons.
    """
    keep_recent = max(0, int(keep_recent or 0))
    tool_indexes = [index for index, message in enumerate(messages or []) if _is_tool_result(message)]
    keep = set(tool_indexes[-keep_recent:]) if keep_recent else set()
    out: list = []
    tombstoned = 0
    for index, message in enumerate(messages or []):
        if not _is_tool_result(message) or index in keep:
            out.append(message)
            continue
        content = getattr(message, "content", "") or ""
        if str(content).strip() == TOOL_RESULT_TOMBSTONE:
            out.append(message)
            continue
        if hasattr(message, "model_copy"):
            out.append(message.model_copy(update={"content": TOOL_RESULT_TOMBSTONE}))
        else:
            out.append(
                type(message)(
                    content=TOOL_RESULT_TOMBSTONE,
                    tool_call_id=getattr(message, "tool_call_id", "") or "",
                )
            )
        tombstoned += 1
    return out, {"tombstoned": tombstoned, "did_microcompact": tombstoned > 0}


def build_summary_message(
    objective: str,
    work_state: str,
    next_move: str,
) -> str:
    """构造摘要消息文本（Objective / Work State / Next Move 三段）。

    摘要必须携带任务状态才能"不返工"（调研报告共性 5）。本函数只返回
    文本；调用方将其作为独立 SystemMessage 追加到断点之后。
    """
    parts = [
        "<summary>",
        f"Objective: {objective.strip()}",
        f"Work State: {work_state.strip()}",
        f"Next Move: {next_move.strip()}",
        "</summary>",
    ]
    return "\n".join(parts)


def _estimate_chars(text: str) -> int:
    """token 估算（chars/3，与 _middle_truncate 同源；luna 审计要求单位一致）。"""
    return len(text or "") // 3


def _split_units(body_msgs: list) -> list:
    """把断点后消息链切分为轮次单元（配对守恒核心）。

    - human 消息：独立单元；
    - assistant(tool_calls)：与其后续全部 tool result 为同一单元
      （到下一个非 tool 消息为止；未配对完的 tool result 也并入单元，
      绝不产生孤儿结构）；
    - 非首位 system：独立单元（永不折叠，只保留相对顺序）；
    - 其他（普通 ai/assistant 无 tool_calls）：独立单元。
    """
    units: list = []
    i = 0
    while i < len(body_msgs):
        m = body_msgs[i]
        mtype = getattr(m, "type", None)
        if mtype == "system":
            units.append([m])
            i += 1
        elif mtype == "human":
            units.append([m])
            i += 1
        elif mtype == "ai" and getattr(m, "tool_calls", None):
            unit = [m]
            cids = {
                (c.get("id") if isinstance(c, dict) else getattr(c, "id", None))
                for c in m.tool_calls
                if (c.get("id") if isinstance(c, dict) else getattr(c, "id", None))
            }
            j = i + 1
            while j < len(body_msgs) and cids:
                nxt = body_msgs[j]
                if getattr(nxt, "type", None) == "tool":
                    cid = getattr(nxt, "tool_call_id", None)
                    if cid in cids:
                        # 只收集属于当前 assistant 的 tool result（luna 审计）
                        cids.discard(cid)
                        unit.append(nxt)
                        j += 1
                    else:
                        # 不属于本 assistant 的 tool：不吞并，停止收集
                        break
                else:
                    break
            units.append(unit)
            i = j
        else:
            units.append([m])
            i += 1
    return units


def _partition_tail_units(units: list, keep_tail: int) -> tuple[list, list]:
    """Split turn units into fold vs tail. System units stay in the tail."""
    tail_units: list = []
    fold_units: list = []
    human_seen = 0
    for unit in reversed(units):
        is_system_unit = any(getattr(m, "type", None) == "system" for m in unit)
        if is_system_unit:
            tail_units.append(unit)
        elif human_seen >= keep_tail:
            fold_units.append(unit)
        else:
            tail_units.append(unit)
            if any(getattr(m, "type", None) == "human" for m in unit):
                human_seen += 1
    fold_units.reverse()
    tail_units.reverse()
    return fold_units, tail_units


def _fold_body(messages: list) -> tuple[list, list]:
    """Frozen prefix (head system + first human) and the foldable body.

    Prior compaction-summary messages are removed from the body.
    """
    if not messages:
        return [], []
    head: list = []
    rest = list(messages)
    if rest and getattr(rest[0], "type", None) == "system":
        first_summary = bool(
            (getattr(rest[0], "additional_kwargs", None) or {}).get(
                "is_compaction_summary"
            )
        )
        if not first_summary:
            head.append(rest[0])
            rest = rest[1:]
    if rest and getattr(rest[0], "type", None) == "human":
        head.append(rest[0])
        rest = rest[1:]
    body = [
        m
        for m in rest
        if not (
            getattr(m, "type", None) == "system"
            and bool(
                (getattr(m, "additional_kwargs", None) or {}).get(
                    "is_compaction_summary"
                )
            )
        )
    ]
    return head, body


def _unit_has_tool(unit: list) -> bool:
    return any(getattr(message, "type", None) == "tool" for message in unit)


def _retain_visible_tombstone(fold_units: list, tail_units: list) -> None:
    """Keep the newest tombstoned tool pair visible after a fold.

    Full tool results still fold away. A pair is retained only when every
    tool result in it is already the short tombstone, and the natural tail
    would otherwise contain no tool message.
    """
    if any(_unit_has_tool(unit) for unit in tail_units):
        return
    for index in range(len(fold_units) - 1, -1, -1):
        unit = fold_units[index]
        tools = [message for message in unit if getattr(message, "type", None) == "tool"]
        if not tools:
            continue
        if all(
            str(getattr(message, "content", "") or "").strip() == TOOL_RESULT_TOMBSTONE
            for message in tools
        ):
            fold_units.pop(index)
            return


def _select_fold_msgs(messages: list, keep_tail: int) -> list:
    _head, body = _fold_body(messages)
    units = _split_units(body)
    fold_units, tail_units = _partition_tail_units(units, keep_tail)
    _retain_visible_tombstone(fold_units, tail_units)
    return [m for unit in fold_units for m in unit]


def _fold_middle_section(
    messages: list,
    keep_tail: int,
    *,
    existing_summary: Optional[str] = None,
    summarizer=None,
    summary_meta: dict | None = None,
    reuse_summary: bool = False,
) -> list:
    """折叠断点之后的 assistant/tool 中间段为摘要消息（确定性折叠）。

    纪律（luna 审计收紧）：
    - **system 永不裁剪**：仅 messages[0] 为 system 时保持头部前缀；
      其他 system 留在原序列位置（不重排、不提升）；
    - 折叠段 = 断点后非 system 的旧消息，且**成对折叠**：按轮次单元
      （assistant + 其匹配 tool result）整体折叠或保留，不拆对；
    - 尾部保留 keep_tail 轮（human 轮计数）；
    - `existing_summary` 非空时复用（避免预算循环重复生成摘要）；
    - 返回新列表，**绝不修改原消息对象**。
    """
    if not messages:
        return []
    # 1) 前缀：首条 system + 紧随的首轮 human 不折叠。其余 system 留在原位。
    head_system, body = _fold_body(messages)

    if not body:
        # luna 审计 R6-1/R7-1：body 过滤后为空时，返回去重后的 head_system + body；
        # 若已有摘要状态（existing_summary），保留之（重复压缩不丢失状态）。
        if existing_summary:
            from langchain_core.messages import SystemMessage

            summary_msg = SystemMessage(
                content=existing_summary,
                additional_kwargs={"is_compaction_summary": True},
            )
            return head_system + [summary_msg]
        return head_system + body

    # 2) 断点后消息切分为"轮次单元"；非首位 system 为独立单元（永不折叠）
    units: list = _split_units(body)
    fold_units, tail_units = _partition_tail_units(units, keep_tail)
    _retain_visible_tombstone(fold_units, tail_units)

    # 折叠段消息展平
    fold_msgs = [m for unit in fold_units for m in unit]

    if not fold_msgs:
        # luna 审计 R8-2：body 非空但无可折叠内容时，若已有摘要状态必须保留
        # （重复压缩不丢状态）——返回 head_system + [摘要] + 保留内容。
        if existing_summary:
            from langchain_core.messages import SystemMessage

            summary_msg = SystemMessage(
                content=existing_summary,
                additional_kwargs={"is_compaction_summary": True},
            )
            # fold_units 被抽空时，被保留的墓碑工具对不在 tail_units 里。
            # 用过滤后的 body 重建，避免那一对从结果里消失。
            return head_system + [summary_msg] + body
        return head_system + body

    # 4) 摘要信息提取。规则模板看断点后的整段（含尾部），这样 Next Move
    # 是最新的 human，而不是被折进摘要的那一条。
    scan = list(messages) or fold_msgs
    objective = ""
    work_state = ""
    for m in scan:
        if getattr(m, "type", None) == "human" and not objective:
            objective = str(getattr(m, "content", "") or "")[:200]
        if getattr(m, "type", None) == "ai" and not work_state:
            work_state = str(getattr(m, "content", "") or "")[:200]
    next_move = ""
    for m in reversed(scan):
        if getattr(m, "type", None) == "human":
            next_move = str(getattr(m, "content", "") or "")[:200]
            break

    # 废弃代码（2026-10-09）：summary_text = existing_summary，有旧摘要就
    # 不再看新折叠段。预算收紧才 reuse_summary，避免再打一次摘要模型。
    summary_text = None
    summary_source = SUMMARY_SOURCE_RULE
    if reuse_summary and existing_summary:
        summary_text = existing_summary
    elif summarizer is not None:
        summary_text = _try_llm_summary(summarizer, fold_msgs, existing_summary)
        if summary_text is not None:
            summary_source = SUMMARY_SOURCE_LLM
    if summary_text is None:
        if existing_summary:
            summary_text = _merge_rule_summary(
                existing_summary, objective, work_state, next_move
            )
        else:
            summary_text = build_summary_message(objective, work_state, next_move)
        summary_source = SUMMARY_SOURCE_RULE
    if summary_meta is not None:
        summary_meta["summary_source"] = summary_source
    # luna 审计 R6-2：使用正式 LangChain SystemMessage（生产链路序列化兼容），
    # 不用 SimpleNamespace。
    from langchain_core.messages import SystemMessage

    summary_msg = SystemMessage(
        content=summary_text,
        additional_kwargs={"is_compaction_summary": True},
    )
    # luna 审计 R8-1：按 units 原序重建——fold 单元在原位置替换为摘要
    # （首个 fold 单元处插入摘要，其余 fold 单元丢弃），非首位 system 与
    # 保留单元保持原相对顺序（不被摘要前移）。
    fold_ids = {id(u) for u in fold_units}
    output: list = []
    inserted = False
    for unit in units:
        if id(unit) in fold_ids:
            if not inserted:
                output.append(summary_msg)
                inserted = True
            continue
        output.extend(unit)
    return head_system + output


def compact_messages(
    messages: list,
    *,
    tail_turns: int = DEFAULT_TAIL_TURNS,
    return_telemetry: bool = False,
    summarizer=None,
) -> list:
    """唯一压缩入口：断点前不可变，折叠断点后中间段为摘要并追加。

    参数:
        messages: 消息链（LangChain 对象或 SimpleNamespace）。
        tail_turns: 尾部保留轮数（默认 2）。
        return_telemetry: True 时返回 (out, telemetry)。

    返回:
        list（或 (list, dict)）。**绝不修改原消息对象**；配对校验失败时
        回退原消息并记录警告（API 400 防线）。
    """
    tokens_before = sum(
        _estimate_chars(getattr(m, "content", "") or "") for m in messages
    )
    # 重复压缩把旧摘要并进新摘要。不能因为已有摘要就跳过这次折叠。
    prior_summary = next(
        (
            getattr(m, "content", "")
            for m in messages
            if getattr(m, "type", "") == "system"
            and bool(
                (getattr(m, "additional_kwargs", None) or {}).get(
                    "is_compaction_summary"
                )
            )
        ),
        None,
    )
    summary_meta: dict = {}
    result = _fold_middle_section(
        list(messages),
        keep_tail=tail_turns,
        existing_summary=prior_summary,
        # 废弃代码（2026-10-09）：summarizer=None if prior_summary else summarizer
        summarizer=summarizer,
        summary_meta=summary_meta,
    )
    tokens_after = sum(
        _estimate_chars(getattr(m, "content", "") or "") for m in result
    )
    # 尾部预算（luna 审计）：preserveRecentBudget 25%——先计算不可裁剪体积
    # （system + 摘要），剩余预算 = 25% - 不可裁剪；超出时收紧尾部保留，
    # 复用已有摘要（不重复生成）。
    existing_summary = next(
        (
            getattr(m, "content", "")
            for m in result
            if getattr(m, "type", "") == "system"
            and bool(
                (getattr(m, "additional_kwargs", None) or {}).get(
                    "is_compaction_summary"
                )
            )
        ),
        None,
    )
    fixed_overhead = sum(
        _estimate_chars(getattr(m, "content", "") or "")
        for m in result
        if getattr(m, "type", "") == "system"
    )
    budget_floor = max(
        0,
        int(tokens_before * TAIL_BUDGET_RATIO) - fixed_overhead,
    )
    guard = 0
    while (
        tokens_after - fixed_overhead > budget_floor
        and guard < 20
    ):
        guard += 1
        tighter = _fold_middle_section(
            result,
            keep_tail=max(0, tail_turns - guard),
            existing_summary=existing_summary,
            reuse_summary=True,
        )
        tighter_after = sum(
            _estimate_chars(getattr(m, "content", "") or "") for m in tighter
        )
        if tighter_after >= tokens_after:
            break  # 无法继续缩小
        # 尾部预算不能把墓碑工具结果也剪没。fold 之后 tail 里还要留得住它。
        result_has_tool = any(getattr(m, "type", None) == "tool" for m in result)
        tighter_has_tool = any(getattr(m, "type", None) == "tool" for m in tighter)
        if result_has_tool and not tighter_has_tool:
            break
        result = tighter
        tokens_after = tighter_after
    if not tool_pair_integrity(result):
        _logger.warning(
            "compaction produced broken assistant-tool pairing; "
            "falling back to unmodified messages"
        )
        result = list(messages)
        tokens_after = tokens_before
    telemetry = {
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "tail_turns": tail_turns,
        "compacted": tokens_after < tokens_before,
        "note": "tokens are char/3 estimates (not provider token counts)",
        "summary_source": summary_meta.get("summary_source", SUMMARY_SOURCE_RULE),
    }
    if return_telemetry:
        return result, telemetry
    return result


def usable_tokens(
    context_window: int,
    reserved: int = DEFAULT_RESERVED_TOKENS,
) -> int:
    """Occupancy may grow until window − reserved; that is the only auto trigger."""
    return max(0, int(context_window) - max(0, int(reserved)))


def run_compaction_ladder(
    messages: list,
    *,
    force: bool = False,
    occupancy: int | None = None,
    context_window: int,
    reserved: int = DEFAULT_RESERVED_TOKENS,
    count: Callable[[str], int] | None = None,
    summarizer=None,
) -> tuple[list, dict]:
    """Single auto/manual compact entry: microcompact, then fold if still over.

    Auto compact fires only when occupancy > (window − reserved), unless
    ``force`` (``/compact``). Count archival, 85% passes, and history clipping
    do not belong here.
    """
    occ = (
        int(occupancy)
        if occupancy is not None
        else occupancy_tokens(messages, count=count)
    )
    usable = usable_tokens(context_window, reserved)
    plan = plan_compaction(
        messages,
        occupancy=occ,
        context_window=context_window,
        reserved=reserved,
        count=count,
        force=force,
    )
    telemetry: dict = {
        "occupancy": occ,
        "usable": usable,
        "window": int(context_window),
        "reserved": max(0, int(reserved)),
        "force": bool(force),
        "did_compact": False,
        "rung": plan["rung"],
    }
    if plan["rung"] == "none":
        return list(messages), telemetry

    micro, micro_tel = microcompact_messages(
        list(messages),
        keep_recent=0 if force else KEEP_RECENT_TOOL_RESULTS,
    )
    occ_micro = occupancy_tokens(micro, count=count)
    telemetry["occupancy_after_micro"] = occ_micro
    telemetry["tombstoned"] = micro_tel.get("tombstoned", 0)
    if plan["rung"] == "microcompact":
        telemetry["did_compact"] = bool(micro_tel.get("did_microcompact"))
        return micro, telemetry

    fold_kwargs = {
        "tail_turns": DEFAULT_TAIL_TURNS,
        "return_telemetry": True,
    }
    if summarizer is not None:
        fold_kwargs["summarizer"] = summarizer
    folded, fold_tel = compact_messages(micro, **fold_kwargs)
    telemetry["did_compact"] = bool(
        fold_tel.get("compacted") or micro_tel.get("did_microcompact")
    )
    telemetry["rung"] = "fold"
    telemetry["tokens_before"] = fold_tel.get("tokens_before")
    telemetry["tokens_after"] = fold_tel.get("tokens_after")
    telemetry["summary_source"] = fold_tel.get("summary_source", SUMMARY_SOURCE_RULE)
    return folded, telemetry


STATE_SNAPSHOT_FIELDS = (
    "objective",
    "constraints",
    "progress",
    "files_touched",
    "next_step",
    "blockers",
)
SUMMARY_SOURCE_FIELD = "summary_source"
SUMMARY_SOURCE_LLM = "llm"
SUMMARY_SOURCE_RULE = "rule"


def build_state_summary_message(fields: Mapping[str, str | list[str]]) -> str:
    """六字段 → <summary> 文本。files_touched 为 list 时用 ", ".join。"""
    files = fields["files_touched"]
    if isinstance(files, (list, tuple)):
        files = ", ".join(str(item) for item in files)
    parts = [
        "<summary>",
        f"Objective: {str(fields['objective']).strip()}",
        f"Constraints: {str(fields['constraints']).strip()}",
        f"Progress: {str(fields['progress']).strip()}",
        f"Files Touched: {str(files).strip()}",
        f"Next Step: {str(fields['next_step']).strip()}",
        f"Blockers: {str(fields['blockers']).strip()}",
        "</summary>",
    ]
    return "\n".join(parts)


def _parse_snapshot_json(text: str):
    start = (text or "").find("{")
    if start < 0:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_state_snapshot(result) -> dict | None:
    """Return the six fields only when every key is present. No half summary."""
    if isinstance(result, str):
        result = _parse_snapshot_json(result)
    if not isinstance(result, Mapping):
        return None
    if any(key not in result for key in STATE_SNAPSHOT_FIELDS):
        return None
    return dict(result)


def _snapshot_text_from_result(result) -> str | None:
    fields = parse_state_snapshot(result)
    if fields is None:
        return None
    return build_state_summary_message(fields)


def _resolve_maybe_awaitable(value):
    """无运行循环才 asyncio.run。有循环收到 awaitable 则失败，不另起线程。"""
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError("summarizer awaitable received on the worker loop; pre-resolve it")


_SUMMARY_LABELS = frozenset(
    {
        "objective",
        "constraints",
        "progress",
        "work state",
        "files touched",
        "next step",
        "next move",
        "blockers",
    }
)


def _summary_field(text: str, label: str) -> str:
    """取一个字段的整段，直到下一个已知标签。续行不能被丢掉。"""
    want = label.lower()
    captured: list[str] = []
    active = False
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        lowered = stripped.lower()
        if lowered in ("<summary>", "</summary>"):
            if active:
                break
            continue
        head, sep, tail = stripped.partition(":")
        if sep and head.strip().lower() in _SUMMARY_LABELS:
            if active:
                break
            if head.strip().lower() == want:
                active = True
                if tail.strip():
                    captured.append(tail.strip())
            continue
        if active and stripped:
            captured.append(stripped)
    return "\n".join(captured).strip()


def _merge_rule_summary(
    prior_summary: str,
    objective: str,
    work_state: str,
    next_move: str,
) -> str:
    """旧摘要并进新的六字段。Next Step 用这次扫到的最新对话，不留旧的 Next Move。"""
    progress = (
        _summary_field(prior_summary, "Progress")
        or _summary_field(prior_summary, "Work State")
        or work_state
    )
    return build_state_summary_message(
        {
            "objective": _summary_field(prior_summary, "Objective") or objective,
            "constraints": _summary_field(prior_summary, "Constraints"),
            "progress": progress,
            "files_touched": _summary_field(prior_summary, "Files Touched"),
            "next_step": next_move
            or _summary_field(prior_summary, "Next Step")
            or _summary_field(prior_summary, "Next Move"),
            "blockers": _summary_field(prior_summary, "Blockers"),
        }
    )


def _invoke_summarizer(summarizer, fold_msgs, prior_summary):
    """按声明把旧摘要送进去。单参数摘要器不多传位置参数。"""
    try:
        signature = inspect.signature(summarizer)
    except (TypeError, ValueError):
        return summarizer(fold_msgs)
    named = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    has_var_positional = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    has_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if len(named) >= 2:
        second = named[1]
        if second.kind == inspect.Parameter.KEYWORD_ONLY:
            return summarizer(fold_msgs, **{second.name: prior_summary})
        return summarizer(fold_msgs, prior_summary)
    if has_var_positional:
        return summarizer(fold_msgs, prior_summary)
    if has_var_keyword:
        return summarizer(fold_msgs, prior_summary=prior_summary)
    return summarizer(fold_msgs)


def _try_llm_summary(summarizer, fold_msgs, prior_summary=None) -> str | None:
    try:
        result = _resolve_maybe_awaitable(
            _invoke_summarizer(summarizer, fold_msgs, prior_summary)
        )
        return _snapshot_text_from_result(result)
    except Exception:
        return None


async def try_llm_summary_async(summarizer, fold_msgs) -> str | None:
    """Await a summarizer on the current loop. CancelledError propagates."""
    if summarizer is None:
        return None
    try:
        result = summarizer(fold_msgs)
        if inspect.isawaitable(result):
            result = await result
        return _snapshot_text_from_result(result)
    except asyncio.CancelledError:
        raise
    except Exception:
        return None


def plan_compaction(
    messages: list,
    *,
    context_window: int,
    reserved: int = DEFAULT_RESERVED_TOKENS,
    occupancy: int | None = None,
    count: Callable[[str], int] | None = None,
    force: bool = False,
) -> dict:
    """Same rung decision as run_compaction_ladder. No LLM and no writes."""
    occ = (
        int(occupancy)
        if occupancy is not None
        else occupancy_tokens(messages, count=count)
    )
    usable = usable_tokens(context_window, reserved)
    if occ <= usable and not force:
        return {"rung": "none", "fold_msgs": []}
    micro, _micro_tel = microcompact_messages(
        list(messages),
        keep_recent=0 if force else KEEP_RECENT_TOOL_RESULTS,
    )
    occ_micro = occupancy_tokens(micro, count=count)
    if occ_micro <= usable and not force:
        return {"rung": "microcompact", "fold_msgs": []}
    return {
        "rung": "fold",
        "fold_msgs": _select_fold_msgs(micro, DEFAULT_TAIL_TURNS),
    }


def build_compaction_summary_prompt(messages, prior_summary=None) -> list:
    """Ask the session model for the six snapshot fields as one JSON object."""
    lines = []
    for message in messages or []:
        kind = getattr(message, "type", "message")
        lines.append(f"{kind}: {getattr(message, 'content', '')}")
    body = "\n".join(lines)
    prior = ""
    if prior_summary:
        prior = "\nPrior summary, merge it and do not drop it:\n" + str(prior_summary)
    rules = (
        "\nKeep user decisions and constraints verbatim. "
        "next_step must quote the latest dialogue directly. "
        "Record errors and approaches that were already tried. "
        "Return JSON only. Do not call tools."
    )
    return [
        HumanMessage(
            content=(
                "Summarize the folded work as JSON with keys "
                "objective, constraints, progress, files_touched, next_step, blockers. "
                "files_touched must be a list of strings.\n" + body + prior + rules
            )
        )
    ]
