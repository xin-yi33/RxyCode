# Changelog

All notable changes to RxyCode are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- **Provider connection presets** — `GET /models/presets` returns ten mainstream
  LLM providers as `{id, name, base_url, category}`. Presets are deliberately
  provider-level only: no preset pins a model id, so the table cannot go stale
  when a vendor renames or retires a model (closes #5)
- **Model discovery** — `POST /models/discover` calls the provider's
  OpenAI-compatible `GET {base_url}/models` with the supplied key and returns the
  real catalogue. Read-only: nothing is persisted until `/models/onboard`.
  Credentials are redacted from every error path and HTTPS is enforced before any
  request leaves the process
- **Real recent-model history** — `set_active_model` records switches in
  `config.recent_models` (capped, pruned when a model is removed) and
  `GET /models` returns it as `recent`, so `/model` can show a 最近常用 group
  backed by actual history

### Changed

- **`/addmodel` follows the OpenCode "connect a provider" flow** — the wizard is
  now built from the shared `DialogSelect` / `DialogPrompt` components
  (searchable list, ↑↓ / Enter / Esc, mouse hover row highlight, wheel scrolling,
  block cursor, category headers) instead of a hand-drawn numbered menu. Flow:
  pick provider → enter key → discover models → pick model → optional nickname.
  Providers without a `/models` catalogue fall back to manual model-id entry
- **`DialogPrompt`** — matches the shared dialog chrome (`borderDim` border,
  `text` title, `DialogSelect`-style block cursor) and can mask credential input

## [1.2.2] - 2026-07-30

### Added

- **Auto-install Bun** — one-command `install.ps1` / `install.sh` install Bun
  when missing (official bun.sh installer), then run `bun install` for the
  packaged OpenTUI app so the default UI can start without a manual Bun setup
- **Runtime Bun bootstrap** — if Bun is still missing at launch, RxyCode tries
  the official installer once (disable with `RXYCODE_SKIP_BUN_INSTALL=1`); also
  discovers `~/.bun/bin` even when PATH is stale, and runs `bun install` on
  first OpenTUI start when `node_modules` is absent
- **No-model onboarding** — when the local model list is empty, the TUI shows a
  welcome hint and auto-opens the `/addmodel` wizard (OpenTUI and Ink)

### Notes

- Prefer installing `@v1.2.2` (this is the current downloadable 1.2.x patch).
  Bun remains required for OpenTUI; if install fails, the CLI still falls back
  to Ink.

---

## [1.2.1] - 2026-07-29

### Fixed

- **Packaging ships OpenTUI** — `pyproject.toml` / `MANIFEST.in` previously only
  bundled Ink `frontend/dist/*.js`. Installed / one-command installs therefore
  failed `_opentui_ready()` and silently fell back to Ink, so end users saw a
  completely different UI than a source checkout. OpenTUI
  (`frontend/opentui-app/package.json`, `src/**`, lockfile) is now included in
  the wheel.

### Notes

- Prefer installing `@v1.2.1` or newer. Tag `v1.2.0` remains for history but its
  published install path did not bundle OpenTUI sources.

---

## [1.2.0] - 2026-07-29

### Highlights

**Frontend rewrite: default TUI moves from Ink to OpenTUI.** The interactive
terminal UI was rebuilt on Bun + React 19 + `@opentui/react` (`frontend/opentui-app/`),
with OpenCode-aligned command palette / nested settings, ScrollBox-based
flicker-resistant chat, native textarea input, safer Ctrl+C, clearer Plan→Build
handoff, and working `autoCompact`. Ink remains as an optional fallback via
`RXYCODE_TUI=ink`. v1.1.0 remains available via the `v1.1.0` git tag.

### Added

- **OpenTUI frontend (`frontend/opentui-app/`)** — full chat shell on
  `@opentui/core` / `@opentui/react`: alternate screen, mouse selection,
  ScrollBox message list, native textarea, markdown rendering, sticky scroll,
  streaming reducer, approval dialog, brand/wordmark chrome
- **Default launch path** — when Bun is available, `main.py` starts OpenTUI
  instead of Ink (`RXYCODE_TUI=opentui|ink|auto`)
- **OpenCode-style Ctrl+P command palette** — stacked dialogs for Session /
  Model / AddModel / Settings / Permission / Language / MCP / Skills / Memory /
  Queue / Schedule / Help / Status
- **Dialog host stack** — `replace` / `push` / `pop` / `clear` with single
  top-of-stack keyboard ownership
- **Plan next-step hint** — after Plan mode finishes, always append how to
  continue: Tab → Build, then type「开始」/ `start`
- **Safer Ctrl+C** — copy selection → cancel stream → clear input → require a
  second Ctrl+C within 2s to quit
- **`autoCompact` wiring** — config flag now gates short-term overflow
  compression, tool-loop compaction, and LangGraph `compressor` node
- **OpenTUI e2e helpers** — nested dialog / palette verification scripts
- **Shell translation hardening** — PowerShell-safe rewriting for `&&`,
  `cd /d`, and `start cmd /k` style commands
- **Permission / evidence / short-term memory tests** — additional contract
  coverage for write paths and routing

### Changed

- **Primary TUI** — OpenTUI is the default interactive UI; Ink is retained as
  rollback (`RXYCODE_TUI=ink`) rather than the sole frontend
- **Status / approval UX** — OpenTUI-native approval and status surfaces
- **User message framing** — historical user frames keep the mode color from
  send time

### Fixed

- Chat flicker / ScrollBox stability vs Ink Static limitations
- Nested dialog input under Windows ConPTY (multi-char paste / filter)
- Accidental process exit on single Ctrl+C when no selection was registered
- Context compression config that existed but was never read (`autoCompact`)
- Assorted PowerShell shell and write-path nesting edge cases

---

## [1.1.0] - 2026-07-27

### Highlights

Complete frontend overhaul with Ink/React/TypeScript TUI, SSE streaming
pipeline, Docker support, CI/CD, and one-command installers. The old
Python/Textual UI has been fully removed; the Ink frontend is now the sole
interactive interface.

### Added

- **Ink/React/TypeScript terminal UI** — 34 components, 26 hooks/utils,
  158 tests; replaces the legacy Python/Textual TUI entirely
- **SSE streaming pipeline** — 50 ms token batching, live assistant message
  updates, correlated tool messages, approval/question dialogs
- **Output ordering fix** — `final-answer` now stays dynamic until the SSE
  `done` event, preventing it from being committed to Ink's `Static` region
  before late-arriving process/tool events
- **One-command installers** — `install.ps1` (Windows) and `install.sh`
  (macOS/Linux) bootstrap `uv` and install the pinned release without cloning
- **Docker multi-stage build** — Node.js frontend build stage + Python runtime
  stage; `docker compose up` for API, `docker compose run --rm tui` for TUI
- **CI/CD with GitHub Actions** — Linux backend tests, Windows contract/system
  tests, frontend tests, ConPTY integration, opt-in live provider tests
- **Three-level cache** — PreciseCache (exact hash) + SemanticCache (0.95
  threshold + entity overlap) + Provider KV Cache (`cache_control` injection)
- **RAG integration** — Codebase vector search with chunking, embedding, and
  cosine similarity search
- **Scheduler** — Cron-like prompt scheduling for recurring tasks
- **LSP integration** (experimental) — Code intelligence via Language Server
  Protocol
- **History tracking** — Command and conversation logging
- **Error recovery** — Retry logic with exponential backoff and error tracking
- **Evaluation harness** — Task success rate, LLM-as-judge, baseline comparisons
- **Safety gate** — Risk levels, TUI/SSE approval workflow, write whitelist,
  audit trail
- **AddModel wizard** — 4-step visual dialog (`/addmodel`) with masked
  credential input
- **Memory system** — Short-term window, long-term compressed storage, user
  memory, semantic search
- **Watchdog timeout** — Monitors execution and cancels on inactivity
- **PromptSpec versioning** — Versioned prompt templates for cache-key stability

### Changed

- **Architecture** — Upgraded from ReAct loop to LangGraph pipeline:
  `goal_planner → decomposer → executor → validator → synthesizer`
- **Python requirement** — Lowered from 3.13+ to 3.10+
- **CLI** — Removed `--python` flag and legacy TUI fallback; Node.js 20+ is
  required for the Ink frontend
- **Packaging** — `pyproject.toml` with wheel/sdist support; `frontend/dist/`
  bundled as a self-contained esbuild ESM bundle in the wheel
- **Dependencies** — Removed `textual` and `prompt_toolkit`; added LangGraph,
  LangChain, FastAPI, pydantic, numpy, pybreaker

### Removed

- Legacy Python/Textual TUI (`utils/tui.py` Textual classes, `utils/input_box.py`,
  `utils/command_completer.py`)
- `--python` CLI flag and all fallback logic
- `textual` and `prompt_toolkit` dependencies

### Fixed

- **Output ordering** — `final-answer` no longer appears above process content;
  the answer stays in the dynamic region until `done` arrives, then is committed
  to `Static` in correct order: process → tool → final-answer
- **Node.js exit code propagation** — Non-zero exit codes from the Ink frontend
  are no longer silently swallowed
- **ESM/CJS compatibility** — `createRequire(import.meta.url)` banner injected
  for dynamic `require` in the esbuild ESM bundle
- **Non-TTY behavior** — Starting without a TTY now exits with code 1 and a
  clear message instead of silently succeeding
- **Docker Node.js** — Runtime image includes the Node.js binary from the
  build stage

---

## [1.0.0] - 2026-06-15

### Highlights

Major architecture rewrite from the ReAct loop to a LangGraph-based
plan-and-execute pipeline with hierarchical task decomposition, verification,
and result synthesis.

### Added

- **LangGraph pipeline** — `goal_planner → decomposer → executor → validator
  → synthesizer` replacing the linear ReAct loop
- **Hierarchical task planning** — Goal refinement, task decomposition with
  dependency analysis, parallel execution via `asyncio.gather + Semaphore`
- **UsageTrackingLLM** — Wraps all LLM calls to auto-record token usage
- **Two-level cache** — PreciseCache (exact hash match) + SemanticCache
  (semantic similarity with 0.95 threshold)
- **Tiered memory** — Short-term window + long-term compressed storage + user
  memory with semantic search
- **Tool orchestrator** — 24+ built-in tools: read, write, edit, bash, grep,
  glob, ls, view, webfetch, websearch, git, and more
- **Safety gate** — Risk level classification, approval workflow, write
  whitelist, audit trail
- **Sub-agent delegation** — Multi-task routing with parallel sub-agents
- **Fast reply path** — Simple queries bypass the full pipeline via 2-level
  cache check
- **Composable modes** — `build` (full pipeline), `plan` (read-only), `compose`
  (plan + build)
- **API server** — FastAPI with SSE streaming, `/chat/stream` endpoint
- **Python 3.10+ support** — Broadened from the previous 3.13+ requirement

### Changed

- **Core engine** — Migrated from `rxycode_backend/` ReAct loop to `core/`
  LangGraph architecture
- **Tool system** — Expanded from 5 basic tools to 24+ tools with timeout,
  retry, and degradation
- **Configuration** — Moved from inline config to `~/.rxycode/config.yaml`
- **Testing** — Introduced comprehensive test suite with pytest markers
  (live, pty, serial)

### Removed

- `rxycode-mcp/` directory (MCP servers restructured into `mcp/` module)
- `test_parse_tool_call.py` and `test_rxycode.py` (replaced by structured
  test suite in `tests/`)

---

## [0.3.3] - 2025-12-01

### Highlights

Initial public release. ReAct-based AI agent with anti-hallucination
verification layer and MCP integration.

### Added

- **ReAct architecture** — Reasoning → Action → Observation → Verification →
  Response loop
- **Anti-hallucination verification** — `ClaimExtractor → Verifier →
  ReportCorrector` pipeline to prevent false success reports
- **Tool system** — 5 core tools: bash (60s timeout), read (5s), write (15s),
  with timeout/retry/degradation
- **Environment awareness** — Auto-detects OS, shell, and path conventions
- **Context isolation** — Per-task context to prevent information leakage
- **History compression** — Compresses conversation history to manage context
  window
- **MCP integration** — 4 MCP servers: codebase_explorer, shell, verify,
  task_progress
- **API server** — Basic FastAPI with `/chat`, `/command`, `/status` endpoints
- **Tests** — Anti-hallucination, timeout, shell syntax, path error, and
  context leakage tests

---

[1.2.2]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2
[1.2.1]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.1
[1.2.0]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.0
[1.1.0]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.1.0
[1.0.0]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0
[0.3.3]: https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3
