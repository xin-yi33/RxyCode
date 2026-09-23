"""Anthropic Claude provider（原生 Messages + 兼容代理策略）。

与 OpenAI 默认行为的差异以 A0 批 8 调研报告（§7.8，2026-08-02 三方审计通过）为准：
  - prompt 缓存需显式 ``cache_control``（ephemeral / automatic），与 OpenAI 的
    自动隐式缓存不同；usage 命中字段为顶层 ``cache_read_input_tokens``、
    写入字段为顶层 ``cache_creation_input_tokens``
  - thinking 在 ``content[]`` 的 ``type: "thinking"`` 块（含 signature），
    非 ``reasoning_content``
  - Claude 5（Opus/Sonnet/Fable）默认开 adaptive thinking；**Opus 4.8** 默认关、
    须显式 ``thinking:{type:"adaptive"}``（type:enabled → 400）；**Haiku 4.5** 仅
    extended（显式 enabled + budget_tokens）
  - 无官方 tiktoken → 用 ``chars:3.0`` 启发式（精确走 messages.count_tokens；A5 前）

传输边界：精确的 Anthropic 官方 Host 使用 ``langchain-anthropic`` 原生 Messages；
其他 Claude 代理仍由其公开的 OpenAI-compatible 契约决定，默认保持 Chat。原生路径
由成熟集成负责鉴权、content block、tool use 和 SSE，RxyCode 只归一公开 chunk。
兼容端点的能力边界（无 prompt caching / thinking 细节不完整）仍按真实端点行为处理。

**端点边界（A18 判据 3，可核验说明）**：
- 原生端点 ``https://api.anthropic.com``（hostname 精确匹配、仅 HTTPS）→
  ``supports_prompt_cache=True``（cache_control ephemeral，§7.8 A3）；
- OpenAI 兼容 / 中转 / 伪原生子串（api.anthropic.com.evil.example、proxy path
  含 api.anthropic.com、http/ftp）→ ``supports_prompt_cache=False``，不注入
  cache_control（A6：兼容层不支持 prompt caching；Luna rev5-7 端点感知）；
- thinking 走 content blocks（含 signature）：``llm_kwargs`` 不注入
  ``extra_body.thinking: {"type":"enabled"}``（Claude 5 adaptive 默认开；
  Opus 4.8 用 enabled 会 400）；用户显式 ``thinking`` 配置（Opus 4.8
  adaptive、Haiku extended enabled+budget_tokens）原样透传；
- 非默认采样（temperature≠1.0 / top_p≠1.0 / top_k 非空）显式传入顶层或
  ``extra_body`` → ValueError（§7.8：HTTP 400）。

数值来源（A0 §7.8）：
  - https://docs.anthropic.com/en/docs/about-claude/models/overview
  - https://docs.anthropic.com/en/docs/about-claude/pricing
  - https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
  - https://docs.anthropic.com/en/docs/build-with-claude/thinking
  - https://docs.anthropic.com/en/docs/build-with-claude/token-counting
  - https://docs.anthropic.com/en/api/messages
  - https://docs.anthropic.com/en/api/openai-sdk
"""

from __future__ import annotations

from dataclasses import replace

try:
    from ...config.model_capabilities import (
        DEFAULT_CAPABILITIES,
        ModelCapabilities,
        ModelPricing,
        UsageFieldMap,
    )
except ImportError:  # pragma: no cover - repo-root layout (tests)
    from config.model_capabilities import (
        DEFAULT_CAPABILITIES,
        ModelCapabilities,
        ModelPricing,
        UsageFieldMap,
    )
from .base import ANTHROPIC_MESSAGES_TRANSPORT, BaseProvider

from ._compat import canonical_model_id, llm_client_base_url

_ANTHROPIC_USAGE = UsageFieldMap(
    # §7.8 ③：原始 SDK usage 是顶层字段；LangChain UsageMetadata 将
    # cache_read/cache_creation 放入 input_token_details。
    cache_read_flat=("cache_read_input_tokens",),
    cache_read_nested=(("input_token_details", "cache_read"),),
    cache_write_flat=("cache_creation_input_tokens",),
    cache_write_nested=(
        ("input_token_details", "cache_creation"),
        ("input_token_details", "cache_creation_input_tokens"),
    ),
    # Native thinking blocks are normalized by AgentV2 to the stable internal
    # ``delta.reasoning_content`` field consumed by the TUI and tool loop.
    reasoning=("reasoning_content",),
)

