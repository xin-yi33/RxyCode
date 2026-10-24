# tools/ - Tool System

## What Is This Module?
Provides all tools the agent can use to interact with the environment: file operations, shell commands, web access, git, and more. Tools are registered via a central registry and orchestrated by the execution layer.

## Architecture
Tools follow the LangChain StructuredTool pattern. Each tool has:
- A name and description (for LLM tool selection)
- An args_schema (Pydantic model for structured input)
- A func (the actual implementation)

## Two-Tier Tool Schema (2026-10-13, 检索式分层)

Every LLM request's `tools` array is **two tiers**:

- **Frozen core** — the built-ins (and `tool_search` itself once registered),
  sorted by name and byte-stable across turns so the provider prefix cache
  keeps hitting (FX6 unchanged).
- **Deferred** — everything tagged `metadata["source"] in {"mcp", "plugin"}`
  (e.g. ~90 GitHub-MCP tools), which **never appears in the request schema**.
  A GitHub-scale MCP connection no longer adds tens of thousands of schema
  tokens per round.

Discovery (`core/tool_search.py`, AI-Agents-in-Depth 图 4-4 pattern):

1. Model calls `tool_search(query)` — a real, always-on meta tool registered
   by `_refresh_mcp_tools` the first time a deferred tool lands.
2. Its result returns the top matches' **full schemas inline in the tool
   result message** (which appends to trajectory — cache prefix untouched).
   Same session dedup: a tool already exposed returns only an "ALREADY
   AVAILABLE" reminder, not the schema again.
3. To invoke a discovered tool the model emits the free-form envelope
   `<tool_call>{"name": "mcp_x", "arguments": {...}}</tool_call>` — parsed by
   `parse_deferred_tool_json_calls` into the standard dispatch dicts and
   executed through the **same** ToolOrchestrator approval/audit path (no
   second invoke channel). Unknown names and bad JSON become explicit
   malformed-call feedback, never silent no-ops.

Invariants (K例复审修订 2026-10-13):
- `tool_search` is a **resident** from session start (empty catalog answered
  gracefully), not "when the first MCP arrives"; subset policies force-include
  it; `risk=read` is a floor only, so the tool is classified READ in
  `core/safety/policy.py` AND in `PLAN_READONLY_TOOL_NAMES`.
- `_get_core_tools()` output varies only when the frozen core changes;
  adding/removing an MCP server no longer mutates the request schema after
  the first registration of `tool_search`.
- Prewarm binds through the same `_get_core_tools()` (`core/prewarm.py`
  `core_tools_for`), so the hello-turn prefix equals the work-turn prefix.
- Discovery result messages carry `DISCOVERY_PIN_MARKER`; ordinary compaction
  (`microcompact_messages`) leaves them at their position. Exposure tracking
  is bound to `(session_id, schema sha256)` — new session or schema change
  re-exposes; it never returns stale "ALREADY AVAILABLE" from a prior session.
- `defercall_N` ids increase monotonically for the session; mixed
  native+envelope replies get every envelope rejected with an explicit
  ToolMessage (never silently dropped); an unterminated envelope is an
  explicit parse error, never silently treated as the final answer.
- Graph path (`execution/executor.py`) shares the tier: `create_agent` is
  bound with the frozen list only (proxies resolved back to the registered
  tool for the deferred flag), and `_DeferredEnvelopeDispatchMiddleware`
  dispatches envelopes through the same orchestrator (approval/audit/journal).

### Resident / on-demand / compat entry（K例复审裁定表）

频率口径：**按调用形态与失败的代价比第一原则评估**（现有审计日志混有来源
不明的调用，不足以支撑"无人使用"结论——这也是裁定边界）。

