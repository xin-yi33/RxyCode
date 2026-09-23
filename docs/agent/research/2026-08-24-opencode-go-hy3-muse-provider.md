# OpenCode Go、HY3、Muse 与 OpenAI/Anthropic 接口层调研报告

> 初稿日期：2026-08-24
> 按负责人新方案修订：2026-08-25
> 面向项目：RxyCode
> 安全：本文不包含 API Key、Authorization、Bearer 值或可识别凭据片段。

## 1. 结论

负责人给出的最终任务不是“只让 Muse 特判走 Responses”，而是三层改造：

1. P0：接口层同时表达 `openai_chat`、`openai_responses`、
   `anthropic_messages`；接口选择由 LLM Provider 传入。
2. P0：保留 OpenAI Chat Completions，新增 OpenAI Responses；再新增 Anthropic 原生
   Messages 执行路径。三种协议不能共用同一个请求体或响应解析假装兼容。
3. P0：规范化用户填写的 Base URL。OpenAI Chat 最终请求
   `/v1/chat/completions`，Responses 最终请求 `/v1/responses`，Anthropic 最终请求
   `/v1/messages`；末尾资源名写或不写都不能重复拼接。
4. P0：Other/custom Base URL 不确定 OpenAI 接口时，Responses 优先探测；只有明确接口不支持
   且未产生输出时才尝试 Chat。两者均不支持时返回组合错误。
5. P1：新增 Muse Spark 与正式版 HY3 Provider。Muse Contributor 在 OpenCode Go 上
   优先 Responses；HY3 保持已经联通的 Chat 请求形状。
6. P2：审计其他预设；只有存在官方 Responses 依据的预设才改为 Responses 优先。

这意味着：

- 不是所有模型都同时支持所有接口；Provider 返回的是“这个具体路由允许尝试的协议”。
- 不是全面改用 Responses；Chat 是兼容基线，现有 Chat 代码不删除、不重写。
- 不自己实现 Responses SSE；继续使用 `langchain-openai` 组包和解析。
- Anthropic Messages 是第三种协议，不是 OpenAI Chat 的另一个 URL；应使用成熟的
  Anthropic/LangChain 集成处理 Messages content block、tool use 和流事件。
- `403 DataPolicyError` 是外部工作区政策条件，不是网络问题，也不是可回退的接口错误。

## 2. 调研方法和证据边界

证据优先级：

1. 模型厂商与网关官方文档；
2. 官方 SDK/上游 Provider 源码；
3. 本项目 mock/wire、回归和 live 结果；
4. GitHub issue 只用于兼容风险，不用于推断模型性能或参数。

必须区分三类事实：

| 事实类型 | 示例 | 能否直接决定 RxyCode 请求体 |
|---|---|---|
| 模型能力 | HY3 256k context、128k max output | 只能用于限额和能力声明 |
| 厂商直连接口 | TokenHub 的 reasoning/echo 字段 | 只有 RxyCode 直连该接口时才能使用 |
| 网关契约 | OpenCode Go 为某模型公布 Chat 或 Responses | 决定本项目经该网关的接口和字段 |

性能、速度、代码能力必须由基准或真实调用实测；本报告不根据宣传材料写性能排名。

## 3. RxyCode 现状与根本问题

项目后端已经使用 LangChain/LangGraph，模型对象由 `ChatOpenAI` 构建。但实时工具循环
`AgentV2._raw_stream()` 历史上固定调用 OpenAI SDK 的
`chat.completions.create()`。因此只在 Provider 的 `llm_kwargs()` 增加
`use_responses_api=True`，不能保证所有真实工具轮都走 Responses。

实施前的旧设计以及负责人最新 P0 暴露出四个缺口：

1. Provider 只有“是否使用 Responses”的布尔决定，没有表达“首选接口 + 安全后备接口”。
2. Other/custom 连接探测固定单一接口；接口选错与权限失败混在一起，既可能误拒绝正确
   配置，也可能用错误回退掩盖 403 等真实原因。
3. `normalize_provider_base_url()` 目前只去除末尾 `/`，不能接受用户填写的
   `/v1/chat`、`/v1/chat/completions`、`/v1/responses` 或 `/v1/messages` 后再还原成安全
   API root；SDK 继续拼接时可能形成重复资源路径。
4. `AnthropicProvider` 已有能力、缓存和参数约束，但 Agent 主执行层仍由 `ChatOpenAI` 和
   OpenAI raw client 驱动，不能认定 Anthropic 原生 `/v1/messages` 已完成。

目标抽象应把协议说完整：Provider 返回 `("openai_chat",)`、
`("openai_responses", "openai_chat")` 或 `("anthropic_messages",)`。可在迁移期兼容旧值
`chat`/`responses`，但核心层不得靠模型名决定协议。

