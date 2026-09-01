# Changelog

All notable changes to RxyCode are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- First-party **module inventory** (`docs/modules/catalog.yaml`) and **development order** (`docs/development-order.yaml`, `docs/DEVELOPMENT-ORDER.md`) with parallel tracks vs must-wait gates. ADR: `docs/decisions/2026-09-01-architecture-inventory.md`. Tracked despite `docs/*` ignore via `.gitignore` exceptions.
- **Plugin store** catalog (GitHub, Canva) with Grok-web-like 连接/添加 OAuth (`plugin/catalog`, `plugin/connect/start`, `plugin/connect/callback`). Tokens stay in plugin `user.json`, never `config.yaml`. Protocol card: `docs/decisions/G-PROTOCOL-031.md`.
- **computer-use** adapter plugin on the same install/list contract (adapter seam only; no screenshot GUI-agent kernel).

### Changed

- Desktop plugin hub primary GitHub/Canva actions call `plugin/connect/start` instead of PAT-only connect.
- Local file tasks that mention ``当前工作目录`` / leftover ``现在`` no longer force websearch prefetch or abort the turn when search fails.
- OAuth token exchange POSTs the same `client_id` used to build the authorize URL (stored on the pending session).
- Module catalog no longer lists the untracked `game/` demo; inventory scan uses git-tracked `<pkg>/__init__.py`.

---

## [1.2.12] - 2026-08-31

### Highlights

