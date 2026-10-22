# 模块边界合同（架构师主文）

> **Status**：Accepted（2026-09-01；2026-09-02 按 PHASE-K §3 密度补文件级变更预算）
> **角色**：`agent-core-boundaries` + `documentation-and-adrs` + `api-and-interface-design`
> **调研**：[`research/2026-09-01-top-coding-agents-core-architecture.md`](./research/2026-09-01-top-coding-agents-core-architecture.md)
> **编号决策**：[`ARCH-001`](../../../../decisions/ARCH-001-single-session-loop.md) · [`ARCH-002`](../../../../decisions/ARCH-002-evolution-seams.md) · [`ARCH-003`](../../../../decisions/ARCH-003-computer-use-direct-control.md) · [`ARCH-004`](../../../../decisions/ARCH-004-targeted-refactor-bar.md)
>
> 本文件是可维护性的牙齿：谁拥有哪些文件、允许 import 谁、改一块时禁止顺手改谁。
> **拆 `core/agent_v2.py`（2026-09-02 实测 6851 行）是架构决策，不是「永远不拆」。** 本目标 diff 仍不含该文件循环改写；抽离排在 [`DEV-ORDER.md`](./DEV-ORDER.md) SP0–SP3。

---

## §1 目标模块图

```
[OpenTUI / Desktop / Ink]
        │  只许 protocol-client / JSON-RPC
        ▼
[appserver]  会话、plugin-host、goal、plan 文件、side_chat
        │  只许 Session 假面 + protocol 类型
        ▼
[Session]  core/session.py:144   无 TUI/HTTP I/O，只 emit
        │
        ├─ [harness]     turn_router / prefix_profile / prewarm / catalog / prompts
        ├─ [isolation]   core/safety + PP10 真沙箱
        ├─ [tools.edit]  tools/edit.py 结构化补丁（PP20）
        ├─ [tools.cu]    Computer Use：接入 OSS MCP，不进 agent_v2
        ├─ [tools.browse] Playwright MCP snapshot+ref（U24 三名；**U46 默认开 + 惰性**）；用户 Chrome CDP（U46 `chrome_attach`）；bundled MCP 或用户插件；不是 webfetch
        ├─ [cache/session] 应用答案缓存 ≠ provider prefix cache；活前缀时「？」不得命中 semantic（UPDATE-01 轨 G）
        ├─ [appserver.session-catalog] OpenTUI `/session` = `sessions/list`（UPDATE-01 轨 H）；不是 chat_storage / `/save-chat`
        ├─ [frontend.effort-picker] OpenTUI `/effort` = Select effort（UPDATE-01 轨 I）；不是 `/variant`；不是改 `formatHeaderLine`
        ├─ [frontend.message-actions] OpenTUI 用户气泡 Message Actions（UPDATE-01 轨 J）；不是 `session/fork`；不是改 `thread/fork` 复制范围
        ├─ [core.session-durability] transcript ≠ catalog ≠ schedule（UPDATE-01 轨 K）；不是 Cursor vscdb；不是重写 U31 / PHASE-N Goal
        ├─ [core.workspace-snapshot] 崩溃 Undo 磁盘 blobs（UPDATE-01 轨 K2）；不是 FileTracker RAM；不是 OpenCode odb vendor
        ├─ [hooks]       PHASE-K K14 + hooks.json
        ├─ [plugin-host] plugin_service + capabilities  唯一 invoke
        ├─ [skills]      斜杠定死（PP1）；索引只进 S2（K10）
        ├─ [mcp]         stdio only → ToolOrchestrator
        └─ [teams]       core/agents/teams/*.yaml   不进 S1
```

AgentV2 应变薄编排器，直到可删。Ink + `api_server.py` SSE = 同一 Session 的后备适配器，**不是第二大脑**（ARCH-001）。

---

## §2 加号 ≠ skill ≠ MCP

