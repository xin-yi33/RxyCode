# Desktop 上游复用冻结 — PhaseG-B1 / DR1

**卡号**: PhaseG-B1（对应完整 G `G1` + 附录 D `DR1`）
**冻结日期**: 2026-08-19
**开发分支**: `feat/phase-g-backend`（基线 `40b73ec`）
**协议变化**: none
**Owner**: 本卡施工者（Grok 4.6，PHASE-M OV1 覆盖主写模型；能力边界仍遵守 DC-F1–DC-F8）

本文件是 PHASE-G-DESKTOP 附录 D C.5 规定的唯一登记处。字段按模板填写；不适用写 `none`。
子代理 OpenCode 复用不在本文件重开：见 `docs/decisions/upstream-reuse.md`（Phase D / 当时编号 B1–B14，与 PhaseG-B* 不是同一组卡）。

---

## 决策记录（C.5 模板）

```yaml
decision_id: D-UPSTREAM-001
status: accepted
upstream:
  project: codex
  repository: https://github.com/openai/codex
  reference_url: https://github.com/openai/codex/tree/main/codex-rs/app-server
  commit: "f5a3dc55404ddc066a4e4a65602fee166ecc46b3"
  license: Apache-2.0
  license_verified_at: "2026-08-19"
  license_evidence: "GET https://raw.githubusercontent.com/openai/codex/f5a3dc55404ddc066a4e4a65602fee166ecc46b3/LICENSE → Apache License Version 2.0, January 2004 (10926 bytes). Not main/HEAD."
capability: bidirectional-app-server-thread-events
reuse_mode: protocol-alignment
reused:
  - "initialize / notification / server-request 三方向边界（对照公开 App Server README，不 vendor Rust）"
  - "stdout = JSON-RPC/JSONL 协议，stderr = 日志"
  - "capability handshake 与错误可机器断言的方向（形状对齐，字段由 RxyCode schema 拥有）"
  - "thread/turn/item、approval、replay 的后续语义对齐目标（本卡只冻结，不改协议）"
adapter_files:
  - "protocol/schema.json"
  - "protocol/schema.py"
  - "protocol/version.py"
  - "protocol/requests.py"
  - "protocol/notifications.py"
  - "protocol/server_requests.py"
  - "frontend/protocol-client/src/generated/types.ts"
  - "appserver/__main__.py"
  - "appserver/server.py"
  - "appserver/jsonrpc.py"
adaptation_reason:
  - "Codex App Server 是 Rust（codex-rs/app-server）；RxyCode appserver 是已交付的 Python stdio JSON-RPC（Desktop 1.2.10 已 spawn python -m appserver）"
  - "语言/运行时不兼容，直接 dependency/fork/vendor Rust 会再造第二套 Runtime，违反 DC-F6 与附录 D C.3.2"
  - "RxyCode 已有 Phase 3 resolver、Phase D ChildSession、Phase F team/*；这些必须留在本仓库，不能写进不可升级的上游核心"
preserved_semantics:
  - "双向 request / notification / server-request 相关"
  - "stdout 只出协议行；日志不进 stdout"
  - "schema.json 是跨语言唯一契约（DC-F1）"
  - "Renderer 不 import Python、不直连后端 HTTP（DC-A1）"
rxycode_extensions:
  - "x-rxycode-capabilities"
  - "x-rxycode-audit"
  - "x-rxycode-child-session"
  - "x-rxycode-model-summary"
  - "protocol.version.PROTOCOL_VERSION = 1.1.0"
  - "既有 session/* 方法族（Phase 4 已冻结，本卡不改语义）"
verification:
  commands:
    - "python -m pytest tests/test_protocol -q"
    - "python -m pytest tests/test_appserver -q"
    - "cd frontend\\protocol-client; bun test"
  evidence: "PhaseG-B1 契约测试 tests/test_protocol/test_b1_baseline.py"
rollback: "删除或回退本文件与 tests/test_protocol/test_b1_baseline.py；不回滚 schema/appserver（本卡未改协议实现）。Codex 升级只更新本文件 commit 字段并重跑 DR1 命令。"
owner: composer-2.5
reviewers:
  - "desktop-contract-review"
  - "security-review"
```

### 第二条：OpenCode（仅交叉引用，不重审 Phase D）

