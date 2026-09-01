# Spec: Plugin store (Grok-web-like OAuth connectors + computer-use adapter)

## Problem

RxyCode already has a B18 plugin hub (zip/registry install + GitHub PAT).
Maintainability is poor: module docs are incomplete, there is no development
order, and adding a connector looks like it might require editing the agent
graph. Users want a store like Grok web: catalog → 连接/添加 → browser OAuth
→ connected tools. GitHub and Canva are the first OAuth rows. Computer-use is
an **adapter plugin**, not a screenshot GUI-agent kernel.

## Assumptions

- Worktree: `D:\agent-demo\RxyCode-phase-g-integrate` (not `C:\Users\Administrator\RxyCode`).
- Protocol stays `1.1.0` (additive methods). Product version is not bumped.
- No live github.com / canva.com token exchange in this environment.
- PHASE-K DK4 said “不自建市场”; this spec **keeps** an in-repo catalog because
  the product objective asks for 插件商店. Zip/registry install remains.
- Pixel-level Anthropic Computer Use is out of scope.

## Out of scope

- Gmail / Drive / Linear / Slack / other Grok connectors.
- Registering a real OAuth app against production providers.
- Merging to `origin/master`.
- Replacing zip/registry install.

## Architecture

```
Desktop PluginMarket  --plugin/catalog-->  PluginService.catalog()
                      --plugin/connect/start-->  plugin_connect.start_connect
                      --plugin/connect/callback--> plugin_connect.complete_connect
                                                         |
                                                         v
                                              user.json (token, never config.yaml)
                                                         |
                                                         v
                                              MCP publish / extra_rows tools
```

- `appserver/plugin_adapter.py` — adapter kind from manifest/catalog. No `core.graph` import.
- `appserver/plugin_connect.py` — OAuth state machine; HTTP transport injected.
- `plugins/catalog.json` — store listing (github, canva, computer-use).
- New plugins = catalog row + package under `plugins/<name>/`. Do not edit the orchestrator.

## Protocol (additive)

| Method | Params | Result |
|--------|--------|--------|
| `plugin/catalog` | (none) | `{plugins: [{name, title, connect, auth, ...}]}` |
| `plugin/connect/start` | `{name}` | `{authorize_url, state, plugin}` ; URL host is the provider OAuth host |
| `plugin/connect/callback` | `{name, code, state}` | `{ok, plugin}` with `auth=configured` and tools/MCP published |

Existing `plugin/list|install|uninstall|toggle` unchanged. PAT connect via
`plugin/install` + `token` remains as a fallback, not the Desktop primary path.

## OAuth

- GitHub authorize host: `github.com` (`/login/oauth/authorize`).
- Canva authorize host: `www.canva.com` (`/api/oauth/authorize`, PKCE).
- Token POST goes through `HttpTransport.post`. Tests supply a fixture transport.
- Tokens written to `<plugin>/user.json`. Redacted from list/catalog payloads and logs.

## Computer-use adapter

Install `computer-use` through `PluginService.install` (registry/local). Manifest
`adapter: computer-use` plus a tool entry. Listed with tools. No graph edits.

## Agent-eval / AC

1. Catalog contains `github` and `canva`.
2. start-connect for each returns an authorize URL on that provider's OAuth host.
3. Fixture callback marks `auth` connected and publishes tools/MCP.
4. computer-use installs via the same contract and appears in list with tools.
5. adapter/connect modules do not import `core.graph`.
6. Module inventory lists every root package; order doc has parallel + must-wait.

## Desktop

连接/添加 on GitHub and Canva rows calls `plugin/connect/start` (then open the
authorize URL). PAT-only UI must fail `PluginMarket.test.ts`.