| 层 | 用户看见 | 缝 / 协议 | 不是 |
|---|---|---|---|
| 加号 / `/plugin` | 已下载可执行扩展 | plugin-host；`plugin/list`（`protocol/requests.py` PluginListRequest；`appserver/server.py:2603`） | skill 目录、MCP 列表 |
| skill / 斜杠 | `/using-superpowers` 定死 SOP | skills；K9 发现 + K10 S2 + PP1 | 加号第一屏 |
| MCP | `/list-mcp`、设置 | mcp stdio → ToolOrchestrator | 产品会话；加号第一屏 |
| Browser Use | Playwright `browser_snapshot`+ref；用户 Chrome CDP | `browser_use`（U24 三名；U46 默认开）；`chrome_attach`（U46）；bundled 或 user MCP；轨 F 路由 + U46 梯子 | webfetch；PP80 WebView；Pi 无端口静默附着；用 CU **冒充**本行完成 |
| Computer Use | OS 窗口无障碍；**任务限定**下可点浏览器窗口 | `computer_use` + ocu MCP（U20–U23 默认关；U46 信号才进网页轮） | Playwright/Chrome 卡完成；Search/Fetch 静默退路；webfetch |

依据：备忘 P2、PHASE-K KC6、PHASE-P **PC2**。

---

## §3 导入法

| 从 \ 到 | 允许 | 禁止 |
|---|---|---|
| 任何 frontend | `protocol-client` / JSON-RPC 类型 | `import` Python `core/` |
| appserver | `Session`、`protocol/`、plugin-host | 第二套 tool loop；为 CU/插件再开 `api_server.py /chat` |
| harness | `catalog`、`prompts`、`turn_router`、`prefix_profile`、`prewarm` | `plugin_service`、safety 执法、CU、teams 解析 |
| isolation | `core/safety/*`、执行隔离 | 改 S1 来「顺便」做策略 |
| plugin-host | capabilities、`plugin/*` | 第二 invoke；把 skill 列表当 `plugin/list` |
| skills | K9 扫描、`append_turn_context` | skills 列表进 `get_system_s1()`（`core/prompts/registry.py:250`） |
| teams | `validate_team`、`core/agents/` | 团目录进 S1；默认自动路由；在 `agent_v2` 新增长分支 |
| 表面 | 协议事件 | HTTP `/chat` 当第二大脑 |
| CU | 新 MCP 适配器 + capability 开关 | 在 `agent_v2` 写截图循环；用 `cli_list`/`cli_run` 替代本能力；把 Playwright `browser_snapshot` 并进本缝冒充 browse 完成 |
| browse | `core/web_intent.py`、`core/web_escalate.py`、`tools/webfetch.py`、`tools/websearch.py`、OpenTUI `genericSummary` | 重写 U24 MCP 三名；新增 `web_browse` 键；search 零结果跳 Chrome/CU；CDP 失败静默改 CU |

---

## §4 变更预算（按缝）

「优化 harness（学 Codex）」只开 harness 缝。其它愿望走对应缝。**禁止**一次 PR 跨缝顺手改。

### 4.1 harness

**允许改**：`core/turn_router.py`、`core/prefix_profile.py`、`core/prewarm.py`、`core/catalog.py`、`core/prompts/`、`core/turn_context.py`、`core/handoff.py`、`tests/test_cache/`、`evals/` 夹具

**禁止顺手改**：`core/safety/*`、`appserver/plugin_service.py`、`tools/edit.py`、`core/agents/teams/`、`frontend/*`、CU 模块、`core/agent_v2.py` 无关分支

**合入门**：PREFIX（`tests/test_cache/test_s1_s2_split.py` + `test_stable_prefix.py`）。碰 identity 还要 K2 的 IDENTITY 测试（未落地则 BLOCKED，不许用全量绿冒充）。

### 4.2 isolation

**允许改**：`core/safety/policy.py`、`core/safety/approval.py`、`core/safety/audit.py`、新增 `core/safety/isolation.py`、`tests/test_safety_gate.py`、`tests/test_safety_audit.py`

