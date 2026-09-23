# Phase P：RxyCode OpenAI/Anthropic 接口层与 HY3、Muse Provider 适配

> 日期：2026-08-25
> 调研依据：[`../research/2026-08-24-opencode-go-hy3-muse-provider.md`](../research/2026-08-24-opencode-go-hy3-muse-provider.md)
> 范围：只改 RxyCode 的 LLM Provider、必要的内部流归一、连接探测、测试和文档。
> 安全：API Key 只在运行时从环境变量或凭据存储读取，禁止写入源码、配置样例、fixture、日志和文档。

## 1. 一句话设计

**保留现有 OpenAI Chat Completions，新增 OpenAI Responses 与 Anthropic Messages；用户
URL 先规范化为 API root，具体走哪种协议、是否允许后备接口，由 LLM Provider 返回。**

这不是把所有模型改成 Responses，也不是把 Chat 全面重写。三种外部接口最终都归一成
RxyCode 已有的 `choices[0].delta` 内部流格式，因此 LangGraph、工具循环和前端不需要理解
外部接口差异。

```text
用户填写 URL + 模型配置
   ↓
normalize_llm_endpoint() → API root（避免重复拼接资源路径）
   ↓
Provider.transport_candidates()
   ├─ ("openai_chat",)
   ├─ ("openai_responses", "openai_chat")
   └─ ("anthropic_messages",)
           ↓
langchain-openai / langchain-anthropic 负责各自协议组包和流解析
           ↓
RxyCode 只做公开 LangChain chunk → 既有内部 chunk 的归一
```

## 2. 优先级与完成顺序

| 优先级 | 负责人要求 | 对应任务卡 |
|---|---|---|
| P0 | 定义 OpenAI Chat、OpenAI Responses、Anthropic Messages 三种协议 | 卡 1 |
| P0 | URL 自动补全、完整资源路径去重和协议冲突拒绝 | 卡 2 |
| P0 | 保留 OpenAI Chat，新增/复用 OpenAI Responses | 卡 3 |
| P0 | 新增 Anthropic 原生 Messages 执行路径 | 卡 4 |
| P0 | 安全回退及 Other 连接探测 | 卡 5、卡 6 |
| P1 | Muse、正式版 HY3 增加 LLM Provider | 卡 7、卡 8 |
| P2 | 审计现有预设；有官方 Responses 依据的预设优先 Responses | 卡 9 |
| 门禁 | 功能、回归、压力、安全和文档审计 | 卡 10 |

任务必须按卡 1 → 10 执行。P0 没有通过前，不开始扩大 P2 范围。

---

## 任务卡一：定义三种接口协议契约（P0）

### 1. 如何改进、要做什么

把当前 `chat`/`responses` 二值扩展成明确的三种协议：`openai_chat`、
`openai_responses`、`anthropic_messages`。`transport_candidates(model_config)` 返回有序
候选，而不是在 `AgentV2` 中用模型名硬编码。迁移期可接受旧值 `chat`/`responses`，但应
在配置解析边界转换成新规范值。

为什么增加：负责人最新 P0 不只有 OpenAI Chat/Responses，还要求 Anthropic 原生接口。
Anthropic Messages 的鉴权头、请求 content block、tool schema、停止原因和流事件都与
OpenAI 不同，不能继续用 `chat` 这个名字掩盖协议。

修改文件：`core/providers/base.py` 和需声明差异的 Provider 文件。

### 2. 示例代码

```python
LLMTransport = Literal[
    "openai_chat",
    "openai_responses",
    "anthropic_messages",
]

class BaseProvider:
    def transport_candidates(self, model_config: dict) -> tuple[LLMTransport, ...]:
        requested = str(model_config.get("api_transport") or "auto").casefold()
        if requested == "openai_chat":
            return ("openai_chat",)
        if requested == "openai_responses":
            return ("openai_responses", "openai_chat")
        if requested == "anthropic_messages":
            return ("anthropic_messages",)
        return ("openai_chat",)
```

`api_transport: openai_chat` 是 OpenAI 兼容网关的故障处置开关；普通用户不需要设置。
自动模式由 Provider 决定。Anthropic 不因 OpenAI endpoint 404 自动跨协议回退，除非具体
Provider 明确声明另一个兼容候选。

