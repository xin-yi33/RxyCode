"""DeepSeek provider.

与 OpenAI 默认行为的差异：
  - 前缀缓存命中数在顶层 usage.prompt_cache_hit_tokens（OpenAI 是嵌套在
    prompt_tokens_details.cached_tokens 里）
  - V4 系默认 thinking enabled，thinking 模式下 temperature 等采样参数无效
  - 上下文窗口 1M（非全局默认 256k）

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

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

_DEEPSEEK_USAGE = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(),  # Chat Completions 主路径不用嵌套形式
    reasoning=("reasoning_content",),
)

# §7.1：v4-flash / v4-pro 均为 1M context；compaction ≈90%
_CONTEXT_WINDOW = 1_048_576
_COMPACTION_THRESHOLD = 943_718


def _thinking_default_on(model_name: str) -> bool:
    """Whether this model id runs with thinking enabled by default (§7.1)."""
    name = model_name.lower()
    if name in ("deepseek-chat",) or (
        name.endswith("-chat") and "reasoner" not in name
    ):
        return False
    return True


def _prompt_variant(model_name: str) -> str:
    name = model_name.lower()
    if "v4-pro" in name or name == "deepseek-v4-pro":
        return "deepseek-v4-pro"
    return "deepseek-v4-flash"


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def matches(self, base_url: str, model_name: str) -> bool:
        return "deepseek" in base_url.lower() or "deepseek" in model_name.lower()

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        thinking_on = _thinking_default_on(model_name)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            context_window=_CONTEXT_WINDOW,
            compaction_threshold=_COMPACTION_THRESHOLD,
            usage_fields=_DEEPSEEK_USAGE,
            supports_reasoning=thinking_on,
            # §7.1：thinking 模式下 temperature 不报错但无效
            accepts_temperature=not thinking_on,
            # §7.1：flash/pro 均支持 Tool Calls（含 thinking 模式）
            supports_function_calling=True,
            structured_output="function_calling",
            prompt_variant=_prompt_variant(model_name),
            # §7.1 启发式估算（非官方 tiktoken）；精确数以 API usage 为准
            tokenizer="chars:2.0",
        )
        return caps.merged_with_overrides(model_config)