本轮实现已按该边界补齐：规范协议及迁移逻辑集中在 `config/model_transport.py`，URL
边界集中在 `config/model_endpoint.py`，配置解析、持久化、探测和 Agent client 创建均
复用这些纯函数。此结论来自本项目单元与 mock/wire 测试，不是外部服务 live 结论。

## 4. 三种接口协议与 URL 边界

### 4.1 OpenAI Chat 路径

保持现有行为：

- 用户可填：API root（如 `https://host/v1`）、`/v1/chat` 别名或完整
  `/v1/chat/completions`；
- 最终 endpoint：`/v1/chat/completions`；
- 请求字段：`messages`、`max_tokens`；
- 实时工具循环仍使用原来的 OpenAI SDK Chat client；
- 原有模型默认不改变接口。

### 4.2 OpenAI Responses 路径

新增行为：

- 用户可填：API root（如 `https://host/v1`）或完整 `/v1/responses`；
- 最终 endpoint：`/v1/responses`；
- 请求概念：`input`、`max_output_tokens`；
- `langchain-openai` 的 `ChatOpenAI(use_responses_api=True)` 负责请求转换、tool 转换和
  Responses SSE 解析；
- RxyCode 只把公开 `AIMessageChunk` 归一成项目已有的 `choices[0].delta` 内部格式。

归一层不是另一套 SSE parser。它负责保持项目内部契约，并检查 completed、incomplete、
failed 和缺失合法终态，避免错误事件被合成 terminal 后误判成功。

### 4.3 Anthropic Messages 路径

新增行为：

- 用户可填：Anthropic API root（如 `https://api.anthropic.com/v1`）或完整
  `/v1/messages`；
- 最终 endpoint：`/v1/messages`；
- 鉴权和版本头遵循 Anthropic Messages 契约，不复用 OpenAI 请求头假装兼容；
- 请求使用 `messages`、`system`、Anthropic tool schema；响应处理 `content[]`、
  `tool_use`、`tool_result`、`stop_reason` 和 usage；
- 优先复用 `langchain-anthropic`/Anthropic SDK 的公开流对象，不手写 Anthropic SSE。

这条路径本轮已实现：精确的 Anthropic 官方 Host 只返回
`("anthropic_messages",)`，`AgentV2` 构造 `ChatAnthropic`，不构造 OpenAI client。
MockTransport 观察到 root 和完整 `/v1/messages` 两种配置均只请求一次
`/v1/messages`，并验证了 Anthropic 鉴权/版本头、system、图像、tool schema、历史
`tool_use`/`tool_result`、文本流、工具流、usage 和 stop reason。协议错误不跨到 OpenAI；
缺失合法终态失败关闭。这里仍只是本地 wire 证据，没有在本轮调用 Anthropic 公网。

### 4.4 URL 自动补全与规范化

规范化必须发生在持久化和创建 SDK client 之前，并输出“API root + 协议类型”，不能把
完整资源 URL 原样交给 SDK 后再次拼接。

| 用户输入示例 | Provider 协议 | 规范化 root | 最终请求 |
|---|---|---|---|
| `https://host/v1/chat` | `openai_chat` | `https://host/v1` | `/v1/chat/completions` |
| `https://host/v1/chat/completions` | `openai_chat` | `https://host/v1` | `/v1/chat/completions` |
| `https://host/v1` | `openai_responses` | `https://host/v1` | `/v1/responses` |
| `https://host/v1/responses` | `openai_responses` | `https://host/v1` | `/v1/responses` |
| `https://host/v1` | `anthropic_messages` | `https://host/v1` | `/v1/messages` |
| `https://host/v1/messages` | `anthropic_messages` | `https://host/v1` | `/v1/messages` |

必须保留网关前缀，例如 `https://opencode.ai/zen/go/v1/responses` 只能去掉末尾
`/responses`，不能误删 `/zen/go`。协议与显式资源路径冲突时应在联网前报错，不能静默
改成另一套协议。

### 4.5 安全回退

可以回退的证据必须是“接口本身不支持”：

- 400、404、405、422 且错误短语明确指向 endpoint、route、protocol 或命名 API 不支持；
- 或错误明确要求改用
  `/responses`、`/chat/completions`。

以下情况禁止回退：

- 401/403、DataPolicy、Region、内容安全；
- 408/429、网络、超时、5xx；
- 普通参数、工具 schema、模型 ID 错误；
- 已经产生 text、reasoning 或 tool call。

原因：这些错误换接口通常不会修复，还可能产生第二次计费、隐藏真实错误，或在部分工具
输出后造成重复执行。

## 5. HY3 调研和适配裁定

### 5.1 已确认模型属性

腾讯 TokenHub 正式版模型表列出：

| 模型 | context | 最大输入 | 最大输出 | 模型能力 |
|---|---:|---:|---:|---|
| `hy3` | 256k | 192k | 128k | 深度思考、结构化输出、Function Calling、Cache |

