# frontend/ - OpenTUI Frontend (default) + Ink fallback

## What Is This Module?
The terminal user interface. **Default path is OpenTUI** under
`frontend/opentui-app/` (Bun + React 19.2+ + `@opentui/react@0.4.5`): ScrollBox
chat, native textarea, alternate screen, mouse selection, and OpenCode-style
nested dialogs. Ink under `frontend/` (React 18) remains as an optional
rollback via `RXYCODE_TUI=ink`.
`frontend/protocol-client/` is the shared **@rxycode/protocol-client** package: JSON-RPC 2.0 line protocol over stdio for OpenTUI and Desktop (types generated from `protocol/schema.json` via `bun run generate`).

## Architecture
Release metadata: OpenTUI and Ink headers, stdio `client_version`, and the
frontend package/lock metadata use product version 1.4.5. Desktop metadata
also advances, but v1.4.5 does not publish a Desktop installer. The private
protocol-client package version follows the product version; JSON-RPC stays 1.1.0.

- OpenTUI under `frontend/opentui-app/` (React 19.2+) — **default** when Bun is available
- Ink 5.x under `frontend/` (React 18) — rollback / `RXYCODE_TUI=ink`
- **Chat transport** (P5): `RXYCODE_TRANSPORT=stdio|http` (default `stdio`)
  - `stdio` (default): spawns `python -m appserver`, uses `@rxycode/protocol-client` JSON-RPC
  - `/session` attach 走完整 `session/events`（不是截断后的 `session/items` 页）→ `sessionEventsToMessages`：用 `call_id` 索引配 tool_end，恢复 thought（`event/final.thinking`）、已结束的 tool card、`done` 的 assistant（Markdown 编译后展示）。没有 begin 的 tool_end 仍保留为一条 tool。禁止把加载消息剥成只有 role/content（会让 tool 一直 `[running]`、MD 变源码）。会话列表每次刷新（打开、置顶、重命名、Fork）都递增请求序号，只有最新一次能改列表和缓存。`models/list`、`session/events` 等管理 RPC 有超时；`session/prompt` 没有。任务模型身份是配置里的 `model_id`（`sessions/list` 已带回），显示名和上下文上限都从这一条取出。失败的 `session/set_model` 之后继续显示这个 id，不改其它窗口的全局 active；换会话、重连或成功切模会换掉它。切模请求在等待期间固定发起时的 `session_id` 和代次，迟到成功或失败都不改已经加载的另一会话。关闭会话弹窗后，置顶、重命名、Fork 的迟到回调不再刷新列表缓存。
  - `http`: embedded FastAPI + SSE (`chatApi` → `/chat/stream`) — fallback via `RXYCODE_TRANSPORT=http`
  - Clipboard attachments are OpenTUI-only: bracketed text paste stays literal; Ctrl+V uses a short fallback for terminals that swallow an empty image/file paste, while Alt+V and `/paste` explicitly invoke the one-shot Python helper. Pure local Windows path pastes become attachment chips only after asynchronous regular-file checks. The frontend stores and replays path/name metadata only (never image bytes). stdio may send attachments only when `initialize.capabilities.prompt_attachments === true`; older servers reject visibly and the draft remains available. HTTP uses the existing `/chat/stream` `ChatRequest.attachments` field and requires `GET /status` to advertise `capabilities.prompt_attachments === true` before an attachment request; ordinary turns do not add this preflight. Admission failures remain visible without automatically retrying attachment requests. Follow-up queue items retain their own attachment metadata; immediate `turn/steer` remains text-only.
  - Status bar 上下文/缓存: stdio 消费 `event/token_usage` + `models/list.context_window`（不再依赖 HTTP `/status`）
  - Esc 立即结束 Processing，后台再发 `session/interrupt`
