"""Doubao (Volcano Ark coding endpoint) provider.

与 OpenAI 默认行为的差异以 A0 第 9 家族调研（§7.9 rev1）为准：
  - doubao-seed-2.1-turbo：256k 上下文 / 256k 最大输出（官方 AI Hub；max_tokens 由配置控制）
  - 未见独立 thinking.type 开关；响应 message/delta 层含 reasoning_content（实测）
  - function calling 实测可用（tool_calls + tool_choice，ark coding 端点）
  - 无官方 tiktoken → 用 chars: 估算
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

_DOUBAO_USAGE = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    reasoning=("reasoning_content",),
)


class DoubaoProvider(BaseProvider):
    """Doubao Seed 2.1 family via Volcano Ark coding endpoint."""

    name = "doubao"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        # 只认 doubao/seed 模型名，避免抢走 ark 端点上其他模型（minimax/glm）。
        return ("volcengine" in url or "ark" in url) and (
            "doubao" in name or "seed" in name
        )

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_DOUBAO_USAGE,
            # 实测：响应含 reasoning_content（message/delta 层）
            supports_reasoning=True,
            # 实测：FC 可用（tool_calls + tool_choice）
            supports_function_calling=True,
            # 无官方 tiktoken（§7.9）
            tokenizer="chars:2.0",
        )
        return caps.merged_with_overrides(model_config)
