# As-is architecture audit

> **Status:** Evidence（不是 Accepted ADR）
> **Date:** 2026-09-01
> **Scope:** `D:\agent-demo\RxyCode\RxyCode1_1_0`
> **Sources:** 仓库对照 + 插件/MCP 只读审计 + 可维护性/测试只读审计 + 文档/模块边界只读审计
> **Does not authorize:** 产品实现、大重构、截图 Computer Use

## 1. Verdict

主产品边界在 `AGENTS.md` 里是清楚的：OpenTUI/Desktop → `appserver` JSON-RPC → `Session` → `AgentV2` → `ToolOrchestrator`。乱的是 **真相源分层**：git 跟踪的模块 README / 协议卡，与 **被 `.gitignore` 整目录排除的 `docs/plans/`**（自称权威的数字 Phase 0–4 + 字母 Phase A–O）并行；再叠加 Phase G 双份、巨型文件、双传输，以及把 MCP 安装 / 插件 zip / OAuth Connect 混成一件事。

直接往现树里加「插件商店 + computer use + GitHub/Canva Connect」会再开一套循环或再开一个后端，可维护性会更差。

## 2. Documentation: what is live vs stale

| Artifact | Role today |
|----------|------------|
| [`AGENTS.md`](../../../../../AGENTS.md) + [`docs/modules/`](../../../../modules/) | 模块索引（30 篇 README，Key Files 大体存在）。2026-09-01 已修：history 误写成会话日志、protocol 版本 1.0.0、core 把 appserver 写成 future |
| [`docs/decisions/G-PROTOCOL-*.md`](../../../../decisions/) | 协议增量卡；最新 `G-PROTOCOL-030`；MCP 投影 [`G-PROTOCOL-010`](../../../../decisions/G-PROTOCOL-010.md)；插件 [`G-PROTOCOL-016`](../../../../decisions/G-PROTOCOL-016.md) |
| [`docs/phase-g/`](../../../../phase-g/) | **已跟踪** 的 Desktop 产品卡；冲突表记录路径失效、卡号撞车、章节号重复 |
| `docs/plans/` | **磁盘存在、git 忽略**（`.gitignore` 第 151 行）。含 `opus5-plan/rxycode/00-EXECUTION-PLAN.md`（自称 2026-08-03 权威，Phase 0–4）与 `PHASE-A`…`PHASE-O`（含 `PHASE-K-PLUGIN-DUAL-MODE.md`、`PHASE-F-MULTI-AGENT-ORCHESTRATION.md`）。Cursor/git 搜索会漏掉它们 |
| `docs/plans/opus5-plan/rxycode/phase-g/` | 与 `docs/phase-g/` **双份**（各约 12 个 md），易漂移 |
| `docs/superpowers/sdd/` | 外部 agent 源码核对 + phase-b progress；不是主执行队列 |
| [`docs/RxyCode_PLAN.md`](../../../../RxyCode_PLAN.md) | 过期树（`cli.py` / `agent.py` / `chains/`） |
| [`docs/ENGINEERING_AUDIT.md`](../../../../ENGINEERING_AUDIT.md) | 历史「已交付」报告，不是现行顺序图 |
| `docs/plans/execution/00-master-plan.md` | 页眉已作废，仍留在被忽略的树里 |

**两套「权威」主轴未合并：** 数字 Phase 0–4 vs 字母 A–O（且 archive 里字母语义曾改名）。没有一张可执行的并行/串行总图。

**无对应模块 README 的产品目录：** `admin-backend/`、根 `desktop/`、`packaging/`、`scripts/`。

**`docs/modules/live-ux-report.md`** 是实测报告，不是模块。

Computer use：**没有** `docs/decisions` ADR，只有调研结论「不做截图点击」。

## 3. Runtime boundaries to keep

```text
OpenTUI / Desktop
  → stdio JSON-RPC (protocol/ + appserver/)
    → Session.emit() 仅协议事件
      → AgentV2
        → tools / MCP 一律 ToolOrchestrator（审批、超时、审计）
Ink + api_server.py HTTP/SSE = 后备适配器，同一 Session，不是第二大脑
```

已确认：前端不 import Python `core/`。风险是 OpenTUI 仍保留 `httpTransport` → `/chat/stream`（`frontend/opentui-app/src/transport/httpTransport.ts`），与「单一 JSON-RPC」教条并存。

## 4. Plugin / MCP / Connect — exists vs missing

### 已有（可复用，不要再做一套）

| Surface | Evidence |
|---------|----------|
| MCP **仅 stdio** | `mcp/client.py`：非 stdio 直接 `ValueError`；工具名 `mcp_{server}_{remote}`；`AgentV2._refresh_mcp_tools()` |
| MCP UI | OpenTUI `DialogMcp.tsx`；`/addmcp` `/list-mcp` `/remove-mcp`；Ink/HTTP 同类。Desktop **没有** MCP Connect UI |
| Plugin host B18 | `plugin/list\|install\|uninstall\|toggle`；`appserver/plugin_service.py`；toggle → `capabilities/set_enabled`；manifest 可带 skills/commands/stdio mcp；**禁止第二 invoke 路径** |
| Capabilities B11 | `capabilities/list\|get\|set_enabled\|invoke\|cancel\|audit`；kinds：`skill` \| `mcp` \| `browser` \| `cli`；browser 占位且不可 enable 成旁路 |
| 模型「Connect」 | `models/onboard` + `credentials/*`（API Key，不是第三方 OAuth） |
| 打开浏览器 | `file/open_external` 返回 `requires_user_action`；Desktop `shell.openExternal` + `isSafeExternalUrl()` |
| CLI-Hub | `appserver/cli_hub_service.py`；闭源无 SDK → reject，**不用 computer-use 补洞** |
| Git | `tools/git_tool.py` 本地 git CLI；无 GitHub REST/OAuth/`gh` 封装 |