```yaml
decision_id: D-UPSTREAM-002
status: accepted
upstream:
  project: opencode
  repository: https://github.com/anomalyco/opencode
  reference_url: https://opencode.ai/docs/agents
  commit: "fe82a1b6ca4f535beb973b0867017e3f639f85ed"
  current_head_observed_2026-08-19: "da4730e4a41dcbb2cb2d907dd2b06ac481b8f962"
  license: MIT
capability: isolated-subagent-session
reuse_mode: semantic-port
reused:
  - "Phase D Child Session / permission / mention 语义（已在 docs/decisions/upstream-reuse.md 冻结）"
adapter_files:
  - "docs/decisions/upstream-reuse.md"
  - "appserver/subagent_routes.py"
  - "protocol/subagents.py"
adaptation_reason:
  - "Desktop 不另造 Child Runtime；B5 只消费 Phase D 已冻结契约"
preserved_semantics:
  - "parent_session_id / root_session_id / budget / lease / audit"
rxycode_extensions:
  - "x-rxycode-budget"
  - "x-rxycode-workspace-lease"
verification:
  commands:
    - "python -m pytest tests/test_subagents -q"
  evidence: "docs/decisions/upstream-reuse.md"
rollback: "none（本卡不修改 Phase D 产物）"
owner: composer-2.5
reviewers:
  - "desktop-contract-review"
  - "security-review"
```

---

## 1. 实测基线（B1 操作步骤）

| 检查项 | 结果 | 路径 / 证据 |
|---|---|---|
| App Server 入口 | 存在 | `appserver/__main__.py` → `python -m appserver` → `AppServer.run()` |
| stdout 协议 | 已确认 | `appserver/jsonrpc.py` `write_message_sync` 只写 `sys.stdout` 一行 JSON |
| stderr 日志 | 已确认 | `appserver/__main__.py` `_configure_logging` → `stream=sys.stderr` |
| 协议版本 | `1.1.0` | `protocol/version.py` `PROTOCOL_VERSION` 与 `protocol/schema.json` `protocol_version` 一致 |
| schema 唯一来源 | 已确认 | Python 模型 → `python -m protocol.schema > protocol/schema.json`；`tests/test_protocol_schema.py::test_exported_schema_matches_committed_file` 冻结 |
| 生成类型流程 | 已确认 | `frontend/protocol-client`：`bun run generate`（`json2ts -i ../../protocol/schema.json`） |
| Phase 3 resolver | 已确认 | `config/model_limits.py` `resolve_output_limit`；未知模型 `UNKNOWN_MODEL_FALLBACK = 32768`，不是 8192 |
| Phase F 消费面 | 已确认 | `appserver/team_routes.py` + `protocol` `team/*` + `tests/test_protocol/test_team_rpc.py`（F18b） |
| Desktop 壳 | 已确认 | `frontend/desktop-app` `@rxycode/desktop-app@1.2.10`；Main spawn `python -m appserver` |
| protocol-client 边界 | 已确认 | Renderer / platform 经 `@rxycode/protocol-client`；Main `appserver.ts` 只转发 NDJSON，不自造 request id |
| BrowserWindow 安全 | 已确认 | `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true` |
| `appserver/handlers/` | 不得创建 | PHASE-M M2：映射到 `appserver/<x>_routes.py` |
| `packaging/` | 缺失 | B13 产物，本卡不伪造 |
| `tests/test_recovery/` | 缺失 | B12 产物，本卡不创建空目录 |

### 启动与版本（G1）

```text
Desktop:   cd frontend/desktop-app ; npm run dev
Build:     npm run build / npm run build:win
Appserver: python -m appserver
Python:    3.13.9（本机开工自检）
Generate:  cd frontend/protocol-client ; bun run generate
```

### 当前 initialize 实码（只记录，本卡不改）

- 请求：`InitializeRequest`（`client_name` / `client_version` / `protocol_version` / `capabilities`）
- 响应：`protocol_version`、`server_name=rxycode-appserver`、布尔 `capabilities.{sessions,approval,models,credentials}`
- 版本不一致：只 warning，仍 `_initialized = True`（B2 必须改成可机器断言的拒绝，本卡禁止动）
- 无 `initialized` notification、无 `modelProviders`、无 `permissionProfiles`、无 Phase 3 `ModelSummary`（B2 / B10）

### 命名差（冻结，不在本卡改语义）

完整 G 文档示例用 `thread/start`、`turn/start`。仓库既有方法是 `session/new`、`session/prompt`、`session/events` 等。
DC-F1：不得删除或改写已有 `session/*` 语义。后续卡若引入 `thread/*`，必须走 `new_method` 协议变更单，并做 session↔thread 适配，禁止复用旧字段表达新语义。

---

## 2. G1–G16 / PhaseG-B* 复用模式（DR1 步骤 2）

