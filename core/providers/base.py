"""Provider 策略层基类。

一个 Provider 描述"这一族模型和 OpenAI 默认行为有什么不同"，它**不持有
状态**——所有 provider 实例都是无状态单例，会被多个 Agent 并发使用。

新增 provider 的完整流程见
docs/plans/opus5-plan/PHASE-A-MODEL-ADAPTATION-LAYER.md §5。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from ._compat import (
    ANTHROPIC_MESSAGES_TRANSPORT,
    LLMTransport,
    OPENAI_CHAT_TRANSPORT,
    OPENAI_RESPONSES_TRANSPORT,
    ensure_resource_path_rewritable,
    infer_transport_from_resource_path,
    normalize_api_transport,
    normalize_resource_path,
    normalize_transport_candidates as _normalize_transport_candidates,
)

# Keep the historical module-level export for callers and tests that imported
# this helper from ``core.providers.base`` before the compatibility module was
# introduced.
normalize_transport_candidates = _normalize_transport_candidates

# Compatibility constant names keep existing Provider imports stable while
# their values move to the canonical protocol vocabulary.
CHAT_TRANSPORT: LLMTransport = OPENAI_CHAT_TRANSPORT
RESPONSES_TRANSPORT: LLMTransport = OPENAI_RESPONSES_TRANSPORT

# P2 audited 2026-08-25.  These connection presets publish a compatible
# /responses endpoint.  Model-level incompatibility is handled by the narrow
# unsupported-endpoint fallback, never by guessing after auth/policy failures.
_RESPONSES_FIRST_PRESET_IDS = frozenset({"openrouter", "groq", "dashscope"})

class _TransportErrorClass(str, Enum):
    TRANSPORT_UNSUPPORTED = "TRANSPORT_UNSUPPORTED"
    MODEL_ERROR = "MODEL_ERROR"
    REQUEST_VALIDATION = "REQUEST_VALIDATION"
    AUTH_OR_POLICY = "AUTH_OR_POLICY"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    UNKNOWN = "UNKNOWN"


_MODEL_ERROR_RE = re.compile(
    r"\bno such model\b"
    r"|\b(?:unknown|invalid|unsupported)\s+model\b"
    r"|\b(?:requested\s+)?model(?:\s+[\w./:-]+){0,4}\s+"
    r"(?:(?:is|was)\s+)?(?:not found|does not exist)\b"
    r"|\b(?:requested\s+)?model(?:\s+[\w./:-]+){0,4}\s+"
    r"(?:could not|cannot|can't|was not)\s+(?:be\s+)?found\b",
    flags=re.IGNORECASE,
)
_REQUEST_VALIDATION_RE = re.compile(
    r"\b(?:invalid|unsupported|malformed|missing|unknown|unexpected|"
    r"unrecognized|bad)\s+(?:endpoint\s+|request\s+)?"
    r"(?:parameter|param|argument|field|tool(?:\s+schema)?|schema|object)\b"
    r"|\b(?:parameter|param|argument|field|tool(?:\s+schema)?|schema|object)"
    r"(?:\s+[\w./:-]+){0,4}\s+(?:(?:is|was)\s+)?"
    r"(?:invalid|malformed|missing|unknown|not found|does not exist|"
    r"not supported|unsupported)\b"
    r"|\b(?:does not|doesn't|cannot|can't)\s+support\s+(?:the\s+)?"
    r"(?:parameter|param|argument|field|tool(?:\s+schema)?|schema)\b",
    flags=re.IGNORECASE,
)
_TRANSPORT_UNSUPPORTED_RE = re.compile(
    r"(?:\b(?:api\s+(?:endpoint|route)|responses\s+api|"
    r"chat[ _-]?completions\s+api|endpoint|route|protocol"
    r")\b|/(?:v\d+/)?(?:responses|chat/completions))\s+"
    r"(?:(?:is|was)\s+)?(?:not supported|unsupported|not found|unavailable|"
    r"does not exist)\b"
    r"|\bunsupported\s+(?:api\s+(?:endpoint|route)|responses\s+api|"
    r"chat[ _-]?completions\s+api|endpoint|route|protocol)\b",
    flags=re.IGNORECASE,
)
_TRANSPORT_SWITCH_RE = re.compile(
    r"\buse\s+/(?:v\d+/)?(?:chat/completions|responses)\s+instead\b"
    r"|\bswitch\s+to\s+(?:the\s+)?(?:responses\s+api|"
    r"chat[ _-]?completions\s+api|/(?:v\d+/)?(?:responses|chat/completions))\b",
    flags=re.IGNORECASE,
)
_MODEL_TRANSPORT_UNSUPPORTED_RE = re.compile(
    r"\bmodel\b.{0,120}\b(?:does not|doesn't|cannot|can't)\s+support\b"
    r".{0,40}\b(?:responses api|chat[ _-]?completions api)\b",
    flags=re.IGNORECASE,
)
_GENERIC_NOT_FOUND_RE = re.compile(
    r"(?<!resource )(?<!object )(?<!model )(?<!requested )\bnot found\b"
    r"|\binvalid url\b",
    flags=re.IGNORECASE,
)
_AUTH_OR_POLICY_RE = re.compile(
    r"\b(?:api\s+key|credential|authentication|authorization|datapolicy|"
    r"data\s+policy|region|regional|content\s+policy|content\s+safety|"
    r"safety\s+policy)\b",
    flags=re.IGNORECASE,
)
_TRANSIENT_ERROR_RE = re.compile(
    r"\b(?:timed?\s*out|timeout|network\s+error|connection\s+"
    r"(?:error|failed|refused|reset)|dns\s+(?:error|failure))\b",
    flags=re.IGNORECASE,
)


def _transport_error_status(exc: BaseException) -> int | None:
    """Return an HTTP status without depending on one SDK exception class."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _transport_error_text(exc: BaseException) -> str:
    """Collect bounded provider error metadata for classification only."""
    parts = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(str(body))
    response = getattr(exc, "response", None)
    text = getattr(response, "text", None)
    if isinstance(text, str):
        parts.append(text[:1000])
    return " ".join(parts)[:3000]


