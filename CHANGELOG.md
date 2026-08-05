# Changelog

All notable changes to RxyCode are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.2.6] - 2026-08-06

### Highlights

Reliability-fix release. Webfetch no longer double-decodes brotli/gzip pages
(`brotli: decoder failed`), the router only treats explicit
"install/add an MCP server" phrases as MCP-install intent (so explaining the MCP
protocol no longer silently adds an npx server to your config), and shell output
on zh-CN Windows decodes as UTF-8 first, fixing Chinese mojibake. Agent-written
POSIX habits (`ls -la`, heredocs, bare `&` separators) are translated to
PowerShell on Windows.

### Fixed

- **webfetch** — drop `Content-Encoding` / `Content-Length` when re-constructing
  the `httpx.Response`, so brotli/gzip pages no longer fail to decode.
- **MCP mis-routing** — `detect_download_intent` now requires an explicit install
  verb before routing to `download_mcp`; bare "MCP" mentions (explain/questions)
  no longer trigger an MCP server install.
- **Shell encoding** — subprocess output is decoded as UTF-8 first, falling back
  to the system preferred encoding only when needed.
- **Shell translation (Windows)** — `ls -la` → `Get-ChildItem -Force`, POSIX
  heredoc → PowerShell here-strings, bare `&` separators → `;`.

---

## [1.2.5] - 2026-08-06

### Highlights

Phase 2 completion: OpenTUI moves to the stdio JSON-RPC transport, keyword-based
request routing is replaced by an explicit routing module, lazy imports are
consolidated under budget, and `api_server.py` is thinned into an HTTP/SSE
adapter over the headless `Session` facade. Phase A lands the model adaptation
layer with a provider-driven LLM construction, tokenizer spec parsing, and
prompt variant lookup.

### Added

- **Phase A model adaptation layer** — LLM construction routed through the
  provider layer: `DeepSeekProvider` (reasoner-aware), `AnthropicProvider` /
  `QwenProvider` skeletons, tokenizer spec parser with fail-safe
  `count_tokens`, usage/reasoning extraction delegated to providers,
  capabilities-driven prompt `(stage, locale, variant)` lookup with default
  fallback
- **Phase 2 completion** — `protocol/` + `appserver` stdio JSON-RPC end to end;
  OpenTUI defaults to the stdio transport (`RXYCODE_TRANSPORT=stdio`)
- **Request routing module** — `core/request_routing.py` with explicit routing
  directives replacing hardcoded keyword lists; file+modify intent routes
  through the full pipeline
- **Parallel gate orchestration** — `evals` parallel gate runner with per-task
  timeouts and gate-based exit codes
- **OpenTUI migration hardening** — approval lifecycle fixes, transport CI
  coverage, appserver stderr kept off the TUI screen

### Changed

- **`api_server.py` thinned** — SSE transport classes and model-onboarding
  endpoints extracted to dedicated modules; core entry flows through `Session`
- **Lazy import consolidation** — function-scoped imports under budget
  (`test_lazy_import_budget` guard passes), `core/` internal cycles resolved
- **Install pins** — one-command installers default to **`v1.2.5`**
- **Release downloads** — only the latest release (v1.2.5) publishes
  wheel/sdist assets; v1.2.4 and earlier keep notes but no installable
  downloads

### Fixed

- Eval session cwd / sandbox root pinned to task workdir (readcode, workdir
  tasks)
- Config fallback to `api_key_secret` when `api_key_env` is empty
- Appserver thinking toggle persists between prompts
- Packaging / installer contract tests aligned to 1.2.5

### Install notes

- **Default one-command install** pins **`v1.2.5`**.
- v1.2.4 release page keeps notes; **downloadable assets are removed** from
  v1.2.4 (and older releases remain without assets).

---

## [1.2.4] - 2026-08-02

### Highlights

Add-model UX polish (provider grouping, OpenCode Go preset, Enter-to-run slash
suggestions), Phase 1 evaluation harness closure, and the Phase 2 typed
agent↔frontend protocol with a TypeScript JSON-RPC client.

### Added

- **Slash Enter expansion** — typing a prefix like `/addm` and pressing Enter
  runs the highlighted suggestion (↑↓ to choose; Tab still completes)