| 工具 | 层 | 理由 |
|---|---|---|
| read/view/ls/grep/glob | 常驻 | 每个编码轮次的观察面（read 与 view 语义重叠但参数/行区间行为不同，合并会断既有调用） |
| edit（operation=replace\|write\|patch） | 常驻 | 代码改写主力。模型面只有**一个**文件变更工具；三种语义作为 `operation` 参数保留（write 全量、replace 点改、patch 标准 diff），`write`/`patch` 退为内部实现 |
| bash | 常驻 | Shell 出入口，几乎所有构建/测试/探查路径 |
| websearch/webfetch | 常驻 | 联网搜索/抓取高频且为只读 |
| task(todo)/task_manage/todo_write | 常驻 | 状态带与长程任务源；两个入口已统一单一 in_progress 校验（K3-9） |
| memory/history | 常驻 | 上下文检索（memory 是持久层示意，history 是会话轨迹轴；作用域不同并存） |
| vision/open_file | 常驻 | TUI/Desktop 日常预览路径 |
| download_file/change_directory/diagnostics/datetime/format/question/skill/final_answer | 常驻 | 日常功能面/对话管理 |
| **download_skill / download_mcp / team_install** | **按需**（`DEFERRED_BUILTIN_TOOL_NAMES`） | 安装类动作低频、高危（DANGER）；不进 schema 既省预算也不做错误默认项。经 `tool_search` 暴露、envelope 派发 |
| **workflow** | 常驻（观察评估中，待单独审计） | 长任务编排工具，新特性还在被验证（另一会话工作流）；本批不动它的层级，**待该特性独立验收后再裁定** |
| 所有 MCP / 插件 | 按需 | `metadata.source` 标记层 |
| 兼容入口 | — | `_select_turn_tools` 已废弃；`task`/`task_manage` 兼容名字仍在；`shell` 归一 `bash` |

## Key Files
| File | Purpose |
|------|---------|
| registry.py | ToolRegistry - per-agent injectable catalog (F2). `default_registry` is the process default; a Coordinator member gets a scoped copy, not the process table. `registry` is a compat alias |
| bash.py | BashTool - execute shell commands with timeout and output capture. Default **hard cap 1800s**. Runtime probes CPU/IO at **180/300/600s** and reports to the user and the model; busy search/traversal is not killed; idle-CPU/IO jobs yield at that checkpoint so the model decides. Git argv still uses 60s. |
| read.py | ReadTool - read file contents with line range support |
| write.py | WriteTool - 内部全量写入实现 + `post_write_report()` 诊断入口；**不再**作为模型工具注册（模型面走 `edit --operation=write`） |
| edit.py | EditTool - 唯一模型面文件变更工具（`operation=replace\|write\|patch`），同步 `edit_file` 为纯写入，异步路径挂写后诊断 |
| patch.py | PatchTool - 内部统一 diff 实现；**不再**作为模型工具注册（模型面走 `edit --operation=patch`） |
| grep_tool.py | GrepTool - search files by regex pattern |
| glob_tool.py | GlobTool - find files by glob pattern |
| git_tool.py | GitTool - git operations (status, diff, commit, etc.) |
| webfetch.py | HTTP GET fetch (no JS). Not a browser. Track F U34/U35: description + `FETCH_NO_JS_NOTE`. Name stays `webfetch`. |
| websearch.py | Search snippets (DDGS/Baidu/Bing/Google). Not page content. Track F U34: `[search_snippet non-authoritative]` / `[sponsored]`. **U46**: one `query` per call; long research is multiple calls. `TOTAL_BUDGET=25s` is per call, not per research job. |
| file_download.py | FileDownloadTool - download files from URLs to ~/.RxyCode/output/ |
| download_tool.py | `download_skill` / `download_mcp` module-level functions + `download_skill_tool` / `download_mcp_tool` (DANGER risk) |
| open_file.py | OpenFileTool - open allowlisted preview files with the host default application |
| vision.py | VisionTool - image analysis using multimodal LLM |
| subagent_task_tool.py | `task` tool - isolated subagent dispatch (`ChildSessionManager`) when `subagents_enabled`. Schema stays visible whenever subagents are on or the session said 用子代理; `agent_id=explore` is the Grok-style readonly codebase worker. |
| task_manage.py | `task_manage` tool - task-list management (legacy `task` when subagents disabled) |
| todo_write.py | Model-facing todo ledger writer over the shared `tasks.json` store; returns the authoritative `TodoSnapshot` projection |
| todo_events.py | `tasks.json` reader and deterministic TodoSnapshot/progress projection used by status-band and timeout evidence consumers |
| agent_invoke.py | `@agent` mention parsing + dispatch (`parse_mention` / `invoke_mention` / `list_mentionable_agents`) |
| memory_tool.py | MemoryTool - interact with the memory system |
| history_tool.py | HistoryTool - access memory/session history |
| datetime_tool.py | DateTimeTool - current date/time queries |
| final_answer.py | `final_answer` - ReAct finish action; calling it is an exit |
| diagnostics.py | DiagnosticsTool - system diagnostics and health checks |
| format_tool.py | FormatTool - code formatting |
| question_tool.py | QuestionTool - ask user for clarification |
| change_directory.py | ChangeDirectoryTool - change working directory |
| view.py | ViewTool - view file with syntax highlighting |
| ls.py | LsTool - list directory contents |
| patch.py | PatchTool - apply unified diff patches |
| skill_manager.py | `find_and_download_skill` / `install_skill_from_url` / `remove_skill` / `list_installed_skills` / `search_github_skills` (module-level functions) |
| skill_tool.py | SkillTool - execute installed skills |
| (Computer Use) | `core/cu/` — ocu OS-window MCP: `list_apps` `get_app_state` `click` `type_text` `press_key` `set_value` `scroll` `drag` `perform_secondary_action`. Bound only when `computer_use.enabled`. Not registered by `register_builtin_tools`. `cli_list`/`cli_run` remain a separate CLI-Anything pair. **Not** Playwright browser-use. |
| (Browser Use) | Playwright MCP via UPDATE-01 **U24** 三名 + **U46** 默认开（惰性进本轮 tools）：`browser_navigate` / `browser_snapshot` / `browser_click`. 用户 Chrome：**U46** `chrome_attach`（CDP 9222，默认开）. bundled MCP 或用户插件，同一能力键。Search/Fetch/Browse routing is U33–U36; escalate ladder is U46 (CU may operate a browser window only with a task signal). If `core/cu` currently also exposes `browser_open`/`browser_act` under `computer_use`, that is the CU channel (`cu:`), not this row. |
| mcp_manager.py | `add_mcp_server` / `remove_mcp_server` / `list_mcp_servers` / `install_mcp_from_npm` / `install_mcp_from_pip` (module-level functions) |
| workflow_tool.py | WorkflowTool - multi-step workflow execution |
| installer.py | ToolInstaller - install packages (npm, pip, etc.) |
| vision_capture.py | Screen/window capture for the vision tool |