### 3. 验收标准

- [x] 三种规范协议值和旧配置迁移映射已实现。
- [x] 默认 Provider 只返回 `("openai_chat",)`，旧模型不会自动改变接口。
- [x] 候选值只能是三种规范值，重复项会稳定去重。
- [x] 核心执行层不出现 Muse、HY3 等模型名判断。
- [x] `api_transport: openai_chat` 能强制保持 Chat，便于紧急兼容。
- [x] 单元测试覆盖新旧值迁移、默认、显式选择、非法/空候选保护。

---

## 任务卡二：实现 URL 自动补全与资源路径去重（P0）

### 1. 如何改进、要做什么

新增单一的 `normalize_llm_endpoint(base_url, transport)`。它接收用户 URL 和 Provider
协议，返回规范化 API root；SDK 或探测层只能在 root 后拼接一次资源路径。不能简单
`rstrip("/")` 后直接追加。

为什么增加：负责人允许 Responses 的 `responses` 写或不写；同理，完整 Chat 或
Anthropic Messages URL 也可能由用户直接粘贴。如果不先去除已存在的资源后缀，SDK 会
形成 `/responses/responses`、`/messages/messages` 或
`/chat/completions/chat/completions`。

修改文件：建议新增 `core/providers/endpoints.py`（纯函数），并在配置持久化、连接探测和
LLM client 创建前统一调用；禁止三个调用点各写一份字符串判断。

### 2. 示例代码

```python
RESOURCE_SUFFIXES = {
    "openai_chat": ("/chat", "/chat/completions"),
    "openai_responses": ("/responses",),
    "anthropic_messages": ("/messages",),
}

def normalize_llm_endpoint(base_url: str, transport: str) -> str:
    parsed = validated_urlsplit(base_url)
    path = parsed.path.rstrip("/")
    for suffix in RESOURCE_SUFFIXES[transport]:
        if path.casefold().endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit(parsed._replace(path=path))
```

必须保留 `/zen/go/v1`、`/compatible-mode/v1` 等网关前缀。只有路径最后一段/两段与当前
协议资源精确相等时才去除，不能用 `replace("responses", "")`。

### 3. 验收标准

- [x] `/v1/chat` 和 `/v1/chat/completions` 均规范成 `/v1`，最终只请求一次
  `/v1/chat/completions`。
- [x] `/v1` 与 `/v1/responses` 在 Responses 协议下最终都只请求一次 `/v1/responses`。
- [x] `/v1` 与 `/v1/messages` 在 Anthropic 协议下最终都只请求一次 `/v1/messages`。
- [x] OpenCode Go、DashScope 等多段前缀不会被误删。
- [x] query、fragment、userinfo、明文 HTTP（携带凭据时）继续在联网前拒绝。
- [x] URL 明示资源与 Provider 协议冲突时明确报错，不静默切协议。
- [x] 单元测试包含大小写、末尾斜杠、相似后缀、攻击者域名和重复拼接反例。

---

## 任务卡三：保留 OpenAI Chat，新增 Responses 执行路径（P0）

### 1. 如何改进、要做什么

`AgentV2._raw_stream()` 保留原来的 `chat.completions.create(**payload)` 请求形状；新增
Responses 分支。Responses 分支必须复用项目已有的 `langchain-openai`，不能自己写
Responses SSE 协议解析器。

为什么增加：负责人后端本来就是 LangChain/LangGraph；复用 `ChatOpenAI` 可以跟随 SDK
升级处理 Responses 事件变化，避免项目维护第二套脆弱的 SSE 状态机。

修改文件：`core/agent_v2.py`、`core/providers/base.py`。

### 2. 示例代码

```python
if active_transport == "openai_responses":
    raw_llm = vars(self._llm).get("_llm", self._llm)
    response_stream = raw_llm.astream(messages, **invoke_kwargs)
    stream = self._responses_stream_as_chat_chunks(response_stream)
elif active_transport == "openai_chat":
    if client is None:
        client = self._openai_client()
    stream = client.create(**existing_chat_payload)
else:
    raise UnsupportedTransport(active_transport)
```

