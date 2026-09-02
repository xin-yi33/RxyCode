# frontend/ - OpenTUI Frontend (default) + Ink fallback

## What Is This Module?
The terminal user interface. **Default path is OpenTUI** under
`frontend/opentui-app/` (Bun + React 19.2+ + `@opentui/react@0.4.5`): ScrollBox
chat, native textarea, alternate screen, mouse selection, and OpenCode-style
nested dialogs. Ink under `frontend/` (React 18) remains as an optional
rollback via `RXYCODE_TUI=ink`.
`frontend/protocol-client/` is the shared **@rxycode/protocol-client** package: JSON-RPC 2.0 line protocol over stdio for OpenTUI and Desktop (types generated from `protocol/schema.json` via `bun run generate`).

## Architecture
- OpenTUI under `frontend/opentui-app/` (React 19.2+) — **default** when Bun is available
- Ink 5.x under `frontend/` (React 18) — rollback / `RXYCODE_TUI=ink`
- **Chat transport** (P5): `RXYCODE_TRANSPORT=stdio|http` (default `stdio`)
  - `stdio` (default): spawns `python -m appserver`, uses `@rxycode/protocol-client` JSON-RPC
  - `http`: embedded FastAPI + SSE (`chatApi` → `/chat/stream`) — fallback via `RXYCODE_TRANSPORT=http`
  - Status bar 上下文/缓存: stdio 消费 `event/token_usage` + `models/list.context_window`（不再依赖 HTTP `/status`）
  - Esc 立即结束 Processing，后台再发 `session/interrupt`
- Settings dialogs (models, MCP, memory) still use HTTP API in both modes
- Expert-team settings are layered (F13): hidden until `agents.enabled`; then team / route / router model / budget appear. Multi-model stays disabled until Phase H.
- OpenTUI: `bun run src/index.tsx`; Ink: Node.js process — both launched by `main.py`

