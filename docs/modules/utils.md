# utils/ - Utilities

## What Is This Module?
Shared utilities used across the codebase: backend event output, streaming state, internationalization, shell helpers, queues, and terminal support helpers.

## Key Files
| File | Purpose |
|------|---------|
| streaming.py | TokenStats singleton, terminal output helpers, status bar formatting |
| tui.py | Non-interactive backend output adapter and `get_tui()` / `set_tui()` event sink access |
| i18n.py | Internationalization: zh/en language support |
| slash_help.py | Canonical `/help` body (`build_help_text`) for HTTP `/command` |
| shell.py | `ShellExecutor` - cross-platform command execution with enforceable sandbox policies (workspace/docker/host modes, process-tree cleanup, timeout/cancellation). On Windows PowerShell, an actual `mysql.exe` / `mysql -u` invocation is wrapped in `cmd.exe` so password-on-CLI stderr warnings and `-e` SQL semicolons do not fail the tool. Env probes such as `MYSQL_*` and `Get-Command mysql` stay in PowerShell. |
| queue.py | QueueManager: persistent task queue |
| safe_http.py | Pinned public HTTP client: `validate_public_url` / `is_public_address` / `fetch_public_response` / `safe_url_label`, `UnsafeUrlError`, `ResponseTooLargeError` (used by webfetch/file_download) |
| atomic_file.py | `atomic_write_text` - atomic same-directory temp write + fsync + rename (used by write/edit/memory/task/queue) |
| user_facing_errors.py | `to_user_facing_error` + `MSG_*` zh/error mapping for terminal messages |

## Core Code: streaming.py

`TokenStats` tracks input/output tokens, provider cache usage, answer-cache hits, billing estimates, and context-window utilization. The module also provides terminal-oriented formatting helpers used by backend and diagnostic paths.

## Core Code: tui.py

`tui.py` is not a user interface. The interactive UI lives exclusively in `frontend/` and uses Ink.

The module exposes:
- `BackendOutputAdapter`: Minimal non-interactive event sink for backend code running without an API stream.
- `get_tui()`: Return the process-wide output sink.
- `set_tui(tui)`: Install an API/SSE-aware sink for the current process.

The adapter preserves the output methods expected by agents and tools, including `write_tool_call`, `write_tool_result`, `write_error`, `write_warning`, `write_thinking`, and `stream_token`.

## Core Code: i18n.py
- Supports Chinese and English text resources.
- `i18n.set_lang(lang)`: Switch language.
- `i18n.t(key)`: Resolve translated text with key fallback.
