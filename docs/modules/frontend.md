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
- Settings dialogs (models, MCP, memory) still use HTTP API in both modes
- OpenTUI: `bun run src/index.tsx`; Ink: Node.js process — both launched by `main.py`

## Key Files (OpenTUI — default)
| File | Purpose |
|------|---------|
| opentui-app/src/App.tsx | Main OpenTUI app — chat, input, shortcuts, dialog routing |
| opentui-app/src/index.tsx | OpenTUI entry — CliRenderer alternate screen + lifecycle |
| opentui-app/src/chatApi.ts | Transport facade — delegates to `transport/` (http or stdio) |
| opentui-app/src/transport/ | P5 transport layer: `httpTransport`, `stdioTransport`, notify mapper |
| opentui-app/src/dialog/* | Nested settings / select / confirm / prompt dialogs |
| opentui-app/src/CommandPalette.tsx | Ctrl+P command palette |
| opentui-app/src/ApprovalDialog.tsx | Tool approval UI |
| opentui-app/src/Markdown.tsx | Markdown rendering |
| opentui-app/src/streamReducer.ts | Streaming message state |

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
- tool_call: Tool execution started
- tool_result: Tool execution completed
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
