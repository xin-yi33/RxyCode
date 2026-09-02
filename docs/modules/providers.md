# providers/ - Provider 策略层

## What Is This Module?

provider 描述"这一族模型和 OpenAI 默认行为有什么不同"，无状态单例，被多个 Agent 并发使用。
默认实现 == Phase A 之前的 OpenAI 行为；未识别模型落到 OpenAIProvider。

注册表（`core/providers/__init__.py`）当前登记：`OpenAIProvider`、`DeepSeekProvider`、
`KimiProvider`、`GLMProvider`、`MiniMaxProvider`、`MIMOProvider`、`DoubaoProvider`、
`AnthropicProvider`、`QwenProvider`、`MuseSparkProvider`、`Hy3Provider`，兜底
`_FALLBACK = OpenAIProvider()`。

## ModelCapabilities 字段表（含义 / 默认值 / 来源）

字段默认值逐字取自 `config/model_capabilities.py`（`ModelCapabilities` dataclass）。

| 字段 | 含义 | 默认值 | 来源/改写处 |
|---|---|---|---|
| provider | 标识（openai/deepseek/doubao...） | `"openai"` | 各 provider capabilities() 里的 `provider=self.name` |
| context_window | 上下文窗口 token | `256_000` | provider 声明（如 DeepSeek `1_048_576`）或配置覆盖 |
| compaction_threshold | 压缩阈值 | `232_000` | 同上（DeepSeek `943_718` ≈ 1M 的 90%） |
| tokenizer | 估算方式（tiktoken:xxx / chars:ratio） | `"tiktoken:o200k_base"` | 同上（DeepSeek/Doubao 用 `"chars:2.0"`） |
| supports_function_calling | 原生 FC | `True` | 同上 |
| supports_reasoning | 推理模型 | `False` | 同上（DeepSeek 按模型名决定；Doubao `True`） |
| accepts_temperature | 是否接受 temperature | `True` | 同上（DeepSeek thinking 模式下 `False`） |
| supports_vision | 多模态输入 | `False` | 同上 |
| supports_prompt_cache | 前缀缓存 | `True` | 同上 |
| structured_output | function_calling / json_in_text | `"function_calling"` | 同上 |
| prompt_variant | 提示词变体键 | `"default"` | 同上（A9 机制） |
| usage_fields | 字段名映射（cache_read/reasoning） | 见 UsageFieldMap | 同上 |
| extra_body | 透传参数 | `{}` | 同上 |
| effort_presets | 抽象档位映射 fast/balanced/deep → 厂商参数（A21） | `{}` | 同上（DeepSeek/OpenAI/Kimi-k3/GLM-5.2 非空） |
| **effort_options** | **厂商档位全集（/effort 命令与设置页档位列表；空 = 不支持档位选择，2026-08-12）** | `()` | 同上（DeepSeek `("low","high","max")`、OpenAI `("low","medium","high")`、Kimi-k3 `("low","high","max")`、GLM-5.2 `("max","xhigh","high","medium","low","minimal","none")`） |

`effort` 注入裁决（2026-08-13，luna audit2 收紧）：`llm_kwargs` 中 effort 命中 `effort_options` → 直接透传厂商档位；否则命中 `effort_presets` keys（fast/balanced/deep）→ 走抽象映射；**都不命中 → 不注入**（OpenAI 原 A21 的 `get(effort, "medium")` 默认已移除——gpt-5.6 省略 reasoning_effort 时厂商默认即 medium，行为等价，仅收紧语义）。

`UsageFieldMap` 默认值（`config/model_capabilities.py`）：

| 字段 | 默认值 |
|---|---|
| cache_read_flat | `("prompt_cache_hit_tokens",)` |
| cache_read_nested | `(("prompt_tokens_details", "cached_tokens"), ("input_token_details", "cache_read"))` |
| reasoning | `("reasoning_content",)` |

能力优先级（`model_capabilities.py` 模块 docstring）：用户在模型配置里显式写的字段 >
Provider 探测结果 > Provider 默认值。所有 provider 的 `capabilities()` 都基于
`DEFAULT_CAPABILITIES` 做 `dataclasses.replace()`，最后
`caps.merged_with_overrides(model_config)` 应用配置覆盖（只认本 dataclass 已声明的
字段名，未知字段忽略，因为 model_config 里还混着 base_url / api_key 等非能力字段）。
> 覆盖规则：只接受 `ModelCapabilities` 的字段名（`usage_fields` 除外——不可通过覆盖改写，与 docs/modules/config.md 一致）；未知字段（如 base_url / api_key）忽略。

