"""模型能力元数据。

RxyCode 历史上把所有模型都当成 "OpenAI 兼容 + 全局常量" 处理：上下文窗口
硬编码 256000，token 一律用 gpt-4o 的分词器估算，provider 的 usage 字段靠
"两个都试一遍" 猜。模型一多这套就撑不住了。

本模块把这些隐式假设变成显式的、可配置的能力声明。

优先级（高到低）：
  1. 用户在模型配置里显式写的字段
  2. Provider 的探测结果
  3. Provider 的默认值
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

#: token 估算方式。
#: - "tiktoken:<encoding>" 用 tiktoken 的具名编码
#: - "chars:<ratio>"       用 字符数 / ratio 估算（无官方分词器时的兜底）
TokenizerSpec = str

#: 结构化输出的实现方式。
#: - "function_calling" 走 OpenAI 原生 tools 字段
#: - "json_in_text"     让模型在正文里输出 JSON，我们扫出来（RxyCode 现有的
#:                      planning/validation/synthesis 路径就是这种）
StructuredOutputMode = Literal["function_calling", "json_in_text"]


@dataclass(frozen=True)
class UsageFieldMap:
    """不同 provider 的 token usage 字段名差异。

    对应 core/agent_v2.py::_extract_cache_read 里原先的 "两个字段都试一遍"。
    """

    #: 命中前缀缓存的 token 数所在字段（顶层 usage 下）
    cache_read_flat: tuple[str, ...] = ("prompt_cache_hit_tokens",)
    #: 命中前缀缓存的 token 数所在嵌套路径，形如 ("prompt_tokens_details", "cached_tokens")
    cache_read_nested: tuple[tuple[str, str], ...] = (
        ("prompt_tokens_details", "cached_tokens"),
    )
    #: 推理/思考内容所在字段（在 delta 或 message 上）
    reasoning: tuple[str, ...] = ("reasoning_content",)


@dataclass(frozen=True)
class ModelCapabilities:
    """一个具体模型的能力声明。

    所有默认值都**刻意**与 Phase A 之前的硬编码行为一致，这样未识别的模型
    落到默认值时行为不变。改默认值等于改所有模型的行为，不要随手改。
    """

    #: provider 标识，例如 "openai" / "deepseek" / "anthropic" / "qwen"
    provider: str = "openai"

    #: 上下文窗口（token）。默认值 256000 来自 utils/streaming.py:47 的旧硬编码。
    context_window: int = 256_000

    #: 触发上下文压缩的阈值。默认 232000 来自 config/settings.py:299。
    #: 一般设为 context_window 的 ~90%。
    compaction_threshold: int = 232_000

    #: token 估算方式。默认 gpt-4o 来自 core/agent_v2.py:207 的旧硬编码。
    tokenizer: TokenizerSpec = "tiktoken:o200k_base"

    #: 是否支持 OpenAI 风格的原生 function calling。
    #: False 时 fast path 必须降级到 json_in_text。
    supports_function_calling: bool = True

    #: 是否是推理型模型（会产出 reasoning/thinking 内容）。
    supports_reasoning: bool = False

    #: 推理型模型通常不接受 temperature / top_p，传了会 400。
    accepts_temperature: bool = True

    #: 是否支持多模态图像输入。Phase C 会用到；Phase A 只是把字段先占上。
    supports_vision: bool = False

    #: 是否支持 prompt 前缀缓存（cache_control）。
    #: 对应 core/agent_v2.py:411-441 原先无条件注入 cache_control 的行为。
    supports_prompt_cache: bool = True

    #: 结构化输出走哪条路。
    structured_output: StructuredOutputMode = "function_calling"

    #: prompt 变体标识。core/prompts 会用 (stage, locale, prompt_variant)
    #: 三元组查模板；找不到变体就回退到通用模板。
    prompt_variant: str = "default"

    #: usage / reasoning 的字段名映射
    usage_fields: UsageFieldMap = field(default_factory=UsageFieldMap)

    #: 未归类的 provider 特有参数，会原样透传给 LLM 构造函数
    extra_body: dict[str, Any] = field(default_factory=dict)

    def merged_with_overrides(self, overrides: dict[str, Any]) -> "ModelCapabilities":
        """应用用户在模型配置里写的显式覆盖。

        只接受本 dataclass 已声明的字段名，未知字段忽略（不报错），因为
        model_config 里还混着 base_url / api_key 等非能力字段。
        """
        known = {f for f in self.__dataclass_fields__ if f != "usage_fields"}
        applied = {k: v for k, v in overrides.items() if k in known}
        if not applied:
            return self
        return replace(self, **applied)


#: 兜底能力：完全等价于 Phase A 之前的全局硬编码行为。
DEFAULT_CAPABILITIES = ModelCapabilities()


def resolve_graph_context_token_limit(
    cfg: dict[str, Any] | None,
    caps: Any = None,
) -> int:
    """Resolve LangGraph compaction threshold from config override or model caps."""
    context_cfg = (cfg or {}).get("context") or {}
    limit = context_cfg.get("graph_context_token_limit")
    if limit:
        return max(1000, int(limit))
    if caps is not None:
        threshold = getattr(caps, "compaction_threshold", None)
        if threshold:
            return max(1000, int(threshold))
    return 232_000