这些值可用于 `Hy3Provider.capabilities()` 和正式版 catalog，但不自动授权把 TokenHub
直连扩展字段发送给 OpenCode Go。

### 5.2 Provider 决定

按负责人 P1 要求新增 `Hy3Provider`，但只精确匹配 `hy3`：

- `hy3-preview` 不适配，也不做 family 模糊匹配；
- OpenCode Go 路由保持 Chat Completions；
- 不改变原来成功调用的 `messages` / `max_tokens` wire；
- 不自动发送 `thinking`、`reasoning_effort`、`reasoning_content`、
  `mandatory_echo`、`previous_response_id` 等 TokenHub 直连字段。

“新增 Hy3Provider”与“HY3 继续走 Chat”并不冲突：Provider 是能力和路由策略身份，不
代表必须新增协议或修改成功的请求体。

## 6. Muse Spark 调研和适配裁定

### 6.1 模型和网关边界

Provider 家族识别范围：

- `muse-spark-1.1`
- `muse-spark-1.2`
- `muse-spark-1.2-contributor`

识别不等于当前 OpenCode Go 可调用。当前可复核的网关路由承诺只用于
`muse-spark-1.2-contributor`；未公开复核的 Standard 型号不能写入精确 context、max
output、effort 或网关可用性承诺。

### 6.2 接口裁定

OpenCode Go 的 Contributor 路由使用 Responses。因此 Muse Provider 对“精确
`opencode.ai` Host + 精确 Contributor ID”返回：

```python
("openai_responses", "openai_chat")
```

Chat 是窄回退候选，不是正常首选。只有网关明确说 Responses endpoint/protocol 不支持，
且没有输出时才尝试 Chat。历史真实调用到达 Responses 后返回 403 DataPolicyError，说明
接口已到达但工作区未同意 Contributor 数据政策；这种 403 必须原样失败，不能回退。

### 6.3 当前保守模型约束

| 项目 | RxyCode 裁定 |
|---|---|
| context/max output | 未公开复核时不发布精确值 |
| effort/thinking | OpenCode Go 无明确契约时不自动注入 |
| temperature | 隐式默认值不冒充用户显式选择 |
| function calling | 使用通用 function schema；tool name >64 在联网前报错 |
| cache | 只记录已确认的自动缓存元数据，不虚构显式断点 |
| DataPolicy/地区 | 外部权限条件；不得当成网络或 Provider 缺陷 |

## 7. 现有预设 Responses 支持审计（P2）

审计原则：OpenAI-compatible 只证明 Chat 兼容，不能推断 Responses。只有官方资料明确
存在 `/responses` 或 Responses API 时才设为优先。

| 预设/Host | 裁定 | 依据状态 |
|---|---|---|
| OpenAI 官方 Host | Responses → Chat | 官方建议推理、工具和多轮场景采用 Responses |
| DeepSeek 官方 Host | Responses → Chat | 官方 create-response 文档 |
| 火山方舟上的 Doubao（官方 Ark Host） | Responses → Chat | 官方 Responses 示例明确使用 Doubao；不外推到 Ark 托管的每个第三方模型 |
| DashScope/Qwen 预设及官方 Host | Responses → Chat | 官方 OpenAI-compatible Responses API 文档 |
| OpenRouter | Responses → Chat | 官方 Responses endpoint |
| Groq | Responses → Chat | 官方 Responses API（Beta） |
| Other/custom | Responses → Chat | 能力未知，通过窄回退安全发现 |
| Together | Chat | 官方兼容说明明确不支持 Responses |
| Moonshot/Kimi | Chat | 本轮未找到足够官方 Responses 证据 |
| Zhipu、SiliconFlow | Chat | 本轮未找到足够官方 Responses 证据 |
| OpenCode Go、Zen 普通模型 | Chat | 按具体网关模型路由声明，不批量推断 |

DashScope/Qwen 的 Responses 参数与 Chat 不同：官方建议用 `reasoning.effort`，并说明
`enable_thinking` 后续将不再支持。因此 Provider 在 Responses 路径移除
`enable_thinking`；跨地域自动档位限制为 `none/minimal/low/medium/high`，不自动选择只在
北京和新加坡支持的 `xhigh/max`。

Host 路由必须用 URL parser 的 `hostname` 精确判断，避免
`https://api.openai.com.attacker.example` 或 userinfo 形式造成误识别。

## 8. 测试分层与结果解释

| 层 | 能证明什么 | 不能证明什么 |
|---|---|---|
| 单元测试 | Provider 识别、候选顺序、错误分类 | 外部服务可用性 |
| mock/wire | 请求形状、chunk 归一、终态 | 真实网关模型输出 |
| 压力测试 | 本地并发、任务泄漏、稳定性 | 真实限流与地区策略 |
| live HY3 | 本轮正式版 Chat 真调用 | Muse 可用性 |
| live Muse | Contributor 真实输出和工具流 | Meta Standard 型号属性 |