## 三条不可违反的设计约束（PHASE-A §2.2）

| # | 约束 | 原因 |
|---|---|---|
| DC1 | `BaseProvider` 的默认实现 = 当前 OpenAI 行为；任何未识别 model 落到 OpenAIProvider，行为与今天**逐字节一致** | 保证零回归（A6 前行为完全保留） |
| DC2 | Provider 只描述差异、不持有状态；所有实例是无状态可缓存单例 | Phase D/E 的 Child/Agent Runtime 并发使用 |
| DC3 | 能力元数据优先级：用户显式配置 > provider 探测 > provider 默认值 | 用户接中转站时自动探测常猜错，配置写死永远赢 |

代码落点：DC1 → base.py 默认实现与 `_FALLBACK = OpenAIProvider()`（providers/__init__.py）；DC2 → 模块级单例（无实例状态）；DC3 → `ModelCapabilities.merged_with_overrides` + `resolve_model_config`。

## Provider 解析顺序

`providers.resolve(model_config)`（`core/providers/__init__.py`）：

1. model_config 里显式写了 `provider` 字段 → 按名字直取（`_BY_NAME`）
2. 依次问每个已注册 provider 的 `matches(base_url, model_name)`
3. 全部落空 → OpenAIProvider（行为等同 Phase A 之前）

注册顺序即匹配优先级（越具体越靠前）；新增 provider 注册进 `core/providers/__init__.py`

> **调研 vs 实现（各家族状态）**：
>
> | 家族 | 调研 | 实现 | 当前路由 |
> |---|---|---|---|
> | OpenAI | §7.2 | OpenAIProvider（A12：兜底 + 显式能力） | 已注册 |
> | DeepSeek | §7.1 | DeepSeekProvider（A22 v4 适配） | 已注册 |
> | Kimi | §7.3 | KimiProvider | 已注册 |
> | GLM | §7.4 | GLMProvider（官方/Ark 走 `clear_thinking`；`opencode.ai` 网关剥掉该字段和 `reasoning_effort`，避免 Console Go `Extra inputs` 400） | 已注册 |
> | MiniMax | §7.5 | MiniMaxProvider | 已注册 |
> | MIMO | §7.6 | MIMOProvider | 已注册 |
> | Anthropic | §7.8 + 2026-08-25 三协议专项 | AnthropicProvider（官方 Host 走原生 Messages，兼容代理保持其 OpenAI 契约） | 已注册 |
> | Qwen | §7.7 | QwenProvider | 已注册 |
> | Doubao | §7.9 | DoubaoProvider（A23） | 已注册 |
> | Muse Spark | 2026-08-24 专项调研 | MuseSparkProvider（Go 上仅 Contributor 走 Responses） | 已注册 |
> | HY3 | 2026-08-25 专项调研 | Hy3Provider（只匹配正式版，保持 Chat） | 已注册 |

## 三种 LLM 传输与 URL 规范化（2026-08-25）

Provider 通过 `transport_candidates(model_config)` 返回有序接口候选：

- 规范值只有 `openai_chat`、`openai_responses`、`anthropic_messages`；
- 默认 `("openai_chat",)`：完全保留原 Chat Completions 行为；
- 已确认 Responses 的路由返回 `("openai_responses", "openai_chat")`；
- Anthropic 官方 Host 返回 `("anthropic_messages",)`，不跨到 OpenAI 接口；
- `api_transport: openai_chat` 是显式兼容开关，只走 Chat；
- 配置解析边界兼容旧值 `chat`/`responses`，运行时统一转换成规范值；非法或空候选失败关闭。

Responses 请求构造和 SSE 解析复用 `langchain-openai` 的
`ChatOpenAI(use_responses_api=True)`。`AgentV2` 只把公开 `AIMessageChunk` 归一成
既有内部 chunk，不实现 provider SSE grammar。

Anthropic 官方 Host 使用 `langchain-anthropic` 的 `ChatAnthropic`。该集成负责
`x-api-key`、`anthropic-version`、system/content block、tool schema、tool use/result
与 SSE；RxyCode 只从公开 `AIMessageChunk` 归一 text、thinking、tool call、usage 和
stop reason。缺少依赖时明确报错，不静默降级到 OpenAI client。