Inline Python in `workflow_tool.py` is
submitted to `ShellExecutor.execute_argv_async`; it therefore uses the same
workspace/Docker boundary, memory and PID limits, timeout handling, and
process-tree cleanup as the bash tool. The production `StructuredTool`
coroutine never starts a raw subprocess. Workflow runs live on a dedicated
asyncio loop so synchronous and asynchronous status/wait/cancel calls share
one task, and cancel waits for `ShellExecutor` cancellation cleanup. Public
`run` calls are foreground operations: they return only after the script has
completed, failed, timed out, or been cancelled. While the script is running,
the tool emits a progress heartbeat every 10s so Desktop does not look frozen.
The returned text begins with
the real script outcome and includes a `run_id/status` trailer. This is an
intentional durability boundary: the side-effect journal cannot commit a
misleading `started` acknowledgement. If the process dies mid-run, the journal
entry remains pending and automatic replay fails closed. Workflow status
history itself is process-local and advisory; callers that need concurrent
status/cancel should supply a stable, unique `run_id` before starting the run.

`open_file.py` is a preview-only host boundary. Both its synchronous and
asynchronous entry points resolve the real target before invoking any OS
opener, require a regular file, and use the same explicit extension allowlist
on Windows, macOS, and Linux. Documents, structured/plain text, common images,
HTML, and PDF are supported. Executables, scripts, shortcuts, directories,
extensionless files, unknown extensions, ambiguous names, and double-extension
names containing an executable/script suffix fail closed. The tool remains a
`WRITE`-risk action, so the orchestrator's workspace write-path check and
approval policy still run before this per-tool validation. Tool aliases
`open` and `browser` canonicalize to `open_file` via
`core.safety.policy.canonical_tool_name` (same table as `shell` → `bash`);
do not look up risk or bind a second `open` tool. On Windows the opener is
``cmd /c start "RxyCode Open" <abs-path>`` as separate argv tokens (not one
quoted `/c` string). The dummy title contains a space so `start` cannot
treat `RxyCode` as `rxycode.exe` on PATH. Electron hosts therefore do not
need `AttachConsole` on this TTY, and `start \"\"` cannot collapse the path
into a file named `\\`. Success is the OS
accepting the launch, not the user closing the window. `bash` must not wait
for Word/Notepad/Typora: `tools/launch_intent.py` classifies `start` /
`xdg-open` / `open` / `Start-Process` / GUI bins. Previewable files opened
via a launcher go to `open_file`; `notepad` / `typora` / `winword` detach
without waiting. `start /wait` and `start /b` stay foreground. Spawn
failure returns an error so the model can retry, then stream the Final Answer.
When the current user turn names previewable files, `open_file` (and bash
`start`/`open` that rewrite into it) refuse a different basename: missing
named files stay `[error: file not found…]` instead of opening leftover
workspace files such as `notes.md`. The pin is basename-only and inactive
when the turn named no previewable file.