`BaseProvider.llm_kwargs()` 在首选 Responses 时向 LangChain 传：

```python
kwargs["use_responses_api"] = True
```

内部归一函数只读取 LangChain 公共 `AIMessageChunk` 字段，输出 RxyCode 原有的
`choices[0].delta` 形状。它不是自写 SSE parser。

### 3. 验收标准

- [x] Chat 分支仍使用原来的 `messages`、`max_tokens` 和
  `chat.completions.create()`。
- [x] Responses 的请求构造与 SSE 解析由 `langchain-openai` 完成。
- [x] 文本、reasoning、tool call、usage 能归一到旧内部流契约。
- [x] completed、incomplete、failed、缺失合法终态均有确定行为。
- [x] Chat 相关既有回归通过；未把所有模型强制切到 Responses。

---

## 任务卡四：新增 Anthropic 原生 Messages 执行路径（P0）

### 1. 如何改进、要做什么

当 Provider 返回 `anthropic_messages` 时，执行层使用 `langchain-anthropic` 的
`ChatAnthropic`（或等价的 Anthropic 官方 SDK 集成）发送原生 Messages 请求。不得把
Anthropic Base URL 交给 `ChatOpenAI`，也不得把 Anthropic content block 强行伪装成
OpenAI wire 后再发送。

为什么增加：现有 `AnthropicProvider` 只实现了 Provider 识别、能力和参数约束；主工具
循环仍依赖 OpenAI client。这不能证明 `/v1/messages` 已接入。成熟集成已经负责
`x-api-key`、`anthropic-version`、content block、tool use 和流事件解析，应直接复用。

修改文件：`core/agent_v2.py`、`core/providers/base.py`、`core/providers/anthropic.py`、
项目依赖文件，以及新增 Anthropic transport 定向测试。若依赖尚未安装，应显式增加并
锁定兼容版本，不能运行时静默降级成 OpenAI 协议。

### 2. 示例代码

```python
if active_transport == "anthropic_messages":
    anthropic_llm = build_anthropic_llm(
        api_key=secret,
        base_url=normalized_root,
        model=model_name,
    )
    async for chunk in anthropic_llm.astream(messages, **invoke_kwargs):
        yield normalize_anthropic_chunk(chunk)
```

`normalize_anthropic_chunk()` 只读取 LangChain 公开 chunk 字段，把 text、reasoning、
`tool_use`、usage 和停止原因映射到 RxyCode 内部事件；它不是自写 Anthropic SSE parser。
系统消息、工具结果和多轮 tool call 必须按 Anthropic 集成的公开消息类型转换。

### 3. 验收标准

- [x] Provider 返回 `anthropic_messages` 时只创建 Anthropic client，不创建 OpenAI client。
- [x] 最终请求只到一次 `/v1/messages`，并使用 Anthropic 鉴权与版本头。
- [x] system、文本、多模态 content block、tool schema、`tool_use`/`tool_result` 映射正确。
- [x] 文本流、工具流、usage、正常停止和错误终态能归一到现有内部契约。
- [x] 使用 `langchain-anthropic`/官方 SDK，不存在手写 Anthropic SSE 解析器。
- [x] mock/wire 测试能区分 Anthropic Messages 与两个 OpenAI 请求体。
- [x] 缺少依赖、无效版本头和不支持能力时返回可诊断错误，且不泄露凭据。

---

## 任务卡五：实现安全的接口回退和组合报错（P0）

### 1. 如何改进、要做什么

仅当第一个接口明确表示“端点/协议不存在或不支持”，并且尚未产生任何有用输出时，才
尝试 Provider 给出的下一个接口。如果 OpenAI 两个接口都明确不支持，返回包含尝试顺序的统一
错误，但不带请求正文和凭据。

为什么增加：盲目遇错就重试会隐藏权限错误、制造重复计费，工具流产生一半后切接口还
会造成重复执行。因此回退必须比普通 retry 更窄。

允许回退：HTTP `400`、`404`、`405`、`422` 且错误短语明确表示 endpoint、route、protocol 或命名 API 不支持，
或要求改用 `/responses`、`/chat/completions`。