**禁止顺手改**：`core/prompts/`（用改 S1 当策略）、`agent_v2.py` 旁路、`tools/edit.py` 补丁语法、frontend chrome

**正交**：`permission_mode`（`confirm_all|auto_edit|full_auto`）是审批；访问档是沙箱。PHASE-K **KC12**。

### 4.3 tools.edit

**允许改**：`tools/edit.py`、`tools/write.py`（测试函数 cap）、`core/builtin_tool_registration.py` 的 edit 注册、`tests/test_tools/`

**禁止顺手改**：`agent_v2` 循环、隔离剖面、plugin-host、frontend 红绿呈现（那是 PP21）

### 4.4 hooks

**允许改**：K14 指定的桥（`core/hooks.py` 或 `core/plugins`）、`tests/test_plugins/`

**禁止顺手改**：发明 K14 表以外的事件名；`SessionStart` 注入团 bootstrap（LC16）；把 hook stdout 塞进模型上下文

### 4.5 plugin-host

**允许改**：`appserver` 的 `plugin/list|install|uninstall`、`protocol/requests.py` 对应模型、CapabilityRegistry（K1 后）

**禁止顺手改**：第二套 invoke；让 `plugin/list` 返回 skills 或 MCP servers；加号 IA（PP50）在宿主未就绪时伪造列表

### 4.6 Computer Use

**允许改**：新 MCP 适配器（独立进程）、capability 开关、`tests/test_cu/`

**禁止**：在 `agent_v2` 写截图循环；自研跨平台 CUA；用 CLI-Hub `cli_list`/`cli_run` **替代**本能力（可并存）；N 个截图 tool 进 S1；把 Playwright `browser_snapshot` / 轨 F `webfetch` 并进本缝。现网 `core/cu` 若已注册 `browser_snapshot`，与 U24 Playwright 撞名归 **U22/U24**，轨 F / FX3-12 不得改名覆盖。

**优先**：[iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use)（ARCH-003）

### 4.7 表面

**允许改**：`frontend/opentui-app/`（只追加命令，既有 `AVAILABLE_COMMANDS` 条目定义不变）、`frontend/desktop-app/src/renderer/`、protocol-client

**禁止**：import Python `core/`；在 Renderer 里做权限/预算/模型解析；为 side chat 走 `api_server.py /chat`

### 4.8 teams

**允许改**：`core/agents/teams/<name>/` YAML 包、`tests/test_agents/`、必要时 `load_builtin_team` 的调用方

**禁止**：团目录进 S1；默认 `disable_model_invocation: false`；在 `agent_v2` 加团名分支；把 L13 发行版当加团前置

### 4.9 tools.browse（U24 MCP + 轨 F 路由 + U46 升级）

**允许改（轨 F U33–U36）**：`core/web_intent.py`、`tools/search_envelope.py`、`tools/websearch.py` **成功信封**（`SEARCH_SNIPPET_HEADER`；遇 `[search error:` 原样返回）、`tools/webfetch.py` 描述/`FETCH_NO_JS_NOTE`、`frontend/opentui-app/src/lib/toolDisplay.ts` 的 `fetch:`/`browse:` 前缀、`tests/test_core/test_web_intent.py`、`tests/test_tools/test_search_envelope.py`、`tests/e2e/update01_browse/`

**允许改（U46）**：`core/web_escalate.py`、`chrome_attach` 能力键、`chrome_navigate`/`chrome_snapshot`/`chrome_click`、`browser_use` **缺省 True**、OpenTUI `chrome:` 前缀、`EscalateTarget.COMPUTER_USE` 任务信号、bundled-or-user MCP 包装（只保证 capability/list，不画 PP50）、`tests/test_core/test_web_escalate.py`、`tests/test_core/test_web_search_call_scope.py`、§10 文件 B2/B3（`test_web_escalate_quality.py` / `test_search_call_scope.py`）。CDP 只连 `127.0.0.1:9222`。research 多次 `websearch`（一条 query/次）；`SEARCH_CALLS_BEFORE_BROWSER` 只约束 discover。禁止改 `TOTAL_BUDGET` / webfetch timeout 数字（那是 FX3-12）。**禁止改** U36 `test_browse_quality.py`、U34 `test_search_envelope.py`、U35 `test_web_intent.py`。

