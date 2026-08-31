"""断点预算（opencode cache-policy 语义移植，PHASE-B §5 B3）。

分配序 tools→system→messages；上限 4 个，超额丢弃；
TTL 5m/1h 双档由 config.cache.ttl 控制（默认 5m）。

本模块是断点分配的唯一入口：B3 的 _apply_cache_control、后续 Phase D/F
的 Child Session 与专家团都必须复用本模块，不得另写一套断点逻辑。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Optional

_logger = logging.getLogger(__name__)

#: Anthropic 官方断点上限（opencode cache-policy.ts:18-22 语义）。
BREAKPOINT_BUDGET = 4

#: 断点分配序（opencode：tools→system→messages）。
BREAKPOINT_ORDER = ("tools", "system", "messages")

#: TTL 档位（秒）。5m 默认；1h 档写入价更高，按配置启用（§6.2 成本保守）。
TTL_TIER_5M = 300
TTL_TIER_1H = 3600
DEFAULT_TTL_SECONDS = TTL_TIER_5M


def cache_control_for_ttl(ttl_seconds: int) -> dict:
    """Anthropic cache_control block for a resolved TTL.

    Only the documented 5m (omit ttl) and 1h (ttl=1h) tiers are expressed.
    Other values keep the 5m default rather than inventing a vendor field.
    """
    control = {"type": "ephemeral"}
    if int(ttl_seconds) == TTL_TIER_1H:
        control["ttl"] = "1h"
    return control


def resolve_ttl_seconds(cfg: Optional[dict]) -> int:
    """解析 cache.ttl 配置为秒。

    支持：
    - "5m" / "1h" 字符串档位
    - 数字秒（兼容现状 config.cache.ttl=3600）
    - 缺失/未知 → 默认 5m（300s）
    """
    if not isinstance(cfg, dict):
        return DEFAULT_TTL_SECONDS
    cache_cfg = cfg.get("cache") or {}
    raw = cache_cfg.get("ttl")
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "5m":
            return TTL_TIER_5M
        if normalized == "1h":
            return TTL_TIER_1H
        if normalized.endswith("m") and normalized[:-1].isdigit():
            return int(normalized[:-1]) * 60
        if normalized.endswith("h") and normalized[:-1].isdigit():
            return int(normalized[:-1]) * 3600
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return DEFAULT_TTL_SECONDS


def allocate_breakpoints(
    tools: list,
    system: str,
    messages: list,
    *,
    budget: int = BREAKPOINT_BUDGET,
) -> list:
    """返回要打点的目标位置列表，顺序固定：tools→system→messages。

    预算强制 ≤ BREAKPOINT_BUDGET（4）：调用方传更大值也按 4 处理
    （Anthropic 官方上限，opencode 语义）；超额按分配序丢弃最不稳定的块。
    """
    if budget <= 0:
        return []
    budget = min(int(budget), BREAKPOINT_BUDGET)
    candidates = []
    if tools:
        candidates.append("tools")
    if system:
        candidates.append("system")
    if messages:
        candidates.append("messages")
    # 按分配序过滤出真实存在的块；超额丢弃（保留分配序靠前的稳定块）
    ordered = [b for b in BREAKPOINT_ORDER if b in candidates]
    return ordered[:budget]


def mark_last_user_breakpoint(messages: list, cache_control: dict | None = None) -> list:
    """末条 user 断点（P0-2 cline 语义）。

    只标记最后一条 user 消息的 cache_control ephemeral——单轮工具循环内
    每次 API 调用都命中静态前缀；早期 user 消息不标记（避免前缀抖动）。
    返回新列表，**绝不修改原消息对象**（luna 审计要求）。

    FXC2：生产路径仅在 ``injects_cache_control(contract)`` 为真时调用
    （``apply_breakpoint_budget`` / ``_apply_cache_control`` 先门控）。
    """
    result = list(messages)
    last_user_idx = None
    for i, m in enumerate(result):
        if getattr(m, "type", None) == "human":
            last_user_idx = i
    if last_user_idx is None:
        return result
    target = result[last_user_idx]
    ak = dict(getattr(target, "additional_kwargs", None) or {})
    if "cache_control" in ak:
        return result
    ak["cache_control"] = dict(cache_control or {"type": "ephemeral"})
    try:
        from langchain_core.messages import HumanMessage

        if isinstance(target, HumanMessage):
            result[last_user_idx] = HumanMessage(
                content=target.content,
                additional_kwargs=ak,
            )
            return result
    except ImportError:  # pragma: no cover
        pass
    # 非 LangChain 对象（测试用 SimpleNamespace）：构造新对象，不改原对象
    new_target = target
    try:
        new_target = SimpleNamespace(
            type=getattr(target, "type", "human"),
            content=getattr(target, "content", ""),
            additional_kwargs=ak,
        )
        for attr in ("tool_calls", "tool_call_id", "name", "id"):
            if hasattr(target, attr):
                setattr(new_target, attr, getattr(target, attr))
    except Exception:  # pragma: no cover - 极端对象兜底
        new_target = target
    result[last_user_idx] = new_target
    return result


def tool_pair_integrity(messages: list) -> bool:
    """tool 消息必须紧跟带对应 tool_call 的 assistant（不拆对，luna 审计）。

    规则：
    - tool 消息必须**直接**位于携带匹配 tool_call_id 的 assistant 之后，
      中间不允许插入其他消息；
    - 同一 tool_call 的连续 tool result（合并形态）合法；
    - tool_call_id 缺失的 tool 消息 → False（孤儿，API 400 防线）；
    - assistant 的 tool_call 声明后若被其他消息打断才出现 tool → False。

    返回 True = 配对完整；False = 存在拆对/孤儿，调用方应回退。
    """
    expecting_cids: set = set()  # 当前 assistant 声明、尚未消费的 tool_call_id
    last_tool_cid: Optional[str] = None  # 上一条消息若是 tool，记录其 cid
    for m in messages:
        mtype = getattr(m, "type", None)
        if mtype == "ai":
            calls = getattr(m, "tool_calls", None) or []
            expecting_cids = {
                (c.get("id") if isinstance(c, dict) else getattr(c, "id", None))
                for c in calls
                if (c.get("id") if isinstance(c, dict) else getattr(c, "id", None))
            }
            last_tool_cid = None
        elif mtype == "tool":
            cid = getattr(m, "tool_call_id", None)
            if not cid:
                return False  # 缺 id 的孤儿 tool
            if cid in expecting_cids:
                # 紧跟 assistant 声明 → 合法，消费
                expecting_cids.discard(cid)
                last_tool_cid = cid
            elif cid == last_tool_cid:
                # 同一 tool_call 的连续 result（合并形态）→ 合法
                continue
            else:
                # 既不在 assistant 声明中，也不是连续 result → 拆对/孤儿
                return False
            last_tool_cid = cid
        else:
            # 非 assistant/tool 消息插入 → 之前的 tool_call 声明作废：
            # 后续 tool 消息无法再"紧跟"对应 assistant（拆对拒绝）。
            expecting_cids = set()
            last_tool_cid = None
    # 遍历结束：assistant 声明但未消费的 tool_call → 配对不完整（luna 审计）。
    return not expecting_cids


def apply_breakpoint_budget(
    messages: list,
    *,
    tools: Optional[list] = None,
    caps=None,
    cfg: Optional[dict] = None,
    contract: Optional[dict] = None,
) -> list:
    """统一断点预算入口（B3 步骤 2/3：_apply_cache_control 调用它）。

    按 caps.cache_breakpoints 声明的断点类型分配（tools→system→messages
    分配序、≤4 强制预算）：
    - 只分配 caps 声明的块类型（如 cache_breakpoints=("system",) 时不打
      messages/tail 断点）；
    - system 断点：首条 system 消息注入 cache_control ephemeral；
    - messages/tail 断点：末条 user 消息注入（P0-2 cline 语义）；
    - tools 断点：由 provider 层在请求体 tools 定义上注入（本层不操作消息）；
    - TTL 从 cfg.cache.ttl 解析（5m/1h 双档），随断点审计返回；
    - 打点后执行 tool_pair_integrity 校验（防拆对，API 400 防线）。

    返回 (messages, allocated, ttl_seconds)。**绝不修改原消息对象**。
    FXC2：传入 ``contract`` 时必须 ``injects_cache_control`` 为真才打点。
    """
    if contract is not None:
        from .catalog import injects_cache_control

        if not injects_cache_control(contract):
            return messages, [], resolve_ttl_seconds(cfg)
    breakpoints = getattr(caps, "cache_breakpoints", ()) if caps is not None else ()
    if not breakpoints:
        return messages, [], resolve_ttl_seconds(cfg)

    system_text = ""
    msg_list = list(messages)
    if msg_list and getattr(msg_list[0], "type", None) == "system":
        system_text = str(getattr(msg_list[0], "content", "") or "")

    # 只分配 caps 声明的断点类型（能力约束，防止在不支持的类型上打点）
    has_tools = bool(tools) and "tools" in breakpoints
    has_system = bool(system_text) and "system" in breakpoints
    has_messages = bool(msg_list) and (
        "messages" in breakpoints or "tail" in breakpoints
    )
    allocated = allocate_breakpoints(
        tools if has_tools else [],
        system_text if has_system else "",
        msg_list if has_messages else [],
    )
    ttl = resolve_ttl_seconds(cfg)

    result = list(messages)
    cache_control = cache_control_for_ttl(ttl)
    for block in allocated:
        if block == "system":
            first = result[0]
            ak = dict(getattr(first, "additional_kwargs", None) or {})
            if "cache_control" not in ak:
                ak["cache_control"] = dict(cache_control)
                try:
                    from langchain_core.messages import SystemMessage

                    if isinstance(first, SystemMessage):
                        result[0] = SystemMessage(
                            content=first.content, additional_kwargs=ak
                        )
                        continue
                except ImportError:  # pragma: no cover
                    pass
                result[0] = SimpleNamespace(
                    type=getattr(first, "type", "system"),
                    content=getattr(first, "content", ""),
                    additional_kwargs=ak,
                )
        elif block in ("messages", "tail"):
            # FXC2: 仅显式族走到这里（调用方 / contract 门控 injects_cache_control）。
            result = mark_last_user_breakpoint(result, cache_control)
        # tools 块：Anthropic 断点在 tools 定义上（B3 步骤 3 由 provider
        # 层处理——tools 定义随请求体注入 cache_control，本层不操作消息）。
    # 防拆对校验：打点后断言 assistant↔tool 配对完整（孤儿 tool → API 400）。
    if not tool_pair_integrity(result):
        _logger.warning(
            "breakpoint application broke assistant-tool pairing; "
            "falling back to unmodified messages"
        )
        return messages, [], ttl
    return result, allocated, ttl


def verify_deepseek_prefix(prompt_tokens: int, hit_tokens: int) -> bool:
    """DeepSeek 自动前缀验证（B3 步骤 4）。

    DeepSeek 不注入 cache_control（CB3），命中信息在
    usage.prompt_cache_hit_tokens。命中>0 视为前缀生效（True）；
    全 0 且已消耗 prompt 时记录警告并返回 False（不静默）。
    """
    if hit_tokens > 0:
        return True
    if prompt_tokens > 0:
        _logger.warning(
            "DeepSeek automatic prefix cache verified MISS: "
            "prompt_tokens=%d hit_tokens=0 (cold start or prefix broken)",
            prompt_tokens,
        )
    return False


# ---------------------------------------------------------------------------
# B5: 会话复用与 prewarm（PHASE-B §5 B5）
# ---------------------------------------------------------------------------

#: 保活空请求默认预算（写入价保护，§6.2 成本保守）。
DEFAULT_KEEP_ALIVE_MAX_CALLS = 20

#: 保活请求最大输出 token（aider max_tokens=1 语义）。
KEEP_ALIVE_MAX_TOKENS = 1

#: 保活间隔（秒）——Anthropic 5m TTL 档（B5 步骤 4）。
KEEP_ALIVE_INTERVAL_S = 300


def build_prewarm_signature(
    *,
    model: str,
    cwd: str,
    mcp: str = "",
    kind: str = "agent",
    thinking_enabled: bool = True,
    tools_digest: str = "",
) -> str:
    """预热签名（Cherry Studio agentSessionWarmup.ts:246-253 语义）。

    模型/cwd/MCP 任一变化 → 签名变化 → 预热缓存失效 → 重建。
    确定性序列化（sort_keys）保证同配置同签名。
    """
    import hashlib
    import json

    norm = json.dumps(
        {
            "model": model,
            "cwd": cwd,
            "mcp": mcp,
            "kind": kind,
            "thinking_enabled": thinking_enabled,
            "tools_digest": tools_digest,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def prewarm_valid(
    signature: str,
    *,
    model: str,
    cwd: str,
    mcp: str = "",
    kind: str = "agent",
    thinking_enabled: bool = True,
    tools_digest: str = "",
) -> bool:
    """预热请求与真实请求同签名校验：签名一致才有效。

    任一配置变化 → 当前签名 ≠ 预热签名 → 预热失效（需重建）。
    """
    current = build_prewarm_signature(
        model=model, cwd=cwd, mcp=mcp,
        kind=kind, thinking_enabled=thinking_enabled, tools_digest=tools_digest,
    )
    return current == signature


def keep_alive_enabled(cfg: Optional[dict]) -> bool:
    """保活开关（B5 步骤 4）：默认关闭，按配置启用（成本保守 §6.2）。"""
    if not isinstance(cfg, dict):
        return False
    return bool((cfg.get("cache") or {}).get("keep_alive", False))


def keep_alive_budget(cfg: Optional[dict]) -> int:
    """保活预算上限（写入价保护）：默认 20 次，可配置。"""
    if not isinstance(cfg, dict):
        return DEFAULT_KEEP_ALIVE_MAX_CALLS
    raw = (cfg.get("cache") or {}).get("keep_alive_max_calls")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return DEFAULT_KEEP_ALIVE_MAX_CALLS


def keep_alive_should_fire(
    *,
    last_call_at: Optional[float],
    now: float,
    cfg: Optional[dict],
    calls_used: int = 0,
) -> bool:
    """保活调度判定（B5 步骤 4）：启用 + 距上次调用 ≥5m + 预算未耗尽。"""
    if not keep_alive_enabled(cfg):
        return False
    if calls_used >= keep_alive_budget(cfg):
        return False
    if last_call_at is None:
        return False  # 无历史调用不保活（无前缀可保）
    return (now - last_call_at) >= KEEP_ALIVE_INTERVAL_S


def build_keep_alive_request(messages: list) -> dict:
    """构造保活请求（aider base_coder.py:1340-1392 语义）。

    最小请求：复用会话前缀 + max_tokens=1 空输出，仅重写缓存不产出内容。
    返回请求字典（messages + 保活参数）。
    """
    return {
        "messages": list(messages),
        "max_tokens": KEEP_ALIVE_MAX_TOKENS,
        "keep_alive": True,
    }


class PrewarmState:
    """预热状态（Cherry Studio ClaudeCodeWarmQueryManager.ts:201-255 语义）。

    保存预热签名；配置变化（模型/cwd/MCP）→ 签名不匹配 → 预热失效 →
    需重建（记录重建事件到审计）。
    """

    def __init__(self) -> None:
        self._signature: Optional[str] = None
        self._warmed_at: Optional[float] = None

    def warm(self, signature: str, now: Optional[float] = None) -> None:
        """记录一次预热（同签名有效）。"""
        import time

        self._signature = signature
        self._warmed_at = now if now is not None else time.time()

    def validate(self, signature: str) -> bool:
        """签名一致且已预热 → 有效；否则失效（需重建）。"""
        return self._signature is not None and self._signature == signature

    def rebuild(self, signature: str, now: Optional[float] = None) -> bool:
        """配置变化 → 重建：返回 True 表示发生了重建（审计记录）。"""
        changed = self._signature != signature
        self.warm(signature, now=now)
        return changed

    @property
    def signature(self) -> Optional[str]:
        return self._signature

    @property
    def warmed_at(self) -> Optional[float]:
        return self._warmed_at