`config/model_endpoint.py` 是持久化、连接探测和运行时共同使用的 URL 边界：它把完整
`/chat`、`/chat/completions`、`/responses`、`/messages` 精确还原为 API root，再由
对应 SDK 或探测层只拼接一次资源路径（``/chat`` 是 Chat Completions 别名，探针与
OpenAI SDK 都落到 ``/chat/completions``）。多段网关前缀会保留；协议与完整资源冲突、
query、fragment、userinfo、非法端口，以及携带凭据的明文 HTTP 均在联网前拒绝。

回退只允许在尚未产生 text/reasoning/tool output 时处理明确的 endpoint/protocol
unsupported：只有 400/404/405/422 且错误短语明确指向 endpoint、route、protocol 或命名 API 时才回退；对于 SDK 明确暴露的 `/responses` 或 `/chat/completions` 请求路径，FastAPI/nginx 的通用 `Not Found`/`Invalid URL` 也可作为端点不存在证据；没有请求路径证据的普通 404/405 保持失败。认证、DataPolicy、限流、网络、
超时、5xx、内容安全、普通参数错误以及部分输出后的错误都不换接口。

P2 Responses-first：OpenAI 官方 Host、火山方舟官方 Host 上的 Doubao、
DashScope/Qwen 官方 Host 与预设、OpenRouter、Groq 预设和 Other/custom。DeepSeek 官方
Host 保持 Chat Completions（thinking 工具轮必须回放 ``reasoning_content``；Responses
的 ``reasoning_text`` item 尚未能按原生 item 重放）。火山方舟托管的
第三方模型不因 Ark Host 被整体切换；Together 与缺少官方 Responses 证据的预设保持
Chat；OpenCode Go 普通模型也不整体切换，由精确 Provider 单独声明。

Qwen 在 Chat 路径继续使用 `extra_body.enable_thinking`；在 Responses 路径改用
`reasoning.effort`。自动预设不包含仅北京/新加坡支持的 `xhigh`、`max`，避免跨地域配置
被路由为上游不接受的档位。

## Muse Spark / HY3 / OpenCode Go（2026-08-25）

`muse-spark-1.1`、`muse-spark-1.2` 和
`muse-spark-1.2-contributor` 会被 Provider 家族识别。识别不等于网关可用：
OpenCode Go 2026-08-24 的公开 `/models` 在该家族中只暴露 Contributor，并把它固定到
`/v1/responses`。因此 `transport_candidates()` 只对“OpenCode Go + 精确 Contributor”
返回 Responses-first；直接 Meta 配置和 Go 上的另外两个 ID 不会被强制改协议。

- Meta 模型页需要登录，本轮没有可公开复核的 1M context、131072 max output 或五档
  effort 证据；三个 ID 使用保守数值能力，catalog 不发布未确认的精确上限。
- OpenCode Go 没有公开 Muse effort 请求契约，因此 Go 请求不自动发送
  `reasoning_effort` 或 `thinking`。
- RxyCode 隐式 temperature 0.7 省略，用户显式值保留。
- Contributor 的 Go 路由使用自动前缀缓存、零 `cache_control` 断点；Responses cached usage 路径是
  `input_tokens_details.cached_tokens`。
- Contributor 允许提示词/补全用于 Meta 后续训练且受区域限制，不能作为默认。
- `Hy3Provider` 只精确匹配正式 `hy3`，声明 256k context / 128k max output；preview
  与近似 ID 不匹配。它保持 OpenCode Go 既有 Chat Completions 请求形状，不发送
  TokenHub 直连的 thinking/reasoning/echo 扩展字段。
- 现有 OpenCode 上游兼容记录显示 Contributor function tool 名称超过 64 字符会被
  拒绝；Muse provider 在联网前防御性验证，不截断名称。该记录不是模型能力来源。
- Responses 流兼容独立 `response.output_text.delta`；不能要求上游一定先发送
  `output_item.added`。
- Responses 只有观察到 LangChain terminal metadata 的 `status=completed` 才映射为
  `stop`；`incomplete` 映射为 `length`/`content_filter`，失败事件被 LangChain 丢弃后
  产生的无状态合成 terminal 以及缺失合法终态都会失败关闭。

