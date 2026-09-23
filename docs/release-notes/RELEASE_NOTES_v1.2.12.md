# RxyCode v1.2.12

RxyCode is a local plan-and-execute coding agent. Type `rxycode` in a terminal to open OpenTUI. Protocol version stays `1.1.0`.

> **v1.2.12 is the current CLI release.** This GitHub Release publishes **one** installable asset: `rxycode-1.2.12.tar.gz`. It does **not** add Windows, macOS, or Linux Desktop binaries. The **v1.2.10** Desktop release remains published.

## What changed

- Muse Spark and HY3 providers land on the existing Chat / Responses / Anthropic Messages transports (PR #17, original work by [log188](https://github.com/log188)).
- DeepSeek and OpenAI Responses keep native reasoning across stream snapshots and Executor `/full`.
- Custom `resource_path` is honored on the async HTTP client; Anthropic Messages rejects it instead of probing a path it cannot rewrite.
- Sonnet 4.5 stays distinct from Sonnet 5; 1h prompt-cache TTL is shared with the 5m default.

## Highlights

- **One download** — `rxycode-1.2.12.tar.gz` (source distribution). Install with pip or uv.
- **Desktop stays on v1.2.10** — `RxyCode.Desktop-1.2.10-win.zip`, setup.exe, dmg, and AppImage remain on the still-open v1.2.10 release.
- **Muse Spark + HY3** — OpenCode Go / Meta / Tencent identities without a fourth transport type.
- **CLI is still OpenTUI** — type `rxycode` in cmd or any terminal.

## Details

### Added

- **Muse Spark** — `muse-spark-1.1` / `1.2` / `1.2-contributor`. OpenCode Go uses OpenAI Responses; a direct Meta Chat Completions endpoint stays Chat (`core/providers/muse_spark.py`).
- **HY3** — formal `hy3` model identity on OpenCode Go and compatible gateways; Chat Completions transport (`core/providers/hy3.py`).
- Responses-first probe contracts and exact `resource_path` rewrite for Chat / Responses HTTP clients.

### Fixed

- Anthropic custom `resource_path` is rejected on save / probe / runtime (Messages cannot rewrite an exact path).
- langchain-openai 1.3.3 dropped `response.reasoning_text.delta` and reasoning `output_item.done`; gated conversion brings them back for AgentV2 and Executor `/full` without duplicating text on the next request.
- Reasoning `output_item.done` is treated as a snapshot, not a delta, so later fragments do not reprint the same thought.
- `asyncio.wait_for` no longer turns a completed Responses stream into `llm_stream_error` (`ContextVar` token reset across Tasks).

### Changed

- Product version **1.2.12** in `pyproject.toml`, installers, OpenTUI/Ink headers, MCP `clientInfo`, and Desktop package metadata. Protocol version stays `1.1.0`.
- Release workflow builds and uploads **sdist only**. No desktop matrix on this tag.

## Install

CLI / OpenTUI (no Electron):

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.12/install.ps1 | iex"
rxycode
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.12/install.sh | sh
rxycode
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.12"
rxycode
```

From this release asset:

```bash
python -m pip install rxycode-1.2.12.tar.gz
rxycode
```

**Desktop GUI** is not attached here. Download it from [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) (`rxycode-desktop-1.2.10-setup.exe` or `RxyCode.Desktop-1.2.10-win.zip`, plus macOS dmg / Linux AppImage). A CLI-only install cannot start Electron.

## Assets

- `rxycode-1.2.12.tar.gz`
