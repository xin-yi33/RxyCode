"""Anthropic Claude provider（骨架；完整实现见 A18）。

与 OpenAI 默认行为的差异：
  - prompt 缓存需显式 ``cache_control``（ephemeral / automatic），非 OpenAI 式
    自动隐式缓存；usage 命中字段为顶层 ``cache_read_input_tokens``
  - thinking 在 ``content[]`` 的 ``type: thinking`` 块中，非 ``reasoning_content``
  - Claude 对 XML 结构化 prompt 响应更好 → ``prompt_variant="claude"``（A9 使用）

数值来源（A0 §7.8，2026-08-02 三方审计通过）：
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

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

_ANTHROPIC_USAGE = UsageFieldMap(
    cache_read_flat=("cache_read_input_tokens",),
    cache_read_nested=(),
    reasoning=(),  # thinking 在 content blocks，非 delta.reasoning_content
)

# §7.8 A1：Opus/Sonnet/Fable/Opus 4.8 为 1M；Haiku 4.5 为 200k
_CONTEXT_WINDOW_DEFAULT = 1_000_000
_CONTEXT_WINDOW_HAIKU = 200_000
# RxyCode 项目约定：compaction_threshold ≈ context 的 90%（同 A3 §7.1 / DeepSeek 卡；
# 非 Anthropic 官方文档数值）
_COMPACTION_RATIO = 0.9


def _context_window(model_name: str) -> int:
    name = model_name.lower()
    if "haiku" in name:
        return _CONTEXT_WINDOW_HAIKU
    return _CONTEXT_WINDOW_DEFAULT


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "anthropic" in url or name.startswith("claude-")

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        context_window = _context_window(model_name)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            context_window=context_window,
            compaction_threshold=int(context_window * _COMPACTION_RATIO),
            usage_fields=_ANTHROPIC_USAGE,
            supports_function_calling=True,
            supports_reasoning=True,
            # §7.8：原生 Messages 支持显式 cache_control；与 OpenAI 自动缓存不同
            supports_prompt_cache=True,
            structured_output="function_calling",
            prompt_variant="claude",
            # §7.8 A8：官方 messages.count_tokens；无 tiktoken encoding。
            # chars:3.0 为 RxyCode 启发式占位（4.7+ 族同文约 +30% tokens，≈ chars/3）；
            # A5 tokenizer 层落地前使用，精确计数走 count_tokens API。
            tokenizer="chars:3.0",
        )
        return caps.merged_with_overrides(model_config)