# §7.8 A1：Opus/Sonnet 5/Fable/Opus 4.8 为 1M；Haiku 4.5 / Sonnet 4.5 为 200k
_CONTEXT_WINDOW_DEFAULT = 1_000_000
_CONTEXT_WINDOW_200K = 200_000
_CONTEXT_WINDOW_HAIKU = _CONTEXT_WINDOW_200K
# §7.8 A1：输出 128k（Haiku 64k）；Sonnet 4.5 不继承 Sonnet 5 的 128k
_MAX_OUTPUT_DEFAULT = 128_000
_MAX_OUTPUT_HAIKU = 64_000
_MAX_OUTPUT_SONNET_45 = 64_000
# RxyCode 项目约定：compaction_threshold ≈ context 的 90%（同 A3 §7.1 / DeepSeek 卡；
# 非 Anthropic 官方文档数值）
_COMPACTION_RATIO = 0.9

# §7.8 问 7：定价按型号分条（USD / 1M；as_of=2026-08-02；source_url=A2）。
# 5m / 1h cache write 单价（写入价 = 1.25×/2× base input）经 ModelPricing 的
# cache_write_per_mtok 承载（填 5m 档）；cache_creation 由 usage 字段采集。
# Sonnet 5 取至 2026-08-31 入门价（§7.8 问 7）。
_ANTHROPIC_PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(
        input_per_mtok=5.0,
        output_per_mtok=25.0,
        cached_input_per_mtok=0.50,
        cache_write_per_mtok=6.25,  # 5m cache write（1.25×）
        as_of="2026-08-02",
        source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
    ),
    "claude-sonnet-5": ModelPricing(
        input_per_mtok=2.0,
        output_per_mtok=10.0,
        cached_input_per_mtok=0.20,
        cache_write_per_mtok=2.50,  # 5m cache write（1.25×）
        as_of="2026-08-02",
        source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
    ),
    "claude-fable-5": ModelPricing(
        input_per_mtok=10.0,
        output_per_mtok=50.0,
        cached_input_per_mtok=1.00,
        cache_write_per_mtok=12.50,  # 5m cache write（1.25×）
        as_of="2026-08-02",
        source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
    ),
    "claude-opus-4-8": ModelPricing(
        input_per_mtok=5.0,
        output_per_mtok=25.0,
        cached_input_per_mtok=0.50,
        cache_write_per_mtok=6.25,  # 5m cache write（1.25×）
        as_of="2026-08-02",
        source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
    ),
    "claude-haiku-4-5": ModelPricing(
        input_per_mtok=1.0,
        output_per_mtok=5.0,
        cached_input_per_mtok=0.10,
        cache_write_per_mtok=1.25,  # 5m cache write（1.25×）
        as_of="2026-08-02",
        source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
    ),
    # Distinct from Sonnet 5.  Leave prices unset until this id is re-audited.
    "claude-sonnet-4-5": ModelPricing(
        input_per_mtok=None,
        output_per_mtok=None,
        cached_input_per_mtok=None,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
    ),
}

#: 未调研型号 → 价格显式 None（来源 URL 仍在），不得静默当 0。
_DEFAULT_ANTHROPIC_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://docs.anthropic.com/en/docs/about-claude/pricing",
)

#: 调研覆盖的五主力（§7.8 问 1；Opus 4.8 不得省略）。
_ANTHROPIC_FAMILY = {
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-sonnet-4-5",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-haiku-4-5",
}

#: §7.8 问 5（A4）：非默认 temperature/top_p/top_k 一律 400 的型号集合
#: Fable / Mythos / Preview / Opus 5 / 4.8 / 4.7 / Sonnet 5（及同代 4.6/4.5 族）。
#: 用函数判断（前缀覆盖），避免手工枚举遗漏（Luna rev13）。Haiku 不在 400 清单。
#: §7.8 问 5（A4「Limits and feature compatibility」原文）：非默认
#: temperature/top_p/top_k 一律 400 的型号——Fable / Mythos / Preview /
#: Opus 5 / Opus 4.8 / Opus 4.7 / Sonnet 5。只列报告明确型号；4.6/4.5 及
#: 未调研变体不继承该契约（DC1 保守，Luna rev13/rev14）。
_SAMPLING_RESTRICTED = frozenset(
    {
        "claude-fable-5",
        "claude-mythos-5",
        "claude-mythos-5-preview",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
    }
)


def _sampling_restricted(model_name: str) -> bool:
    """§7.8 问 5（A4）：该型号是否受"非默认采样一律 400"契约约束。
    仅报告明确列出的型号；旧代（claude-opus-3）与未调研变体不受限（DC1）。"""
    return canonical_model_id("anthropic", model_name) in _SAMPLING_RESTRICTED


