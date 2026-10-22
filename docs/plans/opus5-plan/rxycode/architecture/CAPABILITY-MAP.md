# Capability Map: maintainability + plugin/connect

> **Status:** Accepted（2026-09-01）。产品循环实现仍按 DEV-ORDER 波次，本图不授权当场拆 `agent_v2.py`。
> **Date:** 2026-09-01
> **Why this exists:** 一次请求捆了多块可独立验收的能力；先定模块 id 和依赖方向，再写各模块 spec。

## Modules

| Module id | Responsibility | Depends on |
|-----------|----------------|------------|
| `arch-governance` | 以代码为准的分层图、模块契约、ADR 索引、禁止第二套 agent 循环 | — |
| `docs-dev-order` | 活的开发顺序：串行/并行、哪份文档作废、哪份权威 | `arch-governance` |
| `module-readmes` | 每个真实模块的详细说明，回链 `AGENTS.md` | `arch-governance` |
| `plugin-host` | 现有 `plugin/*` + MCP + skills 收成唯一宿主；商店不另开 invoke | `arch-governance` |
| `connectors-oauth` | Grok Web 式 Connect（GitHub/Canva）：跳转授权、密钥不进 core | `plugin-host` |
| `computer-use-adapter` | 直接控制 + 事实观察（默关）；优先接入 iFurySt/open-codex-computer-use MCP。CLI-Hub `cli_list`/`cli_run` **并存不得替代**。像素点击不是默认软件控制。见 ARCH-003 | `plugin-host` |
| `targeted-refactor` | 只改审计证明会破坏可测性的点；每步 ADR + 测试 | `arch-governance`, `docs-dev-order` |
| `verification` | 文档/边界/协议约束测试 | 贯穿全程 |

## Build order

```text
arch-governance
    → docs-dev-order  ∥  module-readmes
    → plugin-host
    → connectors-oauth  ∥  computer-use-adapter
targeted-refactor 插在有证据的位置
verification 每层都跑
```

`admin-backend/` 标为仓内旁路实验，不进入主产品模块图。

`docs-dev-order` 必须处理：`docs/plans/` 整目录被 gitignore，导致「权威执行计划」对 git/agent 搜索不可见，且与字母 Phase、已跟踪的 `docs/phase-g/` 三套并行。

## Hard boundaries (all modules)

- Headless `Session` 不做 TUI/HTTP I/O；表面只讲 JSON-RPC。
- 插件/Connect 安装与授权在 `appserver`；工具执行仍进 `ToolOrchestrator`。
- 不新增第二条聊天脑（不为 Connect 去扩 `api_server.py` `/chat`）。
- Computer Use：口述要事实观察与授权内操作（ARCH-003）。08-12 冻结的是「像素点击当默认/唯一软件控制」，不是「永远不做直接控制」。CLI-Anything 软联系可并存、不得替代。闭源无 SDK 仍不靠自研截图循环补洞；优先开源 MCP。
