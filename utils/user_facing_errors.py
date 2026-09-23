"""Map internal agent errors to user-facing Chinese messages."""

from __future__ import annotations

MSG_BUILD_INCOMPLETE = (
    "构建流程未完成，部分步骤未通过验证。请查看任务详情后重试。"
)
MSG_GROUNDING = (
    "最终回答未能通过校验，内容与已验证结果不一致。请重试或简化任务。"
)
MSG_TOOL_INTERRUPTED = "工具执行中断，未能完成所需操作。请重试。"
MSG_TOOL_REJECTED = (
    "用户拒绝了该命令，未执行。如需打开新的 CMD 窗口，请在审批弹窗中选择允许。"
)
MSG_TIMEOUT = (
    "模型响应超时：网络可能不稳定。传输错误与首包超时已自动重试；"
    "若仍失败请检查网络连接后重试。"
)
MSG_MODEL_PAUSED = (
    "这一窗口的模型调用已暂停：连续连接失败后进入冷却，不是限流 429。"
    "冷却结束会自动再连，不用关掉窗口。"
)
MSG_CANCELLED = "操作已取消。"
MSG_DEFAULT = "处理未完成，请重试。"

_GROUNDING_MARKERS = (
    "grounded claim",
    "claim manifest",
    "synthesis manifest",
    "synthesizer",
    "grounding failed",
    "verified synthesis",
    "verbatim source",
)


def _extract_error_detail(raw: str) -> str:
    """从原始错误中提取用户可读的关键信息（错误类型 + 简短描述）。

    2026-09-23：用户报告「工具执行中断」「模型调用已暂停」太模糊，
    不知道发生了什么、该怎么办。现在在网络/超时类错误后面附上原始信息。
    注意：grounding/synthesizer 类错误的原始信息全是内部术语，不附。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    # grounding/synthesizer 类错误的原始信息全是内部术语，不附
    lowered = text.lower()
    if any(marker in lowered for marker in _GROUNDING_MARKERS):
        return ""
    # 取第一行（通常包含错误类型和描述）
    first_line = text.split("\n")[0].strip()
    # 去掉常见的内部前缀
    for prefix in ("[error executing ", "[error: ", "[error "):
        if first_line.lower().startswith(prefix.lower()):
            first_line = first_line[len(prefix):]
            break
    # 截断到合理长度
    if len(first_line) > 120:
        first_line = first_line[:117] + "..."
    return first_line


def to_user_facing_error(raw: str) -> str:
    """Return a short Chinese message without internal jargon.

    2026-09-23：每条消息后面附上原始错误的关键信息（_extract_error_detail），
    让用户知道具体是什么错了、该怎么办。
    """
    text = str(raw or "").strip()
    if not text:
        return MSG_DEFAULT

    detail = _extract_error_detail(text)
    suffix = f"\n原因：{detail}" if detail else ""

    lowered = text.lower()

    if "cancel" in lowered and (
        lowered == "cancelled"
        or "cancellederror" in lowered
        or lowered.startswith("cancel")
    ):
        return MSG_CANCELLED

    # 熔断冷却的英文里有 Timeout。必须先于下面的通用超时判断。
    # 废弃代码（2026-09-22）：看到 timeout 就显示「请求超时」，
    # 熔断拒绝也被说成请求超时。
    if "circuit breaker" in lowered or "模型调用已暂停" in text:
        return MSG_MODEL_PAUSED + suffix

    if "timeout" in lowered or "timed out" in lowered:
        return MSG_TIMEOUT + suffix

    # 2026-09-23：内部时钟文案不含 "timeout" 字样，曾漏映射成 MSG_DEFAULT，
    # 造成「报错不固定」（用户报告）。三条时钟文案：
    #   "provider produced no first response event before the deadline"
    #   "provider stopped producing stream events before the idle deadline"
    #   "provider connect handshake exceeded the connect deadline"
    if "deadline" in lowered or "first response" in lowered:
        return MSG_TIMEOUT + suffix

    # 证据失败必须先于「用户拒绝」。evidence 文案里的 no verified WRITE
    # 不是审批拒绝。
    if lowered.startswith("[evidence failed") or (
        "did not complete" in lowered and "tool" in lowered
    ):
        return MSG_TOOL_INTERRUPTED + suffix

    if "rejected by user" in lowered:
        return MSG_TOOL_REJECTED + suffix

    # 废弃代码（2026-09-22）：下面这句会把
    # "[evidence failed: ... no verified WRITE ...]" 误译成「用户拒绝了该命令」。
    # full_auto 当时并没有弹审批。禁止再把 no verified write 当成拒绝。
    # if "rejected by user" in lowered or "no verified write" in lowered:
    #     return MSG_TOOL_REJECTED

    if any(marker in lowered for marker in _GROUNDING_MARKERS):
        return MSG_GROUNDING + suffix

    if lowered.startswith("[build incomplete"):
        return MSG_BUILD_INCOMPLETE + suffix

    return MSG_DEFAULT + suffix