- **URL-based provider grouping** — custom endpoints infer provider group;
  `/model` lists by preset name / inferred URL group / 其他
- **OpenCode Go preset** — provider preset for `https://opencode.ai/zen/go/v1`
- **Phase 1 eval harness** — real AgentV2 pipeline tasks, tool_used checks,
  baselines, nightly eval vs baseline CI, headless approval path
- **Phase 2 protocol** — frozen JSON schema + TypeScript JSON-RPC client and CI
  gate (`protocol/`, frontend client)

### Changed

- **Custom Other add-model** — clears stale API key; custom path uses multi
  batch onboard like presets; default nickname = model id
- **Batch activate** — confirming add-model activates the highlighted selection
- **Install pins** — one-command installers default to **`v1.2.4`**
- **Release downloads** — only the latest release publishes wheel/sdist assets;
  older releases keep notes but no installable downloads

### Fixed

- Dialog prompt plaintext cursor for API key entry
- CI secret/env handling for nightly eval and live lanes
- Packaging / installer contract tests aligned to 1.2.4

### Install notes

- **Default one-command install** pins **`v1.2.4`**.
- Older release pages remain for history; **downloadable assets are removed**
  from prior releases (including v1.2.3 / v1.2.2).

---

## [1.2.3] - 2026-07-31

### Highlights

**OpenCode-style model onboarding, upgraded.** Ten mainstream provider presets,
read-only model discovery, preset **multi-select batch onboard** (no per-model
chat probe), `/model` grouped by provider, and hardened discover failure routing.

### Added

- **Preset batch model onboarding** — after discover on a preset provider, the
  add-model wizard shows a multi-select list (default all checked) and saves via
  `POST /models/onboard/batch` with `skip_probe=true` (no per-model chat probe)
- **`POST /models/onboard/batch`** — add multiple discovered models in one
  request; returns `{added, skipped, active, message}`
- **`GET /models` category field** — each model includes `category` from
  `provider_name` for grouped `/model` display
- **Provider connection presets** — `GET /models/presets` returns ten mainstream
  LLM providers as `{id, name, base_url, category}`. Presets are deliberately
  provider-level only: no preset pins a model id
- **Model discovery** — `POST /models/discover` calls the provider's
  OpenAI-compatible `GET {base_url}/models` with the supplied key and returns the
  real catalogue. Read-only until onboard. Credentials redacted; HTTPS enforced
- **Real recent-model history** — `set_active_model` records switches in
  `config.recent_models`; `GET /models` returns `recent` for a 最近常用 group
- **`DialogSelect` multi mode** — space toggles selection; Enter confirms batch
- **`onboard_models_batch`** — backend helper with `skip_probe=True` for presets
- **`provider_id` / `provider_name` metadata** on saved models for UI grouping

### Changed

- **Preset add-model skips nickname** — preset path: discover → multi-select →
  batch save; custom URL path still uses single onboard with probe
- **`/model` groups by provider** — 最近常用 / provider name / 其他 / 操作
- **`/addmodel` OpenCode connect-provider flow** — shared `DialogSelect` /
  `DialogPrompt` wizard instead of a numbered menu

### Fixed

- **Discover failure routing** — auth/transport failures return to the API Key
  step; only `unsupported_catalogue` falls back to manual model id
- **Custom URL HTTPS guard** — rejects non-HTTPS before calling discover
- **Esc on model list** — goes back a step instead of closing the wizard
- **Structured discover errors** — `error_code` in API responses for TUI routing

### Install notes

- **Default one-command install** now pins **`v1.2.3`**.
- **Exception (this release only):** **`v1.2.2` remains downloadable** from
  [GitHub Releases](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2).
  Use `RXYCODE_VERSION=1.2.2` or `@v1.2.2` if you need the previous patch.

---

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

[1.2.6]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.6
[1.2.5]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.5
[1.2.4]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.4
[1.2.3]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.3
[1.2.2]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2
[1.2.1]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.1
[1.2.0]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.0
[1.1.0]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.1.0
[1.0.0]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0
[0.3.3]: https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3
