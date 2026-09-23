# plugins/ + PluginService — 插件商店与适配器

## What Is This Module?

In-repo plugin **store** (catalog) plus install/connect runtime. GitHub and
Canva are OAuth connectors (Grok-web shape: 连接/添加 → browser authorize →
connected tools). Zip/registry install still works. Computer-use is an adapter
plugin on the same contract, not a screenshot GUI-agent kernel.

## Public surface

| Symbol | Role |
|--------|------|
| `plugins/catalog.json` | Store listing (name, connect kind, OAuth hosts) |
| `plugins/registry.json` | Bundled installable packages |
| `appserver.plugin_service.PluginService` | list / catalog / install / toggle / connect |
| `appserver.plugin_connect` | OAuth start/callback state machine (injected HTTP) |
| `appserver.plugin_adapter` | Adapter kind; must not import `core.graph` |
| protocol `plugin/list\|install\|uninstall\|toggle\|catalog\|connect/start\|connect/callback` | Wire |

## Dependencies

- **Inbound:** Desktop `PluginMarket` / `usePlugins`, appserver dispatch.
- **Outbound:** `mcp/` (publish + token inject), `appserver.capabilities`, `tools.mcp_manager`. **Not** `core.graph`.

## How to test

```
pytest tests/test_plugin.py tests/test_gx24_plugin_consume.py tests/test_module_inventory.py -q --timeout=180
```

Desktop: `frontend/desktop-app` `node --test src/features/plugins/PluginMarket.test.ts`.

## How to add a plugin without breaking maintainability

1. Add a row to `plugins/catalog.json`.
2. Add `plugins/<name>/plugin.json` (+ skills/tools/mcp files).
3. If OAuth: authorize host + token URL in the catalog row; reuse `plugin_connect`.
4. Do not edit `core/graph.py` or `core/agent_v2.py`.
5. Extend `tests/test_plugin.py` on the shipped `PluginService`.
