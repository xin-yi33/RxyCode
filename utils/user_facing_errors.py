"""Map internal agent errors to user-facing Chinese messages."""

from __future__ import annotations

import re

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

#: 稳定的运行级错误码：服务商已下架/改名/停用当前模型（HTTP 404/410、
#: ModelDeprecated、model_not_found、"does not exist"）。web 用它决定
#: 失败 run 是否给「切换模型」动作；与 drain 的凭证拒绝复用同一 code。
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"

# 服务商把模型下线时各家的原始文案形态：
#   APIStatusError: Error code: 410 - {'error': {'type': 'ModelDeprecated', ...}}
#   NotFoundError: Error code: 404 - {'error': {'type': 'model_not_found'}}
#   "The model `x` does not exist"
# 自带模型语境的硬标记；「does not exist」/裸 404|410 必须另有
# model/模型 字样才认 —— 「Expected artifact does not exist」这类
# 构建产物缺失绝不能误判成模型下线。
_MODEL_GONE_TEXT_MARKERS = (
    "modeldeprecated",
    "model_not_found",
)
_MODEL_GONE_GENERIC_MARKERS = (
    "does not exist",
)
_MODEL_GONE_STATUS = re.compile(r"\b(404|410)\b")

# 从原始错误里捞模型 id。覆盖三类常见形态：
#   'message': 'Model deepseek-flash is deprecated'
#   "The model `gpt-x` does not exist"
#   {'error': {'model': 'deepseek-flash'}}
_MODEL_NAME_PATTERNS = (
    re.compile(r"[Mm]odel [`'\"]([\w./-]+)[`'\"]"),
    re.compile(
        r"[Mm]odel ([A-Za-z0-9][\w./-]*?)\s+"
        r"(?:is|was|does|has been|no longer|deprecated|not)",
    ),
    re.compile(r"['\"]model['\"]\s*:\s*['\"]([\w./-]+)['\"]"),
    # 我们自己的文案：「模型 deepseek-flash 已被服务商…停用」
    re.compile(r"模型 ([\w./-]+) 已被"),
)

_MODEL_UNAVAILABLE_HEAD = re.compile(r"^(模型 \S|当前模型)")
_MODEL_PROVIDER_HEAD = re.compile(r"服务商（([^）]+)）")

# 每条面向用户文案的首子句 —— user_facing_kind 用它做幂等识别与终态分类。
_USER_FACING_HEADS = tuple(
    msg.split("，")[0].split("：")[0].split("。")[0]
    for msg in (
        MSG_BUILD_INCOMPLETE,
        MSG_GROUNDING,
        MSG_TOOL_INTERRUPTED,
        MSG_TOOL_REJECTED,
        MSG_TIMEOUT,
        MSG_MODEL_PAUSED,
        MSG_DEFAULT,
        "您没有额度了",
    )
)

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
    # grounding/synthesizer / evidence 门的原文是内部术语，不附给用户。
    lowered = text.lower()
    if lowered.startswith("[evidence failed") or "evidence failed" in lowered:
        return ""
    if any(marker in lowered for marker in _GROUNDING_MARKERS):
        return ""
    # 含 grounded/manifest 的行同样是内部术语，不附
    if "grounded" in lowered or "manifest" in lowered:
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


def is_model_unavailable(raw: str) -> bool:
    """原始错误是否表示模型已被服务商下线/改名/停用。"""
    text = str(raw or "")
    lowered = text.lower()
    if any(marker in lowered for marker in _MODEL_GONE_TEXT_MARKERS):
        return True
    # 泛化标记必须有模型语境 —— 「file/artifact does not exist」
    # 和资源类 404 不是模型问题。
    mentions_model = "model" in lowered or "模型" in text
    if not mentions_model:
        return False
    if any(marker in lowered for marker in _MODEL_GONE_GENERIC_MARKERS):
        return True
    return bool(_MODEL_GONE_STATUS.search(text))


