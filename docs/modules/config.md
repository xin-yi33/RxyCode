# config/ - Configuration Management

## What Is This Module?
Manages all RxyCode configuration: model settings, API keys, active model selection, and user preferences. Stores config in `~/.RxyCode/config.yaml`.

## Key Files
| File | Purpose |
|------|---------|
| settings.py | Core config functions: load_config(), save_config(), get_data_dir(), get_output_dir(). `agents.enabled` defaults false (DC7). Nested expert-team fields (`team`, `route_mode`, `router_model`, budgets) stay hidden in /settings until enabled. `distillation.collect` defaults false (J3). |
| credential_store.py | Atomic owner-only credential storage; DPAPI protection on Windows |
| model_manager.py | Model CRUD plus persisted and unsaved connection probes |
| model_catalog.py + model_catalog.json | Static model catalog (nickname/provider/model mapping) with `catalog_max_age_days` staleness handling |
| core/catalog.py | **Cache-contract catalog (PHASE-FIX §16 已纠字段)** — per-model cache_mode/breakpoints/reasoning contract. Unknown models (no record) get the five-point `unknown_fallback_contract` (cache_mode=auto, no cache_control, no prompt_cache_key, default variant, openai-compatible). Only `injects_cache_control` / `injects_prompt_cache_key` decide injection — never model-name heuristics |
| model_limits.py | Output-limit resolution (`unknown_model_max_tokens=32768`, `context_safety_margin_tokens`, `resolve_max_tokens`) |
| model_capabilities.py | `ModelCapabilities`/`UsageFieldMap`/`ModelPricing` dataclasses consumed by every provider |
| agents/ | Built-in subagent definition files (`explore.json`, `general.json`, `reviewer.md`, `scout.yaml`) loaded by `core/subagents/config_loader.py` |

Headless CLI: `rxycode config add-model <id> <provider-model-id> --base-url <url>`
reads the API key from `RXYCODE_API_KEY` (never from argv). Empty config errors
point at this command or the TUI `/addmodel` flow, not a missing subcommand.

`add_model()` accepts optional `provider_id` and `provider_name` metadata for
grouping in `/model`. `onboard_models_batch()` adds multiple models in one pass;
when `skip_probe=True` (preset/custom discover path) it never calls
`probe_model_connection()`. Config keys are namespaced as
`{provider_id}/{model_id}` so the same vendor model id can exist under two
groups (e.g. DeepSeek vs OpenCode Go). `infer_provider_group(base_url)` maps a
URL host to a preset name, else ``其他``.

`model_manager.probe_model_connection()` accepts an API key, base URL, and
provider model ID directly and performs no persistence. The API onboarding flow
uses it before `add_model()`, so invalid credentials cannot leave a broken model
entry behind. The probe reuses Provider `transport_candidates()`: Other/custom
tries Responses first and falls back to Chat only for an explicit unsupported
endpoint/protocol error. When the HTTP client exposes the attempted resource,
generic `Not Found`/`Invalid URL` responses for `/responses` or
`/chat/completions` are accepted as endpoint-mismatch evidence; model/resource
404s without that evidence remain failures. Auth, policy, rate-limit, timeout,
network, server and ordinary request errors do not trigger a second request.
HTTP 200 is accepted only when the transport-specific response body contains a
non-empty assistant reply. Native Anthropic probes use `/v1/messages` with
`x-api-key` and `anthropic-version`, rather than OpenAI Bearer headers.
Successful probes return the selected `transport`. `test_model_connection()`
remains the persisted-model wrapper.

## Core Code: settings.py
- get_data_dir() -> Path: Returns `~/.RxyCode/` (or `RXYCODE_DATA_DIR`). Creates it if missing and performs best-effort migration from `~/.rxycode/` and the legacy in-repo `data/` directory.
- get_output_dir() -> Path: Returns `~/.RxyCode/output/YYYY-MM-DD/` for generated files and downloads. `RXYCODE_OUTPUT_DIR` overrides the output root; the date directory is still appended.
- get_dated_data_dir(category) -> Path: Returns `~/.RxyCode/<category>/YYYY-MM-DD/` for dated project and session persistence.
- load_config() -> dict: Loads config.yaml, creates default if missing, and migrates legacy inline credentials.
- save_config(cfg): Atomically writes config.yaml and strips inline credentials.
- get_config_path() -> Path: Returns path to config.yaml.
- get_model_config(model_name) -> dict: Returns config for a specific model.
- get_active_model_config() -> dict: Returns config for the currently active model.
- get_mcp_config() -> dict: Returns MCP servers configuration.
- get_scheduler_config() -> dict: Returns scheduler configuration.
- DEFAULT_ALLOWED_ORIGINS: tuple of CORS origins allowed for the local API
  (`http://127.0.0.1:8765`, Vite `5173`, etc.). Override with env
  `RXYCODE_ALLOWED_ORIGINS` (comma-separated).

