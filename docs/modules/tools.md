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
| registry.py | ToolRegistry - central registration and lookup of all tools |
| bash.py | BashTool - execute shell commands with timeout and output capture |
| read.py | ReadTool - read file contents with line range support |
| write.py | WriteTool - write/create files with directory auto-creation |
| edit.py | EditTool - surgical text replacements in files |
| grep_tool.py | GrepTool - search files by regex pattern |
| glob_tool.py | GlobTool - find files by glob pattern |
| git_tool.py | GitTool - git operations (status, diff, commit, etc.) |
| webfetch.py | WebFetchTool - fetch URL content with size limits |
| websearch.py | WebSearchTool - web search (requires API key) |
| file_download.py | FileDownloadTool - download files from URLs to ~/.rxycode/output/ |
| download_tool.py | DownloadTool - download skills/MCP servers from GitHub |
| open_file.py | OpenFileTool - open allowlisted preview files with the host default application |
| vision.py | VisionTool - image analysis using multimodal LLM |
| agent_tool.py | AgentTool - delegate tasks to sub-agents |
| task_tool.py | TaskTool - task queue management |
| memory_tool.py | MemoryTool - interact with the memory system |
| history_tool.py | HistoryTool - access command/chat history |
| datetime_tool.py | DateTimeTool - current date/time queries |
| diagnostics.py | DiagnosticsTool - system diagnostics and health checks |
| format_tool.py | FormatTool - code formatting |
| question_tool.py | QuestionTool - ask user for clarification |
| change_directory.py | ChangeDirectoryTool - change working directory |
| view.py | ViewTool - view file with syntax highlighting |
| ls.py | LsTool - list directory contents |
| patch.py | PatchTool - apply unified diff patches |
| skill_manager.py | SkillManager - install/list/remove skills from GitHub |
| skill_tool.py | SkillTool - execute installed skills |
| mcp_manager.py | MCPManager - manage MCP server connections |
| workflow_tool.py | WorkflowTool - multi-step workflow execution |
| installer.py | InstallerTool - install packages (npm, pip, etc.) |

`agent_tool.py` exposes a native async coroutine so cancellation reaches its
child Agent without a worker thread. Inline Python in `workflow_tool.py` is
submitted to `ShellExecutor.execute_argv_async`; it therefore uses the same
workspace/Docker boundary, memory and PID limits, timeout handling, and
process-tree cleanup as the bash tool. The production `StructuredTool`
coroutine never starts a raw subprocess. Workflow runs live on a dedicated
asyncio loop so synchronous and asynchronous status/wait/cancel calls share
one task, and cancel waits for `ShellExecutor` cancellation cleanup. Public
`run` calls are foreground operations: they return only after the script has
completed, failed, timed out, or been cancelled. The returned text begins with
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
approval policy still run before this per-tool validation.

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
cancellation remains available. In Docker mode, temporary scripts are created
beneath the configured mounted workspace and invoked with the container's
`python` command and a workdir-relative path. Docker/sandbox startup failures
are returned as workflow failures and are never retried on the host. Script
failure and timeout results retain their `[workflow error: ...]` or
`[workflow timeout: ...]` prefix, so evidence collection does not classify
them as successful mutations. Outer task cancellation propagates to the
controlled executor and waits for process-tree cleanup before unwinding.

## Tool Registration Flow
1. AgentV2._register_tools() creates all tool instances
2. Each tool is registered with ToolOrchestrator
3. Tools are bound to the LLM via bind_tools() for automatic tool calling
4. UsageTrackingLLM.re-wraps bind_tools() to maintain token tracking

## Safety (阶段二)
Every tool carries a static risk level in `core/safety/policy.py`
`TOOL_RISK_TABLE` (READ/WRITE/DANGER, default WRITE for unknown tools):
- READ: read, view, grep, glob, ls, webfetch, websearch, datetime, history,
  diagnostics, vision, question, and read-only composite operations
- WRITE: write, edit, patch, open_file, bash, format, change_directory, download_*,
  file_download
- DANGER: installer, git, and workflow `run` (bash escalates to DANGER
  per-command via `classify_bash_command`)

All calls go through the safety gate in
`execution/tool_orchestrator.py::execute_tool` — see
[docs/modules/safety.md](safety.md). The question tool no longer blocks the
API event loop: when an approval broker is active it delegates the prompt
through the broker (SSE approval_request in API mode) instead of raw
`input()`.

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
- Default save location: ~/.rxycode/output/ (configurable)
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
