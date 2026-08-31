"""Qwen / 通义千问 provider（A17 补全：DashScope / 百炼 Model Studio）。

与 OpenAI 默认行为的差异以 A0 批 7 调研报告（§7.7，2026-08-02 三方审计通过）为准：

四档（A17 必须覆盖；按量首选 plus；Token Plan 最强用 3.8）：
  - qwen3.7-plus：主力 A，能力/成本均衡，多模态 Agent（图/文/视频），按量默认
  - qwen3.7-max：主力 B，最强按量推理；动态 id 当前纯文本体验
  - qwen3.7-flash：主力 C，低成本接近旗舰，多模态
  - qwen3.8-max-preview：主力 D，Token Plan 最强推理预览；仅 Token Plan（Credits）

共用（Chat Completions / OpenAI 兼容；按量三主力）：
  - 3.7：context 1_000_000（型号页精确整数）；max_output 65_536；FC=True
  - thinking：3.7 混合思考默认开启（可关）；3.8 仅思考不可关
  - 缓存：隐式默认开；显式可选 cache_control（TTL 5min / min 1024）
  - 无官方 tiktoken → 用 ``chars:0.7`` 启发式（100 万 token ≈ 70 万汉字，Q1）
  - enable_thinking 经 extra_body；Responses 用 reasoning.effort（端点区分）

数值来源（A0 §7.7）：
  - https://help.aliyun.com/zh/model-studio/text-generation-model/
  - https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
  - https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses
  - https://help.aliyun.com/zh/model-studio/deep-thinking
  - https://help.aliyun.com/zh/model-studio/context-cache
  - https://help.aliyun.com/zh/model-studio/qwen3-7-plus
  - https://help.aliyun.com/zh/model-studio/qwen3-7-max
  - https://help.aliyun.com/zh/model-studio/qwen3-7-flash
  - https://help.aliyun.com/zh/model-studio/codex（Q10：qwen3.8-max-preview context_window=983616）
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
from ..catalog import get_contract

_QWEN_USAGE = UsageFieldMap(
    cache_read_flat=(),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    # §7.7 问 4：显式缓存创建写 usage.prompt_tokens_details.cache_creation_input_tokens
    cache_write_nested=(("prompt_tokens_details", "cache_creation_input_tokens"),),
    reasoning=(),  # reasoning_content 在 message/delta，不在 usage
)

# §7.7 Q5/Q6/Q7：3.7 型号页精确 1_000_000
# §7.7 Q10 Codex 元数据：qwen3.8-max-preview context_window=983_616（无独立型号页）
_CONTEXT_WINDOW_37 = 1_000_000
_CONTEXT_WINDOW_38 = 983_616
# §7.7 问 2：3.7 max_output_tokens=65_536（3.8 未找到官方整数 → None）
_MAX_OUTPUT_37 = 65_536
# RxyCode 项目约定：compaction_threshold ≈ context 的 90%（同 A3 §7.1；非厂商文档数值）
_COMPACTION_RATIO = 0.9

# §7.7 问 7：定价按型号分条（CNY / 1M，华北2 北京按量；as_of=2026-08-02；source_url=型号页）。
# 填「默认档」：plus ≤256k；max 统一；flash ≤32k。更高输入阶梯（plus 256k–1M 6/24/1.2、
# flash 32k–256k / 256k–1M）由调用方按实际输入长度切换（§7.7 问 7a / ③「按实际输入长度
# 切换阶梯」），Phase E CostAccountant 消费。
# 3.8 仅 Token Plan（Credits）→ 单价 None，禁止填 3.7-max 的 12/36（§7.7 问 7b）。
_QWEN_PRICING: dict[str, ModelPricing] = {
    "qwen3.7-plus": ModelPricing(
        input_per_mtok=2.0,
        output_per_mtok=8.0,
        cached_input_per_mtok=0.4,  # 隐式命中
        cache_write_per_mtok=None,
        cache_creation_per_mtok=2.5,  # 显式创建（≤256k 档）
        explicit_cache_hit_per_mtok=0.2,  # 显式命中（≤256k 档）
        as_of="2026-08-02",
        source_url="https://help.aliyun.com/zh/model-studio/qwen3-7-plus",
    ),
    "qwen3.7-max": ModelPricing(
        input_per_mtok=12.0,
        output_per_mtok=36.0,
        cached_input_per_mtok=2.4,
        cache_write_per_mtok=None,
        cache_creation_per_mtok=15.0,  # 显式创建
        explicit_cache_hit_per_mtok=1.2,  # 显式命中
        as_of="2026-08-02",
        source_url="https://help.aliyun.com/zh/model-studio/qwen3-7-max",
    ),
    "qwen3.7-flash": ModelPricing(
        input_per_mtok=0.2,
        output_per_mtok=0.8,
        cached_input_per_mtok=0.04,
        cache_write_per_mtok=None,
        cache_creation_per_mtok=0.25,  # 显式创建（≤32k 档）
        explicit_cache_hit_per_mtok=0.02,  # 显式命中（≤32k 档）
        as_of="2026-08-02",
        source_url="https://help.aliyun.com/zh/model-studio/qwen3-7-flash",
    ),
}

#: 3.8-max-preview：仅 Token Plan（Credits），禁止按量 CNY 单价（§7.7 问 7b）。
_38_PREVIEW_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://help.aliyun.com/zh/model-studio/codex",
)

#: 未调研型号 → 价格显式 None（来源 URL 仍在），不得静默当 0。
_DEFAULT_QWEN_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    cache_write_per_mtok=None,
    as_of="2026-08-02",
    source_url="https://help.aliyun.com/zh/model-studio/text-generation-model/",
)

#: 调研覆盖的四档（§7.7 问 1）。qwen-plus / qwen-flash 等旧版不在调研内 → 保守。
_QWEN_FAMILY = {"qwen3.7-plus", "qwen3.7-max", "qwen3.7-flash", "qwen3.8-max-preview"}


def _family(model_name: str) -> str | None:
    """返回调研覆盖的型号规范名；未覆盖返回 None（旧版 qwen-plus 等保守）。"""
    name = model_name.lower().replace(" ", "")
    if name in _QWEN_FAMILY:
        return name
    return None


def _context_window(family: str) -> int:
    return _CONTEXT_WINDOW_38 if family == "qwen3.8-max-preview" else _CONTEXT_WINDOW_37


def _max_output(family: str) -> int | None:
    return None if family == "qwen3.8-max-preview" else _MAX_OUTPUT_37


def _supports_vision(family: str) -> bool:
    """§7.7 ③：plus/flash 多模态（True）；max 动态 id 纯文本（False）；
    3.8 无型号页复核 → 不写入 True 作 API 能力证明（保守 False）。"""
    return family in ("qwen3.7-plus", "qwen3.7-flash")


def _pricing_for(family: str | None) -> ModelPricing:
    if family is None:
        return _DEFAULT_QWEN_PRICING
    if family == "qwen3.8-max-preview":
        return _38_PREVIEW_PRICING
    return _QWEN_PRICING[family]


def _prompt_variant(model_name: str) -> str:
    # 未调研变体保持 DEFAULT_CAPABILITIES.prompt_variant（"default"），与 A12–A16 一致
    family = _family(model_name)
    return family if family is not None else "default"


def _supports_reasoning(model_name: str) -> bool:
    """§7.7 问 5：3.7/3.8 均适配 thinking（3.7 混合默认可关；3.8 仅思考不可关）。"""
    return _family(model_name) is not None


def _is_official_dashscope_host(url: str) -> bool:
    """Whether *url* uses an official DashScope/Model Studio hostname."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.username or parsed.password:
            return False
        host = (parsed.hostname or "").casefold()
    except (TypeError, ValueError):
        return False

    return host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
    } or host.endswith(".maas.aliyuncs.com")