Muse Spark and HY3 providers land on the existing Chat / Responses /
Anthropic Messages transports (PR #17, original work by log188). DeepSeek
and OpenAI Responses keep native reasoning across stream snapshots and
Executor `/full`. Custom `resource_path` is honored on the async HTTP
client. GitHub Release **v1.2.12** publishes **one** asset:
`rxycode-1.2.12.tar.gz`. No new Windows / macOS / Linux Desktop binaries.
**v1.2.10** stays published. Protocol version stays `1.1.0`.

### Added

- **Muse Spark** — `muse-spark-1.1` / `1.2` / `1.2-contributor`; OpenCode Go
  uses OpenAI Responses, Meta Chat Completions stays Chat
  (`core/providers/muse_spark.py`).
- **HY3** — formal `hy3` identity on OpenCode Go / compatible gateways;
  Chat Completions transport (`core/providers/hy3.py`).
- Responses-first probe contracts and exact `resource_path` rewrite for
  Chat / Responses HTTP clients.

### Fixed

- Anthropic custom `resource_path` is rejected (Messages transport cannot
  rewrite it). Sonnet 4.5 stays distinct from Sonnet 5; 1h cache TTL is
  shared with the 5m default.
- langchain-openai 1.3.3 dropped `response.reasoning_text.delta` and
  reasoning `output_item.done`; gated conversion brings them back for
  AgentV2 and Executor `/full` without polluting follow-up requests.
- Reasoning `output_item.done` is a snapshot, not a delta — later chunks
  no longer duplicate text. Multi-part `[A, B, AB]` merges prefer the
  unindexed snapshot.
- `asyncio.wait_for(anext)` no longer resets a ContextVar token created
  in a different Task (Linux py3.11/3.12 `llm_stream_error`).
- P7 lazy-import count stays under 150 after the provider work.

### Changed

- Product version **1.2.12** in `pyproject.toml`, installers, OpenTUI/Ink
  headers, MCP `clientInfo`, and Desktop package metadata. Protocol
  (`protocol/version.py` `1.1.0`) is unchanged.
- Release workflow builds and uploads **sdist only**. No desktop matrix
  on this tag.

---

## [1.2.11] - 2026-08-21

### Highlights

Expert-team runtime (Phase F) ships behind `settings.agents.enabled=false`.
Long tool writes, Windows encoding, and empty HTTP 200 responses are more
reliable. GitHub Release **v1.2.11** publishes **one** asset:
`rxycode-1.2.11.tar.gz`. No new Windows / macOS / Linux Desktop binaries.
**v1.2.10** stays published. Protocol version stays `1.1.0`.

### Added

- **Expert teams** — AgentSpec / TeamSpec, deterministic SopMachine,
  Coordinator, BudgetGuard, mechanical verifier, ModeRouter, JSON-RPC
  worker bridge, builtin `software_dev` Team Pack
  (`core/agents/teams/software_dev/`: 10 roles, 7 SOP stages, PM +
  frontend/backend + tester + mechanical verifier + three auditors + doc).
  Default off. Role-level `ecosystem.*` skill bindings; GitHub skills
  vendored only after SPDX + content gates. Live dispatch uses a per-role
  `AgentRuntime` (isolated cache namespace), not a shared Primary instance.
  The sdist includes `core/agents/teams/**/*.yaml` and `**/*.md`.
- **Docs** — `docs/agent/`, `docs/quickstart.md`. Screenshots live in
  `docs/imgs/`.

### Fixed

- Clarify/plan no longer stall-replan when a child hits wall-clock after
  already producing a non-empty spec or file-level plan. Architect prompt
  treats an empty workspace as greenfield and must not browse `data/`
  or parent directories.
- Stdio OpenTUI and Desktop now route `/team`, `/team-multi`, `/solo`,
  `/why-mode`, and `/agents` through `Session.prompt`, so expert teams
  actually start. Builtin `software_dev` is listed by `team/list`.
  Coordinator dispatches roles through the live AgentV2 instead of a stub.
  When `agents.enabled=false` (the default), ordinary prompts skip ModeRouter
  so concurrent sessions and `session/interrupt` keep AgentV2 latency.
- Expert-team `form_team` binds a per-role `AgentRuntime` so architect
  cannot `write`/`edit`/`patch`. Parallel stages (`parallel_members`)
  dispatch with `asyncio.gather`. `ChildStatus.COMPLETED` now advances SOP
  (Python 3.11+ `str(enum)` is not `completed`).
- `software_dev` plan stage no longer requires a verbatim `expected_output`
  match (`goal_satisfied`) before implement.
- Expert-team `delegate_request` prompt now has a `<ROLE>` section; architect /
  coder / auditor / delegate stages have few-shot examples.
- Integration main-chain test no longer patches the removed
  `AgentV2._should_request_parallel_execution` (ModeRouter / `should_use_subagents`).
- Stream idle timeout 30s (cap 90s) and tool-arg wait 60s so large writes
  are not cut mid-file.
- appserver JSON-RPC stdio limit raised to 8MiB (was 64KiB).
- Windows tool output decodes with `errors=replace` instead of crashing on
  mixed UTF-8 / GBK.
- One retry when a provider returns HTTP 200 then silence.
- Release notes no longer tell a CLI-only install to run `rxycode gui`.
  Desktop is a separate GitHub Release download; the sdist does not ship
  Electron.
- Published sdist no longer ships `evals`, `.coveragerc`, `AGENTS.md`, or
  repo test scripts.
- Linux AppImage startup: `rxycode gui` marks the image executable and
  sets `APPIMAGE_EXTRACT_AND_RUN=1`; the packaged app passes `--no-sandbox`
  so missing FUSE / unsigned chrome-sandbox no longer abort launch.
- Weekly scheduled CI no longer treats live-provider 401/quota/circuit-breaker
  as an AgentV2 quality regression (eval gate skips; live test skips).
- Provider 401/quota text no longer echoes `sk-` / `ark-` keys (including
  asterisk-masked forms) into CI logs, agent answers, or eval artifacts.
- GitHub Actions no longer stores or injects `RXYCODE_LIVE_API_KEY`. Live and
  eval suite runs stay on a local machine.

### Changed

- Product version **1.2.11** in `pyproject.toml`, installers, OpenTUI/Ink
  headers, MCP `clientInfo`, and Desktop package metadata. Protocol
  (`protocol/version.py` `1.1.0`) is unchanged.
- Release workflow builds and uploads **sdist only**. No desktop matrix
  on this tag.
- GitHub `docs/` is trimmed to `agent/`, `assets/`, `imgs/`, `modules/`,
  `release-notes/`, `quickstart.md`, and `GUI.md`.

---

## [1.2.10] - 2026-08-16

### Republish

- `rxycode gui` finds the portable zip wrapper folder, a dropped macOS `.app`,
  or a Linux AppImage instead of only a flat `rxycode-desktop.exe`.
- Desktop runtime staging rewrites pip console-script launchers so zip / dmg /
  AppImage no longer point `rxycode` at the GitHub Actions runner path.
- `rxycode --api` / `Session.prompt` bind the caller workspace so writes do not
  land in the installed package tree.
- Release notes and GUI docs use the published Windows zip name
  `RxyCode.Desktop-<version>-win.zip`.

### Highlights

Desktop GUI release. RxyCode now ships a real Electron app (`rxycode gui`)
with Codex-style Plan mode, a standing Goal dialog, a plan card
(Build / Revise / Skip), and a Composer `+` menu for attachments,
workspace, goal, and plan. OpenTUI remains the default CLI: type
`rxycode` in cmd (or any terminal). Product version is **1.2.10**.
Protocol version stays `1.1.0`.

### Added

- **Desktop Plan / Goal / workspace flows** — Plan mode keeps the agent on
  a plan document; Goal dialog stores a standing goal; plan card offers
  实施 / 补充说明 / 跳过 (`frontend/desktop-app/src/renderer/src/components/`).
- **Composer `+` menu** — 文件和文件夹、在项目中使用、目标、计划模式
  (`ComposerPlusMenu.tsx`).
- **CLI real-business harness** — stdio JSON-RPC client that starts
  `python -m appserver`, creates a workspace session, and prompts through
  ProtocolClient (`real-business-cli-harness.mts`). Test/ops tool, not an
  extra user command.

### Fixed

- Goal dialog closes on Escape and overlay click.
- Full-access confirmation closes on Escape.
- Attached file paths are written into the prompt (`promptWithAttachment`).
- Permission mode labels in the Desktop UI are Chinese: 更改前询问 /
  自动编辑 / 完全访问.
- **OpenTUI composer gap** — chat ScrollBox packs messages against the
  input box (`justifyContent: flex-end`) so tool output is not stranded
  at the top of the pane (“命令与输出分离”).

### Changed

- Product version **1.2.10** in `pyproject.toml`, installers, OpenTUI/Ink
  headers, MCP `clientInfo`, and Desktop Settings 「当前版本」
  (`frontend/desktop-app/package.json`). Protocol (`protocol/version.py`
  `1.1.0`) and evals package version are unchanged.

---

## [1.2.9] - 2026-08-09

### Highlights

Isolated subagent release (Phase C). RxyCode now runs real Child Agents —
OpenCode-style subagents with independent sessions, contexts, tools,
permissions, budgets and lifecycles — instead of re-invoking the primary
agent. Primary interacts with children only through structured
TaskRequest / TaskResult protocol. OpenTUI renders the child tree, exposes
`/children` `/child` `/parent` navigation and `@agent` mention dispatch.
An upstream-reuse audit (OpenCode commit locked, MIT) documents every
adapted semantic. Full-suite green: 10840 tests, CI (Linux/Windows/OpenTUI/
protocol-client) all pass, evals GATE PASS 94.7% vs baseline.

### Added

- **Isolated Child Session runtime (C1-C14)** — `core/subagents/`:
  independent session, context envelope (references + redaction), scoped
  tool registry, permission policy, memory/cache namespaces, budget guard,
  cancellation scope, workspace write leases.
- **Subagent protocol** — `protocol/subagents.py` + machine-verifiable
  `subagents_schema.json`: AgentDefinition, TaskRequest, TaskResult,
  ChildSessionEvent with version field and terminal-state idempotency.
- **Built-in agents** — `config/agents/`: `explore` (read-only code
  exploration), `general`, `reviewer` (read-only review), `scout` (external
  research); JSON / Markdown / YAML definitions normalized into one registry.
- **Three trigger entries** — model Task Tool (`task`), user `@agent`
  mention, and `subtask=true` commands; all through one ChildSessionManager.
- **OpenTUI subagent UI** — child tree with status/agent/session display,
  `/children` `/child <id>` `/parent` commands, `@agent` mention wired to
  `agent/invoke` (stdio JSON-RPC / HTTP).
- **Upstream reuse audit** — `docs/decisions/upstream-reuse.md` locks
  OpenCode commit `fe82a1b` (MIT) with per-card reuse records.
- **protocol-client subagent types** — generated TypeScript types for
  TaskRequest/TaskResult/ChildSessionEvent; CI typecheck green.

### Fixed

- **Legacy `agent` tool migration (C13)** — when subagents are enabled the
  legacy unisolated AgentV2 entry raises a deprecation error pointing to the
  `task` tool; feature flag off keeps the legacy path byte-for-byte.
- **P7 lazy-import budget 60→70** — Phase B subagent tree adds function-scoped
  imports (runtime/manager/permissions), budget re-ratcheted.
- **Merge-regression repairs** — restored master DDGS websearch engine,
  B1 dual-track cache stats, and evidence-gate fixes that the out-of-date
  PR branch had silently dropped.
- **Linux CI path semantics** — external-directory tests now use
  platform-independent absolute paths (`tmp_path` instead of hardcoded
  `C:/workspace`).
- **Secret-scan compliance** — test fixtures use `fake`-marked placeholder
  credentials so `scripts/scan_secrets.py` passes.

### Changed

- **B14 exit checklist** — accurately reflects OpenTUI consumption
  (child events, tree, `@agent`) and marks CLI/standalone-Desktop wiring as
  future-phase follow-ups.
- **Eval evidence** — 18/19 = 94.7% (GATE PASS vs 88.2% baseline) recorded;
  baseline file refresh deferred to the follow-up Phase B merge.
- **`@agent` parse helper** — `parseMention()` pure function with 6 unit
  tests (bun test 138 pass, tsc clean).

---

## [1.2.8] - 2026-08-08

### Highlights

Model-support release. Phase A of the model adaptation layer is complete:
DeepSeek v4 (flash/pro) thinking-mode providers get exact capability
isolation, the Doubao (ark) provider is finished with conservative pro
boundaries, the Anthropic Claude 5 family (Opus/Sonnet/Fable/Haiku/Opus 4.8)
is fully adapted with endpoint-aware prompt caching, and per-model
capabilities, pricing, cache parameters and latency/thinking knobs are now
carried through the provider layer. Phase A exit checks pass with zero eval
regression (94.7% vs 89.5% baseline).

### Added

- **DeepSeek v4 support (A22)** — exact v4-flash/v4-pro identification, 1M
  context, 384K max output, thinking-on by default with effort presets; legacy
  deepseek-chat/reasoner keep A3 behavior.
- **Doubao (ark) provider completion (A23)** — 256k context / soft 256k output,
  `reasoning_content` extraction, function calling; pro stays conservative (R1).
- **Anthropic Claude 5 family (A18)** — five mainstays (Opus 5 / Sonnet 5 /
  Haiku 4.5 / Fable 5 / Opus 4.8), per-mainstay context/max-output/pricing,
  endpoint-aware `supports_prompt_cache`, sampling 400 contract, thinking-block
  handling.
- **per-model optimization knobs (A19-A21)** — cache parameters (min block /
  TTL / breakpoints), token governance, latency/effort presets.

### Fixed

- **Unknown-model capability leaks (DC1)** — unknown variants no longer inherit
  researched capabilities (context, pricing, thinking, cache) across providers.
- **Substring-based model matching** — replaced `"v4" in name` / `"ark" in url`
  generalizations with exact hostname/model matching (prevents cross-model
  stealing on shared endpoints).
- **bash absolute-path escape and Windows recursive-delete safety (stress S1/S12).**

### Changed

- **Phase A exit checks pass** — ruff clean, 10412 tests green, evals GATE PASS
  94.7% vs baseline 89.5%, no hardcoded gpt-4o tokenizer / 256000 context.

---

## [1.2.7] - 2026-08-06

### Highlights

Reliability-fix release focused on the research and thinking-mode paths. A
failed read-only probe (e.g. one 404 during web research) no longer discards a
fully completed answer; the mandatory web-research path now derives a concise
query from task language instead of sending the whole instruction to a search
engine; DeepSeek-style thinking-mode providers get their `reasoning_content`
echoed back on tool-bearing assistant messages (fixes HTTP 400); and tasks that
already produced a written deliverable keep their answer even when a cited URL
was not fetched. Also adds the Doubao (ark) provider.

### Added

- **DoubaoProvider** — model support for the ark coding endpoint (A23).
- **Research query extraction** — `extract_research_query()` strips task-direction
  boilerplate so the search engine receives the topic, not the full instruction.

### Fixed

- **Completed answers preserved** — only WRITE/DANGER or artifact-validation
  failures override a finished answer; a failed read-only probe (webfetch 404,
  websearch miss) no longer replaces a well-sourced reply with
  `[evidence failed: ...]`.
- **DeepSeek thinking-mode 400** — `reasoning_content` is carried back on
  tool-bearing assistant messages (`_to_openai_messages` + `AIMessage`
  `additional_kwargs`), satisfying the "must be passed back to the API" contract.
- **Side-effect tasks keep their answer** — a task that already wrote a file no
  longer returns "could not verify" just because the answer cited an unfetched URL.

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

[1.2.12]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.12
[1.2.11]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11
[1.2.10]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10
[1.2.9]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.9
[1.2.8]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.8
[1.2.7]: https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.7
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