三协议和 URL 的本地证据分别在
`tests/test_providers/test_transport_routing.py`、
`tests/test_providers/test_model_endpoints.py` 与
`tests/test_providers/test_anthropic_transport.py`。这些是 mock/wire 与单元证据，不代表
外部服务 live 已通过。完整依据与验收见
`docs/agent/research/2026-08-24-opencode-go-hy3-muse-provider.md` 和
`docs/agent/plans/PHASE-MUSE-SPARK-OPENCODE-GO.md`。


## 新增一个 Provider 的完整流程

### 完整流程（照抄 PHASE-A §5 扩展手册原文）

> 原文出处：本地开发文档 PHASE-A §5 扩展手册（`docs/plans/` 不入 GitHub）。

## §5 扩展手册：加一个新 Provider

> Phase A 之后，接一个新模型族的标准流程。**这一节是长期使用的，不是一次性任务。**

**第 1 步 · 查资料**（交给 Grok，由 A0 统一执行，2026-08-01 起）

调研不再在卡内临时进行，统一由 **A0** 承担（分批调研 + 每批审计 + §7 分区汇报）。新增模型族时：

1. 在 A0 的调研清单里追加一批（或复用已有批次），按 A0 的 9 问模板调研
2. 结果写入 §7 新分区，通过 A0 的审计门（Grok 自审 + 第三方非编码模型审计，§7.10 留档）
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

### 快速要点（同流程的精简版）

1. §7.x 调研通过（A0 审计门：Grok 自审 + DeepSeek + GPT-5.6-Luna 双验证，记录入 §7.10 批表）
2. 新建 `core/providers/<name>.py`：`matches()` 精确（避免抢同端点其他模型）、`capabilities()` 基于 `DEFAULT_CAPABILITIES` replace、`UsageFieldMap` 按实测
3. 注册 `_PROVIDERS`（越具体越靠前）；测试（matches 识别/不抢/能力字段/overrides）
4. evals 矩阵验证（A10 `--models` 机制）

（实例：A23 DoubaoProvider 全流程，见 PHASE-A §7.9 与 core/providers/doubao.py）
## 常见问题

- 仓库 [issues #2](https://github.com/xin-yi33/RxyCode/issues/2)（provider 相关常见问题，对应 PHASE-A §2.2 设计约束语境；已核实可访问）
- 本项目实测踩坑：
  ① usage/reasoning 字段盲试 → 能力映射委派（A8）；
  ② import-time 绑定 load_config 使配置补丁失效（eval harness 需补丁 utils.shell 等模块全局名）；
  ③ matches 写太宽抢走同端点其他模型（doubao vs minimax/glm）；
  ④ api_key_env 环境变量缺失 → 静默无 key；
  ⑤ 免费配额 429 与计费口径（官方 CNY vs 转发商）

---

## DeepSeek v4 会话续接（A22，§7.1）

deepseek-v4-flash / deepseek-v4-pro 是 thinking 默认开启的推理模型（thinking: {"type":"enabled"} 默认、effort 默认 high）。带 tools 的轮次**必须**把上一轮 assistant 消息的 reasoning_content 原样回传（_to_openai_messages 保留该字段），否则 API **400**（§7.1 问 5，S3/S4 官方明确）。`role=tool` 也必须紧跟带匹配 `tool_calls` 的 assistant；历史里的孤儿 tool 消息会被丢掉，未完成的并行 `tool_calls` 会补一条 stub tool 结果，避免 `Messages with role 'tool' must be a response to a preceding message with 'tool_calls'` 以及 `insufficient tool messages following tool_calls message`。

- 过渡期别名：deepseek-chat（non-thinking）/ deepseek-reasoner（thinking）在 2026-07-24 后指向 v4-flash 对应档（§7.1 S13）；providers.md 支持表仍列出以便旧配置平滑迁移。
- thinking 模式下 temperature / top_p / presence_penalty / frequency_penalty 全部无效（不报错但被忽略，§7.1 问 5）；accepts_temperature=False。
- effort 档位：low/high/max（fast→low、balanced→high、deep→max；**v4-pro 与 v4-flash 一致：low→low、medium→high、high→high、xhigh→high、max→max，2026-08-13 V4-Pro-0813 官方公告**，§7.1 S3 映射表复核更新）。
- 缓存：自动 disk 缓存，顶层 usage.prompt_cache_hit_tokens；命中 0.1x 计费；无显式 cache_control 断点（§7.1 问 4）。
- 精确 token 数始终以 API usage 为准（chars:2.0 为项目侧估算，非官方 tokenizer）。