def _family(model_name: str) -> str | None:
    """返回调研覆盖的型号规范名；未覆盖返回 None。"""
    name = canonical_model_id("anthropic", model_name)
    if name in _ANTHROPIC_FAMILY:
        return name
    return None


def _context_window(family: str) -> int:
    if family in {"claude-haiku-4-5", "claude-sonnet-4-5"}:
        return _CONTEXT_WINDOW_200K
    return _CONTEXT_WINDOW_DEFAULT


def _max_output(family: str) -> int:
    if family == "claude-haiku-4-5":
        return _MAX_OUTPUT_HAIKU
    if family == "claude-sonnet-4-5":
        return _MAX_OUTPUT_SONNET_45
    return _MAX_OUTPUT_DEFAULT


def _thinking_default_on(family: str) -> bool:
    """§7.8 问 5：Claude 5（Opus/Sonnet/Fable）默认开；Opus 4.8 默认关
    （须显式 adaptive）；Haiku 4.5 仅 extended（显式 enabled）。"""
    return family in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5")


def _cache_min_block(family: str) -> int:
    """§7.8 问 4（A3 最小可缓存长度，按型号）：Fable/Opus 5=512；
    Opus 4.8/Sonnet 5=1024；Haiku 4.5=4096。"""
    if family in ("claude-fable-5", "claude-opus-5"):
        return 512
    if family == "claude-haiku-4-5":
        return 4096
    return 1024


def _pricing_for(family: str | None) -> ModelPricing:
    if family is None:
        return _DEFAULT_ANTHROPIC_PRICING
    return _ANTHROPIC_PRICING.get(family, _DEFAULT_ANTHROPIC_PRICING)


def _prompt_variant(model_name: str) -> str:
    # 未调研变体保持 DEFAULT_CAPABILITIES.prompt_variant（"default"），与 A12–A17 一致
    family = _family(model_name)
    return "claude" if family is not None else "default"