def _transport_error_request_url(exc: BaseException) -> str:
    """Return the attempted request URL when an SDK exposes it."""
    explicit = getattr(exc, "request_url", None)
    if explicit:
        return str(explicit)
    request = getattr(exc, "request", None)
    if request is None:
        response = getattr(exc, "response", None)
        request = getattr(response, "request", None)
    return str(getattr(request, "url", "") or "")


def _classify_transport_error(exc: BaseException) -> _TransportErrorClass:
    """Classify a provider failure using complete error phrases.

    Bare words such as ``api``, ``model`` or ``parameter`` are deliberately
    not evidence.  Only a named error subject joined to its failure predicate
    determines model, request-validation, or transport classification.
    """
    status = _transport_error_status(exc)
    text = _transport_error_text(exc)

    if status in {401, 403}:
        return _TransportErrorClass.AUTH_OR_POLICY
    if (
        status in {408, 429}
        or (isinstance(status, int) and status >= 500)
        or isinstance(exc, (TimeoutError, ConnectionError))
        or _TRANSIENT_ERROR_RE.search(text)
    ):
        return _TransportErrorClass.TRANSIENT_ERROR
    if _AUTH_OR_POLICY_RE.search(text):
        return _TransportErrorClass.AUTH_OR_POLICY
    if _MODEL_ERROR_RE.search(text):
        return _TransportErrorClass.MODEL_ERROR
    if status in {400, 404, 405, 422} and _MODEL_TRANSPORT_UNSUPPORTED_RE.search(text):
        return _TransportErrorClass.TRANSPORT_UNSUPPORTED
    if _REQUEST_VALIDATION_RE.search(text):
        return _TransportErrorClass.REQUEST_VALIDATION
    if status not in {400, 404, 405, 422}:
        return _TransportErrorClass.UNKNOWN
    if _TRANSPORT_UNSUPPORTED_RE.search(text) or _TRANSPORT_SWITCH_RE.search(text):
        return _TransportErrorClass.TRANSPORT_UNSUPPORTED
    # Generic FastAPI/nginx ``Not Found`` responses are only transport evidence
    # when the SDK also exposes the attempted API resource.  Model/resource
    # errors remain non-fallback because their body is classified above.
    request_url = _transport_error_request_url(exc).casefold()
    if request_url and _GENERIC_NOT_FOUND_RE.search(text):
        if re.search(r"/(?:v\d+/)?responses(?:$|[/?])", request_url):
            return _TransportErrorClass.TRANSPORT_UNSUPPORTED
        if re.search(r"/chat/completions(?:$|[/?])", request_url):
            return _TransportErrorClass.TRANSPORT_UNSUPPORTED
    return _TransportErrorClass.UNKNOWN

