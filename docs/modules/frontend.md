# frontend/ - Ink TUI Frontend (+ OpenTUI dual entry)

## What Is This Module?
The terminal user interface. Primary rollback path is Ink (React 18). OpenTUI dual entry lives in `frontend/opentui-app/` (Bun + React 19.2+ + `@opentui/react@0.4.5`) to fix flicker (ScrollBox) and cursor misalignment (native textarea) without upgrading the Ink package to React 19.

## Architecture
- Ink 5.x under `frontend/` (React 18) — rollback / `RXYCODE_TUI=ink`
- OpenTUI under `frontend/opentui-app/` (React 19.2+) — default when Bun is available
- Communicates with the Python API server via HTTP/SSE
- Ink: Node.js process; OpenTUI: `bun run src/index.tsx` — both launched by main.py

## Key Files
| File | Purpose |
|------|---------|
| src/App.tsx | Main app component - orchestrates all UI components |
| src/index.tsx | Entry point - renders App, handles TTY check |
| src/types.ts | TypeScript types: Message, StatusInfo, Mode, Command |
| src/components/ChatPanel.tsx | Chat message display with Static/dynamic regions |
| src/components/InputBox.tsx | User input with slash command completion |
| src/components/StatusBar.tsx | Bottom status bar with token/cache/mode info |
| src/components/ProgressBanner.tsx | Streaming progress indicator |
| src/components/ErrorBoundary.tsx | React error boundary |
| src/components/CommandPalette.tsx | Command palette overlay |
| src/components/ModeIndicator.tsx | Mode indicator (Plan/Build/Compose) |
| src/hooks/useApi.ts | API client hook - SSE streaming, message batching |
| src/apiClient.ts | Loopback API URL and automatic bearer-header helpers |
| src/hooks/useMode.ts | Mode state management |

## Core Code: ChatPanel.tsx

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

## Build
- TypeScript compiler: npx tsc
- Tests: npx vitest run
- Dev mode: npm run dev (tsx)
- Production: npm run build && npm start
