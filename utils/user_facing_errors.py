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
MSG_TIMEOUT = "请求超时，请稍后重试。"
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


def to_user_facing_error(raw: str) -> str:
    """Return a short Chinese message without internal jargon."""
    text = str(raw or "").strip()
    if not text:
        return MSG_DEFAULT

    lowered = text.lower()

    if "cancel" in lowered and (
        lowered == "cancelled"
        or "cancellederror" in lowered
        or lowered.startswith("cancel")
    ):
        return MSG_CANCELLED

    if "timeout" in lowered or "timed out" in lowered:
        return MSG_TIMEOUT

    if "rejected by user" in lowered or "no verified write" in lowered:
        return MSG_TOOL_REJECTED

    if lowered.startswith("[evidence failed") or (
        "did not complete" in lowered and "tool" in lowered
    ):
        return MSG_TOOL_INTERRUPTED

    if any(marker in lowered for marker in _GROUNDING_MARKERS):
        return MSG_GROUNDING

    if lowered.startswith("[build incomplete"):
        return MSG_BUILD_INCOMPLETE

    return MSG_DEFAULT
