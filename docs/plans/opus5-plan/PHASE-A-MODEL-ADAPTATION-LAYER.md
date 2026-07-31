# Phase A · 模型适配层（Model Adaptation Layer）

> **在整条路线中的位置**：本文件是 [`2026-07-31-EXECUTION-PLAN.md`](./2026-07-31-EXECUTION-PLAN.md) 的**后继扩展**，编号 Phase A。
> **前置条件**：主计划的 Phase 0（止血）与 Phase 1（Harness 说真话）**必须已完成**。原因见 §0.3。
> **后继**：[`PHASE-B-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-B-MULTI-AGENT-ORCHESTRATION.md)
>
> **一句话目标**：让 RxyCode 能针对不同模型（DeepSeek / Claude / GPT / Qwen / 本地模型）做差异化优化，而不是把所有模型都当成 "OpenAI 兼容 + 全局常量"。
>
> **执行模型**：Composer 2.5 为主力，Grok / Sonnet 5 辅助。分工见 §0.2。
> **基线日期**：2026-07-31　**预计工时**：3 周（1 名后端）

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | Composer 2.5 专用执行协议、模型分工、硬性规则 |
| [§1 为什么要做](#1-为什么要做实测证据) | 当前模型层的 7 个具体问题，全部带 file:line |
| [§2 目标架构](#2-目标架构) | ModelCapabilities + Provider 策略层，先看懂再动手 |
| [§3 任务卡 A1–A11](#3-任务卡) | 逐个执行 |
| [§4 出口检查](#4-phase-a-出口检查) | 怎么算做完 |
| [§5 扩展手册](#5-扩展手册加一个新-provider) | 以后加新模型怎么做 |

---

## §0 执行手册（必读）

### 0.1 Composer 2.5 专用执行协议

你（Composer 2.5）的优势是**快速、准确的多文件机械改写**；劣势是**开放式架构决策**。本文件已经把所有架构决策做完了——数据结构、文件布局、类名、方法签名全部给定。**你的任务是照着实现，不是重新设计。**

**每张任务卡按这 7 步执行，一步都不要跳：**

```
1. LOCATE   用 Grep 按「锚点字符串」定位，不要相信文档里的行号（行号会漂移）
2. READ     Read 工具读出完整上下文（至少锚点前后各 30 行）
3. WRITE    按「操作步骤」里给的代码写。代码是完整的，不要自己发挥
4. LINT     python -m ruff check <改动的文件>
5. TEST     跑任务卡的「验收命令」，把真实输出贴出来
6. CHECK    逐条对照「完成判据」打勾
7. COMMIT   用给定的 commit message
```

**如果任务卡的代码与现有代码冲突**（比如函数签名对不上、导入路径不存在）：**停下来报告，不要自己猜一个改法。** 报告格式：

```
任务卡 A3 步骤 2 无法执行：
- 文档说 core/agent_v2.py 有 _estimate_tokens(self, messages)
- 实际签名是 _estimate_tokens(self, messages, model=None)
- 我需要确认：是文档过时了，还是我定位错了函数？
```

### 0.2 三个模型的分工

| 模型 | 适合干什么 | 不要让它干什么 |
|---|---|---|
| **Composer 2.5** | 按任务卡实现代码、多文件同步改写、补测试、跑验收 | 独立做架构选型、决定要不要偏离本文档 |
| **Grok** | 查 DeepSeek / Anthropic / Qwen 的**最新 API 文档**，确认字段名和参数（A6/A8 需要）、给 provider 差异清单 | 直接改代码（它没有本仓库的完整上下文） |
| **Sonnet 5** | 审查 Composer 写完的 diff、检查是否漏改、写文档（A11） | 长任务连续实现（会丢上下文） |

**推荐流程**：Grok 查资料 → Composer 实现 → Sonnet 5 审查 → Composer 修。

### 0.3 为什么必须先做完主计划的 Phase 0 和 Phase 1

| 前置 | 为什么是硬前置 |
|---|---|
| Phase 0（ruff + CI 矩阵） | Phase A 会大范围改 `core/agent_v2.py` 和新增 `core/providers/` 包。没有 lint 和 CI，改错了不会有人发现 |
| Phase 1（evals 跑真 Agent + 基线） | Phase A 的**每一张任务卡**都要求"评测分数不下降"。没有可信基线，你无法证明自己没把模型层改坏 |

**如果这两个前置没做完，不要开始 Phase A。** 先回主计划。

### 0.4 硬性规则

| # | 规则 |
|---|---|
| MA1 | **不改变任何模型的现有行为**，除非任务卡明确说要改。Phase A 是"把隐式假设变成显式配置"，不是"调优" |
| MA2 | **每张卡做完跑一次 evals 基线比对**：`python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json`。分数掉了立刻停 |
| MA3 | **默认值必须与现状一致**。比如 `context_window` 的默认值就是现在硬编码的 256000，不要顺手改成"更合理"的值 |
| MA4 | **不要引入新的第三方 SDK**（`anthropic`、`dashscope` 等）。Phase A 只做**策略层**，传输仍走 OpenAI 兼容接口。真要接原生 SDK 是 Phase A 之后的事 |
| MA5 | **不要碰 `core/config.py`**。`LLMConfig`（`core/config.py:20-28`）是死代码，全仓库无 import。删它是 A11 的事，中途不要动 |
| MA6 | 一次一张卡，一张卡一个 commit |

### 0.5 环境自检

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .                    # Phase 0 做完了才会通过
python -m pytest tests -q -x --timeout=120
Test-Path evals\baselines\latest-agent.json   # Phase 1 做完了才是 True
git status --short                        # 必须干净
```

四条都过才开始。

---

## §1 为什么要做（实测证据）

以下 7 个问题都在 2026-07-31 用命令实测确认。

### 问题 1：只有一个 OpenAI 兼容工厂，没有 provider 抽象

全仓库的生产 LLM 都从这一个函数出来：

```1207:1226:core/agent_v2.py
    def _build_llm_from_config(self, model_config: dict):
        from langchain_openai import ChatOpenAI
        raw_llm = ChatOpenAI(
            model=model_config.get("model_name", "gpt-4o"),
            api_key=model_config.get("api_key"),
            base_url=model_config.get("base_url"),
            temperature=model_config.get("temperature", 0.7),
            max_tokens=model_config.get("max_tokens", 8192),
            max_retries=3,
            streaming=True,
            stream_usage=True,
        )
        return UsageTrackingLLM(raw_llm, ...)
```

**好消息**：只有一个地方要改。**坏消息**：`ChatAnthropic`、`ChatDeepSeek`、`init_chat_model` 在仓库中均**不存在**，也没有任何 `Provider` 类或协议。

调用点：`core/agent_v2.py:685`（`__init__`）、`:696-698`（role 路由）、`:959`（`switch_model`）。
**另有第二个独立工厂**：`evals/runner.py:585-605`，且**没有**包 `UsageTrackingLLM`——这是 A7 要一并收编的。

### 问题 2：模型配置里没有任何能力元数据

`config/model_manager.py:104-122` 的 `add_model()` 只写 5 个字段：

| 字段 | 默认 |
|---|---|
| `api_key_env` / `api_key_secret` | — |
| `base_url` | 必填 |
| `model_name` | 参数 |
| `max_tokens` | 8192 |
| `temperature` | 0.7 |

**不存在**的字段（全部实测确认 not found）：`context_window`、`supports_vision`、`supports_function_calling`、`supports_reasoning`、`tokenizer`、`prompt_variant`。

### 问题 3：上下文窗口是全局硬编码

| 位置 | 值 | 作用 |
|---|---|---|
| `utils/streaming.py:47` | `context_max = 256000` | TUI 上下文进度条 |
| `core/agent_v2.py:2480` `:2875` | `_ts.update_context(..., 256000)` | 同上 |
| `config/settings.py:299` | `graph_context_token_limit: 232000` | LangGraph 压缩触发阈值 |

给一个 64k 上下文的模型用 256k 的阈值，压缩永远不会触发，直接撞 API 报错。

### 问题 4：所有模型共用 GPT-4o 的分词器

```207:207:core/agent_v2.py
        enc = tiktoken.encoding_for_model("gpt-4o")
```

DeepSeek、Qwen、Claude 的分词方式与 GPT-4o 都不同。token 估算错了，压缩时机、计费、上下文进度条全都跟着错。

### 问题 5：provider 差异靠"两个字段都试一遍"

```163:200:core/agent_v2.py
    # DeepSeek 风格
    hit = usage.get("prompt_cache_hit_tokens")
    ...
    # OpenAI 风格
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
```

`_extract_reasoning()`（`:106-131`）同理，盲试 `reasoning_content` 字段。这种写法加到第三、第四个 provider 就会变成一堆 `if` 面条。**这是 provider 抽象缺失最直接的症状。**

另外 `_provider_name()`（`:1172-1179`）从 `base_url` 的 hostname 猜 provider 名——只用于限流 key，不驱动任何行为。

### 问题 6：Prompt 层只按 locale 分化，没有模型维度

`core/prompts/registry.py:141-180` 的 `get_role_prompt` / `get_system_prompt` 参数只有 `locale`、`tools`、`tool_names`。**没有** model / provider 参数。`PromptSpec.version` 是模板版本，不是模型变体。

### 问题 7：两套固定的 tool calling 约定，不可按模型切换

| 路径 | 约定 | 位置 |
|---|---|---|
| Fast path | OpenAI 原生 function calling | `core/agent_v2.py:1356-1375`（schema）、`:1418-1419`（payload）、`:2319-2359`（流式累积） |
| Executor | LangChain `create_agent` + `bind_tools` → 原生 function calling | `execution/executor.py:160-165` |
| Planning / Validation / Synthesis | **响应文本里扫 JSON** | `planning/structured_output.py:140-158` |

不支持 Claude 的 XML 风格，也不支持"这个模型不支持 function calling，降级到文本协议"。

### 问题小结

| 维度 | 现状 | Phase A 之后 |
|---|---|---|
| Provider 行为策略 | 无 | `core/providers/` 策略层 |
| 能力元数据 | 无 | `ModelCapabilities` |
| 上下文窗口 | 全局 256k/232k | per-model |
| Tokenizer | 全局 gpt-4o | per-model |
| usage/reasoning 字段 | 盲试 | provider 声明 |
| Prompt 变体 | 仅 locale | locale × model_family |
| Function calling 降级 | 无 | 按 capability 决定 |

---

## §2 目标架构

### 2.1 结构图

```
                config/model_capabilities.py
                ┌──────────────────────────────┐
                │  ModelCapabilities (dataclass)│
                │   context_window              │
                │   tokenizer                   │
                │   supports_function_calling   │
                │   supports_reasoning          │
                │   supports_vision             │
                │   usage_fields                │
                │   prompt_variant              │
                └──────────────┬───────────────┘
                               │ 由 model_config 解析得到
                               ▼
   core/providers/                       ┌────────────────────┐
   ┌───────────────────────────┐         │ ProviderRegistry   │
   │ BaseProvider (ABC)        │◄────────┤  match(base_url,   │
   │   capabilities()          │         │        model_name) │
   │   extract_usage(raw)      │         └────────────────────┘
   │   extract_reasoning(chunk)│
   │   build_llm(cfg)          │
   │   count_tokens(text)      │
   │   prompt_variant()        │
   └────────┬──────────────────┘
            │
   ┌────────┴────────┬──────────────┬──────────────┐
   │                 │              │              │
OpenAIProvider  DeepSeekProvider  AnthropicProvider  QwenProvider
（默认兜底）      （含 R1 推理）      （XML 倾向）     （分词器差异）
            │
            ▼
   core/agent_v2.py::_build_llm_from_config
   （改为：provider = registry.resolve(cfg); return provider.build_llm(cfg)）
```

### 2.2 三条不可违反的设计约束

| # | 约束 | 原因 |
|---|---|---|
| DC1 | **`BaseProvider` 的默认实现 = 当前 OpenAI 行为**。任何未识别的 model 落到 `OpenAIProvider`，行为与今天**逐字节一致** | 保证零回归 |
| DC2 | **Provider 只描述差异，不持有状态**。所有 provider 实例是无状态的、可缓存的单例 | 多 Agent（Phase B）会并发用它 |
| DC3 | **能力元数据优先级：用户显式配置 > provider 探测 > provider 默认值**。用户在配置里写死的永远赢 | 用户接的是中转站时，自动探测经常猜错 |

### 2.3 命名与文件布局（**不要改**）

```
config/
  model_capabilities.py       # ModelCapabilities dataclass + 解析函数
core/
  providers/
    __init__.py               # ProviderRegistry + resolve()
    base.py                   # BaseProvider ABC
    openai.py                 # OpenAIProvider（默认兜底）
    deepseek.py               # DeepSeekProvider
    anthropic.py              # AnthropicProvider
    qwen.py                   # QwenProvider
    tokenizers.py             # 分词器解析与缓存
tests/
  test_providers/
    __init__.py
    test_registry.py
    test_openai_provider.py
    test_deepseek_provider.py
    test_capabilities.py
```

---

## §3 任务卡

### A1 · 定义 ModelCapabilities

`P0` / 4h / 无依赖

**背景**
模型配置目前只有 5 个字段（§1 问题 2），没有任何能力描述。后面所有任务卡都依赖这个数据结构，所以它是第一张卡。

**涉及文件**
- 新建 `config/model_capabilities.py`
- 新建 `tests/test_providers/test_capabilities.py`

**操作步骤**

1. 新建 `config/model_capabilities.py`，**完整内容如下**（这是完整实现，直接写入）：

```python
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
```

2. 新建 `tests/test_providers/__init__.py`（空文件）和 `tests/test_providers/test_capabilities.py`：

```python
"""ModelCapabilities 的默认值锁定测试。

这些默认值必须与 Phase A 之前的硬编码行为一致，否则所有未识别模型的行为
会静默改变。改默认值时必须同步改这里，并在 PR 里说明理由。
"""
from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    UsageFieldMap,
)


def test_defaults_match_legacy_hardcoded_behaviour():
    c = DEFAULT_CAPABILITIES
    assert c.context_window == 256_000        # utils/streaming.py:47
    assert c.compaction_threshold == 232_000  # config/settings.py:299
    assert c.tokenizer == "tiktoken:o200k_base"  # agent_v2.py:207 gpt-4o
    assert c.supports_function_calling is True
    assert c.supports_prompt_cache is True
    assert c.structured_output == "function_calling"
    assert c.prompt_variant == "default"


def test_usage_fields_cover_both_legacy_probes():
    fields = DEFAULT_CAPABILITIES.usage_fields
    # agent_v2.py:163-200 原先盲试的两个字段都要在默认映射里
    assert "prompt_cache_hit_tokens" in fields.cache_read_flat
    assert ("prompt_tokens_details", "cached_tokens") in fields.cache_read_nested
    assert "reasoning_content" in fields.reasoning


def test_overrides_apply_known_fields_only():
    base = ModelCapabilities()
    merged = base.merged_with_overrides({
        "context_window": 64_000,
        "base_url": "http://example.com",   # 非能力字段，应被忽略
        "supports_reasoning": True,
    })
    assert merged.context_window == 64_000
    assert merged.supports_reasoning is True
    assert not hasattr(merged, "base_url")


def test_capabilities_are_frozen():
    import dataclasses
    import pytest
    c = ModelCapabilities()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.context_window = 1  # type: ignore[misc]


def test_usage_field_map_is_hashable():
    # frozen dataclass 用作 provider 单例的一部分，必须可哈希
    assert hash(UsageFieldMap()) == hash(UsageFieldMap())
```

**验收命令**

```powershell
python -m pytest tests/test_providers/test_capabilities.py -q
python -m ruff check config/model_capabilities.py tests/test_providers
```

**完成判据**
- [ ] `config/model_capabilities.py` 存在，内容与上面一致
- [ ] 5 个测试全绿
- [ ] ruff 零告警
- [ ] **本卡不改动任何现有文件**，`git status` 只有新增

**回滚**：删除新增文件

**Commit**
```
feat(model): add ModelCapabilities metadata schema

Model config had only 5 fields (base_url, api_key, model_name,
temperature, max_tokens). Context window, tokenizer and usage field names
were global hardcoded constants, so every model was treated as GPT-4o.

Defaults deliberately reproduce the previous hardcoded values so
unrecognised models behave identically.
```

---

### A2 · Provider 策略层骨架

`P0` / 8h / 依赖 A1

**背景**
建立 §2.1 的 `core/providers/` 包。这一卡**只建骨架和注册表，不接线到 agent_v2**——接线是 A7。这样做是为了让每张卡的 diff 都能独立 review。

**涉及文件**
- 新建 `core/providers/__init__.py`、`base.py`、`openai.py`
- 新建 `tests/test_providers/test_registry.py`

**操作步骤**

1. `core/providers/base.py`：

```python
"""Provider 策略层基类。

一个 Provider 描述"这一族模型和 OpenAI 默认行为有什么不同"，它**不持有
状态**——所有 provider 实例都是无状态单例，会被多个 Agent 并发使用。

新增 provider 的完整流程见
docs/plans/opus5-plan/PHASE-A-MODEL-ADAPTATION-LAYER.md §5。
"""

from __future__ import annotations

from typing import Any

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelCapabilities


class BaseProvider:
    """默认实现 == Phase A 之前的 OpenAI 行为。

    子类只覆写真正有差异的方法。任何未被识别的模型都会落到 OpenAIProvider
    （它直接继承本类且不覆写任何东西），因此行为与改造前逐字节一致。
    """

    #: provider 标识，必须与 ModelCapabilities.provider 一致
    name: str = "openai"

    # ---- 识别 ----------------------------------------------------------

    def matches(self, base_url: str, model_name: str) -> bool:
        """本 provider 是否负责该模型。

        注册表按注册顺序询问，第一个返回 True 的胜出；全部返回 False 时
        落到 OpenAIProvider。
        """
        return False

    # ---- 能力 ----------------------------------------------------------

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        """推导该模型的能力。

        子类应基于 DEFAULT_CAPABILITIES 做 dataclasses.replace()，
        不要从零构造，否则新增字段时会漏。
        """
        return DEFAULT_CAPABILITIES

    # ---- usage / reasoning 提取 ----------------------------------------

    def extract_cache_read(self, usage: dict, caps: ModelCapabilities) -> int:
        """从 usage 里取"命中前缀缓存的 token 数"。

        取代 core/agent_v2.py::_extract_cache_read 原先盲试两个字段的写法。
        """
        for key in caps.usage_fields.cache_read_flat:
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        for outer, inner in caps.usage_fields.cache_read_nested:
            nested = usage.get(outer)
            if isinstance(nested, dict):
                value = nested.get(inner)
                if isinstance(value, int) and value >= 0:
                    return value
        return 0

    def extract_reasoning(self, payload: Any, caps: ModelCapabilities) -> str:
        """从 delta / message 里取推理内容。取代 _extract_reasoning。"""
        if not caps.supports_reasoning:
            return ""
        for key in caps.usage_fields.reasoning:
            value = _get_attr_or_key(payload, key)
            if isinstance(value, str) and value:
                return value
        return ""

    # ---- 构造参数 ------------------------------------------------------

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        """返回传给 ChatOpenAI 的关键字参数。

        默认实现完全复刻 core/agent_v2.py:1207-1219 的原参数。
        子类可以删掉不支持的参数（例如推理模型不接受 temperature）。
        """
        kwargs: dict[str, Any] = {
            "model": model_config.get("model_name", "gpt-4o"),
            "api_key": model_config.get("api_key"),
            "base_url": model_config.get("base_url"),
            "max_tokens": model_config.get("max_tokens", 8192),
            "max_retries": 3,
            "streaming": True,
            "stream_usage": True,
        }
        if caps.accepts_temperature:
            kwargs["temperature"] = model_config.get("temperature", 0.7)
        if caps.extra_body:
            kwargs["extra_body"] = dict(caps.extra_body)
        return kwargs

    def supports_prompt_cache(self, caps: ModelCapabilities) -> bool:
        """是否往消息上注入 cache_control。对应 agent_v2.py:411-441。"""
        return caps.supports_prompt_cache


def _get_attr_or_key(obj: Any, key: str) -> Any:
    """OpenAI SDK 的 delta 有时是对象、有时是 dict，两种都要能取。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
```

2. `core/providers/openai.py`：

```python
"""OpenAI provider —— 同时也是所有未识别模型的兜底。

刻意不覆写 BaseProvider 的任何方法：基类的默认实现就是 Phase A 之前的
行为，这保证了改造的零回归性。
"""

from core.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    def matches(self, base_url: str, model_name: str) -> bool:
        # 兜底 provider 不参与匹配，由注册表在全部落空时直接选用。
        return False
```

3. `core/providers/__init__.py`：

```python
"""Provider 注册表。

解析顺序：
  1. model_config 里显式写了 "provider" 字段 → 按名字直取
  2. 依次问每个已注册 provider 的 matches(base_url, model_name)
  3. 全部落空 → OpenAIProvider（行为等同 Phase A 之前）
"""

from __future__ import annotations

from functools import lru_cache

from core.providers.base import BaseProvider
from core.providers.openai import OpenAIProvider

_FALLBACK = OpenAIProvider()

#: 注册顺序即匹配优先级。越具体的越靠前。
_PROVIDERS: list[BaseProvider] = [
    # A3 起逐个填入：DeepSeekProvider(), AnthropicProvider(), QwenProvider()
]

_BY_NAME: dict[str, BaseProvider] = {p.name: p for p in _PROVIDERS}
_BY_NAME[_FALLBACK.name] = _FALLBACK


def resolve(model_config: dict) -> BaseProvider:
    """为一份模型配置选出 provider。"""
    explicit = str(model_config.get("provider") or "").strip().lower()
    if explicit and explicit in _BY_NAME:
        return _BY_NAME[explicit]

    base_url = str(model_config.get("base_url") or "")
    model_name = str(model_config.get("model_name") or "")
    for provider in _PROVIDERS:
        if provider.matches(base_url, model_name):
            return provider
    return _FALLBACK


def get_by_name(name: str) -> BaseProvider | None:
    return _BY_NAME.get(name.strip().lower())


def list_providers() -> list[str]:
    return sorted(_BY_NAME)


@lru_cache(maxsize=256)
def _cached_caps_key(base_url: str, model_name: str, provider_hint: str) -> str:
    """capabilities 解析的缓存键。provider 无状态，结果可安全缓存。"""
    return f"{provider_hint}|{base_url}|{model_name}"


__all__ = ["BaseProvider", "resolve", "get_by_name", "list_providers"]
```

4. `tests/test_providers/test_registry.py`：

```python
"""Provider 注册表解析规则测试。"""
import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES
from core import providers
from core.providers.openai import OpenAIProvider


def test_unknown_model_falls_back_to_openai():
    p = providers.resolve({"base_url": "https://unknown.example/v1",
                           "model_name": "mystery-1"})
    assert isinstance(p, OpenAIProvider)


def test_fallback_capabilities_are_the_legacy_defaults():
    p = providers.resolve({"base_url": "", "model_name": ""})
    assert p.capabilities({}) == DEFAULT_CAPABILITIES


def test_explicit_provider_field_wins():
    p = providers.resolve({"provider": "openai",
                           "base_url": "https://whatever/v1",
                           "model_name": "x"})
    assert p.name == "openai"


def test_unknown_explicit_provider_falls_back_silently():
    # 用户可能写了错别字；不应该崩，应该退回兜底
    p = providers.resolve({"provider": "not-a-real-provider"})
    assert isinstance(p, OpenAIProvider)


def test_llm_kwargs_reproduce_legacy_arguments():
    p = providers.resolve({})
    caps = p.capabilities({})
    kwargs = p.llm_kwargs(
        {"model_name": "gpt-4o", "api_key": "k", "base_url": "b"}, caps,
    )
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["max_tokens"] == 8192
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_retries"] == 3
    assert kwargs["streaming"] is True
    assert kwargs["stream_usage"] is True


@pytest.mark.parametrize("usage,expected", [
    ({"prompt_cache_hit_tokens": 128}, 128),
    ({"prompt_tokens_details": {"cached_tokens": 64}}, 64),
    ({}, 0),
    ({"prompt_cache_hit_tokens": "bad"}, 0),
])
def test_extract_cache_read_handles_both_conventions(usage, expected):
    p = providers.resolve({})
    assert p.extract_cache_read(usage, p.capabilities({})) == expected
```

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
python -m pytest tests -q -x --timeout=300
```

**完成判据**
- [ ] `core/providers/` 三个文件存在
- [ ] `tests/test_providers/test_registry.py` 全绿
- [ ] **未修改任何现有文件**（`git status` 只有新增）
- [ ] 全量测试仍绿

**常见坑**
- 不要在这一卡里改 `agent_v2.py`。骨架和接线分开，接线在 A7。
- `_PROVIDERS` 列表现在是空的，这是**故意的**。A3–A5 逐个填。

**Commit**
```
feat(model): add provider strategy layer skeleton

BaseProvider's default implementation reproduces the previous OpenAI-only
behaviour byte for byte, so unrecognised models are unaffected. Not yet
wired into agent_v2 — that lands in A7.
```

---

### A3 · DeepSeekProvider

`P0` / 6h / 依赖 A2

**背景**
DeepSeek 是当前最需要特化的目标：它用 `prompt_cache_hit_tokens` 而非 OpenAI 的嵌套字段（`agent_v2.py:163-200` 已经在盲试这个），R1 系列会产出 `reasoning_content` 且**不接受 temperature**，上下文窗口也不是 256k。

**⚠️ 动手前先让 Grok 查资料。** 本卡的具体数值（context window、是否支持 function calling、参数限制）**必须以 DeepSeek 官方文档的当前状态为准**，不要照抄下面代码里的占位值。给 Grok 的提问模板：

```
查 DeepSeek 官方 API 文档（platform.deepseek.com/api-docs），回答：
1. deepseek-chat 和 deepseek-reasoner 各自的 context window 是多少 token？
2. deepseek-reasoner 是否支持 tools / function calling？
3. deepseek-reasoner 是否接受 temperature / top_p / presence_penalty？传了会怎样？
4. reasoning 内容在流式响应里的字段名是什么？在 delta 上还是 message 上？
5. 前缀缓存命中的 token 数在 usage 的哪个字段？
6. 官方推荐的 tokenizer 是什么？有没有 tiktoken 兼容的 encoding？
每条都给出文档原文引用和 URL。
```

拿到答案后，把下面代码里标了 `# TODO(grok)` 的常量替换掉，**并把 Grok 给的 URL 写进注释**。

**涉及文件**
- 新建 `core/providers/deepseek.py`
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_deepseek_provider.py`

**操作步骤**

1. `core/providers/deepseek.py`：

```python
"""DeepSeek provider。

与 OpenAI 默认行为的差异：
  - 前缀缓存命中数在顶层 usage.prompt_cache_hit_tokens（OpenAI 是嵌套在
    prompt_tokens_details.cached_tokens 里）
  - deepseek-reasoner 产出 reasoning_content，且不接受采样参数
  - 上下文窗口远小于我们原先硬编码的 256k

数值来源：<把 Grok 查到的官方文档 URL 写在这里>
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
    cache_read_nested=(),          # DeepSeek 不用嵌套形式
    reasoning=("reasoning_content",),
)

# TODO(grok): 用官方文档核实下列数值后替换，并在上面的 docstring 里补 URL
_CHAT_CONTEXT = 128_000
_REASONER_CONTEXT = 128_000


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def matches(self, base_url: str, model_name: str) -> bool:
        return "deepseek" in base_url.lower() or "deepseek" in model_name.lower()

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        is_reasoner = "reasoner" in model_name or model_name.endswith("-r1")

        context = _REASONER_CONTEXT if is_reasoner else _CHAT_CONTEXT
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            context_window=context,
            # 留 10% 余量给输出，与 OpenAI 侧 232000/256000 的比例一致
            compaction_threshold=int(context * 0.9),
            usage_fields=_DEEPSEEK_USAGE,
            supports_reasoning=is_reasoner,
            # TODO(grok): 核实 reasoner 是否真的拒绝 temperature
            accepts_temperature=not is_reasoner,
            # TODO(grok): 核实 reasoner 是否支持 tools
            supports_function_calling=not is_reasoner,
            structured_output=("json_in_text" if is_reasoner
                               else "function_calling"),
            prompt_variant=("deepseek-reasoner" if is_reasoner else "deepseek"),
            # DeepSeek 分词器与 GPT 不同，官方无 tiktoken encoding；
            # 用字符比估算，中文场景约 1.6 字符/token。
            tokenizer="chars:1.6",
        )
        return caps.merged_with_overrides(model_config)
```

2. 在 `core/providers/__init__.py` 的 `_PROVIDERS` 里注册（**放在列表最前面**，因为它比兜底更具体）：

```python
from core.providers.deepseek import DeepSeekProvider

_PROVIDERS: list[BaseProvider] = [
    DeepSeekProvider(),
]
```

3. `tests/test_providers/test_deepseek_provider.py`：

```python
"""DeepSeek provider 行为测试。"""
import pytest

from core import providers
from core.providers.deepseek import DeepSeekProvider


@pytest.mark.parametrize("cfg", [
    {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-chat"},
    {"base_url": "https://relay.example/v1", "model_name": "deepseek-reasoner"},
    {"base_url": "https://api.DeepSeek.com", "model_name": "x"},
])
def test_matches_by_url_or_model_name(cfg):
    assert isinstance(providers.resolve(cfg), DeepSeekProvider)


def test_chat_model_keeps_sampling_and_tools():
    caps = providers.resolve(
        {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-chat"}
    ).capabilities({"model_name": "deepseek-chat"})
    assert caps.accepts_temperature is True
    assert caps.supports_function_calling is True
    assert caps.supports_reasoning is False
    assert caps.structured_output == "function_calling"


def test_reasoner_drops_sampling_and_downgrades_structured_output():
    caps = providers.resolve(
        {"base_url": "https://api.deepseek.com/v1",
         "model_name": "deepseek-reasoner"}
    ).capabilities({"model_name": "deepseek-reasoner"})
    assert caps.supports_reasoning is True
    assert caps.accepts_temperature is False
    assert caps.structured_output == "json_in_text"


def test_reasoner_llm_kwargs_omit_temperature():
    p = providers.resolve({"model_name": "deepseek-reasoner"})
    caps = p.capabilities({"model_name": "deepseek-reasoner"})
    kwargs = p.llm_kwargs({"model_name": "deepseek-reasoner"}, caps)
    assert "temperature" not in kwargs


def test_cache_read_uses_flat_field_only():
    p = providers.resolve({"model_name": "deepseek-chat"})
    caps = p.capabilities({"model_name": "deepseek-chat"})
    assert p.extract_cache_read({"prompt_cache_hit_tokens": 42}, caps) == 42
    # DeepSeek 不用嵌套形式，即使出现也不该被误读
    assert p.extract_cache_read(
        {"prompt_tokens_details": {"cached_tokens": 99}}, caps
    ) == 0


def test_user_override_beats_provider_default():
    p = providers.resolve({"model_name": "deepseek-chat"})
    caps = p.capabilities({"model_name": "deepseek-chat", "context_window": 32_000})
    assert caps.context_window == 32_000


def test_context_window_is_not_the_global_256k():
    caps = providers.resolve({"model_name": "deepseek-chat"}).capabilities(
        {"model_name": "deepseek-chat"}
    )
    assert caps.context_window != 256_000, (
        "DeepSeek must not inherit the legacy global 256k window"
    )
```

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
```

**完成判据**
- [ ] 所有 `TODO(grok)` 已用官方文档数值替换，且 docstring 里有 URL
- [ ] 7 个测试全绿
- [ ] `providers.resolve()` 对非 DeepSeek 配置仍返回 `OpenAIProvider`（注册新 provider 不能误伤兜底）
- [ ] 仍未接线到 `agent_v2.py`

**常见坑**
- `matches()` 用了子串匹配 `"deepseek" in base_url`。如果用户接的是中转站（base_url 里没有 deepseek 字样但模型名是 `deepseek-chat`），靠 model_name 那一半兜住。这是**故意的双条件**，不要改成 `and`。

**Commit**
```
feat(model): add DeepSeekProvider with reasoner-aware capabilities

DeepSeek reports prefix-cache hits in a flat usage field and its reasoner
models reject sampling parameters — both were previously handled by
blind-probing two field names in agent_v2._extract_cache_read.
```

---

### A4 · AnthropicProvider 与 QwenProvider

`P1` / 6h / 依赖 A2

**背景**
补齐另外两个常用族。做法与 A3 完全一致，**先让 Grok 查文档拿准确数值**。

**Grok 提问模板**

```
分别查 Anthropic Claude 与阿里 DashScope/Qwen 的官方 API 文档，回答：
1. 各主力模型的 context window
2. 是否支持 OpenAI 兼容端点？兼容端点下 function calling 可用吗？
3. prompt 缓存（prompt caching）怎么开启？usage 里命中数字段名是什么？
4. 是否有 reasoning/thinking 输出？字段名？
5. 官方 tokenizer，以及是否有 tiktoken 兼容 encoding
每条给文档原文和 URL。
```

**操作步骤**

1. 按 A3 的模式新建 `core/providers/anthropic.py` 与 `core/providers/qwen.py`
2. 关键差异点（用 Grok 的答案确认后填）：
   - **Anthropic**：`prompt_variant="claude"`（Claude 对 XML 结构化 prompt 响应更好，A9 会用到这个标识）；prompt 缓存的 `cache_control` 语义与 OpenAI 不同，需要在 `supports_prompt_cache` 上体现
   - **Qwen**：分词器差异最大，`tokenizer` 用 `chars:` 估算；DashScope 兼容端点的 function calling 支持情况需确认
3. 注册进 `_PROVIDERS`，**顺序**：`[DeepSeekProvider(), AnthropicProvider(), QwenProvider()]`
4. 每个 provider 至少 5 个测试，参考 `test_deepseek_provider.py` 的结构

**完成判据**
- [ ] 两个 provider 文件 + 两个测试文件
- [ ] 所有数值有文档 URL 出处
- [ ] `test_registry.py` 里的兜底测试仍绿（新 provider 不误伤未识别模型）
- [ ] 仍未接线

---

### A5 · Tokenizer 适配层

`P0` / 6h / 依赖 A1

**背景**
`core/agent_v2.py:207` 给**所有**模型用 `tiktoken.encoding_for_model("gpt-4o")`。DeepSeek、Qwen、Claude 的分词方式都不同，估算偏差会传导到压缩时机、计费和上下文进度条。

**涉及文件**
- 新建 `core/providers/tokenizers.py`
- 新建 `tests/test_providers/test_tokenizers.py`

**操作步骤**

1. `core/providers/tokenizers.py`：

```python
"""按 ModelCapabilities.tokenizer 规格估算 token 数。

规格格式：
  "tiktoken:<encoding_name>"  用 tiktoken 具名编码（精确）
  "chars:<ratio>"             字符数 / ratio（无官方分词器时的兜底估算）

tiktoken 的 encoding 对象构造开销不小，按名字缓存。
"""

from __future__ import annotations

from functools import lru_cache

#: tiktoken 不可用或规格无法解析时的兜底比例。
_FALLBACK_RATIO = 4.0


@lru_cache(maxsize=16)
def _get_tiktoken_encoding(name: str):
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(name)
    except (ValueError, KeyError):
        return None


def count_tokens(text: str, spec: str) -> int:
    """按 *spec* 估算 *text* 的 token 数。

    永不抛异常：任何解析失败都退化为字符比估算，因为 token 计数只用于
    压缩时机和显示，估错不应该让请求失败。
    """
    if not text:
        return 0

    if spec.startswith("tiktoken:"):
        encoding = _get_tiktoken_encoding(spec.split(":", 1)[1])
        if encoding is not None:
            return len(encoding.encode(text, disallowed_special=()))
        return int(len(text) / _FALLBACK_RATIO) + 1

    if spec.startswith("chars:"):
        try:
            ratio = float(spec.split(":", 1)[1])
        except ValueError:
            ratio = _FALLBACK_RATIO
        if ratio <= 0:
            ratio = _FALLBACK_RATIO
        return int(len(text) / ratio) + 1

    return int(len(text) / _FALLBACK_RATIO) + 1
```

2. 测试要覆盖：tiktoken 路径、chars 路径、空串、非法 spec、tiktoken 缺失时的降级（用 `monkeypatch` 让 import 失败）。

3. **本卡不改 `agent_v2.py:207`**，接线在 A7。

**验收命令**

```powershell
python -m pytest tests/test_providers/test_tokenizers.py -q
python -m ruff check core/providers/tokenizers.py
```

**完成判据**
- [ ] 5 种情况都有测试
- [ ] `count_tokens` 在任何输入下都不抛异常（写一个 fuzz 风格的参数化测试）
- [ ] 未修改现有文件

---

### A6 · 接线：LLM 工厂改走 Provider

`P0` / 8h / **依赖 A2 A3 A4 A5**

**背景**
这是 Phase A 最关键、也最危险的一卡——第一次修改 `core/agent_v2.py`。做完之前的所有卡都是纯新增，从这一卡开始有回归风险。

**涉及文件**
- `core/agent_v2.py`：锚点 `def _build_llm_from_config`（约 `:1207`）
- `core/agent_v2.py`：锚点 `def _provider_name`（约 `:1172`）
- `evals/runner.py`：锚点 `ChatOpenAI(`（约 `:585`）

**操作步骤**

1. **先记录基线**。改之前跑一次并把输出存下来：

```powershell
python -m pytest tests -q --timeout=600 | Tee-Object -FilePath a6-before.txt
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json | Tee-Object -FilePath a6-evals-before.txt
```

2. 用 `Grep` 定位 `_build_llm_from_config`，`Read` 出完整实现（含 `UsageTrackingLLM(...)` 的全部参数）。**把原文抄进你的工作笔记**，改完要逐参数对照。

3. 改写为：

```python
    def _build_llm_from_config(self, model_config: dict):
        """按 provider 策略构造 LLM。

        provider 的默认实现（OpenAIProvider）复刻了改造前的参数，因此未识别
        的模型行为不变。差异化只发生在显式声明了差异的 provider 上。
        """
        from langchain_openai import ChatOpenAI

        from core import providers

        provider = providers.resolve(model_config)
        caps = provider.capabilities(model_config)
        raw_llm = ChatOpenAI(**provider.llm_kwargs(model_config, caps))

        return UsageTrackingLLM(
            raw_llm,
            rate_limiter=self._rate_limiter,
            rate_provider=provider.name,
            rate_model=str(model_config.get("model_name") or "unknown"),
            # 下面这些参数照抄原实现，一个都不要漏
            ...
        )
```

> **注意第 3 步的 `...`**：原实现的 `UsageTrackingLLM(...)` 还有别的参数（第 2 步你已经抄下来了）。**全部保留原样**，只把 `rate_provider` 从 `self._provider_name(model_config)` 换成 `provider.name`。

4. 把解析出的 `caps` 挂到 agent 上，供后续卡使用。在 `_build_llm_from_config` 里 `return` 之前不要挂（那是工厂函数），改在 `__init__`（锚点 `self._llm = self._build_llm()`，约 `:685`）之后加：

```python
        from core import providers
        self._provider = providers.resolve(self.model_config)
        self._capabilities = self._provider.capabilities(self.model_config)
```

`switch_model()`（约 `:959`）里也要同步刷新这两个属性——**用 Grep 确认 switch_model 里重建 LLM 的那一行，在它后面加同样的两行**。

5. 保留 `_provider_name()` 但标为过渡：

```python
    def _provider_name(self, model_config: dict) -> str:
        """从 base_url 猜 provider 名。

        已被 core.providers.resolve() 取代，仅为向后兼容保留。
        新代码请用 self._provider.name。
        """
```

6. **收编 evals 的第二个工厂**。`evals/runner.py:585-605` 自己 new 了一个 `ChatOpenAI` 且没包 `UsageTrackingLLM`。改成复用同一条路径：

```python
    from core import providers

    provider = providers.resolve(model_config)
    caps = provider.capabilities(model_config)
    llm = ChatOpenAI(**provider.llm_kwargs(model_config, caps))
```

7. 跑对照：

```powershell
python -m pytest tests -q --timeout=600 | Tee-Object -FilePath a6-after.txt
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

用 `Compare-Object` 比对 before/after 的测试数量。

**验收命令**

```powershell
python -m pytest tests -q --timeout=600
python -m ruff check core evals
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
# 手动：起 API + OpenTUI，用现有的默认模型对话一轮
```

**完成判据**
- [ ] 测试通过数与 `a6-before.txt` **完全一致**
- [ ] evals 基线比对显示 **0 regression**
- [ ] 手动对话正常，token 统计和上下文进度条显示正常
- [ ] `evals/runner.py` 不再有独立的 `ChatOpenAI(...)` 构造
- [ ] `UsageTrackingLLM` 的所有原参数都保留了（逐个对照第 2 步的笔记）
- [ ] 删掉临时文件 `a6-*.txt`

**回滚**：`git revert <commit>`。这一卡**必须是独立 commit**，方便出问题时单独退。

**常见坑**
- **最容易出错的是漏抄 `UsageTrackingLLM` 的参数**。原调用可能有 5–8 个参数，Read 的时候一定要读到闭合括号。
- `switch_model()` 里如果忘了刷新 `self._capabilities`，切换模型后能力元数据会停留在旧模型上，症状是"切到小上下文模型后压缩仍不触发"。
- 不要在这一卡里顺手改 `tiktoken` 或上下文常量，那是 A7。

**Commit**
```
refactor(model): route LLM construction through the provider layer

Both production (agent_v2) and eval (evals/runner) LLM factories now go
through core.providers.resolve(). OpenAIProvider reproduces the previous
arguments exactly, so behaviour is unchanged for unrecognised models.
```

---

### A7 · 消除硬编码上下文与分词器

`P0` / 8h / 依赖 A6

**背景**
三处硬编码 256000/232000（§1 问题 3）和一处全局 `tiktoken gpt-4o`（问题 4）。A6 已经让 agent 持有 `self._capabilities`，现在把这些常量换掉。

**涉及文件（每处都用 Grep 定位，不要信行号）**

| 文件 | 锚点 | 当前值 |
|---|---|---|
| `core/agent_v2.py` | `encoding_for_model("gpt-4o")` | 全局分词器 |
| `core/agent_v2.py` | `update_context(` ×2 | `256000` |
| `utils/streaming.py` | `context_max` | `256000` |
| `config/settings.py` | `graph_context_token_limit` | `232000` |

**操作步骤**

1. **分词器**。找到 `_estimate_tokens`（锚点 `encoding_for_model`），改为：

```python
    def _estimate_tokens(self, messages) -> int:
        """按当前模型的分词规格估算 token 数。

        改造前这里对所有模型硬用 gpt-4o 的编码，DeepSeek / Qwen 的偏差可达
        20% 以上，会让压缩时机和计费一起偏。
        """
        from core.providers.tokenizers import count_tokens

        spec = getattr(self, "_capabilities", None)
        spec = spec.tokenizer if spec else "tiktoken:o200k_base"
        total = 0
        for m in messages:
            content = getattr(m, "content", "") or ""
            if isinstance(content, str):
                total += count_tokens(content, spec)
        return total
```

> 保留 `getattr(self, "_capabilities", None)` 的兜底：`_estimate_tokens` 可能在 `__init__` 完成之前被调用。

2. **两处 `update_context(..., 256000)`**：换成 `self._capabilities.context_window`。

3. **`utils/streaming.py` 的 `context_max`**：这是个模块级默认值，不能直接访问 agent。改为构造参数，由调用方传入：

```python
# utils/streaming.py
#: 未指定时的兜底上下文窗口。真实值应由调用方按 ModelCapabilities 传入。
DEFAULT_CONTEXT_MAX = 256_000
```

然后把构造 `StreamTUI`（或对应类）的地方改成传 `self._capabilities.context_window`。**用 Grep 找出所有构造点**。

4. **`config/settings.py:299` 的 `graph_context_token_limit`**：这是 LangGraph 压缩阈值，被 `core/graph.py` 读取。保留配置项作为**显式覆盖**，但默认值改为 `None`，表示"跟随模型能力"：

```python
    # None 表示跟随当前模型的 ModelCapabilities.compaction_threshold。
    # 显式设为数字则强制覆盖（用于压测或规避 provider 元数据不准的情况）。
    "graph_context_token_limit": None,
```

然后在 `core/graph.py` 读取处加解析：**用 Grep 找 `graph_context_token_limit` 的所有读取点**，改为：

```python
    limit = cfg.get("context", {}).get("graph_context_token_limit")
    if not limit:
        caps = state.get("_capabilities")
        limit = caps.compaction_threshold if caps else 232_000
```

这需要把 `_capabilities` 注入 graph state——在 `_prepare_graph_state`（锚点，约 `agent_v2.py:823`）里加 `state["_capabilities"] = self._capabilities`，并在 `core/state.py` 的 `AgentState` TypedDict 里加字段：

```python
    #: 当前模型的能力元数据（运行时注入，不序列化）
    _capabilities: Any
```

5. 加一个回归测试 `tests/test_model_capabilities_wiring.py`，断言：
   - 用一个 `context_window=32000` 的假 provider 时，压缩阈值确实变成 28800 而不是 232000
   - `_estimate_tokens` 在不同 tokenizer spec 下给出不同结果

**验收命令**

```powershell
python -m pytest tests -q --timeout=600
python -m ruff check .
Select-String -Path core\agent_v2.py,utils\streaming.py -Pattern "256000|256_000"
# 期望：只剩注释或 DEFAULT_* 兜底常量，没有裸用的
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] `encoding_for_model("gpt-4o")` 已消失
- [ ] 三处 256000 已参数化
- [ ] `graph_context_token_limit` 默认 `None` 且能被模型能力驱动
- [ ] 新增的 wiring 测试通过
- [ ] evals 无回归（**默认模型的能力值与旧硬编码一致，所以分数应当完全不变**）

**常见坑**
- 如果默认模型的 `context_window` 不等于 256000，evals 分数**会**变。那说明你把 A1 的默认值改了——回去检查 `DEFAULT_CAPABILITIES`。

**Commit**
```
refactor(model): drive context window and tokenizer from capabilities

Context limits were hardcoded to 256000/232000 in three places and token
estimation used the gpt-4o encoding for every model, so a 64k model would
never trigger compaction and DeepSeek token counts were ~20% off.
```

---

### A8 · 推理模型专项适配

`P1` / 8h / 依赖 A6 A7

**背景**
推理型模型（DeepSeek-R1、o 系列）有三个特殊性：产出独立的 reasoning 流、拒绝采样参数、部分不支持 function calling。A3 已经在 capabilities 里声明了这些，本卡把声明**落实到调用路径**。

**涉及文件**
- `core/agent_v2.py`：`_extract_reasoning`（锚点，约 `:106`）、`_extract_cache_read`（约 `:163`）、`_record_usage`（约 `:271`）、`_raw_stream`（约 `:1377`）
- `core/agent_v2.py`：`_apply_cache_control`（约 `:411`）
- `planning/structured_output.py`：`invoke_structured_output`（约 `:140`）

**操作步骤**

1. **把字段盲试改成 provider 委派**。`_extract_cache_read` 和 `_extract_reasoning` 现在自己试字段名，改为调用 provider：

```python
    def _extract_cache_read(self, usage: dict) -> int:
        return self._provider.extract_cache_read(usage, self._capabilities)
```

> `UsageTrackingLLM` 是独立于 `AgentV2` 的类（约 `:333`）。它需要拿到 provider 和 caps——**在构造时传进去**，即 A6 第 3 步的 `UsageTrackingLLM(...)` 调用里加两个参数 `provider=provider, capabilities=caps`，并在 `UsageTrackingLLM.__init__` 里存下来。

2. **cache_control 按能力开关**。`_apply_cache_control`（约 `:411`）现在无条件注入 `{"type": "ephemeral"}`，改为：

```python
        if not self._provider.supports_prompt_cache(self._capabilities):
            return messages
```

3. **不支持 function calling 时降级**。在 fast path 组 payload 的地方（锚点 `payload["tools"]`，约 `:1418`）加：

```python
        if core_tools and self._capabilities.supports_function_calling:
            payload["tools"] = [self._tool_to_openai(t) for t in core_tools]
        elif core_tools:
            # 该模型不支持原生 tools，把工具清单写进 prompt，让它输出 JSON。
            # 解析走 planning/structured_output.py 的同一套 iter_balanced_json。
            ...
```

> **这一步的降级实现比较重**。如果时间紧，**先只做到"检测到不支持就明确报错而不是静默失败"**，把完整降级留给后续卡。明确报错比错误行为好得多。在任务卡里标注你选了哪条路。

4. **推理内容的流式转发**。确认 `_raw_stream` 里对 `delta.reasoning_content` 的处理走了 provider（第 1 步已改），并且 TUI 的 thinking 面板仍正常显示。

**验收命令**

```powershell
python -m pytest tests -q --timeout=600
python -m ruff check .
# 如果手头有 DeepSeek key，手动跑一轮 reasoner 模型对话
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] `_extract_cache_read` / `_extract_reasoning` 不再自己试字段名
- [ ] `cache_control` 受 `supports_prompt_cache` 控制
- [ ] 不支持 function calling 的模型要么正确降级，要么明确报错（不能静默产生错误行为）
- [ ] 默认模型（OpenAI 系）行为不变，evals 无回归
- [ ] PR 描述里说明第 3 步选了"完整降级"还是"明确报错"

---

### A9 · per-model prompt 变体机制

`P1` / 8h / 依赖 A6

**背景**
`core/prompts/registry.py:141-180` 的查找只有 `(stage, locale)` 两个维度。Claude 对 XML 结构响应更好，推理模型不需要 few-shot（反而会干扰），这些都需要变体机制。

**涉及文件**
- `core/prompts/registry.py`、`templates.py`
- 所有 `get_role_prompt(` / `get_system_prompt(` 调用点（用 Grep 找全）

**操作步骤**

1. `PromptRegistry` 的查找键从 `(stage, locale)` 扩为 `(stage, locale, variant)`，**回退链**是：

```
(stage, locale, variant)  →  (stage, locale, "default")  →  报错
```

2. `get_role_prompt` / `get_system_prompt` 加可选参数 `variant: str = "default"`。**不要改成必选**——现有几十个调用点都不传，靠默认值保持兼容。

3. `AgentV2` 在调用时传 `variant=self._capabilities.prompt_variant`。用 Grep 找出 `agent_v2.py` 里所有 `get_role_prompt(` / `get_system_prompt(` 调用点（fast path 约 `:2141` `:2714`），逐个加参数。

4. **本卡不新增任何实际变体模板**，只建机制。所有模型仍走 `"default"`。这样这一卡的 evals 分数必然不变，风险为零。第一个真实变体（Claude XML）留到 A11 之后按需加。

5. 测试：`tests/test_core/test_prompts.py` 加变体回退测试。

**完成判据**
- [ ] 三级回退链实现且有测试
- [ ] 所有现有调用点不传 variant 时行为**完全不变**
- [ ] `agent_v2.py` 传入了 `self._capabilities.prompt_variant`
- [ ] evals 分数不变（因为还没有真实变体）

---

### A10 · 评测：per-model 对比矩阵

`P1` / 6h / 依赖 A6，**依赖主计划 Phase 1 全部完成**

**背景**
Phase A 的价值必须能被度量。主计划 H2 已经建立了 `--backend agent|raw-llm` 的对比框架，现在加一个模型维度。

**操作步骤**

1. `evals/cli.py` 加 `--models <id1,id2,...>`，对每个模型跑一遍全量。
2. 报告输出矩阵：

```
Task                         gpt-4o    deepseek-chat   deepseek-reasoner   qwen-max
readcode-01                    PASS         PASS              PASS           FAIL
bugfix-03                      PASS         FAIL              PASS           PASS
...
Pass rate                      84%          71%               79%            68%
Avg tokens                   9,870       12,400            31,200         11,100
Avg duration                 41.7s        38.2s            112.4s          44.1s
```

3. 基线按模型分文件存：`evals/baselines/<date>-agent-<model>.json`。
4. 至少跑一次完整矩阵并把结果提交进 git（作为 Phase A 的成果证据）。

**完成判据**
- [ ] `--models` 参数可用
- [ ] 矩阵报告可读
- [ ] 至少 3 个模型的基线已提交
- [ ] PR 描述里贴出矩阵，指出哪些任务在哪些模型上失败（这是后续优化的输入）

---

### A11 · 文档与死代码清理

`P1` / 6h / 依赖 A1–A10

**操作步骤**

1. 新建 `docs/modules/providers.md`，内容必须包含：
   - `ModelCapabilities` 每个字段的语义和默认值来源
   - provider 解析顺序（显式 > matches > 兜底）
   - **加一个新 provider 的完整步骤**（照抄本文件 §5）
   - 三条设计约束（§2.2）及其理由

2. 更新 `docs/modules/config.md`：模型配置新增的能力字段。

3. 更新 `docs/modules/core.md`：LLM 构造路径变化。

4. **删除死代码** `core/config.py` 的 `LLMConfig`（`:20-28`）。先确认真的无人使用：

```powershell
Select-String -Path *.py,core\*.py,config\*.py,execution\*.py,planning\*.py,tools\*.py,tests\*.py -Pattern "from.*core\.config import|core\.config\." -Recurse
```

无输出才删。有输出就**不要删**，记进主计划 §10.4 待办池。

5. 更新主计划 `2026-07-31-EXECUTION-PLAN.md` §3.2 的 Phase 表，把 Phase A 标为完成。

**完成判据**
- [ ] `docs/modules/providers.md` 存在，按它能独立加出一个新 provider
- [ ] 三份既有模块文档已更新
- [ ] `core/config.py` 死代码已删或已记入待办池（二选一，说明理由）

---

## §4 Phase A 出口检查

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=600
python -m pytest tests/test_providers -q
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
Select-String -Path core\agent_v2.py -Pattern 'encoding_for_model\("gpt-4o"\)'
Select-String -Path core\agent_v2.py,utils\streaming.py -Pattern "256000"
```

**Phase A 完成的定义：**
- 前 4 条命令全绿，evals 零回归
- 后 2 条无输出（或只剩注释/兜底常量）
- 至少 3 个模型跑出了 eval 基线矩阵
- `docs/modules/providers.md` 可独立指导加新 provider

---

## §5 扩展手册：加一个新 Provider

> Phase A 之后，接一个新模型族的标准流程。**这一节是长期使用的，不是一次性任务。**

**第 1 步 · 查资料**（交给 Grok）

```
查 <厂商> 官方 API 文档，回答：
1. 各主力模型的 context window
2. 是否兼容 OpenAI /chat/completions？兼容端点下 tools 可用吗？
3. prompt 缓存怎么开？usage 里命中数字段名？
4. 是否有 reasoning/thinking 输出？字段名？在 delta 还是 message 上？
5. 是否拒绝 temperature / top_p 等采样参数？
6. 官方 tokenizer，有无 tiktoken 兼容 encoding？
每条给文档原文和 URL。
```

**第 2 步 · 写 provider**

复制 `core/providers/deepseek.py` 作模板，改四个地方：`name`、`matches()`、`capabilities()`、docstring 里的文档 URL。

**第 3 步 · 注册**

`core/providers/__init__.py` 的 `_PROVIDERS` 列表。**顺序 = 优先级，越具体越靠前。**

**第 4 步 · 写测试**

复制 `tests/test_providers/test_deepseek_provider.py`，至少覆盖：
- `matches()` 的正例（URL 匹配、模型名匹配）和反例
- capabilities 的关键字段不等于全局默认值
- 用户显式覆盖能赢过 provider 默认值
- usage 字段提取

**第 5 步 · 验证不误伤兜底**

```powershell
python -m pytest tests/test_providers/test_registry.py -q
```

新 provider 的 `matches()` 如果写得太宽，会把别的模型抢走。这个测试文件专门守这条。

**第 6 步 · 跑评测**

```powershell
python -m evals.cli run --backend agent --models <新模型id> --save-baseline
```

**第 7 步 · 更新文档**

`docs/modules/providers.md` 的支持列表。

---

## §6 与后续 Phase 的接口

Phase A 为后面两个 Phase 预留了这些接缝，**实现时不要破坏它们**：

| 预留 | 给谁用 | 约束 |
|---|---|---|
| `ModelCapabilities.supports_vision` | Phase C 多模态 | Phase A 只占字段不实现，Phase C 填逻辑 |
| Provider 无状态单例（约束 DC2） | Phase B 多 Agent | 多个 Agent 会并发调用同一个 provider 实例，**不要在 provider 里存任何 per-request 状态** |
| `ModelCapabilities.prompt_variant` | Phase B 角色化 Agent | 不同角色的 Agent 可能用不同模型，变体机制要能按 agent 解析 |
| `AgentState._capabilities` | Phase B | 多 Agent 下每个 agent 的 capabilities 不同，state 注入要按 agent 隔离 |