## Key Files (OpenTUI — default)
| File | Purpose |
|------|---------|
| opentui-app/src/App.tsx | Main OpenTUI app — chat, input, shortcuts, dialog routing |
| opentui-app/src/index.tsx | OpenTUI entry — CliRenderer alternate screen + lifecycle |
| opentui-app/src/chatApi.ts | Transport facade — delegates to `transport/` (http or stdio) |
| opentui-app/src/transport/ | P5 transport layer: `httpTransport`, `stdioTransport`, `httpAdmin.ts`, `notifyToStreamEvent.ts`, `sseParser.ts` |
| opentui-app/src/mention.ts | `@agent` mention autocomplete + dispatch over stdio `agent/invoke` |
| opentui-app/src/dialog/* | Nested settings / select / confirm / prompt dialogs |
| opentui-app/src/CommandPalette.tsx | Ctrl+P command palette |
| opentui-app/src/ApprovalDialog.tsx | Tool approval UI |
| opentui-app/src/QuestionDialog.tsx | Interactive `question` tool (choice / free text) |
| opentui-app/src/questionInfo.ts | Parse `question/request` params and summarize tool args |
| opentui-app/src/Markdown.tsx | Markdown rendering |
| opentui-app/src/streamReducer.ts | Streaming message state |
| opentui-app/src/commands.ts / commandRouter.ts | Slash-command parsing/routing（含 `/effort`：2026-08-12，选择思考强度，档位随当前模型，local 命令） |
| opentui-app/src/dialog/DialogEffort.tsx | `/effort` 档位选择对话框（复用 DialogSelect，档位来自 `models/list` 的 `effort_options`） |
| opentui-app/src/Modal.tsx / brand.ts / statusBar.ts | Shared UI primitives |

## Key Files (Ink — fallback)
| File | Purpose |
|------|---------|
| src/App.tsx | Main Ink app component |
| src/index.tsx | Ink entry point - renders App, handles TTY check |
| src/types.ts | TypeScript types: Message, StatusInfo, Mode, Command |
| src/components/ChatPanel.tsx | Chat message display with Static/dynamic regions |
| src/components/InputBox.tsx | User input with slash command completion |
| src/components/StatusBar.tsx | Bottom status bar with token/cache/mode info |
| src/hooks/useApi.ts | API client hook - SSE streaming, message batching |
| src/apiClient.ts | Loopback API URL and automatic bearer-header helpers |
| src/hooks/useMode.ts | Mode state management |

## Core Code: ChatPanel.tsx (Ink fallback)

**Flicker Prevention:**
- Uses `committedIdsRef` and `staticGenerationRef` to split immutable summaries into Static output and keep active messages dynamic
- Ink's Static component assumes append-only; finalized message IDs are committed once, while a generation key resets Static after `/clear`
- Streaming assistant messages stay dynamic until the `final` event sets `done: true`; later thinking/tool events are inserted before the assistant, and `final` moves the answer after all progress messages
- Completed thinking and tool messages commit immutable summaries only, so private reasoning and large raw tool results never enter terminal scrollback
- clearKey prop forces remount on /clear to flush old Static content

**Message Types:**
- UserMessage: Bordered user input display
- AssistantMessage: Markdown-rendered response
- ThinkingMessage: Spinning indicator with elapsed time, expandable content
- ToolMessage: Tool call with status icon, duration, exit code
- SystemMessage: System notifications
- WelcomeMessage: Initial capability list (shown when no messages)

## Core Code: useApi.ts

**Streaming Architecture:**
- sendMessage() opens SSE connection to /chat/stream
- Token events are batched (50ms throttle) to reduce re-renders
- Message updates queued and flushed every 100ms
- Final event merges all pending updates into single setMessages() call
- fetchStatus() called after streaming ends to update token stats
- Mutating requests automatically carry the per-launch bearer token inherited
  from `main.py`; `/status` remains a public loopback health read.
- Model setup submits typed JSON to `/models/onboard`. API keys never enter a
  slash-command string or command log, and the wizard masks the active key input.

**Event Types:**
- progress: Thinking progress updates
- token: Streaming text tokens
- reasoning: Model reasoning (thinking) stream
- tool_call: Tool execution started
- tool_result: Tool execution completed
- approval_request: Tool approval request (see ApprovalDialog)
- question_request: Correlated choice/free-text question
- final: Final response
- error: Error occurred
- plan/step: Planning step updates

## Core Code: App.tsx

**Layout:**
1. Header: RxyCode version, mode, model name
2. Settings panel (toggle with Ctrl+P)
3. ChatPanel: Main chat area and the single streaming-answer preview
4. ProgressBanner: Streaming progress
5. InputBox: User input with command completion
6. StatusBar: Memory, billing, cache, tokens, mode

**Keyboard Shortcuts:**
- Ctrl+T: Toggle thinking visibility at the App level; remains available when dialogs replace the input box
- /thinking: Same server-synchronized toggle as Ctrl+T
- Ctrl+P: Toggle settings
- Tab: Cycle mode (Plan/Build/Compose)
- Esc: Cancel current operation
- Enter: Submit input

## Desktop (Electron)

`frontend/desktop-app/` is the Codex-style GUI. Composer 模型菜单在同名模型上显示完整 id；没有密钥的条目带「未配置密钥」且不可选，发送会被拦住，避免再走到 `Starting Agent worker…` 后才报 `ARK_API_KEY`。Composer `+` 菜单提供：文件和文件夹、在项目中使用 Work（选工作区并开新聊天）、目标 `/goal`（按 session 记住持续目标）、计划模式 `/plan`（`session/prompt` 传 `mode: "plan"`，只输出 `#` / `## Summary` / `## Steps` 计划文档）。计划文档下方「是，实施此计划」切到 Agent/`build` 并按文档执行；「请你补充说明哪里需要改进」回车仍留在 plan 模式改写文档。主输入框在计划模式下同样继续改计划。`/build` 切回 Agent 模式。设置页只有在 `models/list` 真的返回 method-not-found 时才显示「旧版 appserver」；后端未连接或运行时失败会显示真实原因，不再误报 BLOCKED_PREREQUISITE。侧栏项目夹只在悬停时显示「…」与添加会话；三点菜单与右键共用置顶 / 编辑 / 分区 / 资源管理器 / 永久工作树 / 归档聊天 / 移除项目。审查、终端、浏览器、文件、侧边聊天是右侧栏拉开后的居中入口（`right-panel-menu`，含快捷键）；点一项才进入对应 pane。顶栏只保留拉开右栏 / 底栏的开关。底部栏是带标签页的终端（`bottom-terminal-tab` / `+` / 关闭），占主栏下方、左侧栏通高。关闭审查不再收起整栏。

## Environment (OpenTUI)

| Variable | Default | Effect |
|----------|---------|--------|
| `RXYCODE_TRANSPORT` | `stdio` | `stdio` = appserver subprocess (default); `http` = SSE via embedded API |
| `RXYCODE_PROJECT_ROOT` | set by `main.py` | Repo root for appserver `PYTHONPATH` (stdio mode) |
| `RXYCODE_APPSERVER_PYTHON` | set by `main.py` | Python executable for appserver subprocess |
| `RXYCODE_WORKSPACE_ROOT` | cwd at launch | `session/new` workspace (stdio mode) |
| `RXYCODE_API_URL` / `RXYCODE_API_TOKEN` | set by `main.py` | HTTP settings; chat fallback when `RXYCODE_TRANSPORT=http` |
| `RXYCODE_APPSERVER_LOG` | unset | If set, appserver stderr is appended here (never written to the TTY — that corrupts OpenTUI) |

## Build
- TypeScript compiler: npx tsc
- Tests: npx vitest run
- Dev mode: npm run dev (tsx)
- Production: npm run build && npm start
