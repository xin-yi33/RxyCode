# Phase F · 多模态 × 多 Agent 协作（Multimodal Agent Collaboration）

> **在整条路线中的位置**：[`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的后继扩展，编号 Phase F，是核心路线的**最后一段**。
> **前置条件**：主计划 Phase 0/1/2/3/**4** + [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) + [`PHASE-B-ISOLATED-SUBAGENT.md`](./PHASE-B-ISOLATED-SUBAGENT.md) + [`PHASE-C-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-C-MULTI-AGENT-ORCHESTRATION.md) + [`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) + [`PHASE-E-MULTI-MODEL-COLLABORATION.md`](./PHASE-E-MULTI-MODEL-COLLABORATION.md) **全部完成**。
> **后继**：[`PHASE-G-PERSONA-AGENT-INTERFACE.md`](./PHASE-G-PERSONA-AGENT-INTERFACE.md)（接口预留，非必做）
> **注意主计划 Phase 4（Desktop）也是硬前置**，理由见 §0.3——终端里没法看图；Phase 3 的模型输出上限契约也必须已冻结，避免附件/视觉模型请求各自猜预算。
>
> **一句话目标**：让图像能端到端流过系统（用户 → Agent → 模型 → 记忆 → 前端），并让多 Agent 编排能利用视觉能力（例如"截图审查员"角色看 UI 截图找问题）。
>
> **执行模型**：管道类型拓宽与预览 UI **Composer 主写**；预览/粘贴图片 UI 卡的**多模态环节**委托 Grok 辅助。权威见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)。
> **基线日期**：2026-07-31（编号自 Phase E 调整为 Phase F）　**预计工时**：6 周（1 名后端 + 1 名前端）
>
> ---
>
> **📌 Phase E 交接给本文档的三个约束**（来自 `PHASE-E-MULTI-MODEL-COLLABORATION.md` §7）
>
> | 交接项 | 本文档要做的事 |
> |---|---|
> | `HandoffTranslator` 的输入类型现在是 `str` | F4 拓宽类型时**必须同时拓宽它**，否则跨模型交接会把图像变成 `repr` 文本 |
> | `ModelCapabilities.supports_vision`（Phase A 已有） | 视觉角色的能力校验直接用它，不要另造一套 |
> | `CostAccountant` 只算文本 token | 图像 token 的计费方式与文本不同，D 阶段要扩展它（各家算法不同，让 Grok 查） |
>
> **另外：Phase E 的 `AgentSpec.extra` 已预留 `requires_vision`**，视觉角色直接用这个 key，不要新增字段。

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | 执行协议、分工、为什么 Desktop 是硬前置 |
| [§1 现状真相](#1-现状真相实测证据) | 全链路都是 `str`，附 file:line |
| [§2 目标架构](#2-目标架构) | ContentBlock 贯穿全链路 |
| [§3 任务卡 F1–F12](#3-任务卡) | 逐个执行 |
| [§4 出口检查](#4-phase-c-出口检查) | 怎么算做完 |
| [§5 扩展手册](#5-扩展手册加一种新的-content-block) | 以后加音频/视频怎么做 |

---

## §0 执行手册（必读）

### 0.1 执行协议

与前置 Phase A/B/C 相同的 7 步（LOCATE → READ → WRITE → LINT → TEST → CHECK → COMMIT），加 Phase F 专属的两条：

```
8. TEXT-PATH  每张卡做完，验证纯文本路径完全没变：
              python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
              （Phase F 的所有改动对纯文本输入必须是零影响的）

9. ROUNDTRIP  每张卡做完，跑往返保真测试：
              python -m pytest tests/test_multimodal/test_roundtrip.py -q
              （F2 建立之后每张卡都要跑）
```

**为什么要往返保真测试**：多模态改造最典型的 bug 是"某一层偷偷把 content block 变成了字符串"。这种 bug 不会报错，只会让图像**静默消失**——模型收到的是 `[{'type': 'image_url', ...}]` 的 Python repr 文本。往返测试就是抓这个的。

### 0.2 三个模型的分工

| 模型 | 干什么 | 不要干什么 |
|---|---|---|
| **Composer 2.5** | **主写全部**：类型拓宽、AttachmentStore、缓存键（按文档已定决策）、预览/粘贴图片 UI 卡本体 | 自行改缓存策略 |
| **Grok 4.5** | 查各家 vision API 的差异（图像尺寸/格式限制、base64 vs URL、token 计费、content block 格式）；预览/粘贴图片 UI 卡的**多模态环节**（视觉验收：贴图、预览、清除的自测） | 改管道 Python / 写卡本体（那是 Composer 的） |
| **Sonnet 5** | 审查 F3 的 diff（类型拓宽最容易漏改）、写文档（F12） | 长任务连续实现 |

### 0.3 为什么 Desktop（主计划 Phase 4）是硬前置

**终端里没法看图。** 我实测确认过：`frontend/opentui-app/` 全目录搜 `sixel`、`kitty`、`iterm`、`graphics` 均**无结果**；粘贴处理（`App.tsx:511-516`）只处理文本字节。

即使你在后端把多模态全打通，OpenTUI 用户也只能看到 `[图片]` 占位符——既不能贴图进去，也不能看模型指的是图里哪一块。**多模态的价值 90% 在交互界面上**，没有 Desktop，Phase F 做完了也没人用得上。

其余前置的理由：

| 前置 | 为什么绕不过 |
|---|---|
| 主计划 Phase 2 | Content block 必须在 `protocol/` 里定义一次，各客户端自动生成类型。否则你要在 API/Agent/memory/cache/SSE/前端六个地方各定义一遍，格式必然漂移 |
| **Phase A** | `ModelCapabilities.supports_vision` 字段是 Phase A 占的坑。没有它，你无法在运行前判断当前模型能不能吃图，只能等 API 报错 |
| **Phase C** | Phase F 的最终目标是"多模态 × 多 Agent"。没有 AgentRuntime，你没有地方挂"这个角色需要 vision 能力"这个约束 |
| **Phase D** | 图片输入、预览、附件和视觉结果需要一个真正能呈现它们的 Desktop 工作台；本 Phase 只拓宽协议和能力，不重新造桌面壳 |

**自检命令**：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
Test-Path protocol\schema.json, core\providers\__init__.py, core\agents\runtime.py
# 三个都要 True
Test-Path frontend\desktop-app\package.json  # 主计划 Phase 4 的 Desktop 应用
python -c "from config.model_capabilities import ModelCapabilities; print(ModelCapabilities().supports_vision)"
```

### 0.4 硬性规则

| # | 规则 | 原因 |
|---|---|---|
| MD1 | **纯文本路径必须逐字节不变。** Phase F 的每一处类型拓宽都是"加一个分支"，不是"改现有分支" | 零回归 |
| MD2 | **绝不把图像 base64 塞进任何日志、trace、错误信息。** 一张图能有几 MB，会瞬间撑爆日志和 SSE | 已有 SSE 截断（`api_server.py:2153`）但那是 4096 字符，不够 |
| MD3 | **图像存磁盘，链路里传引用。** 不要让 base64 在内存里被复制五次 | 内存与性能 |
| MD4 | **语义缓存对多模态请求直接跳过，不要试图"给图片算相似度"** | 见 F5 的理由 |
| MD5 | **模型不支持 vision 时必须明确报错**，不能静默丢弃图像 | 静默丢弃 = 用户以为模型看了图，实际没有 |
| MD6 | 一次一张卡，一张卡一个 commit |

---

## §1 现状真相（实测证据）

**结论：全链路都是 `str`，多模态是零基础。** 全仓库生产代码里 `image_url` 出现 **0 次**（实测 grep `core/*.py`、`api_server.py`、`tools/*.py`、`execution/*.py`）。

### 1.1 从 HTTP 到 LLM，每一层都是字符串

| 层 | 位置 | 类型 |
|---|---|---|
| HTTP 请求 | `api_server.py:252-255` | `ChatRequest.message: str` |
| 会话持久化 | `api_server.py:408-417` | `"content": str(content)` |
| Agent 入口 | `core/agent_v2.py:3014` | `run(self, user_input: str) -> str` |
| 用户消息组装 | `core/prompts/registry.py:239-266` | `build_user_message(...) -> str` |
| LangChain 消息 | `core/agent_v2.py:2762` | `HumanMessage(content=user_msg)`，`user_msg` 是 `str` |
| OpenAI 载荷 | `core/agent_v2.py:1326-1327` | 见下 |

```1326:1327:core/agent_v2.py
            elif role == "human":
                out.append({"role": "user", "content": getattr(m, "content", "") or ""})
```

这一行是**整条链路的收口**。只要它还写死取字符串，上游做什么都白搭。

### 1.2 `vision` 工具是误导性的

```56:62:tools/vision.py
def run_vision(operation: str = "describe", filePath: str = "", prompt: str = "") -> str:
    """Run vision operations on images."""
    ...
        if operation == "describe":
            return _describe_image(str(p))
        elif operation == "ocr":
            return _ocr_image(str(p))
```

实际行为：`describe` 返回 PIL 读出的**元数据**（尺寸、格式）+ 可选 Tesseract OCR 文本（`:86-128`）；`screenshot` 用 mss 截屏存成 PNG 并返回**文件路径**（`:180-207`）。`prompt` 参数在 schema 里声明了（`:50-52`）但**实现中完全没用**。

**它从不把图像送给 LLM。** 而 `docs/modules/tools.md:28` 却写着它用 "multimodal LLM"——文档与实现不符，F10 要修。

### 1.3 MCP 的图像会被丢弃

```811:816:mcp/client.py
            if content_type == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif content_type == "image":
                parts.append(f"[image: {item.get('mimeType', 'unknown')}]")
            elif content_type == "audio":
                parts.append(f"[audio: {item.get('mimeType', 'unknown')}]")
```

数据本身扔掉，只留 MIME 占位符。

### 1.4 工具层契约是 `str`

| 位置 | 签名 |
|---|---|
| `execution/tool_orchestrator.py:618-628` | `async def execute_tool(...) -> str` |
| `execution/tool_orchestrator.py:1009-1027` | `return str(result)` |
| `execution/tool_orchestrator.py:249-280` | `_clean_tool_output(result: Any, ...) -> str`，先 `str(result)` |
| `execution/tool_orchestrator.py:265-268` | 输出上限 30000 字符 |

工具**不可能**返回图像。

### 1.5 记忆层会把非字符串烧成 repr

```86:88:memory/chat_storage.py
                clean_msg = deepcopy(msg)
                clean_msg["role"] = str(msg.get("role", ""))
                clean_msg["content"] = _sanitize_text(str(msg.get("content", "")))
```

`memory/short_term.py:19-24`、`memory/long_term.py:91-97` 同理。**一个 content block 列表存进去再读出来，会变成 `"[{'type': 'image_url', ...}]"` 这样的字符串**。这是 MC 规则里最需要防的那类静默失败。

### 1.6 缓存键是纯文本哈希

```93:99:cache/precise_cache.py
    def _hash_parts(*parts: str) -> str:
        digest = hashlib.sha256()
        for part in parts:
            encoded = part.encode("utf-8")
```

应用层用法（`core/agent_v2.py:2723-2729`）：

```python
cache_key = json.dumps([user_input, memory_fingerprint], ...)
cached = precise_cache.get(system, cache_key, namespace=cache_namespace)
```

语义缓存（`cache/semantic_cache.py:137`、`:68-74`、`:120-123`）用 `SequenceMatcher` 做文本相似度。**给图像算文本相似度是没有意义的**，这是 F5 要处理的核心设计问题。

### 1.7 传输与前端

| 项 | 现状 | 位置 |
|---|---|---|
| SSE | UTF-8 JSON 文本，理论上能塞 base64 但没有入口 | `api_server.py:2510-2520` |
| SSE 工具结果截断 | 4096 字符 / 60 行 | `api_server.py:2153-2154`、`:2241-2252` |
| 请求体大小限制 | **未配置**，依赖 Starlette/Uvicorn 默认 | `api_server.py:63`、`:2570-2582` |
| 文件上传端点 | **不存在**（无 `UploadFile` / `multipart`） | — |
| 前端消息类型 | `content: string` | `frontend/opentui-app/src/types.ts:5-8` |
| 前端粘贴 | 只处理文本 | `frontend/opentui-app/src/App.tsx:511-516` |
| 终端图像协议 | **无任何引用** | 全目录 grep 无结果 |
| RAG | 图像/音视频扩展名直接跳过索引 | `rag/chunker.py:26-34` |

### 1.8 改造面总表

| 层 | 改造性质 | 难度 |
|---|---|---|
| 协议类型定义 | 新增 | 低 |
| API schema | 拓宽 | 低 |
| Agent 链路 | 拓宽（十几处） | 中，机械 |
| `_to_openai_messages` | 加分支 + provider 差异 | 中 |
| 记忆持久化 | 拓宽 + 保真 | 中 |
| **缓存键** | **重新设计** | **高，有真实权衡** |
| 工具返回类型 | 拓宽 | 中 |
| 附件存储与引用 | 新增 | 中 |
| Desktop UI | 新增 | 中 |
| 多 Agent 视觉角色 | 新增 | 低（Phase C 已铺好） |

---

## §2 目标架构

### 2.1 核心思路：引用而非内联

```
用户拖入 screenshot.png
        │
        ▼
┌───────────────────────────────────────────────┐
│ POST /attachments  →  存到 ~/.rxycode/attachments/<sha256>.png │
│                        返回 attachment_id                      │
└───────────────────────┬───────────────────────┘
                        │ 只传 id，不传 base64
                        ▼
┌───────────────────────────────────────────────┐
│ POST /chat                                     │
│ { message: [                                   │
│     {type: "text",  text: "这个按钮为什么歪了"}, │
│     {type: "image", attachment_id: "ab12..."}  │
│ ]}                                             │
└───────────────────────┬───────────────────────┘
                        │ 全链路只传 attachment_id
                        ▼
        Session → AgentRuntime → memory / cache / SSE
                        │
                        │ 只在最后一步展开
                        ▼
┌───────────────────────────────────────────────┐
│ _to_openai_messages()                          │
│   provider.render_content_blocks(blocks)       │
│   → 此时才从磁盘读文件、编 base64、按 provider  │
│     的格式组装                                  │
└───────────────────────────────────────────────┘
```

**为什么用引用**：一张 2MB 的图，base64 后 2.7MB。如果它在 `Session` → `AgentRuntime` → `memory` → `cache key` → `SSE` 里各存一份，一次对话就能吃掉几十 MB，而且会污染日志和 trace（违反 MD2）。传 `attachment_id` 则全程只有 64 个字符。

### 2.2 四条不可违反的设计约束

| # | 约束 | 原因 |
|---|---|---|
| DCD1 | **`ContentBlock` 在 `protocol/` 里定义一次**，其余各层引用它，不许各自定义 | 六处定义必然漂移 |
| DCD2 | **base64 只在 `_to_openai_messages` 这一层出现**，其它任何地方都只传 `attachment_id` | MD2 MD3 |
| DCD3 | **纯文本输入必须走与 Phase F 之前逐字节相同的代码路径**。类型拓宽用"加分支"实现，不改现有分支 | MD1，零回归 |
| DCD4 | **附件有生命周期**：按 session 归属，会话删除时级联删除，且有磁盘配额 | 不然 `~/.rxycode/attachments/` 会无限增长 |

### 2.3 文件布局（**不要改**）

```
protocol/
  content.py                   # ContentBlock 联合类型
  attachments.py               # 附件上传 / 引用的协议类型
core/
  attachments/
    __init__.py
    store.py                   # 内容寻址存储（sha256 → 文件）
    quota.py                   # 配额与清理
  providers/
    base.py                    # 新增 render_content_blocks()
tests/
  test_multimodal/
    __init__.py
    test_content_blocks.py
    test_roundtrip.py          # 往返保真 —— F2 之后每张卡都要跑
    test_attachment_store.py
    test_cache_keys.py
    test_provider_rendering.py
```

---

## §3 任务卡

### F1 · 定义 ContentBlock

`P0` / 4h / 依赖主计划 Phase 2

**背景**
全链路类型拓宽的地基。必须先有一个**唯一**的定义（约束 DCD1）。

**涉及文件**
- 新建 `protocol/content.py`
- 修改 `protocol/schema.py`（导出新类型）
- 新建 `tests/test_multimodal/__init__.py`、`test_content_blocks.py`

**操作步骤**

1. `protocol/content.py`：

```python
"""消息内容块。

RxyCode 历史上每一层的消息内容都是 str（api_server.ChatRequest.message、
AgentV2.run(user_input)、HumanMessage(content)、memory 持久化、SSE），
所以图像根本无处安放。本模块引入内容块，让同一条消息能同时携带文本和
图像引用。

关键设计（见 PHASE-E 文档 §2.1）：图像在链路里只以 attachment_id 传递，
base64 只在 core/providers 渲染成 API 载荷的那一刻才出现。
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    """图像引用。

    刻意**不含**图像数据本身。数据在 core/attachments/store.py 里按
    sha256 内容寻址，这里只存 id。
    """

    type: Literal["image"] = "image"
    #: core.attachments.store 里的 attachment id（sha256 hex）
    attachment_id: str
    #: MIME 类型，例如 "image/png"
    mime_type: str
    #: 可选的替代文本，用于不支持 vision 的模型降级和无障碍展示
    alt_text: str = ""


#: 消息内容块的判别联合。
#: 加新类型（音频/视频/文件）的完整流程见 PHASE-E 文档 §5。
ContentBlock = Annotated[
    Union[TextBlock, ImageBlock],
    Field(discriminator="type"),
]

#: 消息内容：纯字符串（历史格式，仍然合法）或内容块列表。
#:
#: 保留 str 分支不是为了兼容旧数据，而是因为**绝大多数消息就是纯文本**，
#: 让它们继续走原路径能保证零回归（约束 DCD3）。
MessageContent = Union[str, list[ContentBlock]]


def is_multimodal(content: MessageContent) -> bool:
    """判断内容是否含非文本块。

    纯 str 和只含 TextBlock 的列表都算纯文本——后者可能由客户端产生，
    不应该因此走多模态路径（那会白白跳过缓存）。
    """
    if isinstance(content, str):
        return False
    return any(block.type != "text" for block in content)


def to_plain_text(content: MessageContent) -> str:
    """把内容降级成纯文本。

    用于：不支持 vision 的模型、日志、缓存键的文本部分。
    图像块渲染成 alt_text 或占位符，**绝不**渲染成 base64（规则 MD2）。
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if block.type == "text":
            parts.append(block.text)
        elif block.type == "image":
            label = block.alt_text or block.mime_type
            parts.append(f"[image: {label}]")
    return "\n".join(parts)
```

2. 在 `protocol/schema.py` 里导出这些类型，重新生成 `schema.json`。

3. `tests/test_multimodal/test_content_blocks.py` 必须覆盖：
   - `is_multimodal` 对 `str`、只含 text 的列表、含 image 的列表的判定
   - `to_plain_text` **绝不产生 base64**（写一个断言 `"base64" not in result` 的测试）
   - pydantic 判别联合能正确反序列化两种 block
   - 未知 `type` 会被拒绝

**验收命令**

```powershell
python -m pytest tests/test_multimodal/test_content_blocks.py -q
python -m ruff check protocol/content.py
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
python -m pytest tests/test_protocol_schema.py -q
cd frontend\protocol-client; bun run generate; cd ..\..
git diff --exit-code frontend/protocol-client/src/generated/
```

**完成判据**
- [ ] `protocol/content.py` 存在且是唯一定义处
- [ ] `schema.json` 已更新，TS 类型已重新生成并提交
- [ ] `to_plain_text` 不产生 base64 的测试存在
- [ ] **未修改任何现有文件**（除 `schema.py` 的导出）

**Commit**
```
feat(protocol): define multimodal content blocks

Every layer from ChatRequest.message to _to_openai_messages typed content
as str, so images had nowhere to live. Images are referenced by
attachment_id rather than inlined, so base64 never travels through
memory, cache keys, traces or SSE.
```

---

### F2 · 附件存储

`P0` / 1 周 / 依赖 F1

**背景**
实现 §2.1 的内容寻址存储。这一卡是纯新增，风险低，但**配额和清理必须一起做**（约束 DCD4），否则磁盘会被吃光。

**涉及文件**
- 新建 `core/attachments/__init__.py`、`store.py`、`quota.py`
- 新建 `protocol/attachments.py`
- 新建 `tests/test_multimodal/test_attachment_store.py`、`test_roundtrip.py`

**操作步骤**

1. `core/attachments/store.py` 的核心 API：

```python
"""附件的内容寻址存储。

按 sha256 存到 ~/.rxycode/attachments/<前2位>/<完整hash>.<ext>，同一张图
重复上传不会占两份空间。

生命周期（约束 DCD4）：附件按 session 归属；会话删除时级联删除；总容量
超过配额时按 LRU 淘汰未被任何活跃会话引用的附件。
"""

class AttachmentStore:
    def put(self, data: bytes, *, mime_type: str, session_id: str) -> str:
        """存入附件，返回 attachment_id（sha256 hex）。

        同内容重复存入返回同一个 id 并追加 session 引用。
        """

    def get_path(self, attachment_id: str) -> Path:
        """取附件的磁盘路径。不存在时抛 AttachmentNotFound。"""

    def get_bytes(self, attachment_id: str) -> bytes:
        """读出附件内容。

        只应该被 core/providers 的渲染层调用（约束 DCD2）。
        其它地方需要附件请用 get_path 或 get_metadata。
        """

    def get_metadata(self, attachment_id: str) -> AttachmentMeta:
        """取 mime_type / 大小 / 创建时间 / 引用的 session 列表。"""

    def release_session(self, session_id: str) -> int:
        """解除某个 session 的所有引用，返回因此变成孤儿的附件数。"""
```

2. **校验必须严格**。`put()` 要拒绝：
   - 超过单文件上限（默认 20 MB，可配置）
   - MIME 不在白名单（默认 `image/png`、`image/jpeg`、`image/webp`、`image/gif`）
   - **文件头与声明的 MIME 不符**（用 magic bytes 校验，不要信客户端说的 MIME）

3. `core/attachments/quota.py`：总容量上限（默认 2 GB）、LRU 淘汰、`rxycode attachments gc` 命令。

4. `tests/test_multimodal/test_roundtrip.py` —— **这个文件是 Phase F 的安全网**，后面每张卡都要跑：

```python
"""多模态往返保真测试。

Phase F 最典型的 bug 是"某一层偷偷把 content block 变成了字符串"——不报
错，图像只是静默消失，模型收到的是一段 Python repr。这个文件在每一层的
边界上验证保真性。

F2 之后每张 Phase F 任务卡做完都要跑这个文件。
"""

def test_attachment_roundtrip_preserves_bytes():
    """存进去什么，读出来还是什么。"""

def test_same_content_deduplicates():
    """同一张图存两次只占一份空间，且 id 相同。"""

def test_content_block_survives_pydantic_roundtrip():
    """ImageBlock → JSON → ImageBlock 不丢字段。"""

def test_mime_mismatch_is_rejected():
    """声明 image/png 但内容是 JPEG，必须拒绝。"""

def test_oversized_attachment_is_rejected():
    """超过单文件上限要报错，不能截断后存下。"""

def test_release_session_orphans_unreferenced_attachments():
    """会话删除后，只被它引用的附件变成孤儿。"""

def test_still_referenced_attachment_survives_session_release():
    """被另一个会话也引用的附件不能被删。"""
```

**验收命令**

```powershell
python -m pytest tests/test_multimodal -q
python -m ruff check core/attachments protocol/attachments.py
python -m pytest tests -q --timeout=600
```

**完成判据**
- [ ] 7 个往返测试全绿
- [ ] magic bytes 校验存在（不信客户端 MIME）
- [ ] 配额与 GC 可用
- [ ] 未修改任何现有文件

---

### F3 · API 与 Session 层拓宽

`P0` / 1 周 / 依赖 F2，依赖主计划 Phase 2

**背景**
第一次修改现有代码。从这一卡开始有回归风险，所以 MD1（纯文本零变化）要格外小心。

**涉及文件（用 Grep 定位，不要信行号）**

| 文件 | 锚点 | 改法 |
|---|---|---|
| `api_server.py` | `class ChatRequest` | `message: MessageContent` |
| `api_server.py` | `def _session_message` | 不再无条件 `str(content)` |
| `api_server.py` | 无 | 新增 `POST /attachments` |
| `core/session.py` | `async def prompt` | 参数类型拓宽 |
| `protocol/requests.py` | `class PromptRequest` | `text: str` → `content: MessageContent` |

**操作步骤**

1. `ChatRequest.message` 改为 `MessageContent`。**pydantic 会自动接受两种形态**——旧客户端发字符串照样工作，这就是 DCD3 的实现方式。

2. `_session_message`（锚点 `def _session_message`）：

```python
def _session_message(role: str, content: MessageContent, *, run_id: str, **metadata) -> dict:
    """构造一条持久化消息。

    改造前这里无条件 str(content)，所以 content block 列表会被烧成 Python
    repr 字符串，图像静默消失。现在纯文本仍走 str()（零回归），内容块列表
    序列化成 JSON 可还原的形式。
    """
    if isinstance(content, str):
        stored: Any = str(content)          # 原路径，逐字节不变
    else:
        stored = [b.model_dump() for b in content]
    return {..., "content": stored, ...}
```

3. 新增 `POST /attachments` 端点：

```python
@app.post("/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: str = Form("latest"),
) -> AttachmentUploadResponse:
    """上传附件，返回 attachment_id。

    刻意用 multipart 而不是 JSON+base64：base64 会让请求体涨 33%，而且
    FastAPI 会把整个 JSON 读进内存。multipart 可以流式落盘。
    """
```

4. **配置请求体大小上限**。实测确认 `api_server.py` 当前**没有任何 body size 限制**（`:63` 的 `FastAPI()` 和 `:2570-2582` 的 `uvicorn.run` 都没配）。加一个中间件：

```python
#: 请求体上限。附件走 /attachments 的 multipart 流式落盘，普通 JSON 请求
#: 不该有这么大——限制它可以挡住 base64 塞进 /chat 的滥用。
MAX_JSON_BODY_BYTES = 4 * 1024 * 1024
```

5. **SSE 侧要防 base64 泄漏**（规则 MD2）。现有截断是 4096 字符（`:2153-2154`），但那是工具结果。检查所有往 SSE 写内容的地方，确保 content block 是以 `to_plain_text()` 的形式出现的。

6. 往返测试加：

```python
def test_text_only_request_produces_identical_session_message():
    """纯文本请求的持久化结果与 Phase F 之前逐字节相同。"""

def test_multimodal_request_survives_session_persistence():
    """含图像的消息存进 session 再读出来，attachment_id 还在。"""

def test_sse_never_contains_base64():
    """跑一轮带图对话，断言所有 SSE 事件里没有 base64 片段。"""
```

**验收命令**

```powershell
python -m pytest tests/test_multimodal -q
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 旧客户端发纯字符串仍正常（写一个显式测试）
- [ ] `POST /attachments` 可用，multipart 流式落盘
- [ ] JSON body 上限已配置
- [ ] SSE 无 base64 的测试通过
- [ ] evals 零回归

---

### F4 · Agent 链路与记忆层拓宽

`P0` / 1.5 周 / 依赖 F3

**背景**
这是 Phase F 最容易漏改的一卡——要动十几处。**强烈建议让 Sonnet 5 审查 diff。**

**涉及文件（每处用 Grep 定位）**

| 文件 | 锚点 | 说明 |
|---|---|---|
| `core/agent_v2.py` | `async def run(self, user_input` | 入口类型 |
| `core/agent_v2.py` | `HumanMessage(content=` | 消息构造 |
| `core/agent_v2.py` | `def _to_openai_messages` | **收口点，最关键** |
| `core/agent_v2.py` | `def _estimate_tokens` | 图像 token 怎么算 |
| `core/prompts/registry.py` | `def build_user_message` | 返回类型 |
| `memory/short_term.py` | `def add_user_message` | 持久化保真 |
| `memory/long_term.py` | `json.dumps(messages` | 同上 |
| `memory/chat_storage.py` | `_sanitize_text(str(` | 同上 |
| `memory/compressor.py` | `m.get("content", "")` | 压缩时的降级 |

**操作步骤**

1. **`_to_openai_messages` 是收口点**，先改它。加分支而不是改现有分支：

```python
            elif role == "human":
                content = getattr(m, "content", "") or ""
                if isinstance(content, str):
                    # 原路径，逐字节不变（约束 DCD3）
                    out.append({"role": "user", "content": content})
                else:
                    # 多模态：交给 provider 渲染，因为 OpenAI 和 Anthropic 的
                    # 图像块格式不同。base64 只在这一层出现（约束 DCD2）。
                    out.append({
                        "role": "user",
                        "content": self._provider.render_content_blocks(
                            content, self._capabilities,
                        ),
                    })
```

2. 在 `core/providers/base.py` 加 `render_content_blocks`：

```python
    def render_content_blocks(
        self, blocks: list, caps: ModelCapabilities,
    ) -> list[dict] | str:
        """把内容块渲染成该 provider 的 API 格式。

        默认实现走 OpenAI 的 image_url + data URI 形式。Anthropic 的格式
        不同（source.type = "base64"），由 AnthropicProvider 覆写。

        模型不支持 vision 时降级为纯文本并**明确记录**——不能静默丢图
        （规则 MD5），调用方应该在更早的地方就拦住。
        """
        if not caps.supports_vision:
            raise UnsupportedModalityError(
                f"model does not support vision; "
                f"drop the image or switch to a vision-capable model"
            )
        ...
```

> **⚠️ 让 Grok 先查清各家格式差异**：
> ```
> 对比 OpenAI Chat Completions 和 Anthropic Messages API 的图像输入格式：
> 1. 各自的 content block JSON 结构（字段名、嵌套）
> 2. 支持 URL 还是只支持 base64？data URI 前缀怎么写？
> 3. 单张图和单次请求的尺寸/数量上限
> 4. 图像消耗多少 token？怎么估算？
> 5. 支持哪些 MIME？
> 每条给文档原文和 URL。
> ```

3. **图像 token 估算**。Phase A 的 `count_tokens` 只处理文本。加一个 `count_image_tokens(width, height, spec)`——**用 Grok 查到的官方公式**。估不准会让上下文压缩时机错乱。

4. **记忆层保真**。三个文件（`short_term.py`、`long_term.py`、`chat_storage.py`）都是同一个模式：纯文本走 `str()`（原路径），内容块列表存 `model_dump()`。**读回来时要能还原成 block 对象**，不能只还原成 dict。

5. **压缩器降级**。`memory/compressor.py` 做长期记忆压缩时，图像应该降级成 `to_plain_text()` 的占位符——把整张图重复喂给压缩模型既贵又没用。这一条写进注释说明理由。

6. 往返测试加：

```python
def test_image_block_survives_short_term_memory():
def test_image_block_survives_long_term_persistence():
def test_compressor_degrades_images_to_placeholders():
def test_unsupported_vision_model_raises_not_silently_drops():
def test_text_only_path_produces_identical_openai_payload():
```

最后一条是零回归的关键证据——用一个固定的纯文本输入，断言 `_to_openai_messages` 的输出与改动前完全一致。

**验收命令**

```powershell
python -m pytest tests/test_multimodal -q
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 九处锚点全部处理（在 PR 描述里逐条列出）
- [ ] 纯文本 payload 逐字节相同的测试通过
- [ ] 不支持 vision 时**抛异常**而非静默丢图
- [ ] 记忆往返保真
- [ ] evals 零回归
- [ ] Sonnet 5 审查过 diff 并确认没有漏改

---

### F5 · 缓存键策略

`P0` / 5d / 依赖 F4

**背景**
**这是 Phase F 唯一有真实设计权衡的一卡。** 现有精确缓存是文本 SHA256（`cache/precise_cache.py:93-99`），语义缓存是 `SequenceMatcher` 文本相似度（`semantic_cache.py:68-74`）。图像进来之后两者都失效。

**决策已经做好了，照做即可**（Composer 2.5 不要在这里自己发挥）：

| 缓存 | 多模态请求怎么办 | 理由 |
|---|---|---|
| **精确缓存** | **启用**。键 = `sha256(文本部分 + 有序的 attachment_id 列表)` | attachment_id 本身就是内容哈希，所以"同样的图 + 同样的问题"能正确命中。这是有价值的——用户经常对同一张图追问 |
| **语义缓存** | **直接跳过** | 给图像算文本相似度是伪科学。"这两个问题文本很像但配图不同"会导致**错误命中**，返回和图片无关的答案。这类 bug 极难被发现，收益远小于风险 |

**操作步骤**

1. 精确缓存键。找到 `core/agent_v2.py` 里构造 `cache_key` 的地方（锚点 `cache_key = json.dumps`）：

```python
        from protocol.content import is_multimodal

        if isinstance(user_input, str):
            # 原路径，键与 Phase F 之前完全一致（约束 DCD3）
            cache_key = json.dumps([user_input, memory_fingerprint], ...)
        else:
            # attachment_id 是内容 sha256，所以"同图同问"能正确命中。
            # 顺序敏感：图在文字前和图在文字后是不同的请求。
            parts = [
                b.text if b.type == "text" else f"img:{b.attachment_id}"
                for b in user_input
            ]
            cache_key = json.dumps([parts, memory_fingerprint], ...)
```

2. 语义缓存跳过。找到语义缓存的调用点：

```python
        # 语义缓存做的是文本相似度匹配（cache/semantic_cache.py:68-74）。
        # 对多模态请求，"文本相似但配图不同"会错误命中并返回与图无关的
        # 答案——这类 bug 几乎不可能在使用中被发现。收益不值这个风险。
        if not is_multimodal(user_input):
            hit = semantic_cache.get(...)
```

3. `tests/test_multimodal/test_cache_keys.py` 必须覆盖：

```python
def test_text_only_cache_key_is_unchanged():
    """纯文本的缓存键与 Phase F 之前逐字符相同。"""

def test_same_image_same_question_hits_precise_cache():
def test_same_question_different_image_misses():
def test_block_order_affects_the_key():
def test_semantic_cache_is_skipped_for_multimodal():
def test_semantic_cache_still_used_for_text_only():
```

**完成判据**
- [ ] 6 个缓存测试全绿
- [ ] 纯文本缓存键**逐字符不变**（否则已有缓存全失效，evals 会明显变慢）
- [ ] 语义缓存对多模态确实跳过
- [ ] evals 零回归**且耗时无明显增加**（耗时增加说明缓存键变了）

---

### F6 · 工具层与 MCP

`P1` / 1 周 / 依赖 F4

**背景**
让工具能产出图像（截图、图表），让 MCP 的图像不再被丢弃（`mcp/client.py:811-816`）。

**操作步骤**

1. 工具返回类型从 `str` 拓宽为 `str | ToolResult`，其中 `ToolResult` 可带附件：

```python
@dataclass
class ToolResult:
    """工具的结构化返回。

    绝大多数工具仍然直接返回 str（原路径不变）。只有需要产出图像的工具
    才用这个类型。
    """
    text: str
    attachments: list[str] = field(default_factory=list)   # attachment_id
```

2. `execution/tool_orchestrator.py` 的 `execute_tool`（锚点 `async def execute_tool`）和 `_clean_tool_output`（锚点 `def _clean_tool_output`）加分支。**`str` 分支逐字节不变。**

3. MCP 图像保真。`mcp/client.py:811-816` 改为把图像存进 AttachmentStore：

```python
            elif content_type == "image":
                data = base64.b64decode(item.get("data", ""))
                aid = store.put(data, mime_type=item.get("mimeType", "image/png"),
                                session_id=session_id)
                blocks.append(ImageBlock(attachment_id=aid,
                                         mime_type=item.get("mimeType", "image/png")))
```

4. **音频暂不处理**。`mcp/client.py:815` 的 audio 分支保持占位符，加注释说明"Phase F 只做图像，音频见 §5 扩展手册"。

5. `_clean_tool_output` 的 30000 字符上限（`:265-268`）只作用于 text 部分，附件不受此限。

**完成判据**
- [ ] 返回 `str` 的工具行为完全不变
- [ ] MCP 图像能落进 AttachmentStore 并变成 ImageBlock
- [ ] 音频仍是占位符，且有注释说明为什么
- [ ] evals 零回归

---

### F7 · 重写 vision 工具

`P1` / 5d / 依赖 F4 F6

**背景**
`tools/vision.py` 现在做的是 OCR + 元数据 + 截图落盘，返回字符串，**从不把图像送给 LLM**（§1.2）。而 `docs/modules/tools.md:28` 宣称它用 "multimodal LLM"。这一卡把实现和文档对齐。

**操作步骤**

1. `run_vision` 的 `describe` 操作改为真正调用 vision 模型：把图像存进 AttachmentStore，返回带 `ImageBlock` 的 `ToolResult`，让主模型自己看。

2. **`prompt` 参数现在真正生效**（`tools/vision.py:50-52` 声明了但没用）。

3. **保留 `ocr` 操作走 Tesseract**。理由写进注释：OCR 对纯文字截图比 vision 模型又快又便宜又准，不要为了"用上多模态"而删掉它。

4. `screenshot` 操作改为把截图存进 AttachmentStore 并返回 `ImageBlock`，而不是返回文件路径字符串。

5. **模型不支持 vision 时**（`caps.supports_vision == False`）：`describe` 自动降级到 `ocr` + 元数据，并在返回文本里**明确说明"当前模型不支持看图，以下是 OCR 结果"**。这不违反 MD5——MD5 禁止的是静默丢弃，明确告知的降级是可以的。

6. 修正 `docs/modules/tools.md:28`。

**完成判据**
- [ ] `describe` 真的走 vision 模型
- [ ] `ocr` 仍走 Tesseract 且有注释说明理由
- [ ] 不支持 vision 的模型上有明确的降级提示
- [ ] `docs/modules/tools.md` 与实现一致

---

### F8 · Desktop 附件 UI

`P0` / 1.5 周 / 依赖 F3，**依赖主计划 Phase 4**（并复用 Phase 3 的模型上限摘要）

**背景**
多模态的价值 90% 在界面上（§0.3）。

**操作步骤**

1. Desktop 支持三种输入方式：拖拽文件、粘贴剪贴板图像、点击附件按钮。
2. 上传走 `POST /attachments`，UI 显示上传进度（大图可能要几秒）。
3. 消息气泡里内联显示缩略图，点击放大。
4. 历史消息里的 `ImageBlock` 能正确渲染（从 `GET /attachments/<id>` 拉）。
5. **必须做的错误态**：
   - 当前模型不支持 vision → 附件按钮置灰 + tooltip 说明原因（用 `ModelCapabilities.supports_vision`）
   - 文件过大 / 格式不支持 → 上传前就在前端拦住并给出明确提示
   - 上传失败 → 可重试，不要丢用户的输入

6. **OpenTUI 侧**：显示 `[图片: filename.png]` 占位符即可，**不要**去折腾 sixel/kitty 协议。终端图像协议的兼容性很差，投入产出比极低。在 `docs/modules/frontend.md` 里写明这个决定和理由。

**完成判据**
- [ ] 三种输入方式可用
- [ ] 缩略图渲染 + 点击放大
- [ ] 三种错误态都有明确提示
- [ ] OpenTUI 有占位符且不崩
- [ ] Desktop 的 typecheck 和测试都过

---

### F9 · 视觉 Agent 角色

`P1` / 1 周 / 依赖 F7 F8、Phase C

**背景**
这是 Phase F 的题眼——**多模态 × 多 Agent**。前面所有卡都是铺路，这一卡才是"共同协作"。

**操作步骤**

1. `AgentSpec` 加字段（用 Phase C 预留的 `extra`，或直接加正式字段）：

```python
    #: 该角色是否需要 vision 能力。
    #: 为 True 时，Orchestrator 在构造 AgentRuntime 就会校验模型的
    #: ModelCapabilities.supports_vision，不支持则**构造时报错**——
    #: 不要等到运行时才发现这个角色看不了图。
    requires_vision: bool = False
```

2. 在 `AgentRuntime.__init__` 加校验：

```python
        if spec.requires_vision and not self._capabilities.supports_vision:
            raise AgentSpecError(
                f"role {spec.role!r} requires vision but model "
                f"{spec.model!r} does not support it"
            )
```

3. 加内置角色 `ui_reviewer`（`core/agents/roles/builtin.yaml`）：

```yaml
  - role: ui_reviewer
    display_name: 界面审查员
    prompt_stage: agent_ui_reviewer
    tools: [read_file, vision, screenshot]
    requires_vision: true
    can_delegate: false
    memory_scope: private
    timeout_s: 300
```

4. **黑板要能放图像引用**。Phase C 的 `BlackboardEntry.value: str` 需要拓宽成 `MessageContent`（Phase C §6 已经预告了这一点）。

5. **委派时的图像传递**。`DelegateRequest.task: str` 也要拓宽——architect 委派给 ui_reviewer 时要能把截图带过去。

6. 端到端场景测试：

```
coder 改完 UI 代码
  → 委派给 ui_reviewer，附上改动前后的截图
  → ui_reviewer 用 vision 模型对比，把问题写进黑板
  → coder 从黑板读结论并修复
```

用 mock LLM 跑通这条链。

**完成判据**
- [ ] `requires_vision` 在**构造时**校验（不是运行时）
- [ ] `ui_reviewer` 角色可用
- [ ] 黑板和委派都能携带图像引用
- [ ] 端到端场景测试通过
- [ ] 单 Agent 纯文本路径 evals 零回归

---

### F10 · 多模态评测

`P1` / 5d / 依赖 F9，依赖主计划 Phase 1

**操作步骤**

1. `evals/tasks.py` 加 `setup_attachments` 字段，让任务能带图。
2. 加检查类型 `image_referenced`（断言 Agent 真的看了图，而不是靠文件名猜）。
3. 加至少 5 个多模态任务：读图表、看 UI 截图找问题、对比两张图、OCR 后处理、看错误截图定位代码。
4. **对照实验**：同样的任务用 vision 模型 vs 纯文本模型（只给 OCR 结果）。差值就是多模态的真实增量。
5. **诚实面对结果**。如果 OCR + 文本模型在多数任务上不比 vision 模型差且便宜十倍，**写进文档**，并把 vision 设为按需启用。

**完成判据**
- [ ] 5 个多模态任务已加且通过 `scripts/lint_eval_tasks.py`
- [ ] 对照矩阵已产出并提交
- [ ] 结论（含负面结论）写进 `docs/modules/evals.md`

---

### F11 · 配额、清理与运维

`P1` / 4d / 依赖 F2 F8

**操作步骤**

1. `rxycode attachments gc` 命令：清理孤儿附件，打印回收空间。
2. 会话删除时级联 `release_session`（约束 DCD4）。
3. 启动时检查附件目录总大小，超配额时告警。
4. 附件目录**必须在 `.gitignore` 里**（它在 `~/.rxycode/` 下，本来就不在仓库，但要确认没人把它配到仓库内）。
5. **安全**：`GET /attachments/<id>` 要校验请求方对该 session 有权限，不能凭 id 就能拉任意附件。id 是 sha256 不易猜，但这不是访问控制。

**完成判据**
- [ ] GC 命令可用且有测试
- [ ] 级联删除有测试
- [ ] 附件访问有权限校验（**这条别漏，是真实的安全问题**）

---

### F12 · 文档

`P1` / 5d / 依赖 F1–F11

**操作步骤**

1. 新建 `docs/modules/multimodal.md`：
   - 四条设计约束（§2.2）及理由
   - 为什么用引用而非内联
   - **为什么语义缓存对多模态直接跳过**（F5 的决策记录，这是最容易被后人"优化"掉的决定，必须写清理由）
   - 加一种新 content block 的完整步骤（§5）
   - F10 的评测结论，包括什么时候不该用 vision
2. 新建 `docs/modules/attachments.md`：存储布局、配额、GC、安全模型。
3. 更新：`docs/modules/tools.md`（vision 工具改了、工具返回类型拓宽了）、`docs/modules/cache.md`（多模态键策略）、`docs/modules/memory.md`（content block 持久化）、`docs/modules/agents.md`（`requires_vision`）、`docs/modules/frontend.md`（OpenTUI 不做终端图像的决定及理由）、`docs/modules/api_server.md`（`/attachments` 端点、body 限制）。
4. 更新 `AGENTS.md` 架构图。
5. 更新主计划的 Phase 表，标记整条路线完成。

---

## §4 Phase F 出口检查

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=900
python -m pytest tests/test_multimodal -q
python -m pytest tests/test_agents -q
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
python -m evals.cli run --backend agent --agents multi --modality vision --save-baseline
cd desktop; npm run typecheck; npm test; cd ..
```

**Phase F 完成的定义：**
- 全部命令绿，**纯文本路径零回归且耗时无明显增加**
- 往返保真测试全绿（没有任何一层把 content block 烧成字符串）
- Desktop 能拖图、贴图、看缩略图，错误态齐全
- `ui_reviewer` 角色能在多 Agent 编排里真正看图并把结论写进黑板
- 多模态评测矩阵已产出，**结论（含负面结论）写进了文档**
- 附件有配额、有 GC、有访问控制

---

## §5 扩展手册：加一种新的 Content Block

> Phase F 之后加音频、视频、PDF 的标准流程。

**第 1 步 · 先问值不值得**

回答：这个模态能解决什么现有方式解决不了的问题？如果"转成文本再处理"效果差不多且便宜十倍，就不要加。F10 的评测方法可以用来验证。

**第 2 步 · 定义 block**

`protocol/content.py` 加一个 `BaseModel`，加进 `ContentBlock` 联合，**并在 `to_plain_text()` 里加降级分支**（这一步最容易漏——漏了会让不支持该模态的模型收到空内容）。

**第 3 步 · 扩 AttachmentStore**

`core/attachments/store.py` 的 MIME 白名单和 magic bytes 校验表。单文件上限可能要按类型区分（视频比图片大得多）。

**第 4 步 · 扩 ModelCapabilities**

`config/model_capabilities.py` 加 `supports_audio` 之类的字段，各 provider 的 `capabilities()` 里填。

**第 5 步 · 扩 provider 渲染**

`core/providers/base.py` 的 `render_content_blocks`，以及各 provider 的覆写。**先让 Grok 查清各家格式差异。**

**第 6 步 · 补往返测试**

`tests/test_multimodal/test_roundtrip.py` 加对应的保真测试。**这一步不能省**——它是防止"某一层静默丢数据"的唯一手段。

**第 7 步 · 前端**

Desktop 的输入与展示。不支持时的置灰与提示。

**第 8 步 · 评测**

加至少 3 个该模态的任务，跑对照实验。**如果对照实验显示没有增量，回到第 1 步重新考虑。**

**第 9 步 · 文档**

`docs/modules/multimodal.md` 的支持列表 + 决策记录。

---

## §6 整条路线到此结束

Phase F 完成后，RxyCode 的形态是：

```
headless 核心（Session + 类型化协议）
  ├─ 模型层：provider 策略 + 能力元数据，支持 per-model 优化
  ├─ Agent 层：角色化多 Agent，独立工具集 / 记忆 / 缓存 / 熔断，显式委派协议
  ├─ 模态层：文本 + 图像端到端，引用式传递，provider 差异化渲染
  └─ 客户端：OpenTUI（文本）+ Desktop（全功能）+ 未来的 IDE 扩展
```

**后续的候选方向**（不在本路线内，需要重新评估优先级）：
- IDE 扩展（协议做好后成本很低）
- 音频/视频模态（按 §5 流程）
- Tauri 迁移（包体积优化，主计划 §8.1 已说明这是可逆决定）
- Skills 自动创建（主计划 §3.4 明确移除的项，若团队扩张可重新评估）
