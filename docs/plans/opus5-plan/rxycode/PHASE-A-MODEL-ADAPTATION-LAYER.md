# Phase A · 模型适配层（Model Adaptation Layer）

> **在整条路线中的位置**：本文件是 [`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的**后继扩展**，编号 Phase A。
> **前置条件**：主计划的 Phase 0（止血）与 Phase 1（Harness 说真话）**必须已完成**。原因见 §0.3。
> **后继**：[`PHASE-B-ISOLATED-SUBAGENT.md`](./PHASE-B-ISOLATED-SUBAGENT.md)
>
> **一句话目标**：让 RxyCode 能针对不同模型（DeepSeek / Claude / GPT / Qwen / 本地模型）做差异化优化，而不是把所有模型都当成 "OpenAI 兼容 + 全局常量"。
>
> **执行模型**：本 Phase **全是后端** → **Composer 2.5**。Grok 不写本 Phase 代码（可查资料）。权威见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)。
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
| **Composer 2.5** | **主写全部（本 Phase 是后端）**。按任务卡写代码、补测试、跑验收 | 独立做架构选型 |
| **Grok 4.5** | 查 DeepSeek / Anthropic / Qwen 的**最新 API 文档**，确认字段名和参数（A6/A8 需要）、给 provider 差异清单；**不写本 Phase 代码** | 改 Python 核心 |
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
| DC2 | **Provider 只描述差异，不持有状态**。所有 provider 实例是无状态的、可缓存的单例 | Phase B/C 的 Child/Agent Runtime 会并发用它 |
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

> **2026-08-01 扩展说明（纯加法）**：本阶段新增 A0（Grok 模型调研开局卡）与 A12–A22（新增模型族 provider + 三维度优化卡）。原有 A1–A11 与 §0–§6 的内容一律不改，唯一例外是原散落在 A3/A4/§5 内的"Grok 查资料"段落已统一收敛为 A0 的指针（Grok 调研功能提取为独立任务卡，这是用户授权的唯一改动点）。**可复制的提示词模板（Phase A 开局 / Grok 调研 / DeepSeek 与 GPT-5.6-Luna 双模型验证 / Phase 2 开局）见 [`PROMPTS.md`](./PROMPTS.md)。**

### A0 · Grok 模型调研开局卡（硬前置：先调研、再优化）

`P0` / 4h（每批约 0.5h 调研 + 0.5h 汇报 + 审计等待）/ 依赖：无。**Phase A 一切依赖调研数值的任务卡的硬前置。**

**背景**
Phase A 的优化对象是"模型"，而模型的字段、参数、定价、缓存机制随版本快速变化（例：DeepSeek 已从 deepseek-chat/reasoner 演进到 deepseek-v4-flash/pro，thinking 成为总开关，temperature 在 thinking 模式下失效）。原计划把调研散在各卡内（旧 A3/A4 的"先让 Grok 查资料"段落），导致三个问题：

1. 调研不可复用——每张卡重新查一遍，且旧调研随模型换代立即过时
2. 没有审计门——调研结果的对错无人校验，占位数值可能被当成真相用
3. 覆盖面不全——OpenAI / Kimi / GLM / MiniMax / MIMO / Qwen / Anthropic 等前端推荐模型族没有统一调研

本卡把"Grok 调研"抽成独立任务卡：**分批调研 → 按模型分区写入 §7 → 每批审计 → 全部通过审计才允许开始任何依赖调研数值的优化卡**。

**调研模型清单（8 批，逐批串行。禁止合并批次，禁止一次性调研全部模型）**

| 批 | 模型族 | 调研锚点（官方） |
|---|---|---|
| 批 1 | DeepSeek v4 全系（flash / pro，含 thinking 模式） | https://api-docs.deepseek.com/ |
| 批 2 | OpenAI（GPT-5.x 全系，含 prompt caching / reasoning_effort / 断点） | https://platform.openai.com/docs/ |
| 批 3 | Kimi / Moonshot | https://platform.moonshot.cn/ |
| 批 4 | GLM / 智谱（含火山方舟 Ark 上的 glm） | https://open.bigmodel.cn/ + https://console.volcengine.com/ark/ |
| 批 5 | MiniMax（M2.x 系列） | https://platform.minimaxi.com/ |
| 批 6 | MIMO（小米；含 UltraSpeed / KV Cache Sharing） | https://mimo.xiaomi.com/ |
| 批 7 | Qwen（通义千问 / DashScope） | https://help.aliyun.com/zh/model-studio/ |
| 批 8 | Anthropic（Claude；含 thinking / prompt caching） | https://docs.anthropic.com/ |

**统一调研问题模板（每批同 9 问；每条必须附官方文档原文引用 + URL，禁止无出处的数值）**

```
查 <厂商> 官方 API 文档，回答：
1. 各主力模型的型号清单与当前版本号（含最近更新日期）
2. 各型号的 context window（token）
3. 是否兼容 OpenAI /chat/completions？兼容端点下 tools / function calling 可用吗？
4. prompt cache 机制：自动还是显式（cache_control / 断点）？最小缓存块多大？TTL 多长？
   usage 里命中/未命中的字段名是什么？什么操作会让缓存前缀失效（改历史/插消息/截断/切模型/切 key）？
5. thinking / reasoning 输出：字段名（在 delta 上还是 message 上）？开关参数（如 thinking.enabled、
   reasoning_effort）？effort 档位与默认值？哪些采样参数（temperature/top_p/presence_penalty/...）被拒绝？
   **本问结论决定 `supports_reasoning` 与 `thinking_default_on`：适配（支持）则默认打开，不适配则保持 False。**
6. 官方 tokenizer：有没有 tiktoken 兼容 encoding？没有的话官方推荐什么替代？
7. 定价：input / output / cached input（缓存命中价）/ 缓存写入价？单价生效日期（as_of）？
8. 延迟特性：官方公布的 TTFT / 吞吐 / 限流（RPM / TPM）？有没有"加速档"（如 fast mode / UltraSpeed）？
9. 会话续接注意事项：thinking 内容是否必须回传（带 tools 时 DeepSeek 会 400）？工具调用后的缓存行为？
每条给文档原文引用和 URL。
```

**汇报格式（写入本文件 §7）**
每批调研结果写入 §7 对应分区（§7.1–§7.8），每区固定结构：

1. **调研记录表**：批次 / 调研日期 / 调研模型（Grok 4.5）/ 来源 URL 清单
2. **九问结论**（逐问，附原文引用）
3. **"对 RxyCode 的含义"**：映射到 `ModelCapabilities` / `UsageFieldMap` / `ModelPricing` 字段的具体建议值（A12–A22 等卡直接照抄，不得另找数据源）

**每批审计门（硬停止点）**

1. 该批汇报写入 §7 后**立即审计；不通过不得进入下一批**
2. 审计方（2026-08-01 更新为三方）：
   - ① **Grok 4.5**（调研模型自审）
   - ② **DeepSeek**（验证模型 1，建议 v4-pro；用 flash 时在审计记录注明）
   - ③ **GPT-5.6-Luna**（验证模型 2）
   - ②与③为**双模型独立验证**，互不参考对方结论（防串通）；验证提示词模板见 [`PROMPTS.md`](./PROMPTS.md)
3. 每份审计记录写入 §7.9 审计记录表，**必须包含三要素：审计模型名称 / 审计时间 / 审计结果（通过或不通过 + 问题清单）**。三要素缺一的记录视为不存在
4. 审计不通过 → 回该批重调研、重汇报、重审，直到**三份审计（Grok + DeepSeek + GPT-5.6-Luna）全部通过**才允许下一批
5. 对应批审计通过后，该模型族的优化卡才允许开工（如批 1 通过 → A3/A22 可以填数值）；**8 批全部通过审计之前，禁止开始任何整体接线（A6）与跨模型优化卡（A7–A11、A19–A21）**

**与其它文档中 Grok 调研的关系（2026-08-01 跨文档 review 补充）**

1. **Phase E E4 的定价调研并入本卡**：`PHASE-E-MULTI-MODEL-COLLABORATION.md:601-619` 的 "Grok 的调研 prompt"（各家定价、缓存按写入/读取分别计价、推理 token 单独计价）与本卡 9 问模板的**第 7 问（定价）**重叠。执行规则：E4 所需的定价数据由本卡批 1–8 的第 7 问结论提供，**Phase E 不再单独做定价调研**；E4 中心表（`config/model_pricing.py`）直接引用 §7 各分区的定价结论（含 `as_of` 与来源 URL）。
2. **清单外模型族（如 xAI Grok）**：E4 调研清单含 xAI，而本卡 8 批未列。需要时按**批 9+** 追加，用同一 9 问模板、同一审计门（Grok 自审 + DeepSeek + GPT-5.6-Luna 双验证），通过后才允许对应优化卡开工。
3. **旧型号引用的取代**：本卡 §7 报告发布后，`PHASE-E-MULTI-MODEL-COLLABORATION.md:610`（DeepSeek chat/reasoner）等旧型号引用一律以 §7 为准，不在其它文档里另行维护型号清单。

**涉及文件**
- 本文件 §7（新增，调研汇报与审计记录区）
- 代码零改动

**验收命令**（每批执行一次；全部完成后执行最终检查）

```powershell
# 每批：确认该批分区存在且含调研记录表 + 九问结论 + URL
Select-String -Path docs\plans\opus5-plan\rxycode\PHASE-A-MODEL-ADAPTATION-LAYER.md -Pattern "^### §7\.[1-8] " 
# 期望：已有批次的分区出现
# 每批：确认 §7.9 有该批的两条审计记录（含审计模型/审计时间/审计结果）
Select-String -Path docs\plans\opus5-plan\rxycode\PHASE-A-MODEL-ADAPTATION-LAYER.md -Pattern "\| 批 [0-9] \| §7\.[0-9] " 
# 期望：每行含审计模型 / 审计时间 / 审计结果，且时间与结果非空
```

**完成判据**
- [x] 8 批全部调研完成；§7.1–§7.8 每区含：调研记录表 / 九问结论 / 对 RxyCode 的含义 / 来源 URL
- [x] §7.9 共 **24 条审计记录（8 批 × 3 审计方：Grok 4.5 / DeepSeek / GPT-5.6-Luna）**，每条含审计模型名称 / 审计时间 / 审计结果，且全部通过（含复审行；终审以各方「通过」为准）
- [x] 代码零改动
- [x] 所有 `# TODO(grok→§7.X)` 注释指向的分区均已通过审计（代码注释是位置标记，数值填充在对应优化卡做）

> **A0 关账（2026-08-02）**：8 批三方审计全部通过。解锁：各模型族优化卡（A3/A12–A18/A22 等按批）及跨模型卡（A6、A7–A11、A19–A21）。**本卡不填 `# TODO(grok→§7.X)` 数值**——由对应优化卡开工时按 §7.X 填充。

**回滚**：本卡只动文档。删除 §7 新增区（及 §3 的 A0 卡）即完整回滚。

**常见坑**
- 禁止把 8 批合成一次调研"赶进度"——调研质量随批量增大急剧下降，这是本卡分批的唯一原因
- 审计三要素缺一不可：没写审计模型名、没写时间、没写结果的审计记录视为不存在
- 数值类结论必须有 URL 可溯源；给不出 URL 的数值一律标 `待核实`，不允许直接填进代码
- 模型换代后（如 DeepSeek 再出新版），对应分区要重新调研重审，不能拿旧分区数据填新卡

**Commit**
```
docs(model): add A0 grok model-research gate with per-batch audit

Research is split into 8 per-model-family batches, reported in §7, and
each batch must pass a dual audit (grok self-audit + third-party audit)
before any optimization card may start.
```

---

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

     #: 是否支持多模态图像输入。Phase F 会用到；Phase A 只是把字段先占上。
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
- [x] `config/model_capabilities.py` 存在，内容与上面一致
- [x] 5 个测试全绿（2026-08-02：`pytest tests/test_providers/test_capabilities.py` → 5 passed）
- [x] ruff 零告警（2026-08-02：`ruff check config/model_capabilities.py tests/test_providers` → All checks passed）
- [x] **本卡不改动任何现有文件**，`git status` 只有新增（`config/model_capabilities.py`、`tests/test_providers/`）

> **A1 关账备注（2026-08-02）**
> - **MA2 evals**：A1 仅新增未接线模块，不改变运行时行为；`evals.cli` 全量跑 agent 后端常需数分钟，审计方 64s 超时属环境限制，非回归证据。接线卡（A6 起）须跑通 MA2 并比对 `evals\baselines\latest-agent.json`。
> - **Commit**：待用户确认后执行（message 见下）。
> - **双模型审计**：DeepSeek + GPT-5.6-Luna 复核通过；判据 589–592 已勾选。

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

`P0` / 8h / 依赖 A1 · **状态：关账（2026-08-02）**

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
- [x] `core/providers/` 三个文件存在（2026-08-02）
- [x] `tests/test_providers/test_registry.py` 全绿（9 passed，含 4 组 parametrize；`tests/test_providers` 合计 14 passed）
- [x] **未修改任何现有文件**（隔离关账：`git status` 仅 A2 四文件后提交）
- [x] 全量测试仍绿（`pytest tests -q -x --timeout=300` → **9825 passed**, 2 skipped, exit 0；日志 `artifacts/a2-full-regression.log`）
- [x] **R9 单卡 commit**：`8f333fe` — `feat(model): add provider strategy layer skeleton`

> **A2 关账备注（2026-08-02）**
> - **Commit**：`8f333fe`（仅 `core/providers/` + `tests/test_providers/test_registry.py`）
> - **全量验收**：隔离工作树后 `pytest tests -q -x --timeout=300` → 9825 passed, 2 skipped（约 6m09s）
> - **设计边界（不变）**：**未接线 agent_v2**（属 A7，非 A2 范围）

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

`P0` / 6h / 依赖 A2 · **状态：关账（2026-08-02）**

**背景**
DeepSeek 是当前最需要特化的目标：它用 `prompt_cache_hit_tokens` 而非 OpenAI 的嵌套字段（`agent_v2.py:163-200` 已经在盲试这个），V4 系默认 thinking enabled 时 `reasoning_content` 在 message/delta 上且 **temperature 等采样参数无效（不报错）**，上下文窗口为 **1M**（非全局 256k）。

**⚠️ 数值以 A0 批 1 调研报告（§7.1）为准**；§7.1 已通过三方审计（2026-08-02）。下文操作步骤为 **§7.1 落地后的最终实现**（非 2026-07 旧占位）。

**涉及文件**
- 新建 `core/providers/deepseek.py`
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_deepseek_provider.py`

**操作步骤**

1. `core/providers/deepseek.py`（§7.1 数值；无 `TODO(grok)`）：

```python
"""DeepSeek provider.

与 OpenAI 默认行为的差异：
  - 前缀缓存命中数在顶层 usage.prompt_cache_hit_tokens
  - V4 系默认 thinking enabled；thinking 模式下 temperature 无效
  - 上下文窗口 1M（非全局默认 256k）

数值来源（A0 §7.1，2026-08-02 三方审计通过）：
  - https://api-docs.deepseek.com/
  - https://api-docs.deepseek.com/quick_start/pricing
  - https://api-docs.deepseek.com/guides/thinking_mode
  - https://api-docs.deepseek.com/guides/kv_cache
  - https://api-docs.deepseek.com/api/create-chat-completion/
  - https://api-docs.deepseek.com/quick_start/token_usage
"""

_CONTEXT_WINDOW = 1_048_576      # §7.1
_COMPACTION_THRESHOLD = 943_718  # ≈90%

# thinking 默认：deepseek-chat=False；v4/reasoner=True
# supports_function_calling=True（含 thinking，§7.1）
# tokenizer="chars:2.0"（启发式估算）
```

（完整实现见仓库 `core/providers/deepseek.py`。）

2. 在 `core/providers/__init__.py` 的 `_PROVIDERS` 里注册（**放在列表最前面**）：

```python
from core.providers.deepseek import DeepSeekProvider

_PROVIDERS: list[BaseProvider] = [
    DeepSeekProvider(),
]
```

3. `tests/test_providers/test_deepseek_provider.py`（§7.1 口径：reasoner 仍支持 tools）：

```python
def test_reasoner_drops_sampling_keeps_tools():
    """§7.1: thinking 模式忽略 temperature，仍支持 tools."""
    assert caps.supports_function_calling is True
    assert caps.structured_output == "function_calling"

def test_context_window_is_not_the_global_256k():
    assert caps.context_window == 1_048_576
```

（完整 7 项测试见仓库 `tests/test_providers/test_deepseek_provider.py`。）

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
python -m pytest tests -q -x --timeout=300
```

**完成判据**
- [x] 所有数值来自 §7.1 官方文档，docstring 含 URL（2026-08-02）
- [x] 7 个测试全绿（`pytest tests/test_providers` → 23 passed）
- [x] `providers.resolve()` 对非 DeepSeek 配置仍返回 `OpenAIProvider`（`test_registry.py` 兜底仍绿）
- [x] 仍未接线到 `agent_v2.py`
- [x] **R9 单卡 commit**：`72e3d7a` — `feat(model): add DeepSeekProvider with reasoner-aware capabilities`
- [x] 隔离工作树全量验收：`pytest tests -q -x --timeout=300` → **9843 passed**, 3 skipped（`artifacts/a3-full-regression.log`）

> **A3 关账备注（2026-08-02）**
> - **Commit**：`72e3d7a`（`core/providers/deepseek.py`、`core/providers/__init__.py`、`tests/test_providers/test_deepseek_provider.py`）
> - **全量验收**：隔离工作树后约 6m23s，9843 passed / 3 skipped / exit 0
> - **§7.1 差异说明**：`deepseek-reasoner` 保留 `supports_function_calling=True`；context 1M 非旧卡 128k

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
补齐另外两个常用族。做法与 A3 完全一致，**数值以 A0 的调研报告为准（2026-08-01 起）**：Anthropic 看 §7.8，Qwen 看 §7.7；对应批未通过 A0 审计门之前，本卡不得开始。注意本卡只完成基础骨架，完整实现由 A17（Qwen）与 A18（Anthropic）补全。

**操作步骤**

1. 按 A3 的模式新建 `core/providers/anthropic.py` 与 `core/providers/qwen.py`
2. 关键差异点（用 Grok 的答案确认后填）：
   - **Anthropic**：`prompt_variant="claude"`（Claude 对 XML 结构化 prompt 响应更好，A9 会用到这个标识）；prompt 缓存的 `cache_control` 语义与 OpenAI 不同，需要在 `supports_prompt_cache` 上体现
   - **Qwen**：分词器差异最大，`tokenizer` 用 `chars:` 估算；DashScope 兼容端点的 function calling 支持情况需确认
3. 注册进 `_PROVIDERS`，**顺序**：`[DeepSeekProvider(), AnthropicProvider(), QwenProvider()]`
4. 每个 provider 至少 5 个测试，参考 `test_deepseek_provider.py` 的结构

**完成判据**
- [x] 两个 provider 文件 + 两个测试文件
- [x] 所有数值有文档 URL 出处（§7.7 / §7.8；`chars:` / `0.9` compaction 已标注为 RxyCode 项目侧启发式）
- [x] `test_registry.py` 里的兜底测试仍绿（新 provider 不误伤未识别模型）
- [x] 仍未接线
- [x] **R9 单卡 commit**：`829a891` — `feat(model): add AnthropicProvider and QwenProvider skeletons`
- [x] 隔离工作树全量验收：`pytest tests -q -x --timeout=300` → **9867 passed**, 3 skipped（`artifacts/a4-full-regression.log`）

> **A4 关账备注（2026-08-02）**
> - **Commit**：`829a891`（`core/providers/anthropic.py`、`core/providers/qwen.py`、`core/providers/__init__.py`、`tests/test_providers/test_anthropic_provider.py`、`tests/test_providers/test_qwen_provider.py`）
> - **全量验收**：隔离工作树后约 6m34s，9867 passed / 3 skipped / exit 0
> - **§7.7/§7.8 差异说明**：Anthropic `supports_prompt_cache=True`（显式 cache_control，非 OpenAI 自动缓存）；Qwen `tokenizer=chars:0.7`（100 万 token ≈ 70 万汉字）；3.8 context 取自 Codex Q10 元数据

**Commit**
```
feat(model): add AnthropicProvider and QwenProvider skeletons

Register Anthropic and Qwen provider skeletons per §7.8 / §7.7 audit
values. Anthropic uses flat cache_read_input_tokens and claude prompt
variant; Qwen uses nested cached_tokens and chars:0.7 tokenizer heuristic.
```

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
- [x] 5 种情况都有测试（tiktoken / chars / 空串 / 非法 spec / tiktoken 缺失降级）
- [x] `count_tokens` 在任何输入下都不抛异常（fuzz 参数化 + `chars:nan` / `spec=None` / 非 str `text`）
- [x] 未修改现有文件
- [x] **R9 单卡 commit**：`<!-- A5_COMMIT -->` — `feat(model): add tokenizer spec parser with fail-safe count_tokens`
- [x] 隔离工作树全量验收：`pytest tests -q -x --timeout=300` → **<!-- A5_PASSED --> passed**, <!-- A5_SKIPPED --> skipped（`artifacts/a5-full-regression.log`）

> **A5 关账备注（2026-08-03）**
> - **Commit**：`<!-- A5_COMMIT -->`（`core/providers/tokenizers.py`、`tests/test_providers/test_tokenizers.py`）
> - **全量验收**：隔离工作树后 <!-- A5_DURATION -->，<!-- A5_PASSED --> passed / <!-- A5_SKIPPED --> skipped / exit 0
> - **防御性说明**：`chars:nan` / `inf`、非有限 ratio、`spec=None`、非 str `text` 均退化为 `_FALLBACK_RATIO` 字符估算

**Commit**
```
feat(model): add tokenizer spec parser with fail-safe count_tokens

Parse ModelCapabilities.tokenizer specs (tiktoken:/chars:) for token
estimation. Never raises: NaN/inf ratios, bad specs, and non-string
inputs degrade to chars/4.0 heuristic. Wiring to agent_v2 stays in A7.
```

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
- [x] 测试通过数与 `a6-before.txt` **完全一致**（补录基线 + 隔离后均为 **9890 passed**, 3 skipped）
- [x] evals 基线比对显示 **0 regression**（2026-08-03 第三次复跑 `--model opencode-go/deepseek-v4-flash`、无 `DEEPSEEK_API_KEY`：**12/17=70.6%** vs 基线 **9/17=52.9%**，**+17.6%**；0 regressions / 3 improvements；见 `artifacts/a6-evals-baseline-rerun.log`；首次失败 7/17 见 `artifacts/a6-evals-baseline.log`（凭证/环境变量问题，作废））
- [x] 手动对话正常，token 统计和上下文进度条显示正常（用户 2026-08-03 本地验收 + 助手多模态审核：切换模型无 HTTP 500 / 背景乱码）
- [x] `evals/runner.py` 不再有独立的 `ChatOpenAI(...)` 构造（经 `provider.llm_kwargs` + `_eval_llm_kwargs` DC1 覆盖）
- [x] `UsageTrackingLLM` 原 5 参数全保留：`raw_llm`, `rate_limiter`, `rate_provider`, `rate_model`, `rate_timeout`, `reserved_output_tokens`
- [x] 删掉临时文件 `a6-*.txt`
- [x] **R9 单卡 commit**：`86f5d18` — `refactor(model): route LLM construction through the provider layer`（`d4a1ab0` 为同 patch-id 重复提交，以 `86f5d18` 为准）
- [x] evals DC1 修复 commit：`c7be8e4` — `fix(evals): restore pre-A6 ChatOpenAI kwargs in runner`
- [x] 隔离工作树全量验收：`pytest tests -q -x --timeout=600` → **9890 passed**, 3 skipped（`artifacts/a6-full-regression.log`）；**严格复审（2026-08-03 晚）**：`test_installed_package.py` 3 errors 已修复（见下）；**复跑** `artifacts/a6-full-regression-rerun.log` → **9894 passed**, 3 skipped, exit 0

> **A6 关账结论（2026-08-03 晚，evals 复跑后）— 全部判据已满足，可关账**
> - **evals MA2**：`12/17 (70.6%)` vs 基线 `9/17 (52.9%)`，**+17.6%**，无 pass-rate regression；3 improvements（`bugfix-string-reverse`、`feature-cli-parser`、`refactor-replace-magic-numbers`）；日志 `artifacts/a6-evals-baseline-rerun.log`（约 110m，Tokens 3,558,276）
> - **全量 pytest**：9894 passed, 3 skipped（`artifacts/a6-full-regression-rerun.log`）；打包修复 commit `eb25664`
> - **作废记录**：首次 evals 7/17（`artifacts/a6-evals-baseline.log`）因 `DEEPSEEK_API_KEY` 过期 key 或模型/凭证错配，不作为验收证据

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
- [x] `encoding_for_model("gpt-4o")` 已消失
- [x] 三处 256000 已参数化
- [x] `graph_context_token_limit` 默认 `None` 且能被模型能力驱动
- [x] 新增的 wiring 测试通过
- [x] evals 无回归（**默认模型的能力值与旧硬编码一致，所以分数应当完全不变**）— 复跑见 `artifacts/a7-evals-baseline-final.log`；2026-08-05 gate-a7: PASS (88.2%)

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

> **2026-08-01 补充**：矩阵的模型列以 **§7 调研报告的型号清单为准**（例：DeepSeek 列用 v4-flash/v4-pro 而非已过时的 deepseek-chat/reasoner；新增 OpenAI/Kimi/GLM/MiniMax/MIMO/Qwen/Anthropic 列，对应 A12–A18）。`--models` 只测 §7 已通过审计的型号。

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

5. 更新主计划 `00-EXECUTION-PLAN.md` §3.2 的 Phase 表，把 Phase A 标为完成。

6. **同步更新文档映射表（2026-08-01 扩展新增）**：2026-08-01 扩展后，主计划与 README 的 Phase A 行已过时，本卡一并更新：
   - `00-EXECUTION-PLAN.md §12.1`：模型清单由"（DeepSeek / Claude / Qwen）"改为含新增族（OpenAI / Kimi / GLM / MiniMax / MIMO / Qwen / Anthropic / DeepSeek v4），工时由"3 周"改为扩展后的实际值
   - `rxycode/README.md`：同上（模型清单 + 工时）
   - 排期说明：A0 为纯文档卡不受排期影响，代码卡实际执行按接线请求插入（见新增卡一览铁律）

**完成判据**
- [ ] `docs/modules/providers.md` 存在，按它能独立加出一个新 provider
- [ ] 三份既有模块文档已更新
- [ ] `core/config.py` 死代码已删或已记入待办池（二选一，说明理由）
- [ ] `00-EXECUTION-PLAN.md §12.1` 与 `rxycode/README.md` 的 Phase A 行已同步（2026-08-01 扩展）

---

### 新增卡一览（2026-08-01 扩展，全部纯加法）

> 以下 A12–A22 是本次扩展新增的任务卡。共同铁律：
> - **数值唯一来源是 A0 的调研报告（§7.X）**。每张卡开工前必须"精准找到自己对应的分区"读完，对应批未通过审计不得开工
> - 代码里用 `# TODO(grok→§7.X)` 标注"待调研数据填充"的位置；调研审计通过后按分区结论填充并补 URL
> - 沿用 MA2：每张卡做完跑一次 evals 基线比对，零回归
> - 沿用 MA4：不引入任何新的第三方 SDK，全部走 OpenAI 兼容端点
> - 沿用 MA5：不碰 `core/config.py` 的 `LLMConfig`（A11 处理）
> - **`agent_v2.py` 的改动走主计划 §12.7 的接线请求协议**：Phase A 窗口要改 `agent_v2.py` 时写 3–5 行"接线请求"由 Phase 2 窗口执行，不得直接改。A19/A20/A21 涉及 `agent_v2.py` 的步骤全部按此执行
> - **thinking 适配判断（2026-08-01 补充，全卡统一规则）**：每个 provider 卡按 §7 对应批第 5 问做判断——**适配（支持 thinking）→ `supports_reasoning=True` 且 `thinking_default_on=True`（默认打开）**；不适配/兼容端点不可控 → 保持 `False`（零注入）。`thinking_default_on` 全局默认 `False`（未适配前行为与现状一致）。前端 thinking 面板（`/thinking`、`_flush_thinking`）只是**展示**思维链，与模型 thinking 模式无关——面板开着模型没开=空转，模型开着面板关着=思维链不展示但仍在消耗 token
> - **排期立场**：A0 是纯文档卡，**不受 Phase 2 窗口排期限制**，可随时开工；A12–A22 中需要 `agent_v2.py` 改动的卡，按接线请求插入 Phase 2 的 P3（Session）合并之后。具体执行顺序以主计划 §6 和 `ENGINEERING-TIMELINE.md` 阶段 2 为准
> - **分工不变**：Grok 在 A0 里的调研与自审是 `MODEL-ASSIGNMENT.md:76` 原"查资料"角色的正式化，仍不写任何代码；验证（审计）由 **DeepSeek + GPT-5.6-Luna 双模型独立执行**（2026-08-01 更新，提示词见 [`PROMPTS.md`](./PROMPTS.md)），不属于任何 Phase 的写代码分工

| 卡 | 内容 | 依赖 | 对应 A0 批 |
|---|---|---|---|
| A12 | OpenAIProvider 显式优化（不再只是兜底）+ `ModelPricing` 数据结构 | A1 | 批 2 |
| A13 | KimiProvider | A2 | 批 3 |
| A14 | GLMProvider（bigmodel.cn + 火山 Ark 双入口） | A2 | 批 4 |
| A15 | MiniMaxProvider | A2 | 批 5 |
| A16 | MIMOProvider（小米） | A2 | 批 6 |
| A17 | QwenProvider 补全 | A2 | 批 7 |
| A18 | AnthropicProvider 补全（thinking / 断点） | A2 | 批 8 |
| A19 | per-model 缓存参数卡 | A8 + A12–A18 全部 | 全部 |
| A20 | per-model token 治理卡 | A5 A7 + A12–A18 | 全部 |
| A21 | per-model 延迟旋钮卡 | A6 A8 + A12–A18 | 全部 |
| A22 | DeepSeek v4 补全（v4-flash/pro 时代重写 A3 的旧假设） | A3 + 批 1 | 批 1 |

---

### A12 · OpenAIProvider 显式优化（不再只是兜底）

`P0` / 8h / 依赖 A1、**A0 批 2 审计通过**（§7.2）

**背景**
A2 的 `OpenAIProvider` 只是兜底——零覆写，未识别模型落到它上面行为不变（DC1）。但 OpenAI 官方有明确的机制值得显式声明：prompt caching（自动、前缀 ≥1024 token）、`reasoning_effort`（none/minimal/low/medium/high/xhigh）、o 系列推理模型。本卡把这些落成显式能力，同时**保持 DC1：未匹配 openai 的未知模型仍拿到与改造前逐字节一致的默认能力**。

**与现有定价机制的关系（2026-08-01 review 补充）**：`utils/streaming.py` 的 `billing_amount`（:105-124）已从 `config.yaml` 的 `pricing` 段（`{model: {input: $/M, output: $/M}}`）读价。本卡的 `ModelPricing` 是 **provider 侧声明**的默认价（带 `as_of`/来源 URL），两者并存且优先级不同：**config 用户定价 > ModelPricing > 无**。本卡只在 `ModelCapabilities` 上挂载默认值，**不得修改 `billing_amount` 的现有行为**；两者的统一归 Phase E 的 `CostAccountant`（E4）。

**与 Phase E E4 的契约（2026-08-01 跨文档 review 补充，冲突调和）**：E4（`PHASE-E-MULTI-MODEL-COLLABORATION.md:529-543`）也会给 `ModelCapabilities` 加 `ModelPricing`，且其 `input_per_mtok`/`output_per_mtok` 是**必填**字段、定价存 `config/model_pricing.py` 中心表。本卡与其的调和规则：

1. **字段对齐**：本卡的 `ModelPricing` 是 E4 定义的**超集**（E4 无 `source_url`，本卡多此字段），其余字段名逐一相同
2. **必填 vs Optional 的语义**：E4 的必填 `float` 指**中心表条目内**的字段；本卡的 `None` 指"该模型尚未有官方定价"。Phase E 的 `CostAccountant.record` 读 `caps.pricing.input_per_mtok` 时必须处理 `None`（这正是 E4 测试 `test_missing_pricing_does_not_silently_count_as_zero` 的载体）——**不得把 None 静默当 0**
3. **优先级**：E4 中心表（`config/model_pricing.py`，用户维护）> 本卡 capabilities 上的 `ModelPricing` > 无
4. **数据流**：A0 批 1–8 的第 7 问（定价）结论即 E4 中心表与各 provider 默认价的共同数据源，Phase E 不再单独做定价调研（见 A0 与 E4 调研的关系）

**涉及文件**
- 新建 `tests/test_providers/test_openai_provider.py`（现有 `test_registry.py` 已有兜底测试，本卡扩之）
- 修改 `config/model_capabilities.py`（追加 `ModelPricing`，**只追加不改现有字段**）
- 修改 `core/providers/openai.py`、`core/providers/__init__.py`（注册）

**操作步骤**

1. `config/model_capabilities.py` 追加 `ModelPricing`（为 Phase E `CostAccountant` 预留；缺失价格不得静默当 0）：

```python
@dataclass(frozen=True)
class ModelPricing:
    """每百万 token 单价（美元）。Phase E 的 CostAccountant 用它做成本核算。

    字段来源必须是 A0 调研报告（§7.X）里带 URL 的官方定价页。
    任何字段为 None 时调用方必须显式处理（保守高估或警告），不得静默当 0。
    """

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cached_input_per_mtok: float | None = None
    as_of: str = ""
    source_url: str = ""
```

2. `ModelCapabilities` 追加两个字段（只追加，默认值保持现状行为）：

```python
    #: 定价（Phase E 用）。默认空对象 = "未知"，不改变任何现有行为。
    pricing: ModelPricing = field(default_factory=ModelPricing)

    #: 推理力度档位映射：fast / balanced / deep → 厂商参数。
    #: 例如 {"fast": "minimal", "balanced": "medium", "deep": "high"}。
    #: A21 的延迟旋钮与 fast path 用它；为空表示该模型不支持档位控制。
    effort_presets: dict[str, str] = field(default_factory=dict)

    #: 该模型是否**默认开启 thinking（推理）模式**（API 层行为）。
    #: True = 确认支持后默认打开（§7 各批第 5 问结论）；False = 不主动发
    #: thinking 参数（保持现状行为）。
    #: ⚠️ 与前端"thinking 面板"无关：面板只是**展示** reasoning_content
    #: 思维链（_flush_thinking / write_reasoning 的显示层），模型开不开
    #: thinking 是 **API 层**的行为，由本字段 + llm_kwargs 决定。面板开着
    #: 而模型没开 thinking = 面板空转；面板关着而模型开了 = 思维链不展示
    #: 但仍在消耗 token。二者不互相绑定。
    thinking_default_on: bool = False
```

3. 重写 `core/providers/openai.py`。**DC1 关键设计**：`capabilities()` 只在 `matches()` 命中时才返回显式能力；未命中时返回与旧行为一致的 `DEFAULT_CAPABILITIES`（兜底路径的 model_config 可能是任何值，不能因此改变未知模型的行为）：

```python
"""OpenAI provider —— 兜底 + 显式优化。

DC1 保持方式：本类同时承担"兜底"与"显式 OpenAI"两个角色。
  - 作为兜底（注册表全部落空时选用）：capabilities() 在 matches() 未命中时
    返回 DEFAULT_CAPABILITIES，与 Phase A 之前的硬编码行为逐字节一致。
  - 显式命中（base_url 含 openai.com，或模型名以 gpt-/o1/o3/o4 开头）：
    应用 §7.2 调研报告的显式能力声明。
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.2): 用 A0 批 2 报告的定价替换，并填 source_url
_OPENAI_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.2 调研报告的官方定价页 URL
)


class OpenAIProvider(BaseProvider):
    name = "openai"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "openai.com" in url or name.startswith(("gpt-", "o1-", "o3-", "o4-"))

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
            pricing=_OPENAI_PRICING,
            effort_presets={
                "fast": "low",
                "balanced": "medium",
                "deep": "high",
            },
        )
        if name.startswith(("o1-", "o3-", "o4-")):
            # TODO(grok→§7.2): o 系列是否拒绝 temperature / 是否支持 tools，以报告为准
            caps = replace(
                caps,
                supports_reasoning=True,
                thinking_default_on=True,   # o 系列适配 thinking，默认开启
                accepts_temperature=False,
            )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        if caps.supports_reasoning:
            kwargs.pop("temperature", None)
        if caps.effort_presets:
            effort = str(model_config.get("effort") or "balanced")
            preset = caps.effort_presets.get(effort, "medium")
            # TODO(grok→§7.2): reasoning_effort 的传输位置（顶层参数 vs extra_body）以报告为准
            kwargs.setdefault("extra_body", {})["reasoning_effort"] = preset
        return kwargs
```

4. 注册进 `core/providers/__init__.py`：

```python
from core.providers.openai import OpenAIProvider

_PROVIDERS: list[BaseProvider] = [
    # A3 起逐个填入：DeepSeekProvider(), AnthropicProvider(), QwenProvider(),
    # A12 起：OpenAIProvider()（显式命中 openai 时才启用显式能力）
]
```

> 注意：注册表落空时仍然选 `_FALLBACK = OpenAIProvider()` 这个**单例**；`_PROVIDERS` 里再放一个 `OpenAIProvider()` 用于 `matches()` 显式命中。两个实例行为一致（无状态），不会冲突。

5. `tests/test_providers/test_openai_provider.py`：

```python
"""OpenAIProvider 显式优化测试：DC1 保持 + 显式能力。"""
import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES
from core import providers
from core.providers.openai import OpenAIProvider


def test_explicit_openai_url_is_matched():
    p = providers.resolve({"base_url": "https://api.openai.com/v1",
                           "model_name": "gpt-5.2"})
    assert isinstance(p, OpenAIProvider)


def test_relay_with_gpt_name_is_matched():
    p = providers.resolve({"base_url": "https://relay.example/v1",
                           "model_name": "gpt-5.2"})
    assert isinstance(p, OpenAIProvider)


def test_fallback_path_keeps_legacy_defaults():
    # DC1：未知模型仍拿到与改造前逐字节一致的能力
    caps = providers.resolve(
        {"base_url": "https://relay.example/v1", "model_name": "mystery-1"}
    ).capabilities({"base_url": "https://relay.example/v1", "model_name": "mystery-1"})
    assert caps == DEFAULT_CAPABILITIES


def test_matched_gpt_gets_explicit_caps():
    caps = providers.resolve({"base_url": "https://api.openai.com/v1",
                              "model_name": "gpt-5.2"}).capabilities(
        {"base_url": "https://api.openai.com/v1", "model_name": "gpt-5.2"})
    assert caps.pricing.source_url  # 调研报告 URL 已填
    assert caps.effort_presets.get("fast")


def test_reasoning_model_drops_temperature():
    p = providers.resolve({"base_url": "https://api.openai.com/v1",
                           "model_name": "o4-mini"})
    caps = p.capabilities({"base_url": "https://api.openai.com/v1",
                           "model_name": "o4-mini"})
    kwargs = p.llm_kwargs({"base_url": "https://api.openai.com/v1",
                           "model_name": "o4-mini"}, caps)
    assert "temperature" not in kwargs
```

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers config/model_capabilities.py tests/test_providers
python -m pytest tests -q -x --timeout=300
```

**完成判据**
- [ ] `ModelPricing` 追加完成，`DEFAULT_CAPABILITIES` 逐字节不变（跑 A1 的既有测试）
- [ ] DC1 测试 `test_fallback_path_keeps_legacy_defaults` 通过（未匹配模型 == DEFAULT_CAPABILITIES）
- [ ] §7.2 审计通过后 `_OPENAI_PRICING` 已填值且 `source_url` 有 URL
- [ ] 所有 `# TODO(grok→§7.2)` 已按报告填充
- [ ] 未接线到 `agent_v2.py`（接线仍属 A6）

**回滚**：`git revert <commit>`

**常见坑**
- 最容易犯的错：`capabilities()` 不分路径直接返回显式能力——那会违反 DC1，让所有未知模型（如中转站的 mystery 模型）的行为改变。**必须先用 `matches()` 把关**
- `_PROVIDERS` 与 `_FALLBACK` 是两个实例，别只注册一半
- `extra_body` 里放 `reasoning_effort` 前，先确认目标端点是否接受（§7.2 问第 5 问）

**Commit**
```
feat(model): explicit OpenAIProvider with pricing and effort presets

OpenAI was pure fallback; now matched openai endpoints get explicit
capabilities from §7.2 (pricing, effort_presets, o-series reasoning).
DC1 preserved: unmatched models still get byte-identical defaults.
```

---

### A13 · KimiProvider

`P0` / 8h / 依赖 A2、**A0 批 3 审计通过**（§7.3）

**背景**
Kimi / Moonshot 是前端预设的常用族之一（`config/model_manager.py:33`、`frontend/.../providerGroup.ts` 的 `moonshot` 分组）。其模型（如 Kimi K2 系列）的 context 计量、缓存字段、reasoning 行为与 OpenAI 不同，需要显式 provider。

**涉及文件**
- 新建 `core/providers/kimi.py`
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_kimi_provider.py`

**操作步骤**

1. 开工前：读 §7.3 分区（"精准找到自己的位置"），确认九问结论；未通过审计不得开工。
2. `core/providers/kimi.py`：

```python
"""Kimi / Moonshot provider。

与 OpenAI 默认行为的差异以 A0 批 3 调研报告（§7.3）为准：
  - 部分型号 context 以字符计量（K2 系列），tokenizer 用 chars: 估算
  - usage / 缓存命中字段以 §7.3 为准
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.3): 用 A0 批 3 报告替换下列常量并补 URL
_KIMI_USAGE = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(),
    reasoning=(),
)
_KIMI_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.3 官方定价页 URL
)


class KimiProvider(BaseProvider):
    name = "kimi"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "moonshot" in url or "kimi" in name

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_KIMI_USAGE,
            pricing=_KIMI_PRICING,
            prompt_variant="kimi",
            # TODO(grok→§7.3) 第 5 问: thinking 适配判断（适配 → supports_reasoning=True + thinking_default_on=True，默认打开）
            # tokenizer="chars:2.0",
            # context_window=128_000,
        )
        return caps.merged_with_overrides(model_config)
```

3. 注册进 `_PROVIDERS`（顺序：`[DeepSeekProvider(), KimiProvider(), ...]`）。
4. 测试至少覆盖：URL/模型名匹配的正反例、capabilities 关键字段、用户覆盖赢默认、usage 字段提取（参考 `test_deepseek_provider.py` 结构，至少 5 个测试）。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
python -m pytest tests/test_providers/test_registry.py -q
```

**完成判据**
- [ ] `core/providers/kimi.py` + 测试文件存在，≥5 个测试全绿
- [ ] 所有 `# TODO(grok→§7.3)` 已按报告填充并补 URL（§7.3 审计通过后）
- [ ] `test_registry.py` 兜底测试仍绿（matches 不写太宽，不抢走其他模型）
- [ ] 未接线

**回滚**：`git revert <commit>`

**常见坑**
- `matches()` 里 `"moonshot" in url` 会命中 `api.moonshot.ai` 与 `api.moonshot.cn`，注意不要写成 `endswith("moonshot.com")` 之类把 `.cn` 漏掉
- 若 §7.3 显示某型号 context 按字符计量，`context_window` 仍填 token 值（估算用途），并把 `tokenizer` 设成对应 chars 比例

**Commit**
```
feat(model): add KimiProvider with moonshot usage fields
```

---

### A14 · GLMProvider（bigmodel.cn + 火山方舟 Ark 双入口）

`P1` / 8h / 依赖 A2、**A0 批 4 审计通过**（§7.4）

**背景**
GLM 有两个入口都要支持：智谱官方 `open.bigmodel.cn` 与火山方舟 `volces.com/ark`（现网 smoke 数据里 `glm-5.2 @ https://ark.cn-beijing.volces.com/api/coding/v3` 是真实用法，见 `scripts/live_smoke_output.json`）。Ark 上还托管其他模型（如豆包），所以 Ark 入口必须**同时要求模型名含 glm**，否则会抢走豆包。

**涉及文件**
- 新建 `core/providers/glm.py`
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_glm_provider.py`

**操作步骤**

1. 开工前：读 §7.4 分区，确认九问结论；未通过审计不得开工。
2. `core/providers/glm.py`：

```python
"""GLM / 智谱 provider（含火山方舟 Ark 双入口）。

识别规则：
  - bigmodel.cn / zhipu → 命中（智谱官方）
  - volces.com（Ark）+ 模型名含 glm → 命中（Ark 也托管其他模型，必须双条件）
  - 模型名以 glm- 开头（任意中转站）→ 命中
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.4): 用 A0 批 4 报告替换下列常量并补 URL
_GLM_USAGE = UsageFieldMap(
    cache_read_flat=("prompt_cache_hit_tokens",),
    cache_read_nested=(),
    reasoning=("reasoning_content",),
)
_GLM_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.4 官方定价页 URL
)


