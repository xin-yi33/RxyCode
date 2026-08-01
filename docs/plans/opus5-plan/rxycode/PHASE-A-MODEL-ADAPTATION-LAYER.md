# Phase A · 模型适配层（Model Adaptation Layer）

> **在整条路线中的位置**：本文件是 [`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的**后继扩展**，编号 Phase A。
> **前置条件**：主计划的 Phase 0（止血）与 Phase 1（Harness 说真话）**必须已完成**。原因见 §0.3。
> **后继**：[`PHASE-B-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-B-MULTI-AGENT-ORCHESTRATION.md)
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

> **2026-08-01 扩展说明（纯加法）**：本阶段新增 A0（Grok 模型调研开局卡）与 A12–A22（新增模型族 provider + 三维度优化卡）。原有 A1–A11 与 §0–§6 的内容一律不改，唯一例外是原散落在 A3/A4/§5 内的"Grok 查资料"段落已统一收敛为 A0 的指针（Grok 调研功能提取为独立任务卡，这是用户授权的唯一改动点）。

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
2. 审计方 = ① **Grok 4.5**（调研模型自审）+ ② **第三方非编码模型**（执行会话的 opencode 模型，当前为 `deepseek-v4-flash`；由用户触发暂停后进行审计）
3. 每份审计记录写入 §7.9 审计记录表，**必须包含三要素：审计模型名称 / 审计时间 / 审计结果（通过或不通过 + 问题清单）**。三要素缺一的记录视为不存在
4. 审计不通过 → 回该批重调研、重汇报、重审，直到两份审计都通过才允许下一批
5. 对应批审计通过后，该模型族的优化卡才允许开工（如批 1 通过 → A3/A22 可以填数值）；**8 批全部通过审计之前，禁止开始任何整体接线（A6）与跨模型优化卡（A7–A11、A19–A21）**

**与其它文档中 Grok 调研的关系（2026-08-01 跨文档 review 补充）**

1. **Phase C C4 的定价调研并入本卡**：`PHASE-C.md:601-619` 的 "Grok 的调研 prompt"（各家定价、缓存按写入/读取分别计价、推理 token 单独计价）与本卡 9 问模板的**第 7 问（定价）**重叠。执行规则：C4 所需的定价数据由本卡批 1–8 的第 7 问结论提供，**Phase C 不再单独做定价调研**；C4 中心表（`config/model_pricing.py`）直接引用 §7 各分区的定价结论（含 `as_of` 与来源 URL）。
2. **清单外模型族（如 xAI Grok）**：C4 调研清单含 xAI，而本卡 8 批未列。需要时按**批 9+** 追加，用同一 9 问模板、同一审计门（Grok 自审 + 第三方审计），通过后才允许对应优化卡开工。
3. **旧型号引用的取代**：本卡 §7 报告发布后，`PHASE-C.md:610`（DeepSeek chat/reasoner）等旧型号引用一律以 §7 为准，不在其它文档里另行维护型号清单。

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
- [ ] 8 批全部调研完成；§7.1–§7.8 每区含：调研记录表 / 九问结论 / 对 RxyCode 的含义 / 来源 URL
- [ ] §7.9 共 16 条审计记录（8 批 × 2 审计方），每条含审计模型名称 / 审计时间 / 审计结果，且全部通过
- [ ] 代码零改动
- [ ] 所有 `# TODO(grok→§7.X)` 注释指向的分区均已通过审计（代码注释是位置标记，数值填充在对应优化卡做）

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

