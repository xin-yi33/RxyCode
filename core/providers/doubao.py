"""Doubao (Volcano Ark coding endpoint) provider.

与 OpenAI 默认行为的差异以 A0 批 9 调研报告（§7.9，2026-08-06 三方审计通过）为准：
  - doubao-seed-2.1-turbo：256k 上下文 / 256k 最大输出（软上限，默认约 4k，
    可由请求 max_tokens 调高；勿写 128k——128k 属 Seed-2.0-lite/mini）
  - 未见独立 thinking.type 开关文档；响应 message/delta 层含 reasoning_content（实测）
  - function calling 实测可用（tool_calls + tool_choice=required，ark coding 端点）
  - temperature=0.7 实测 HTTP 200（兼容）
  - 无官方 tiktoken encoding → tokenizer 用 chars: 启发式估算
  - pro 未实测（R1 边界）：能力声明只对 turbo 生效，pro 走保守

数值来源（A0 §7.9，2026-08-06 三方审计通过）：
  - https://ai.volcengine.com/model
  - https://www.volcengine.com/docs/82379/1544106
  - artifacts/a10-doubao-probe.txt（HTTP 200 / model id / FC tool_calls /
    reasoning_content / temperature）
  - artifacts/a10-doubao-256k-probe.txt（max_tokens=65536 HTTP 200）
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
from .base import BaseProvider, CHAT_TRANSPORT, RESPONSES_TRANSPORT

_DOUBAO_USAGE = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    reasoning=("reasoning_content",),
)
#: §7.9：pro 未实测，usage_fields 不含 reasoning 映射（仅 turbo 声明 reasoning）。
_DOUBAO_USAGE_NO_REASONING = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    reasoning=(),
)


#: §7.9 实测并声明的 turbo 型号 id（ark 别名 + 官方 snapshot）；其余一律保守。
_TURBO_IDS = frozenset(
    {"doubao-seed-2.1-turbo", "doubao-seed-2-1-turbo-260628"}
)
_PRO_IDS = frozenset({"doubao-seed-2.1-pro", "doubao-seed-2-1-pro-260628"})


def _is_turbo(model_name: str) -> bool:
    """§7.9 R1：精确识别 turbo 型号 id（含官方 snapshot 变体）。"""
    return model_name.lower() in _TURBO_IDS


def _is_pro(model_name: str) -> bool:
    """§7.9 R1：精确识别 pro 型号 id（含官方 snapshot 变体）；未实测。"""
    return model_name.lower() in _PRO_IDS


def is_ark_coding_hostname(url: str) -> bool:
    """判断 URL 是否为官方 ark coding 域：http(s)、hostname 为 ``*.volces.com``
    且 labels 含 ``ark``（如 ark.cn-beijing.volces.com；§7.9 官方 ark coding
    端点）。用标准 URL 解析：不用 "ark" in host 子串泛化（fooark.volces.com
    不匹配）、拒绝 userinfo 注入（user@host）、异常 URL 保守 False
    （Luna rev3/rev5/rev6）。"""
    try:
        from urllib.parse import urlparse
    except ImportError:  # pragma: no cover
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.username or parsed.password:
            return False
        host = (parsed.hostname or "").lower()
        if host != "volces.com" and not host.endswith(".volces.com"):
            return False
        return "ark" in host.split(".")
    except ValueError:  # 畸形 URL：保守不匹配
        return False

#: §7.9：官方 CNY 刊例（元/百万 token）：turbo 3.00/15.00、缓存命中 0.60；
#: pro 6.00/30.00、缓存 1.20（2026-08-06 时点）。ModelPricing 计价单位是 USD/1M
#: （Phase E CostAccountant），需官方 CNY→USD 换算后填入；当前留占位 None，
#: 不得静默当 0（来源 URL 仍在）。缓存写入无单独写入价 → None。
#: 按型号分条（turbo/pro 定价不同，勿共用单一值）。
#: §7.9「适配缺口」明确：pricing 属 Phase E 中心表，A23 按占位 None + source_url
#: 即完成本卡判据（换算由 Phase E CostAccountant 落地时执行，见 PHASE-A §4）。
#: 此处是已确认的 Phase E 占位（非待办 TODO）；Phase E 接入时按 CNY→USD 填入。
_DOUBAO_PRICING_TURBO = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-06",
    source_url="https://ai.volcengine.com/model",
)
_DOUBAO_PRICING_PRO = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-06",
    source_url="https://ai.volcengine.com/model",
)
_DEFAULT_DOUBAO_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-06",
    source_url="https://ai.volcengine.com/model",
)


def _pricing_for(model_name: str) -> ModelPricing:
    """§7.9：turbo/pro 定价分条；未知变体返回全 None 占位（保守，DC1，
    不得继承已调研型号的 pricing）。"""
    if _is_turbo(model_name):
        return _DOUBAO_PRICING_TURBO
    if _is_pro(model_name):
        return _DOUBAO_PRICING_PRO
    return _DEFAULT_DOUBAO_PRICING


class DoubaoProvider(BaseProvider):
    """Doubao Seed 2.1 family via Volcano Ark coding endpoint."""

    name = "doubao"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        if not ("doubao" in name or "seed" in name):
            return False
        # §7.9：只认官方 ark coding 域 *.volces.com（如 ark.cn-beijing.volces.com），
        # 避免抢走 ark 上其他模型（minimax/glm）或误配任意含 "ark"/"volces" 子串的 URL。
        # 用 hostname 精确校验，不用子串泛化（Luna rev1）。
        return is_ark_coding_hostname(url)

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            return pinned
        explicit = self.explicit_transport_candidates(model_config)
        if explicit is not None:
            return explicit
        if is_ark_coding_hostname(str(model_config.get("base_url") or "")):
            return (RESPONSES_TRANSPORT, CHAT_TRANSPORT)
        return super().transport_candidates(model_config)

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        # §7.9 R1：pro 未实测、未知变体未调研，能力声明只对 turbo 生效，其余保守
        # （不声明 reasoning/FC/context，usage_fields 不带 reasoning 映射）。
        is_turbo = _is_turbo(model_name)
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=(_DOUBAO_USAGE if is_turbo else _DOUBAO_USAGE_NO_REASONING),
            pricing=_pricing_for(model_name),
            prompt_variant="doubao",
            # §7.9 实测：turbo 响应含 reasoning_content（message/delta 层）
            supports_reasoning=is_turbo,
            # §7.9 实测：turbo FC 可用（tool_calls + tool_choice=required）
            supports_function_calling=is_turbo,
            # §7.9 rev2：官方标多模态，但探针仅验证文本请求——不得暗示全模态已实测
            supports_vision=False,
            # §7.9：无官方 tiktoken → chars: 估算；有官方 tokenizer 后再换
            tokenizer="chars:2.0",
        )
        if is_turbo:
            # §7.9：turbo 256k 上下文（调研确认值）→ 显式声明；pro/未知变体
            # 不 replace，保持全局默认（语义上是"未声明"，DC1 不继承调研能力）。
            caps = replace(
                caps,
                context_window=256_000,
                compaction_threshold=232_000,
                max_output_tokens=None,  # 256k 为软上限，能力层不声明硬上限（A23）
            )
        return caps.merged_with_overrides(model_config)