## Default Config Structure
- models: dict of model_name -> {api_key_env or api_key_secret, base_url, model_name, ...capability overrides}
- active_model: str
- language: zh or en
- memory: {short_term_window, long_term_threshold, vector_experience_enabled, rag_enabled}
- cache: {enabled, prompt_prefix_cache, ttl}
- mcpServers: dict of server configs
- scheduler: {enabled, check_interval}
- governance: {rate_limit: {rpm, tpm, burst, wait_timeout_seconds, reserved_output_tokens}, model_routes}
- model_limits: {unknown_model_max_tokens, context_safety_margin_tokens}
- safety: {enabled, permission_mode (full_auto/auto_edit/confirm_all), auto_approve, approval_timeout, allowed_write_paths, dry_run}
- context: {token_limit, compression thresholds}
- observability: {trajectory_retention_runs, trace_retention_runs, audit_max_bytes}
- lifecycle: {hook_timeout_seconds}
- pricing: per-model $/M token prices (for billing display)
- recovery: error-recovery policy defaults
- lsp: {enabled, servers}
- autoCompact: {enabled, threshold}
- rag: {index_delay_seconds, retrieval settings}
- evals: eval harness defaults
- execution: {parallel_enabled, max_parallel, max_graph_steps, max_tool_rounds, max_replan_rounds, tool_timeout_seconds, pipeline_soft_budget_seconds, task_stall_timeout_seconds, task_max_time_seconds, heartbeat_interval_seconds, checkpoint_enabled, checkpoint_retention, tool_journal_enabled, tool_journal_retention, tool_journal_max_result_chars, sandbox_mode, workspace_root, docker_image, docker_network, max_memory_mb, max_cpus, max_processes, tool_retry_max_attempts, tool_retry_backoff}. `tool_timeout_seconds` defaults to `1800`, `task_stall_timeout_seconds` defaults to `0`, `task_max_time_seconds` defaults to `7200`, `max_tool_rounds` defaults to `10`, `max_replan_rounds` defaults to `8`. A legitimate silent task is therefore not killed at 600 seconds, while explicit tool and total-task ceilings still apply.

`execution.tool_timeout_seconds` is the unified per-tool wall-clock deadline
used by fast-path, graph, and workflow calls. Setting it to `0` explicitly
disables that layer; explicit task cancellation still propagates regardless of
this setting. `sandbox_mode` is `workspace` by default (`host`/`workspace`/
`docker`), enforced by `utils/shell.py` `ShellExecutor`.

## Model Entry Fields

Each entry under `models:` is a dict keyed by model name. Recognized fields
(verbatim from `resolve_model_config()` and `add_model()` in `settings.py` /
`model_manager.py`):

| Field | Meaning |
|-------|---------|
| `model_name` | Model id sent to the provider (e.g. `deepseek-chat`) |
| `base_url` | API endpoint; also feeds `providers.resolve()` matching |
| `api_key_env` | Env var name holding the key (preferred storage form) |
| `api_key_secret` | Opaque reference into the DPAPI-protected credential store |
| `api_key` | Explicit inline key (migrated off on load by `_sanitize_model_credentials`) |
| `max_tokens` | Output token ceiling (default `8192` in `llm_kwargs`) |
| `temperature` | Sampling temperature (default `0.7` in `llm_kwargs`) |
| `provider_id` / `provider_name` | Grouping metadata for `/model` (see `add_model()`) |
| `provider` | **Explicit** provider name; bypasses `matches()` probing (short-circuits in `providers.resolve()`) |
| `api_transport` | Expert compatibility override: `openai_chat`, `openai_responses`, `anthropic_messages`, or omitted/`auto`; legacy `chat`/`responses` are migrated at the config boundary |

**全局思考强度档位（`effort` 键，2026-08-12）**：配置顶层 `effort` 键 = 全局思考强度档位（厂商档位值如 `medium`，或抽象档位 `fast`/`balanced`/`deep`）。读写入口：`config/model_manager.py` 的 `get_effort()` / `set_effort()`；消费方：`core/agent_v2.py::_build_llm_from_config`（优先级：显式传入 > 全局设置 > `balanced`）；设置入口：CLI `/effort` 命令与 `models/set_active` 的 `effort` optional_field。

**`api_key` resolution priority** (`resolve_model_config()`, `config/settings.py`):

1. `api_key_env` — read the env var into `api_key`. A literal `api_key` value in
   `${ENV_VAR}` reference form is treated as an env name too.
2. If the env var is unset/empty **and** `api_key_secret` exists, fall back to
   `load_credential(api_key_secret, get_config_path())` (common for
   OpenTUI/appserver child processes that do not inherit the operator shell).
3. Otherwise an explicit inline `api_key` remains as-is.

**Model capability overrides:** every provider runs
`caps.merged_with_overrides(model_config)`, which accepts any `ModelCapabilities`
field name — e.g. `context_window`, `tokenizer`, `supports_reasoning` — written
directly inside the model entry to override the provider's declared value
(unknown fields are ignored; `usage_fields` is not overrideable). See
[docs/modules/providers.md](providers.md).

## Data Migration
When the default data root is used, `settings.py` copies missing entries from the previous `~/.rxycode/` root and the legacy in-repo `data/` directory into `~/.RxyCode/`. Explicit `RXYCODE_DATA_DIR` locations are not populated from legacy sources.

Legacy inline model credentials are migrated on load. `config.yaml` keeps only
an environment-variable or opaque secret reference. Windows protects stored
values with per-user DPAPI; POSIX stores them in a dedicated `0600` file. Both
files use same-directory temporary writes, `fsync`, atomic replacement, and
permission tightening on every load/save.