**允许改（U24，本缝但另一张卡）**：Playwright MCP 配置块、能力键 `browser_use`、`tests/test_browser_use/`。与现网 `core/cu` `browser_snapshot` 撞名归 **U22/U24**，禁止覆盖 StructuredTool.name。U46 不改这三名。

**允许改（FX3-12，另一张卡）**：`tools/websearch.py` / `tools/webfetch.py` 的 **失败串、timeout、引擎回退**。禁止动 U34 信封、U35 描述、webfetch 名、`core/cu`。

**禁止顺手改**：把 `webfetch` 改名为 `browser_*`；新增 `web_browse`；PP80 内嵌 GitHub WebView；搬 Claude 扩展；安装包塞 Chrome；静默拉起用户日常 profile；search 零结果跳 Chrome/CU；CDP 失败静默改 CU；U0–U23 卡体（U20 只加指针）；单任务省 token / 问号失忆。ocu 工具表仍归 U20–U23；U46 只在任务信号下把 `list_apps` 放进本轮 tools。

**合入门**：U36 / U46 / §10 `tests/e2e/update01_browse`；无 key 必须红绿。Playwright 不是唯一 overall。无 live Chrome。

### 4.10 cache / session（轨 G 连续性 + tools 纪律）

**允许改（U37–U45）**：`core/followup.py`、`core/prefix_hydrate.py`、`core/tool_visibility.py`、`core/compact_tools.py`、`core/subagents/parent_result.py`、`AgentV2._fast_reply_with_tools` 的应用答案缓存旁路与 `CancelledError` remember、`_ensure_session_loaded` hydrate、`_select_turn_tools` 的闲 MCP 闸门（不是第二套 selector）、`tests/test_core/test_followup_cache.py`、`tests/e2e/update01_continuity/`

**禁止顺手改**：把用户任务焊进 S1；重写 U3 `microcompact_messages`；U15/U16 卡体；第二套 skill 加载器 / 第二套 `plugin/*` invoke；TurnRouter `skip_await`；`get_relevant_context("你好")` 零分过滤；U24 Playwright / 轨 F browse / 轨 E slash 卡体

**合入门**：U45 / §11 `tests/e2e/update01_continuity`；无 key 必须红绿。live LLM 不是唯一 overall。

### 4.11 appserver.session-catalog / frontend.session-list（轨 H 会话列表）

**允许改（U47–U51）**：`core/session_list.py`、`core/session_title.py`、`core/prompts/session_title.md`、`appserver/sessions.py` **additive** 字段（`generated_title` / `title_is_manual`）、`appserver/task_store.py` optional upsert 键、`appserver/server.py` `_session_summary` additive 键 + prompt 成功后标题钩子、`frontend/opentui-app/src/dialog/DialogSessionList.tsx`、`sessionListKeybind.ts`、`DialogSelect.tsx` **optional** `onKeybind`、`stdioTransport.ts` `listSessions`/`attachSession`、`tests/test_core/test_session_list.py`、`tests/test_core/test_session_title.py`、`frontend/opentui-app/src/dialog/sessionListKeybind.test.ts`、`tests/e2e/update01_session/`。

**禁止顺手改**：`memory/chat_storage.py`；`api_server.py` HTTP `/session`；Ink `frontend/src/App.test.tsx`；`DialogSelect.keyboard.test.tsx` 导航断言；`session/fork` / `thread_fork.py` 语义；新增 `session/pin` / `session/compact`；U25–U32 `parse_slash`；U3 compact PE；U36 `test_browse_quality.py`；U38 `test_followup_cache.py`；4.10 轨 G 文件（`core/followup.py` 等）。

