"""DeepSeek provider.

与 OpenAI 默认行为的差异：
  - 前缀缓存命中数在顶层 usage.prompt_cache_hit_tokens（OpenAI 是嵌套在
    prompt_tokens_details.cached_tokens 里）
  - V4 系默认 thinking enabled，thinking 模式下 temperature 等采样参数无效
  - 上下文窗口：仅 v4-flash/v4-pro 及旧型号 chat/reasoner 为 1M（§7.1）；
    未知变体保持全局默认 256K（DC1，非全 DeepSeek 型号均 1M）

数值来源（A0 §7.1，2026-08-02 三方审计通过）：
  - https://api-docs.deepseek.com/
  - https://api-docs.deepseek.com/quick_start/pricing
  - https://api-docs.deepseek.com/guides/thinking_mode
  - https://api-docs.deepseek.com/guides/kv_cache
  - https://api-docs.deepseek.com/api/create-chat-completion/
  - https://api-docs.deepseek.com/quick_start/token_usage
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlsplit

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
from .base import BaseProvider, CHAT_TRANSPORT

_DEEPSEEK_USAGE = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(),  # Chat Completions 主路径不用嵌套形式
    reasoning=("reasoning_content",),
)

# FXC4: v4-flash / v4-pro 均为 1M context；max output 384K；compaction 更晚
# （0.97× 窗口 ≈ 1_017_118），旧 90% 点（943_718）不再提前 compact。
# DeepSeek 磁盘 TTL 为小时到天级，5 分钟空 keep-alive 是 Anthropic 补偿，
# DeepSeek 默认不启用 keep-alive（keep_alive_enabled 默认 False）。
_CONTEXT_WINDOW = 1_048_576
_MAX_OUTPUT = 384_000
_COMPACTION_THRESHOLD = int(1_048_576 * 0.97)

# §7.1 问 7：定价分条（USD / 1M；as_of=2026-08-02；source_url=S2）。
# 缓存写入价：无单独写入价（自动磁盘缓存）→ None。
_DEEPSEEK_PRICING: dict[str, ModelPricing] = {
    "deepseek-v4-flash": ModelPricing(
        input_per_mtok=0.14,
        output_per_mtok=0.28,
        cached_input_per_mtok=0.0028,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
    ),
    "deepseek-v4-pro": ModelPricing(
        input_per_mtok=0.435,
        output_per_mtok=0.87,
        cached_input_per_mtok=0.003625,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
    ),
}

#: 未调研/旧型号 → 价格显式 None（来源 URL 仍在），不得静默当 0。
_DEFAULT_DEEPSEEK_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://api-docs.deepseek.com/quick_start/pricing",
)


def _pricing_for(model_name: str) -> ModelPricing:
    """§7.1 问 7：精确匹配 v4-flash/v4-pro；未知/旧型号 → 显式 None（DC1，
    不子串匹配，避免 deepseek-v4-flash-foo 等变体继承定价）。"""
    name = model_name.lower()
    if _is_v4(name):
        return _DEEPSEEK_PRICING[name]
    return _DEFAULT_DEEPSEEK_PRICING


def _is_v4(model_name: str) -> bool:
    """精确识别 v4-flash / v4-pro（§7.1）；不泛化 `"v4" in name`。"""
    name = model_name.lower()
    return name in ("deepseek-v4-flash", "deepseek-v4-pro")


def _thinking_default_on(model_name: str) -> bool:
    """Whether this model id runs with thinking enabled by default (§7.1).

    - v4-flash / v4-pro：默认开启（§7.1 问 5）
    - deepseek-chat（过渡期 non-thinking 别名）：关闭
    - deepseek-reasoner（过渡期 thinking 别名）：开启
    - 未知变体：保守 False（DC1，不套用 v4 默认）
    """
    name = model_name.lower()
    if _is_v4(name):
        return True
    if name in ("deepseek-reasoner",):
        return True
    return False


def _prompt_variant(model_name: str) -> str:
    name = model_name.lower()
    if name == "deepseek-v4-pro":
        return "deepseek-v4-pro"
    if name == "deepseek-v4-flash":
        return "deepseek-v4-flash"
    # 旧型号（chat/reasoner 过渡期）与未知变体：保持 A3 通用 variant，不套 v4。
    return "deepseek"


def _known_deepseek(model_name: str) -> bool:
    """§7.1 覆盖或过渡期别名的型号；未知变体返回 False（DC1 保守）。"""
    name = model_name.lower()
    return _is_v4(name) or name in ("deepseek-chat", "deepseek-reasoner")


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def matches(self, base_url: str, model_name: str) -> bool:
        return "deepseek" in base_url.lower() or "deepseek" in model_name.lower()

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            return pinned
        explicit = self.explicit_transport_candidates(model_config)
        if explicit is not None:
            return explicit
        try:
            host = (
                urlsplit(str(model_config.get("base_url") or "")).hostname or ""
            ).casefold()
        except ValueError:
            host = ""
        if host == "deepseek.com" or host.endswith(".deepseek.com"):
            # Default Chat Completions: thinking+tools must echo
            # ``reasoning_content``.  Explicit ``openai_responses`` keeps
            # native ``reasoning_text`` events at the SDK stream layer so the
            # next turn can replay reasoning → function_call → output.
            return (CHAT_TRANSPORT,)
        return super().transport_candidates(model_config)

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        thinking_on = _thinking_default_on(model_name)
        is_v4 = _is_v4(model_name)
        known = _known_deepseek(model_name)

        # usage_fields 是 endpoint 协议布局（api.deepseek.com 响应结构），非模型能力：
        # 任何命中该端点的型号（含未知变体）都按此解析缓存命中/reasoning_content，
        # 否则静默漏解析（Luna rev5 确认选项 2）。pricing/prompt_variant 仍按型号保守。
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_DEEPSEEK_USAGE,
            pricing=_pricing_for(model_name),
            prompt_variant=_prompt_variant(model_name),
        )
        if known:
            # A3 原版通用字段（v4 与旧型号 chat/reasoner 均有）：1M context、
            # thinking 语义、Tool Calls、tokenizer（28591e1 起即如此，保持不回归）。
            caps = replace(
                caps,
                context_window=_CONTEXT_WINDOW,
                compaction_threshold=_COMPACTION_THRESHOLD,
                supports_reasoning=thinking_on,
                # §7.1：thinking 模式下 temperature 不报错但无效
                accepts_temperature=not thinking_on,
                # A3 即有：flash/pro/旧型号均支持 Tool Calls
                supports_function_calling=True,
                structured_output="function_calling",
                # 默认是否开启 thinking：reasoner/v4 为 True（A3 语义，非 v4 专属）
                thinking_default_on=thinking_on,
                # §7.1 启发式估算（非官方 tiktoken）；精确数以 API usage 为准
                tokenizer="chars:2.0",
            )
            if is_v4:
                # A22 新增、仅 v4：max output 384K、effort 档位、§7.1 问 4
                # disk 缓存参数（旧型号保持 A3 原值，不套 v4 专属）。
                caps = replace(
                    caps,
                    max_output_tokens=_MAX_OUTPUT,
                    effort_presets={
                        "fast": "low",
                        "balanced": "high",
                        "deep": "max",
                    },
                    effort_options=("low", "high", "max"),
                    # FXC4: cache_min_block_tokens V4 口径（256 分桶、约 1024
                    # 起步）；短 pipeline 低命中不算 bug，不再是 64
                    cache_min_block_tokens=1024,
                    cache_ttl_s=None,
                    cache_breakpoints=(),
                )
        # 未知变体：保持 DEFAULT（context 256K 等），DC1 不套 v4 能力。
        return caps.merged_with_overrides(model_config)