| 完整 G 卡 | 后端卡 | Codex 对照 | reuse_mode | 本卡裁定 |
|---|---|---|---|---|
| G1 基线冻结 | B1 | App Server 进程边界 | protocol-alignment | 本卡完成冻结 |
| G2 handshake | B2 | initialize / capabilities / errors | protocol-alignment | 待 B2；禁止 vendor |
| G3 进程监督 | B3 | app-server 生命周期 | protocol-alignment | 已有 spawn/kill-tree；B3 补契约 |
| G4 Project/Workspace | B4 | 无强制 Codex 源码 | none | 路径安全自研 |
| G5 Thread/Turn/Item | B5 | thread-turn-item | semantic-port | 映射到既有 session store，不另造 Runtime |
| G6 时间线/流式 Item | 无后端卡（前端 H6） | 无强制 Codex 源码 | none | **不适用后端实现**。协议变化 none；只消费 B5 Item 事件，禁止 Renderer 自造 Item 真相 |
| G7 Tool/Command | B6 | tool/event 时序 | semantic-port | 复用既有 tool runner |
| G8 Approval | B7 | server-request approval | semantic-port | 已有 `appserver/approval.py` |
| G9 Review/Git | B8 | review/diff | semantic-port | 无 Codex 源码可 dependency |
| G10 File Preview / External Editor | B9 | none | none | 自研 + workspace 边界 |
| G11 Worktree / 执行环境 | B9 | none | none | 与 G10 同属 B9；不另造 Runtime |
| G12 Settings/Model | B10 | none（上限走 Phase 3） | none | 禁止 Desktop 写死 8192 |
| G13 Skills/MCP | B11 | none | none | 走 capability，不旁路 |
| G14 恢复/replay | B12 | reconnect/cursor | semantic-port | `tests/test_recovery` 尚未建 |
| G15 视觉/a11y | 无后端卡（前端 H 视觉卡） | 无强制 Codex 源码 | none | **不适用后端实现**。协议变化 none；禁止把截图像素写成业务/权限逻辑 |
| G16 打包 | B13 | none | none | `packaging/` 尚未建 |
| P3 B14 CLI-Hub | B14 | 非 Codex；CLI-Anything Apache-2.0 | semantic-port | 主链出口后。禁止 `cli:` 进 `tools/registry.py`（PHASE-N HN2） |
| P3 B15 HARNESS 技能 | B15 | CLI-Anything HARNESS.md Apache-2.0 + OpenCode 参考 | vendor + semantic-port | 主链出口后。挂起条件：Phase B 缓存未落地 → `BLOCKED_PREREQUISITE` |
| P3 B16 定时任务 | B16 | 无 Codex 源码 | none | 主链出口后。扩展已有 `scheduler/`，应用层 asyncio，不依赖系统 cron |
| P3 B17 回收站 | B17 | 无 Codex 源码 | none | 主链出口后。仓库已有 `session/trash|restore|purge`，B17 只对齐 `deleted_at`/`thread/purge` 语义，禁止另造删除状态机 |
| P3 B18 插件市场 | B18 | Codex plugins 形态 + SKILL.md | semantic-port | 主链出口后。`plugin/toggle` **不是** new_method（PHASE-K KC6 → `capability/set`） |

禁止在任何 B 卡：

- vendor / 复制 Codex 商标、图标、私有认证、未公开服务；
- 在 Renderer 重建 app-server、权限、resolver、预算；
- 新建 `appserver/handlers/`；
- 用临时 HTTP / 内存字典代替 `appserver` + `schema.json`；
- 把 `cli:<软件名>` 注册进 LLM 工具 schema。

DR1 原文「每张 F 卡」在合并后对应完整 G 的 **G1–G16**（不是 PHASE-F 的 F1–F18）。上表 16 行已逐张给出 Codex 对照或明确「不适用」。PHASE-F 专家团不是 Desktop 上游复用对象；B1 只确认 `team/*` 消费面已存在。

前端拆分卡 H1–H13 不产生第二套复用决策：H 卡只消费本文件 + 对应 B 卡协议。H6 对齐 G6（none），H 视觉部分对齐 G15（none）。

---

## 2.1 既有契约测试盘点（DR1 步骤 6 / 完成判据 4）

B1 **不新建** Thread/Turn/Item 状态机，也不 mock 不存在的 `tests/test_threads`。下列是仓库里已经能断言的数据流/错误流，以及明确缺口。