默认回退只发生在同一 OpenAI-compatible Provider 明确给出的
`openai_responses → openai_chat` 候选之间。不得因为 Anthropic Messages 报错就自行切到
OpenAI Chat；只有具体 Provider 明确声明跨协议兼容且通过独立 wire 测试，才允许这种候选。

禁止回退：`401/403`、DataPolicy/区域/内容政策错误、`408/429`、网络或超时、`5xx`、
普通参数/tool schema/模型错误，以及已经收到 text、reasoning 或 tool call 后的错误。

### 2. 示例代码

```python
try:
    async for chunk in active_stream:
        if is_useful(chunk):
            got_useful = True
        yield chunk
except Exception as exc:
    can_switch = (
        not got_useful
        and next_transport is not None
        and provider.should_fallback_transport(
            exc,
            from_transport=active_transport,
            to_transport=next_transport,
        )
    )
    if can_switch:
        active_transport = next_transport
        continue
    raise
```

### 3. 验收标准

- [x] 明确 endpoint/protocol 不支持的 Responses 404/405 能在首个有用输出前切换至 Chat。
- [x] 404 明确表示模型不存在时不切换接口。
- [x] 400/422 只有明确“接口不支持”证据才切换。
- [x] 401、403、429、超时、网络、5xx 和 DataPolicy 不切换。
- [x] 产生部分文本或工具调用后绝不切换。
- [x] 两个 OpenAI 端点都不支持时返回
  `attempted: openai_responses, openai_chat` 组合错误。
- [x] 日志只记录 Provider 和接口名称，不记录 API Key、Header 或消息正文。
- [x] Anthropic Messages 失败不会被默认路由到 OpenAI Chat/Responses。
- [x] 只有带有明确请求资源路径的通用 `Not Found`/`Invalid URL` 才可作为传输不支持证据；无路径证据的普通 404/405、模型/资源错误仍不回退。

---

## 任务卡六：Other 自定义 Base URL 连接探测（P0）

### 1. 如何改进、要做什么

`probe_model_connection()` 与运行时共用 Provider 的接口候选和回退分类。Other/custom
缺少可信预设信息，自动模式先探测 `/responses`，只在明确端点不支持时探测
`/chat/completions`，成功后返回实际接口名称。

为什么增加：如果配置页面只测 Chat，会错误拒绝 Responses-only 网关；如果所有错误都
自动切换，又会把 403 等真正原因掩盖掉。

修改文件：`config/model_manager.py`、`tests/test_api_security_onboarding.py`。

### 2. 示例代码

Responses 探测体：

```json
{"model":"provider/model","input":"Hi","max_output_tokens":32,"stream":false}
```

Chat 探测体：

```json
{"model":"provider/model","messages":[{"role":"user","content":"Hi"}],"max_tokens":32,"stream":false}
```

成功结果增加规范协议名 `transport`：

```json
{"success":true,"transport":"openai_chat","reply":"OK","elapsed":0.42}
```

### 3. 验收标准

- [x] Other/custom 自动探测顺序为 Responses → Chat。
- [x] Responses 404 后 Chat 200 能成功，并返回 `transport=openai_chat`。
- [x] Responses 403 时只发一次请求，保留原错误，不探测 Chat。
- [x] 两端点均 404 时返回统一组合错误。
- [x] HTTP 明文 Base URL 在联网前被拒绝。
- [x] Provider 回显凭据或抛出含凭据异常时，结果中已脱敏。
- [x] 探测和运行时共用卡 2 的 URL 规范化函数，不会重复拼接资源路径。
- [x] HTTP 200 只有在响应体包含该协议的非空 assistant 回复时才判定探测成功；Responses、Chat、Anthropic Messages 分别校验自己的响应结构。
- [x] Anthropic 原生探测使用 `/v1/messages`、`x-api-key` 和 `anthropic-version`，不复用 OpenAI Bearer 请求头。

---

## 任务卡七：适配 Muse Spark Provider（P1）

### 1. 如何改进、要做什么

