# tools/ - Tool System

## What Is This Module?
Provides all tools the agent can use to interact with the environment: file operations, shell commands, web access, git, and more. Tools are registered via a central registry and orchestrated by the execution layer.

## Architecture
Tools follow the LangChain StructuredTool pattern. Each tool has:
- A name and description (for LLM tool selection)
- An args_schema (Pydantic model for structured input)
- A func (the actual implementation)

## Key Files
| File | Purpose |
|------|---------|
| registry.py | ToolRegistry - per-agent injectable catalog (F2). `default_registry` is the process default; a Coordinator member gets a scoped copy, not the process table. `registry` is a compat alias |
| bash.py | BashTool - execute shell commands with timeout and output capture. Default **hard cap 1800s**. Runtime probes CPU/IO at **180/300/600s** and reports to the user and the model; busy search/traversal is not killed; idle-CPU/IO jobs yield at that checkpoint so the model decides. Git argv still uses 60s. |
| read.py | ReadTool - read file contents with line range support |
| write.py | WriteTool - write/create files with directory auto-creation |
| edit.py | EditTool - surgical text replacements in files |
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
- Combined output longer than 30000 chars is middle-truncated (head + tail
  kept, ~15000 chars each) with a "[输出已截断...]" hint telling the agent to
  use grep / redirect-to-file for the rest (Tier1 style, adapted from
  memory/compressor.py:170-194)

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

### EditTool (edit.py)
- Surgical text replacement using old_text/new_text pattern
- Validates that old_text exists in file before replacing
- Supports multiple replacements in one call

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