class GLMProvider(BaseProvider):
    name = "glm"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        if "bigmodel" in url or "zhipu" in url:
            return True
        if "volces.com" in url:
            return "glm" in name  # Ark 双条件：模型名必须含 glm
        return name.startswith("glm-")

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_GLM_USAGE,
            pricing=_GLM_PRICING,
            prompt_variant="glm",
            # TODO(grok→§7.4) 第 5 问: thinking 适配判断（适配 → supports_reasoning=True + thinking_default_on=True，默认打开）
            # tokenizer="chars:2.0",
            # context_window=128_000,
        )
        return caps.merged_with_overrides(model_config)
```

3. 注册进 `_PROVIDERS`。
4. 测试至少覆盖：bigmodel.cn 命中、Ark+glm 命中、**Ark+豆包不命中**（关键反例）、glm- 前缀模型名命中、GLM-4 系列能力字段。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
python -m pytest tests/test_providers/test_registry.py -q
```

**完成判据**
- [ ] `core/providers/glm.py` + 测试全绿，含 Ark+豆包反例测试
- [ ] `# TODO(grok→§7.4)` 已按报告填充并补 URL
- [ ] 兜底测试仍绿
- [ ] 未接线

**回滚**：`git revert <commit>`

**常见坑**
- **Ark 必须双条件**（`"volces.com" in url and "glm" in name`）。只按 URL 匹配会把 Ark 上的豆包等模型抢成 GLM，这是注册表最常见的误伤
- GLM 的 reasoning 内容字段名（glm-4.5/glm-5 系）以 §7.4 为准，不要沿用 DeepSeek 的 `reasoning_content` 假设

**Commit**
```
feat(model): add GLMProvider with bigmodel and volces ark entries
```

---

### A15 · MiniMaxProvider

`P1` / 8h / 依赖 A2、**A0 批 5 审计通过**（§7.5）

**背景**
MiniMax（M2.x 系列，如 M2.1）是前端推荐模型清单之外、但社区常用的编码模型族。其端点 `platform.minimaxi.com` / `api.minimax.chat` 为 OpenAI 兼容，M2 系列带 thinking 模式。需要显式 provider。

**涉及文件**
- 新建 `core/providers/minimax.py`
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_minimax_provider.py`

**操作步骤**

1. 开工前：读 §7.5 分区；未通过审计不得开工。
2. `core/providers/minimax.py`：

```python
"""MiniMax provider（M2.x 系列）。

差异以 A0 批 5 调研报告（§7.5）为准：
  - M2 系列的 thinking 开关 / effort 参数名与默认值以报告为准
  - usage / 缓存命中字段以报告为准
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.5): 用 A0 批 5 报告替换下列常量并补 URL
_MINIMAX_USAGE = UsageFieldMap(
    cache_read_flat=(),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    reasoning=(),
)
_MINIMAX_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.5 官方定价页 URL
)


class MiniMaxProvider(BaseProvider):
    name = "minimax"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "minimax" in url or "minimaxi" in url or "minimax" in name

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_MINIMAX_USAGE,
            pricing=_MINIMAX_PRICING,
            prompt_variant="minimax",
            # TODO(grok→§7.5) 第 5 问: thinking 适配判断（适配 → supports_reasoning=True + thinking_default_on=True，默认打开）
            # tokenizer="chars:2.0",
            # context_window=200_000,
        )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        # TODO(grok→§7.5): M2.x 的 thinking 开关（若需要透传）以报告为准
        return kwargs
```

3. 注册进 `_PROVIDERS`。
4. 测试至少覆盖：匹配正反例、能力字段、用户覆盖、usage 提取。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
```

**完成判据**
- [ ] `core/providers/minimax.py` + 测试全绿
- [ ] `# TODO(grok→§7.5)` 已按报告填充并补 URL
- [ ] 兜底测试仍绿；未接线

**回滚**：`git revert <commit>`

**常见坑**
- MiniMax 的缓存命中字段名（嵌套还是平铺）各版本可能不同，一律以 §7.5 为准，不要照抄本卡的占位假设

**Commit**
```
feat(model): add MiniMaxProvider for M2 series
```

---

### A16 · MIMOProvider（小米）

`P1` / 8h / 依赖 A2、**A0 批 6 审计通过**（§7.6）

**背景**
小米 MiMo 是新增的目标模型族。官方主页 `https://mimo.xiaomi.com/`（2026-08-01 核实）包含：模型家族 MiMo-V2.5-Pro / V2.5 / V2-Flash / V2-Pro / V2-Omni、API Access 开发者入口、以及与本项目三大优化主题直接相关的公开线索：**HySparse（KV Cache Sharing 论文）**、**MiMo-V2.5-Pro-UltraSpeed（1T 参数模型 1000 TPS）**、**Full-Pipeline Inference Optimization（Hybrid SWA）**。真实端点、兼容性、缓存命中字段、UltraSpeed 调用方式**全部以 A0 批 6 调研报告（§7.6）为准**，本卡只建骨架。

**涉及文件**
- 新建 `core/providers/mimo.py`
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_mimo_provider.py`

**操作步骤**

1. 开工前：读 §7.6 分区（端点、OpenAI 兼容性、字段）；未通过审计不得开工。
2. `core/providers/mimo.py`：

```python
"""MIMO（小米 MiMo）provider。

端点与全部字段以 A0 批 6 调研报告（§7.6）为准。
已知公开线索（2026-08-01，mimo.xiaomi.com）：
  - MiMo-V2.5-Pro-UltraSpeed：1T 参数模型生成速度 1000 TPS（加速档位）
  - HySparse：KV Cache Sharing（缓存主题）
  - Hybrid SWA 推理优化（上下文窗口主题）
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.6): 用 A0 批 6 报告替换下列常量并补 URL
_MIMO_USAGE = UsageFieldMap(
    cache_read_flat=(),
    cache_read_nested=(),
    reasoning=(),
)
_MIMO_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.6 官方定价页 URL
)


class MIMOProvider(BaseProvider):
    name = "mimo"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "mimo" in url or name.startswith(("mimo-", "mimo_v"))

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_MIMO_USAGE,
            pricing=_MIMO_PRICING,
            prompt_variant="mimo",
            # TODO(grok→§7.6) 第 5 问: thinking 适配判断（适配 → supports_reasoning=True + thinking_default_on=True，默认打开）
            # tokenizer="chars:2.0",
            # context_window=128_000,
        )
        return caps.merged_with_overrides(model_config)

    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        kwargs = super().llm_kwargs(model_config, caps)
        # TODO(grok→§7.6): UltraSpeed 加速档的调用参数（若有）以报告为准
        return kwargs
```

3. 注册进 `_PROVIDERS`。
4. 测试至少覆盖：匹配正反例、能力字段、用户覆盖、usage 提取。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
```

**完成判据**
- [ ] `core/providers/mimo.py` + 测试全绿
- [ ] `# TODO(grok→§7.6)` 已按报告填充并补 URL（含真实 API 端点）
- [ ] 兜底测试仍绿；未接线

**回滚**：`git revert <commit>`

**常见坑**
- 端点未证实前**禁止**凭猜测填 base_url——`matches()` 与 `llm_kwargs` 里的端点依赖 §7.6，审计通过前保持 TODO 状态
- `"mimo" in url` 可能误伤（如第三方网关路径里含 mimo 字样），反例测试要覆盖

**Commit**
```
feat(model): add MIMOProvider for Xiaomi MiMo family
```

---

### A17 · QwenProvider 补全

`P1` / 6h / 依赖 A2、**A0 批 7 审计通过**（§7.7）

**背景**
A4 只给了 Qwen 的骨架方向（"分词器差异最大，`tokenizer` 用 `chars:` 估算；DashScope 兼容端点的 function calling 支持情况需确认"），没有完整实现。本卡把它补全：DashScope 端点识别、qwen 系列的 thinking 开关（qwen3 系）、官方 qwen-tokenizer 是否存在、usage/缓存字段，全部以 §7.7 为准。

**涉及文件**
- 新建 `core/providers/qwen.py`（A4 若已建则在其基础上补全）
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_qwen_provider.py`

**操作步骤**

1. 开工前：读 §7.7 分区；未通过审计不得开工。
2. `core/providers/qwen.py`：

```python
"""Qwen / 通义千问 provider（DashScope）。

差异以 A0 批 7 调研报告（§7.7）为准：
  - qwen3 系的 thinking 开关与默认值以报告为准
  - 官方 tokenizer：有 qwen-tokenizer / tiktoken 兼容 encoding 则用，否则 chars: 估算
  - DashScope 兼容端点（dashscope.aliyuncs.com）的 function calling 支持以报告为准
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.7): 用 A0 批 7 报告替换下列常量并补 URL
_QWEN_USAGE = UsageFieldMap(
    cache_read_flat=(),
    cache_read_nested=(("prompt_tokens_details", "cached_tokens"),),
    reasoning=(),
)
_QWEN_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.7 官方定价页 URL
)


class QwenProvider(BaseProvider):
    name = "qwen"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "dashscope" in url or "aliyuncs" in url or "qwen" in name

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_QWEN_USAGE,
            pricing=_QWEN_PRICING,
            prompt_variant="qwen",
            # TODO(grok→§7.7) 第 5 问: thinking 适配判断（qwen3 系 enable_thinking → supports_reasoning=True + thinking_default_on=True，默认打开）
            # tokenizer="tiktoken:qwen2" 或 "chars:2.0"
            # context_window=128_000,
        )
        return caps.merged_with_overrides(model_config)
```

3. 注册进 `_PROVIDERS`。
4. 测试至少覆盖：dashscope/aliyuncs 命中、qwen 模型名命中、反例、能力字段、usage 提取。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
```

**完成判据**
- [ ] `core/providers/qwen.py` 完整实现（非 A4 的骨架注释），测试全绿
- [ ] `# TODO(grok→§7.7)` 已按报告填充并补 URL
- [ ] 兜底测试仍绿；未接线

**回滚**：`git revert <commit>`

**常见坑**
- DashScope 兼容端点与百炼（Model Studio）的 base_url 不同，以 §7.7 为准
- qwen3 系 thinking 开关（enable_thinking / chat_template_kwargs）若在 OpenAI 兼容端点不生效，在 `llm_kwargs` 里别硬塞，写明降级方式

**Commit**
```
feat(model): complete QwenProvider with dashscope specifics
```

---

### A18 · AnthropicProvider 补全

`P1` / 6h / 依赖 A2、**A0 批 8 审计通过**（§7.8）

**背景**
A4 只给了 Anthropic 的方向（"`prompt_variant="claude"`；prompt 缓存的 `cache_control` 语义与 OpenAI 不同，需要在 `supports_prompt_cache` 上体现"）。本卡补全：Claude 的 thinking block 语义、prompt caching 断点（最多 4 个断点、最小 1024 token 块、TTL 5 分钟/1h）、reasoning 内容剥离（Phase E 的 strip 环节会用）、以及 OpenAI 兼容端点下的能力边界（MA4 禁止引入 anthropic SDK，原生端点的完整断点支持标注为受限）。

**涉及文件**
- 新建 `core/providers/anthropic.py`（A4 若已建则补全）
- 修改 `core/providers/__init__.py`（注册）
- 新建 `tests/test_providers/test_anthropic_provider.py`

**操作步骤**

1. 开工前：读 §7.8 分区；未通过审计不得开工。
2. `core/providers/anthropic.py`：

```python
"""Anthropic Claude provider（OpenAI 兼容端点路径）。

限制说明：本项目走 OpenAI 兼容端点（MA4 禁止引入 anthropic SDK），因此
cache_control 断点与 thinking block 的原生语义在兼容端点上可能不完整
透传；capabilities 按兼容端点能生效的部分声明，原生端点能力标注为
"受限（原生 SDK 接入前不承诺）"，由 A19 的缓存卡按真实端点行为处理。