保留 Muse 家族识别，但只对已确认的 OpenCode Go
`muse-spark-1.2-contributor` 声明 Responses 优先。其他 Muse 型号不虚构网关可用性
和精确能力。Provider 在联网前校验 function tool name 长度，禁止静默截断。

为什么增加：OpenCode Go 对 Contributor 公布的是 Responses 路由；旧工具循环固定走
Chat 会选错端点。Contributor 还存在显式数据政策要求，不能遇到 403 后悄悄改走 Chat。

修改文件：`core/providers/muse_spark.py`、`tests/test_providers/test_muse_spark_provider.py`、
`config/model_catalog.json`。

### 2. 示例代码

```python
def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
    if (
        host(model_config["base_url"]) == "opencode.ai"
        and model_config["model_name"].casefold()
            == "muse-spark-1.2-contributor"
    ):
        return ("openai_responses", "openai_chat")
    return super().transport_candidates(model_config)
```

模型约束：

- 家族 ID：`muse-spark-1.1`、`muse-spark-1.2`、
  `muse-spark-1.2-contributor`；
- OpenCode Go 当前只对 Contributor 建立路由承诺；
- 未公开复核的 context、max output、effort 不写成确定值；
- Go 请求不自动添加未证实的 `thinking` 或 `reasoning_effort`；
- tool name 超过 64 字符时请求前失败，不自动改名；
- Contributor 的 DataPolicy/区域限制属于外部授权条件，不通过接口回退掩盖。

### 3. 验收标准

- [x] 三个 Muse ID 能被家族 Provider 精确识别，近似名称不误匹配。
- [x] OpenCode Go + Contributor 返回 Responses → Chat 候选。
- [x] Muse 403 DataPolicy 不回退、不被标记为成功或 skipped。
- [x] 未确认的 Muse 1.1/1.2 不发布精确 catalog 限额。
- [x] 工具名超长在联网前报错。
- [x] Responses 文本、工具调用与合法终态的 mock/wire 测试通过。

---

## 任务卡八：适配正式版 HY3 Provider（P1）

### 1. 如何改进、要做什么

新增 `Hy3Provider`，只精确匹配正式模型 ID `hy3`；它负责能力身份、正式参数上限和
接口决策，但不改已经联通的 Chat 请求形状。`hy3-preview` 及未来型号不匹配。

为什么增加：负责人明确要求 HY3 也有独立 LLM Provider。独立 Provider 能把模型能力和
网关传输决策放在同一策略层，同时通过精确匹配避免 preview/future 型号继承错误假设。

修改文件：`core/providers/hy3.py`、`core/providers/__init__.py`、
`config/model_catalog.json`、`tests/test_providers/test_hy3_provider.py`。

### 2. 示例代码

```python
class Hy3Provider(BaseProvider):
    name = "hy3"

    def matches(self, base_url: str, model_name: str) -> bool:
        return model_name.strip().casefold() == "hy3"

    def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
        return ("openai_chat",)
```

正式版模型约束（模型层资料，不等于可以向第三方网关发送扩展字段）：

- context window：256,000；最大输入：192,000；最大输出：128,000；
- 支持深度思考、Function Calling、结构化输出和 Cache；
- OpenCode Go 仍走 Chat Completions；
- 不向 Go 自动发送 TokenHub 直连的 `thinking`、`reasoning_effort`、
  `reasoning_content`、`mandatory_echo`、`previous_response_id`。

### 3. 验收标准

- [x] `hy3` 解析为 `Hy3Provider`；preview 和近似 ID 不解析为该 Provider。
- [x] HY3 返回规范值 `("openai_chat",)`，请求形状仍保持已验证的 Chat 路径。
- [x] Chat wire 继续使用 `messages`、`max_tokens`，不出现 Responses 字段。
- [x] OpenCode Go wire 不出现 TokenHub 专属推理/echo 字段。
- [x] 正式版目录记录为 256k context / 128k max output，来源和日期齐全。
- [x] Provider 注册顺序测试证明不会抢其他模型。

---

## 任务卡九：审计现有预设并设置 Responses 优先级（P2）

### 1. 如何改进、要做什么

