"""GLM / 智谱 provider（A14，含火山方舟 Ark 双入口）。

与 OpenAI 默认行为的差异以 A0 批 4 调研报告（§7.4，2026-08-02 三方审计通过）为准：
  - 缓存命中字段：``usage.prompt_tokens_details.cached_tokens``（嵌套路径，非平铺）
  - reasoning 内容在 message/delta 层（非 usage 嵌套字段）
  - glm-5.2：官方表述 1M（精确整数未找到，项目侧启发式 1_048_576）；
    5.x/4.7/4.6 系 200K；4.5 系 128K——皆项目侧启发式，非官方精确值
  - thinking：GLM 全系适配 → supports_reasoning=True + thinking_default_on=True；
    reasoning_effort 仅 glm-5.2+（max/xhigh/high/medium/low/minimal/none）
  - 采样参数：未找到「thinking 拒绝 temperature」明文 → accepts_temperature 保持 True
  - 无官方 tiktoken → 用 ``chars:1.5`` 估算（§7.4 问 6 启发式）

数值来源（A0 §7.4）：
  - https://docs.bigmodel.cn/cn/guide/start/model-overview
  - https://docs.bigmodel.cn/cn/guide/start/concept-param
  - https://docs.bigmodel.cn/cn/guide/capabilities/cache
  - https://docs.bigmodel.cn/cn/guide/capabilities/thinking
  - https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode
  - https://open.bigmodel.cn/pricing
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
from .base import BaseProvider

_GLM_USAGE = UsageFieldMap(
    # §7.4 问 4：官方 usage.prompt_tokens_details.cached_tokens（嵌套），无平铺主字段
    cache_read_flat=(),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    # §7.4 问 4/5：缓存写入价与 reasoning 计数未找到；reasoning 在 message/delta 层——
    # 显式清空 A12 承载的全局默认嵌套路径
    cache_write_nested=(),
    reasoning_nested=(),
    reasoning=(),  # reasoning_content 在 message/delta，不在 usage
)

# §7.4 问 2：官方上下文表述（1M / 200K / 128K）——项目侧启发式整数，非官方精确值
_CONTEXT_WINDOWS = {
    "1m": 1_048_576,
    "200k": 200_000,
    "128k": 128_000,
}
# RxyCode 项目约定：compaction_threshold ≈ context 的 90%（同 A3 §7.1；非厂商文档数值）。
# glm-5.2 按 §7.4 ③ 明确值 943_000（与 1M 的 90%=943_718 略有取整差异，以报告为准）。
_COMPACTION = {
    "1m": 943_000,
    "200k": 180_000,
    "128k": 115_200,
}

#: 调研覆盖的型号（§7.4 问 1/2）。取值：(窗口档位, max_output_tokens, supports_vision, 是否 glm-5.2+)
#: max_output 为 G6 可证实的精确 max_tokens 上限；窗口为项目侧启发式。
_GLM_FAMILY: dict[str, tuple[str, int, bool, bool]] = {
    "glm-5.2": ("1m", 131_072, False, True),
    "glm-5.1": ("200k", 131_072, False, False),
    "glm-5": ("200k", 131_072, False, False),
    "glm-5-turbo": ("200k", 131_072, False, False),
    "glm-5v-turbo": ("200k", 131_072, True, False),  # 视觉（§7.4 问 1）
    "glm-4.7": ("200k", 131_072, False, False),
    "glm-4.7-flash": ("200k", 131_072, False, False),
    "glm-4.6": ("200k", 131_072, False, False),
    "glm-4.5": ("128k", 98_304, False, False),
    "glm-4.5-air": ("128k", 98_304, False, False),
    "glm-4.5-airx": ("128k", 98_304, False, False),
    "glm-4-long": ("1m", 4_096, False, False),  # 超长文本；max output 4K（G1）
}

# §7.4 问 7：精确单价未找到（G13 前端渲染，无独立可摘录官方文本）→ 全部 None。
# Ark Coding Plan 走订阅额度，勿与按量价混用。as_of 仅表示查阅日，不代表已核验单价。
_GLM_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://open.bigmodel.cn/pricing",
)


def _family(model_name: str) -> tuple[str, int, bool, bool] | None:
    """返回调研覆盖的型号 (window,max_out,vision,is52)；未覆盖返回 None。"""
    return _GLM_FAMILY.get(model_name.lower())


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").casefold()
    except ValueError:
        return ""


def _prompt_variant(model_name: str) -> str:
    # 未调研变体保持 DEFAULT_CAPABILITIES.prompt_variant（"default"），与 A12/A13 一致
    family = _family(model_name)
    return model_name.lower() if family is not None else "default"


class GLMProvider(BaseProvider):
    name = "glm"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        # §7.4 ③ 识别规则：
        #   - bigmodel.cn / zhipu → 命中（智谱官方）
        #   - volces.com（Ark）+ 模型名含 glm → 命中（Ark 也托管其他模型，必须双条件）
        #   - 模型名以 glm- 开头（任意中转站）→ 命中
        if "bigmodel" in url or "zhipu" in url:
            return True
        if "volces.com" in url:
            return "glm" in name
        return name.startswith("glm-")

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        # FXC5: GLM's live contract is clear_thinking:false; it does not take
        # a thinking object (drop base's default {type:enabled}). 5.1 sends
        # no reasoning_effort (capabilities: only glm-5.2+ sets effort_options).
        if caps.supports_reasoning and caps.thinking_default_on:
            body = kwargs.setdefault("extra_body", {})
            body.pop("thinking", None)
            body.setdefault("clear_thinking", False)
        # OpenCode Go / Console Go is an OpenAI-compatible gateway. Vendor
        # extras (clear_thinking, reasoning_effort) become
        # "Extra inputs are not permitted" 400s upstream.
        if _host(str(model_config.get("base_url") or "")) == "opencode.ai":
            kwargs.pop("reasoning_effort", None)
            body = dict(kwargs.get("extra_body") or {})
            for key in (
                "thinking",
                "clear_thinking",
                "reasoning_effort",
                "reasoning_content",
                "mandatory_echo",
                "previous_response_id",
            ):
                body.pop(key, None)
            if body:
                kwargs["extra_body"] = body
            else:
                kwargs.pop("extra_body", None)
        return kwargs

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        family = _family(model_name)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_GLM_USAGE,
            pricing=_GLM_PRICING,
        )
        if family is not None:
            window, max_out, vision, is_52 = family
            context_window = _CONTEXT_WINDOWS[window]
            caps = replace(
                caps,
                context_window=context_window,
                compaction_threshold=_COMPACTION[window],
                # §7.4 问 2：G6 可证实的精确 max_tokens 上限
                max_output_tokens=max_out,
                supports_function_calling=True,
                # §7.4 问 1：视觉仅 glm-5v-turbo 等另条
                supports_vision=vision,
                supports_reasoning=True,
                thinking_default_on=True,  # §7.4 问 5：thinking.type 默认 enabled
                supports_prompt_cache=True,
                # §7.4 ③ 列 json_schema，但 StructuredOutputMode 仅支持 function_calling /
                # json_in_text（A12/A13 同裁决；Luna 终审接受 function_calling；无运行时消费点）
                structured_output="function_calling",
                prompt_variant=_prompt_variant(model_name),
                # §7.4 问 5：未找到「thinking 拒绝 temperature」明文 → 保留采样参数
                accepts_temperature=True,
                # §7.4 问 6：官方无 tiktoken → chars:1.5 启发式（精确走 /paas/v4/tokenizer）
                tokenizer="chars:1.5",
                # §7.4 ③：仅 glm-5.2+ 支持 reasoning_effort（max 默认推荐）
                effort_presets=(
                    {"fast": "low", "balanced": "high", "deep": "max"}
                    if is_52
                    else {}
                ),
                effort_options=(
                    ("max", "xhigh", "high", "medium", "low", "minimal", "none")
                    if is_52
                    else ()
                ),
                # §7.4 问 4：隐式自动缓存，最小块/TTL 未找到 → None；无显式断点
                cache_min_block_tokens=None,
                cache_ttl_s=None,
                cache_breakpoints=(),
            )
        return caps.merged_with_overrides(model_config)
