# 开发顺序（并行 vs 必须等待）

机器可读源：[`docs/development-order.yaml`](development-order.yaml)。
模块地图：[`docs/modules/catalog.yaml`](modules/catalog.yaml)。

本文件回答三件事：先做什么、哪些可以同时做、加新功能时走哪条缝以免拆掉可维护性。

## 总序

```
architecture-inventory
        │
        ▼
 adapter-contract   ← 插件只能登记到这里，禁止改 core/graph.py
        │
        ├──────────────┬──────────────────┬──────────────────┐
        ▼              ▼                  ▼                  ▼
 oauth-github    oauth-canva    computer-use-adapter   oauth-secrets-mcp
        │              │                  │                  │
        └──────────────┴────────┬─────────┴──────────────────┘
                                │
                    desktop-plugin-hub（可与 OAuth 实现并行，但必须等 adapter-contract）
                                │
                                ▼
                         tests-quality
```

## 必须等待（串行门）

| 后继 | 必须先完成 | 原因 |
|------|------------|------|
| `adapter-contract` | `architecture-inventory` | 先有模块边界，才知道插件不该进 agent graph。 |
| `oauth-github` / `oauth-canva` | `adapter-contract` | 连接器是 catalog 数据 + 同一套 `plugin/connect/*`，不是新的编排器。 |
| `computer-use-adapter` | `adapter-contract` | 只提供 adapter seam，不做像素级 Computer Use 内核。 |
| `tests-quality` | 上述实现轨 | Quality 跑的是已上船的 store/connect/adapter，而不是副本。 |

**插件 OAuth 必须等 architecture + adapter。** 不要在 `core/graph.py` / `core/agent_v2.py` 里加 `if plugin == "github"`。

## 可以并行

- **oauth-connectors 组**：GitHub OAuth、Canva OAuth、computer-use 适配器、MCP 密钥注入。共享 adapter 合约后互不阻塞。
- **surfaces 组**：Desktop `连接/添加` 可在协议方法名冻结后与 connector 实现并行。
- **docs 组**：模块 README 补全可与实现并行，但 catalog.yaml 本身是 architecture-inventory 的交付物。

## 如何加东西（可维护性）

1. 先查 `docs/modules/catalog.yaml`：改动落在哪个包、依赖方向是什么。
2. 新插件/连接器：只改 `plugins/catalog.json` + 一个 `plugins/<name>/` 包 +（如需）OAuth 条目。不要改 graph。
3. 新协议方法：`protocol/requests.py` → `python -m protocol.schema` → `frontend/protocol-client` generate → appserver handler。
4. Desktop 只消费 JSON-RPC，禁止 import `core/`。
5. 密钥只进插件 `user.json` / credential store，禁止 `config.yaml` 与日志。
6. 每做一次结构性移动，写 `docs/decisions/` + `CHANGELOG.md` `[Unreleased]`。

## 本轮交付顺序（已执行）

1. 架构盘点与开发顺序（本文 + catalog）。
2. adapter 合约 + OAuth connect 状态机（注入 HTTP，测试不打公网）。
3. GitHub / Canva catalog 行；computer-use 适配器安装。
4. Desktop 连接/添加走 `plugin/connect/start`。
5. `tests/test_module_inventory.py` + `tests/test_plugin.py` 门禁。