**⚠️ 调研已由 A0 统一负责（2026-08-01 起）。** 本卡所需的全部数值（context window、function calling、reasoning、缓存字段、tokenizer）**以 A0 批 1 的调研报告（§7.1）为准**；§7.1 未通过 A0 审计门之前，本卡不得开始。下面代码里标了 `# TODO(grok)` 的常量即位置标记，用 §7.1 的结论替换，**并把来源 URL 写进注释**（新卡的标记写作 `# TODO(grok→§7.X)`，二者同义）。若 §7.1 报告与下文旧占位值不一致，一律以 §7.1 为准（下文旧占位值仅作结构示意，DeepSeek 已迭代到 v4 系，见 A22）。

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
补齐另外两个常用族。做法与 A3 完全一致，**数值以 A0 的调研报告为准（2026-08-01 起）**：Anthropic 看 §7.8，Qwen 看 §7.7；对应批未通过 A0 审计门之前，本卡不得开始。注意本卡只完成基础骨架，完整实现由 A17（Qwen）与 A18（Anthropic）补全。

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
   - `00-EXECUTION-PLAN.md:2383`：模型清单由"（DeepSeek / Claude / Qwen）"改为含新增族（OpenAI / Kimi / GLM / MiniMax / MIMO / Qwen / Anthropic / DeepSeek v4），工时由"3 周"改为扩展后的实际值
   - `rxycode/README.md:54`：同上（模型清单 + 工时）
   - 排期说明：A0 为纯文档卡不受排期影响，代码卡实际执行按接线请求插入（见新增卡一览铁律）

**完成判据**
- [ ] `docs/modules/providers.md` 存在，按它能独立加出一个新 provider
- [ ] 三份既有模块文档已更新
- [ ] `core/config.py` 死代码已删或已记入待办池（二选一，说明理由）
- [ ] `00-EXECUTION-PLAN.md:2383` 与 `rxycode/README.md:54` 的 Phase A 行已同步（2026-08-01 扩展）

---

### 新增卡一览（2026-08-01 扩展，全部纯加法）

> 以下 A12–A22 是本次扩展新增的任务卡。共同铁律：
> - **数值唯一来源是 A0 的调研报告（§7.X）**。每张卡开工前必须"精准找到自己对应的分区"读完，对应批未通过审计不得开工
> - 代码里用 `# TODO(grok→§7.X)` 标注"待调研数据填充"的位置；调研审计通过后按分区结论填充并补 URL
> - 沿用 MA2：每张卡做完跑一次 evals 基线比对，零回归
> - 沿用 MA4：不引入任何新的第三方 SDK，全部走 OpenAI 兼容端点
> - 沿用 MA5：不碰 `core/config.py` 的 `LLMConfig`（A11 处理）
> - **`agent_v2.py` 的改动走主计划 §11.7 的接线请求协议**（`00-EXECUTION-PLAN.md:2560-2582` 共享面三规则 P1/P2/P3，示例见 :2568-2580）：Phase A 窗口要改 `agent_v2.py` 时写 3–5 行"接线请求"由 Phase 2 窗口执行，不得直接改。A19/A20/A21 涉及 `agent_v2.py` 的步骤全部按此执行
> - **thinking 适配判断（2026-08-01 补充，全卡统一规则）**：每个 provider 卡按 §7 对应批第 5 问做判断——**适配（支持 thinking）→ `supports_reasoning=True` 且 `thinking_default_on=True`（默认打开）**；不适配/兼容端点不可控 → 保持 `False`（零注入）。`thinking_default_on` 全局默认 `False`（未适配前行为与现状一致）。前端 thinking 面板（`/thinking`、`_flush_thinking`）只是**展示**思维链，与模型 thinking 模式无关——面板开着模型没开=空转，模型开着面板关着=思维链不展示但仍在消耗 token
> - **排期立场**：A0 是纯文档卡，**不受 Phase 2 窗口排期限制**，可随时开工（`ENGINEERING-TIMELINE.md:191` 建议 Phase A 推后的对象是代码卡，不适用于零代码的 A0）；A12–A22 中需要 `agent_v2.py` 改动的卡，按接线请求插入 Phase 2 的 P3（Session）合并之后（`00-EXECUTION-PLAN.md:2520`）
> - **分工不变**：Grok 在 A0 里的调研与自审是 `MODEL-ASSIGNMENT.md:76` 原"查资料"角色的正式化，仍不写任何代码；第三方审计由用户指定的执行会话模型担任，不属于任何 Phase 的写代码分工

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

