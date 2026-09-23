"""Kimi / Moonshot provider（A13）。

与 OpenAI 默认行为的差异以 A0 批 3 调研报告（§7.3，2026-08-02 三方审计通过）为准：
  - 缓存命中字段：顶层 ``usage.cached_tokens``（非 prompt_cache_hit_tokens，不嵌套）
  - reasoning 内容在 message/delta 层（非 usage 嵌套字段）
  - kimi-k3：1M 上下文 / 始终推理；k2.7 系：262k / 始终思考（不支持 reasoning_effort）；
    k2.6：262k / thinking 默认 enabled 但**可 disabled**（无独立开关字段，thinking_default_on=True
    仅表达默认开启）
  - 采样参数固定（temperature 1.0 等），勿显式传；改值报错
  - 无官方 tiktoken → 用 ``chars:1.75`` 估算（§7.3 问 6 启发式）

数值来源（A0 §7.3）：
  - https://platform.kimi.com/docs/models
  - https://platform.kimi.com/docs/api/chat
  - https://platform.kimi.com/docs/guide/use-thinking-models
  - https://platform.kimi.com/docs/guide/use-reasoning-effort
  - https://platform.kimi.com/docs/pricing/chat-k3
  - https://platform.kimi.com/docs/pricing/chat-k26
  - https://platform.kimi.com/docs/pricing/chat-k27-code
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
from .base import BaseProvider

_KIMI_USAGE = UsageFieldMap(
    # §7.3 问 4：官方 OpenAPI 用顶层 cached_tokens（不嵌套）
    cache_read_flat=("cached_tokens",),
    cache_read_nested=(),
    # §7.3 问 4/5：缓存写入单价官方未找到；reasoning **token 计数**官方未找到
    # → 嵌套计数路径 reasoning_nested 显式清空，避免误导
    cache_write_nested=(),
    reasoning_nested=(),
    # 2026-09-23 修复：reasoning 是**内容**字段映射（delta/message 上的
    # reasoning_content，见 UsageFieldMap.reasoning 注释与本文件模块 docstring
    # §7.3「reasoning 内容在 message/delta 层」），不是 usage 计数路径。
    # 此前误置 () → BaseProvider.extract_reasoning 字段循环为空 → 流式轮次
    # 思维链全部丢失（探针：tui.reasoning.emit 缺失 + final thinking_len=0）。
    reasoning=("reasoning_content",),
)

# §7.3 问 2：定价页精确 context（非营销「1M / 256k」近似）
_K3_CONTEXT = 1_048_576
_K2X_CONTEXT = 262_144
# RxyCode 项目约定：compaction_threshold ≈ context 的 90%（同 A3 §7.1；非厂商文档数值）
_K3_COMPACTION = 943_000
_K2X_COMPACTION = 236_000

# §7.3 问 7：定价按型号分条（CNY / 1M，中国区；as_of=2026-08-02；勿填国际站 USD）。
# cache_write 单价官方未找到 → None（不得静默当 0）。
# 注：ModelPricing 类文档泛称「美元」，但 §7.3 ③ 明确本批定价按 CNY 填写
# （「货币：CNY（中国区）；勿填国际站 USD」）——货币语义由 Phase E 的
# CostAccountant 按 as_of/source_url 结算，本卡只承载调研数值。
_KIMI_PRICING: dict[str, ModelPricing] = {
    "kimi-k3": ModelPricing(
        input_per_mtok=20.00,
        output_per_mtok=100.00,
        cached_input_per_mtok=2.00,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://platform.kimi.com/docs/pricing/chat-k3",
    ),
    "kimi-k2.7-code": ModelPricing(
        input_per_mtok=6.50,
        output_per_mtok=27.00,
        cached_input_per_mtok=1.30,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://platform.kimi.com/docs/pricing/chat-k27-code",
    ),
    "kimi-k2.7-code-highspeed": ModelPricing(
        input_per_mtok=13.00,
        output_per_mtok=54.00,
        cached_input_per_mtok=2.60,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://platform.kimi.com/docs/pricing/chat-k27-code",
    ),
    "kimi-k2.6": ModelPricing(
        input_per_mtok=6.50,
        output_per_mtok=27.00,
        cached_input_per_mtok=1.10,
        cache_write_per_mtok=None,
        as_of="2026-08-02",
        source_url="https://platform.kimi.com/docs/pricing/chat-k26",
    ),
}

#: 未调研型号（kimi-k2.5 / moonshot-v1-*）→ 价格显式 None（来源 URL 仍在），不得静默当 0。
_DEFAULT_KIMI_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://platform.kimi.com/docs/pricing/chat",
)

#: 调研覆盖的型号（§7.3 问 1：RxyCode 主写 k3 / k2.7-code / k2.7-code-highspeed / k2.6）。
_KIMI_FAMILY: dict[str, str] = {
    "kimi-k3": "kimi-k3",
    "kimi-k2.7-code": "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed": "kimi-k2.7-code-highspeed",
    "kimi-k2.6": "kimi-k2.6",
}


def _family(model_name: str) -> str | None:
    """返回调研覆盖的型号规范名；未覆盖返回 None（k2.5/moonshot-v1/未知变体）。"""
    return _KIMI_FAMILY.get(model_name.lower())


def _prompt_variant(model_name: str) -> str:
    # 未调研变体保持 DEFAULT_CAPABILITIES.prompt_variant（"default"），
    # 与 A12 一致：只对调研覆盖的型号声明专属 variant，未知变体不套用。
    family = _family(model_name)
    return family if family is not None else "default"


def _pricing_for(model_name: str) -> ModelPricing:
    family = _family(model_name)
    if family is not None:
        return _KIMI_PRICING[family]
    return _DEFAULT_KIMI_PRICING


class KimiProvider(BaseProvider):
    name = "kimi"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        # §7.3 问 3：api.moonshot.cn / api.moonshot.ai 均可；kimi 模型名任意端点命中。
        # 勿写成 endswith("moonshot.com") 之类把 .cn 漏掉。
        # 注（A13 卡骨架原文指定该规则）：`"kimi" in name` 属卡面约定，仅对实测正例
        # 断言覆盖；复合名（glm-kimi-* 等）不在卡面反例清单内，若未来出现按卡面「matches
        # 别写太宽」原则收紧为 startswith/白名单，不在本卡范围。
        return "moonshot" in url or "kimi" in name

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        # FXC5/FX-CB11: the thinking shape comes from catalog thinking_param,
        # never from model-name heuristics. kimi-k3 sample is
        # "reasoning_effort: {...}" -> only effort, drop base's thinking object;
        # k2.x sample is "{type:enabled, keep:all}" -> keep the thinking object.
        from RxyCode.RxyCode1_1_0.core.catalog import get_contract

        contract = get_contract("kimi", str(model_config.get("model_name") or ""))
        sample = str(((contract or {}).get("thinking_param") or {}).get("sample") or "")
        if "reasoning_effort" in sample:
            kwargs.setdefault("extra_body", {}).pop("thinking", None)
        return kwargs

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        family = _family(model_name)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_KIMI_USAGE,
            pricing=_pricing_for(model_name),
            prompt_variant=_prompt_variant(model_name),
        )
        if family is not None:
            context_window = _K3_CONTEXT if family == "kimi-k3" else _K2X_CONTEXT
            caps = replace(
                caps,
                context_window=context_window,
                compaction_threshold=(
                    _K3_COMPACTION if family == "kimi-k3" else _K2X_COMPACTION
                ),
                # §7.3 问 2：k3 max_completion_tokens 默认 131072（上限可至 1M）
                max_output_tokens=(131_072 if family == "kimi-k3" else None),
                supports_function_calling=True,
                # §7.3 问 1：k3 原生视觉 + video；k2.x 未声明（不臆造）
                supports_vision=(family == "kimi-k3"),
                supports_reasoning=True,
                thinking_default_on=True,  # k3 始终推理；k2.x 始终/默认思考
                supports_prompt_cache=True,
                # §7.3 ③ 列 K3 structured_output="json_schema"，但 RxyCode 的
                # StructuredOutputMode 仅支持 function_calling / json_in_text（A12 同裁决：
                # §7.2 的 gpt-5.6 同样标注 "+ json_schema"，Luna 终审接受 function_calling；
                # 且 StructuredOutputMode 为 Literal，json_schema 会触发类型错误）。
                # caps.structured_output 当前无运行时消费（纯元数据），以 function_calling
                # 声明，json_schema 属 Phase E 扩展，不在本卡落地。
                structured_output="function_calling",
                prompt_variant=_prompt_variant(model_name),
                # §7.3 问 5：采样参数固定，勿显式传（改值报错）
                accepts_temperature=False,
                # §7.3 问 6：官方无 tiktoken → chars:1.75 启发式（精确走 estimate-token-count / usage）
                tokenizer="chars:1.75",
                # §7.3 问 5：仅 k3 支持 reasoning_effort（low/high/max，无 medium）。
                # 注：这是 RxyCode 的档位映射（默认档 balanced→high）；K3 官方原生默认
                # reasoning_effort=max（省略参数时）。调用方显式传档位时走本映射。
                effort_presets=(
                    {"fast": "low", "balanced": "high", "deep": "max"}
                    if family == "kimi-k3"
                    else {}
                ),
                effort_options=("low", "high", "max") if family == "kimi-k3" else (),
                # §7.3 问 4：自动 Context Caching，前次 prompt > 256 才缓存；
                # TTL 系统自动管理（无固定值）；无显式断点
                cache_min_block_tokens=256,
                cache_ttl_s=None,
                cache_breakpoints=(),
            )
        return caps.merged_with_overrides(model_config)