class QwenProvider(BaseProvider):
    name = "qwen"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        # §7.7 ③：仅认 qwen / qwen2 / qwen3 前缀或 qwen 端点。
        # 勿用 "qwen" in name（会把 my-qwen-model 等误判为 Qwen，违反 DC1）。
        if name.startswith(("qwen", "qwen2", "qwen3")):
            return True
        return (
            "dashscope" in url
            or "maas.aliyuncs.com" in url
            or "token-plan" in url
        )

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        """Prefer Responses only on Alibaba's documented official hosts.

        The preset policy in ``BaseProvider`` handles saved DashScope entries.
        This host check also covers imported/legacy configurations that have no
        ``provider_id``.  Model-name matching alone is deliberately insufficient:
        a Qwen model may be served by a third-party Chat-only gateway.
        """
        pinned = self._resource_path_candidates(model_config)
        if pinned is not None:
            return pinned
        explicit = self.explicit_transport_candidates(model_config)
        if explicit is not None:
            return explicit
        if _is_official_dashscope_host(str(model_config.get("base_url") or "")):
            return (RESPONSES_TRANSPORT, CHAT_TRANSPORT)
        return super().transport_candidates(model_config)

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        family = _family(model_name)

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_QWEN_USAGE,
            pricing=_pricing_for(family),
            prompt_variant=_prompt_variant(model_name),
        )
        if family is not None:
            context_window = _context_window(family)
            is_38 = family == "qwen3.8-max-preview"
            responses = self.uses_responses_api(model_config)
            caps = replace(
                caps,
                context_window=context_window,
                compaction_threshold=int(context_window * _COMPACTION_RATIO),
                # §7.7 问 2：3.7=65536；3.8 未找到官方整数 → None
                max_output_tokens=_max_output(family),
                # §7.7 ③：3.7 FC=True（Q1 证实）；3.8 无型号页勾选表 → None（未找到）
                supports_function_calling=(None if is_38 else True),
                # §7.7 ③ Q1 第 3 列「内置工具」：plus/max/flash=True（Harness 不得覆盖）；
                # 3.8 未找到 → None（禁止继承写 True）
                supports_builtin_tools=(None if is_38 else True),
                # §7.7 问 7b：3.8 仅 Token Plan Credits；3.7 按量（空串）
                billing=("token_plan_credits" if is_38 else ""),
                # §7.7 ③：plus/flash 多模态；max 纯文本；3.8 不写入 True
                supports_vision=_supports_vision(family),
                supports_reasoning=True,
                # §7.7 问 5：3.7 混合思考默认可关；3.8 仅思考不可关（均默认开）
                thinking_default_on=True,
                supports_prompt_cache=True,
                # §7.7 ③：plus/flash Q1 结构化输出支持 → function_calling 可用；
                # max Q1=不支持 vs Q5=支持 → 冲突留档（§7.7 问 3 审计处置），以 Q1 列序
                # 为准保守声明；StructuredOutputMode 亦仅支持 function_calling/json_in_text
                structured_output="function_calling",
                prompt_variant=_prompt_variant(model_name),
                # §7.7 问 5：3.7 未找到「思考拒绝 temperature」明文 → 保留采样参数；
                # 3.8 temperature 默认 0.6、<0.6 强制抬到 0.6（非整段拒绝）→ 仍可传
                accepts_temperature=True,
                # §7.7 问 6：官方无 tiktoken → chars:0.7 启发式（100 万 token ≈ 70 万汉字）
                tokenizer="chars:0.7",
                # Responses supports seven effort values, but xhigh/max are
                # region-limited.  Keep automatic presets within the five
                # values documented for every region; Chat stays parameter-free.
                effort_presets=(
                    {"fast": "minimal", "balanced": "medium", "deep": "high"}
                    if responses
                    else {}
                ),
                effort_options=(
                    ("none", "minimal", "low", "medium", "high")
                    if responses
                    else ()
                ),
                # §7.7 问 4：显式 cache_control（最小 1024 / TTL 5min=300s）+ 隐式
                # （最小 256，Qwen3.7 系列约 2000）；两者互斥（§7.7 问 4）。
                # cache_min_block_tokens 单值字段承载显式 cache_control 阈值（与
                # Anthropic 显式断点同一字段语义）；隐式路径是自动缓存，由
                # cache_params() 注释说明，无独立字段。
                cache_min_block_tokens=1024,
                cache_ttl_s=300,
                cache_breakpoints=(),
            )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        # FXC5/FX-CB11: driven by catalog thinking_param.sample, never by a
        # model-name heuristic. Qwen sample is "enable_thinking: true|false"
        # (3.8-preview: false forbidden) — so we set true when thinking is on
        # and never emit a {type:disabled} thinking object.
        contract = get_contract("qwen", str(model_config.get("model_name") or ""))
        sample = str(((contract or {}).get("thinking_param") or {}).get("sample") or "")
        body = kwargs.setdefault("extra_body", {})
        body.pop("thinking", None)  # DashScope uses enable_thinking, not {type}
        if self.uses_responses_api(model_config):
            # The Responses contract prefers reasoning.effort and documents
            # enable_thinking as a deprecated, non-standard compatibility field.
            body.pop("enable_thinking", None)
            return kwargs
        kwargs.pop("reasoning_effort", None)
        body.pop("reasoning", None)
        # FXC5/FX-CB11: strictly catalog-driven — a Qwen variant without a
        # catalog record gets NO thinking parameter (unknown-model fallback,
        # FXC6: never invent params from capabilities).
        if (
            "enable_thinking" in sample
            and caps.supports_reasoning
            and caps.thinking_default_on
        ):
            body.setdefault("enable_thinking", True)
        return kwargs