| 对象 | 现有契约（真实测试/模块，非 mock） | 错误流 | 缺口与归属 |
|---|---|---|---|
| Thread（现名 Session） | `tests/test_appserver/test_session_model.py`、`test_desktop_task_store.py`、`session/new` 在 `server.py` | 缺 `workspace_root` → `-32602` | 文档 `thread/*` 方法未建 → **B5**；`tests/test_threads/` 不存在，本卡不创建空目录 |
| Turn | `session/prompt` / `session/interrupt`：`tests/test_appserver/test_stdio_integration.py`、`test_prompt_emit_watchdog.py` | 未 initialize → `-32002` | queued/waiting/approval 完整状态机 → **B5** |
| Item | `protocol/notifications.py` 进入 `schema.json`；`tests/test_protocol_schema.py` 冻结 union | schema 漂移会被 freeze 测挂掉 | Item 分页/持久化协议 → **B5** |
| Event | `appserver/eventbus.py`；`tests/test_appserver/test_protocol_tui_recovery.py`；通知模型在 schema | replay cursor 部分存在于 `session/events` | 完整 `event_id`/`sequence`/乱序去重 → **B12** |
| Approval | `appserver/approval.py`；`tests/test_appserver/test_approval.py`；根目录 `tests/test_approval.py`；`protocol/server_requests.py` | 无 UI 时 broker 仍可拒绝（既有 safety 测试） | auto-review / 作用域过期 → **B7** |
| Capability | `initialize` 返回布尔 `sessions/approval/models/credentials`；`InitializeRequest` 在 schema | 版本不一致目前只 warning | 必须拒绝不兼容版本 + §3.5 能力列表 + modelProviders → **B2** |

本卡新增的 `tests/test_protocol/test_b1_baseline.py` 只冻结「这些契约文件仍在、缺口目录仍不得空造」。

**DR1 完成判据 4 状态：未完成。** B1 只做冻结与缺口登记，**不得**把上表当成 Thread/Turn/Item/Event/Approval/Capability 已有完整契约。完整数据流/错误流由后续卡补齐：Capability/handshake → B2；Thread/Turn/Item → B5；Approval 扩展 → B7；Event replay → B12。后续卡未合入前，该项保持未完成。

---

## 3. 可复用 / 需要补齐 / 禁止重写

### 可复用（本卡冻结为唯一真相）

| 能力 | 位置 |
|---|---|
| stdio JSON-RPC appserver | `appserver/` |
| schema + 生成类型 | `protocol/schema.json` → `frontend/protocol-client` |
| Phase 3 max token | `config/model_limits.py` |
| Phase D Child | `appserver/subagent_routes.py` + `core/subagents/` |
| Phase F team RPC | `appserver/team_routes.py` |
| Approval / Question | `appserver/approval.py`、`appserver/question.py` |
| Desktop 壳与进程监督雏形 | `frontend/desktop-app/src/main/appserver.ts` |
| 事件总线雏形 | `appserver/eventbus.py` |

### 需要补齐（后续卡，本卡不实现）

| 缺口 | 归属 |
|---|---|
| 版本不兼容必须拒绝 + 稳定 error code | B2 |
| capability / modelProviders / permissionProfiles / ModelSummary | B2 / B10 |
| `initialized` notification | B2 |
| 启动失败 / 20 次启停 / 未完成任务不伪造完成 | B3 |
| Project/Workspace 路径 canonicalize | B4 |
| Thread/Turn/Item 与 Child 隔离契约 + H5 fixture | B5 |
| Tool/Command 终态与后台任务 | B6 |
| Permission Center 与 auto-review | B7 |
| Review / checkpoint / git hunk | B8 |
| File preview / worktree | B9 |
| replay / orphan / `recovery_required` | B12 |
| runtime 打包 | B13 |

### 禁止重写

- `core/agent_v2.py`（Phase C 禁碰清单）
- Phase 3 resolver（Desktop 只消费摘要）
- Phase D ChildSessionManager
- 把 `protocol-client` 生成类型当反向 schema
- Codex Rust app-server 整树 vendor

---

## 4. 许可证与回滚

| 上游 | 锁定 commit | 许可证 | 本卡是否复制源码 |
|---|---|---|---|
| openai/codex | `f5a3dc55404ddc066a4e4a65602fee166ecc46b3` | Apache-2.0（2026-08-19 对**该 commit** 的 `LICENSE` 核实，不是 main 浮动头：`https://raw.githubusercontent.com/openai/codex/f5a3dc55404ddc066a4e4a65602fee166ecc46b3/LICENSE`，10926 bytes，文首 Apache License Version 2.0, January 2004） | 否。仅协议对齐，无 vendor 目录 |
| anomalyco/opencode | `fe82a1b6ca4f535beb973b0867017e3f639f85ed` | MIT | 否（Phase D 已 semantic-port） |

未复制源码，故无 NOTICE 入库项。若后续卡改为 vendor，必须先改本文件 `reuse_mode` 并附 LICENSE/NOTICE，否则 `BLOCKED_LICENSE_REVIEW`。

回滚：`git revert` 本卡 commit。不触及 schema 语义。

---

## 5. 前端交接（B1 → H1）

- 包边界：Desktop 只经 `@rxycode/protocol-client` 连 appserver。
- schema 现状：`protocol_version = 1.1.0`，本卡无字段增删。
- 生成命令：`cd frontend/protocol-client && bun run generate`（本卡未跑，因 schema 未变）。
- 已知限制：initialize 能力面与完整 G §5.1 示例尚未对齐 → 等 B2。