历史结果：HY3 曾通过真实 smoke；Muse Contributor 曾到达 Responses 路由后返回 403
DataPolicyError。后者证明路由到达和外部授权缺失，不能写成 Muse 成功，也不能归因于
V2Ray 或普通网络限制。

本轮结果边界：三协议、URL 规范化和 Anthropic Messages 均完成本地单元/mock/wire
验证（三协议专项 86 passed，Provider 全套 607 passed）；未运行需要真实凭据的 live。
HY3 本轮 live 仍受安全凭据与预算条件限制；Muse Contributor 还受 workspace
DataPolicy 与地区条件限制。历史 live 不提升为本轮通过。

## 9. 风险与建议

1. Contributor 涉及数据使用授权，必须由 workspace owner 明确决定；RxyCode 不自动
   接受政策，也不把 Contributor 设为静默默认模型。
2. `api_transport: openai_chat` 保留为运维兼容开关，遇到上游 Responses 回归时可不改代码降级；迁移期兼容旧值 `chat`。
3. 不对超时/5xx自动换接口；这类问题应进入原有 retry/circuit breaker，不能混入协议发现。
4. 新增 Responses-first 预设必须提供官方 URL、审计日期、正反例测试。
5. live 压测要单独设置预算和并发上限，凭据只从环境变量读取。
6. PR 前应同时审查代码、调研文档、开发任务卡、Provider 模块文档，防止旧结论残留。
7. 本机 Python 3.14 与当前 Starlette 测试依赖存在 `TestClient(client=...)` 版本不匹配；
   该环境问题不应伪装成本功能通过。PR/CI 应在项目标准 Python/锁定依赖上补跑完整测试。

## 10. 主要来源

- [腾讯 TokenHub 模型列表](https://cloud.tencent.com/document/product/1823/130051)
- [腾讯混元 OpenAI 兼容接口](https://cloud.tencent.com/document/product/1729/111007)
- [OpenCode Go 官方说明与模型端点表](https://opencode.ai/docs/go/)
- [Meta Models](https://ai.developer.meta.com/docs/models/)
- [OpenAI 模型与 Responses 指南](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI Chat Completions API](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions)
- [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [LangChain ChatAnthropic 集成](https://docs.langchain.com/oss/python/integrations/chat/anthropic)
- [langchain-anthropic 包](https://pypi.org/project/langchain-anthropic/)
- [DeepSeek Create Response](https://api-docs.deepseek.com/api/create-response/)
- [火山方舟 Responses API](https://www.volcengine.com/docs/82379/1958524?lang=zh)
- [阿里云百炼：通过 OpenAI-compatible Responses API 调用 Qwen](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses)
- [OpenRouter Responses API](https://openrouter.ai/docs/api/api-reference/responses/create-responses)
- [Groq Responses API](https://console.groq.com/docs/responses-api)
- [Together OpenAI compatibility](https://docs.together.ai/docs/inference/openai-compatibility)
- [OpenCode Provider 源码](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/provider/provider.ts)

## 11. 调研自审

- [x] 明确 Chat 保留、Responses 新增，不是全面重写。
- [x] 明确由 Provider 传入接口候选，核心层不按模型名路由。
- [x] 明确 OpenAI Chat/Responses 与 Anthropic Messages 是三种接口协议。
- [x] 明确用户 URL、规范化 API root 和最终资源 endpoint 三者的区别。
- [x] URL 自动补全、完整资源去重和协议冲突拒绝已实现并测试。
- [x] Anthropic 原生 `/v1/messages` 主执行路径已实现并测试。
- [x] 区分模型能力、厂商直连接口和 OpenCode Go 网关契约。
- [x] HY3 只适配正式版，preview 没有能力或路由承诺。
- [x] Muse 未公开复核的精确能力没有写成确定值。
- [x] P2 未把 OpenAI-compatible 等同于 Responses-compatible。
- [x] 403 DataPolicy 与网络问题、接口不支持已明确区分。
- [x] GitHub issue 未被用作模型性能证据。
- [x] 文档不包含凭据。
- [ ] 本轮 HY3 live 成功（外部测试项）。
- [ ] 本轮 Muse Contributor live 成功（外部权限项）。

调研结论：旧版 OpenAI Chat/Responses、Muse 和 HY3 结果仍然有效；负责人新增的三协议、
URL 去重和 Anthropic Messages P0 已获得本地单元/mock/wire 证据。该结论不等于外部模型
已完成本轮 live，也不应写成已经达到上线质量；真实模型可用性仍需在具备授权、地区条件
和预算的 live 环境中单独记录。