The current allowlist is intentionally reviewable in `PREVIEWABLE_EXTENSIONS`:
- text/data: `.txt`, `.log`, `.md`, `.markdown`, `.rst`, `.tex`, `.bib`,
  `.csv`, `.tsv`, `.json`, `.jsonl`, `.xml`, `.yaml`, `.yml`, `.toml`,
  `.cfg`, `.conf`
- browser/document: `.html`, `.htm`, `.css`, `.svg`, `.pdf`, `.rtf`,
  `.docx`, `.xlsx`, `.pptx`, `.odt`, `.ods`, `.odp`
- image: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.tif`,
  `.tiff`, `.ico`, `.avif`

Legacy executable document types and macro-enabled Office formats are not
included. New extensions must be added explicitly rather than inferred from a
MIME type or platform association.

The workflow-specific deadline defaults to 1200 seconds, below the default
global `execution.tool_timeout_seconds` budget of 1800 seconds. A positive
workflow deadline is clamped to the global tool budget. Explicit
`timeout_seconds=0` disables only the workflow-specific deadline and falls
back to the configured global tool deadline; if both are disabled, task
cancellation remains available. Foreground `bash` hard cap is **1800s**; runtime
probes CPU/IO at 180/300/600s and yields idle jobs to the model. Do not cite
the old 60s/120s schema defaults — those are deprecated as of 2026-09-20.
Git argv still uses an explicit 60s. Long scripted jobs may still use this
workflow tool or a per-call timeout. Contrast:
[`../plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md`](../plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md). In Docker mode, temporary scripts are created
beneath the configured mounted workspace and invoked with the container's
`python` command and a workdir-relative path. Docker/sandbox startup failures
are returned as workflow failures and are never retried on the host. Script
failure and timeout results retain their `[workflow error: ...]` or
`[workflow timeout: ...]` prefix, so evidence collection does not classify
them as successful mutations. Outer task cancellation propagates to the
controlled executor and waits for process-tree cleanup before unwinding.

Secret preview redaction (`tools/secret_text.py`) first lowercases the model-
visible text once and checks the unique `bearer`/assignment-key marker table.
Marker-free text is returned unchanged without entering either character
scanner. Text containing a marker still uses the existing bearer and assignment
parsers, including case-insensitive keys, quoted or escaped values, and values
whose key/value separator spans lines. This is only a model-visible preview
optimization; spilled files remain raw and are not rewritten by this helper.

`tools/todo_events.py::todo_progress_for_session` is the shared read-only
consumer for timeout evidence. It reopens the exact session's
`tasks.json` on every call, validates the snapshot identity and scope, and
projects items with `todo_progress_snapshot`. It has no write path, no
`latest` fallback, and no summary-model call; an absent or invalid ledger is
represented by empty progress.

## Tool Registration Flow
1. `core/builtin_tool_registration.register_builtin_tools(registry, orchestrator, ...)`
   creates and registers all built-in tools (called by AgentV2._register_tools())
2. Isolated subagents default on (`subagent_config_from_env()`; `RXYCODE_SUBAGENTS=0` disables). When `subagents_enabled` is on, the `task` name is the isolated subagent
   dispatch tool and the task-list tool registers as `task_manage`; exactly one
   tool owns the `task` name
3. Tools are bound to the LLM via bind_tools() for automatic tool calling
4. UsageTrackingLLM.re-wraps bind_tools() to maintain token tracking

## Safety (阶段二)
Every tool carries a static risk level in `core/safety/policy.py`
`TOOL_RISK_TABLE` (READ/WRITE/DANGER, default WRITE for unknown tools):
- READ: read, view, grep, glob, ls, webfetch, websearch, datetime, history,
  diagnostics, vision, question, skill, final_answer, and read-only composite operations
- WRITE: write, edit, patch, open_file, bash, format, change_directory,
  memory, task, file_download
- DANGER: installer, git, workflow `run`, **download_skill, download_mcp**
  (bash escalates to DANGER per-command via `classify_bash_command`)

All calls go through the safety gate in
`execution/tool_orchestrator.py::execute_tool` — see
[docs/modules/safety.md](safety.md). The question tool asks the user over a
dedicated channel (`core/question.py`), not the safety-approval protocol. In
stdio appserver mode the worker installs `PipeQuestionBroker` so OpenTUI and
Desktop receive `question/request` and can render a choice/text dialog. If no
broker is installed and stdin is not a TTY (worker pipes), the tool returns
`[no input: question channel unavailable]` instead of blocking on `input()`.

## Generated File Paths

`write` and `file_download` send every new file to `~/.RxyCode/output/YYYY-MM-DD/`, including requests that supplied an absolute path. Paths inside the active workspace preserve their relative subdirectory structure under that date directory. Existing files remain editable in place. Relative reads first check the active workspace and then today's output directory, allowing later tools to continue working with newly generated files.

## Core Tool Implementations

### BashTool (bash.py)
- Executes commands via subprocess with configurable timeout
- Captures stdout/stderr separately
- Handles Windows PowerShell vs cmd detection
- Supports working directory changes
- **Managed persistent shell (2026-10-23)**: agent `bash` calls default to
  `core/persistent_shell.py` instead of a fresh process per call, so
  environment variables, shell functions, venv activation and the current
  directory survive between tool rounds. The shell is created lazily on the
  first command, keyed by the trusted session identity, serializes commands on
  one shell while different identities run in parallel, and commits only the
  directory the shell itself confirms back to `session_runtime`. `workdir` is
  single-shot (cd in, run, cd back — never a subshell, so variables survive).
  Completion uses a random per-command sentinel, so output that merely looks
  like a marker cannot settle a command early, and a non-zero exit is always
  reported. Timeout/cancel/crash destroy the shell and say state was lost;
  nothing is replayed. Disabled for `sandbox_mode=docker` (a container per
  command is the isolation boundary) and by `RXYCODE_MANAGED_SHELL=0`. The
  one-shot path (`execute_async`/`execute_argv_async`) remains in use for GUI
  launches, docker, and all internal callers (git, formatter, workflow,
  diagnostics).
- **Process liveness (2026-10-24)**: managed, one-shot and Web/native bash
  share one async CPU/IO probe. The window is five seconds by production
  default, repeats after the 180/300/600 checkpoints, and is judged by the
  current AgentV2 session model rather than the optional P6 timeout engine.
  Low CPU/IO is never a kill decision. Probe results are request-local and
  keyed by `call_id+pid+generation+seq`; completion/cancel discards late
  verdicts. Direct callers without an owner LLM report “本次未判定”.
- Uses the bounded `ShellExecutor` previews and raw stdout/stderr artifacts;
  bash formats the previews without reading the complete artifact back into
  memory. Artifact paths retain the `Full output saved to:` prefix, duplicate
  large captures are still omitted, and model-visible previews pass through
  secret redaction. Combined preview text above 30000 chars is middle-truncated
  with a hint to read the artifact in segments. A failed spill reports
  `[spill write failed; output truncated]` and never claims the full output
  was saved. The shared `append_capture_hints()` presentation helper is also
  used by workflow, Git, formatter, installer/MCP, screenshot, and file-opener
  callers of `ShellExecutor`, so their bounded previews retain a path to the
  complete local artifact without loading it back into memory. If a truncated
  stream contains a secret-redaction marker, its raw tail is conservatively
  omitted before tool-orchestrator redaction; the exact bytes remain in the
  local artifact.
- Every call still goes through the unchanged gate: argument validation, risk
  classification, approval, journal, output limits and sandbox. The persistent
  shell reuses the *environment*, never a prior authorization.
- **Spawn lifecycle (2026-10-24)**: the persistent shell adopts the whole
  `ShellSandboxPlan` (Job + policy + backend temp files). The Windows Job is
  created before spawn and bound while the root is suspended; the handle is
  owned from the moment it exists, so a cancelled spawn closes it instead of
  leaking it. The sandbox's per-spawn temp files are deleted on close, on
  startup failure and on cancellation. Sub-agent shells are reclaimed on
  normal completion (`ChildRuntime.release()`), not only on shutdown.

### ReadTool (read.py)
- Reads file contents with optional line range (offset/limit)
- Default per-call page size is 800 lines; larger files are paged via `offset`
  (e.g. offset=801 for the next chunk). This is a default window, not a
  schema-enforced hard maximum: an explicit positive `limit` can request a
  different page size.
- Handles encoding detection (UTF-8, GBK, Latin-1)
- Returns structured output with line numbers

### WriteTool (write.py)
- Creates/overwrites files with auto-directory creation
- Validates file path and content
- Returns success/failure with file path
- **Not a model-facing tool since 2026-10-23**: the model calls
  `edit(operation="write")`; this module stays the implementation plus the
  `post_write_report()` entry point. Keeping one registered file-change tool
  is what removed the "three tools, three different diagnostic behaviours"
  class of bug.
- **Post-write diagnostics (2026-10-23)**: after a successful save it calls
  `post_write_report()` → `core/post_write_diagnostics.py`. The report keeps
  "the file was written" and "the check result" as separate facts, carries the
  content fingerprint that was actually checked, and only counts `pass` as a
  pass. Python uses real `compile()` (never executing the file) plus project
  Ruff; JS uses `node --check`; TS/TSX use project `tsc --noEmit` with the
  jsx mode matching the extension. Missing checkers report `unavailable`, and
  bracket counting is no longer used as a syntax signal.
- **Checker output is parsed from the complete artifact** (2026-10-24): the
  controlled execution entry returns a bounded preview plus an artifact path.
  Parsing the preview silently truncated machine output (a real Ruff run's
  180 findings exceeded the preview and parsed as "invalid JSON" → the whole
  check was reported `unavailable`). Only the model-facing summary is
  compressed now.
- **Executable project config needs explicit trust** (2026-10-24): an ESLint
  flat config is JavaScript and tsconfig compiler plugins load modules, so
  "check this file" would otherwise run arbitrary project code without
  approval. Without `diagnostics.run_project_config_checkers: true`, a
  full-auto permission mode, or `auto_approve: ["danger"]`, the
  config-executing checker is skipped **alone**: safe checks (`tsc` without
  plugins, `node --check`, Python `compile()`) still run, and only when no safe
  checker exists is the report `not_checked` with the trust reason. A tsconfig
  that declares compiler plugins has no safe substitute, so that file reports
  `not_checked`.
- **The trust gate uses the request's effective mode** (round-5 audit): the
  permission mode comes from
  `execution.tool_orchestrator.current_permission_mode()` — the request-level
  override wins over global config, so a prompt narrowed to `auto_edit` cannot
  inherit a global `full_auto` trust.
- **ESLint config is resolved upward** (round-5 audit):
  `find_executable_eslint_config()` walks parent directories because ESLint
  does; a nested package without its own config would otherwise execute the
  parent's `eslint.config.js` unnoticed.
- **Data configs are checked for local code-loading entries** (2026-10-24):
  legacy `.eslintrc.json` is not assumed safe from its extension. A local
  top-level `parser`, or a local `parser`/`extends` inside `overrides`, can load
  project JavaScript before ESLint reports a parse error. These entries are
  resolved and inspected recursively; when the target is missing or cannot be
  proven data-only, ESLint alone is skipped without explicit trust.
- **tsconfig is read as JSONC with `extends`** (round-5 audit): comments and
  trailing commas no longer break parsing, and `composite`/`plugins` come from
  the merged effective config (`--incremental false` is omitted for composite
  projects — TS6379).

### EditTool (edit.py)
- **The single model-facing file-change tool** (2026-10-23): one schema with
  `operation=replace|write|patch`, `replaceAll` for replace. The sync
  `edit_file()` is a pure writer; the async path attaches diagnostics.
- Reports similar lines when `oldString` is not found
- **Post-write diagnostics (2026-10-23/24)**: every committed operation reports
  through the same `post_write_report()` entry point the write tool uses, and
  the report names the operation (`edit`/`write`/`patch`). Earlier the success
  check matched only the `[edited` prefix, so `operation=write` and
  `operation=patch` were committed but never diagnosed.

### PatchTool (patch.py)
- Applies a unified diff to one file, then reports through the same
  `post_write_report()` diagnostics entry point as write/edit.
- Not registered as a separate model tool; reached through
  `edit(operation="patch")`.

### FileDownloadTool (file_download.py)
- Downloads files from public HTTP/HTTPS URLs
- Default save location: ~/.RxyCode/output/ (configurable)
- A relative `save_path` is resolved against the persisted working directory
  of the current session, without changing process-global cwd
- Successful `Saved to:` output is converted at the orchestrator boundary into
  artifact evidence containing the resolved path, size, and SHA-256; a missing
  artifact changes the evidence status to failed
- Size limit: 100MB
- Auto-deduplication: appends _1, _2, etc. if file exists

### HistoryTool (history_tool.py)
- Searches global memory under `memory/user` and `memory/projects/global`
- Searches only `memory/sessions/<current_session_id>` for session memory;
  another concurrent session's files are not enumerated