只有找到当前官方 Responses 接口依据的预设才设为 Responses 优先；明确只支持 Chat 或
没有公开证据的预设继续 Chat。不能因为“OpenAI-compatible”就推断一定有 Responses。

为什么增加：Responses 常能更完整地表达 reasoning、工具调用和多轮状态，但网关支持
度不一致。P2 的目标是证据驱动地提升已支持模型，不是全量试错。

审计裁定（2026-08-25）：

| 预设/官方 Host | 自动顺序 | 原因 |
|---|---|---|
| OpenAI 官方 Host | Responses → Chat | 官方推荐推理/工具场景使用 Responses |
| DeepSeek 官方 Host | Responses → Chat | 官方已有 create-response 接口资料 |
| 火山方舟上的 Doubao（官方 Ark Host） | Responses → Chat | 官方 Responses 示例明确使用 Doubao；不外推到 Ark 托管的每个第三方模型 |
| DashScope/Qwen 预设及官方 Host | Responses → Chat | 阿里云官方提供 OpenAI-compatible Responses API |
| OpenRouter 预设 | Responses → Chat | 官方公开 Responses endpoint |
| Groq 预设 | Responses → Chat | 官方公开 Responses API（Beta） |
| Other/custom | Responses → Chat | 未知能力，配合卡 5 的窄回退安全发现 |
| Together | Chat | 官方兼容表明确 Responses 不支持 |
| Moonshot/Kimi、Zhipu、SiliconFlow | Chat | 本轮未找到足够的官方 Responses 证据 |
| OpenCode Go 普通模型、Zen | Chat | 按网关模型表逐个声明；不得全局推断 |
| OpenCode Go Muse Contributor | Responses → Chat | 由 Muse Provider 精确声明 |
| OpenCode Go HY3 | Chat | 由 HY3 Provider 精确声明 |

Qwen 的端点和思考参数必须联动：Chat 保持 `extra_body.enable_thinking`；Responses 使用
`reasoning.effort`，不再发送已被官方标注为后续不支持的 `enable_thinking`。自动档位只用
所有地域都支持的 `none/minimal/low/medium/high`；仅北京和新加坡支持的 `xhigh/max`
不进入跨地域自动预设。

### 2. 示例代码

```python
def transport_candidates(self, model_config: dict) -> tuple[str, ...]:
    if is_official_response_host(model_config.get("base_url", "")):
        return ("openai_responses", "openai_chat")
    return super().transport_candidates(model_config)
```

Host 判断必须用 URL parser 的 `hostname`，不能用容易被 userinfo 或相似域名欺骗的宽松
字符串包含。

### 3. 验收标准

- [x] 每个 Responses-first 预设/模型路由都有官方资料依据或明确的 custom 探测规则。
- [x] Together 保持 Chat；未证实预设没有被批量切换。
- [x] 官方 Host 与伪造相似 Host 不会混淆。
- [x] `llm_kwargs()` 只为 Responses-first 路由设置 `use_responses_api=True`。
- [x] OpenCode Go 普通模型不因 P2 被整体切到 Responses。

---

## 任务卡十：分层验收、安全与交付（门禁）

### 1. 如何改进、要做什么

按“静态检查 → 定向单测 → 相关回归 → 压力 → live（外部条件允许时）→ 敏感信息
扫描”的顺序验收。Mock/wire、压力和真实 live 必须分开报告，不能用 mock 代替真实服务，
也不能把 DataPolicy 403 写成 Provider 代码失败。

### 2. 示例命令

```powershell
python -m ruff check core/providers core/agent_v2.py config/model_manager.py tests
python -m pytest -q -p no:cacheprovider tests/test_providers
python -m pytest -q -p no:cacheprovider tests/test_model_catalog.py
python -m pytest -q -p no:cacheprovider tests/test_api_security_onboarding.py -k "unsaved_probe or custom_probe"
python -m compileall -q core config tests scripts
python scripts/stress_muse_provider.py --requests 200 --chunks 32 --concurrency 1 2 4 8 16
python scripts/scan_secrets.py .
```

Live 测试只允许从环境变量安全注入凭据，并单独设置预算与显式开关。不得把真实凭据写进
命令历史、pytest 参数或临时 YAML。

