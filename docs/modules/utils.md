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
| output_capture.py | `BoundedOutputCapture` - drains stdout/stderr in fixed-size chunks, retains bounded per-stream previews, and synchronously spills overflow to `get_data_dir()/spill/<session>/` with byte counts, SHA-256, truncation, artifact, and capture-error metadata. |
| queue.py | QueueManager: persistent task queue |
| safe_http.py | Pinned public HTTP client: `validate_public_url` / `is_public_address` / `fetch_public_response` / `safe_url_label`, `UnsafeUrlError`, `ResponseTooLargeError` (used by webfetch/file_download) |
| atomic_file.py | `atomic_write_text` - atomic same-directory temp write + fsync + rename (used by write/edit/memory/task/queue) |
| user_facing_errors.py | `to_user_facing_error` + `MSG_*` zh/error mapping for terminal messages |
| clipboard_capture.py | Standalone one-shot OS clipboard helper; no project imports, one JSON result, bounded command/text/image reads |

## Clipboard capture helper

Run `python -I -X utf8 <project-root>/utils/clipboard_capture.py --output-dir
<client-data>/clipboard`. Isolated mode prevents the script's `utils/` directory
or `PYTHONPATH` from shadowing standard-library modules while preserving
standard-library and installed-package access. The non-isolated command
`python <script>` is deprecated (2026-10-11): the repository's `utils/queue.py`
can shadow stdlib `queue` and fail during import before clipboard access. The
helper emits exactly one JSON object with `kind` (`text`,
`attachments`, `empty`, or `error`), `text`, and `attachments`; failures may
also include `error`. Windows reads copied file paths through native CF_HDROP,
then bitmap through Pillow, then bounded Unicode text; CF_HDROP and text still
work if Pillow is unavailable, while image paste reports explicit install
guidance. Linux supports graphical Wayland (`wl-paste`) or X11
(`xclip`) when installed. macOS supports clipboard PNG and text; Finder file
objects are explicitly unsupported. Headless/missing-command cases report an
error rather than a successful empty paste.

Clipboard text is capped at 64 KiB and marked when truncated. A copied image is
normalized to a unique PNG under the supplied output directory, capped at 20
MP, 2048 px per edge, and 5 MiB encoded; its human label is
`剪贴板图片.png`. The default is `~/.RxyCode/temp/clipboard`, matching
`config.settings.DEFAULT_CONFIG_DIR`; `RXYCODE_DATA_DIR` overrides the data
root without importing the full settings package. POSIX command reads have a
deadline, and the helper starts its own process group so the caller can cancel
the helper and its clipboard-command descendants together.

Generated PNGs remain in the persistent clipboard temp directory so queued
turns and history can continue referring to them; they are not deleted at the
end of the current turn. There is currently no automatic, reference-safe
cleanup or garbage collection. A future cleanup policy must account for
queued/history references before removing generated files; that policy is not
implemented yet.

## Core Code: streaming.py

`TokenStats` tracks input/output tokens, provider cache usage, answer-cache hits, billing estimates, and context-window utilization. The module also provides terminal-oriented formatting helpers used by backend and diagnostic paths.

## Core Code: tui.py

`tui.py` is not a user interface. The default interactive TUI is OpenTUI in
`frontend/opentui-app/`; Ink in `frontend/` remains the optional
`RXYCODE_TUI=ink` fallback.

Retired documentation wording (2026-10-11): the former “frontend exclusively
uses Ink” description was stale because OpenTUI is now the default TUI. This
corrects the module documentation only; it does not change code or runtime
routing.

The module exposes:
- `BackendOutputAdapter`: Minimal non-interactive event sink for backend code running without an API stream.
- `get_tui()`: Return the process-wide output sink.
- `set_tui(tui)`: Install an API/SSE-aware sink for the current process.

The adapter preserves the output methods expected by agents and tools, including `write_tool_call`, `write_tool_result`, `write_error`, `write_warning`, `write_thinking`, and `stream_token`.

## Core Code: i18n.py
- Supports Chinese and English text resources.
- `i18n.set_lang(lang)`: Switch language.
- `i18n.t(key)`: Resolve translated text with key fallback.

## Shell output capture

`ShellExecutor` reads stdout and stderr independently in 64 KiB chunks. Each
stream keeps at most a 48 KiB preview; once their combined raw output exceeds
30000 bytes, complete streams are written to local artifacts under
`get_data_dir()/spill/<session>/`. Artifact writes run synchronously inside the
pipe readers, so slow storage applies backpressure instead of accumulating
queued chunks. Results retain `stdout`, `stderr`, `exit_code`, and `success`,
and may additionally include per-stream byte counts, SHA-256 values, artifact
paths and truncation flags, plus `capture_error`. A failed spill keeps only the
bounded preview and explicitly reports the capture failure; it does not change
or retry the already-executed command. For truncated streams, a small
cross-chunk scan detects the same sensitivity markers used by secret preview
redaction; if any appear, the raw tail is omitted with an explicit safety note
so a byte-window cannot retain a secret value after clipping away its key.
Non-sensitive output keeps the usual head-and-tail preview. Timeout/cancellation
continues through the existing process-tree cleanup path and removes incomplete
artifacts. `append_capture_hints()` lets existing ShellExecutor consumers expose
generated local artifact path lines (or a capture-failure notice) without
reopening complete files.