**与现有定价机制的关系（2026-08-01 review 补充）**：`utils/streaming.py` 的 `billing_amount`（:105-124）已从 `config.yaml` 的 `pricing` 段（`{model: {input: $/M, output: $/M}}`）读价。本卡的 `ModelPricing` 是 **provider 侧声明**的默认价（带 `as_of`/来源 URL），两者并存且优先级不同：**config 用户定价 > ModelPricing > 无**。本卡只在 `ModelCapabilities` 上挂载默认值，**不得修改 `billing_amount` 的现有行为**；两者的统一归 Phase C 的 `CostAccountant`（C4）。

**与 Phase C C4 的契约（2026-08-01 跨文档 review 补充，冲突调和）**：C4（`PHASE-C.md:529-543`）也会给 `ModelCapabilities` 加 `ModelPricing`，且其 `input_per_mtok`/`output_per_mtok` 是**必填**字段、定价存 `config/model_pricing.py` 中心表。本卡与其的调和规则：

1. **字段对齐**：本卡的 `ModelPricing` 是 C4 定义的**超集**（C4 无 `source_url`，本卡多此字段），其余字段名逐一相同
2. **必填 vs Optional 的语义**：C4 的必填 `float` 指**中心表条目内**的字段；本卡的 `None` 指"该模型尚未有官方定价"。Phase C 的 `CostAccountant.record` 读 `caps.pricing.input_per_mtok` 时必须处理 `None`（这正是 C4 测试 `test_missing_pricing_does_not_silently_count_as_zero` 的载体）——**不得把 None 静默当 0**
3. **优先级**：C4 中心表（`config/model_pricing.py`，用户维护）> 本卡 capabilities 上的 `ModelPricing` > 无
4. **数据流**：A0 批 1–8 的第 7 问（定价）结论即 C4 中心表与各 provider 默认价的共同数据源，Phase C 不再单独做定价调研（见 A0 与 C4 调研的关系）

**涉及文件**
- 新建 `tests/test_providers/test_openai_provider.py`（现有 `test_registry.py` 已有兜底测试，本卡扩之）
- 修改 `config/model_capabilities.py`（追加 `ModelPricing`，**只追加不改现有字段**）
- 修改 `core/providers/openai.py`、`core/providers/__init__.py`（注册）

**操作步骤**

1. `config/model_capabilities.py` 追加 `ModelPricing`（为 Phase C `CostAccountant` 预留；缺失价格不得静默当 0）：