**合入门**：U51 / §12 `tests/e2e/update01_session`；无 key 必须红绿。live LLM 不是唯一 overall。

### 4.12 frontend.effort-picker（轨 I `/effort` 选择器）

**允许改（U52–U56）**：`frontend/opentui-app/src/dialog/effortPicker.ts`、`DialogEffort.tsx`（title/placeholder/options 接线，**不**改 `buildOptions` 返回值）、`useSettingsDialogs.tsx`（model/addmodel 成功后 replace effort）、`DialogAddModel.tsx` **additive**（保存成功仍 `onDone`，由宿主弹 picker）、`App.tsx` composer 元信息行（`formatComposerEffortChip`）、`effortPicker.test.ts`、`composerEffortChip.test.ts`、`effortAfterModel.test.ts`、`tests/test_docs/test_update01_effort_picker_research_manifest.py`、`tests/e2e/update01_effort/`。

**禁止顺手改**：`formatHeaderLine` 三参签名 / `format.test.ts`；`DialogEffort.options.test.ts` 的 `buildOptions` 期望数组；`tests/test_providers/test_effort_presets.py`；U25–U32 `parse_slash`；`/variant` 别名；Ink `frontend/src/App.test.tsx`；占用状态栏公式（U1/U2）；4.11 轨 H 文件（`session_list.py` / `DialogSessionList.tsx` 等）；U36 `test_browse_quality.py`；U38 `test_followup_cache.py`。

**合入门**：U56 / §13 `tests/e2e/update01_effort`；无 key 必须红绿。live LLM 不是唯一 overall。

### 4.13 frontend.message-actions（轨 J 已发送用户气泡）

**允许改（U57–U62）**：`frontend/opentui-app/src/dialog/messageActions.ts`、`DialogMessageActions.tsx`、`RevertBanner.tsx`、`App.tsx` **additive**（UserMessage `onMouseUp` + 横幅 + composer 回填）、`core/session_revert.py`、`protocol/requests.py` **additive** `session/revert` / `session/unrevert`、`appserver/server.py` dispatch、CommandSpec `/undo` `/redo` **additive**、`tests/test_core/test_session_revert.py`、`messageActions.test.ts`、`tests/test_docs/test_update01_message_actions_research_manifest.py`、`tests/e2e/update01_message_actions/`。

**必须抄**：`messageActions.ts` 的 `shouldOpenMessageActions` **没有** `busy` 参数（运行中 overlay 仍开）。Revert 的 `onSelect`：`revertNeedsAbort(isStreaming)` 为 true 时先 `session/interrupt` 等到 idle，再 `session/revert`。Copy / Fork **不得** interrupt。

**禁止顺手改**：`DialogSelect.keyboard.test.tsx` 导航断言；`tests/test_thread_fork.py` 复制范围；`session/fork` 语义；`agent_v2.py` 主循环；Ink `App.test.tsx`；4.12 轨 I 文件（`effortPicker.ts` 等）；4.11 轨 H 文件；U25–U32 `parse_slash` 解析器（只许 additive 词条）；U36 / U38 测试文件。

**合入门**：U62 / §14 `tests/e2e/update01_message_actions`；无 key 必须红绿。live LLM 不是唯一 overall。

### 4.14 core.session-durability（轨 K 落盘 / 调度 / timeout）

**允许改（U63–U68）**：`core/session_durability.py`、`tests/test_core/test_session_durability.py`、`tests/test_docs/test_update01_session_durability_research_manifest.py`、`tests/e2e/update01_durability/`、`appserver/schedule_service.py` **仅确认** boot 调用 `restore_after_restart`（已有则锁测，禁止重写 orphan 语义）、`tools/bash.py` **仅 additive description**（默认 timeout 仍 60）。

