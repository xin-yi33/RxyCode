# PhaseG-H1 · Desktop 基线与前端包边界

> 卡级基线冻结（PHASE-G-FRONTEND.md PhaseG-H1 + PHASE-G-DESKTOP.md G1）。
> 分支：`feat/phase-g-frontend`。协议变化：none。Grok：无。
> 本卡不重写 `frontend/`、不创建假壳、不改 `protocol/schema.json` / `appserver/`。

## 前置检查（真实结果）

| 路径 | 结果 |
|---|---|
| `frontend/desktop-app/` | 存在 |
| `frontend/protocol-client/` | 存在 |
| `protocol/schema.json` | 存在，`protocol_version` = **1.1.0** |
| `appserver/` | 存在（前端只读观察，后端 Owner） |
| `frontend/desktop-app/src/protocol/` | H1 新增握手占位；完整错误投影归 H2 |
| `frontend/desktop-app/tests/` | H1 新增基线测试目录 |

验收命令：

```powershell
Test-Path frontend\desktop-app
Test-Path frontend\protocol-client
python -m pytest tests/test_protocol -q
```

实测：`True` / `True` / `6 passed`（`tests/test_protocol`，2026-08-19）。

## 工具链（本机记录）

| 项 | 版本 |
|---|---|
| Node | v24.18.0 |
| npm | 11.16.0 |
| Bun | 1.3.14 |
| Python | 3.13.9 |
| Electron（desktop-app 安装） | 39.8.10 |
| Desktop package | `@rxycode/desktop-app` 1.2.10 |
| protocol-client | `@rxycode/protocol-client` 0.1.0（`file:../protocol-client`） |

## 进程与目录边界

```text
frontend/desktop-app/src/main/index.ts     Electron 入口；spawn/监督 appserver；IPC allowlist
frontend/desktop-app/src/preload/index.ts  contextBridge `window.api` 白名单
frontend/desktop-app/src/platform/         Renderer 唯一 preload 适配层
frontend/desktop-app/src/renderer/         React UI；经 protocol-client 发 JSON-RPC
frontend/desktop-app/src/protocol/         H1 握手占位（H2 扩展）
frontend/protocol-client/src/client.ts     JSON-RPC 客户端实现
frontend/protocol-client/src/generated/    由 schema.json generate，禁止当 schema 真相
protocol/schema.json                       后端唯一 schema Owner（前端只读）
```

`BrowserWindow.webPreferences`（已存在，H1 记录并测试锁定）：

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`

Renderer 通信路径（DC-J1）：

```text
Renderer ProtocolClient
  → platform.sendLine (preload allowlist)
  → Main AppServerManager stdio
  → appserver JSON-RPC
```

生产 Renderer 不 import Python、不读数据库、不 `fetch`/`axios` 打后端 HTTP。Settings 里的 `https://api.example.com/v1` 仅为模型 base_url 占位文案，不是客户端直连。

## 生成类型来源

| 项 | 值 |
|---|---|
| Schema | `protocol/schema.json` `protocol_version` 1.1.0（与 `protocol/version.py` `PROTOCOL_VERSION` 一致） |
| 生成命令 | `frontend/protocol-client`：`bun run generate` |
| 生成产物 | `frontend/protocol-client/src/generated/types.ts`、`subagent-types.ts` |
| 生成产物来源 commit | `af0adee0d43ae1b239990383a24a3ee491d2f96e`（`feat(protocol): expose team list groups install and set_active`） |
| OpenTUI 共享 | `frontend/opentui-app` 同样依赖 `@rxycode/protocol-client` `file:../protocol-client`，与 Desktop 共享生成类型 |
| 前端规则 | 禁止提交 generate 差异；H1 未运行 generate |

## 启动 / 测试 / 构建命令

```powershell
cd frontend\desktop-app
npm run dev
npm run typecheck
npm run test -- --test-name-pattern H1
npm run build
npm run smoke
```

H1 本卡命令（前端）：

```powershell
cd frontend\protocol-client
npm test
cd ..\desktop-app
npm run test -- tests/h1-baseline.test.mts
```

## 可复用 / 需要补齐 / 禁止重写

### 可复用（Phase 4 壳，H1 不改结构）

- `src/main/`（appserver 监督、crash/update、外部 URL、workspace dialog）
- `src/preload/index.ts` IPC allowlist
- `src/platform/index.mts` + Renderer `ProtocolClient`
- `src/renderer/` 现有会话/审批/设置 UI
- `@rxycode/protocol-client` 传输与生成类型
- `electron-builder.yml` 打包入口（H13 再验收）

### 需要补齐（后续 H 卡，不在 H1 伪造完成）

| 缺口 | 归属 |
|---|---|
| `src/protocol/` 完整 initialize 错误投影、capability UI 门控 | H2 |
| 孤儿回收 20 次 / 未知 IPC 拒绝的进程级补强 | H3 |
| `src/features/projects/`、`src/features/workspaces/` | H4 |
| `src/features/threads/`、Child Tree、软删除投影 | H5 |
| `src/features/timeline/`、Item 虚拟滚动 | H6 |
| `src/features/execution/` | H7 |
| `src/features/approvals/` 权限中心（现有 ApprovalModal 为 Phase4 基础） | H8 |
| `src/features/review/`、`src/features/git/` | H9 |
| `src/features/files/`、`preview/`、`worktrees/` | H10 |
| Settings 8 分区骨架、MCP/Skills 面板 | H11 / H16 |
| 通知/恢复/a11y 视觉系统 | H12 / H17 |
| locale 入包、三端 smoke | H13 / H14 |
| 多 Agent 契约预留、CLI 画廊 | H18 / H19 |

README 已诚实记录：Desktop 尚未消费 Phase B `child_session/*`（OpenTUI 已有）。H1 不把该缺口标成通过。

### 禁止重写

- `protocol/schema.json`、`protocol/*.py`
- `appserver/`、`core/`、后端 `tests/test_*.py`
- 整棵 `frontend/` 目录重命名或第二套状态机
- 用 mock HTTP / 假壳让 H2–H13 提前打钩

## 握手占位（G1 第 5 项）

- `src/protocol/handshakePlaceholder.ts`：`matchProtocolVersion`、`isDeclaredCapability`
- `tests/h1-baseline.test.mts`：目录边界、schema 1.1.0、webPreferences、Renderer 隔离、DC-J3
- `frontend/protocol-client/src/handshake.placeholder.test.ts`：生成类型消费 InitializeRequest

未声明能力不得显示为可用；版本不一致返回 `protocol_mismatch`。超时/断开/overload 等 typed 状态是 H2。

## 已知限制

- H1 不跑完整 `python -m pytest -q`（开工自检全量门，非本卡验收命令）。
- `tests/test_protocol` 有 Windows 管道 UTF-8 警告，6 测试仍通过；属后端线程警告，前端不改 Python。
- `docs/plans/` 被 `.gitignore` 忽略；本基线与交接包入库 `frontend/desktop-app/docs/handoffs/`。开发文档勾选在 luna 通过后写入 `PHASE-G-FRONTEND.md`（本地）并镜像到本目录验收记录。