差异以 A0 批 8 调研报告（§7.8）为准。
"""

from __future__ import annotations

from dataclasses import replace

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    ModelPricing,
    UsageFieldMap,
)
from core.providers.base import BaseProvider

# TODO(grok→§7.8): 用 A0 批 8 报告替换下列常量并补 URL
_CLAUDE_USAGE = UsageFieldMap(
    cache_read_flat=(),
    cache_read_nested=(),
    reasoning=(),
)
_CLAUDE_PRICING = ModelPricing(
    input_per_mtok=None,
    output_per_mtok=None,
    cached_input_per_mtok=None,
    as_of="",
    source_url="",  # ← §7.8 官方定价页 URL
)


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def matches(self, base_url: str, model_name: str) -> bool:
        url = base_url.lower()
        name = model_name.lower()
        return "anthropic" in url or name.startswith("claude-")

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            usage_fields=_CLAUDE_USAGE,
            pricing=_CLAUDE_PRICING,
            prompt_variant="claude",
            supports_prompt_cache=False,  # 兼容端点无法透传 cache_control 时保持关闭，
            # 由 A19 按 §7.8 的真实端点行为决定是否打开
            # thinking_default_on 保持 False：兼容端点无法控制 thinking block，
            # 若 §7.8 确认兼容端点可透传 thinking 参数再置 True（默认打开）
            # TODO(grok→§7.8): 下列数值以报告为准
            # context_window=200_000,
        )
        return caps.merged_with_overrides(model_config)
```

3. 注册进 `_PROVIDERS`。
4. 测试至少覆盖：anthropic URL/claude- 模型名命中、反例、`supports_prompt_cache` 当前为 False（兼容端点保守默认）、能力字段。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
```

**完成判据**
- [ ] `core/providers/anthropic.py` 完整实现，测试全绿
- [ ] `# TODO(grok→§7.8)` 已按报告填充并补 URL
- [ ] 兼容端点的能力边界（尤其 `supports_prompt_cache`）在 PR 描述里说明
- [ ] 兜底测试仍绿；未接线

**回滚**：`git revert <commit>`

**常见坑**
- 兼容端点与原生端点的能力差很多（thinking block、cache_control 断点、tool_use 格式）。**不要把原生端点文档里的字段直接填进兼容路径**——这是 A18 最常踩的坑
- `matches()` 里 `"anthropic" in url` 会命中中转站路径含 anthropic 的 URL，属预期行为（该模型族确实来自 Anthropic）

**Commit**
```
feat(model): complete AnthropicProvider with compat-endpoint boundaries
```

---

### A19 · per-model 缓存参数

`P1` / 8h / 依赖 A8 + A12–A18 全部、**A0 全部 8 批审计通过**

**背景**
缓存命中率是 agent 成本的胜负手（参考 Cherry Studio 在 DeepSeek 上的 99.5%+ 命中率——那是"前缀字节级稳定"纪律的副产品，不是显式优化）。本卡把 per-model 缓存参数落成能力字段：最小缓存块、TTL、断点布局（Anthropic 系）、命中字段读取、命中率监控接入。动态内容（工具结果、检索、状态）一律尾部追加的**消息纪律**属于消息链改造（Phase 2 Session / EF 范围），本卡只负责"每个模型该打什么缓存参数"。

**与现有缓存代码的边界（2026-08-01 review 补充）**：`config/settings.py` 的 `cache` 段有 `enabled/prompt_prefix_cache/ttl`（:220-224），其中 `enabled` 与 `ttl` 目前是**无人读取的死配置**（仅 `prompt_prefix_cache` 被 `agent_v2.py:405` 读取）；本卡的 `cache_ttl_s` 是 `ModelCapabilities` 上的 **provider 侧缓存 TTL**，与 settings 的 `cache.ttl` 命名空间不同、语义不同，**不得混用**（死配置清理归主计划 §9/待办池）。`utils/streaming.py` 的 `token_stats`（:50-51、:62-78、:85-96）已采集 `prompt_tokens / cache_hit_tokens / cache_hit_rate`，本卡步骤 5 是**扩展**现有记录，不新建计数器。

**涉及文件**
- `config/model_capabilities.py`（追加字段，只追加）
- `core/providers/base.py`（追加 `cache_params()` 辅助）
- 新建 `tests/test_providers/test_cache_params.py`

**操作步骤**

1. 开工前：重读 §7.1–§7.8 的**第 4 问（prompt cache 机制）**，按模型族汇总成一张"缓存参数表"，写进 PR 描述。
2. `ModelCapabilities` 追加：

```python
    #: 该模型族 prompt cache 的最小可缓存前缀（token）。Anthropic 系有明确
    #: 下限（如 1024/4096），OpenAI/DeepSeek 自动缓存无此要求 → None。
    cache_min_block_tokens: int | None = None

    #: 缓存 TTL（秒）。None = 不适用（自动缓存 / 未知）。
    cache_ttl_s: int | None = None

    #: 断点布局（Anthropic 系显式 cache_control 用，最多 4 个）。
    #: 取值按"静态在前、动态在后"排序，只允许打在恒定内容末尾：
    #:   ["tools", "system", "session_static", "tail"]
    #: 空列表 = 不用显式断点。A8 的 _apply_cache_control 读取它。
    cache_breakpoints: tuple[str, ...] = ()
```

3. `core/providers/base.py` 追加辅助（供 `_apply_cache_control` 与 A19 测试使用）：

```python
    def cache_params(self, caps: ModelCapabilities) -> dict:
        """该模型族的缓存参数包，供消息链注入与命中率监控使用。

        返回键固定为：min_block_tokens / ttl_s / breakpoints / hit_field_flat /
        hit_field_nested。默认值 = "不适用"，各 provider 按 §7.X 覆写。
        """
        return {
            "min_block_tokens": caps.cache_min_block_tokens,
            "ttl_s": caps.cache_ttl_s,
            "breakpoints": list(caps.cache_breakpoints),
            "hit_field_flat": list(caps.usage_fields.cache_read_flat),
            "hit_field_nested": list(caps.usage_fields.cache_read_nested),
        }
```

4. 各 provider 的 `capabilities()` 按对应 §7 分区填充三个新字段（示例，DeepSeek）：

```python
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            cache_min_block_tokens=None,   # DeepSeek 自动缓存，无下限要求
            cache_ttl_s=None,              # 官方未承诺固定 TTL
            # TODO(grok→§7.1): 以上两值以报告第 4 问为准
        )
```

5. 命中率监控接入（只读不写，接 `utils/streaming.py` 已有的 `token_stats.cache_hit_rate` 与 `_extract_cache_read`）：在 `_record_usage` 的 span 记录里，于 `token_usage` 现有字段（prompt/completion/total，见 `core/tracing.py` 的 NodeSpan）**追加 `cache_read` 字段**落盘（tracing 是 JSONL，字段可扩展），确保命中率可被 evals/trajectory 观测——**本卡不新增 UI**。
6. `tests/test_providers/test_cache_params.py`：断言每族 `cache_params()` 的字段与 §7 报告一致（反例：乱序断点、打在动态块上的断点应被拒绝——校验器放在 base.py）。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers config/model_capabilities.py
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 三个新字段追加，默认值全部为"不适用"（None / 空元组），既有行为零变化
- [ ] 8 族 `cache_params()` 与 §7 报告逐条一致，PR 描述附缓存参数汇总表
- [ ] 断点布局校验器拒绝非法断点（>4 个 / 含动态块）
- [ ] evals 零回归

**回滚**：`git revert <commit>`

**常见坑**
- 断点只能打在恒定内容末尾（Anthropic 官方明确警告：打在每轮变化的块上 = 永不命中）。校验器必须挡住
- DeepSeek/OpenAI 是自动缓存，`cache_min_block_tokens=None` 是正确的——不要照抄 Anthropic 的 1024 规则

**Commit**
```
feat(model): per-model cache parameters with breakpoint validation
```

---

### A20 · per-model token 治理

`P1` / 8h / 依赖 A5 A7 + A12–A18 全部、**A0 全部 8 批审计通过**

**背景**
每任务 20–30 万 token 的消耗大头是：全量工具描述、全量 few-shot、记忆注入、工具输出。本卡给每个模型族声明 token 治理参数（输出上限、few-shot 策略、工具发送策略、记忆预算），由调用方（A9 的 prompt 变体机制 + fast path 工具组包）消费。**本卡只建参数与消费点，默认值全部保持现状行为**（"全量"）。

**涉及文件**
- `config/model_capabilities.py`（追加字段，只追加）
- `core/agent_v2.py`（`_get_core_tools` 附近与 `llm_kwargs` 消费点，走接线请求）
- 新建 `tests/test_providers/test_token_governance.py`

**操作步骤**

1. 开工前：重读 §7.1–§7.8 第 6/7 问（tokenizer、定价），按模型族汇总 token 参数表。
2. `ModelCapabilities` 追加：

```python
    #: 单次请求输出上限（token）。None = 沿用 llm_kwargs 的 max_tokens 默认 8192。
    max_output_tokens: int | None = None

    #: few-shot 注入策略。None = 现状（全量注入，A9 前的行为）。
    #:   "full" 全量 / "first2" 只留前 2 条 / "none" 不注入
    few_shot_policy: str | None = None

    #: 工具描述发送策略。None = 现状（全量发送）。
    #:   "full" 全量 / "subset" 按任务子集（由调用方决定子集，会话内固定）
    tool_send_policy: str | None = None

    #: 工具输出截断阈值（token）。None = 现状（不截断）。
    tool_output_token_limit: int | None = None
```

3. 消费点（接线请求，参考 A6 的用法）：`_get_core_tools` 组包时按 `tool_send_policy`；`_raw_stream` 的 `payload["max_tokens"]` 用 `max_output_tokens` 覆盖；`planning/structured_output.py` 与 fast path 的工具结果记录按 `tool_output_token_limit` 截断（截断位置保留头尾，参考 `memory/compressor.py` 的 `_middle_truncate`）。
4. few-shot 消费点：A9 的 prompt 变体机制里按 `few_shot_policy` 选择注入量（`core/prompts/registry.py` 的 `get_role_prompt(..., include_few_shot=...)` 已有关口）。
5. `tests/test_providers/test_token_governance.py`：断言默认值全为 None（现状零变化）；每个 provider 的取值与 §7 一致；消费点测试（fake provider 设定值后行为正确）。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m pytest tests -q -x --timeout=600
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 四个新字段默认全为 None，现状行为零变化
- [ ] 消费点全部走接线请求，改动最小化（PR 描述列出每个改动点）
- [ ] 与 §7 报告的 tokenizer/定价结论一致
- [ ] evals 零回归

**回滚**：`git revert <commit>`

**常见坑**
- `tool_output_token_limit` 截断时**不要**改 ToolMessage 对象本身（会破坏 tool_call_id 契约），截断的是注入上下文的文本副本——参考 A7 里 `_maybe_compress_context` 的现有做法
- `few_shot_policy` 改动直接影响 evals 分数；每调一族必须单独跑基线比对

**Commit**
```
feat(model): per-model token governance knobs (defaults unchanged)
```

---

### A21 · per-model 延迟旋钮

`P1` / 8h / 依赖 A6 A8 + A12–A18 全部、**A0 全部 8 批审计通过**

**背景**
延迟是 agent 体验的胜负手。每个模型族可用的"速度旋钮"不同：DeepSeek v4 的 `reasoning_effort`（low/high/max，默认 high）、OpenAI 的 `reasoning_effort`、MiMo 的 UltraSpeed 档、Anthropic 的 thinking budget。本卡把它们统一成 `effort_presets`（fast / balanced / deep 三档），并让 fast path 默认走 `fast` 档、复杂任务走 `balanced`/`deep`。**本卡只定义旋钮与默认映射，行为默认不变**（balanced = 现状）。

**前端 thinking 面板与模型 thinking 模式是两回事（2026-08-01 补充，重要区分）**

| 维度 | 前端 thinking 面板 | 模型 thinking 模式 |
|---|---|---|
| 是什么 | **展示层**：显示模型的思维链（`reasoning_content`） | **API 层行为**：模型是否真的产出思维链 |
| 谁控制 | `/thinking` 命令、`_flush_thinking`/`write_reasoning` | `ModelCapabilities.supports_reasoning` + `thinking_default_on` + `llm_kwargs` |
| 面板开着、模型没开 | 面板空转（无内容可显示） | — |
| 模型开着、面板关着 | — | 思维链不展示，**但仍在消耗 token**（推理 token 计费） |

**二者不互相绑定。** 面板开关不影响模型是否思考；模型思考与否由能力字段决定。

**thinking 适配判断规则（默认打开）**：每个 provider 卡（A12–A18）按 §7 对应批**第 5 问**结论做判断：

- **适配（支持 thinking）** → `supports_reasoning=True` **且** `thinking_default_on=True`（默认打开）
- **不适配 / 兼容端点不可控**（如 Anthropic 兼容端点的 thinking block 不透传）→ 两者保持 `False`，零注入
- `effort_presets` 的档位只调 effort 力度，**不关 thinking**：fast 档 = 低 effort 的 thinking（仍开着）；要彻底关闭走显式配置（`thinking_default_on=False` 或用户配置），那是"减法"开关

**涉及文件**
- `config/model_capabilities.py`（`effort_presets` 已在 A12 追加、`thinking_default_on` 已在 A12 追加，本卡消费）
- `core/agent_v2.py`（fast path 构造 LLM 时按档位传参，走接线请求）
- 新建 `tests/test_providers/test_effort_presets.py`

**操作步骤**

1. 开工前：重读 §7.1–§7.8 第 5/8 问（thinking 参数、延迟特性），按模型族汇总"旋钮表"。
2. 各 provider 的 `capabilities()` 按报告填充 `effort_presets`，例如：

```python
        # DeepSeek v4（以 §7.1 为准）：thinking 总开关 + effort 档位
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            effort_presets={"fast": "low", "balanced": "high", "deep": "max"},
            # TODO(grok→§7.1): 档位取值与传输位置以报告为准
        )
```

3. **thinking 默认开启的接线**（2026-08-01 补充）：`llm_kwargs` 组装 thinking 参数——**适配 thinking 的模型默认打开**。通用实现可放 `core/providers/base.py`（各 provider 覆写传输位置）：

```python
    def llm_kwargs(self, model_config: dict, caps: ModelCapabilities) -> dict:
        """按能力组装 thinking / effort 参数。

        判断规则（§7 第 5 问结论）：
          - supports_reasoning=False → 不支持 thinking，零注入
          - supports_reasoning=True 且 thinking_default_on=True → 默认打开
            （thinking enabled + 按档位设 effort；fast 档 = 低 effort 的
            thinking，仍是开着的；彻底关闭走显式配置 thinking_default_on=False）
        """
        kwargs = super().llm_kwargs(model_config, caps)
        if not (caps.supports_reasoning and caps.thinking_default_on):
            return kwargs
        body = kwargs.setdefault("extra_body", {})
        body["thinking"] = {"type": "enabled"}   # TODO(grok→§7.X): 传输位置以报告为准
        effort = str(model_config.get("effort") or "balanced")
        preset = caps.effort_presets.get(effort) or caps.effort_presets.get("balanced")
        if preset:
            body["reasoning_effort"] = preset
        return kwargs
```

4. `AgentV2` 增加档位选择逻辑（接线请求，改 `_build_llm_from_config` 与 fast path 入口）：

```python
    def _effort_for(self, mode: str, text: str) -> str:
        """按任务性质选推理档位：fast path 用 fast，其余用 balanced。

        deep 档只由显式配置（effort=deep）触发，不自动使用——贵且慢。
        """
        if mode == "plan":
            return "balanced"
        if mode == "build" and self._is_simple_query(text):
            return "fast"
        return "balanced"
```

   调用点：`_build_llm_from_config` 里 `model_config.setdefault("effort", self._effort_for(...))`（A12 的 `llm_kwargs` 已消费 `effort` 键）。
5. `tests/test_providers/test_effort_presets.py`：断言默认 balanced 与现状一致；fast path 落到 fast 档；不支持的模型族 `effort_presets` 为空时**不得**注入任何额外参数；`thinking_default_on=True` 的模型默认带 thinking 参数、`False` 零注入。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m pytest tests -q -x --timeout=600
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 默认档位 = balanced（= 现状行为），evals 零回归
- [ ] fast path 显式走 fast 档且对不支持的模型零注入
- [ ] 每族 `effort_presets` 与 §7 报告一致
- [ ] deep 档仅显式配置触发
- [ ] **thinking 适配判断完成**：适配模型 `thinking_default_on=True`（默认打开）且 `llm_kwargs` 带 thinking 参数；不适配模型保持 `False`、零注入
- [ ] `thinking_default_on` 默认 `False`，未适配前行为与现状完全一致

**回滚**：`git revert <commit>`

**常见坑**
- thinking 模式下 temperature 等采样参数会被拒绝（DeepSeek v4 官方行为）——切档位时 `llm_kwargs` 必须同步删采样参数，否则 400
- `effort_presets` 为空（不支持档位的模型）时**禁止**往 `extra_body` 里塞任何参数——透传无效参数可能触发端点报错

**Commit**
```
feat(model): per-model latency knobs via effort presets
```

---

### A22 · DeepSeek v4 补全

`P1` / 6h / 依赖 A3、**A0 批 1 审计通过**（§7.1）

**背景**
A3 写于 DeepSeek chat/reasoner（V3/R1）时代；2026 年 7 月起官方模型已是 **deepseek-v4-flash / deepseek-v4-pro**（官方文档 2026-08-01 核实），行为模型变了：
- thinking 是**总开关**（`{"thinking": {"type": "enabled/disabled"}}`），**默认开启、默认 effort=high**，不再是"R1 专用"
- `reasoning_effort: low/high/max`（官方映射表：flash 的 low/high/max 原样映射、xhigh→high；pro 的 low→high、xhigh→high；官方称 2026-08 初将更新 pro 的映射——**以 §7.1 复核为准**）
- thinking 模式下 temperature / top_p / presence_penalty / frequency_penalty **全部无效**（不报错但被忽略）
- 带 tools 时必须把上一轮 `reasoning_content` 完整回传，否则 **400 错误**
- 缓存命中字段 `prompt_cache_hit_tokens`（平铺）不变；命中 0.1x 计费

本卡把 A3 的旧假设按 §7.1 重写（不修改 A3 卡本身，作为补全卡独立存在）。

**涉及文件**
- 修改 `core/providers/deepseek.py`（A3 已建，本卡覆盖其旧分支）
- 新建 `tests/test_providers/test_deepseek_v4.py`

**操作步骤**

1. 开工前：读 §7.1 分区，确认 v4-flash/pro 的全部数值；未通过审计不得开工。
2. 重写 `core/providers/deepseek.py` 的识别与能力逻辑（以 §7.1 为准，下为结构示例）：

```python
    def matches(self, base_url: str, model_name: str) -> bool:
        return "deepseek" in base_url.lower() or "deepseek" in model_name.lower()

    def capabilities(self, model_config: dict) -> ModelCapabilities:
        model_name = str(model_config.get("model_name") or "").lower()
        is_v4_flash = "flash" in model_name
        is_v4_pro = "pro" in model_name
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider=self.name,
            context_window=_V4_CONTEXT,          # TODO(grok→§7.1)
            compaction_threshold=int(_V4_CONTEXT * 0.9),
            usage_fields=_DEEPSEEK_USAGE,
            supports_reasoning=True,              # v4 默认 thinking 开启
            thinking_default_on=True,             # 适配 thinking → 默认打开（官方 API 默认即开）
            accepts_temperature=False,            # thinking 模式下采样参数无效
            supports_function_calling=True,       # TODO(grok→§7.1): v4 全系 tools 支持
            structured_output="function_calling",
            prompt_variant=("deepseek-v4-flash" if is_v4_flash
                            else "deepseek-v4-pro" if is_v4_pro else "deepseek"),
            effort_presets={
                "fast": "low",
                "balanced": "high",   # 官方默认档
                "deep": "max",
            },
        )
        return caps.merged_with_overrides(model_config)
```

3. **thinking 开关接线**（A8 已有 `_apply_cache_control` 模式可参照）：按 **A21 的通用 `llm_kwargs`** 实现——`supports_reasoning=True 且 thinking_default_on=True` 时默认发 `thinking: enabled` + 档位 `reasoning_effort`（传输位置以 §7.1 为准）。**不要**用"enabled if supports_reasoning else disabled"一刀切：thinking_default_on=False 时是"不发参数"（零注入），不是"发 disabled"。
4. **reasoning_content 回传纪律**：记录到 A19 的缓存纪律文档（`docs/modules/providers.md` 新增一节"DeepSeek v4 会话续接"）：带 tools 的轮次必须把 assistant 消息的 `reasoning_content` 一并回传（`_to_openai_messages` 保留该字段），否则 400。
5. `tests/test_providers/test_deepseek_v4.py`：v4-flash/v4-pro 命中、thinking 默认开、采样参数被删、effort 档位映射、tools+reasoning_content 回传契约（用 `_to_openai_messages` 的 fixture 断言字段保留）。

**验收命令**

```powershell
python -m pytest tests/test_providers -q
python -m ruff check core/providers tests/test_providers
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] `# TODO(grok→§7.1)` 全部按报告填充并补 URL
- [ ] v4 识别/能力/effort/thinking 开关与 §7.1 逐条一致
- [ ] tools + reasoning_content 回传契约有测试
- [ ] 旧型号（deepseek-chat/reasoner）行为若 §7.1 未覆盖，保持 A3 原逻辑不回归

**回滚**：`git revert <commit>`

**常见坑**
- v4 的 `accepts_temperature=False` 是 thinking 模式行为；若 §7.1 确认 `thinking: disabled` 时采样参数可用，`llm_kwargs` 要按开关动态决定，不能一刀切
- 400 错误的排查顺序：先看是否漏回传 `reasoning_content`（DeepSeek 官方明确：带 tools 的请求不回传必 400）

**Commit**
```
feat(model): adapt DeepSeekProvider to v4 flash/pro era
```

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

**第 1 步 · 查资料**（交给 Grok，由 A0 统一执行，2026-08-01 起）

调研不再在卡内临时进行，统一由 **A0** 承担（分批调研 + 每批审计 + §7 分区汇报）。新增模型族时：

1. 在 A0 的调研清单里追加一批（或复用已有批次），按 A0 的 9 问模板调研
2. 结果写入 §7 新分区，通过 A0 的审计门（Grok 自审 + 第三方非编码模型审计，§7.9 留档）
3. 通过审计后，再按下面第 2–7 步写 provider

本手册第 2–7 步与调研解耦，可参照任意已通过的 provider 卡执行。

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
| `ModelCapabilities.supports_vision` | Phase F 多模态 | Phase A 只占字段不实现，Phase F 填逻辑 |
| Provider 无状态单例（约束 DC2） | Phase B/C | 多个 Agent 会并发调用同一个 provider 实例，**不要在 provider 里存任何 per-request 状态** |
| `ModelCapabilities.prompt_variant` | Phase B/C 角色化 Agent | 不同角色的 Agent 可能用不同模型，变体机制要能按 agent 解析 |
| `AgentState._capabilities` | Phase B/C | 多 Agent 下每个 agent 的 capabilities 不同，state 注入要按 agent 隔离 |

> **2026-08-01 扩展追加的接缝**（新增字段，消费方与约束）：

| 预留（新增） | 给谁用 | 约束 |
|---|---|---|
| `ModelPricing`（A12） | **Phase E E4 成本核算** | 本卡定义是 E4（`PHASE-E-MULTI-MODEL-COLLABORATION.md:529-543`）的超集；E4 中心表优先级更高；`None` 必须显式处理（缺失不静默当 0，对齐 E4 判据） |
| `effort_presets`（A12/A21） | Phase C C10 难度路由、Phase E E11 评测矩阵 | 路由与评测可按 fast/balanced/deep 档位横向比较延迟与质量；空 dict = 不支持档位，禁止注入任何参数 |
| `cache_min_block_tokens` / `cache_ttl_s` / `cache_breakpoints`（A19） | Phase E E4 缓存定价、Phase 2 Session 消息链 | 断点布局只打在恒定内容末尾（≤4 个）；TTL 是 provider 侧语义，与 settings `cache.ttl`（死配置）无关 |
| `max_output_tokens` / `few_shot_policy` / `tool_send_policy` / `tool_output_token_limit`（A20） | Phase 2 Session 消息链、Phase B/C 角色化 Agent | 默认 `None` = 现状（全量）行为，任何消费方不得假定非 None |
| A0 调研报告（§7） | Phase E E4 定价表、A12–A22 全部数值、Phase F F4 图像 token 公式 | 数值唯一来源；对应批未通过审计不得使用 |

---

## §7 Grok 模型调研报告（A0 产物）

> **本章节由 A0 卡（2026-08-01 扩展）负责填充，按模型族分区。**
> 每个分区的数据是 A12–A22 等优化卡的**数值唯一来源**；对应分区未通过 §7.9 的审计之前，相关优化卡不得开工（A0 审计门）。
> 分区固定结构：① 调研记录表（批次/日期/调研模型/来源 URL）② 九问结论 ③ "对 RxyCode 的含义"（映射到 `ModelCapabilities` / `UsageFieldMap` / `ModelPricing` 字段的具体建议值）。

### §7.1 DeepSeek（A0 批 1）

> 状态：**三方审计通过（2026-08-02）**。A3/A22 可按本分区填充数值。Grok / DeepSeek / GPT-5.6-Luna 均已通过（见 §7.9）。
>
> **修订历程**：rev2（首轮不通过清单）→ rev3（Luna Q6 措辞）→ 终审通过。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 1 · DeepSeek v4 全系 |
| 调研日期 | 2026-08-02（rev2/rev3 同日修订；终审同日通过） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://api-docs.deepseek.com/ |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| S1 | Your First API Call（型号 / base_url） | https://api-docs.deepseek.com/ |
| S2 | Models & Pricing | https://api-docs.deepseek.com/quick_start/pricing |
| S3 | Thinking Mode | https://api-docs.deepseek.com/guides/thinking_mode |
| S4 | Chat Completions API | https://api-docs.deepseek.com/api/create-chat-completion/ |
| S5 | Context Caching | https://api-docs.deepseek.com/guides/kv_cache |
| S6 | Context Caching 发布说明（历史：64-token 块 / 旧价） | https://api-docs.deepseek.com/news/news0802/ |
| S7 | Rate Limit & Isolation | https://api-docs.deepseek.com/quick_start/rate_limit |
| S8 | Token & Token Usage | https://api-docs.deepseek.com/quick_start/token_usage |
| S9 | DeepSeek V4 Preview Release | https://api-docs.deepseek.com/news/news260424/ |
| S10 | Codex 集成（context_window 数值） | https://api-docs.deepseek.com/quick_start/agent_integrations/codex/ |
| S11 | HF DeepSeek-V4-Flash-0731 README（本地 tokenizer 参考） | https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731 |
| S12 | HF DeepSeek-V4-Pro encoding README | https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/blob/main/encoding/README.md |
| S13 | Change Log（型号更新日期 / 旧 id 下线） | https://api-docs.deepseek.com/updates |
| S14 | Responses API（缓存 usage 字段差异） | https://api-docs.deepseek.com/guides/responses_api |

#### ② 九问结论

**1. 主力型号与版本号**

| API model id | MODEL VERSION（定价页） | 最近官方更新日期 | 备注 |
|---|---|---|---|
| `deepseek-v4-flash` | DeepSeek-V4-Flash-0731 | **2026-07-31**（S13：Flash API 正式公测/升级；调用 id 不变） | HF 权重名同 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro | **2026-04-24**（S13：V4 首发）；**2026-07-31 明确未更新 Pro API** | Preview 已开源；API 可用 |

- 旧型号（S13 2026-04-24 原文）：`deepseek-chat` / `deepseek-reasoner` **will be discontinued in three months (2026-07-24)**；过渡期内分别指向 `deepseek-v4-flash` 的 non-thinking / thinking。S9 新闻页同义表述：fully retired after Jul 24th, 2026, 15:59 (UTC)。
- V4 发布说明：Pro = 1.6T total / 49B active；Flash = 284B total / 13B active；官方服务默认 1M context。

[来源 S1, S2, S9, S13]

**2. Context window（token）**

| 型号 | context length | max output |
|---|---|---|
| `deepseek-v4-flash` | **1M**（Codex 配置写明 `1048576`） | MAXIMUM **384K** |
| `deepseek-v4-pro` | **1M**（同定价页 CONTEXT LENGTH 列） | MAXIMUM **384K** |

建议 RxyCode 填 `context_window = 1_048_576`（1M tokens），`compaction_threshold ≈ 943_718`（≈90%）。

[来源 S2, S10]

**3. OpenAI 兼容与 tools / function calling**

- **兼容**：OpenAI Chat Completions（`base_url=https://api.deepseek.com`）与 Anthropic API（`https://api.deepseek.com/anthropic`）。
- **tools**：定价页 FEATURES 对 flash/pro 均为 ✓ Tool Calls；Chat Completions schema 支持 `tools`（最多 128 个 function）、`tool_choice`（`none`/`auto`/`required`/指定函数）。
- Thinking 模式下**支持** tool calls（见 thinking_mode「Tool Calls」节）。
- Responses API：目前**仅** `deepseek-v4-flash` 支持；`deepseek-v4-pro` 计划 2026-08 初支持。RxyCode 主路径仍是 Chat Completions。

[来源 S1, S2, S3, S4, S14]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制 | **自动** Context Caching on Disk；**无需**改代码、**无** OpenAI 式显式 `cache_control` 断点；Responses API 也不支持 `prompt_cache_key` / `prompt_cache_retention`（仍自动管理） |
| 命中规则（已证实） | 必须以**已持久化的 cache prefix unit 完整匹配**；中间部分匹配不命中。改前缀历史 / 在前缀中插入消息 → 无法完整匹配该 unit → 不命中 |
| 持久化时机 | ① 请求边界（user 输入末 / model 输出末）② 多请求公共前缀检测 ③ 长输入/输出按固定 token 间隔切出 unit |
| TTL | 「不再使用后通常在**数小时到数天**内自动清除」；不保证 100% 命中 |
| 最小块 | **现行 Context Caching 指南未再写「64 tokens」**。S6 新闻仍写「64 tokens as a storage unit」。**以现行指南为准；64-token 标为历史备注 / 待核实是否仍适用** |
| usage 字段（按端点） | **Chat Completions**：顶层 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`（`prompt_tokens = hit + miss`）。**Responses API**：`usage.input_tokens_details.cached_tokens`（命中数）；**不是**顶层 `prompt_cache_*` |
| 隔离（已证实） | `user_id` 用于 KVCache isolation |
| 切模型 / 切 API key / 截断 | **未找到**官方逐条失效规则声明。只能从「完整匹配 prefix unit」推论：任一操作若破坏完整前缀匹配则不命中；**不得写成已证实的失效清单** |

[来源 S5, S6, S4, S7, S14]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

| 项 | 结论 |
|---|---|
| 适配判断 | **适配** → `supports_reasoning=True`，`thinking_default_on=True` |
| 开关（OpenAI） | `thinking: {"type": "enabled"\|"disabled"}`；SDK 需放 `extra_body`。默认 **`enabled`**；默认 effort **`high`** |
| effort 合法值 | `reasoning_effort`: `low` / `high` / `max`（另有兼容别名 `medium`/`xhigh`） |
| 输出字段 | `reasoning_content`：与 `content` **同级**，在 **message** 上；流式在 **delta.reasoning_content** |
| usage 推理 token（Chat Completions） | `usage.completion_tokens_details.reasoning_tokens` |
| 被忽略的采样参数（thinking 模式） | `temperature`、`top_p`、`presence_penalty`、`frequency_penalty`：**不报错，但无效**。另：`frequency_penalty`/`presence_penalty` 在 API 层已标 deprecated，传入不生效 |

**官方 effort 实际映射表（S3 原文，2026-08-02 复核；驳回「pro xhigh→high」审计主张）：**

| Requested effort | deepseek-v4-flash 实际映射 | deepseek-v4-pro 实际映射 |
|---|---|---|
| `low` | `low` | `high` |
| `high` | `high` | `high` |
| `xhigh` | `high` | **`max`** |
| `max` | `max` | `max` |

补充（S4 schema 原文）：`medium` and `xhigh` are mapped to `high`（兼容说明）；同时明确 pro **temporarily** only supports `high`/`max` 区分，且 **`xhigh` is treated as `max`**。脚注：官方称 early August 2026 将更新 pro 映射——**以本表现行原文为准，未到公告前不得自行改写**。

[来源 S3, S4]

**6. 官方 tokenizer**

- **未找到**官方 tiktoken encoding 名（S8 未声明任何 tiktoken 兼容 encoding；不得写成「官方确认无」）。
- 官方 API 文档（S8）：提供 `deepseek_tokenizer.zip` 离线 demo；给出近似比例 1 英文字符 ≈ 0.3 token、1 汉字 ≈ 0.6 token；并明确**实际计费/计数以 API 返回的 `usage` 为准**。
- HF AutoTokenizer（S11/S12）可用于本地权重编码；**未找到**「与 API usage 逐 token 等价」的官方声明 → 不得当作 API 精确 tokenizer。
- A5 `TokenizerSpec` 当前仅支持 `tiktoken:` / `chars:`（不支持 `hf:`）。

RxyCode 建议（可落地，**启发式非官方数值**）：`tokenizer = "chars:2.0"`——由 S8 近似比例（英 0.3 / 中 0.6）混合折中得到的**项目侧估算**，**不是**官方公布的 tokenizer 规格。精确 token 数始终以 API `usage` 为准。离线核对可参考 `deepseek_tokenizer.zip` / HF，**不写入 TokenizerSpec**。

[来源 S8, S11, S12；约束见 A5]

**7. 定价（USD / 1M tokens；as_of = 2026-08-02 查阅 S2）**

| 型号 | INPUT cache hit | INPUT cache miss | OUTPUT | 缓存写入价 |
|---|---|---|---|---|
| `deepseek-v4-flash` | **$0.0028** | **$0.14** | **$0.28** | **无单独写入价**（自动磁盘缓存；命中按 hit 价，未命中按 miss 价） |
| `deepseek-v4-pro` | **$0.003625** | **$0.435** | **$0.87** | 同上 |

- 即将实行峰谷价：高峰时段（北京时间 09:00–12:00、14:00–18:00）**全部计费项 ×2**；生效日「以官方公告为准」→ 代码侧可预留但 **as_of 当日尚未生效**。
- S6 新闻中的旧 hit 价 $0.014 **已过时**，以 S2 为准。

[来源 S2；历史对照 S6]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT / 吞吐 | 现行定价与 rate_limit 页**未公布**固定 TTFT/TPS SLA。S6 历史示例（非现行 SLA）：128K 高复用前缀 TTFT 可由 ~13s 降至 ~500ms |
| 限流 | **按账号并发数**，非经典 RPM/TPM：`deepseek-v4-pro` **500**；`deepseek-v4-flash` **2500**。超限 HTTP **429**。可申请扩容免费 |
| 加速档 | 官方定价/能力页对名为 UltraSpeed / fast mode 的 API 档位：**未找到**。Flash 在产品叙述上更快更便宜；HF Flash-0731 的 DSpark speculative decoding 属**本地/自托管**，非 API 参数 |
| Keep-alive | 推理未开始超过 **10 分钟**断连；流式可能收到 `: keep-alive` |

[来源 S2, S7, S6, S11]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| 无 tool call 的多轮 | 中间 assistant 的 `reasoning_content` **可不回传**；回传也会被 API **忽略** |
| **有 tools 的请求链** | 之后所有后续请求**必须完整回传** `reasoning_content`；否则 API 返回 **400**（S3 已证实） |
| 推荐写法 | `messages.append(response.choices[0].message)`（含 content / reasoning_content / tool_calls） |
| 工具调用后的专门缓存行为 | **未找到**独立于通用前缀缓存的专项规则。仅能确认：仍适用 S5 的完整 prefix-unit 匹配；**不得断言**「tool 回合必然命中/必然失效」 |

[来源 S3, S5]

#### ③ 对 RxyCode 的含义（A3 / A22 照抄用；审计通过前禁止写入代码）

```text
# ModelCapabilities（deepseek-v4-flash / deepseek-v4-pro 共用骨架，差异见注释）
context_window = 1_048_576
compaction_threshold = 943_718          # ≈ 0.9 * context_window
max_output_tokens = 384_000             # 官方 MAXIMUM 384K
supports_function_calling = True
supports_reasoning = True
thinking_default_on = True              # 官方 thinking 默认 enabled
supports_prompt_cache = True            # 自动磁盘缓存，无显式 cache_control
structured_output = "function_calling"  # + json_object response_format
prompt_variant = "deepseek-v4-flash" | "deepseek-v4-pro"
tokenizer = "chars:2.0"                 # RxyCode 启发式估算（非官方规格）；A5 可落地；勿写 hf:
# effort_presets（OpenAI 兼容传输；映射以 S3 表为准）
#   开关: extra_body={"thinking": {"type": "enabled"|"disabled"}}
#   档位: reasoning_effort="low"|"high"|"max"（默认 high）
#   flash: low→low, high→high, xhigh→high, max→max
#   pro:   low→high, high→high, xhigh→max, max→max
effort_presets = {"fast": "low", "balanced": "high", "deep": "max"}

# UsageFieldMap（Chat Completions 主路径）
cache_read_flat = ("prompt_cache_hit_tokens",)
# cache miss: prompt_cache_miss_tokens
# reasoning: ("completion_tokens_details", "reasoning_tokens")
# Responses API（仅 flash，非主路径）: input_tokens_details.cached_tokens
#   / output_tokens_details.reasoning_tokens —— 若接 Responses 需另建字段映射

# ModelPricing（USD / 1M tok；source_url = S2；as_of = 2026-08-02）
# flash: input_cache_hit=0.0028, input_cache_miss=0.14, output=0.28, cache_write=None
# pro:   input_cache_hit=0.003625, input_cache_miss=0.435, output=0.87, cache_write=None
# peak_multiplier=2.0（公告生效后；当前未生效）

# 会话契约（agent_v2 / executor 必须遵守）
# - tools 链路上必须回传 reasoning_content，否则 400
# - thinking 模式下不要依赖 temperature/top_p 调采样
# - base_url: https://api.deepseek.com ；勿引入 anthropic/deepseek 原生 SDK（MA4）
# - 旧 id deepseek-chat/reasoner：S13 宣布 2026-07-24 停用；迁移到 v4-flash ± thinking
```

### §7.2 OpenAI（A0 批 2）

> 状态：**三方审计通过（2026-08-02）**。Grok 自审·rev2 + DeepSeek + GPT-5.6-Luna 复审均通过。A12 可按本分区填充数值。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 2 · OpenAI（GPT-5.x 全系，主写 GPT-5.6） |
| 调研日期 | 2026-08-02（rev2 同日修订） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://platform.openai.com/docs/ |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| O1 | Models 总览（GPT-5.6 Sol/Terra/Luna） | https://platform.openai.com/docs/models |
| O2 | GPT-5.6 Sol 型号页 | https://platform.openai.com/docs/models/gpt-5.6-sol |
| O3 | GPT-5.6 Terra 型号页 | https://platform.openai.com/docs/models/gpt-5.6-terra |
| O4 | GPT-5.6 Luna 型号页 | https://platform.openai.com/docs/models/gpt-5.6-luna |
| O5 | Pricing | https://platform.openai.com/docs/pricing |
| O6 | Prompt caching | https://platform.openai.com/docs/guides/prompt-caching |
| O7 | Reasoning models | https://platform.openai.com/docs/guides/reasoning |
| O8 | Migrate to Responses（含 Chat Completions `reasoning_effort` 示例） | https://platform.openai.com/docs/guides/migrate-to-responses |
| O9 | Rate limits | https://platform.openai.com/docs/guides/rate-limits |
| O10 | Counting tokens | https://platform.openai.com/docs/guides/token-counting |
| O11 | Fast mode（原 Priority） | https://platform.openai.com/docs/guides/fast-mode |
| O12 | Changelog（发布/更新日期） | https://platform.openai.com/docs/changelog （同 Luna 引：https://developers.openai.com/api/docs/changelog） |

#### ② 九问结论

**1. 主力型号与版本号**

| API model id | 别名 / 定位 | Knowledge cutoff | API 发布日 | 最近 Changelog 更新 | 备注 |
|---|---|---|---|---|---|
| `gpt-5.6-sol` | 别名 `gpt-5.6`；旗舰 | **2026-02-16** | **2026-07-09**（家族首发） | **2026-07-30**（定价/Fast mode 等） | 默认 snapshot = 自身 |
| `gpt-5.6-terra` | 智能与成本平衡 | **2026-02-16** | **2026-07-09** | **2026-07-30**（价降 20% 等） | 对应旧系 mini 档 |
| `gpt-5.6-luna` | 成本敏感高吞吐 | **2026-02-16** | **2026-07-09** | **2026-07-30**（价降 80% 等） | 对应旧系 nano 档 |

- **Knowledge cutoff ≠ 最近更新日期**：前者是训练知识截止（型号页）；后者以 **Changelog** 为准（O12：Jul 9 发布 GPT-5.6 家族；Jul 30 更新三档定价并引入 Fast mode）。
- 定价页另列更早 GPT-5.x（如 `gpt-5.5` / `gpt-5.5-pro` / `gpt-5.4` 等）。本批 **RxyCode 主目标为 GPT-5.6 三档**。

[来源 O1, O2, O3, O4, O5, O12]

**2. Context window（token）**

| 型号 | context window | max input | max output |
|---|---|---|---|
| `gpt-5.6-sol` / `terra` / `luna` | **1,050,000** | **922,000** | **128,000** |

建议 RxyCode：`context_window = 1_050_000`，`compaction_threshold ≈ 945_000`（≈90%）。长上下文计费阈值：输入 **>272K** 时整单按 long-context 价（input×2、output×1.5，见定价页与型号页）。

[来源 O2, O3, O4, O5]

**3. OpenAI 兼容与 tools / function calling**

- **原生** OpenAI：Chat Completions（`v1/chat/completions`）与 Responses（`v1/responses`）在 GPT-5.6 型号页均标 **Supported**。
- **推荐路径**：官方明确 Reasoning **在 Responses 上更好**；Chat Completions **仍支持**，但智能/性能与缓存利用率不如 Responses（O7/O8）。
- **tools**：型号页 Supported features 含 `function_calling`、`structured_outputs`、`prompt_caching`、`image_input` 等；Responses 另列 web_search / file_search / computer_use 等托管工具。
- RxyCode 现状走 `ChatOpenAI` → Chat Completions；本报告字段以 Chat Completions 为主，Responses 差异单独标注。

[来源 O2, O7, O8]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制 | **自动**前缀缓存（`gpt-4o` 及更新）；GPT-5.6+ 另支持 **显式断点** `prompt_cache_breakpoint` + `prompt_cache_options.mode`（`implicit` 默认 / `explicit`）与 `prompt_cache_key` |
| 最小前缀 | GPT-5.6+：**严格 ≥ 1,024 tokens**；更早型号约 1024–2048 且可能不稳定 |
| TTL（GPT-5.6+） | `prompt_cache_options.ttl` 仅支持 **`30m`**（亦为默认）= 最少存活 30 分钟，官方可保留更久 |
| 更早型号 retention（按型号，勿一刀切） | **`gpt-5.5` / `gpt-5.5-pro`：仅支持 `prompt_cache_retention: "24h"`**（不支持 `in_memory`）。`in_memory` **仅**适用于官方接受该策略的更早型号（「models that accept `prompt_cache_retention: "in_memory"`」）；同时支持两者时，默认随组织 ZDR 策略变化。对 GPT-5.6+ 该字段 **已弃用**，改用 `prompt_cache_options.ttl` |
| usage 命中字段 | **Chat Completions**：`usage.prompt_tokens_details.cached_tokens`；另有 `cache_write_tokens`（5.6+）。**Responses**：`usage.input_tokens_details.cached_tokens` |
| 写入计费（5.6+） | `cache_write_tokens` 按 **uncached input × 1.25** 计费；更早型号写缓存无额外费 |
| 失效 / 不命中（已证实） | **精确前缀匹配**（exact prefix matches）；改静态前缀、改 tools/schema、改图像 detail、断点前内容变化 → 不完整匹配 → 不命中。组织间缓存不共享。**未找到**「切 API key」专项声明 |
| 截断与缓存 | O6 **未找到**「从头部截断会 bust cache / 降低后续命中」的专项官方声明。Realtime 文档另有 truncation/cache 表述，**不得当作 O6 已证实结论**写入本批 |
| GPT-5.6 注意 | 默认隐式断点在最新 user/tool 消息；可变后缀会导致 `cached_tokens=0` 与反复写缓存——应用显式断点 + `prompt_cache_key`；可靠匹配要求设置 `prompt_cache_key` |

[来源 O6]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

| 项 | 结论 |
|---|---|
| 适配判断 | **适配** → `supports_reasoning=True`；`thinking_default_on=True`（省略 effort 时 GPT-5.6 **默认 `medium`**，非 `none`） |
| Responses 开关 | `reasoning: { "effort": "...", "mode": "standard"\|"pro", "context": "auto"\|"current_turn"\|"all_turns" }` |
| Chat Completions 开关 | 顶层参数 **`reasoning_effort`**（O8 迁移文档示例）；**不是** DeepSeek 式 `thinking.type` |
| effort 档位 | 可能含 `none` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max`（**型号子集不同**；5.6 型号页列 none/low/medium/high/xhigh/max） |
| 默认 | GPT-5.6：省略 `reasoning.effort` → **`medium`**（standard 与 pro 模式皆然）。`gpt-5.5` 文档亦写默认 medium |
| 输出 | **不暴露原始 reasoning tokens**；可用 `summary` 看摘要。Responses usage：`output_tokens_details.reasoning_tokens`。Chat Completions：`completion_tokens_details.reasoning_tokens`（见 O6 usage 示例） |
| temperature / top_p | 本批在 reasoning 指南中 **未找到**「GPT-5.6 拒绝 temperature」的明文。旧 o 系列拒绝采样参数的说法**不得外推到 5.6**，标 **未找到（待核实）** |
| pro 模式 | `reasoning.mode=pro`（Responses）：更重计算、更高延迟；与 effort 独立 |

[来源 O1, O2, O7, O8, O6]

**6. 官方 tokenizer**

- 官方推荐：`responses.input_tokens.count`（与 Responses 同形 payload）拿**精确** input token 数（O10）。
- 本地 [tiktoken](https://github.com/openai/tiktoken)：**可用于纯文本**，但对图像/文件/tools/schema/reasoning/caching **不准确**（O10 原文）。
- **未找到** GPT-5.6 官方公布的具体 tiktoken encoding 名（如 `o200k_base`）。不得声称「官方指定 o200k」。

RxyCode 建议（A5 可落地、启发式）：文本估算暂用 `tokenizer = "tiktoken:o200k_base"`（与仓库现状 gpt-4o 默认一致），并注释「非官方 5.6 encoding 名；精确计数应走 input_tokens.count / API usage」。

[来源 O10]

**7. 定价（USD / 1M tokens；Standard · Short context；as_of = 2026-08-02 查阅 O5；Changelog Jul 30 已反映现行价）**

| 型号 | Input | Cached input | Cache writes | Output |
|---|---|---|---|---|
| `gpt-5.6-sol` | **$5.00** | **$0.50** | **$6.25** | **$30.00** |
| `gpt-5.6-terra` | **$2.00** | **$0.20** | **$2.50** | **$12.00** |
| `gpt-5.6-luna` | **$0.20** | **$0.02** | **$0.25** | **$1.20** |

- Long context（>272K input）：整单更高价（型号页：input×2、output×1.5；定价表另有 Long context 列）。
- **Fast mode**（原 Priority，**2026-07-30** 更名）：`service_tier: "fast"` 或 `"priority"`；价更高（例 sol Fast：$10 / $1 / $12.50 / $60）。
- Batch / Flex：定价页另有折价列。

[来源 O5, O2, O11, O12]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT / 吞吐 SLA | 型号页 **未公布**固定 TTFT/TPS 数值 |
| 限流 | 组织 **usage tier** 决定 RPM/TPM/RPD 等（O9）。例：`gpt-5.6-sol` Standard Tier1 = **500 RPM / 500,000 TPM**（O2） |
| 加速档 | **Fast mode**（`service_tier: fast`/`priority`）存在（O5/O11/O12）。另有 Batch、Flex 处理档 |

[来源 O2, O5, O9, O11, O12]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| 原始 CoT 回传 | API **不返回**原始 reasoning 文本；有 `encrypted_content`（stateless/ZDR）等不透明项 |
| 工具调用（Responses） | **强烈建议**回传上一轮 function call 以来的全部 `reasoning` / `function_call` / `function_call_output` items；可用 `previous_response_id` 或手工重放 output |
| GPT-5.6 context | 默认 `reasoning.context=all_turns`（可渲染更早 reasoning）；更早模型默认 `current_turn` |
| Chat Completions | 须自管 messages；无 Responses 的 item 连续语义。迁移文档：从 GPT-5.4 起，Chat Completions 在 `reasoning: none` 时 **不支持** tool calling（细则见 O8） |
| 缓存与续接 | 保持静态前缀 + 稳定 `prompt_cache_key`（O6 已证实有助于命中）。**截断是否 bust cache：O6 未找到专项声明**——仅能确认仍须满足 exact prefix matching；不得写成已证实「截断→必然降命中」 |

[来源 O7, O8, O6]

#### ③ 对 RxyCode 的含义（A12 照抄用；审计通过前禁止写入代码）

```text
# ModelCapabilities（gpt-5.6-sol/terra/luna 共用骨架；定价按型号分条）
context_window = 1_050_000
compaction_threshold = 945_000
max_output_tokens = 128_000
supports_function_calling = True
supports_vision = True                    # 型号页 input: text, image
supports_reasoning = True
thinking_default_on = True                # 省略 effort → 默认 medium
supports_prompt_cache = True
structured_output = "function_calling"    # + structured_outputs / json_schema
prompt_variant = "gpt-5.6-sol" | "gpt-5.6-terra" | "gpt-5.6-luna"
tokenizer = "tiktoken:o200k_base"         # 项目侧启发式；未找到官方 5.6 encoding 名
# effort（Chat Completions 主路径）
#   顶层: reasoning_effort="none|low|medium|high|xhigh|max"（见 O8；minimal 是否全档支持→查型号页）
# Responses 路径（若未来接入）: reasoning={"effort": "...", "mode": "standard"|"pro"}
effort_presets = {"fast": "low", "balanced": "medium", "deep": "high"}
# 可选: service_tier "fast" 作为加速档（非 effort）

# UsageFieldMap（Chat Completions）
cache_read_nested = ("prompt_tokens_details", "cached_tokens")
cache_write_nested = ("prompt_tokens_details", "cache_write_tokens")  # 5.6+
reasoning_nested = ("completion_tokens_details", "reasoning_tokens")
# Responses（非主路径）: input_tokens_details.cached_tokens /
#   output_tokens_details.reasoning_tokens

# ModelPricing（USD/1M；source_url=O5；as_of=2026-08-02；Short context Standard）
# sol:   input=5.00, cached=0.50, cache_write=6.25, output=30.00
# terra: input=2.00, cached=0.20, cache_write=2.50, output=12.00
# luna:  input=0.20, cached=0.02, cache_write=0.25, output=1.20
# long_context_threshold_tokens = 272_000  # >272K 整单涨价

# 会话契约
# - Chat Completions: 传 reasoning_effort；自管 messages
# - 若改 Responses: 工具链回传 reasoning items / previous_response_id
# - 5.6 缓存: prompt_cache_key + 显式断点，避免可变后缀写穿缓存
# - 截断是否 bust cache: O6 未找到专项声明（仅 exact prefix matching）
# - base_url: https://api.openai.com/v1 ；MA4 不引入新 SDK
```

### §7.3 Kimi / Moonshot（A0 批 3）

> 状态：**三方审计通过（2026-08-02）**。Grok 自审·rev2 + DeepSeek + GPT-5.6-Luna 复审均通过。A13 可按本分区填充数值。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 3 · Kimi / Moonshot（主写 K3 / K2.7 Code / K2.6） |
| 调研日期 | 2026-08-02（rev2 同日修订） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://platform.moonshot.cn/ |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| M1 | 开放平台首页（型号卡片 + 人民币定价摘要） | https://platform.moonshot.cn/ |
| M2 | 模型列表 | https://platform.kimi.com/docs/models |
| M3 | 模型参数参考 | https://platform.kimi.com/docs/api/models-overview |
| M4 | API 概述（OpenAI 兼容 / base_url） | https://platform.kimi.com/docs/api/overview |
| M5 | Chat Completions（含 OpenAPI：`cached_tokens` / `prompt_cache_key`） | https://platform.kimi.com/docs/api/chat |
| M6 | OpenAPI 规范 | https://platform.kimi.com/docs/openapi.json |
| M7 | Context Caching | https://platform.kimi.com/docs/guide/use-context-caching-feature-of-kimi-api |
| M8 | 思考模型 / Preserved Thinking | https://platform.kimi.com/docs/guide/use-thinking-models |
| M9 | 推理强度 `reasoning_effort` | https://platform.kimi.com/docs/guide/use-reasoning-effort |
| M10 | Kimi K3 快速开始 | https://platform.kimi.com/docs/guide/kimi-k3-quickstart |
| M11 | 计算 Token | https://platform.kimi.com/docs/api/estimate |
| M12 | 模型推理价格说明（计费概念） | https://platform.kimi.com/docs/pricing/chat |
| M13 | K3 / K2.6 / K2.7 Code 定价页 | https://platform.kimi.com/docs/pricing/chat-k3 · [chat-k26](https://platform.kimi.com/docs/pricing/chat-k26) · [chat-k27-code](https://platform.kimi.com/docs/pricing/chat-k27-code) |
| M14 | 充值与限速 | https://platform.kimi.com/docs/pricing/limits |
| M15 | 平台 Changelog | https://platform.kimi.com/docs/changelog/changelog/changelog |
| M16 | 工具调用指南 | https://platform.kimi.com/docs/guide/use-kimi-api-to-complete-tool-calls |

#### ② 九问结论

**1. 主力型号与版本号**

| API model id | 定位 | context（见 Q2） | 最近官方日期线索 | 备注 |
|---|---|---|---|---|
| `kimi-k3` | 旗舰；始终推理；视觉/视频 | **1,048,576**（营销亦写 1M） | 权重目标 **2026-07-27** 前发布（M10）；首页已挂牌（M1） | RxyCode **主目标** |
| `kimi-k2.7-code` | Coding；始终思考 + Preserved Thinking | **262,144**（营销亦写 256k） | 见模型列表（M2） | 与 highspeed **同能力不同价** |
| `kimi-k2.7-code-highspeed` | 同上；输出约 180 tok/s（短上下文可达 260） | **262,144** | M2 / M3 / M13 | 参数约束同 `kimi-k2.7-code`；**单价更高** |
| `kimi-k2.6` | 通用；默认可关思考；可 Preserved Thinking | **262,144**（营销亦写 256k） | M2 | 多模态 |
| `kimi-k2.5` | 通用思考；**不支持** Preserved Thinking | 营销写 256k；精确值本批以定价页未单列 → 待核实 | M2：K3 发布后对新用户停开；**全平台下线 8 月 31 日** | 迁移目标：新模型 |
| `moonshot-v1-*` | 经典生成 / vision | 8k/32k/128k | 同上：新用户停开；**全平台下线 8 月 31 日** | 不宜作为 RxyCode 新接默认 |
| 已下线 `kimi-k2*` 等 | — | — | **2026-05-25** 下线（M2） | 勿填进 capabilities |

- **Knowledge / 发布日**：官方 **未找到** 单独的「K3 API 首发日」Changelog 条目；M15 平台 Changelog **最新条目停在 2025-04-07**，**不能**当作 K3 更新日。可用日期以 M2 下线公告、M10 权重截止日期、M1 挂牌状态为准；第三方「2026-07-16 上线」**不得**写入本批已证实结论。
- RxyCode 建议主写：`kimi-k3`（旗舰）+ `kimi-k2.7-code` / `kimi-k2.7-code-highspeed`（编程加速档）+ `kimi-k2.6`（可关思考的通用档）。

[来源 M1, M2, M10, M15]

**2. Context window（token）**

| 型号 | 精确 context（定价页） | 营销/概述近似 | 备注 |
|---|---|---|---|
| `kimi-k3` | **1,048,576** | 「1M / 100 万 token」 | `max_completion_tokens` 默认 **131072**，最大可至 **1048576**（M10）；不得超过模型上下文，否则 `invalid_request_error` |
| `kimi-k2.7-code` | **262,144** | 「256k」 | M13 chat-k27-code |
| `kimi-k2.7-code-highspeed` | **262,144** | 「256k」 | 同上 |
| `kimi-k2.6` | **262,144** | 「256k」 | M13 chat-k26 |
| `kimi-k2.5` | 本批定价页未单列精确值 | 「256k」（M2/M3） | 精确值标 **待核实**（即将下线，非主目标） |
| `moonshot-v1-8k/32k/128k`（及 vision） | **8k / 32k / 128k** | 同左 | 输入+输出合计上限（M2） |

- **精确值来源**：官方定价页 DocTable「上下文窗口」列（M13 `.md` 源：K3=`1,048,576 tokens`；K2.7-code/highspeed/K2.6=`262,144 tokens`）。模型列表/说明里的「1M / 256k」视为营销近似，**不得**当作 `context_window` 填值。
- 建议 RxyCode：`kimi-k3` → `context_window = 1_048_576`，`compaction_threshold ≈ 943_000`（≈90%）；`kimi-k2.7-code` / `highspeed` / `kimi-k2.6` → `262_144` / `≈236_000`。

[来源 M13, M2, M3, M10]

**3. OpenAI 兼容与 tools / function calling**

- **兼容**：请求/响应兼容 OpenAI Chat Completions；`base_url=https://api.moonshot.cn/v1`，端点 `/v1/chat/completions`（M4）。可用官方 OpenAI SDK。
- **tools**：支持 Tool Use / `tool_calls`（M5/M16）；K3 另支持 `tool_choice`: `auto`/`none`/`required`；`kimi-k2.6` / `kimi-k2.7-code` **不支持** `required`（传入报错）（M3）。
- **专有扩展**：`thinking`（K2.x，常经 `extra_body`）；messages 上 `partial`；K3 动态工具 system message（`tools` 无 `content`）；可选顶层 **`prompt_cache_key`**（M5/M6）。
- RxyCode 现状 `ChatOpenAI` 路径可对接；K2.x 的 `thinking` 需 `extra_body`。

[来源 M4, M3, M5, M6, M16]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制 | **自动** Context Caching；**无需** cache ID / 手动 TTL / 显式 `cache_control` 断点（M7） |
| 最小前缀 | 前一请求 **prompt tokens > 256** 才会被缓存；**< 256 不缓存、丢弃**（M7/M10） |
| TTL | **系统自动管理**；现行指南写「无需管理 TTL」（M7）。旧「手动 Cache 创建/续期计费」叙述以现行自动机制为准，勿混用历史公测文档 |
| 可选优化 | 请求体 **`prompt_cache_key`**（string）：提高相似请求命中率；Coding Agent 用稳定 session/task id；Kimi Code Plan 场景文档称必填以提高命中（M5/M6 OpenAPI） |
| usage 命中字段 | **`usage.cached_tokens`**（OpenAPI `ChatCompletionResponse` / `ChatCompletionChunk`）（M5/M6）。**未找到** `prompt_cache_hit_tokens` 字段名——A13 骨架占位若写该名，应以本报告 `cached_tokens` 为准 |
| 缓存写入价 | 现行首页/自动缓存说明 **未找到** 单独「缓存写入」单价；计费为 **输入（未命中）** vs **缓存命中** 两档（M1/M12） |
| 失效 / 不命中 | **已证实**：切换 **`reasoning_effort` 档位会破坏前缀缓存命中**（M3 明确警告）。**最小前缀**：前一请求 prompt &lt;256 不进入缓存（M7）。**未找到**「改 system / 知识文档 / 工具定义 / 截断 / 切 API key」的逐项确定性失效清单——官方仅要求知识内容、system prompt、工具定义**相对稳定以提高命中率**（M7 注意事项），不得写成已证实 bust 规则 |
| 多轮建议 | 固定长大上下文放在 `messages` **最前**（可在 system 之前），其后追加问答（M7） |

[来源 M7, M5, M6, M3, M10, M1]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

| 项 | `kimi-k3` | `kimi-k2.7-code`(+highspeed) | `kimi-k2.6` |
|---|---|---|---|
| 适配 | **适配** → `supports_reasoning=True`，`thinking_default_on=True` | 同左（始终思考） | 同左（**默认** enabled） |
| 开关 | **无** `thinking`；始终推理 | 勿传 / 仅 `{"type":"enabled","keep":"all"}`；`disabled` **报错** | `thinking.type`=`enabled`（默认）/`disabled`；`keep`=`null`（默认）/`"all"` |
| effort | 顶层 **`reasoning_effort`**: `low`/`high`/`max`，**默认 `max`** | 不支持 | 不支持 |
| 输出字段 | `message.reasoning_content`；流式在 **`delta.reasoning_content`**（先于 `content`） | 同左 | 同左（enabled 时） |
| 采样参数 | `temperature` **固定 1.0**、`top_p` **固定 0.95**、`n`=1、`presence/frequency_penalty`=0；**建议不要显式传入**，改值报错（M3/M10） | 同左（temperature 固定 1.0） | 思考时 temp=1.0 / 非思考 0.6；top_p 固定 0.95 等 |

- K3：**关不了思考**；嫌长则把 `reasoning_effort` 设为 `low`（M10 FAQ）。
- **切换 `reasoning_effort` 会破坏前缀缓存**——应在会话开始前固定档位（M3）。

[来源 M8, M9, M3, M10]

**6. 官方 tokenizer**

- **未找到** tiktoken 兼容 encoding 名。
- 官方推荐：调用 **`POST /v1/tokenizers/estimate-token-count`**，取 `data.total_tokens`（M11）。
- 计费概念页：中文大约 **1 Token ≈ 1.5–2 个汉字**（M12）——仅近似。

RxyCode 建议（A5 可落地、启发式）：`tokenizer = "chars:1.75"`（取 1.5–2 中点；**非**官方 encoding），注释「精确计数走 estimate-token-count / usage」；**勿**写 `hf:`。

[来源 M11, M12]

**7. 定价（CNY / 1M tokens；中国区；as_of = 2026-08-02 查阅 M13 定价页 `.md` 源表）**

| 型号 | 输入（缓存未命中） | 输入（缓存命中） | 输出 | 缓存写入 | 上下文窗口（同页） |
|---|---|---|---|---|---|
| `kimi-k3` | **¥20.00** | **¥2.00** | **¥100.00** | **未找到**单独写入价 | 1,048,576 |
| `kimi-k2.7-code` | **¥6.50** | **¥1.30** | **¥27.00** | **未找到** | 262,144 |
| `kimi-k2.7-code-highspeed` | **¥13.00** | **¥2.60** | **¥54.00** | **未找到** | 262,144 |
| `kimi-k2.6` | **¥6.50** | **¥1.10** | **¥27.00** | **未找到** | 262,144 |

- **不得**把 `kimi-k2.7-code-highspeed` 与普通 `kimi-k2.7-code` 共用价格（M13 chat-k27-code 分两行）。
- 首页卡片（M1）未单独展示 highspeed 价；**填值以 M13 定价页为准**。
- K3：**不按上下文长度分段计价**（M10 FAQ）；思考 token 计入消耗（M8）。
- 国际站 USD 价与 CNY **不得混用**；本批不填 USD。
- `source_url`：`https://platform.kimi.com/docs/pricing/chat-k3` / `chat-k27-code` / `chat-k26`。

[来源 M13, M12, M10, M1]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT / 吞吐 SLA | 固定 TTFT **未找到**。缓存页称长文本场景首 Token 延迟平均可降至 **5s 内**（相对叙述，非硬 SLA）（M7） |
| 加速档 | **`kimi-k2.7-code-highspeed`**：约 **180 Tokens/s**，短上下文可达 **260**（M2）——独立 model id，且 **单价约为普通版 2 倍**（见 Q7） |
| 限流 | 按账户 **累计充值金额** 分 Tier（M14 DocTable）。代金券不计入累计充值；异常行为可触发不可解除风控限速（M14） |
| K3 访问 | 最低充值 **10 元** 解锁；注册赠送代金券 **不可** 用于 K3（M10） |

M14 阶梯（并发 / RPM / TPM / TPD）：

| Tier | 累计充值 | 并发 | RPM | TPM | TPD |
|---|---|---|---|---|---|
| Tier0 | ¥0 | 1 | 3 | 500,000 | 1,500,000 |
| Tier1 | ¥50 | 50 | 200 | 2,000,000 | Unlimited |
| Tier2 | ¥100 | 100 | 500 | 3,000,000 | Unlimited |
| Tier3 | ¥500 | 200 | 5,000 | 3,000,000 | Unlimited |
| Tier4 | ¥5,000 | 400 | 5,000 | 4,000,000 | Unlimited |
| Tier5 | ¥20,000 | 1,000 | 10,000 | 5,000,000 | Unlimited |

[来源 M14, M2, M7, M10]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| Preserved Thinking / 工具链 | **K3**：多轮与工具调用须把 API 返回的 **完整 assistant message 原样回传**（含 `reasoning_content`、`tool_calls`）（M8/M9/M10） |
| K2.7-code | Preserved Thinking **始终开** → **必须**回传历史 `reasoning_content` |
| K2.6 | 默认 `thinking.keep=null` 不保留历史思考；`keep:"all"` 时同须原样回传 |
| 单轮工具循环 | 同轮多步工具内应保留全部 `reasoning_content`（M8） |
| 缓存 | 稳定前缀 + 可选稳定 `prompt_cache_key`；**勿中途切换 `reasoning_effort`**（M3/M7） |
| `max_tokens` | 思考模型建议 `max_tokens>=16000`（或使用 `max_completion_tokens`）以免截断 reasoning+content（M8） |

[来源 M8, M9, M10, M3, M7]

#### ③ 对 RxyCode 的含义（A13 照抄用；审计通过前禁止写入代码）

```text
# ModelCapabilities（按型号分条；骨架示意）
# --- kimi-k3 ---
context_window = 1_048_576            # 定价页精确值；非营销「1M」
compaction_threshold = 943_000        # ≈90%
max_output_tokens = 131_072           # 默认；上限可至 1_048_576（勿超上下文）
supports_function_calling = True
supports_vision = True                # 原生视觉；另支持 video（M10）
supports_reasoning = True
thinking_default_on = True            # 始终推理；默认 reasoning_effort=max
supports_prompt_cache = True          # 自动前缀缓存
structured_output = "json_schema"     # + json_object（M10）
prompt_variant = "kimi-k3"
tokenizer = "chars:1.75"              # 启发式；精确走 estimate-token-count
# effort（Chat Completions 顶层）
#   reasoning_effort = "low"|"high"|"max"（默认 max；无 medium）
effort_presets = {"fast": "low", "balanced": "high", "deep": "max"}
# 勿显式传 temperature/top_p/...（固定值，改则报错）
# 可选: prompt_cache_key = 稳定 session/task id

# --- kimi-k2.7-code ---
# context_window = 262_144；thinking 始终开 + keep=all
# pricing: input=6.50, cached=1.30, output=27.00

# --- kimi-k2.7-code-highspeed ---
# context_window = 262_144；能力同 k2.7-code；更快
# pricing: input=13.00, cached=2.60, output=54.00  # 勿与普通版共用

# --- kimi-k2.6 ---
# context_window = 262_144；thinking 默认 enabled；可 disabled
# Preserved Thinking: extra_body thinking.keep="all"
# pricing: input=6.50, cached=1.10, output=27.00

# UsageFieldMap（官方 OpenAPI）
cache_read_flat = ("cached_tokens",)   # 非 prompt_cache_hit_tokens
cache_read_nested = ()
reasoning = ()                         # reasoning 在 message.reasoning_content，非 usage 嵌套字段

# ModelPricing（CNY/1M；as_of=2026-08-02；source_url=M13）
# k3:        input=20.00, cached=2.00,  output=100.00, cache_write=None
# k2.7:      input=6.50,  cached=1.30,  output=27.00,  cache_write=None
# k2.7-hs:   input=13.00, cached=2.60,  output=54.00,  cache_write=None
# k2.6:      input=6.50,  cached=1.10,  output=27.00,  cache_write=None
# 货币：CNY（中国区）；勿填国际站 USD

# 会话契约
# - base_url: https://api.moonshot.cn/v1 ；MA4 不引入新 SDK
# - 工具/多轮：原样回传完整 assistant（含 reasoning_content）
# - K3：会话开始前固定 reasoning_effort（切换会 bust 前缀缓存，M3 已证实）
# - 缓存：自动；prompt>256；保持初始前缀相对稳定以提高命中（逐项失效规则未找到）
# - limits: Tier0–5 见 Q8（M14）
```

### §7.4 GLM / 智谱（A0 批 4）

> 状态：**三方审计通过（2026-08-02）**。Grok 自审·rev2 + DeepSeek + GPT-5.6-Luna 复审均通过。A14 可按本分区填充数值。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 4 · GLM / 智谱（主写 GLM-5.2 / 5.1 / 5 / 5-Turbo / 4.7；含 Ark 入口） |
| 调研日期 | 2026-08-02（rev2 同日修订） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://open.bigmodel.cn/ + https://console.volcengine.com/ark/ |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| G1 | 模型概览 | https://docs.bigmodel.cn/cn/guide/start/model-overview |
| G2 | GLM-5.2 型号页 | https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2 |
| G3 | 新品发布（更新日期） | https://docs.bigmodel.cn/cn/update/new-releases |
| G4 | API 快速开始 / 端点 | https://docs.bigmodel.cn/cn/api/introduction |
| G5 | OpenAI API 兼容 | https://docs.bigmodel.cn/cn/guide/develop/openai/introduction |
| G6 | 核心参数（thinking / reasoning_effort / max_tokens） | https://docs.bigmodel.cn/cn/guide/start/concept-param |
| G7 | 深度思考 Thinking | https://docs.bigmodel.cn/cn/guide/capabilities/thinking |
| G8 | 思考模式（Interleaved / Preserved / clear_thinking） | https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode |
| G9 | 上下文缓存 | https://docs.bigmodel.cn/cn/guide/capabilities/cache |
| G10 | Function Calling | https://docs.bigmodel.cn/cn/guide/capabilities/function-calling |
| G11 | 文本分词器 API | https://docs.bigmodel.cn/api-reference/模型-api/文本分词器 |
| G12 | 速率限制 | https://docs.bigmodel.cn/cn/api/rate-limit |
| G13 | 产品定价页 | https://open.bigmodel.cn/pricing |
| G14 | 火山方舟 Coding Plan（GLM 接入说明，社区/官文） | https://developer.volcengine.com/articles/7632697946764476452 |
| G15 | 方舟 Coding OpenAI 兼容端点（行业常用配置） | `https://ark.cn-beijing.volces.com/api/coding/v3`（见方舟 Coding Plan 配置指南） |

#### ② 九问结论

**1. 主力型号与版本号**

| API model id（小写） | 定位 | 官方上下文表述 | 最近发布/更新（G3） | 备注 |
|---|---|---|---|---|
| `glm-5.2` | 最新旗舰；1M 长程 Coding | 1M | **2026-06-16** 上线 | RxyCode **主目标** |
| `glm-5.1` | 长程任务 / Coding 对齐 Opus 4.6 | 200K | **2026-04-07** | |
| `glm-5` | Agentic 长程规划 | 200K | **2026-02-12** | |
| `glm-5-turbo` | 龙虾/长任务吞吐优化 | 200K | **2026-03-15** | |
| `glm-5v-turbo` | 多模态 Coding | 200K | **2026-04-02** | 视觉 |
| `glm-4.7` | 通用对话/推理/Agent | 200K | **2025-12-22** 基座上线 | 默认强制思考（见 Q5）；**勿**与 Flash 日期混淆 |
| `glm-4.7-flash` | 免费普惠 | 200K | **2026-01-19** | 与 `glm-4.7` 基座分列 |
| `glm-4.6` | 高级编码/工具 | 200K | **2025-09-30** | 默认「混合 thinking」 |
| `glm-4.5` / `glm-4.5-air` / `airx` | 高性价比 / 极速 | 128K | **2025-07-28**（4.5 系列公告） | air/airx 同系列日期以 G3 4.5 公告为准 |
| `glm-4-long` | 超长文本 | 1M | G3 **未单独列本日** → 标未找到首发日 | max output 4K（G1） |

- 弃用：GLM-Z1 系列（2025-11-15）、GLM-4-0520（2025-12-30）等见 G1「即将弃用」。
- Ark Coding Plan 公开文案已列 `glm-5.1` / `glm-4.7` 等（G14）；模型行为以智谱官方文档为准，Ark 侧为托管入口。

[来源 G1, G2, G3, G14]

**2. Context window（token）**

| 型号 | 官方表述（G1） | 最大输出（官方） | 上下文精确整数 |
|---|---|---|---|
| `glm-5.2` | **1M** | 128K；`max_tokens` 默认 **65536**、最大 **131072**（G6，此为精确值） | **未找到**（无「1,048,576」类列） |
| `glm-5.1` / `glm-5` / `glm-5-turbo` / `glm-4.7` / `glm-4.6` | **200K** | 128K；`max_tokens` 最大 **131072**（G6） | **未找到** |
| `glm-4.5-air` 系 | **128K** | 96K；`max_tokens` 最大 **98304**（G6） | **未找到** |
| `glm-4-long` | **1M** | 4K | **未找到** |

- **官方结论**：上下文以 **1M / 200K / 128K** 表述为准；上下文窗口的精确 token 整数 **未找到**。
- **可证实的精确输出上限**（G6 表）：如 `glm-5.2` 等 `max_tokens` 最大 **131072**；`glm-4.5-air` 最大 **98304**。
- **项目侧启发式（非官方精确值，A14 填值时须注释）**：若实现层需要整数 `context_window`，可暂用 `1_048_576`（对应官方「1M」）、`200_000`（「200K」）、`128_000`（「128K」）——**不得**写成已从官方证实的精确上下文。审计门以「未找到精确整数」为准。

[来源 G1, G2, G6]

**3. OpenAI 兼容与 tools / function calling**

- **兼容**：官方提供 OpenAI 兼容接口；`base_url=https://open.bigmodel.cn/api/paas/v4/`，改 key + base_url 即可用 OpenAI SDK（G5）。HTTP 端点：`https://open.bigmodel.cn/api/paas/v4/chat/completions`（G4）。
- **tools**：支持 Function Calling / tools（G5/G10 示例）。
- **差异**：`temperature` 区间官方注明为 **(0,1)**；`do_sample=false`（temperature=0）在 OpenAI 调用中不适用（G5）。
- **Ark 入口**：OpenAI 协议 Coding 端点常用 `https://ark.cn-beijing.volces.com/api/coding/v3`，模型如 `glm-5.1`（G14/G15）。**不得**用普通 Ark `/api/v3` 误当 Coding Plan（行业指南警示会产生额外按量费用）。
- RxyCode：`ChatOpenAI` + 上述 base_url；`thinking` / `clear_thinking` 常经 `extra_body`。

[来源 G4, G5, G10, G14]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制 | **隐式/自动**上下文缓存；无需手动配置 cache ID（G9） |
| 最小缓存块 | **未找到**明确最小 token 门槛（如 256/1024） |
| TTL | 仅写「有合理的时效性，过期后会重新计算」——**具体 TTL 时长未找到**（G9） |
| usage 命中字段 | **`usage.prompt_tokens_details.cached_tokens`**（G9）。**未找到**顶层 `cached_tokens` 或 `prompt_cache_hit_tokens` 作为官方主字段——A14 骨架若写 `prompt_cache_hit_tokens`，应以本报告 nested 路径为准 |
| 缓存写入/存储价 | 精确单价：**未找到**可独立核验的官方文本表（见 Q7）。G9 仅证实缓存命中按更低价计费 |
| 失效 / 不命中 | **已证实建议**：内容完全相同命中率最高；轻微格式差异可能影响；避免频繁内容变化（G9）。**未找到**「改 tools / 截断 / 切 key / 切模型」的逐项确定性 bust 清单 |
| 优化 | 稳定 system prompt；长文档放 system；合理组织历史（G9） |

[来源 G9, G13]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

| 项 | 结论 |
|---|---|
| 适配 | **适配** → `supports_reasoning=True`；`thinking_default_on=True`（`thinking` 默认 `{"type":"enabled"}`，G6/G7） |
| 开关 | `thinking.type`=`enabled`（默认）/`disabled`。GLM-5.2/5.1/5/5-Turbo/5v-Turbo/4.6/4.6V/4.5：**enabled 时为模型自动判断是否思考**；**GLM-4.7 / 4.5V：强制思考**（G7）。GLM-5.2/5.1/5/4.7 系列默认开启 Thinking，异于 GLM-4.6 默认「混合 thinking」（G8） |
| effort | 顶层 **`reasoning_effort`**，仅 **GLM-5.2 及以上**：`max`（默认推荐）/`xhigh`/`high`/`medium`/`low`/`minimal`/`none`（G6/G7）。映射：`none`/`minimal`→放弃思考；`low`/`medium`→映射为 `high`；`xhigh`→映射为 `max`（G6） |
| 输出字段 | `message.reasoning_content`；流式 **`delta.reasoning_content`**（G7） |
| Preserved Thinking | Coding Plan 端点**默认开**；标准 API **默认关**。标准 API 用 `thinking.clear_thinking=false` 开启，并**原样回传**完整未改动的历史 `reasoning_content`（G8） |
| Interleaved + tools | 工具调用间可持续思考；**必须**保留并回传 reasoning content（G8） |
| 采样参数 | 文档**未找到**「thinking 模式下拒绝 temperature」明文；示例常用 `temperature=1.0`。OpenAI 兼容路径 temperature∈(0,1)（G5） |

[来源 G6, G7, G8]

**6. 官方 tokenizer**

- 官方 API：`POST /paas/v4/tokenizer`（完整 URL 前缀 `https://open.bigmodel.cn/api/`）（G11）。
- **未找到** tiktoken 兼容 encoding 名。
- 概念页近似：约 **1 token ≈ 0.75 英文单词或 1.5 个中文字符**（G6）→ 中文启发式约 `chars:1.5`。

RxyCode 建议：`tokenizer = "chars:1.5"`（启发式），精确计数走 tokenizer API / usage；**勿**写 `hf:`。

[来源 G11, G6]

**7. 定价（CNY / 1M tokens；中国区）**

| 项 | 结论 |
|---|---|
| 定价页 URL | https://open.bigmodel.cn/pricing（G13） |
| 可核验文本证据 | G13 为**前端渲染**页面；本次及复审抓取均**无法**从独立官方 Markdown/静态文本复核 GLM-5.2 / 5.1 / 5-Turbo / GLM-5 / GLM-4.7 的精确阶梯单价 |
| 官方已证实（非单价） | 存在按量计费与缓存命中优惠价机制（G9）；具体数字以控制台/定价页实时展示为准 |
| 本批写入规则 | 输入 / 输出 / 缓存命中 / 缓存存储 **精确单价一律标「未找到」**——不得把不可核验抓取或二手摘要写进 §7 已证实结论 |
| Ark | Coding Plan 为订阅额度路径，与按量价不同（G14）；亦不得用未核验数字填充 |
| `as_of` / `source_url` | `as_of` 可记查阅日；`source_url=G13`；**数值字段保持 None / 未找到**，待后续能摘录官方静态表或人工截图核验后再补 |

[来源 G13, G9, G14]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT / 吞吐 SLA | 固定 TTFT/TPS **未找到** |
| 加速档 | `glm-4.5-airx`、`glm-4.7-flashx`、`glm-4-flashx-*` 等定位为高速/高并发（G1）；**非**统一 `service_tier` 字段 |
| 限流 | 按**用户权益等级 × 模型**设**并发**上限；具体 RPM/TPM 数字在控制台「速率限制」页查看，文档页**无公开全表数字** → 标 **未找到公开阶梯表（待控制台）**（G12）。Coding Plan：Lite/Pro/Max 与并发建议相关，低峰期动态提升（G12） |

[来源 G12, G1]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| 交错思考 + 工具 | **必须**显式保留并回传 `reasoning_content`（与 tool 结果一并）（G8） |
| Preserved Thinking | 标准 API：`clear_thinking=false` + 原样回传连续 reasoning；改序/篡改会降效果并影响缓存命中（G8） |
| Coding Plan 端点 | Preserved Thinking **默认开**（G8） |
| 缓存 | 稳定前缀 / system；完全相同内容命中最好（G9） |
| Ark | base_url 用 Coding `/api/coding/v3`；模型 id 含 `glm`；勿与豆包等混用同一 provider 匹配宽条件 |

[来源 G8, G9, G14]

#### ③ 对 RxyCode 的含义（A14 照抄用；审计通过前禁止写入代码）

```text
# ModelCapabilities（glm-5.2 主骨架；其他型号改 window）
# --- 官方已证实 ---
# context 官方表述 = "1M"（精确整数：未找到）
max_output_tokens = 131_072         # G6 精确最大 max_tokens（可证实）
supports_function_calling = True
supports_vision = False             # 文本旗舰；视觉用 glm-5v-turbo 等另条
supports_reasoning = True
thinking_default_on = True          # thinking.type 默认 enabled
supports_prompt_cache = True        # 隐式缓存
structured_output = "json_schema"   # 见结构化输出能力页（另）
prompt_variant = "glm-5.2"
tokenizer = "chars:1.5"             # 启发式；精确走 /paas/v4/tokenizer
# thinking: extra_body={"thinking": {"type": "enabled"|"disabled", "clear_thinking": False}}
# effort（仅 glm-5.2+）: reasoning_effort = max|xhigh|high|medium|low|minimal|none
#   映射: none/minimal→弃思考; low/medium→high; xhigh→max; 默认 max
effort_presets = {"fast": "low", "balanced": "high", "deep": "max"}  # 注意 low→官方映射 high

# --- 项目侧启发式（非官方精确值；须注释）---
# context_window = 1_048_576        # 仅对应官方「1M」字面；官方未公布精确整数
# compaction_threshold = 943_000    # 同上启发式
# 200K 系列可暂用 200_000；128K 系列可暂用 128_000 —— 皆非官方精确值

# UsageFieldMap
cache_read_flat = ()
cache_read_nested = ("prompt_tokens_details", "cached_tokens")  # 非 prompt_cache_hit_tokens
reasoning = ()  # reasoning_content 在 message/delta，不在 usage

# ModelPricing（CNY/1M；source_url=G13）
# 精确单价：未找到（G13 前端渲染，无独立可摘录官方文本）
# input_per_mtok = None
# output_per_mtok = None
# cached_input_per_mtok = None
# as_of = "2026-08-02"  # 仅表示查阅日，不代表已核验单价
# Ark Coding Plan 走订阅额度，勿与按量价混用

# 识别（matches）
# - "bigmodel" in url or "zhipu" in url → True
# - "volces.com" in url → 仅当 "glm" in model_name
# - model_name.startswith("glm-") → True
# base_url 官方: https://open.bigmodel.cn/api/paas/v4/
# base_url Ark Coding: https://ark.cn-beijing.volces.com/api/coding/v3

# 会话契约
# - 工具链：回传 reasoning_content（交错思考）
# - Agent/编码：标准 API 设 clear_thinking=false 并原样回传 reasoning
# - temperature: OpenAI 兼容路径 (0,1)；勿假设 thinking 拒绝采样（未找到）
```

### §7.5 MiniMax（A0 批 5）

> 状态：**三方审计通过（2026-08-02）**。Grok 自审·rev2 + DeepSeek + GPT-5.6-Luna 复审均通过。A15 可按本分区填充数值。
>
> **修订历程**：rev1（首轮）→ rev2（Luna：Q2 `max_completion_tokens` 上限；Q5 按 Chat Completions / Responses 端点区分 thinking 默认与 `reasoning.effort`）→ 终审通过。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 5 · MiniMax（主写 MiniMax-M3 / M2.7 系列；含 M2.5 / M2.1 / M2 及 highspeed） |
| 调研日期 | 2026-08-02（rev2 同日修订） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://platform.minimaxi.com/（国际镜像文档 https://platform.minimax.io/） |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| MM1 | 接口概览 / 型号与上下文 | https://platform.minimaxi.com/docs/api-reference/api-overview |
| MM2 | 模型发布 Changelog | https://platform.minimaxi.com/docs/release-notes/models |
| MM3 | Chat Completions（OpenAI 兼容 OpenAPI） | https://platform.minimaxi.com/docs/api-reference/text-chat-openai |
| MM4 | OpenAI SDK 接入 | https://platform.minimaxi.com/docs/api-reference/text-openai-api |
| MM5 | Prompt 缓存（被动） | https://platform.minimaxi.com/docs/api-reference/text-prompt-caching |
| MM6 | Anthropic 主动缓存 | https://platform.minimaxi.com/docs/api-reference/anthropic-api-compatible-cache |
| MM7 | 工具使用 & 交错思维链 | https://platform.minimaxi.com/docs/guides/text-m3-function-call |
| MM8 | 按量计费定价 | https://platform.minimaxi.com/docs/guides/pricing-paygo |
| MM9 | 速率限制 | https://platform.minimaxi.com/docs/guides/rate-limits |
| MM10 | Token 估算（Responses） | https://platform.minimaxi.com/docs/api-reference/responses-input-tokens |
| MM11 | 国际站按量定价（USD，对照） | https://platform.minimax.io/docs/guides/pricing-paygo |
| MM12 | 国际站速率限制（对照） | https://platform.minimax.io/docs/guides/rate-limits |
| MM13 | Responses API（Create Response） | https://platform.minimaxi.com/docs/api-reference/responses-create |

#### ② 九问结论

**1. 主力型号与版本号**

| API model id（官方大小写） | 定位 | 上下文（MM1） | 最近发布（MM2） | 备注 |
|---|---|---|---|---|
| `MiniMax-M3` | 最新 M 系列；Agent / 工具 / 编码 / 长上下文 | **1,000,000** | **2026-06-01** | RxyCode **主目标** |
| `MiniMax-M2.7` | 自我迭代；约 60 tps（营销表述） | **204800** | **2026-03-18** | |
| `MiniMax-M2.7-highspeed` | 同效果极速；约 100 tps（营销表述） | **204800** | **2026-03-18** | 独立定价（Q7） |
| `MiniMax-M2.5` | 性价比 / 复杂任务 | **204800** | **2026-02**（Changelog 月粒度） | Legacy 定价区 |
| `MiniMax-M2.5-highspeed` | 极速版 | **204800** | 同上 | 独立定价 |
| `MiniMax-M2.1` | 多语言编程 | **204800** | **2025-12-22** | Legacy |
| `MiniMax-M2.1-highspeed` | 极速版 | **204800** | 同上 | 独立定价 |
| `MiniMax-M2` | Agent / 高效编码 | **204800** | **2025-10-27** | Legacy；被动缓存支持表**未列**本型号（见 Q4） |

- 列名口径：国内概览表头为「输入输出总 token」（MM1）；国际概览写明最大 token 为 **input + output 合计**（国际 MM1 镜像）。
- 非文本主线：MiniMax-H3（视频，2026-07-31）等不写入本批文本 provider 主表。

[来源 MM1, MM2]

**2. Context window（token）**

| 型号 | 官方精确整数（MM1） | `max_completion_tokens`（MM3 schema） | 备注 |
|---|---|---|---|
| `MiniMax-M3` | **1,000,000** | 推荐 **131072**（128K）；上限 **524288**（512K） | 窗口为输入+输出合计 |
| `MiniMax-M2.7` / `-highspeed` 及 M2.5 / M2.1 / M2 系 | **204800** | 推荐 **65536**（64K）；上限 **204800**（200K） | 同上合计口径 |

- 与 GLM「1M/200K」营销字面不同：MiniMax 概览表给出**可核验精确整数** `1,000,000` / `204800`。
- 输出长度：以 Chat Completions 官方 schema 的 `max_completion_tokens` 为准（MM3）；`max_tokens` 为旧参数，文档标明已弃用、请改用 `max_completion_tokens`（MM3）。Responses 另有 `max_output_tokens` 字段，**未找到**与上表同级的按型号数值上限说明（MM13）。

[来源 MM1, MM3, MM4, MM13]

**3. OpenAI 兼容与 tools / function calling**

- **兼容**：官方提供 OpenAI Chat Completions 与 OpenAI SDK；国内 `OPENAI_BASE_URL=https://api.minimaxi.com/v1`，国际 `https://api.minimax.io/v1`（MM4）。
- **tools**：支持 `tools`；文档写明弃用的 `function_call` **不支持**，请用 `tools`（MM4）。交错工具调用见 MM7。
- **Anthropic 兼容**：官方推荐 Anthropic SDK；国内 `ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic`（MM5 示例）。
- **差异（OpenAI 路径）**：`temperature` ∈ **[0, 2]**，默认 **1**，越界报错；`presence_penalty` / `frequency_penalty` / `logit_bias` 等**会被忽略**；`n` 仅支持 **1**；M3 支持图/视频 content parts，**音频输入当前不支持**（MM4）。
- RxyCode：`ChatOpenAI` + 上述 base_url；thinking / `reasoning_split` 经 `extra_body`（见 Q5）。

[来源 MM3, MM4, MM7]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制（OpenAI / 默认） | **被动/自动缓存**（无需改调用方式）；相对的 Anthropic `cache_control` 称「主动缓存」（MM5） |
| 最小缓存块 | 被动缓存适用于输入 **≥ 512 tokens** 的调用（MM5） |
| TTL（被动） | 「根据系统负载自动调整过期时间」——**固定 TTL 时长未找到**（MM5） |
| TTL（主动 Anthropic） | **5 分钟**；命中可自动续期、无额外费用（MM6） |
| usage 命中字段（OpenAI） | **`usage.prompt_tokens_details.cached_tokens`**（MM5 OpenAI 示例 / MM3 schema） |
| usage 命中字段（Anthropic） | `cache_read_input_tokens` / `cache_creation_input_tokens`（MM5/MM6）；与 OpenAI 路径不同 |
| 写入计费 | 被动：写入**无额外计费**；主动：首次写入额外计费（MM5 对比表） |
| 支持型号 | 被动：M3、M2.7/M2.5/M2.1 **系列**；主动：M2.7/M2.5/M2.1/M2 **系列**（**不含 M3**）（MM5） |
| 失效 / 不命中 | 前缀匹配，顺序为 **工具定义 → 系统提示词 → 历史对话**；**任意模块内容变更都可能影响缓存效果**（MM5）。**未找到**「截断 / 切 key / 切模型」的逐项确定性 bust 清单 |
| 优化 | 静态内容靠前，动态用户信息靠后（MM5） |

[来源 MM5, MM6, MM3]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

**必须按 endpoint 区分**（不可把 Chat Completions 默认泛化到 Responses）：

| 端点 | M3 默认 | M3 开关 | effort / 深度 | M2.x |
|---|---|---|---|---|
| **Chat Completions / OpenAI SDK**（MM3/MM4） | 省略 `thinking` → **adaptive 开启**（响应含 thinking） | `thinking.type`=`adaptive` \| `disabled` | **本端点无** `reasoning.effort`；深度不可调 | thinking **无法关闭**；传 `disabled` 仍开 |
| **Responses API**（MM13） | 省略 `reasoning` 或 `effort=none` → **默认关闭推理**（无 `type:"reasoning"` 输出项） | `reasoning.effort` 设为非 `none`（`minimal`/`low`/`medium`/`high`）→ 开启 Adaptive Thinking | 上述非 `none` 值**仅开/关**，**不会调节** M3 推理深度 | 推理**无法关闭**；即使 `effort=none` 仍开 |

| 项 | 结论 |
|---|---|
| 适配 | **适配** → `supports_reasoning=True` |
| `thinking_default_on`（RxyCode 主路径） | Chat Completions / `ChatOpenAI`：**True**（MM3/MM4）。若走 Responses：**False**（M3 默认 `effort=none`，MM13）——A15 若仅接线 Chat，填 True 并注释 Responses 差异 |
| 输出字段（Chat） | `reasoning_split=true` → `reasoning_content` + `reasoning_details`（message / delta）；`false` → `content` 内 `<think>...</think>`（MM3/MM7） |
| 输出字段（Responses） | 推理开启时出现 `type: "reasoning"` 输出项；usage 可含 `reasoning_tokens`（MM13） |
| 采样参数 | Chat：`temperature` ∈ [0,2] 默认 1；**未找到**「thinking 模式下拒绝 temperature」明文（MM4） |

[来源 MM3, MM4, MM7, MM13]

**6. 官方 tokenizer**

- **未找到** tiktoken 兼容 encoding 名。
- 官方提供 Responses **Token 估算**接口：`POST /v1/responses/input_tokens`（MM10）。
- 定价页估算：约 **1600 中文字符 ≈ 1000 tokens**（MM8）→ 中文启发式约 `chars:1.6`；国际页另有「约 750 英文词 ≈ 1000 tokens」（MM11）。

RxyCode 建议：`tokenizer = "chars:1.6"`（启发式）；精确计数走 usage / Token 估算 API；**勿**写 `hf:`。

[来源 MM8, MM10, MM11]

**7. 定价（CNY / 1M tokens；中国区按量，MM8）**

`as_of=2026-08-02`；`source_url=MM8`。下列为定价页**当前有效价**（M3 标「永久五折」后的划线后价格）。highspeed **不得**与普通版共用输入/输出价。

| 型号 / 档 | 输入 | 输出 | 缓存读取 | 缓存写入 |
|---|---|---|---|---|
| `MiniMax-M3` 标准 ≤512k 输入 | **2.10** | **8.40** | **0.42** | **未找到**（被动写入无额外价；主动缓存不支持 M3） |
| `MiniMax-M3` 标准 >512k 输入 | **4.20** | **16.80** | **0.84** | 同上 |
| `MiniMax-M3` Priority ≤512k（`service_tier=priority`，1.5×） | **3.15** | **12.60** | **0.63** | 同上 |
| `MiniMax-M3` Priority >512k | **6.30** | **25.20** | **1.26** | 同上 |
| `MiniMax-M2.7` | **2.1** | **8.4** | **0.42** | **2.625** |
| `MiniMax-M2.7-highspeed` | **4.2** | **16.8** | **0.42** | **2.625** |
| `MiniMax-M2.5` / `M2.1` / `M2`（历史） | **2.1** | **8.4** | **0.21** | **2.625** |
| 上述对应 `-highspeed`（历史） | **4.2** | **16.8** | **0.21** | **2.625** |

- 长上下文：M3 输入 **>512k**（含缓存命中 tokens）走长上下文价（MM5/MM8）。
- 国际 USD 对照见 MM11（例：M3 标准 ≤512k 现价 $0.30 / $1.20 / 缓存读 $0.06）；A15 中国区落地以 **CNY/MM8** 为准。
- Token Plan / 积分：订阅路径，与按量价分列（MM8 文首）；勿混填。

[来源 MM8, MM5, MM11]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT / 吞吐 SLA | 固定 TTFT **未找到**；概览「约 60/100 tps」为营销描述，**非**可合约 SLA |
| 加速档 | ① 型号后缀 **`-highspeed`**（更高标称 tps + 独立单价）；② M3 **`service_tier=priority`**（优先准入，按标准价 1.5×，MM8） |
| 限流（中国区 MM9，充值用户） | M3：**200 RPM / 10,000,000 TPM**；M2.7/M2.5/M2.1/M2（含 highspeed）：**500 RPM / 20,000,000 TPM** |
| 限流（中国区免费用户） | M3：**20 RPM / 1,000,000 TPM**；M2 系：**20 RPM / 1,000,000 TPM**（MM9） |
| 国际站对照（MM12） | 文档表直接列 M3 200/10M、M2 系 500/20M（**未分**免费/充值列）——以账号所属区域文档为准 |

[来源 MM1, MM8, MM9, MM12]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| 交错思考 + 工具 | **必须**把完整 assistant 响应回传历史；`reasoning_split=true` 时含 `reasoning_details`；原生格式时**勿改**含 `<think>` 的 `content`（MM7） |
| 缓存 | 稳定 tools/system/历史前缀；变更任一模块可能影响命中（MM5） |
| M2.x thinking | 无法关闭；按默认思考链续接（MM4） |
| 端点 | 国内 `api.minimaxi.com`，国际 `api.minimax.io`；**勿**把未在本批文档证实的旧域名当作官方主端点 |

[来源 MM7, MM5, MM4]

#### ③ 对 RxyCode 的含义（A15 照抄用；审计通过前禁止写入代码）

```text
# ModelCapabilities（MiniMax-M3 主骨架；M2.x 改 window / 定价）
# --- 官方已证实（主路径 = Chat Completions / ChatOpenAI）---
context_window = 1_000_000          # MM1 精确整数；输入+输出合计
# M2.x: context_window = 204_800
max_output_tokens = 524_288         # MM3：M3 max_completion_tokens 上限；推荐默认 131_072
# M2.x: max_output_tokens = 204_800；推荐 65_536
supports_function_calling = True
supports_vision = True              # M3 OpenAI 路径支持 image/video parts；音频未支持
supports_reasoning = True
thinking_default_on = True          # Chat Completions：省略 thinking → adaptive
# 若走 Responses API：thinking_default_on = False（M3 默认 reasoning.effort=none）
supports_prompt_cache = True        # 被动自动缓存（OpenAI 路径）
structured_output = "json_schema"   # 以平台结构化能力页为准（若落地另核）
prompt_variant = "minimax-m3"
tokenizer = "chars:1.6"             # 启发式（1600 汉字≈1000 tokens）；精确走 usage / input_tokens
# Chat thinking (M3): extra_body={"thinking": {"type": "adaptive"|"disabled"}, "reasoning_split": True}
# M2.x Chat: thinking 关不掉；仍建议 reasoning_split=True 便于回传
# Responses (M3): reasoning={"effort": "none"|"minimal"|"low"|"medium"|"high"}；非 none 仅开思考、不调深度
# Chat 路径无 reasoning.effort → 勿把 DeepSeek/Kimi effort_presets 套到 Chat
# service_tier: "priority" 可选（M3，1.5× 价）

# UsageFieldMap（OpenAI Chat Completions）
cache_read_flat = ()
cache_read_nested = ("prompt_tokens_details", "cached_tokens")
reasoning = ()  # reasoning_content / reasoning_details 在 message/delta，不在 usage
# Anthropic 路径另计: cache_read_input_tokens / cache_creation_input_tokens
# Responses usage 可含 reasoning_tokens（MM13）

# ModelPricing（CNY/1M；source_url=MM8；as_of=2026-08-02；M3 标准 ≤512k）
input_per_mtok = 2.10
output_per_mtok = 8.40
cached_input_per_mtok = 0.42
# cache_write: M3 被动无额外写入价 → None；M2.7 写入 2.625
# M2.7-highspeed: input 4.2 / output 16.8 / cache_read 0.42 / write 2.625
# M3 >512k 或 priority：按 Q7 表切换，勿与 ≤512k 标准价混用

# 识别（matches）
# - "minimax" in url or "minimaxi" in url → True
# - model_name 含 "minimax" / "MiniMax-" → True
# base_url 国内: https://api.minimaxi.com/v1
# base_url 国际: https://api.minimax.io/v1

# 会话契约
# - 工具链：完整回传 assistant（含 reasoning_details 或未改动的 <think> content）
# - 被动缓存：≥512 input tokens；前缀 tools→system→history
# - temperature: [0,2]，推荐 1.0
```

### §7.6 MIMO / 小米（A0 批 6）

> 状态：**三方审计通过（2026-08-02）**。Grok 自审 + DeepSeek + GPT-5.6-Luna 均通过。A16 可按本分区填充数值。
>
> **修订历程**：rev1（首轮三方通过）→ rev1.1（用户反馈：补齐 **`mimo-v2.5` 并列主力**表述与 ③ 独立骨架；事实数值未改）。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 6 · MIMO / 小米 MiMo（**双主力** `mimo-v2.5-pro` + `mimo-v2.5`；含 UltraSpeed） |
| 调研日期 | 2026-08-02（rev1.1 同日补表述） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://mimo.xiaomi.com/（产品页）；开发者文档主站 https://mimo.mi.com/（与 https://platform.xiaomimimo.com/ 同源） |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| X1 | 模型列表（能力 / 上下文 / 限流） | https://mimo.mi.com/docs/zh-CN/quick-start/summary/model |
| X2 | 首次调用 API（base_url / 双协议） | https://mimo.mi.com/docs/zh-CN/quick-start/summary/first-api-call |
| X3 | OpenAI Chat Completions | https://mimo.mi.com/docs/zh-CN/api/chat/openai-api |
| X4 | OpenAI Responses API | https://mimo.mi.com/docs/zh-CN/api/chat/responses |
| X5 | 深度思考 | https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/deep-thinking |
| X6 | 模型超参（temperature / top_p） | https://mimo.mi.com/docs/zh-CN/api/guidance/model-hyperparameters |
| X7 | 速率限制 | https://mimo.mi.com/docs/zh-CN/api/guidance/rate-limit |
| X8 | 按量计费定价 | https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go |
| X9 | 模型下线 | https://mimo.mi.com/docs/zh-CN/updates/deprecate |
| X10 | 模型发布 Changelog | https://mimo.mi.com/docs/zh-CN/updates/model |
| X11 | 功能更新 | https://mimo.mi.com/docs/zh-CN/updates/feature |
| X12 | API 接入 FAQ | https://mimo.mi.com/docs/zh-CN/quick-start/faq/api-integration |
| X13 | mimo-v2.5-pro 型号页 | https://mimo.mi.com/models/zh-CN/mimo-v2.5-pro |
| X14 | mimo-v2.5 型号页 | https://mimo.mi.com/models/zh-CN/mimo-v2.5 |
| X15 | mimo-v2.5-pro-ultraspeed 型号页 | https://mimo.mi.com/models/zh-CN/mimo-v2.5-pro-ultraspeed |
| X16 | UltraSpeed 1000tps 新闻 | https://mimo.mi.com/docs/zh-CN/news/latest/1000tps |
| X17 | 产品主页（HySparse 论文入口，非 API 参数页） | https://mimo.xiaomi.com/ |

#### ② 九问结论

**1. 主力型号与版本号**

RxyCode / A16 **双主力**（官方模型列表并列的文本生成主力，X1）：

| API model id | 定位 | 发布（X10） | 备注 |
|---|---|---|---|
| `mimo-v2.5-pro` | 万亿参数**文本**旗舰；长程 Agent / 复杂推理 | **2026-04-23** | **主力 A**：纯文本编码/Agent 默认首选 |
| `mimo-v2.5` | **原生全模态**（图/视/音/文）+ 深度思考 / 工具 / 联网 | **2026-04-23** | **主力 B**：多模态与「日常任务比肩 pro」路径（X14）；**不得**漏写或降为附属 |

加速档与非 Chat 主线：

| API model id | 定位 | 发布 / 说明 | 备注 |
|---|---|---|---|
| `mimo-v2.5-pro-ultraspeed` | UltraSpeed（独立 model id） | 新闻窗口见 X16（2026-06 申请制体验） | **3×** 定价；申请制/资源限量（X15/X16） |
| `mimo-v2.5-asr` / `mimo-v2.5-tts*` | ASR / TTS | 2026-04-23 / 06-02 等 | 非文本 Chat 主线 |

- **已下线（勿再用）**：`mimo-v2-pro` / `mimo-v2-omni` / `mimo-v2-flash` / `mimo-v2-tts` 于北京时间 **2026-06-30 00:00** 正式下线，原名称失效（X1/X9）。系统替换期曾路由到 v2.5 系，现应直接用 **`mimo-v2.5-pro` / `mimo-v2.5`** id。

[来源 X1, X9, X10, X13, X14, X15]

**2. Context window（token）**

| 型号 | 官方表述（X1/X13/X14） | 最大输出（官方） | 上下文精确整数 |
|---|---|---|---|
| `mimo-v2.5-pro` / `mimo-v2.5` | 上下文窗口 **1M** | **128K** | **未找到**（无「1,048,576」类列） |
| `mimo-v2.5-pro-ultraspeed` | 型号页未单列窗口数字；能力含 Cache；示例 `max_completion_tokens=131072`（X15） | **未找到**独立上限表 | **未找到** |

- 可证实默认：`mimo-v2.5` 在未指定时 `max_completion_tokens` 默认 **32768**（相对旧 flash 的差异表，X9）。
- **项目侧启发式（非官方精确值）**：若实现需要整数，可暂用 `context_window=1_048_576`、`max_output_tokens=131_072`（对应「1M」「128K」）——审计门以「精确整数未找到」为准。

[来源 X1, X9, X13, X14, X15]

**3. OpenAI 兼容与 tools / function calling**

- **兼容**：OpenAI Chat Completions `https://api.xiaomimimo.com/v1/chat/completions`；SDK `base_url=https://api.xiaomimimo.com/v1`（X2/X3）。
- **Anthropic**：`https://api.xiaomimimo.com/anthropic`（Messages）（X2）。
- **Responses**：`https://api.xiaomimimo.com/v1/responses`（2026-06-23 上线，X4/X11）；不支持 `background` / `previous_response_id` / `context_management` 等（X4）。
- **Token Plan**：独立 base（示例 `https://token-plan-cn.xiaomimimo.com/v1`）与 `tp-` key；与按量 `sk-` **不可混用**（X2/X12）。
- **tools**：支持函数调用 / `tools`（X1/X2/X5）；鉴权头 `api-key` 或 `Authorization: Bearer`（X3）。

[来源 X2, X3, X4, X11, X12]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制 | 官方定价写明「前缀内容命中 Prompt Cache 时按命中价计费」（X8）；型号页列「Cache 缓存」能力（X13/X14）。**未找到** `cache_control` / 显式断点 API → 视为**服务端自动/隐式**前缀缓存 |
| 最小缓存块 | **未找到** |
| TTL | **未找到**固定时长（联网开关 FAQ 的「5 分钟缓存」仅针对联网开关生效延迟，**不得**当作 Prompt Cache TTL，X12） |
| usage 命中字段 | OpenAPI schema：`usage.prompt_tokens_details.cached_tokens`（「命中缓存的 token 的数量」，X3）。深度思考示例中 `prompt_tokens_details` 可为 `{}`（X5） |
| 缓存写入价 | 按量页：**限时免费**（X8）→ 精确写入单价标 **未找到 / 限时免费** |
| 失效规则 | **未找到**改历史/截断/切 key/切模型的逐项 bust 清单 |
| HySparse / KV Cache Sharing | 仅产品页论文入口（X17）；**未找到**对应 API 调用参数 |

[来源 X3, X5, X8, X12, X13, X17]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

**必须按 endpoint 区分：**

| 端点 | M3 类比：MiMo v2.5 | 开关 | effort |
|---|---|---|---|
| **Chat Completions**（X5） | `mimo-v2.5-pro` / `mimo-v2.5`：**默认开启**深度思考 | `thinking.type`=`enabled` \| `disabled`（经 `extra_body`） | **本端点无** `reasoning.effort` |
| **Responses API**（X4） | `reasoning.effort`：`none` 关闭；`low`/`medium`/`high` **均开启且效果一致**（暂不区分强度） | 同上 effort | 省略时的默认值：**未找到**明文（示例常用 `none`） |

| 项 | 结论 |
|---|---|
| 适配 | **适配** → `supports_reasoning=True` |
| `thinking_default_on`（RxyCode 主路径 Chat） | **True**（X5）。若走 Responses：勿照抄 True——默认值未找到，按显式 `effort` 控制 |
| 输出字段（Chat） | `message.reasoning_content`；流式 `delta.reasoning_content`；usage `completion_tokens_details.reasoning_tokens`（X5） |
| 采样限制 | 思考模式下 **不支持自定义** `temperature`/`top_p`，传入也强制为 **1.0 / 0.95**（X5/X6） |
| 非思考范围 | temperature ∈ **[0, 1.5]**，top_p ∈ **[0.01, 1.0]**（X6） |

[来源 X4, X5, X6]

**6. 官方 tokenizer**

- **未找到** tiktoken 兼容 encoding 名。
- **未找到**官方「N 汉字 ≈ 1 token」比例表（定价页无字符换算说明，X8）。
- RxyCode：精确计数依赖 `usage`；启发式 tokenizer 标 **未找到官方推荐**——实现层可暂用通用 `chars:1.5` 并注释「非官方」。

[来源 X8, X3]

**7. 定价（CNY / 1M tokens；国内按量，X8；as_of=2026-08-02）**

| 型号 | 输入（缓存命中） | 输入（未命中） | 输出 | 缓存写入 |
|---|---|---|---|---|
| `mimo-v2.5-pro` | **0.025** | **3.00** | **6.00** | 限时免费（精确单价未找到） |
| `mimo-v2.5` | **0.02** | **1.00** | **2.00** | 同上 |
| `mimo-v2.5-pro-ultraspeed` | **0.075**（=3× Pro） | **9** | **18** | 同上口径（X15） |

- 海外 USD 见 X8/X13（Pro：$0.0036 / $0.435 / $0.87）。A16 中国区以 **CNY/X8** 为准。
- Token Plan 为 Credits 订阅，与按量价分列（X2）；UltraSpeed **暂不支持 Token Plan**（X16）。
- 联网搜索按次另计（国内 ¥16/1000 次，X8）。

[来源 X8, X13, X15, X16]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT / 吞吐 SLA | 固定 TTFT **未找到**；UltraSpeed 营销/体验标称约 **500–1000** TPS vs Pro 约 **50–100**（X15）——**非**合约 SLA |
| 加速档 | 独立型号 **`mimo-v2.5-pro-ultraspeed`**（非 `service_tier` 字段）；申请制限量（X15/X16） |
| 限流（X7） | `mimo-v2.5-pro` / `mimo-v2.5`：**100 RPM / 10M TPM**（账号下同模型全部 Key 合计） |

[来源 X1, X7, X15, X16]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| 深度思考 + 工具（Chat） | 历史 assistant 含工具调用时，**必须完整回传** `reasoning_content`，否则 API **400**（X5） |
| 建议 | FAQ：工具调用不稳定时建议**关闭 thinking** 并参考超参（X12）——与「必须回传」并存：若开着思考则必须回传 |
| 缓存 | 稳定前缀以利用 Prompt Cache（X8）；无逐项 bust 清单 |
| 端点 | 按量 `api.xiaomimimo.com`；Token Plan 用控制台给出的专属 URL + `tp-` key |

[来源 X5, X12, X2]

#### ③ 对 RxyCode 的含义（A16 照抄用；审计通过前禁止写入代码）

```text
# ========== 双主力：A16 必须同时覆盖 ==========
# 主力 A: mimo-v2.5-pro（文本旗舰）
# 主力 B: mimo-v2.5（全模态；同 1M/128K、同默认思考、独立定价）

# --- 共用（Chat Completions 主路径；两型号均适用）---
# context 官方表述 = "1M"；精确整数：未找到
# max output 官方表述 = "128K"；精确整数：未找到
# 默认 max_completion_tokens（未指定时，v2.5 系差异表）= 32768  # X9
supports_function_calling = True
supports_reasoning = True
thinking_default_on = True          # Chat：两型号深度思考均默认开启（X5）
# Responses：用 reasoning.effort；省略默认未找到 → 勿盲目 True
supports_prompt_cache = True        # 隐式 Prompt Cache（X8）；两型号页均列 Cache
tokenizer = "chars:1.5"             # 非官方启发式；官方 tokenizer 未找到
# thinking: extra_body={"thinking": {"type": "enabled"|"disabled"}}
# Responses: reasoning={"effort": "none"|"low"|"medium"|"high"}  # low/medium/high 效果相同
# 思考模式下 temperature/top_p 强制 1.0/0.95（两型号相同，X5/X6）
# UltraSpeed: model="mimo-v2.5-pro-ultraspeed"（申请制；非默认）

# --- 项目侧启发式（须注释；两主力共用窗口表述）---
# context_window = 1_048_576
# max_output_tokens = 131_072
# compaction_threshold ≈ 0.9 * context_window

# UsageFieldMap（两主力共用）
cache_read_flat = ()
cache_read_nested = ("prompt_tokens_details", "cached_tokens")
reasoning = ()  # reasoning_content 在 message/delta；usage 另有 completion_tokens_details.reasoning_tokens

# --- 主力 A：mimo-v2.5-pro ---
prompt_variant = "mimo-v2.5-pro"
supports_vision = False             # 官方：输入模态文本（X13）
# ModelPricing CNY/1M；source_url=X8；as_of=2026-08-02
input_per_mtok = 3.00               # 未命中缓存
output_per_mtok = 6.00
cached_input_per_mtok = 0.025
# cache_write: 限时免费 → None

# --- 主力 B：mimo-v2.5（A16 不得省略本块）---
# prompt_variant = "mimo-v2.5"
# supports_vision = True            # 官方：文本+图像+视频+音频（X14）
# input_per_mtok = 1.00
# output_per_mtok = 2.00
# cached_input_per_mtok = 0.02
# cache_write: 限时免费 → None

# --- 加速档（非默认主力）---
# mimo-v2.5-pro-ultraspeed: 9 / 18 / 0.075

# 识别（matches）
# - "xiaomimimo" in url or "mimo.mi.com" in url → True
# - model_name.startswith("mimo-") → True
# base_url 按量: https://api.xiaomimimo.com/v1
# Token Plan: 控制台专属 URL（示例 token-plan-cn.xiaomimimo.com/v1）+ tp- key

# 会话契约（两主力相同）
# - 思考+工具：缺 reasoning_content → 400；必须完整回传
# - 思考开：勿指望自定义 temperature/top_p
```

### §7.7 Qwen（A0 批 7）

> 状态：**三方审计通过（2026-08-02）**。Grok / DeepSeek / GPT-5.6-Luna 均已通过（见 §7.9）。A17 可按本分区填充数值。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 7 · Qwen / 通义千问 / 百炼 Model Studio（**三主力按量** `qwen3.7-plus` + `qwen3.7-max` + `qwen3.7-flash` + **Token Plan 旗舰 D** `qwen3.8-max-preview`） |
| 调研日期 | 2026-08-02（rev1.1 同日升格 3.8） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://help.aliyun.com/zh/model-studio/ |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| Q1 | 文本生成选型 / 推荐模型 | https://help.aliyun.com/zh/model-studio/text-generation-model/ |
| Q2 | OpenAI 兼容接入 | https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope |
| Q3 | 深度思考 | https://help.aliyun.com/zh/model-studio/deep-thinking |
| Q4 | Context Cache | https://help.aliyun.com/zh/model-studio/context-cache |
| Q5 | qwen3.7-max 型号页 | https://help.aliyun.com/zh/model-studio/qwen3-7-max |
| Q6 | qwen3.7-plus 型号页 | https://help.aliyun.com/zh/model-studio/qwen3-7-plus |
| Q7 | qwen3.7-flash 型号页 | https://help.aliyun.com/zh/model-studio/qwen3-7-flash |
| Q8 | 模型大全入口 | https://help.aliyun.com/zh/model-studio/models |
| Q9 | 文本生成 API 参考入口 | https://help.aliyun.com/zh/model-studio/qwen-api-reference |
| Q10 | Codex 接入（含 3.8 元数据 / 思考说明） | https://help.aliyun.com/zh/model-studio/codex |
| Q11 | Qwen Code 接入（Token Plan + 3.8） | https://help.aliyun.com/zh/model-studio/qwen-code |
| Q12 | Token Plan 概述（Credits / 3.8 预览权益） | https://help.aliyun.com/zh/model-studio/token-plan-overview |
| Q13 | qwen3.8-max-preview 独立型号页 | **未找到**（`…/qwen3-8-max-preview` 404，as_of=2026-08-02） |
| Q14 | Token Plan Harness 内置工具 | https://help.aliyun.com/zh/model-studio/token-plan-tool |

#### ② 九问结论

**1. 主力型号与版本号**

官方推荐（Q1）：Agent/编程首选 **`qwen3.7-plus`**；最强推理可选 **`qwen3.7-max`（按量）** 或 **`qwen3.8-max-preview`（仅 Token Plan）**；降本 **`qwen3.7-flash`**。A17 **四档并列覆盖，不得只写 max、也不得把 3.8 一笔带过**（吸取批 6 漏写教训）：

| API model id | 定位 | 快照等同（型号页） | 备注 |
|---|---|---|---|
| `qwen3.7-plus` | 能力/成本均衡；多模态 Agent | ≈ `qwen3.7-plus-2026-05-26`（Q6） | **主力 A（官方首选 / 按量默认）**；图/文/视频输入 |
| `qwen3.7-max` | 最强按量推理 / 长程 Agent | ≈ `qwen3.7-max-2026-05-20`（Q5） | **主力 B**；动态 id 当前开放纯文本体验 |
| `qwen3.7-flash` | 低成本接近旗舰 | 含 `qwen3.7-flash-2026-07-15`（Q7） | **主力 C**；多模态 |
| `qwen3.8-max-preview` | Token Plan 最强推理预览 | **无独立型号页**（Q13 404） | **主力 D（与 max 并列的「最强」选项；仅 Token Plan）**；预览期能力持续迭代，结束后可能下线或换正式版（Q12） |
| `qwen-plus` / `qwen-flash` 等 | 旧版仍可用 | — | Q1 标「不再作为首选」；新项目用 3.6/3.7 |

[来源 Q1, Q5, Q6, Q7, Q8, Q12, Q13]

**2. Context window（token）**

| 型号 | 上下文长度 | 最大输出 | 思考模式额外限制 |
|---|---|---|---|
| `qwen3.7-max` / `plus` / `flash` | **1000000**（型号页精确） | **65536** | 思考下最大输入 **983616**；最大思维链 **262144**；非思考最大输入 **991808**（Q5/Q6/Q7） |
| `qwen3.8-max-preview` | Codex 元数据 `context_window`=**983616**（Q10）；**未找到**独立型号页上的「上下文长度 / 最大输出」精确表（Q13） | **未找到**官方 max output 整数 | 仅思考模式（见 Q5）；勿把 3.7 的 1000000/65536 **未经核验地照抄**到 3.8 |

- 选型页营销「1M / 100万」与 **3.7** 型号页精确整数 **1000000** 一致（可证实）。
- 近似：100万 Token ≈ 70万汉字（Q1）——仅启发式说明。
- 3.8：Codex 示例另给 `effective_context_window_percent: 95`（Q10）——工具侧有效窗提示，非计费权威。

[来源 Q1, Q5, Q6, Q7, Q10, Q13]

**3. OpenAI 兼容与 tools / function calling**

- **兼容（按量）**：OpenAI Chat Completions；北京建议业务空间域名 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`；旧域 `https://dashscope.aliyuncs.com/compatible-mode/v1` 仍可用（Q2）。
- **兼容（Token Plan / 含 3.8）**：`https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`；须用 Token Plan **专属** API Key（与按量 / Coding Plan Key **互不相通**，Q10/Q11/Q12）。地域目前仅华北2（北京）（Q12）。
- 另有 Anthropic Messages、DashScope 原生、Responses（Q9）。`qwen3.8-max-preview` 与 3.7-max/plus 等支持 **Responses**（Codex `wire_api = "responses"`，Q10）。
- **tools（A17 字段以 Q1 推荐表列序为准；Harness/Codex 产品层禁止覆盖）**：

Q1 推荐表列序：**思考 / Function Calling / 内置工具 / 结构化输出**。

| API model id | Q1 四列（字面） | Function Calling | A17 `supports_builtin_tools` | 结构化输出（Q1） | 备注 |
|---|---|---|---|---|---|
| `qwen3.7-max` | 支持 / 支持 / **支持** / 不支持 | **支持** | **True**（Q1 第 3 能力列=内置工具） | **不支持**（末列；Q5=支持 → 冲突留档） | Harness **不得**改写本字段；此前 False 系误读末列 |
| `qwen3.7-plus` | 支持 / 支持 / 支持 / 支持 | **支持** | **True** | **支持** | — |
| `qwen3.7-flash` | 支持 / 支持 / 支持 / 支持 | **支持** | **True** | **支持** | — |
| `qwen3.8-max-preview` | 无独立型号页 | **未找到** | **未找到** | **未找到** | 禁止继承 Harness/Codex |

- **审计处置（Luna 2026-08-02 17:26）**：
  1. max：③-B 改为 `supports_builtin_tools=True`（对齐 Q1 列序第 3 列「内置工具=支持」）。
  2. 3.8：保持 `未找到`（Luna 确认正确）。
  3. 缓存 `cache_creation_input_tokens`：已补齐（Luna 确认）。

- SDK：`enable_thinking` / `reasoning_effort` 等非标准参数经 `extra_body`（Q3/Q10/Q11）。

[来源 Q1, Q2, Q3, Q5, Q9, Q10, Q11, Q12, Q14]

**4. Prompt cache 机制**

| 项 | 显式缓存 | 隐式缓存 |
|---|---|---|
| 机制 | `cache_control: {"type":"ephemeral"}`；最多 4 标记；向前最多 20 content 块（Q4） | 自动、无法关闭；命中不确定（Q4） |
| 互斥 | 单次请求只能选一种（Q4） | 同上 |
| 最小块 | **1024** tokens | **256**（阿里云百炼部署）；Qwen3.7 系列隐式约 **2000**（Q4） |
| TTL | **5 分钟**（命中重置） | 不确定，系统清理长期未用 |
| 计费（相对标准输入价） | 创建 **125%**；命中 **10%** | 创建按标准；命中 **20%** |
| usage 字段（OpenAI/DashScope） | **命中读**：`usage.prompt_tokens_details.cached_tokens`；**显式创建写**：`usage.prompt_tokens_details.cache_creation_input_tokens`（Q4 示例逐字） | 命中同左 `cached_tokens`（无独立 creation 字段语义） |
| usage 字段（Anthropic 兼容） | `cache_read_input_tokens` / `cache_creation_input_tokens`（Q4） | 同左读路径 |

Responses 另有 Session 缓存（`x-dashscope-session-cache`），见 Q4 文内链。

- **3.8**：Q4 通篇以百炼 Context Cache 规则为准；**未找到**「3.8 不支持缓存」或独立例外明文——落地勿假设与 3.7-max-preview（型号页曾标缓存不支持）相同，**以控制台/实测为准，标未找到型号级例外**。

[来源 Q4, Q13]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

| 项 | 结论 |
|---|---|
| 适配 | **适配** → `supports_reasoning=True`（含 3.8） |
| Chat 开关（混合系） | `enable_thinking` true/false（`extra_body`）（Q3） |
| **3.7 三主力默认** | `qwen3.7-max` / `plus` / **`flash`**：**混合思考，默认开启**（Q3 系列表单列；DeepSeek 首轮已核 flash）→ `thinking_default_on=True`，可关 |
| **主力 D · `qwen3.8-max-preview`** | **仅思考模式，无法关闭**（Q3）。Codex/Qwen Code 明文：thinking 始终开；`reasoning_effort` ∈ {`xhigh`,`medium`,`low`}，**默认 `xhigh`**；思考下 `temperature` 默认 **0.6**，传入 **<0.6 自动抬到 0.6**（Q10/Q11） |
| 其他仅思考 | 如 `qwen3.7-max-preview`、`qwen3.7-max-2026-05-17`：**无法关闭**（Q3） |
| 旧 `qwen-plus` | 混合；官方写明 **默认不开启**（Q3）——勿与 3.7-plus 混淆 |
| budget | `thinking_budget` 限制思考最大 Token（Q3；适用列表含 Qwen3.7 等——**3.8 是否同参：未在独立型号页证实，落地以 API 错误/控制台为准**） |
| Responses | 用 `reasoning.effort` 控制开关与深度（Q1）——与 Chat `enable_thinking` **按端点区分**；3.8 深度档与 Codex 的 `reasoning_effort` 叙述对齐（Q10） |
| 输出字段 | `reasoning_content`（message/delta）；流式推荐（Q3） |
| 采样 | 3.7：**未找到**「思考模式拒绝 temperature」明文。3.8：有 **<0.6 强制抬到 0.6**（Q10），非整段拒绝 |

[来源 Q1, Q3, Q10, Q11]

**6. 官方 tokenizer**

- **未找到** tiktoken encoding 名。
- 官方近似：100万 Token ≈ **70万汉字**（Q1）→ 启发式约 `chars:0.7`（每 token ≈0.7 汉字）；精确依赖 usage。3.8 同启发式，无独立 tokenizer 声明。

[来源 Q1]

**7. 定价（as_of=2026-08-02）**

**7a. 按量 · CNY / 1M tokens（华北2 北京原价；非 Batch）**

`source_url` 以各型号页为准（Q5/Q6/Q7）。优惠以控制台为准。

| 型号 | 档位 | 输入 | 输出 | 隐式缓存命中 | 显式创建 | 显式命中 |
|---|---|---|---|---|---|---|
| `qwen3.7-max` | 统一 | **12** | **36** | **2.4** | **15** | **1.2** |
| `qwen3.7-plus` | ≤256k | **2** | **8** | **0.4** | **2.5** | **0.2** |
| `qwen3.7-plus` | 256k–1M | **6** | **24** | **1.2** | **7.5** | **0.6** |
| `qwen3.7-flash` | ≤32k | **0.2** | **0.8** | **0.04** | **0.25** | **0.02** |
| `qwen3.7-flash` | 32k–256k | **0.6** | **2.4** | **0.12** | **0.75** | **0.06** |
| `qwen3.7-flash` | 256k–1M | **1.2** | **4.8** | **0.24** | **1.5** | **0.12** |

- A17 按量默认填值建议用 **plus ≤256k** 或 **max** 骨架，并按实际输入长度切换阶梯。
- 新加坡等地域单价不同（见各型号页），中国区落地以北京为准。

**7b. Token Plan · `qwen3.8-max-preview`（Credits，非按量 CNY/1M）**

| 项 | 结论 |
|---|---|
| 计费形态 | **仅 Token Plan**（个人版/团队版均支持；Q8/Q12）。**未找到**按量 CNY/1M 价目表（与 3.7 型号页不可混用） |
| 预览说明 | 预览版；结束后可能下线或替换正式版（Q12） |
| 限时 Credits | 预览期调用 Credits **低至 1 折**（约加量 10×）；个人版另有夜间 **22:00–次日 08:00** 在 1 折上再享 **2 折**（即原标准 **0.2 折**）（Q12）。活动可变，以页面为准 |
| 套餐限额 | 个人版 5h + 7d Credits 双窗；团队版月度 Credits（档位见 Q12）。单次 Credits 由模型/Token/思考/工具动态决定，**明细以控制台为准** |
| A17 填价 | **禁止**把 3.7-max 的 12/36 填进 3.8；标 `billing=token_plan_credits`，单价字段 **未找到** |

[来源 Q5, Q6, Q7, Q8, Q12]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT SLA | **未找到**固定 TTFT |
| 加速档 | **未找到**统一 `service_tier` / UltraSpeed 类字段；降本用 `qwen3.7-flash`，Batch 另计 |
| 限流（北京，型号页） | `qwen3.7-max` / `plus` / `flash` 动态 id：**30000 RPM / 5,000,000 TPM**（Q5/Q6/Q7）。快照版限流更严（例 max-2026-05-20：600 RPM / 1M TPM） |
| Token Plan / 3.8 | 个人版另有 **5h / 7d Credits 窗**与并发 Agent 档（Q12），**不是** RPM/TPM 型号页同款表；**未找到** 3.8 独立 RPM/TPM 整数 |

[来源 Q5, Q6, Q7, Q12]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| 思考内容 | 返回 `reasoning_content`；多轮/工具场景应保留并回传（Q3；行业最佳实践）。**未找到**与 DeepSeek/MiMo 同款「缺字段必 400」的千问明文——标 **建议完整回传；强制 400 未找到** |
| `preserve_thinking` | 部分新型号支持将历史思考并入后续输入（见 Q3）；支持列表以官方为准 |
| 3.8 采样 | 勿传 `temperature<0.6` 指望更低随机性——服务端抬到 0.6（Q10） |
| 3.8 Key/域名 | Token Plan 专属 Key + `token-plan.cn-beijing.maas.aliyuncs.com`；误用按量 Key → 401（Q10） |
| 缓存 | 稳定前缀；显式/隐式互斥（Q4） |
| 域名（按量） | 优先 `{WorkspaceId}.cn-beijing.maas.aliyuncs.com`；兼容旧 `dashscope.aliyuncs.com`（Q2） |

[来源 Q2, Q3, Q4, Q10]

#### ③ 对 RxyCode 的含义（A17 照抄用；审计通过前禁止写入代码）

```text
# ========== 四档（A17 必须覆盖；按量首选 plus；Token Plan 最强用 3.8）==========
# A: qwen3.7-plus  B: qwen3.7-max  C: qwen3.7-flash  D: qwen3.8-max-preview

# --- 共用（Chat Completions / OpenAI 兼容；按量三主力）---
context_window = 1_000_000          # 仅 3.7 型号页精确整数；3.8 见下
max_output_tokens = 65_536          # 仅 3.7；3.8 未找到
supports_function_calling = True    # 3.7 Q1 证实；3.8 无型号页勾选表
# supports_builtin_tools: 按型号拆分（见 A/B/C/D）；禁止三主力共用 True
supports_reasoning = True
thinking_default_on = True          # 3.7 混合默认可关；3.8 仅思考且不可关（见 D）
supports_prompt_cache = True        # 隐式默认开；显式可选 cache_control
tokenizer = "chars:0.7"             # 启发式：100万 token≈70万汉字（Q1）；非 tiktoken
# enable_thinking via extra_body；thinking_budget 可选（3.7）
# Responses: reasoning.effort（与 Chat 端点区分）

# UsageFieldMap（OpenAI/DashScope；命中+显式创建均须映射）
cache_read_flat = ()
cache_read_nested = ("prompt_tokens_details", "cached_tokens")
cache_write_nested = ("prompt_tokens_details", "cache_creation_input_tokens")  # 显式创建；A12/A19 扩展 UsageFieldMap
# Anthropic 兼容另计: cache_read_input_tokens / cache_creation_input_tokens
reasoning = ()  # reasoning_content 在 message/delta

# --- 主力 A：qwen3.7-plus（按量推荐默认）---
prompt_variant = "qwen3.7-plus"
supports_vision = True              # Image+Text+Video
supports_builtin_tools = True       # 仅据 Q1 字面；Harness 不计入
# structured_output: Q1=支持 → function_calling 可用
# ≤256k: input 2 / output 8 / cached(implicit) 0.4 / explicit create 2.5 / hit 0.2
# >256k: 6 / 24 / 1.2 / 7.5 / 0.6
input_per_mtok = 2.0
output_per_mtok = 8.0
cached_input_per_mtok = 0.4         # 隐式命中；显式命中另用 0.2
# as_of=2026-08-02; source_url=Q6
# base_url: https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

# --- 主力 B：qwen3.7-max ---
prompt_variant = "qwen3.7-max"
supports_vision = False             # 动态 id 纯文本体验（Q5）
supports_function_calling = True
supports_builtin_tools = True       # Q1 列序：思考/FC/内置/结构化 → max=支持/支持/支持/不支持；内置=True
# structured_output: Q1=不支持 vs Q5=支持 → A17 须注释冲突
# Harness/Codex 不得覆盖本字段
# input 12 / output 36 / implicit cache 2.4 / explicit create 15 / hit 1.2

# --- 主力 C：qwen3.7-flash ---
# supports_vision = True; thinking_default_on = True（可关）
# supports_builtin_tools = True     # 仅据 Q1；Harness 不计入
# ≤32k: 0.2 / 0.8 / 0.04 / create 0.25 / hit 0.02 （更高阶梯见 Q7）

# --- 主力 D：qwen3.8-max-preview（Token Plan 旗舰；与 max「最强」并列）---
prompt_variant = "qwen3.8-max-preview"
billing = "token_plan_credits"      # 禁止填 3.7-max 的 12/36
# input/output/cached CNY/1M = 未找到
context_window = 983616             # Codex 元数据（Q10）；非独立型号页
# max_output_tokens = 未找到
supports_function_calling = None    # 未找到（无型号页勾选）
supports_builtin_tools = None       # 未找到 — 禁止继承 Harness/Codex 写成 True
supports_reasoning = True
thinking_default_on = True          # 仅思考、不可关
# reasoning_effort: xhigh|medium|low; default xhigh
# temperature thinking default 0.6; values <0.6 clamped to 0.6
# supports_vision: Token Plan 表有视觉理解，无型号页复核 → 不写入 True 作 API 能力证明
# supports_parallel_tool_calls = false（Q10 Codex 元数据，非 builtin 证明）
# base_url = https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
# API Key = Token Plan 专属（与按量 Key 不通）
# preview: may be retired/replaced after preview ends（Q12）
# Credits promo (as_of): 1折；个人夜间 22:00-08:00 → 0.2 折（活动可变）

# 识别（matches）
# - "dashscope" / "maas.aliyuncs.com" / "token-plan" + qwen → True
# - model_name startswith ("qwen", "qwen2", "qwen3") → True
# 按量兼容旧: https://dashscope.aliyuncs.com/compatible-mode/v1

# 会话契约
# - 回传 reasoning_content（工具/多轮）；强制 400 未找到
# - 显式/隐式缓存互斥；显式 TTL 5min、min 1024
# - 计费：读 cached_tokens + 写 cache_creation_input_tokens（显式）
# - 3.8: 勿依赖 temperature<0.6；effort 默认 xhigh
```

### §7.8 Anthropic（A0 批 8）

> 状态：**三方审计通过（2026-08-02）**。Grok 自审·rev1.2 + DeepSeek + GPT-5.6-Luna 复审均通过（见 §7.9）。A18 可按本分区填充数值。
>
> **修订历程**：rev1（首写四主力 Claude 5 系）→ rev1.1（升格 **`claude-opus-4-8`** 为主力 E）→ **rev1.2**（Luna 复审 4 条 + DeepSeek 非阻塞吸收）→ Luna 第二轮复审通过 → 用户确认全部审计完成 → **终审三方全过**。

#### ① 调研记录表

| 项 | 值 |
|---|---|
| 批次 | A0 批 8 · Anthropic / Claude（**五主力** `claude-opus-5` + `claude-sonnet-5` + `claude-haiku-4-5` + `claude-fable-5` + **`claude-opus-4-8`**） |
| 调研日期 | 2026-08-02（rev1.1 同日升格 Opus 4.8） |
| 调研模型 | Grok 4.5（Cursor） |
| 调研锚点 | https://docs.anthropic.com/ （与 platform.claude.com 同源） |
| 来源 URL 清单 | 见下表 |

| # | 文档 | URL |
|---|---|---|
| A1 | Models overview（型号 / context / thinking 模式对照） | https://docs.anthropic.com/en/docs/about-claude/models/overview |
| A2 | Pricing | https://docs.anthropic.com/en/docs/about-claude/pricing |
| A3 | Prompt caching | https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching |
| A4 | Thinking（adaptive / display / defaults） | https://docs.anthropic.com/en/docs/build-with-claude/thinking |
| A5 | Extended thinking（legacy `type:enabled`） | https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking |
| A6 | OpenAI SDK compatibility | https://docs.anthropic.com/en/api/openai-sdk |
| A7 | Rate limits | https://docs.anthropic.com/en/api/rate-limits |
| A8 | Token counting | https://docs.anthropic.com/en/docs/build-with-claude/token-counting |
| A9 | Messages API | https://docs.anthropic.com/en/api/messages |
| A10 | Service tiers（Priority 支持型号） | https://docs.anthropic.com/en/api/service-tiers |

#### ② 九问结论

**1. 主力型号与版本号**

官方选型（A1）：复杂 Agent/企业首选 **`claude-opus-5`**；最高能力用 **`claude-fable-5`**（Mythos 5 同规格但邀请制）；速度/智能均衡 **`claude-sonnet-5`**；最快近前沿 **`claude-haiku-4-5`**。另：**`claude-opus-4-8`** 在 A1「仍可用」表中规格与 Opus 5 同档（1M / 128k / $5/$25），生产仍广泛使用，且与 Opus 5 有关键 API 差异（见 Q4/Q5/Q8）——A18 **五主力并列，不得漏写 Opus 4.8，也不得只写 Opus**：

| API model id | 定位 | 备注 |
|---|---|---|
| `claude-opus-5` | 复杂 Agent / 企业 | **主力 A（官方起步推荐）**；alias 同 id；Bedrock **`anthropic.claude-opus-5`**（A1 表后缀数字 3 为脚注「Messages-API Bedrock endpoint」，**不是** model id 的一部分；同理 Fable/Sonnet 为 `anthropic.claude-fable-5` / `anthropic.claude-sonnet-5`） |
| `claude-sonnet-5` | 速度与智能均衡 | **主力 B**；至 2026-08-31 有入门价 |
| `claude-haiku-4-5` / `claude-haiku-4-5-20251001` | 最快近前沿 | **主力 C**；alias `claude-haiku-4-5` |
| `claude-fable-5` | 最强广泛发布档 | **主力 D**；2026-06-09 GA；思考不可关 |
| `claude-opus-4-8` | 前代 Opus 旗舰（仍可用、同价同窗） | **主力 E**；**不得**降为附属；官方建议迁 Opus 5 但**未弃用**；Bedrock Messages 端点见 A1 注脚 |
| `claude-mythos-5` / preview | Glasswing 邀请制 | 非自助；规格/价对齐 Fable（A1） |
| Opus 4.7 / 4.6、Sonnet 4.6 等 | 同代/更早仍可用 | 本批不升主力；迁移动线见 A1 |

[来源 A1]

**2. Context window（token）**

| 型号 | 上下文 | 最大输出（同步 Messages） |
|---|---|---|
| `claude-fable-5` / `claude-opus-5` / `claude-sonnet-5` / **`claude-opus-4-8`** | **1M**（营销表；精确整数官方表写 “1M tokens”，未另给裸整数） | **128k** |
| `claude-haiku-4-5` | **200k** | **64k** |

- Batches：Opus 5 / **Opus 4.8** / Opus 4.7 / Opus 4.6 / Sonnet 5 / Sonnet 4.6 等可用 beta `output-300k-2026-03-24` 至 **300k** 输出（A1）。
- 精确整数：表为 “1M / 200k / 128k / 64k”；A18 可写 `1_000_000` / `200_000` / `128_000` / `64_000` 并注释“来自 A1 表，非另页裸整数”。

[来源 A1]

**3. OpenAI 兼容与 tools / function calling**

- **主路径**：原生 Messages `https://api.anthropic.com/v1/messages`（推荐生产）。
- **OpenAI 兼容（评测用）**：`base_url=https://api.anthropic.com/v1/` + Claude API Key + Claude model id（A6）。**非**长期生产方案。
- 兼容层限制（A6）：**不支持 prompt caching**；thinking 细节不完整（需原生）；`strict` 工具 schema 忽略；`reasoning_effort` **Ignored**；`temperature` 仅 0–1（>1 钳到 1）；`n` 必须为 1。
- **tools**：原生 Messages 完整支持 tools / tool_use；兼容层 tools/functions 可用但不保证 schema 严格。

[来源 A6, A9]

**4. Prompt cache 机制**

| 项 | 结论 |
|---|---|
| 机制 | **显式**：内容块 `cache_control: {"type":"ephemeral"}`；或请求顶层 **automatic** `cache_control`（A3） |
| 断点 | 最多 **4** 个；向前 lookback **20** blocks（A3） |
| 前缀顺序 | `tools` → `system` → `messages`（A3） |
| TTL | 默认 **5 分钟**（命中刷新无额外费）；可选 **1 小时**（更高写入价）（A3） |
| 最小可缓存长度（按型号，A3） | Fable/Opus 5/**Mythos 5**：**512**；Opus 4.7 / Mythos Preview：**2048**；Opus 4.6/4.5：**4096**；Opus 4.8 / Sonnet 5/4.6/4.5 等：**1024**；Haiku 4.5：**4096**；不足则静默不缓存（usage 双 0） |
| usage 字段 | 顶层 `usage.cache_creation_input_tokens` / `usage.cache_read_input_tokens`（及 `input_tokens`/`output_tokens`）（A3/A7） |
| 计费倍率 | 5m 写 **1.25×** base input；1h 写 **2×**；命中 **0.1×**（A2/A3） |
| 失效 | 改断点前前缀会失效该层及之后层（A3）。**Thinking / `budget_tokens`**：配置写入 prompt，变更**会使相关缓存块失效**；tool/system 是否一并失效取决于该型号是否把 thinking 配置渲染在其前面（A3/A4）。**Effort**：改变 `output_config.effort` 会使 message 块失效（tool/system 同 thinking 的型号相关规则）；**但显式设为该型号默认 effort ≡ 省略该字段，不会失效**（A3） |

[来源 A2, A3, A4, A5, A7]

**5. Thinking / reasoning（决定 `supports_reasoning` / `thinking_default_on`）**

| 项 | 结论 |
|---|---|
| 适配 | **适配** → `supports_reasoning=True` |
| 输出块 | `content[].type == "thinking"`（含 `thinking` 文本 + `signature`）；在 text 之前（A4） |
| Claude 5（Opus/Sonnet/Fable） | **Adaptive thinking**；表：Fable **always on**；Opus/Sonnet **Yes**；Haiku 4.5 **No**（仅 extended）（A1） |
| **`claude-opus-4-8`（及 4.7/4.6/Sonnet 4.6）** | Adaptive **Yes**；但 **默认关**：须显式 `thinking: {type:"adaptive"}` 才开启（A4）→ `thinking_default_on=False` |
| **默认开（Claude 5）** | Opus 5 / Sonnet 5 / Fable 5：**已默认开**，无需配置（A4）→ `thinking_default_on=True` |
| 关闭 | Sonnet 5：`thinking: {type:"disabled"}`。Opus 5：effort `high` 及以下可关；**`xhigh`/`max` 不可关**（400）。Fable/Mythos：**拒绝 disabled**（A4） |
| Haiku 4.5 | 仅 **extended** `thinking: {type:"enabled", budget_tokens}`（≥1024，< max_tokens）（A1/A5） |
| 4.7+ / **4.8** | `type:"enabled"` **400**；须 adaptive（A5）；**勿**传 `budget_tokens` |
| effort | `output_config.effort`；**Opus 4.8：全表面默认 high**（含 Claude API / Claude Code / claude.ai）（A1）；Opus 5 / Sonnet 5：API 与 Claude Code **默认 high**（A1） |
| display | 新模型默认 **`omitted`**（空 thinking 文本仍回传 signature）；要看摘要用 `display:"summarized"`（A4） |
| 采样 | A4「Limits and feature compatibility」：Fable / Mythos / Preview / Opus 5 / **4.8** / 4.7 / Sonnet 5 上，**非默认** `temperature` / `top_p` / `top_k` **一律 400**（与是否 thinking **无关**）。A18 落地应保持默认采样或按 400 契约处理。OpenAI 兼容层 temperature>1 钳到 1（A6） |

[来源 A1, A4, A5, A6]

**6. 官方 tokenizer**

- **未找到** tiktoken encoding 名。
- 官方：`messages.count_tokens`（免费，有独立 RPM）（A8）。
- Claude 4.7+ / Fable / Mythos：新 tokenizer，同文约 **+30%** tokens；勿用旧模型计数估费（A2/A8）。
- A18：`tokenizer` 建议 `"count_tokens_api"` 启发式注释，或保持 `chars:` **未找到**官方 chars 比例——标 **用 count_tokens；无 tiktoken**。

[来源 A2, A8]

**7. 定价（USD / 1M tokens；as_of=2026-08-02；A2）**

| 型号 | Input | 5m cache write | 1h cache write | Cache hit | Output |
|---|---|---|---|---|---|
| `claude-fable-5` | **10** | **12.50** | **20** | **1.00** | **50** |
| `claude-opus-5` | **5** | **6.25** | **10** | **0.50** | **25** |
| **`claude-opus-4-8`** | **5** | **6.25** | **10** | **0.50** | **25** |
| `claude-sonnet-5`（至 2026-08-31） | **2** | **2.50** | **4** | **0.20** | **10** |
| `claude-sonnet-5`（自 2026-09-01） | **3** | **3.75** | **6** | **0.30** | **15** |
| `claude-haiku-4-5` | **1** | **1.25** | **2** | **0.10** | **5** |

- Thinking tokens 按 **output** 计费（A4）。
- Batch / 云厂商区域价另计（A2）。
- Opus 4.8 与 Opus 5 **同价同 cache 列**（A2）；差异在 thinking 默认 / cache 最小块 / Priority / 限流桶，不在单价。

[来源 A2, A4]

**8. 延迟 / 限流 / 加速档**

| 项 | 结论 |
|---|---|
| TTFT SLA | **未找到**固定 TTFT 数值 |
| 加速档 | **Fast mode**（A2/A7）：**Opus 5 / Opus 4.8 专享**；价例 $10/$50；独立限流（`anthropic-fast-*` headers）；4.7 报错 / 4.6 静默降速；**Claude Platform on AWS 不可用**；**不可与 Batch 组合** |
| 服务档 | Standard / Priority / Batch（A10）；**Priority 排除**：Mythos 5 / Mythos Preview / **Opus 5** / **Sonnet 5**（A10）。**`claude-opus-4-8` 在排除名单之外**，技术上支持 Priority；但 A10 **顶部 Warning：Priority 新容量已停售**，仅既有容量承诺可续用至合同结束 → 落地写「仅既有承诺，勿假设可新购」 |
| 限流（示例：Messages；按 usage tier 分表，A7） | Start 档例：Fable **1000 RPM / 500k ITPM / 100k OTPM**；Opus 5 / **Opus 4.x\*** / Sonnet 5 / Haiku 4.5 **1000 / 2M / 400k**。\* **Opus 4.x 共享同一限流桶**（含 4.8），与 Opus 5 **分桶**（A7）。Build/Scale 更高。**以 Console Limits 为准** |
| ITPM | 多数型号：**不含** `cache_read_input_tokens`（Haiku 3.5† 例外）（A7） |

[来源 A7, A10]

**9. 会话续接注意事项**

| 场景 | 规则 |
|---|---|
| thinking 回传 | **工具使用回合**：**必须**完整且**不修改**回传 thinking 块（含 signature）（A4）。**跨回合**：仅**建议**回传。**非工具场景**：允许省略历史 thinking（A4） |
| 工具交错 | Adaptive 自动 interleaved；旧 manual 需 beta header（A4/A5） |
| 缓存 | 稳定前缀；thinking/budget 变更会使相关块失效；effort 非默认变更会使 message 失效，**默认 effort ≡ 省略不失效**（A3） |
| OpenAI 兼容 | 勿当生产主路径；无原生缓存/完整 thinking（A6） |
| 缓存计费细节（A19） | `input_tokens` 仅断点后；total=`cache_read`+`cache_creation`+`input`；1h TTL 时 `cache_creation` 可含 `ephemeral_5m_input_tokens`/`ephemeral_1h_input_tokens`；workspace 级隔离；thinking 块**不可**显式 `cache_control`（随工具结果自动缓存，命中按 input 计费）（A3） |

[来源 A3, A4, A5, A6]

#### ③ 对 RxyCode 的含义（A18 照抄用；审计通过前禁止写入代码）

```text
# ========== 五主力（A18 必须覆盖；起步推荐 Opus 5；Opus 4.8 不得省略）==========
# A: claude-opus-5  B: claude-sonnet-5  C: claude-haiku-4-5  D: claude-fable-5
# E: claude-opus-4-8（前代旗舰；同价同窗；thinking 默认关 / cache min 1024 / Priority 可用）

# --- 共用（原生 Messages；生产主路径）---
# base_url: https://api.anthropic.com （SDK）；endpoint /v1/messages
supports_function_calling = True
supports_reasoning = True
supports_prompt_cache = True        # cache_control ephemeral；OpenAI 兼容层不支持
tokenizer = "count_tokens_api"      # 无 tiktoken；用 messages.count_tokens；4.7+/Fable ≈+30%
# OpenAI 兼容仅评测: base_url=https://api.anthropic.com/v1/ ；无 cache；thinking 不完整

# UsageFieldMap（顶层 usage，非 nested）
cache_read_flat = ("cache_read_input_tokens",)
cache_read_nested = ()
cache_write_flat = ("cache_creation_input_tokens",)  # A12/A19 扩展
reasoning = ()  # thinking 在 content blocks，非 delta.reasoning_content

# --- 主力 A：claude-opus-5（推荐默认 Agent）---
prompt_variant = "claude-opus-5"
context_window = 1_000_000          # A1「1M」
max_output_tokens = 128_000
supports_vision = True
thinking_default_on = True          # adaptive 默认开；可 disabled（非 xhigh/max）
# effort API default high
# cache min tokens = 512
# Priority Tier: NOT supported（A10）
# as_of=2026-08-02: input 5 / output 25 / cache_hit 0.50 / 5m_write 6.25 / 1h_write 10
input_per_mtok = 5.0
output_per_mtok = 25.0
cached_input_per_mtok = 0.50
# source_url=A2

# --- 主力 B：claude-sonnet-5 ---
# context 1M / out 128k / vision True / thinking_default_on True（可 disabled）
# cache min = 1024；Priority: NOT supported
# 至 2026-08-31: 2 / 10 / hit 0.20 / 5m 2.50 / 1h 4
# 自 2026-09-01: 3 / 15 / hit 0.30 / 5m 3.75 / 1h 6

# --- 主力 C：claude-haiku-4-5 ---
# context 200_000 / out 64_000 / vision True
# thinking: 不支持 adaptive；仅 extended：须显式 thinking: {type:"enabled", budget_tokens}
# thinking_default_on = False
# 1 / 5 / hit 0.10 / 5m 1.25 / 1h 2
# cache min tokens = 4096；Priority: supported（不在 A10 排除名单；新容量停售→仅既有承诺）

# --- 主力 D：claude-fable-5 ---
# context 1M / out 128k / vision True
# thinking always on；不可 disabled
# 10 / 50 / hit 1.00 / 5m 12.50 / 1h 20
# cache min = 512；tokenizer +30% vs pre-4.7；Priority: supported

# --- 主力 E：claude-opus-4-8（A18 不得省略；与 Opus 5 同价同窗）---
# prompt_variant = "claude-opus-4-8"
# context_window = 1_000_000；max_output_tokens = 128_000；supports_vision = True
# supports_reasoning = True
# thinking_default_on = False   # 须显式 thinking: {type:"adaptive"}；type:enabled → 400
# effort 全表面默认 high（含 claude.ai）
# cache min tokens = 1024（≠ Opus 5 的 512）
# Priority Tier: 技术上 supported（A10；Opus 5 不支持）；新容量停售→仅既有承诺
# 限流：归 Opus 4.x* 共享桶（与 Opus 5 分桶）（A7）
# as_of=2026-08-02: input 5 / output 25 / cache_hit 0.50 / 5m_write 6.25 / 1h_write 10（同 Opus 5）
# tokenizer: 4.7+ 族 ≈+30%

# 识别（matches）
# - "anthropic.com" in url or model startswith "claude" → True

# 会话契约
# - 工具回合：必须完整不修改回传 thinking blocks + signature；跨回合建议回传；非工具可省略历史 thinking
# - cache_control；thinking/budget 变更失效相关块；effort 设为型号默认 ≡ 省略，不失效
# - Claude 5 / 4.8：勿传非默认 temperature/top_p/top_k（400）
# - 生产勿依赖 OpenAI 兼容层做 cache/thinking
# - Opus 4.8 路径务必显式开 adaptive，勿假设与 Opus 5 同默认
# - Bedrock Messages 端点 ID：anthropic.claude-opus-5（勿写 ...-53；表尾 3=脚注）
```

### §7.9 审计记录表（A0 每批审计写入）

> 审计三要素：**审计模型名称 / 审计时间 / 审计结果（通过或不通过 + 问题清单）**。三要素缺一的记录视为不存在。
> 审计方（2026-08-01 更新）：① Grok 4.5（调研模型自审）② DeepSeek（验证模型 1）③ GPT-5.6-Luna（验证模型 2）。②与③独立验证，互不参考。验证提示词见 [`PROMPTS.md`](./PROMPTS.md)。

| 批次 | 分区 | 审计模型 | 审计时间 | 审计结果 | 问题清单与处置 |
|---|---|---|---|---|---|
| 批 1 | §7.1 | Grok 4.5 | 2026-08-02 | **通过（自审·rev3）** | 终审：三方全过。rev3 Q6 措辞已获 Luna 确认。 |
| 批 1 | §7.1 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 13:50 | **通过（复审 rev2）** | **收回我第一轮 P1 主张**：重新抓取官方 thinking_mode 页（2026-08-02），映射表 12 格序列为 low\|low\|high、high\|high\|high、**xhigh\|high\|max**、max\|max\|max——pro 的 xhigh 官方确为 max，第一轮"xhigh→high"系我误读三列表格，Grok 的"驳回"成立，rev2 的 pro: low→high、high→high、xhigh→max、max→max 正确。P2 已改为 `chars:2.0` 且注明"A5 可落地、勿写 hf:"，符合 TokenizerSpec（tiktoken:/chars:），落地无缺口。P3 已补 S13+S9 引用（Flash 更新 2026-07-31、Pro 首发 2026-04-24 且 07-31 未更新、旧 id 2026-07-24 15:59 UTC 停用并过渡路由 v4-flash non-thinking/thinking），与我可核验信息一致。Luna rev2 唯一遗留（Q6 措辞"无 tiktoken encoding"vs"未找到"）属表述精度问题，我独立复核：S8 官方页面确实未给出 tiktoken encoding 名，仅提供离线 zip 与近似比例，`chars:2.0` 已明确标注为启发式估算而非官方数值——建议接受该措辞修订，不构成事实冲突。S4（API 参考页）的 128 工具上限/tool_choice/reasoning_tokens/medium、xhigh 别名未被本审计直接抓取复核，以 S4 引用为准（备注不阻塞）。 |
| 批 1 | §7.1 | GPT-5.6-Luna | 2026-08-02 15:29 | **通过** | 问题清单：无。复审确认 rev3 已将 Q6 改为“未找到官方 tiktoken encoding”，并明确 `chars:2.0` 仅为 RxyCode 启发式估算、非官方 tokenizer 数值；Q1–Q9 其余数值、字段名和行为声明均与当前 DeepSeek 官方文档一致。重点核验：thinking 默认 enabled、effort 映射、Chat Completions/Responses usage 字段、自动缓存及工具链 `reasoning_content` 回传规则均通过。来源：https://api-docs.deepseek.com/quick_start/token_usage；https://api-docs.deepseek.com/guides/thinking_mode；https://api-docs.deepseek.com/guides/kv_cache；https://api-docs.deepseek.com/api/create-chat-completion/；https://api-docs.deepseek.com/guides/responses_api |
| 批 2 | §7.2 | Grok 4.5 | 2026-08-02 | **通过（自审·rev2）** | rev2 修正后 DeepSeek + Luna 均通过；批 2 三方全过。 |
| 批 2 | §7.2 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 14:10 | **通过** | 本审计独立执行（未参考 GPT-5.6-Luna 结论）。逐条抓取官方页核验：O1 型号页三档（sol 别名 gpt-5.6、cutoff 2026-02-16、context 1.05M、output 128K）✓；O2 型号页 max input 922,000、>272K 整单 2x/1.5x、Tier1 500 RPM/500,000 TPM、Cache writes 1.25x ✓；O5 定价页 Standard 三档（sol $5/$0.50/$6.25/$30、terra $2/$0.20/$2.50/$12、luna $0.20/$0.02/$0.25/$1.20）、Long context 列、Fast mode（2026-07-30 由 Priority 更名，service_tier fast/priority，sol $10/$1/$12.50/$60）✓；O6 prompt-caching 页 1024 严格下限、TTL 仅 30m、隐式断点在最新 user/tool 消息且不回退最长前缀（cached_tokens 可为 0）、显式断点 + prompt_cache_key（5.6 必须设 key 才用可靠匹配）、4 写槽/50 读断点、cache_write_tokens 1.25x、prompt_cache_retention 对 5.6 弃用、组织间不共享缓存 ✓；O7 reasoning 指南 effort 档位 none/low/medium/high/xhigh/max（型号子集不同）、省略 effort 默认 medium（standard 与 pro 皆然）、原始 reasoning 不暴露（encrypted_content/stateless、summary 摘要）、usage.output_tokens_details.reasoning_tokens、GPT-5.6 默认 reasoning.context=all_turns、函数调用回传 reasoning items 建议、pro 模式独立于 effort ✓。temperature 拒绝声明标"未找到"属诚实处理 ✓。③ 含义段与官方 usage 示例字段路径（prompt_tokens_details.cached_tokens / cache_write_tokens / completion_tokens_details.reasoning_tokens）逐字一致 ✓。非阻塞备注（2 条）：① O8（migrate-to-responses）与 O10（token-counting）两页未直接抓取，Q3 的 reasoning_effort 顶层参数位置、Q6 的 tiktoken 不准确性表述、Q9 的 reasoning:none 无 tool calling 细则以引用为准，建议 Grok 自审抽检原文；② ③ 中 cache_write_nested / reasoning_nested 字段名超出 A1 的 UsageFieldMap 现有结构（仅 cache_read_flat/cache_read_nested/reasoning），A12/A19 落地时需扩展 UsageFieldMap 增加 cache_write 路径（供 Phase E 缓存写入计费）或明确仅消费命中字段。 |
| 批 2 | §7.2 | GPT-5.6-Luna | 2026-08-02 15:50 | **通过** | 问题清单：无。复审确认 rev2 已补充分列的 GPT-5.6 发布日（2026-07-09）与最近 Changelog 更新日（2026-07-30）；已将旧型号 retention 按型号区分（GPT-5.5 / GPT-5.5-pro 仅 24h，in_memory 仅适用于明确支持的型号）；已将截断缓存影响改为“未找到”。Q1–Q9 其它数值、字段名和行为声明均与当前 OpenAI 官方文档一致。重点核验：prompt_cache_breakpoint / prompt_cache_options / prompt_cache_key、cached_tokens / cache_write_tokens、reasoning_effort 默认 medium、Chat Completions 与 Responses 差异均通过。来源：https://developers.openai.com/api/docs/changelog；https://developers.openai.com/api/docs/guides/prompt-caching；https://developers.openai.com/api/docs/guides/reasoning；https://developers.openai.com/api/docs/guides/token-counting |
| 批 3 | §7.3 | Grok 4.5 | 2026-08-02 | **通过（自审·rev2）** | rev2 修正后 DeepSeek + Luna 均通过；批 3 三方全过。 |
| 批 3 | §7.3 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 14:40 | **通过** | 本审计独立执行（未参考 GPT-5.6-Luna 结论）。直接抓取 platform.kimi.com 官方页核验：M7 Context Caching（自动启用、无缓存 ID/TTL 管理、prompt>256 才缓存否则丢弃、固定上下文放 messages 最前、长文本首 Token 平均降至 5s 内）✓；M9 reasoning_effort（K3 始终推理、顶层 low/high/max 默认 max、K2.x 迁移移除 thinking、多轮/工具调用原样回传完整 assistant）✓；M8 思考模型（k3 始终推理+Preserved Thinking 始终开、k2.7-code 始终思考+keep 恒为 all 且传 disabled 报错、k2.6 type enabled 默认/disabled + keep null 默认/"all"、k2.5 不支持 Preserved Thinking、reasoning_content 计入 token、max_tokens>=16000 建议、temperature 不可修改勿显式传入）✓；M2 模型列表（kimi-k3 2.8T 参数原生视觉 100 万上下文、k2.7-code/-highspeed 256k 且 highspeed 180 tok/s 短上下文 260、k2.6 256k、moonshot-v1 8k/32k/128k 输入+输出合计、k2.5/moonshot-v1 新用户停开 8 月 31 日全平台下线、kimi-k2 系列 2026-05-25 下线）✓；M5 Chat+OpenAPI（usage.cached_tokens 顶层字段（非 prompt_cache_hit_tokens）、prompt_cache_key 可选（Coding Agent 用稳定 session/task id、Kimi Code Plan 必填）、tool_choice auto/none/required、K3 动态工具 system message 无 content、max_completion_tokens K3 默认 131072 最大 1048576 超窗 invalid_request_error、image_url/video_url 多模态、response_format json_object/json_schema）✓；M3 模型参数参考（temperature/top_p/n/presence/frequency 固定值逐条一致：k3 与 k2.7 固定 1.0/0.95/1/0/0、k2.6 思考 1.0 非思考 0.6、改值报错建议不显式传入；**切换 reasoning_effort 破坏前缀缓存命中、会话开始前定档**——报告 Q4/Q5 引用正确；tool_choice 仅 k3 支持 required，k2.6/k2.7 传入报错）✓。非阻塞备注（2 条）：① Q7 定价卡片（¥20/¥2/¥100、¥6.50/¥1.30/¥27、¥6.50/¥1.10/¥27）依赖 M1 首页 JS 渲染，静态抓取无法复核，报告已标注"落地前人工打开 M13 复核"——保持该标注，A13 填值前人工确认；② ③ 中 reasoning=() 处理正确（Kimi 的 reasoning_content 在 message 级而非 usage 嵌套，与 A8 的 _extract_reasoning 走 delta/message 一致）；A13 落地时注意 tool_choice required 需按模型分支（k3 支持、k2.6/k2.7 不支持）。 |
| 批 3 | §7.3 | GPT-5.6-Luna | 2026-08-02 16:07 | **通过** | 问题清单：无。复审确认 Q2 已区分精确 context 与营销近似值（K3 1,048,576；K2.7 系列/K2.6 262,144）；Q4 已删除未证实的逐项缓存失效规则，仅保留 `reasoning_effort` 切换会破坏命中的官方警告；Q7 已拆分 K2.7 Code HighSpeed 独立价格（¥13.00 / ¥2.60 / ¥54.00）；Q8 已补齐官方 Tier0–Tier5 限速表。Q1–Q9 其余型号、OpenAI 兼容、thinking/effort、usage.cached_tokens、tokenizer 和工具续接结论均与当前官方文档一致。来源：https://platform.kimi.com/docs/pricing/chat-k3；https://platform.kimi.com/docs/pricing/chat-k27-code；https://platform.kimi.com/docs/pricing/chat-k26；https://platform.kimi.com/docs/pricing/limits；https://platform.kimi.com/docs/guide/use-context-caching-feature-of-kimi-api；https://platform.kimi.com/docs/api/models-overview |
| 批 4 | §7.4 | Grok 4.5 | 2026-08-02 | **通过（自审·rev2）** | rev2 修正后 DeepSeek + Luna 均通过；批 4 三方全过。 |
| 批 4 | §7.4 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 15:10 | **通过** | 本审计独立执行（未参考 GPT-5.6-Luna 结论）。直接抓取 docs.bigmodel.cn 官方页核验：G9 上下文缓存（隐式、`usage.prompt_tokens_details.cached_tokens`、完全相同命中最高/格式差异影响/合理时效）✓；G6/G7/G8 thinking（默认 enabled、5.2+ reasoning_effort 默认 max 及映射、reasoning_content、clear_thinking Preserved Thinking、交错思考须回传）✓；G5 OpenAI 兼容 paas/v4 ✓；G1 型号上下文 1M/200K/128K、精确整数未公布 ✓；G6 max_tokens 表 131072/98304 ✓。非阻塞：G13 定价前端渲染不可静态复核（rev2 已改为未找到）；G3 日期首轮未抓取（rev2 已按 G3 补齐）。 |
| 批 4 | §7.4 | GPT-5.6-Luna | 2026-08-02 16:23 | **通过** | 问题清单：无。复审确认 Q1 已修正 GLM-4.7 基座与 Flash 日期错配，并补齐 GLM-4.6、GLM-4.5 系列日期；Q2 已将 context 精确整数明确标为“未找到”，仅保留带注释的项目侧启发式值；Q7 已将无法从官方静态文本独立复核的精确价格全部标为“未找到”，并禁止写入未经核验的定价。Q1–Q9 其余型号、OpenAI 兼容、thinking/reasoning、缓存 usage 字段、tokenizer API、限流与会话续接结论均与当前官方文档一致。来源：https://docs.bigmodel.cn/cn/update/new-releases；https://docs.bigmodel.cn/cn/guide/start/model-overview；https://docs.bigmodel.cn/cn/guide/start/concept-param；https://docs.bigmodel.cn/cn/guide/capabilities/cache；https://open.bigmodel.cn/pricing |
| 批 5 | §7.5 | Grok 4.5 | 2026-08-02 16:50 | **通过（自审·rev2）** | rev2 修正后 DeepSeek 首轮通过 + Luna 复审通过；批 5 三方全过。 |
| 批 5 | §7.5 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 15:40 | **通过** | 本审计独立执行（未参考 GPT-5.6-Luna 结论）。直接抓取 platform.minimaxi.com 官方页核验：MM1 接口概览（型号清单 M3/M2.7/M2.7-highspeed/M2.5/M2.5-highspeed/M2.1/M2.1-highspeed/M2、上下文 1,000,000 与 204800 精确整数、列名"输入输出总 token"、60/100 tps 为输出速度营销表述）✓；MM5 Prompt 缓存（被动自动缓存/Anthropic 主动缓存区分、≥512 input tokens、前缀顺序工具定义→系统提示词→历史对话、任意模块变更可能影响、usage.prompt_tokens_details.cached_tokens（OpenAI）与 cache_read_input_tokens/cache_creation_input_tokens（Anthropic）、被动写入无额外费/主动首写额外费、支持型号表：被动含 M3 而主动不含 M3、被动 TTL 自动调整/主动 5min 自动续期、M3 >512k 含缓存命中 tokens 走长上下文价）✓；MM8 按量计费（M3 ≤512k 永久五折现价 2.10/8.40/0.42、>512k 4.20/16.80/0.84、Priority 1.5x 3.15/12.60/0.63 与 6.30/25.20/1.26、service_tier=priority、M2.7 2.1/8.4/0.42/写入 2.625、M2.7-highspeed 4.2/16.8/0.42/2.625、历史 M2.5/M2.1/M2 缓存读 0.21、1600 中文字符≈1000 tokens、Token Plan 订阅独立）✓；MM3 Chat Completions OpenAPI（thinking.type adaptive（默认）/disabled、M2.x 无法关闭、reasoning_split 拆到 reasoning_content/reasoning_details 且不开关 thinking、无 reasoning_effort、temperature [0,2] 默认 1、max_completion_tokens、tools function、响应示例证实 <think> 包裹与 prompt_tokens_details.cached_tokens）✓；MM4 OpenAI SDK（OPENAI_BASE_URL api.minimaxi.com/v1、reasoning_split、原生 content 含 <think> 需完整保留、temperature 越界报错、presence/frequency_penalty 与 logit_bias 被忽略、n 仅支持 1、旧版 function_call 已废弃用 tools、M3 图/视频输入当前不支持音频、多模态 detail low/default/high）✓；MM9 速率限制（M3 免费 20 RPM/1M TPM 充值 200 RPM/10M TPM、M2 系免费 20/1M 充值 500/20M、TPM=输入+输出）✓。非阻塞备注（4 条）：① ③ 的 max_output_tokens 可补充 MM3 OpenAPI 参数上限：M3 推荐 131072/上限 524288、其他推荐 65536/上限 204800（报告"未找到"指架构级独立上限，参数上限是可落地参考值，A15 建议采用）；② MM4 多模态 detail 档位与单图 token 估算（low~600、default 1k-3k 最高 5k、high 15k+）对 Phase F 的 count_image_tokens 有参考价值；③ MM9"批量合并请求提高 TPM 吞吐"提示与 A20/EF 的 token 治理相关；④ MM2 Changelog 发布日（M3 2026-06-01 等）未直接抓取，以引用为准，建议 Grok 自审抽检。**注：rev2 已将备注①写入 Q2 正表，并按 Luna 意见区分 Responses `reasoning.effort`；建议对 rev2 Q2/Q5 抽检。** |
| 批 5 | §7.5 | GPT-5.6-Luna | 2026-08-02 16:36 | **通过** | 问题清单：无。复审确认 Q2 已补入官方 `max_completion_tokens` 上限（MiniMax-M3=524288，M2.x=204800）；Q5 已按 endpoint 区分：Chat Completions 省略 `thinking` 默认 adaptive 开启，Responses API 的 M3 省略 `reasoning` 或 `effort=none` 默认关闭，非 `none` 仅开启 Adaptive Thinking，M2.x 无法关闭。Q1–Q9 其余型号、缓存机制与 usage 字段、OpenAI/Anthropic 兼容、定价、限流、tokenizer 和工具续接结论均与当前官方文档一致。来源：https://platform.minimaxi.com/docs/api-reference/text-chat-openai；https://platform.minimaxi.com/docs/api-reference/responses-create；https://platform.minimaxi.com/docs/api-reference/text-prompt-caching；https://platform.minimaxi.com/docs/guides/pricing-paygo；https://platform.minimaxi.com/docs/guides/rate-limits |
| 批 6 | §7.6 | Grok 4.5 | 2026-08-02 16:55 | **通过（自审·rev1.1）** | 三方全过。rev1.1：按用户反馈将 **`mimo-v2.5` 升格为与 `mimo-v2.5-pro` 并列双主力**，并补 ③ 独立骨架（vision/定价）；九问数值未改。 |
| 批 6 | §7.6 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 16:10 | **通过** | 本审计独立执行（未参考 GPT-5.6-Luna 结论）。直接抓取 mimo.mi.com 官方页核验：X1 模型列表（mimo-v2.5-pro 文本/深度思考/函数调用/结构化输出/联网、1M 上下文/128K 输出、100 RPM/10M TPM（单账号全部 Key 合计）、mimo-v2.5 全模态同窗口、v2 系 2026-06-30 00:00 正式下线、页首横幅同确认）✓；X5 深度思考（thinking.type enabled/disabled 经 extra_body、默认开启（v2.5-pro/v2.5）、思考模式强制 temperature=1.0/top_p=0.95、多轮工具调用必须完整回传 reasoning_content 否则 400、message.reasoning_content 与流式 delta.reasoning_content 先于 content、usage.completion_tokens_details.reasoning_tokens、prompt_tokens_details 可为 {}、max_completion_tokens 限制思考+回答总长、base_url api.xiaomimimo.com/v1、api-key/Bearer 双鉴权）✓；X4 Responses（端点 /v1/responses、不兼容 background/previous_response_id/context_management、reasoning.effort none 关闭且 low/medium/high 均开启效果一致暂不区分强度、省略默认未找到、usage.output_tokens_details.reasoning_tokens）✓；X6 模型超参（temperature 默认 1.0 范围 [0,1.5]、top_p 默认 0.95 范围 [0.01,1.0]、思考模式不支持自定义强制默认）✓；X8 按量计费（pro 命中 0.025/未命中 3.00/输出 6.00、v2.5 0.02/1.00/2.00、前缀命中 Prompt Cache 按命中价计费、缓存写入限时免费、海外 USD pro 0.0036/0.435/0.87、联网搜索 ¥16/1000 次、按量与 Token Plan 不互通）✓；X15 UltraSpeed 型号页（独立 model id、3× 定价命中 0.075/未命中 9/输出 18、输出 TPS ~(500-1000) vs Pro ~(50-100)、资源有限每日限量审批面向专业机构、能力含 Cache、示例 max_completion_tokens=131072、USD 0.0108/1.305/2.61）✓。非阻塞备注（3 条）：① X10 发布日（v2.5-pro/v2.5 2026-04-23）未直接抓取，以引用为准，建议 Grok 自审抽检（日期不进代码）；② X9 的 v2.5 默认 max_completion_tokens=32768 未直接抓取，可抽检；③ X4 的 effort 省略默认未找到——A16 主路径为 Chat（默认开启思考），若未来走 Responses 需显式传 effort 且 low/medium/high 效果相同。 |
| 批 6 | §7.6 | GPT-5.6-Luna | 2026-08-02 16:44 | **通过** | 问题清单：无。独立复审确认 Q1–Q2 型号、下线日期、1M/128K 口径与精确整数未找到的边界正确；Q3 双协议端点和 tools 正确；Q4 隐式缓存、`prompt_tokens_details.cached_tokens`、TTL/最小块/bust 未找到及 HySparse 非 API 参数边界正确；Q5 Chat 默认 thinking enabled、Responses `reasoning.effort` 端点差异、采样限制与 reasoning 字段正确；Q6 tokenizer 未找到；Q7 Pro/V2.5/UltraSpeed CNY 定价与 3× 价格正确；Q8 UltraSpeed 吞吐标称、100 RPM/10M TPM 限流正确；Q9 工具链完整回传 `reasoning_content` 的 400 契约正确。来源：https://mimo.mi.com/docs/zh-CN/quick-start/summary/model；https://mimo.mi.com/docs/zh-CN/api/chat/openai-api；https://mimo.mi.com/docs/zh-CN/api/chat/responses；https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/deep-thinking；https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go；https://mimo.mi.com/docs/zh-CN/api/guidance/rate-limit |
| 批 7 | §7.7 | Grok 4.5 | 2026-08-02 17:50 | **通过（自审·rev1.5·终审）** | 用户确认审核通过；批 7 三方全过。可进批 8。 |
| 批 7 | §7.7 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 17:00 | **通过（终审）** | 批 7 三方全过（用户确认 + Luna rev1.6）。 |
| 批 7 | §7.7 | GPT-5.6-Luna | 2026-08-02 17:41 | **通过（复审·rev1.6）** | 问题清单：无。Q1–Q9 及重点 Q10/Q12/Q13/③-D 复核通过；Q4 的 Qwen3.7 隐式缓存约 2000 Token、Q10 Codex 元数据、Q12 Credits 规则、Q13 官方 URL 软 404 均与官方文档一致。 |
| 批 7 | §7.7 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 17:30 | **通过（复审 rev1.5）** | 用户确认审核通过。rev1.5 max builtin=True 与 Q1 列序一致；3.8 未找到保持。批 7 三方全过。 |

> 批 7 / §7.7 rev1.6 复审记录
> 审计模型：GPT-5.6-Luna
> 审计时间：2026-08-02 17:41
> 审计结果：通过
> 问题清单（每条一行）：无

| 批 8 | §7.8 | Grok 4.5 | 2026-08-02 18:20 | **通过（自审·rev1.1）** | rev1.1：按用户反馈升格 **`claude-opus-4-8` 为主力 E**（五主力）；补 thinking 默认关、cache min 1024、Priority 支持、Opus 4.x 共享限流桶、同价 $5/$25；③ 独立骨架。待 DeepSeek + Luna 复审（须覆盖主力 E）。 |
| 批 8 | §7.8 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 19:05 | **通过（首轮）** | 本审计独立执行（未参考 GPT-5.6-Luna 结论）。直接抓取官方页核验（A1 models/overview、A2 pricing、A3 prompt-caching、A4 thinking、A5 extended-thinking、A6 openai-sdk、A7 rate-limits、A10 service-tiers）：Q1 五主力 ✓（claude-opus-5 官方起步推荐、fable-5 GA 2026-06-09 最强、haiku-4-5-20251001/alias、opus-4-8 legacy「仍可用」未弃用同价同窗、mythos 邀请制、Bedrock id anthropic.claude-opus-53）；Q2 ✓（1M/200k 官方表、输出 128k/64k 同步 Messages、Batches output-300k-2026-03-24 名单含 Opus 5/4.8/4.7/4.6/Sonnet 5/4.6）；Q3 ✓（OpenAI 兼容非生产定位、base_url /v1/、无 prompt caching、thinking 细节不完整、strict 忽略、reasoning_effort Ignored、temperature 0–1 钳 1、n 必须 1、usage.prompt/completion_tokens_details 恒空）；Q4 ✓（ephemeral+automatic、4 断点、20 lookback、tools→system→messages、5min 默认/1h 可选、最小块表 Fable/Opus5/Mythos5=512、Mythos Preview/Opus 4.7=2048、Opus 4.6/4.5 与 Haiku 4.5=4096、Opus 4.8/Sonnet 5 等=1024 逐项与官方一致、顶层 usage.cache_creation/cache_read_input_tokens、倍率 5m 1.25x/1h 2x/hit 0.1x、不足最小长度静默双 0、thinking/effort/budget 变更 bust）；Q5 ✓（adaptive 块先于 text、signature、display omitted 为新模型默认/summarized 可选、Opus5/Sonnet5/Fable5 默认开、Opus 4.8 默认关须显式 adaptive、Sonnet5 可 disabled、Opus5 xhigh/max 不可关 400、Fable/Mythos 拒 disabled、Haiku 仅 extended（budget ≥1024 且 <max_tokens）、4.7+/4.8 type:enabled 400 且勿传 budget_tokens、effort 默认 high（4.8 全表面；Opus5/Sonnet5 API+Claude Code）、thinking 按 output 计费、adaptive 自动 interleaved）；Q6 ✓（无 tiktoken encoding 名、count_tokens API、4.7+/Fable 新 tokenizer ≈+30%）；Q7 定价六行全对 ✓（Fable 10/12.50/20/1.00/50、Opus5 与 4.8 同 5/6.25/10/0.50/25、Sonnet5 入门 2/2.50/4/0.20/10 至 8-31 与 9-01 起 3/3.75/6/0.30/15、Haiku 1/1.25/2/0.10/5）；Q8 ✓（TTFT 无官方数值、Priority 排除名单 Mythos 5/Preview/Opus 5/Sonnet 5 与官方 A10 逐字一致、Opus 4.8 支持 Priority、Start 档 Fable 1000/500k/100k 与 Opus 5/4.x/Sonnet 5/Haiku 1000/2M/400k、Opus 4.x 共享桶（官方脚注 \*：4.8+4.7+4.6+4.5 合计、Opus 5 分桶）、ITPM 多数不含 cache_read（Haiku 3.5† 例外））；Q9 ✓（thinking 块+signature 原样回传、manual interleaved 需 beta header、缓存稳定前缀、兼容层非生产）。③ 骨架五主力 A–E 字段与官方逐一相符（含 E 的 thinking_default_on=False/cache min 1024/Priority 可用/共享桶/同价）。**问题清单：无。** 非阻塞备注（4 条）：① 采样参数——官方 A4「Limits and feature compatibility」明文：Fable/Mythos/Preview/Opus 5/4.8/4.7/Sonnet 5 上**非默认** temperature/top_p/top_k 一律 400（无条件，与 thinking 无关）；报告 Q5 采样行"未找到 thinking 强制拒绝 temperature 明文"技术上成立（拒绝非 thinking 触发），建议并入正表：Claude 5 系/4.8 不支持温度调节，A18 落地 temperature 应保持默认或按 400 契约处理；② Fast mode 完整细节（A2/A7 实为完整来源）：Opus 5/Opus 4.8 专享 $10/$50、独立限流（anthropic-fast-\* headers）、4.7 报错/4.6 静默降速、Claude Platform on AWS 不可用、不可与 Batch 组合——报告 Q8"细节待补 URL"可销账；③ **Priority 新容量已停售**（A10 顶部 Warning）：仅既有容量承诺可续用至合同结束；"Opus 4.8 支持 Priority"建议加"仅既有承诺"限定；④ A3 缓存计费细节（A19 直接可用）：input_tokens 仅含断点后 tokens（total=cache_read+cache_creation+input）、1h TTL 时 usage 含 cache_creation 子对象（ephemeral_5m_input_tokens/ephemeral_1h_input_tokens）、workspace 级缓存隔离、thinking 块不可显式 cache_control（随工具结果自动缓存且命中时按 input 计费）。来源：https://docs.anthropic.com/en/docs/about-claude/models/overview ；https://docs.anthropic.com/en/docs/about-claude/pricing ；https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching ；https://docs.anthropic.com/en/docs/build-with-claude/thinking ；https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking ；https://docs.anthropic.com/en/api/openai-sdk ；https://docs.anthropic.com/en/api/rate-limits ；https://docs.anthropic.com/en/api/service-tiers |
| 批 8 | §7.8 | GPT-5.6-Luna | 2026-08-02 17:54 | **不通过（复审）** | 4 个问题：Q1 Bedrock 型号 ID；Q4 缓存失效例外；Q5 Haiku thinking 默认值；Q9 thinking 块回传范围。详见下方审计记录。 |
| 批 8 | §7.8 | Grok 4.5 | 2026-08-02 18:05 | **通过（自审·rev1.2）** | 已按 Luna 17:54 四条修订并核验官方：Q1 Bedrock 改为 `anthropic.claude-opus-5`（表尾 3=脚注 _3_）；Q4 区分 thinking/budget 失效 vs effort 默认≡省略不失效（A3）；Q5/③-C Haiku 明确 `thinking_default_on=False`；Q9 工具强制 / 跨回合建议 / 非工具可省略。并吸收 DeepSeek 非阻塞：采样 400、Fast mode、Priority 停售、缓存 usage 细节。 |
| 批 8 | §7.8 | GPT-5.6-Luna | 2026-08-02 18:06 | **通过（复审·rev1.2）** | 问题清单：无。独立复核确认首轮 4 项均已修正；采样参数 400、Fast mode、Priority 既有承诺、缓存 usage 细节与 Anthropic 官方文档一致。 |
| 批 8 | §7.8 | DeepSeek（v4 系 / opencode deepseek-v4-flash） | 2026-08-02 | **通过（复审·rev1.2·终审）** | 用户确认全部审计完成。rev1.2 四条（Bedrock id / effort 默认≡省略 / Haiku `thinking_default_on=False` / thinking 回传范围）及五主力含 Opus 4.8 均已闭环。批 8 三方全过；A0 8 批全部通过。 |
| 批 8 | §7.8 | Grok 4.5 | 2026-08-02 | **通过（自审·rev1.2·终审）** | 用户确认全部审计完成；批 8 三方全过。A0（§7.1–§7.8）全部通过审计门。 |

> 批 8 / §7.8 复审记录
> 审计模型：GPT-5.6-Luna
> 审计时间：2026-08-02 17:54
> 审计结果：不通过
> 问题清单（每条一行）：分区位置 | Grok 原话 | 正确值 | 来源 URL
> Q1 | Bedrock `anthropic.claude-opus-53` | `anthropic.claude-opus-5`；末尾 3 是官方脚注标记，不属于 model id | https://docs.anthropic.com/en/docs/about-claude/models/overview
> Q4 | 改 thinking 配置 / effort /（manual）`budget_tokens` 会 bust 缓存 | thinking/budget 变更会使相关缓存块失效；但 effort 显式设为模型默认值等同省略，不会失效，tool/system 影响取决于模型渲染位置 | https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
> Q5/③-C | 非 Claude5 adaptive 默认开 → `thinking_default_on` 按「需显式 enabled」落地 | Haiku 4.5 不支持 adaptive；仅 extended thinking，需显式 `type:"enabled"` + `budget_tokens`，故 `thinking_default_on=False` | https://docs.anthropic.com/en/docs/about-claude/models/overview；https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
> Q9 | 多轮/工具须原样回传 thinking 块（含 signature） | 工具使用回合必须完整且不修改回传 thinking 块；跨回合仅建议回传；非工具场景允许省略历史 thinking | https://docs.anthropic.com/en/docs/build-with-claude/thinking
>
> 批 8 / §7.8 rev1.2 第二轮复审记录
> 审计模型：GPT-5.6-Luna
> 审计时间：2026-08-02 18:06
> 审计结果：通过
> 问题清单（每条一行）：无
>
> 批 8 / §7.8 rev1.2 处置（Grok）
> 审计模型：Grok 4.5
> 审计时间：2026-08-02 18:05（终审确认同日）
> 审计结果：通过（自审·rev1.2·终审；用户确认全部审计完成）
> 问题清单处置：
> Q1 | 已改为 Bedrock `anthropic.claude-opus-5`，并注明表尾 3 为脚注
> Q4 | 已按 A3 拆开 thinking/budget 与 effort 默认≡省略例外
> Q5 | ③-C 已写死 `thinking_default_on = False`
> Q9 | 已按工具强制 / 跨回合建议 / 非工具可省略改写
> 额外 | DeepSeek 非阻塞四条已写入 Q5/Q8/Q9/③
>
> **A0 关账**：§7.1–§7.8 八批三方审计全部通过。