try:
    from ...config.model_capabilities import (
        DEFAULT_CAPABILITIES,
        ModelCapabilities,
    )
except ImportError:  # pragma: no cover - repo-root layout (tests)
    from config.model_capabilities import DEFAULT_CAPABILITIES, ModelCapabilities


class BaseProvider:
    """默认实现 == Phase A 之前的 OpenAI 行为。

    子类只覆写真正有差异的方法。任何未被识别的模型都会落到 OpenAIProvider
    （它直接继承本类且不覆写任何东西），因此行为与改造前逐字节一致。
    """

    #: provider 标识，必须与 ModelCapabilities.provider 一致
    name: str = "openai"

    # ---- 识别 ----------------------------------------------------------

    def matches(self, base_url: str, model_name: str) -> bool:
        """本 provider 是否负责该模型。

        注册表按注册顺序询问，第一个返回 True 的胜出；全部返回 False 时
        落到 OpenAIProvider。
        """
        return False

    def _resource_path_candidates(
        self, model_config: dict
    ) -> tuple[LLMTransport, ...] | None:
        resource_path = normalize_resource_path(model_config.get("resource_path"))
        if not resource_path:
            return None
        inferred = infer_transport_from_resource_path(resource_path)
        requested = normalize_api_transport(
            model_config.get("api_transport"), allow_auto=True
        )
        if requested != "auto" and requested != inferred:
            raise ValueError(
                "resource_path does not match api_transport: "
                f"{resource_path} != {requested}"
            )
        ensure_resource_path_rewritable(resource_path, inferred)
        return (inferred,)

    def transport_candidates(
        self, model_config: dict
    ) -> tuple[LLMTransport, ...]:
        """Return API transports in the order the provider wants them tried.

        Chat remains the compatibility default.  A model added through the
        UI's ``Other``/custom provider is deliberately probed Responses-first,
        then Chat, because its Base URL carries no trustworthy preset policy.
        Providers with an official Responses contract override this method.

        ``api_transport`` is an expert escape hatch for imported configs.  It
        chooses the first transport but keeps the other as a safe endpoint-
        mismatch fallback; runtime fallback is still restricted to explicit
        endpoint/protocol unsupported errors before any useful output.
        """
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            return pinned

        explicit = self.explicit_transport_candidates(model_config)
        if explicit is not None:
            return explicit

        provider_id = str(model_config.get("provider_id") or "").casefold()
        if provider_id in _RESPONSES_FIRST_PRESET_IDS | {"custom", "other"}:
            return (RESPONSES_TRANSPORT, CHAT_TRANSPORT)
        return (CHAT_TRANSPORT,)

    def explicit_transport_candidates(
        self, model_config: dict
    ) -> tuple[LLMTransport, ...] | None:
        """Return a canonical explicit override, or ``None`` for auto mode."""
        requested = normalize_api_transport(
            model_config.get("api_transport"), allow_auto=True
        )
        if requested == "auto":
            return None
        if requested == CHAT_TRANSPORT:
            # Explicit Chat is also the emergency compatibility switch.  Do
            # not silently undo an operator's deliberate choice.
            return (CHAT_TRANSPORT,)
        if requested == RESPONSES_TRANSPORT:
            return (RESPONSES_TRANSPORT, CHAT_TRANSPORT)
        if requested == ANTHROPIC_MESSAGES_TRANSPORT:
            return (ANTHROPIC_MESSAGES_TRANSPORT,)
        raise ValueError(f"unsupported api_transport: {requested}")

    def uses_responses_api(self, model_config: dict) -> bool:
        """Compatibility helper: whether the preferred transport is Responses."""
        candidates = self.transport_candidates(model_config)
        return bool(candidates and candidates[0] == RESPONSES_TRANSPORT)

    def should_fallback_transport(
        self,
        exc: BaseException,
        *,
        from_transport: LLMTransport,
        to_transport: LLMTransport,
    ) -> bool:
        """Whether an untouched request may try the alternate API endpoint.

        Only endpoint/protocol mismatch is eligible.  Authentication, policy,
        rate-limit, timeout, server, content-safety, and ordinary request-body
        failures must retain their original error instead of being hidden by a
        second billable request.  AgentV2 separately guarantees that fallback
        is never attempted after text/reasoning/tool output is observed.
        """
        del from_transport, to_transport
        return (
            _classify_transport_error(exc)
            is _TransportErrorClass.TRANSPORT_UNSUPPORTED
        )

    def reasoning_effort_when_disabled(self, model_config: dict) -> str | None:
        """Wire effort for a turn that asks to disable thinking.

        Most models omit the parameter.  Always-reasoning families may return
        their lowest supported effort instead.
        """
        return None

    def validate_tool_payloads(self, tools: list[dict]) -> None:
        """Validate provider-specific function-tool wire constraints.

        The default OpenAI-compatible path imposes no additional policy here.
        Providers should fail before network I/O when an upstream-only limit is
        known; silently truncating a name would break tool-result dispatch.
        """
        return None

    # ---- 能力 ----------------------------------------------------------

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        """推导该模型的能力。

        子类应基于 DEFAULT_CAPABILITIES 做 dataclasses.replace()，
        不要从零构造，否则新增字段时会漏。
        """
        return DEFAULT_CAPABILITIES

    # ---- usage / reasoning 提取 ----------------------------------------

    def extract_cache_read(self, usage: dict, caps: ModelCapabilities) -> int:
        """从 usage 里取"命中前缀缓存的 token 数"。

        取代 core/agent_v2.py::_extract_cache_read 原先盲试两个字段的写法。
        """
        for key in caps.usage_fields.cache_read_flat:
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        for outer, inner in caps.usage_fields.cache_read_nested:
            nested = usage.get(outer)
            if isinstance(nested, dict):
                value = nested.get(inner)
                if isinstance(value, int) and value >= 0:
                    return value
        return 0

    def extract_cache_write(self, usage: dict, caps: ModelCapabilities) -> int:
        """Extract provider-reported prompt-cache creation tokens."""
        for key in caps.usage_fields.cache_write_flat:
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        for outer, inner in caps.usage_fields.cache_write_nested:
            nested = usage.get(outer)
            if isinstance(nested, dict):
                value = nested.get(inner)
                if isinstance(value, int) and value >= 0:
                    return value
        return 0

    def extract_reasoning(self, payload: Any, caps: ModelCapabilities) -> str:
        """从 delta / message 里取推理内容。取代 _extract_reasoning。"""
        if not caps.supports_reasoning:
            return ""
        for key in caps.usage_fields.reasoning:
            value = _get_attr_or_key(payload, key)
            if isinstance(value, str) and value:
                return value
        return ""

    # ---- 构造参数 ------------------------------------------------------

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        """返回传给 ChatOpenAI 的关键字参数。

        Phase 3（M4/ML2/ML5/EXIT.6）：**只接受 resolver 产出的最终值**。
        调用方（agent_v2._build_llm_from_config）负责把
        ``OutputLimitResolution.resolved_max_tokens`` 写入 ``model_config``；
        本方法不自行解析、不读取 raw ``max_tokens``、不 fallback。
        缺少 ``resolved_max_tokens`` → 抛 ValueError（禁止绕过 resolver）。
        """
        resolved = model_config.get("resolved_max_tokens")
        if not isinstance(resolved, int) or resolved <= 0:
            raise ValueError(
                "llm_kwargs requires resolved_max_tokens (positive int) from "
                "OutputLimitResolution; call resolve_configured_max_tokens() "
                "first (Phase 3 M4/EXIT.6). Got resolved_max_tokens="
                f"{resolved!r}"
            )
        max_tokens = resolved
        api_key = model_config.get("api_key")
        # Reject explicit empty credentials (the OpenAI SDK Missing-credentials
        # path). Omit/None is left to callers / unit tests that only assert
        # kwargs shape; production always pre-checks via _build_llm_from_config.
        if isinstance(api_key, str) and not api_key.strip():
            raise ValueError(
                "llm_kwargs requires a non-empty api_key; resolve credentials "
                "before constructing ChatOpenAI (do not pass '')."
            )
        kwargs: dict[str, Any] = {
            "model": model_config.get("model_name", "gpt-4o"),
            "api_key": api_key,
            "base_url": model_config.get("base_url"),
            "max_tokens": max_tokens,
            "max_retries": 3,
            "streaming": True,
            "stream_usage": True,
        }
        if caps.accepts_temperature:
            kwargs["temperature"] = model_config.get("temperature", 0.7)
        if caps.extra_body:
            kwargs["extra_body"] = dict(caps.extra_body)
        if self.uses_responses_api(model_config):
            # ChatOpenAI owns Responses request construction and SSE parsing.
            # RxyCode only selects the transport and normalizes public chunks.
            kwargs["use_responses_api"] = True
        # A21: thinking 适配判断——supports_reasoning + thinking_default_on 的模型
        # 默认注入 thinking enabled（extra_body）；effort_presets 非空时按档位注入
        # reasoning_effort（顶层）。各 provider 覆写传输位置时调用 super() 继承；
        # 若 provider 已显式设置 thinking，不覆盖其传输位置。
        # /effort 扩展（2026-08-12）：effort 值命中 caps.effort_options（厂商
        # 档位全集，用户经 /effort 直接选择）时**直接透传**该值；否则仍走
        # effort_presets 抽象映射（fast/balanced/deep，Phase F 难度路由用）。
        if caps.supports_reasoning and caps.thinking_default_on:
            # ``thinking`` is a Chat-Completions-only compatibility field.
            # Responses uses the standard top-level ``reasoning_effort``;
            # keep that mapping below even when the preferred transport is
            # Responses-first.
            if not self.uses_responses_api(model_config):
                body = kwargs.setdefault("extra_body", {})
                if "thinking" not in body:
                    body["thinking"] = {"type": "enabled"}
            effort = str(model_config.get("effort") or "balanced")
            options = caps.effort_options or ()
            if effort in options:
                kwargs["reasoning_effort"] = effort
            else:
                preset = (caps.effort_presets or {}).get(effort)
                if preset is not None:
                    kwargs["reasoning_effort"] = preset
        return kwargs

    def supports_prompt_cache(self, caps: ModelCapabilities) -> bool:
        """是否往消息上注入 cache_control。对应 agent_v2.py:411-441。"""
        return caps.supports_prompt_cache

    def cache_params(self, caps: ModelCapabilities) -> dict:
        """该模型族的缓存参数包，供消息链注入与命中率监控使用。

        返回键固定为：min_block_tokens / ttl_s / breakpoints / hit_field_flat /
        hit_field_nested。默认值 = "不适用"，各 provider 按 §7.X 覆写。
        断点布局在此校验（§7.8：>4 / 乱序 / 动态块 → ValueError）。
        """
        self.validate_breakpoints(caps.cache_breakpoints)
        return {
            "min_block_tokens": caps.cache_min_block_tokens,
            "ttl_s": caps.cache_ttl_s,
            "breakpoints": list(caps.cache_breakpoints),
            "hit_field_flat": list(caps.usage_fields.cache_read_flat),
            "hit_field_nested": list(caps.usage_fields.cache_read_nested),
        }

    def validate_breakpoints(self, breakpoints: tuple[str, ...]) -> None:
        """校验 Anthropic 系显式 cache_control 断点布局（A19）。

        规则（§7.8 A3 / 常见坑）：
          - 最多 4 个；
          - 只允许打在恒定内容末尾，按"静态在前、动态在后"排序；
          - 合法取值：tools → system → session_static → tail（前缀顺序）。
        非法布局抛 ValueError；空元组 = 不用显式断点，合法。
        """
        allowed = ("tools", "system", "session_static", "tail")
        if len(breakpoints) > 4:
            raise ValueError(
                f"breakpoint count {len(breakpoints)} > 4 (Anthropic limit)"
            )
        if not all(b in allowed for b in breakpoints):
            raise ValueError(
                f"breakpoints contain non-static block: {breakpoints!r}; "
                "only tools/system/session_static/tail allowed, static-first"
            )
        order = {name: i for i, name in enumerate(allowed)}
        if any(
            order[breakpoints[i]] >= order[breakpoints[i + 1]]
            for i in range(len(breakpoints) - 1)
        ):
            raise ValueError(
                f"breakpoints out of order or tail-mid: {breakpoints!r}; "
                "must be tools->system->session_static->tail"
            )


def _get_attr_or_key(obj: Any, key: str) -> Any:
    """OpenAI SDK 的 delta 有时是对象、有时是 dict，两种都要能取。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