```python
@dataclass(frozen=True)
class ModelPricing:
    """每百万 token 单价（美元）。Phase C 的 CostAccountant 用它做成本核算。

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
    #: 定价（Phase C 用）。默认空对象 = "未知"，不改变任何现有行为。
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
A4 只给了 Anthropic 的方向（"`prompt_variant="claude"`；prompt 缓存的 `cache_control` 语义与 OpenAI 不同，需要在 `supports_prompt_cache` 上体现"）。本卡补全：Claude 的 thinking block 语义、prompt caching 断点（最多 4 个断点、最小 1024 token 块、TTL 5 分钟/1h）、reasoning 内容剥离（Phase C 的 strip 环节会用）、以及 OpenAI 兼容端点下的能力边界（MA4 禁止引入 anthropic SDK，原生端点的完整断点支持标注为受限）。

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
| `ModelCapabilities.supports_vision` | Phase C 多模态 | Phase A 只占字段不实现，Phase C 填逻辑 |
| Provider 无状态单例（约束 DC2） | Phase B 多 Agent | 多个 Agent 会并发调用同一个 provider 实例，**不要在 provider 里存任何 per-request 状态** |
| `ModelCapabilities.prompt_variant` | Phase B 角色化 Agent | 不同角色的 Agent 可能用不同模型，变体机制要能按 agent 解析 |
| `AgentState._capabilities` | Phase B | 多 Agent 下每个 agent 的 capabilities 不同，state 注入要按 agent 隔离 |

> **2026-08-01 扩展追加的接缝**（新增字段，消费方与约束）：

| 预留（新增） | 给谁用 | 约束 |
|---|---|---|
| `ModelPricing`（A12） | **Phase C C4 成本核算** | 本卡定义是 C4（`PHASE-C.md:529-543`）的超集；C4 中心表优先级更高；`None` 必须显式处理（缺失不静默当 0，对齐 C4 判据） |
| `effort_presets`（A12/A21） | Phase B B10 难度路由、Phase C C11 评测矩阵 | 路由与评测可按 fast/balanced/deep 档位横向比较延迟与质量；空 dict = 不支持档位，禁止注入任何参数 |
| `cache_min_block_tokens` / `cache_ttl_s` / `cache_breakpoints`（A19） | Phase C C4 缓存定价、Phase 2 Session 消息链 | 断点布局只打在恒定内容末尾（≤4 个）；TTL 是 provider 侧语义，与 settings `cache.ttl`（死配置）无关 |
| `max_output_tokens` / `few_shot_policy` / `tool_send_policy` / `tool_output_token_limit`（A20） | Phase 2 Session 消息链、Phase B 角色化 Agent | 默认 `None` = 现状（全量）行为，任何消费方不得假定非 None |
| A0 调研报告（§7） | Phase C C4 定价表、A12–A22 全部数值、Phase D D4 图像 token 公式 | 数值唯一来源；对应批未通过审计不得使用 |

---

## §7 Grok 模型调研报告（A0 产物）

> **本章节由 A0 卡（2026-08-01 扩展）负责填充，按模型族分区。**
> 每个分区的数据是 A12–A22 等优化卡的**数值唯一来源**；对应分区未通过 §7.9 的审计之前，相关优化卡不得开工（A0 审计门）。
> 分区固定结构：① 调研记录表（批次/日期/调研模型/来源 URL）② 九问结论 ③ "对 RxyCode 的含义"（映射到 `ModelCapabilities` / `UsageFieldMap` / `ModelPricing` 字段的具体建议值）。

### §7.1 DeepSeek（A0 批 1）

> 状态：**待调研**。审计通过前，A3/A22 不得填充数值。

### §7.2 OpenAI（A0 批 2）

> 状态：**待调研**。审计通过前，A12 不得填充数值。

### §7.3 Kimi / Moonshot（A0 批 3）

> 状态：**待调研**。审计通过前，A13 不得填充数值。

### §7.4 GLM / 智谱（A0 批 4）

> 状态：**待调研**。审计通过前，A14 不得填充数值。

### §7.5 MiniMax（A0 批 5）

> 状态：**待调研**。审计通过前，A15 不得填充数值。

### §7.6 MIMO / 小米（A0 批 6）

> 状态：**待调研**。审计通过前，A16 不得填充数值。

### §7.7 Qwen（A0 批 7）

> 状态：**待调研**。审计通过前，A17 不得填充数值。

### §7.8 Anthropic（A0 批 8）

> 状态：**待调研**。审计通过前，A18 不得填充数值。

### §7.9 审计记录表（A0 每批审计写入）

> 审计三要素：**审计模型名称 / 审计时间 / 审计结果（通过或不通过 + 问题清单）**。三要素缺一的记录视为不存在。
> 审计方：① Grok 4.5（调研模型自审）② 第三方非编码模型（执行会话的 opencode 模型，当前 `deepseek-v4-flash`，由用户触发暂停后进行）。

| 批次 | 分区 | 审计模型 | 审计时间 | 审计结果 | 问题清单与处置 |
|---|---|---|---|---|---|
| 批 1 | §7.1 | Grok 4.5 | | 待审计 | |
| 批 1 | §7.1 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 2 | §7.2 | Grok 4.5 | | 待审计 | |
| 批 2 | §7.2 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 3 | §7.3 | Grok 4.5 | | 待审计 | |
| 批 3 | §7.3 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 4 | §7.4 | Grok 4.5 | | 待审计 | |
| 批 4 | §7.4 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 5 | §7.5 | Grok 4.5 | | 待审计 | |
| 批 5 | §7.5 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 6 | §7.6 | Grok 4.5 | | 待审计 | |
| 批 6 | §7.6 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 7 | §7.7 | Grok 4.5 | | 待审计 | |
| 批 7 | §7.7 | opencode（deepseek-v4-flash） | | 待审计 | |
| 批 8 | §7.8 | Grok 4.5 | | 待审计 | |
| 批 8 | §7.8 | opencode（deepseek-v4-flash） | | 待审计 | |