- Settings dialogs (models, MCP, memory) still use HTTP API in both modes。**例外（UPDATE-01 轨 H）**：`/session` 列表走 stdio JSON-RPC `sessions/list`，不走 HTTP `sendCommand("/session")`。**例外（UPDATE-01 轨 I）**：`/effort` overlay 标题锁定 `Select effort`；`/model` 换模型与 `/addmodel` 后弹出同一 overlay；esc = `default`。禁止把命令改名为 `/variant`。**例外（UPDATE-01 轨 J）**：已发送 **user** 气泡右键弹出 `Message Actions`（命中=灰底；**运行中仍弹**）。Revert/Copy/Fork。Copy/Fork 不 interrupt；Revert busy 先 `session/interrupt`。禁止 `session/fork` 当 Fork。**例外（UPDATE-01 轨 K）**：换模型不新开 session；隔夜 attach 同一 `session_id` 后 hydrate dated memory。禁止把列表当 transcript
- Expert-team settings are layered (F13): hidden until `agents.enabled`; then team / route / router model / budget appear. Multi-model stays disabled until Phase H.
- OpenTUI: `bun run src/index.tsx`; Ink: Node.js process — both launched by `main.py`

## Key Files (OpenTUI — default)
| File | Purpose |
|------|---------|
| opentui-app/src/App.tsx | Main OpenTUI app — chat, input, shortcuts, dialog routing。composer 元信息行：`{mode} · {model} · {effortChip}`（UPDATE-01 U54）；禁止改 `formatHeaderLine` 三参换芯片。已发送 user 气泡右键 Message Actions（U58）；Revert 横幅（U59） |
| opentui-app/src/TranscriptMountWindow.tsx / `transcriptMountBudget.ts` | Transcript render budget: tail-first 80-message native mount window with 40-message overlapping older/newer pages. Full `messages` remains authoritative; `/copy`, tool/thought/markdown cards, revert/fork and source data are not truncated. The top/bottom controls and PageUp/PageDown move a bounded sliding window; anchor rows keep their viewport line across a page prepend. New session loads and `/clear` reset the window. |
| opentui-app/src/followupQueue.ts | Processing 时 follow-up 队列（FIFO，上限 10）；立即发送走 `turn/steer` |
| opentui-app/src/FollowupQueueBar.tsx | 队列行：立即发送 / 编辑 / 删除 |
| opentui-app/src/index.tsx | OpenTUI entry — CliRenderer alternate screen + lifecycle |
| opentui-app/src/chatApi.ts | Transport facade — delegates to `transport/` (http or stdio) |
| opentui-app/src/transport/ | P5 transport layer: `httpTransport`, `stdioTransport`, `httpAdmin.ts`, `notifyToStreamEvent.ts`, `sseParser.ts` |
| opentui-app/src/clipboard.ts | One-shot clipboard helper lifecycle, strict bounded metadata parsing, conservative path-drop parsing and async file validation |
| opentui-app/src/mention.ts | `@agent` mention autocomplete + dispatch over stdio `agent/invoke` |
| opentui-app/src/dialog/* | Nested settings / select / confirm / prompt dialogs。`/session` 默认走 `DialogSessionList` + JSON-RPC `sessions/list`（UPDATE-01 轨 H）；禁止 HTTP `sendCommand("/session")` 读 `chat_storage`。Esc 关闭不变。`/effort` 走 `DialogEffort` + `effortPicker.ts`（UPDATE-01 轨 I；标题 `Select effort`） |
| opentui-app/src/CommandPalette.tsx | Ctrl+P command palette |
| opentui-app/src/ApprovalDialog.tsx | Tool approval UI |
| opentui-app/src/QuestionDialog.tsx | Interactive `question` tool (choice / free text) |
| opentui-app/src/questionInfo.ts | Parse `question/request` params and summarize tool args |
| opentui-app/src/Markdown.tsx | Markdown rendering |
| opentui-app/src/streamReducer.ts | Streaming message state |
| opentui-app/src/commands.ts / commandRouter.ts | Slash-command parsing/routing（含 `/effort`：2026-08-12；UPDATE-01 轨 I 不改命令名、不加 `/variant` 别名） |
| opentui-app/src/dialog/effortPicker.ts | UPDATE-01 轨 I：`SELECT_EFFORT_TITLE` / `buildEffortPickerOptions` / `shouldOpenEffortPicker` / `formatComposerEffortChip`。Default 首行；esc=`default`。**不**改现网 `buildOptions` |
| opentui-app/src/dialog/DialogEffort.tsx | `/effort` overlay（复用 DialogSelect）。标题锁定 `Select effort`；选项 = `[Default] + effort_options`。禁止把 Default 塞进 `buildOptions` |
| opentui-app/src/dialog/messageActions.ts | UPDATE-01 轨 J：`shouldOpenMessageActions` / `pointInUserBubble` / overlay 文案。右键 `button===2`。**busy 仍弹 overlay**。Fork 方法锁定 `thread/fork`。Revert busy 走 `revertNeedsAbort` → `session/interrupt` |
| opentui-app/src/dialog/DialogMessageActions.tsx | 用户气泡 Message Actions overlay（Revert / Copy / Fork）。复用 DialogSelect，禁止重写导航 |
| opentui-app/src/Modal.tsx / brand.ts / statusBar.ts | Shared UI primitives |

**Transcript native mount budget (OpenTUI):** `ScrollBox` viewport culling only
skips drawing off-screen children; it does not unmount their native renderables.
`TranscriptMountWindow` therefore mounts at most 80 transcript messages and
slides that bounded window by 40 messages when navigating older/newer pages.
Message objects and their content remain in App state; this is a render-tree
budget, not transcript deletion, summarization, or an RSS/Private-memory claim.

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
- Shift+Enter / Ctrl+Enter: Insert newline（2026-09-23：Ctrl+Enter 补进
  `promptKeyBindings.ts` 绑定表与 `promptSubmitKey.ts` 纯函数；此前 Ctrl+Enter
  无绑定落空，什么都不发生）

**2026-09-23（P0/P1b 验证内联）**：子代理（专家团各阶段）的流式 token/reasoning
带 `intermediate` 标记，`streamReducer` 不再把它们追加进主聊流；专家团阶段
分隔线（「──────── stage · role ────────」）不再渲染成主聊流 system 消息，
阶段信息只走状态行。主代理输出不受影响。

## Desktop (Electron)

`frontend/desktop-app/` is the Codex-style GUI. Composer 模型菜单在同名模型上显示完整 id；没有密钥的条目带「未配置密钥」且不可选，发送会被拦住，避免再走到 `Starting Agent worker…` 后才报 `ARK_API_KEY`。Composer `+` 菜单提供：文件和文件夹、在项目中使用 Work（选工作区并开新聊天）、目标 `/goal`（按 session 记住持续目标）、计划模式 `/plan`（`session/prompt` 传 `mode: "plan"`，只输出 `#` / `## Summary` / `## Steps` 计划文档）。计划文档下方「是，实施此计划」切到 Agent/`build` 并按文档执行；「请你补充说明哪里需要改进」回车仍留在 plan 模式改写文档。主输入框在计划模式下同样继续改计划。`/build` 切回 Agent 模式。设置页只有在 `models/list` 真的返回 method-not-found 时才显示「旧版 appserver」；后端未连接或运行时失败会显示真实原因，不再误报 BLOCKED_PREREQUISITE。侧栏项目夹只在悬停时显示「…」与添加会话；三点菜单与右键共用置顶 / 编辑 / 分区 / 资源管理器 / 永久工作树 / 归档聊天 / 移除项目。审查、终端、浏览器、文件、侧边聊天是右侧栏拉开后的居中入口（`right-panel-menu`，含快捷键）；点一项才进入对应 pane。顶栏只保留拉开右栏 / 底栏的开关。底部栏是带标签页的终端（`bottom-terminal-tab` / `+` / 关闭），占主栏下方、左侧栏通高。关闭审查不再收起整栏。

## Environment (OpenTUI)

2026-10-13: the unified `edit` file tool uses the existing edit-family card.
`operation="write"` (or an unambiguous historical content payload) displays
`Wrote` and the content preview; replace/patch display `Edited` and red/green
differences. Old write/edit/patch cards remain readable. Whole-file overwrite
previews still show submitted content, not a verified before/after diff.

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

## Web (apps/web)

Web theme state remains in the existing app-root `ThemeSync`: `rxy_theme` cookie initializes Zustand, and the selected theme updates the root `.dark` class and `data-theme`. Cookie reads and writes are best-effort so browser storage restrictions do not prevent an in-memory theme change; no localStorage fallback is used. The global CSS declares `color-scheme: light` for the light theme and `dark` for `.dark`, including native controls. This does not guarantee immunity to vendor-forced night-mode transformations.

ALTCHA 3.4.1 must receive its endpoint through `challenge`, not the unsupported legacy `challengeurl`. The widget uses the supported JSON `configuration` attribute for `hideFooter`/`hideLogo`, and clears its single-use payload whenever it leaves the verified state. The server's V1 challenge format, signing, and verification remain unchanged. Browser regression coverage lives in `tests/web/w3/test_w3_c08_browser_regressions.py`; run it with `python -m pytest tests/web/w3/test_w3_c08_browser_regressions.py -k chromium -q`. WebKit and physical-device behavior require separate available runtimes.

When ALTCHA 3.4.1 emits its `error` state, the auth widget makes one bounded
fallback attempt using a same-origin V1 challenge and the pinned `js-sha256`
pure-JavaScript implementation. The fallback runs only in a secure context,
hashes the unchanged `SHA-256(salt + decimal counter)` input, yields in small
main-thread batches, and stops on abort, expiry, or the existing 90-second
limit. Failure leaves the auth token empty; another attempt requires the
visible retry button. The normal worker-backed widget path is unchanged.

The console stylesheet is built with Tailwind CSS `3.4.19`, PostCSS `8.5.31`,
and Autoprefixer `10.6.1` (exact versions in both `package-lock.json` and
`bun.lock`). The previous Tailwind v4 output relied on cascade layers and newer
color/transition CSS; Chromium `98.0.4758.0` ignored the utility rules and left
the `/app` flex shell and fixed mobile sidebar unstyled. `tailwind.config.js`
maps the existing semantic palette to comma-separated RGB custom properties so
v3 opacity utilities such as `bg-card/60` and `bg-waiting/15` remain valid; the
`shadow-sm` value is pinned to the prior console elevation. `vite.config.ts`
uses conservative syntax targets (`chrome90`, `safari14`, `es2020`) only; these
are not a browser-support promise and do not add polyfills.

Composer request IDs prefer `crypto.randomUUID()`. Where that method is absent,
`src/lib/secureRequestId.ts` uses `crypto.getRandomValues()` and sets RFC 4122
UUIDv4 version/variant bits; there is no `Math.random()` path. If secure random
values themselves are unavailable, the composer shows an inline error and
does not issue a task request. A network-failed retry retains the same draft
ID; server responses continue to follow the existing request-id reset rules.

The production CSS and computed-layout regressions are in
`tests/web/w3/test_w3_c08_browser_regressions.py`. They build and serve a
production bundle only when selected, reject cascade layers, `@property`, CSS
nesting, `color-mix()` and `oklch()`, and inspect mobile/desktop shell layout,
sidebar overlay, theme, composer transition completion, and model-button text
colors. To run those checks use
`python -m pytest tests/web/w3/test_w3_c08_browser_regressions.py -k 'production_css or production_app_layout' -q`.
The optional `RXYCODE_LEGACY_CHROMIUM` environment variable points to a real
Chromium 98 executable; the test checks its actual browser version and does not
spoof the user agent. The secure request-ID fallback test can be run against a
real Chromium 90 executable using `RXYCODE_UUID_FALLBACK_CHROMIUM`; otherwise
it removes only `randomUUID` in the modern test context while retaining real
`getRandomValues`. These checks do not establish general Chrome 90/Safari 14
support; WebKit, Safari, and physical-device behavior remain separate targets.

### 2026-10-22 CAPTCHA transport and execution-path correction

This section supersedes the earlier ALTCHA note above only where it says the
fallback requires `isSecureContext === true` or that the normal widget is
unchanged on every device. The compatibility solver requires an HTTPS page (or
loopback HTTP for local development), not the browser's `isSecureContext` flag,
Worker, or `crypto.subtle`. Public `rxycode.xyz` and `www.rxycode.xyz` HTTP
entries upgrade before React renders; other non-loopback HTTP origins render no
auth form. Caddy independently redirects allowlisted public HTTP using
Cloudflare's overwritten `X-Forwarded-Proto`, with explicit route ordering and
one-day HSTS without subdomain/preload flags.

Mobile-like clients selected by touch, viewport, and mobile-UA signals start
the chunked pure-JS solver directly. Desktop clients dynamically load the
official ALTCHA worker widget and fall back to the same solver on widget error
or load failure. These signals affect execution only: all clients submit the
same V1 payload to the same server HMAC verifier, with unchanged endpoint,
counter maximum, TTL, and replay protection. The UA is never an authorization
signal. The public HTTP 200 observation established that HTTP could be served;
it did not establish the URL used by the user's handset or an HTTPS
`isSecureContext` regression on that handset.

The focused regressions and opt-in anonymous live smoke are in
`tests/web/w3/test_w3_c08_browser_regressions.py`. The live smoke requires an
isolated Playwright context and makes no auth POST; it checks the public HTTP
308 with a raw `http.client` request rather than relying on browser/CLI HTTPS
upgrade behavior. Local focused browser runs completed with 24 passed and 3
WebKit cases skipped because its browser binary is not installed; web typecheck
passed, and official Caddy `v2.11.7 validate` accepted `Caddyfile.prod` after
the downloaded release matched its published SHA-512. These are historical local
checks; deployed state is recorded separately below and in `OPS-LOG.md`.

R5 was deployed from the frozen `mobile-compat-20261022-091225-9e85b988`
snapshot on 2026-10-22 20:32:24 CST; the product version did not change. Public
anonymous live ALTCHA checks passed 9/9 across real Chromium 148/98/90. Final
Chromium 98 public UI smoke passed at 320×640 and 667×375, including stable
dark/restored computed colors matching CSS vars, settled drawer/focus, and login
readiness; ten anonymous screenshots were updated. RUM POSTs were aborted and
other business writes were zero. The R5 theme control is the frozen
`useUi`/`rxy_theme` cookie path, not the later dirty-main preferences WIP. This
does not establish WebKit, Safari, or physical-device behavior. The concise
comparison and verification caveats are in
`docs/deploy/mobile-browser-adaptation-20261022.md`.

## Web 控制台（UI-2026-10-22 开发包，apps/web）

路由：`/app`（会话）、`/app/p/:projectId`（项目首页）、`/scheduled`（定时任务）、`/settings/:section`（general/appearance/notifications/security/archived/models）、`/plugins`（占位）；`/app/settings?section=x` 旧深链重定向到对应新分区。侧栏三分区：导航（新任务/Ctrl+K 搜索/定时任务）+ 项目 + 会话（置顶与最近分组、⋯ 菜单走 sessions 生命周期 API）；桌面收起为 56px 图标轨。`SearchModal`：250ms 防抖、AbortController、IME 安全、五类搜索与 cursor 分页。外观引擎 `lib/appearance.ts` 把服务端偏好解析为 `<html>` data 属性与 `--rxy-*` 变量；`rxy_theme` cookie 仅作访客回退，无 localStorage。i18n `lib/i18n.tsx`（auto/zh-CN/en），偏好 locale 优先、`rxy_locale` cookie 次之、navigator 兜底。归档会话在 SessionPage 显示只读横幅并隐藏 Composer。安全：thinking 时间线条目为纯进度块，不渲染 reasoning/intermediate 原始文本（`tests/web/w3/test_w3_c03_unit.py` 契约）。后端 API 契约测试在 `tests/web/w10/`（postgres 容器同 w9）。

模型选择器仅消费 `source=byok` 项：平台模型不会从旧 catalog/cache 中显示、选中或作为默认值；旧草稿仍保留原 `model_ref`，若它指向已停止的平台模型则提示配置/重选并阻止提交，不自动改选或发请求。BYOK `model_ref` 原样保存与提交。Composer 选中按钮和菜单项只展示模型名（回退 `model_id`），不展示 provider、分组或重复 ID；搜索仍匹配 provider，菜单项 key 继续使用完整 `model_ref`。模型设置列表同样忽略旧 catalog 中的平台项，不展示平台可用性文案。

BYOK-only enforcement policy（前后端共同约束）：不设超级号/管理员例外；旧 allowlist 或 `enforce=0` 不得恢复平台模型；旧平台默认值必须忽略；worker 若拿到旧 snapshot 或缺少 snapshot 必须拒绝执行。BYOK 密钥加解密、ownership/version 校验与 SSRF 防护保持原实现，不因移除平台路径而放宽或重写。

### BYOK Composer 草稿模型生命周期热修（2026-10-23）

成功提交后 `clearDraft` 只清正文与本次 `requestId`，保留显式 `modelRef`；运行中、终态和路由切换继续使用同一选择。首页 `__new__` 收到服务端 `session_id` 后，仅在目标草稿尚无显式选择时继承本次有效 `modelRef`，不会覆盖目标会话已有选择，也不写全账号默认值。登出仍走 `resetDrafts` 清理私人草稿。选择有效模型时只清除与未选模型关联的陈旧 `BYOK_REQUIRED` 提示；实际模型权限拒绝保持可见。回归覆盖见 `tests/web/w10/test_composer_model_lifecycle.py`。

### 刷新模型恢复与待定状态发送门控（2026-10-23）

已存在会话仅以最新历史 run 的 `model_ref` 恢复选择；若最新引用不可用，提示用户重选，不静默退回更早 run。对已登录用户，在没有有效显式选择且 catalog 尚未返回时，新任务 `/app` 与会话 Composer 均禁用发送，submit/Enter 也执行相同拦截；访客仍优先显示原登录提示。现有会话的历史加载/失败状态独立门控；有效显式 BYOK 选择可继续，不必等待历史。失败时显示恢复失败、重试或手选提示，不把请求失败误报为缺 Key。

上述状态按草稿/会话隔离；发送成功清正文并保留模型，新 session 只继承到尚无显式选择的草稿，登出清空私人草稿。未新增全局默认模型存储、接口或自动挑选策略，BYOK 权限与“仅显示模型名”规则不变。回归包括候选 `e2e/test_model_restore_page.py` 真实浏览器 10/10，及 `tests/web/w10/test_composer_model_lifecycle.py` 2/2。此补丁已静态上线；普通完整 HTML 响应中的 Cloudflare Web Analytics 注入与原始 index Range 字节核验见 `docs/deploy/OPS-LOG.md`。

#### 线上真实 provider 验收补记（2026-10-23）

主审在会话 `28093b300301433497d66789cf9f808a` 实测两轮 `deepseek-flash` BYOK：刷新同会话、不重选模型后 Enter 创建的两条 Run（`aa43aa3a71ba43dcaea72b218c26eb1c`、`8615057e01f0478c855964d738f470a7`）均 succeeded；两次请求保留同一 `model_ref=m_8f193a80f3a84948b7ff3e9974160c5f`。正常退出/重登后重开会话仍自动恢复，无误报 Key 缺失。线上仅验证一个实际可用模型，不把本地多模型 mock 结果当作真实多模型验收。390×844 Chromium 视口无横向溢出且按钮仅显示模型名；未进行 vivo 真机测试。

### 聊天前端打磨与产物归属（UI-01～09 + 产物列表，2026-10-24）

- **滚动唯一写口**：`features/timeline/useChatScrollController.ts` 是唯一写 `scrollTop` 的模块（SessionPage 只挂 `data-testid=chat-scroll`）。follow 阈值 40px、jump 阈值 120px；滚动方向区分用户输入（`lastUserInputRef`：wheel/touchmove/翻页键打时间戳）与浏览器 scroll anchoring（`CONTENT_SYNC_GRACE_MS`）——两条都满足才视为锚定位移，避免流式期间用户下滚被 `restoreReadingAnchor` 拉回。
- **预览分栏**：`features/preview/SplitWorkspace.tsx`（`chat-preview-split`/`chat-preview-handle`/`data-preview-pane`）拥有拖拽、Esc（drag snapshot 优先恢复）、双击/重置与 ≤767px overlay 模式；**chat 子树永驻**——无预览时两层包装退化为 `display:contents` 而非切回 fragment，Composer 附件与滚动监听不因预览开关重挂载。`openSignal` nonce 是唯一允许重开已折叠 pane 的入口（`SessionPage.openPreview` 递增）。`split.ts` 的 `runSpring` 用 ≤4ms 定长子步积分——30FPS 单步 Euler 对 rigid(k=1200) 发散。
- **产物列表**：`features/runs/ArtifactRows.tsx` 渲染 `<section data-artifacts>`——「产出文件 (N) — 以上回答在工作区生成的文件」归属分区（不是裸列表）；行内 `components/FileName.tsx`（扩展名保留截断 + `title`/`aria-label` 全名）默认内嵌 `components/FileTypeIcon.tsx`（扩展名→10 类，Windows 式类别着色+字形）；下载/预览控件均有 `title` tooltip。
- **思考/任务块**：`ThinkingBlock` 展示 reasoning delta 累积的真实思考文本（placeholder 过滤 + snapshot 替换，对齐 OpenTUI 语义），可展开；`TasksBlock` 渲染 `plan.updated`/`todo.updated` 为 checkbox 进度清单。
- **共享小件**：`components/Collapse.tsx`（0fr→1fr 折叠，inert+aria-hidden）、`CopyButton.tsx`+`lib/useCopyFeedback.ts`+`lib/clipboard.ts`（真实剪贴板布尔、2.5s 对勾、诚实失败）、`components/streamReveal.ts`（grapheme 安全逐字进入，reduced-motion 直通）、`components/FileTypeIcon.tsx`/`FileName.tsx`。
- **Composer**：IME 保护（compositionend 后 500ms 内 Enter 不提交、keyCode 229、repeat、dialog[open]）+ `submitInFlightRef` 同步闸门（同一任务内两次 Enter 只一个 task POST）。
- **回归**：`tests/web/w3/test_chat_interaction_contracts.py`、`test_chat_visual_contracts.py`、`test_chat_composite_e2e.py`（共享 fixture `_chat_case.py`）；契约断言见各文件 docstring。
- **OpenTUI 同步打磨**：`frontend/opentui-app` 侧新增 `theme.ts` SURFACES 近黑 token、`lib/displayColumns.ts`（CJK 列宽对齐）、`lib/copyFeedback.ts`、`lib/fileName.ts`（复合后缀截断）、`ToolCard` 的 `fileEditVerb`（unified edit 写全文时标 Wrote）；`e2e/ui-polish-verify.mjs` 的清理只杀本测试 spawn 的进程树（`listCliProcesses(rootPid)` 按 ParentProcessId BFS，不再命令行子串全机匹配）。

### Process-liveness evidence row（2026-10-24）

Web full 的 worker projection now maps typed `event/progress.details` to
`process.liveness`, not `assistant.delta(channel=status)`. `eventReducer`
shows every result as a compact timeline row containing elapsed time, the
five-second observation window, CPU start/end, IO byte delta, process count,
the model's `continue` / `stop` / `unknown` action, and its note. It never
places this evidence in the Thought block or the final answer, and does not
replace an unrecognized result with the generic `处理中…` placeholder.

The durable projection whitelists only the typed evidence fields; command
lines, raw stdout/stderr, prompts, and arbitrary extra payload keys are not
copied. Replay is deduplicated by event `seq` and again by
`(probe_id, details.seq)` in the reducer. Malformed evidence renders as
`unknown`. Existing text-only progress, approval, question, tool, Thought, and
final-answer behavior remains unchanged.

2026-10-24 user protection: without explicit user confirmation, no Web
consumer or future refactor may bypass the five-second observation,
current-session model judgment, or per-result user feedback.

### 反馈功能（feedback，2026-10-27）

- **设置页 tab**：`/settings/feedback`（`features/feedback/FeedbackSection.tsx`）= 共用表单 `FeedbackForm.tsx` + 「我的反馈」列表 + `feedback_admin` 批次管理子区；honeypot `name=website` + `CAPTCHA_REQUIRED` 时内联 `AltchaWidget`；图片走 XHR `/api/v1/feedback/images`（选择/拖拽/粘贴，≤5 张，≤5MB，png/jpeg/webp，前端先验后传）。
- **RunCard 入口**：`SessionPage` 为每个 RunCard 传 `onFeedback`（打开预填 `module=run_output`/`kind=content_quality` 的 Modal）与 `onTerminal`。
- **自动询问**：`features/feedback/autoPrompt.ts` 是零依赖纯函数策略（`AutoPromptPolicy` + `signalFromRunView`），`useAutoFeedbackPrompt.ts` 只做粘合（storage/时钟/visibility/composer 焦点/Modal 门全部可注入）。RunTimeline 的 `onTerminal` 只在本页面真实观察到 非终态→终态 转换时回调——历史回放不触发，这是「实时性」门的第一道。
- **评分/门细节**：权重表与阈值（score≥3）、九道门、1500ms 延迟窗 + 输入取消、20s 自动收起，均见 `docs/release-notes/CHANGELOG_v1.4.6.md` 反馈一节与 `autoPrompt.test.ts` 固定语料（`MATRIX should-show:8/8 should-hide:14/14 FP=0 FN=0`，不得为迁就实现改标注）。
- **测试**：`tests/web/w3/test_feedback_e2e.py`（复用 `_chat_case.py` 桩 + MockEventSource；注意 reducer 的 seq 缺口等待——SSE 注入必须用连续 seq）。
