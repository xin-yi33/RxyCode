"""Qwen / 通义千问 provider（骨架；完整实现见 A17）。

与 OpenAI 默认行为的差异：
  - 分词无官方 tiktoken encoding，用 ``chars:0.7`` 启发式（100 万 token ≈ 70 万汉字）
  - 缓存命中在 ``usage.prompt_tokens_details.cached_tokens``（嵌套路径）
  - 3.7 系默认混合思考（``enable_thinking`` 经 extra_body）；输出 ``reasoning_content``

数值来源（A0 §7.7，2026-08-02 三方审计通过）：
  - https://help.aliyun.com/zh/model-studio/text-generation-model/
  - https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
  - https://help.aliyun.com/zh/model-studio/deep-thinking
  - https://help.aliyun.com/zh/model-studio/context-cache
  - https://help.aliyun.com/zh/model-studio/qwen3-7-plus
  - https://help.aliyun.com/zh/model-studio/qwen3-7-max
  - https://help.aliyun.com/zh/model-studio/qwen3-7-flash
  - https://help.aliyun.com/zh/model-studio/codex（Q10：qwen3.8-max-preview context_window=983616）
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

_QWEN_USAGE = UsageFieldMap(
    cache_read_flat=(),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    reasoning=(),  # reasoning_content 在 message/delta
)

# §7.7 Q5/Q6/Q7：3.7 型号页精确 1_000_000
# §7.7 Q10 Codex 元数据：qwen3.8-max-preview context_window=983_616（无独立型号页）
_CONTEXT_WINDOW_37 = 1_000_000
_CONTEXT_WINDOW_38 = 983_616
# RxyCode 项目约定：compaction_threshold ≈ context 的 90%（同 A3 §7.1；非厂商文档数值）
_COMPACTION_RATIO = 0.9


def _context_window(model_name: str) -> int:
    name = model_name.lower()
    if "3.8" in name or "qwen3.8" in name:
        return _CONTEXT_WINDOW_38
    return _CONTEXT_WINDOW_37


def _prompt_variant(model_name: str) -> str:
    name = model_name.lower()
    if "3.8" in name:
        return "qwen3.8-max-preview"
    if "max" in name and "preview" not in name:
        return "qwen3.7-max"
    if "flash" in name:
        return "qwen3.7-flash"
    return "qwen3.7-plus"


def _supports_reasoning(model_name: str) -> bool:
    """§7.7：3.7/3.8 均适配 thinking；旧 qwen-plus 混合但默认关（仍 supports）。"""
    return True


class QwenProvider(BaseProvider):
    name = "qwen"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        if name.startswith(("qwen", "qwen2", "qwen3")) or "qwen" in name:
            return True
        return (
            "dashscope" in url
            or "maas.aliyuncs.com" in url
            or "token-plan" in url
        )

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        context_window = _context_window(model_name)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            context_window=context_window,
            compaction_threshold=int(context_window * _COMPACTION_RATIO),
            usage_fields=_QWEN_USAGE,
            supports_function_calling=True,
            supports_reasoning=_supports_reasoning(model_name),
            supports_prompt_cache=True,
            structured_output="function_calling",
            prompt_variant=_prompt_variant(model_name),
            # §7.7：100 万 token ≈ 70 万汉字 → chars:0.7
            tokenizer="chars:0.7",
        )
        return caps.merged_with_overrides(model_config)