**必须抄**：`retain_history_on_model_change()==True`；`set_model_creates_session()==False`；`hydrate_looks_across_dates()==True`；`catalog_stores_prompts()==False`；`file_tracker_is_durable()==False`；`loop_clock_resumes_on_boot()==True`；`loop_replays_killed_foreground_bash()==False`；`goal_autostart_on_open("paused")==False`；`BASH_DEFAULT_TIMEOUT_SECONDS==60`。

**禁止顺手改**：U31 `parse_loop_args`；PHASE-N Goal store；`tools/bash.py` 默认 timeout 改大；`DesktopTaskStore` 写入 prompt；轨 J `session_revert.py`；`agent_v2.py` 主循环；Ink `App.test.tsx`；`chat_storage.py`；4.13 轨 J 文件；4.11 轨 H 文件。

**合入门**：U68 / §15 `tests/e2e/update01_durability`；无 key 必须红绿。live LLM 不是唯一 overall。崩溃文件 Undo 的磁盘权威是 **4.15**（U69–U72），不是本缝把 FileTracker 改成 durable。

### 4.15 core.workspace-snapshot（轨 K2 磁盘快照）

**允许改（U69–U72）**：`core/workspace_snapshot.py`、`core/session_durability.py` **additive**（`workspace_snapshot_store_is_durable` / 体积与 checkpoint 上限）、`history/tracker.py` **只许** flush 后丢掉全文（禁止改成崩溃权威）、`tests/test_core/test_workspace_snapshot.py`、`tests/e2e/update01_snapshots/`。

**必须抄**：磁盘 content-addressed blobs；`SNAPSHOT_MAX_FILE_BYTES=2MiB`；`SNAPSHOT_KEEP_CHECKPOINTS=100`；新进程能 restore before。

**禁止顺手改**：U65 `file_tracker_is_durable()==False`；`tools/bash.py` Field default；OpenCode odb vendor；Cursor vscdb；用户仓库自动 commit。

**合入门**：U72 / §16 `tests/e2e/update01_snapshots`。

---

## §5 拆核（SP*）

见 [`DEV-ORDER.md`](./DEV-ORDER.md) SP0–SP3。证据：高星项目用目录/crate 消化大体量；Cline Task ~3756 行是债。软连接 = 已有 `Session.emit()` / `prompt()`（`core/session.py:144`）。

| 卡 | 做什么 | 本目标 |
|---|---|---|
| SP0 | 测试迁到 Session 假面 | **可开工**（只动 `tests/`） |
| SP1 | 抽出 harness 调用 | 只写卡，不执行 |
| SP2 | 工具只经 ToolOrchestrator | 只写卡，不执行 |
| SP3 | 团逻辑不在 agent_v2 新增长分支 | 只写卡，不执行 |

---

## §6 本文件出口

- [ ] 八缝都有允许改 / 禁止顺手改（含 4.9 tools.browse）
- [ ] **4.11** session-catalog 与 **4.10** cache/session 分行（OpenTUI `/session` ≠ 应用答案缓存）
- [ ] **4.12** effort-picker 与 **4.11** session-list 分行（OpenTUI `/effort` ≠ `/session`；不是 `/variant`）
- [ ] **4.13** message-actions 与 **4.12** effort-picker 分行（用户气泡 overlay ≠ `/effort`；Fork ≠ `session/fork`）
- [ ] **4.14** session-durability 与 **4.11** session-catalog / **4.13** message-actions 分行（transcript ≠ 列表；时钟 ≠ Cursor blob；bash 现网 default ≠ 新政策）
- [ ] **4.15** workspace-snapshot 与 **4.14** 分行（崩溃 Undo 在磁盘 ≠ FileTracker RAM）
- [ ] 加号 ≠ skill ≠ MCP 写进表
- [ ] browse ≠ CU ≠ webfetch（`[tools.browse]` 与 `[tools.cu]` 分缝）
- [ ] 拆核指向 SP0–SP3，且写明必须拆、本目标不执行循环改写
- [ ] CU 禁止替代条款写明