### 3. 验收标准

- [x] 旧版 OpenAI 双接口、Muse、HY3、注册表和 catalog 定向测试通过。
- [x] Other 探测、403 不回退、双端点失败组合错误测试通过。
- [x] Ruff 通过。
- [x] 本轮可复现分层回归通过：三协议专项 86 passed；Provider 607 passed；
  catalog 15 passed；batch onboarding 15 passed；相关 core 9 passed；
  Other/custom 接口探测 7 passed（45 deselected）。
- [x] compileall 通过。
- [x] 压力测试通过：1000 请求、33000 chunks、0 error、0 task leak。
- [x] 敏感信息扫描无发现。
- [x] 文档已如实区分旧版已完成项、负责人新增 P0 本地结果与外部未完成项。
- [x] 三种规范协议值及旧配置迁移测试通过。
- [x] URL 自动补全、完整资源去重和协议冲突矩阵测试通过。
- [x] Anthropic 原生 Messages 文本、工具、usage、终态和 wire 测试通过。
- [x] 最新 P0 全部实现后，Provider 模块文档与最终代码一致。
- [x] P1 回退分类正反例覆盖模型不存在、参数/tool schema 错误和明确协议不支持。
- [x] Anthropic 流式 `input_token_details.cache_read` 已纳入 cache-read usage，且不混入 cache creation。
- [x] Anthropic thinking block 已归一到内部 `reasoning_content`，TUI 和工具循环可以读取；Responses 路径不再注入 Chat 专用 `thinking`，但保留合法的 `reasoning_effort`。
- [x] 核心模块文档已明确按协议构造 `ChatOpenAI` 或 `ChatAnthropic`。

环境说明：当前机器的完整 `tests/test_api_security_onboarding.py` 受 Python 3.14 与已安装
Starlette `TestClient` 版本不匹配（`client=` 参数不被接受）及 Windows pytest 临时目录
权限影响，不能把该全文件结果写成本功能回归失败或通过。本任务直接相关的 7 个
Other/custom 探测用例已单独通过；PR/CI 仍应在项目锁定依赖的标准 Python runner 上执行
完整门禁。
- [ ] 本轮真实 HY3 live 成功（外部门禁，需要安全凭据与预算）。
- [ ] 本轮 Muse Contributor live 成功（外部门禁，需要 workspace DataPolicy 授权与地区允许）。

外部两项未勾选不等于本地 Provider 实现失败，但禁止宣称真实模型已经完整走通。

## 3. 关键禁止项

- 禁止删除、替换或全面重写现有 Chat Completions 路径。
- 禁止在 `AgentV2` 用模型 ID 决定接口；接口选择属于 Provider。
- 禁止自己解析 Responses SSE；使用 `langchain-openai`。
- 禁止把 `/v1/chat` 当成 OpenAI 标准最终资源；最终 Chat endpoint 是
  `/v1/chat/completions`。
- 禁止把已包含 `/responses`、`/chat/completions` 或 `/messages` 的 URL 再次拼接同名资源。
- 禁止把 Anthropic 原生 Messages 路由交给 `ChatOpenAI`，或自己解析 Anthropic SSE；
  使用 `langchain-anthropic`/官方 SDK 集成。
- 禁止对所有异常做接口回退，或在产生部分输出后切接口。
- 禁止把腾讯 TokenHub 直连字段无证据转发到 OpenCode Go。
- 禁止把 Muse Contributor 403 DataPolicy 处理成通过、跳过或 Chat 回退。
- 禁止记录、打印、提交或文档化 API Key。
- 禁止在本任务中 commit、push 或创建 PR；PR 由用户之后自行完成。

## 4. 交付定义

达到可提交 PR 的本地水准需要：卡 1—9 的本地验收全通过，卡 10 的静态、回归、压力、
安全和文档项全通过。卡 1、2、4 现有结论只覆盖本地单元/mock/wire；真实 live 是独立
外部门禁：有权限和预算时执行并如实记录；没有权限时保持未勾选，不能伪造成功，也不能
因此回滚正确的 Provider 架构。完成本地门禁也不得提前写“已经达到上线质量”。