Desktop/OpenTUI **未检出消费 `plugin/list`**：市场协议超前于产品 UI。

### 缺失（Grok Web 式 Connect）

- OAuth 2.1 / PKCE + 安全回调
- 远程 MCP（HTTP/SSE）与带 Authorization 的会话
- `connector/*` 状态机（connected / expired / disconnect）
- 与模型 API Key **分离** 的第三方 token vault
- GitHub/Canva 设置页「点连接 → 跳转 → 连上」
- VS Code extension 商店；`admin-backend` 无 plugin/OAuth controller

### 最安全插入点（确认后才实现）

```text
Desktop/OpenTUI
  → connector/*（appserver，新方法域，不塞进 session/prompt）
  → OAuth + secret store
  → 写入 mcpServers 或 PluginService 安装 connector pack
  → AgentV2._refresh_mcp_tools() / CapabilityService
  → 同一 session/prompt + ToolOrchestrator
```

不要：renderer 里第二套 tool loop；用未实现的 `browser` capability 冒充 Canva；只把 Connect 做进 `api_server` HTTP。

### Computer use

无产品级 mouse/a11y/browser-use agent。`vision` / `vision_capture` 是读屏，不是 GUI 操控。握手里 `browser: False`、`vision: False`。调研文档已冻结截图点击路线。

## 5. Maintainability / testability

| Hotspot | Evidence |
|---------|----------|
| God files | `core/agent_v2.py` ≈ 6850 行；`appserver/server.py` ≈ 3200 行；`api_server.py` ≈ 2250 行；另有 `core/graph.py`、`execution/tool_orchestrator.py`、`mcp/client.py`、`protocol/requests.py` 均 >1000 行 |
| 包级循环 | 静态 import 边：`core` ↔ `execution` / `planning` / `validation` / `recovery` / `synthesis`；`appserver` ↔ `core` |
| 测试直绑 AgentV2 | `tests/test_core/` 约 83 个文件 + 大量顶层测试 import `agent_v2` |
| 测试双轨 | `tests/unit|integration|contract|system|live` 新分层很小；legacy `tests/test_*.py` + `tests/test_*/` 占绝大多数（全树约 330 个 `test_*.py`） |
| 文档数字不可信 | `docs/modules/tests.md` 引用 `tests/stress_test/test_phase4_harness.py`，磁盘上不存在 |
| 覆盖空洞 | `synthesis/` 几乎空；`rag` / `history` / `lsp` / `scheduler` / `utils` 无 `tests/test_<mod>/`；`admin-backend` 零测试 |
| 双/三后端 | appserver + `api_server.py` + Java `admin-backend`（8080，与 Python 8765 无关） |
| 环形依赖 | `api_server.py` ↔ `api_server_stream.py` |
| 双 import | bare `core.*` vs `RxyCode.RxyCode1_1_0.core.*`；`tests/conftest.py` 用进程门禁兜底 |
| Session/Task 多套 | Python `TaskStatus` ≠ Flyway `CREATED/IN_PROGRESS` ≠ JPA `@Table` 名（`session` vs SQL `chat_session`） |
| 工作区噪音 | 未跟踪 `admin-backend/`、`pip/` 缓存、`desktop/*.json`（与 `frontend/desktop-app/` 并存） |

脆测试习惯：`asyncio.sleep` 竞态、system 层真进程、live opt-in、`api_server` 导入时改 stdout。

建议的后续重构优先级（仍须 ADR，本文件不授权动手）：

1. P0：测试经 `Session`/协议假面，而不是继续加厚对 `agent_v2` 的直依赖
2. P0：冻结 OpenTUI 默认只 stdio；Ink+SSE 标 legacy
3. P1：写清「全量绿」等于哪一条命令；分层 vs legacy
4. P1：`admin-backend` / `pip/` / 根目录 `desktop/*.json` 移出主产品心智
5. P2：拆 `agent_v2.py` 仅在有测试假面之后

## 6. ADR convention to match later

现有决策在 [`docs/decisions/`](../../../../decisions/)：

- 协议增量：`G-PROTOCOL-001` … `G-PROTOCOL-030`（YAML `protocol_change` 头）
- 上游复用：`G-UPSTREAM-B15.md`、`desktop-upstream-reuse.md`

架构治理新卡应 **另起 `ARCH-*` 前缀**，不要插入 `G-PROTOCOL` 序列（那是协议 diff 卡）。Connect 落地时再写一张 `G-PROTOCOL`（`connector/*` new_method）。

## 7. Open follow-ups

- `docs/modules/` Key Files 已抽查：核心表内文件大体存在；`tools.md` 未列出 `cli_bridge.py` / `task_tool.py` / `team_install_tool.py` 等后加工具。
- `docs/plans/` 是否重新纳入 git：属 `docs-dev-order` 决策，本文件不改 `.gitignore`。
- Computer use 调研结论应升为一张 `ARCH-*` ADR，避免只在 research 里「算数」。
- 能力地图见 [CAPABILITY-MAP.md](./CAPABILITY-MAP.md)；人审之前不写模块 spec、不改产品代码。
