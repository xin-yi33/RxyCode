# config/ - Configuration Management

## What Is This Module?
Manages all RxyCode configuration: model settings, API keys, active model selection, and user preferences. Stores config in `~/.RxyCode/config.yaml`.

## Key Files
| File | Purpose |
|------|---------|
| settings.py | Core config functions: load_config(), save_config(), get_data_dir(), get_output_dir() |
| credential_store.py | Atomic owner-only credential storage; DPAPI protection on Windows |
| model_manager.py | Model CRUD plus persisted and unsaved connection probes |

`model_manager.probe_model_connection()` accepts an API key, base URL, and
provider model ID directly and performs no persistence. The API onboarding flow
uses it before `add_model()`, so invalid credentials cannot leave a broken model
entry behind. `test_model_connection()` remains the persisted-model wrapper.

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

## Default Config Structure
- models: dict of model_name -> {api_key_env or api_key_secret, base_url, model_name}
- active_model: str
- language: zh or en
- memory: {short_term_window, long_term_threshold}
- cache: {enabled, prompt_prefix_cache, ttl}
- mcpServers: dict of server configs
- scheduler: {enabled, check_interval}
- execution: {parallel_enabled, max_parallel, tool_timeout_seconds, pipeline_soft_budget_seconds, task_stall_timeout_seconds, task_max_time_seconds, heartbeat_interval_seconds}. `tool_timeout_seconds` defaults to `1800`, `task_stall_timeout_seconds` defaults to `0`, and `task_max_time_seconds` defaults to `7200`. A legitimate silent task is therefore not killed at 600 seconds, while explicit tool and total-task ceilings still apply.

`execution.tool_timeout_seconds` is the unified per-tool wall-clock deadline
used by fast-path, graph, and workflow calls. Setting it to `0` explicitly
disables that layer; explicit task cancellation still propagates regardless of
this setting.

## Data Migration
When the default data root is used, `settings.py` copies missing entries from the previous `~/.rxycode/` root and the legacy in-repo `data/` directory into `~/.RxyCode/`. Explicit `RXYCODE_DATA_DIR` locations are not populated from legacy sources.

Legacy inline model credentials are migrated on load. `config.yaml` keeps only
an environment-variable or opaque secret reference. Windows protects stored
values with per-user DPAPI; POSIX stores them in a dedicated `0600` file. Both
files use same-directory temporary writes, `fsync`, atomic replacement, and
permission tightening on every load/save.
