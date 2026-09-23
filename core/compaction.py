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

import json
import logging
from typing import Callable, Optional

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


def _fold_middle_section(
    messages: list,
    keep_tail: int,
    *,
    existing_summary: Optional[str] = None,
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
    # 1) 前缀边界（luna 审计）：仅 messages[0] 为 system 时它才是缓存前缀
    #    核心（保持头部、字节不变）；**其他 system 一律留在原序列位置**
    #    （永不裁剪、不重排、不提升）。
    head_system: list = []
    body: list = []
    if messages and getattr(messages[0], "type", None) == "system":
        # luna 审计 R8-3：首条若是摘要标记消息，不当头部前缀（摘要唯一性）
        first_summary = bool(
            (getattr(messages[0], "additional_kwargs", None) or {}).get(
                "is_compaction_summary"
            )
        )
        if first_summary:
            body = list(messages)
        else:
            head_system.append(messages[0])
            body = list(messages[1:])
    else:
        body = list(messages)

    # 移除已有摘要消息（luna 审计 B4-1）：压缩结果中最多一个摘要。
    # 用显式标记 additional_kwargs["is_compaction_summary"] 识别（luna 审计
    # R5），**不用正文子串**——正文含 "Objective" 的合法 system 不受影响。
    body = [
        m
        for m in body
        if not (
            getattr(m, "type", None) == "system"
            and bool(
                (getattr(m, "additional_kwargs", None) or {}).get(
                    "is_compaction_summary"
                )
            )
        )
    ]

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

    # 3) 尾部保留（单元粒度）：system 单元永不折叠；其余保留最后 keep_tail
    #    个 human 轮单元
    tail_units: list = []
    fold_units: list = []
    human_seen = 0
    for unit in reversed(units):
        is_system_unit = any(
            getattr(m, "type", None) == "system" for m in unit
        )
        if is_system_unit:
            # system 永不裁剪：强制保留在尾部（相对顺序不变）
            tail_units.append(unit)
        elif human_seen >= keep_tail:
            fold_units.append(unit)
        else:
            tail_units.append(unit)
            if any(getattr(m, "type", None) == "human" for m in unit):
                human_seen += 1
    fold_units.reverse()
    tail_units.reverse()

    # 折叠段消息展平
    fold_msgs = [m for unit in fold_units for m in unit]
    tail_msgs = [m for unit in tail_units for m in unit]

    if not fold_msgs:
        # luna 审计 R8-2：body 非空但无可折叠内容时，若已有摘要状态必须保留
        # （重复压缩不丢状态）——返回 head_system + [摘要] + 保留内容。
        if existing_summary:
            from langchain_core.messages import SystemMessage

            summary_msg = SystemMessage(
                content=existing_summary,
                additional_kwargs={"is_compaction_summary": True},
            )
            return head_system + [summary_msg] + tail_msgs
        return head_system + body

    # 4) 摘要信息提取（确定性：首条 human 为 objective、首条 ai 为 work_state、
    #    最后 human 为 next_move）
    objective = ""
    work_state = ""
    for m in fold_msgs:
        if getattr(m, "type", None) == "human" and not objective:
            objective = str(getattr(m, "content", "") or "")[:200]
        if getattr(m, "type", None) == "ai" and not work_state:
            work_state = str(getattr(m, "content", "") or "")[:200]
    next_move = ""
    for m in reversed(fold_msgs):
        if getattr(m, "type", None) == "human":
            next_move = str(getattr(m, "content", "") or "")[:200]
            break

    summary_text = existing_summary
    if summary_text is None:
        summary_text = build_summary_message(objective, work_state, next_move)
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
    # luna 审计 R7-1：重复压缩不丢失既有摘要状态——首次折叠前提取旧摘要
    # （含 Objective/Work State/Next Move），合并进新摘要。
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
    result = _fold_middle_section(
        list(messages),
        keep_tail=tail_turns,
        existing_summary=prior_summary,
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
        )
        tighter_after = sum(
            _estimate_chars(getattr(m, "content", "") or "") for m in tighter
        )
        if tighter_after >= tokens_after:
            break  # 无法继续缩小
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
    telemetry: dict = {
        "occupancy": occ,
        "usable": usable,
        "window": int(context_window),
        "reserved": max(0, int(reserved)),
        "force": bool(force),
        "did_compact": False,
        "rung": "none",
    }
    if occ <= usable and not force:
        return list(messages), telemetry

    micro, micro_tel = microcompact_messages(list(messages))
    occ_micro = occupancy_tokens(micro, count=count)
    telemetry["occupancy_after_micro"] = occ_micro
    telemetry["tombstoned"] = micro_tel.get("tombstoned", 0)
    if occ_micro <= usable and not force:
        telemetry["did_compact"] = bool(micro_tel.get("did_microcompact"))
        telemetry["rung"] = "microcompact"
        return micro, telemetry

    folded, fold_tel = compact_messages(
        micro, tail_turns=DEFAULT_TAIL_TURNS, return_telemetry=True
    )
    telemetry["did_compact"] = bool(
        fold_tel.get("compacted") or micro_tel.get("did_microcompact")
    )
    telemetry["rung"] = "fold"
    telemetry["tokens_before"] = fold_tel.get("tokens_before")
    telemetry["tokens_after"] = fold_tel.get("tokens_after")
    return folded, telemetry
