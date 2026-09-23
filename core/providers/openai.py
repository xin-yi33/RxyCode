"""OpenAI provider —— 兜底 + 显式优化（A12）。

DC1 保持方式：本类同时承担"兜底"与"显式 OpenAI"两个角色。
  - 作为兜底（注册表全部落空时选用）：capabilities() 在 matches() 未命中时
    返回 DEFAULT_CAPABILITIES，与 Phase A 之前的硬编码行为逐字节一致。
  - 显式命中（base_url 含 openai.com，或模型名以 gpt-/o1-/o3-/o4- 开头）：
    应用 §7.2 调研报告的显式能力声明（2026-08-02 三方审计通过）。

数值来源（A0 §7.2，2026-08-02 三方审计通过）：
  - https://platform.openai.com/docs/models
  - https://platform.openai.com/docs/pricing
  - https://platform.openai.com/docs/guides/prompt-caching
  - https://platform.openai.com/docs/guides/reasoning
  - https://platform.openai.com/docs/guides/migrate-to-responses
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlsplit

try:
    from ...config.model_capabilities import (
        DEFAULT_CAPABILITIES,
        ModelCapabilities,
        ModelPricing,
    )
except ImportError:  # pragma: no cover - repo-root layout (tests)
    from config.model_capabilities import (
        DEFAULT_CAPABILITIES,
        ModelCapabilities,
        ModelPricing,
    )
from .base import BaseProvider, CHAT_TRANSPORT, RESPONSES_TRANSPORT

#: gpt-5.6 三档定价（USD/1M，Short context Standard；§7.2 问 7 / ③，定价按型号分条）。
#: cache_write 按 uncached input × 1.25 计费（§7.2 问 4）。
_OPENAI_PRICING: dict[str, ModelPricing] = {
    "gpt-5.6-sol": ModelPricing(
        input_per_mtok=5.00,
        output_per_mtok=30.00,
        cached_input_per_mtok=0.50,
        cache_write_per_mtok=6.25,
        as_of="2026-08-02",
        source_url="https://platform.openai.com/docs/pricing",
    ),
    "gpt-5.6-terra": ModelPricing(
        input_per_mtok=2.00,
        output_per_mtok=12.00,
        cached_input_per_mtok=0.20,
        cache_write_per_mtok=2.50,
        as_of="2026-08-02",
        source_url="https://platform.openai.com/docs/pricing",
    ),
    "gpt-5.6-luna": ModelPricing(
        input_per_mtok=0.20,
        output_per_mtok=1.20,
        cached_input_per_mtok=0.02,
        cache_write_per_mtok=0.25,
        as_of="2026-08-02",
        source_url="https://platform.openai.com/docs/pricing",
    ),
}

#: 未调研型号（如 gpt-5.2）→ 价格显式 None（来源 URL 仍在），不得静默当 0。
_DEFAULT_OPENAI_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://platform.openai.com/docs/pricing",
)

#: gpt-5.6 三档 + 别名 `gpt-5.6`（§7.2 问 1：gpt-5.6-sol 的别名）。
#: 只认这 4 个 id，`gpt-5.6-*` 未知变体不套调研能力。
_5_6_FAMILY: dict[str, str] = {
    "gpt-5.6": "gpt-5.6-sol",
    "gpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-luna": "gpt-5.6-luna",
}


def _gpt_5_6_family(model_name: str) -> str | None:
    """返回 gpt-5.6 家族规范名（含别名归一），非本家族返回 None。"""
    return _5_6_FAMILY.get(model_name.lower())


def _prompt_variant(model_name: str) -> str:
    """gpt-5.6 按型号取 prompt_variant；其余保持默认。"""
    family = _gpt_5_6_family(model_name)
    return family if family is not None else "default"


def _pricing_for(model_name: str) -> ModelPricing:
    family = _gpt_5_6_family(model_name)
    if family is not None:
        return _OPENAI_PRICING[family]
    return _DEFAULT_OPENAI_PRICING


class OpenAIProvider(BaseProvider):
    name = "openai"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "openai.com" in url or name.startswith(("gpt-", "o1-", "o3-", "o4-"))

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
        if host == "openai.com" or host.endswith(".openai.com"):
            # Official OpenAI guidance prefers Responses for reasoning,
            # tool-calling and multi-turn workflows; Chat remains fallback.
            return (RESPONSES_TRANSPORT, CHAT_TRANSPORT)
        return super().transport_candidates(model_config)

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        base_url = str(model_config.get("base_url") or "")
        model_name = str(model_config.get("model_name") or "")
        if not self.matches(base_url, model_name):
            # DC1：兜底路径，行为与改造前完全一致。
            return DEFAULT_CAPABILITIES.merged_with_overrides(model_config)
        name = model_name.lower()
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            pricing=_pricing_for(name),
        )
        if _gpt_5_6_family(name) is not None:
            # §7.2 ③（2026-08-02 审计通过）：gpt-5.6 三档显式能力。
            caps = replace(
                caps,
                context_window=1_050_000,
                compaction_threshold=945_000,
                max_output_tokens=128_000,
                supports_vision=True,
                supports_reasoning=True,
                thinking_default_on=True,  # 省略 effort → 默认 medium
                supports_prompt_cache=True,
                structured_output="function_calling",
                prompt_variant=_prompt_variant(name),
                effort_presets={
                    "fast": "low",
                    "balanced": "medium",
                    "deep": "high",
                },
                effort_options=("low", "medium", "high"),
                # §7.2 问 6：项目侧启发式；未找到官方 5.6 encoding 名
                tokenizer="tiktoken:o200k_base",
                # §7.2 第 4 问：自动前缀缓存，GPT-5.6+ 最小 1024；TTL 30m=1800s；
                # 无显式断点（自动/隐式模式）
                cache_min_block_tokens=1024,
                cache_ttl_s=1800,
                cache_breakpoints=(),
                # B2 (CB3): OpenAI 系用请求级 prompt_cache_key=session_id
                # 显式键控缓存（codex client.rs / kimi llm.py 语义）。
                prompt_cache_key_required=True,
            )
        if name.startswith(("o1-", "o3-", "o4-")):
            # §7.2 问 5：旧 o 系列明文拒绝采样参数（5.6 未证实，勿外推）
            caps = replace(
                caps,
                supports_reasoning=True,
                thinking_default_on=True,
                accepts_temperature=False,
            )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        if caps.supports_reasoning and not caps.accepts_temperature:
            # §7.2 问 5：仅旧 o 系列有拒绝采样参数的明文；GPT-5.6 未找到，
            # 保留 temperature（accepts_temperature=True）。
            kwargs.pop("temperature", None)
        if caps.supports_reasoning and caps.effort_presets:
            # 仅对推理模型注入 reasoning_effort（§7.2 �?5：gpt-5.6 调研范围内；
            # gpt-4o/gpt-5.2 无数据，不得臆造参数）。
            # /effort 扩展（2026-08-12）：effort 命中厂商档位全集（effort_options）
            # 时直接透传；否则走抽象映射（fast/balanced/deep）。
            # 审计修复（luna audit2，2026-08-13）：未知档位（不在 effort_options
            # 也不在 presets keys）→ **不注入**，与 base.py 安全回退语义一致
            # （原 A21 的 get(effort, "medium") 默认会把非法档位误注入 medium）。
            effort = str(model_config.get("effort") or "balanced")
            options = caps.effort_options or ()
            if effort in options:
                kwargs["reasoning_effort"] = effort
            else:
                preset = caps.effort_presets.get(effort)
                if preset is not None:
                    # §7.2 �?5 / ③：Chat Completions 顶层参数 reasoning_effort
                    # （不�?extra_body，也不是 DeepSeek �?thinking.type）�?/
                    kwargs["reasoning_effort"] = preset
        return kwargs
