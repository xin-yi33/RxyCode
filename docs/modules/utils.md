# utils/ - Utilities

## What Is This Module?
Shared utilities used across the codebase: backend event output, streaming state, internationalization, shell helpers, queues, and terminal support helpers.

## Key Files
| File | Purpose |
|------|---------|
| streaming.py | TokenStats singleton, terminal output helpers, status bar formatting |
| tui.py | Non-interactive backend output adapter and `get_tui()` / `set_tui()` event sink access |
| i18n.py | Internationalization: zh/en language support |
| shell.py | Shell detection and desktop path resolution |
| queue.py | QueueManager: persistent task queue |

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