def _is_native_anthropic_host(base_url: str) -> bool:
    """§7.8 A6：原生 Messages 端点为 https://api.anthropic.com（端口 443 或未指定）。
    防伪原生子串注入（api.anthropic.com.evil.example / proxy path 含
    api.anthropic.com / http/ftp / 非标准端口均不得匹配，Luna rev6/rev7/rev13）。"""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        if parsed.scheme != "https":  # 原生 Messages 仅 HTTPS
            return False
        if (parsed.hostname or "").lower() != "api.anthropic.com":
            return False
        port = parsed.port
        return port is None or port == 443
    except ValueError:  # 畸形 URL：保守按非原生
        return False


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        """Use native Messages only for Anthropic's exact official host."""
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            return pinned
        if _is_native_anthropic_host(
            str(model_config.get("base_url") or "")
        ):
            explicit = self.explicit_transport_candidates(model_config)
            if explicit is None:
                return (ANTHROPIC_MESSAGES_TRANSPORT,)
            if explicit != (ANTHROPIC_MESSAGES_TRANSPORT,):
                raise ValueError(
                    "native Anthropic endpoints require "
                    "api_transport=anthropic_messages"
                )
            return explicit
        return super().transport_candidates(model_config)

    def anthropic_llm_kwargs(
        self, model_config: dict, caps: ModelCapabilities
    ) -> dict:
        """Translate Provider policy into ``ChatAnthropic`` constructor args."""
        policy = self.llm_kwargs(model_config, caps)
        kwargs = {
            "model": policy["model"],
            "api_key": policy.get("api_key"),
            "base_url": llm_client_base_url(
                str(policy.get("base_url") or ""),
                ANTHROPIC_MESSAGES_TRANSPORT,
            ),
            "max_tokens": policy["max_tokens"],
            "max_retries": policy.get("max_retries", 3),
            "streaming": True,
            "stream_usage": True,
        }
        if "temperature" in policy:
            kwargs["temperature"] = policy["temperature"]

        body = policy.get("extra_body") or {}
        if isinstance(body, dict):
            for key in ("thinking", "top_k", "top_p", "output_config"):
                if key in body:
                    kwargs[key] = body[key]
        return kwargs

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        """§7.8 问 5 / A21：Anthropic 的 thinking 在 content blocks（含 signature），
        不走 OpenAI 兼容的顶层 ``reasoning_effort``，也不由 base 注入
        ``extra_body.thinking: {"type":"enabled"}``（A21 注记：Anthropic 走
        content block，不注入 extra_body.thinking；且 Opus 4.8 用 type:enabled
        会 400，Claude 5 adaptive 默认开无需配置）。

        本覆写：
        - 用户显式传入 ``model_config["extra_body"]["thinking"]`` → **完全尊重**
          （Haiku 4.5 合法配置 ``enabled + budget_tokens``、Opus 4.8 开启须
          ``adaptive``），不误删；若 Opus 4.8 显式传 ``enabled`` 则保留原样，
          由 API 返回 400（§7.8 400 契约，不静默改写）；
        - 用户未显式指定 thinking → 移除 base 对 thinking_default_on=True
          自动注入的 ``type:"enabled"``（Claude 5 adaptive 默认开无需配置）；
        - 显式传非默认 ``temperature/top_p/top_k`` → 拒绝（§7.8：非默认采样
          一律 400）；
        - 移除 ``reasoning_effort``（Anthropic 无此参数）。
        """
        kwargs = super().llm_kwargs(model_config, caps)
        kwargs.pop("reasoning_effort", None)

        model_name = str(model_config.get("model_name") or "").lower()
        user_body = model_config.get("extra_body")
        if not isinstance(user_body, dict):
            user_body = {}

        # §7.8 ③：Anthropic 无 reasoning_effort 参数（thinking 走 content block /
        # output_config.effort）——顶层与合并后 extra_body 内均移除，防止绕过（Luna rev8/rev9）。
        if "reasoning_effort" in user_body:
            user_body = dict(user_body)
            user_body.pop("reasoning_effort", None)

        # §7.8 问 5：非默认 temperature/top_p/top_k 一律 400（与是否 thinking 无关）。
        # 该契约适用于 §7.8 A4 列出的型号（Fable/Mythos/Preview/Opus 4.5+/Sonnet 4.5+）；
        # 其他未知变体保持 DEFAULT 行为，可传自定义采样（DC1，Luna rev10/rev11/rev13）。
        if _sampling_restricted(model_name):
            merged_sampling = {}
            for src in (model_config, user_body):
                for key in ("temperature", "top_p", "top_k"):
                    if key in src:
                        merged_sampling[key] = src[key]
            for key, value in merged_sampling.items():
                # §7.8：仅"非默认值"一律 400；显式传 Anthropic 默认值放行。
                # 默认值定义：temperature=1.0、top_p=1.0、top_k 官方默认即不传（None=未设）。
                default_ok = (
                    (key == "temperature" and value == 1.0)
                    or (key == "top_p" and value == 1.0)
                    or (key == "top_k" and value is None)
                )
                if default_ok:
                    continue
                raise ValueError(
                    f"anthropic: {key} must be left at default "
                    f"(custom sampling rejected with HTTP 400 per §7.8)"
                )

        has_user_thinking = "thinking" in user_body
        if has_user_thinking:
            # 显式传入（含 None 也原样保留，由调用方/API 校验层处理）→ 完全尊重。
            # 唯一入口约定：显式 thinking 配置通过 model_config["extra_body"]["thinking"]
            # 传入（项目无顶层 "thinking" 键约定，A21 由能力字段驱动默认注入）。
            # §7.8 问 5（A4「关闭」行原文）：**Fable/Mythos 拒绝 disabled**（HTTP 400）。
            if (
                model_name == "claude-fable-5"
                and isinstance(user_body["thinking"], dict)
                and user_body["thinking"].get("type") == "disabled"
            ):
                raise ValueError(
                    "anthropic: claude-fable-5 thinking cannot be disabled "
                    "(HTTP 400 per §7.8)"
                )
            body = dict(kwargs.get("extra_body") or {})
            body["thinking"] = user_body["thinking"]
            kwargs["extra_body"] = body
        # 合并用户其他显式 extra_body 键——用户值优先（覆盖 base 生成的同键默认值，
        # Luna rev17 Minor；thinking 已单独处理，采样键对受限型号不注入）。
        # 无用户 thinking 时，此处统一从当前 extra_body 拷贝并移除 base 注入的
        # thinking.enabled / reasoning_effort（单一处理点，避免重复 else 分支）。
        if user_body:
            body = dict(kwargs.get("extra_body") or {})
            strip_sampling = _sampling_restricted(model_name)
            for key, value in user_body.items():
                if key == "thinking":
                    continue
                if key in ("temperature", "top_p", "top_k") and strip_sampling:
                    continue
                body[key] = value  # 用户值优先（覆盖 base 生成的同键默认值）
            body.pop("reasoning_effort", None)
            if not has_user_thinking:
                body.pop("thinking", None)
            kwargs["extra_body"] = body
        else:
            body = dict(kwargs.get("extra_body") or {})
            if not has_user_thinking:
                body.pop("thinking", None)
            body.pop("reasoning_effort", None)
            # 强制重新赋值（即使 body 已空，避免 kwargs 仍指向 base 含 thinking 的 dict）
            if body:
                kwargs["extra_body"] = body
            else:
                kwargs.pop("extra_body", None)
        # Native TTL is expressed on content-block cache_control, never as a
        # Chat Completions extra_body field.  OpenAI-compatible Claude proxies
        # reject unknown cache_ttl and do not support prompt caching.
        return kwargs

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        # §7.8 ③：anthropic URL 或 claude- 模型名前缀 → 命中。
        # "anthropic" in url 命中中转站路径含 anthropic 的 URL 属预期（模型族确实来自 Anthropic）。
        return "anthropic" in url or name.startswith("claude-")

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        family = _family(model_name)
        base_url = str(model_config.get("base_url") or "").lower()
        # §7.8 A6：仅原生 Messages 端点（api.anthropic.com）支持显式 cache_control；
        # OpenAI 兼容/中转端点不支持 prompt caching → supports_prompt_cache 按端点区分
        # （Luna rev5/rev6）。用 hostname 精确校验，防伪原生子串注入
        # （api.anthropic.com.evil.example 不得匹配）。
        native_endpoint = _is_native_anthropic_host(base_url)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_ANTHROPIC_USAGE,
            pricing=_pricing_for(family),
            prompt_variant=_prompt_variant(model_name),
            # §7.8 A6：supports_prompt_cache 是端点级事实（非模型专属）——原生
            # Messages 端点支持显式 cache_control，OpenAI 兼容/中转端点不支持。
            # 对未知变体同样按端点设置（Luna rev12），模型专属的 min_block/ttl/
            # breakpoints 仅对已调研五主力在下方分支设置。
            supports_prompt_cache=native_endpoint,
            # §7.8 问 5：采样 400 契约覆盖 Fable/Mythos/Preview/Opus5/4.8/4.7/Sonnet5
            # （→ accepts_temperature=False）；Haiku 4.5 不在清单、未知变体保守
            # （→ True）。放在外层使 capability 元数据与 llm_kwargs 拒绝行为一致
            # （含 Mythos/Opus 4.7 等非五主力受限型号，Luna rev15/rev16）。
            accepts_temperature=not _sampling_restricted(model_name),
        )
        if family is not None:
            context_window = _context_window(family)
            caps = replace(
                caps,
                context_window=context_window,
                compaction_threshold=int(context_window * _COMPACTION_RATIO),
                # §7.8 A1：max_output 128k（Haiku 64k）
                max_output_tokens=_max_output(family),
                supports_function_calling=True,
                # §7.8 A1：五主力均支持视觉
                supports_vision=True,
                supports_reasoning=True,
                # §7.8 问 5：Claude 5 默认开；Opus 4.8 / Haiku 4.5 默认关
                thinking_default_on=_thinking_default_on(family),
                # §7.8 ③ 未列 json_schema；StructuredOutputMode 仅支持 function_calling /
                # json_in_text（A12–A17 同裁决；无运行时消费点）
                structured_output="function_calling",
                # §7.8 问 6：官方无 tiktoken → chars:3.0 启发式占位（A5 前）；
                # 精确计数走 messages.count_tokens；4.7+ 族同文约 +30% tokens
                tokenizer="chars:3.0",
                # §7.8 ③：Anthropic 无 reasoning.effort（thinking 走 content block /
                # output_config.effort，属 A21）→ 不设 effort_presets
                effort_presets={},
                # §7.8 问 4（A19）：显式 cache_control 断点（最多 4 个，静态在前）+
                # 按型号最小块 + TTL 5min=300s
                cache_min_block_tokens=_cache_min_block(family),
                cache_ttl_s=300,
                cache_breakpoints=("tools", "system", "session_static", "tail"),
            )
        # §7.8 A6：supports_prompt_cache 是端点级硬事实（非模型专属、不可被 override
        # 绕过）——非原生端点恒 False；原生端点恒 True（Luna rev9/rev12/rev13 Minor）。
        caps = caps.merged_with_overrides(model_config)
        caps = replace(caps, supports_prompt_cache=native_endpoint)
        return caps