def _extract_model_name(text: str) -> str:
    for pattern in _MODEL_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def model_unavailable_message(model_name: str = "", provider_name: str = "") -> str:
    """模型停用的人话。服务商名未知时省略括号，不编造。"""
    provider = f"（{provider_name}）" if provider_name else ""
    if model_name:
        return (
            f"模型 {model_name} 已被服务商{provider}停用，"
            "请在模型选择中换一个模型后重试。"
        )
    return f"当前模型已被服务商{provider}停用，请在模型选择中换一个模型后重试。"


def classify_user_error(
    raw: str,
    *,
    model_name: str = "",
    provider_name: str = "",
) -> dict[str, str] | None:
    """模型停用 → 结构化错误信息（code/可读文案/模型/服务商/原文）。

    agent 把异常吞成字符串返回值时，结构化信息经此附在
    ``AgentV2._last_turn_error`` / ``PromptResult.error_code`` 上，
    worker 终态化时写进 ``run.error`` 事件的 ``code``/``raw`` 载荷 —
    界面凭 code 给「切换模型」动作、凭 raw 给可展开的「详情」。
    """
    text = str(raw or "").strip()
    if not text:
        return None
    head = text.split("\n", 1)[0]
    own_message = bool(_MODEL_UNAVAILABLE_HEAD.match(head)) and "停用" in head
    if not own_message and not is_model_unavailable(text):
        return None
    model = model_name or _extract_model_name(text)
    provider = provider_name
    if not provider:
        match = _MODEL_PROVIDER_HEAD.search(head)
        provider = match.group(1) if match else ""
    return {
        "code": MODEL_UNAVAILABLE,
        "model": model,
        "provider": provider,
        "message": model_unavailable_message(model, provider),
        "raw": text[:1500],
    }


def user_facing_kind(text: str) -> str | None:
    """文本已是我们的用户可读错误文案时返回终态类别，否则 None。

    ``to_user_facing_error`` 的输出全部代表失败（除「操作已取消」）。
    classify_agent_result 据此把吞成字符串的错误正确判成 failed —
    2026-10-28 现场：410 ModelDeprecated 经 MSG_DEFAULT 返回后被
    classify 当成成功文本，run 终态被写成「已完成」。
    """
    head = str(text or "").strip().split("\n", 1)[0]
    if not head:
        return None
    if head.startswith(MSG_CANCELLED.split("。")[0]):
        return "cancelled"
    if any(head.startswith(prefix) for prefix in _USER_FACING_HEADS):
        return "failed"
    if (head.startswith("模型 ") or head.startswith("当前模型")) and "停用" in head:
        return "failed"
    return None


def to_user_facing_error(
    raw: str,
    *,
    model_name: str = "",
    provider_name: str = "",
) -> str:
    """Return a short Chinese message without internal jargon.

    2026-09-23：每条消息后面附上原始错误的关键信息（_extract_error_detail），
    让用户知道具体是什么错了、该怎么办。
    """
    text = str(raw or "").strip()
    if not text:
        return MSG_DEFAULT

    # 幂等：输入已是本模块产出的文案（例如 classify 后的 detail）就直接返回，
    # 不再套一层「处理未完成，请重试。」。
    if user_facing_kind(text) is not None:
        return text

    detail = _extract_error_detail(text)
    suffix = f"\n原因：{detail}" if detail else ""

    lowered = text.lower()

    # BYOK: our server does not meter the user. Only an upstream 403 that
    # says the key itself has no credits becomes this sentence.
    if re.search(r"\b403\b", lowered) and any(
        mark in lowered
        for mark in (
            "insufficient_quota",
            "insufficient quota",
            "quota",
            "billing",
            "out of credits",
            "no quota",
            "余额不足",
            "额度不足",
            "额度已用",
        )
    ):
        return "您没有额度了"

    if "cancel" in lowered and (
        lowered == "cancelled"
        or "cancellederror" in lowered
        or lowered.startswith("cancel")
    ):
        return MSG_CANCELLED

    # 模型被服务商下线（410 ModelDeprecated / 404 model_not_found）：
    # 人话里不带原始报文 —— 原文由 run.error 的 raw 载荷折叠进「详情」。
    info = classify_user_error(
        text, model_name=model_name, provider_name=provider_name
    )
    if info is not None:
        return str(info["message"])

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
