# frontend/src/ - 前端源码

## 这个文件夹负责什么

RxyCode 终端 UI 的全部 TypeScript/React 源码。基于 Ink（React for terminals）构建，通过 SSE 接收后端流式数据，渲染聊天面板、思考流、工具调用、命令面板和弹窗。

## 核心原理

前后端解耦 + 流式优先：界面组件只关心交互和展示，后端 Python Agent 通过 `/chat/stream` SSE 端点提供能力。思考过程和最终回复均为逐 token 流式推送，前端实时渲染（50ms 批处理）。

## TypeScript 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `App.tsx` | 应用入口组件，组合 Header + ChatPanel + InputBox/Modal | 顶层布局、弹窗调度、命令分发 |
| `layout.ts` | 终端布局自适应辅助 | 命令面板和弹窗的高度随终端行数自适应，防溢出 |
| `index.tsx` | Ink render 入口 | 启动 React 渲染、挂载鼠标管理器 |
| `log.ts` | 前端日志 | 分级日志（info/warn/error/debug）输出到 stderr |
| `logo.ts` | ASCII art | RxyCode logo |
| `theme.ts` | 颜色常量 | Catppuccin 风格色板 |
| `types.ts` | 类型定义 + 命令注册表 | Message/Mode/StatusInfo/AVAILABLE_COMMANDS |
| `mouse.ts` | SGR 1006 鼠标解析 + React Context | 鼠标事件解析与分发 |
| `stdinBridge.ts` | stdin 桥接 | 清理鼠标报告字节后再交给 Ink |
| `testUtil.tsx` | 测试辅助 | 宽终端 render 用于 ink-testing-library |
| `hooks/useApi.ts` | API 通信层 | SSE 流式接收、消息状态管理、命令发送 |
| `components/` | UI 组件目录 | 见下 |

## 文件详解

### `layout.ts`

- 写了什么：终端布局自适应辅助函数
- 功能是什么：命令面板和弹窗的可见行数随终端高度自适应
- 核心原理：命令面板和弹窗都是底部锚定的列表。鼠标坐标计算假设列表贴底（`topRow = rows - listHeight`），如果高度固定且终端过短，列表会溢出到终端外，导致鼠标坐标错位。`maxVisibleFor(termRows)` 动态计算可用行数（最小 4，最大 12），确保列表始终贴底。
- 代码规模：约 33 行

关键对象/函数：

- `maxVisibleFor(termRows: number): number`：计算可用行数
- `paletteHeight(termRows: number): number`：命令面板总高度 = maxVisible + 6（边框+标题+搜索+分隔+底）
- `modalHeight(mv: number): number`：弹窗总高度 = mv + 4（边框+标题+分隔+底）

### `hooks/useApi.ts`

- 写了什么：SSE 流式通信层，管理消息状态、流式渲染、命令发送
- 功能是什么：与后端 `/chat/stream` 建立 SSE 连接，逐事件解析并实时更新 React 状态
- 核心原理：**流式优先**——思考过程（`reasoning` 事件）和最终回复（`token` 事件）均为逐 token 流式推送。防抖 50ms 确保流畅但不过度渲染。首个 token 到达时创建实时 assistant 消息，后续 token 增量更新，`final` 事件替换为最终内容。
- 代码规模：约 490 行

关键对象/函数：

- 函数 `useApi()`：返回 `{ messages, streamingContent, status, isStreaming, sendMessage, sendCommand, fetchStatus, cancelRequest, addMessage, setMessages }`
- 内部 `handleEvent(ev)`：SSE 事件分发器，处理 `reasoning`/`progress`/`plan`/`step`/`tool_call`/`tool_result`/`token`/`final`/`error`/`done`
- 内部 `debouncedUpdateThinking(text, step?)`：思考内容防抖更新（50ms，累积模式）

### `components/ChatPanel.tsx`

- 写了什么：聊天面板，渲染所有消息类型
- 功能是什么：展示用户消息、思考过程、工具调用、助手回复、系统消息
- 核心原理：**Static + 动态区分离**——已定稿的消息放入 Ink `<Static>`（不重渲染），活跃消息在动态区实时更新。间距紧凑：无多余 padding 和空行。
- 代码规模：约 219 行

关键组件：

- `WelcomeMessage`：欢迎屏（无 paddingTop/PaddingBottom，紧凑布局）
- `ThinkingMessage`：思考过程展示（流式时强制展开，完成后尊重 toggle）
- `ToolMessage`：工具调用展示（running/success/error/timeout 状态图标）
- `UserMessage`：用户消息（彩色边框包裹）
- `AssistantMessage`：助手回复（Markdown 标题/列表/代码块渲染）

### `components/AddModelWizard.tsx`

- 写了什么：`/addmodel` 命令的可视化向导弹窗
- 功能是什么：4 步引导用户输入模型名称、API Key、API URL、昵称
- 核心原理：替代旧的"把步骤提示塞进聊天区"行为。弹窗替代 InputBox 渲染（不会双框），每步显示已收集字段（API Key 掩码显示），URL 校验失败原地重输。
- 代码规模：约 95 行

关键对象/函数：

- 类型 `AddModelStep = 'provider_model_id' | 'api_key' | 'api_url' | 'nickname'`
- 组件 `AddModelWizard`：props = `{ step, data, error?, onSubmit, onCancel }`

### `components/InputBox.tsx`

- 写了什么：底部输入框 + 命令面板
- 功能是什么：用户输入文本/命令，Ctrl+P 打开命令面板（扁平列表，无分类标题）
- 核心原理：命令面板用 `maxVisibleFor(termRows)` 自适应高度，`offset: 4`（边框+标题+搜索+分隔后是第一项，恒定）。Enter 提交用户输入文本（不提交列表第一项）。
- 代码规模：约 250 行

### `components/Modal.tsx`

- 写了什么：通用弹窗组件
- 功能是什么：列表选择弹窗（session/model/memory/skill/mcp/queue/schedule）
- 核心原理：高度用 `maxVisibleFor(termRows)` 自适应，`offset: 3`（边框+标题+分隔后是第一项）。
- 代码规模：约 120 行

## 流式管道架构

```
后端 (Python)                              前端 (TypeScript)
─────────────────                         ──────────────────────────
_raw_stream()                              useApi.ts
  |                                          |
  +-- OpenAI async stream                    fetch /chat/stream (SSE)
  |     |                                      |
  |     +-- reasoning_content chunk           parse SSE events:
  |     |     -> tui.write_reasoning()          +-- 'reasoning' -> update ThinkingMessage (50ms 防抖, 累积)
  |     +-- content token                      +-- 'token'     -> create/update live AssistantMessage (50ms 批)
  |     |     -> tui.stream_token()            +-- 'tool_call' -> show ToolMessage
  |     +-- tool_calls delta                   +-- 'tool_result' -> update ToolMessage
  |                                            +-- 'final'    -> finalize AssistantMessage + ThinkingMessage
  +-- StreamTUI (api_server.py)
        |
        +-- asyncio.Queue -> SSE event_gen()
```

## 典型协作关系

通过 `http://127.0.0.1:8765` 与后端 API 协作，不直接导入 Python 模块。
