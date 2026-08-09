# Phase D-F · RxyCode Desktop 前端开发执行文档

> **文档定位**：本文是 [`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) 的前端执行拆分文档，不替换完整 D 文档，也不删除其中的产品定义、协议示例、任务卡验收和完整出口标准。完整 D 文档是公共基线；本文把前端和 Electron Host 的实现责任拆出来，使前端开发者可以独立施工、测试和交接。
>
> **产品名称**：RxyCode Desktop。本文保持完整 D 文档中对 Codex 工作台的交互目标、OpenCode/Codex 上游复用边界、Phase 3 模型上限摘要和 Phase A/B/C 公共契约不变。
>
> **前置条件**：主计划 Phase 0/1/2/3/4 + Phase A/B/C 公共契约已冻结；Phase 4 的 Electron 壳、`frontend/protocol-client/`、`appserver/` 和 `protocol/schema.json` 是否真实存在必须以工作区检查为准。缺失时只能输出 `BLOCKED_PREREQUISITE`，不能用 mock 或临时 HTTP 绕过。
>
> **主文档关系**：完整功能、示例代码和总体验收以 [`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) 为唯一基线；本文只增加前端 owner、前端文件边界、前端任务卡和前后端交接要求。
>
> **基线日期**：2026-08-05　**建议工时**：与完整 Phase D 的 12–16 周总估算并行拆分，不得将两份文档的工时简单相加　**任务卡**：PhaseD-F1–PhaseD-F13

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必须先读) | 模型分工、施工回路、硬约束和协作方式 |
| [§1 拆分真相与文件边界](#1-拆分真相与文件边界) | 哪些代码由前端写、哪些代码禁止前端碰 |
| [§2 前端架构与协议消费](#2-前端架构与协议消费) | Electron、protocol-client、Renderer 和状态投影 |
| [§3 公共接口与交接协议](#3-公共接口与交接协议) | 前端消费的稳定接口和后端交接格式 |
| [§4 前端任务卡](#4-前端任务卡) | PhaseD-F1–F13 具体施工顺序 |
| [§5 前端安全与体验](#5-前端安全与体验) | preload、权限呈现、secret、可访问性和视觉辅助 |
| [§6 前端测试与验收](#6-前端测试与验收) | 单元、组件、进程、E2E、视觉和机械门 |
| [§7 前端出口与后端合并](#7-前端出口与后端合并) | 什么条件下前端可以交付给完整 D |
| 附录 A | 原 D 卡映射、命令继承和交接模板 |

---

## §0 执行手册（必须先读）

### 0.1 本文解决什么问题

完整 D 文档把 Desktop 视为一个整体，但前后端分开开发时必须先冻结边界：

```text
后端：协议 schema、appserver、Session/Thread 真相、权限、工具、Git、恢复
前端：Electron Main、preload、protocol-client、Reducer、Renderer、视觉、打包入口
共享：只通过 protocol/schema.json、生成类型、契约测试和 capability handshake 交接
```

本文不复制一份后端业务逻辑。前端开发者必须先读完整 D 的 §0–§11、附录 A–C；其中的 JSON、状态机、Review、checkpoint、Child Tree、Codex App Server 复用规则和验收要求保持原文不变。

### 0.2 模型分工（硬约束）

| 模型 | 负责 | 禁止 |
|---|---|---|
| **Composer 2.5** | **主写全部前端代码**：Electron Main、preload、React、TypeScript、protocol-client、Reducer、组件、组件测试、E2E、打包和最终合并 | 不得让 Grok 独立实现 Desktop；不得通过前端绕过 appserver、权限或模型 resolver |
| **Grok 4.5** | 仅做卡内标注的多模态辅助：启动 dev server、截屏、视觉回归、图片/文件预览、布局和设计稿对照 | 不写 Python；不改 `protocol/schema.json`；不独立修改前端公共状态模型；不单独提交主链 |
| **Sonnet 5（可选）** | 对 F2/F5/F6/F8/F9/F10/F12 的 diff 做状态、权限旁路、IPC 泄漏和可访问性预审 | 不替代 Composer 实现，不以预审结果替代测试 |
| **后端协作者** | 提供已冻结协议、生成类型、appserver 启动/错误/事件样例和真实验收输出 | 不直接覆盖前端公共组件；协议变更必须走后端协议变更单 |
| **人** | 决定交互取舍、审批呈现、是否接受视觉/无障碍问题和最终合并 | 不用“截图像”替代协议和自动化验收 |

### 0.3 开工前自检

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
git status --short
git branch --show-current
python --version
Test-Path frontend\desktop-app
Test-Path frontend\protocol-client
Test-Path protocol\schema.json
python -m pytest -q
```

`frontend/desktop-app` 不存在时，F1 只能记录缺失清单并输出 `BLOCKED_PREREQUISITE`；不能创建临时目录后把 F2–F13 标记为通过。

### 0.4 每张前端卡的固定回路

```text
LOCATE → READ 完整 D 对应卡 → WRITE → TYPECHECK/LINT
→ UNIT/COMPONENT TEST → PROCESS/E2E → VISUAL（如卡内要求）
→ CHECK DIFF → HANDOFF → COMMIT
```

每张卡必须留下：

- 前端改动文件清单；
- 消费的 schema、method、event、capability 版本；
- 生成类型的 commit 或来源；
- 启动、测试、构建和视觉验收命令；
- 真实输出、已知限制、回滚 commit；
- 后端交接所需的最小复现步骤。

### 0.5 前端继承的八条硬规则

| 编号 | 规则 | 违反后果 |
|---|---|---|
| DC-F1 | Renderer 只能经 `frontend/protocol-client` 与 appserver 通信；禁止 import Python、读取数据库、直接调用后端 HTTP | 前端与 CLI/TUI/LinkAgent 分叉 |
| DC-F2 | UI 只投影后端状态，不复制 Agent 路由、工具注册、权限判断、max token resolver 或审计规则 | 多端语义漂移 |
| DC-F3 | 外部能力只能从 capability handshake 进入 UI；未声明能力不得显示为可用 | UI 猜测后端能力 |
| DC-F4 | 每个异步 UI 操作都必须显示 started/progress/completed/failed/cancelled 或 waiting 状态 | loading 假完成、重连丢状态 |
| DC-F5 | `ask`、allow、deny、auto-review 的按钮只提交后端请求；前端不能自行放行 | 权限旁路 |
| DC-F6 | Thread/Turn/Item、Review、Approval、Child Tree 均按 `event_id`/`sequence`/`cursor` 做幂等投影 | 重复事件和乱序破坏历史 |
| DC-F7 | preload 使用 `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`；IPC 只暴露 allowlist API | Renderer 获得 Node/Key/进程权限 |
| DC-F8 | Grok 截图不能替代组件、协议、E2E 和构建测试 | 视觉通过但功能不可靠 |

### 0.6 明确不做的事情

本前端文档不做：

- 在 React/TypeScript 内实现 Agent、Provider、Tool Registry、PermissionPolicy、Git 真相或模型上限解析；
- 创建第二套 Thread/Turn/Item/Child Session 状态机；
- 用临时 HTTP、mock appserver 或浏览器本地状态代替正式协议；
- 把 API Key、完整环境变量、完整 prompt 或原始工具输出放进持久化 Renderer 状态；
- 直接复制 Codex/OpenCode 品牌、图标、私有实现；
- 让 Grok 4.5 独立提交 Desktop 主链。

---

## §1 拆分真相与文件边界

### 1.1 两份执行文档和一份公共基线

```text
PHASE-D-RXYCODE-DESKTOP.md
  = 完整产品、协议、示例、D1–D16、完整安全/测试/出口标准的公共基线

PHASE-D-FRONTEND-RXYCODE-DESKTOP.md
  = Electron/TypeScript/React/protocol-client/视觉/前端测试的施工责任

PHASE-D-BACKEND-RXYCODE-DESKTOP.md
  = appserver/schema/Session/权限/工具/Git/恢复/后端测试的施工责任
```

完整 D 的原始示例代码不复制成变体。前端只引用并按原文消费：初始化握手、事件 JSON、Review 请求、checkpoint、capability 列表和状态恢复流程必须以完整 D §5 为准。

### 1.2 文件 ownership 白名单

| 范围 | 前端 Owner | 后端 Owner | 冲突处理 |
|---|---|---|---|
| `frontend/desktop-app/src/renderer/` | 可写 | 只读 | 后端不得直接改 Renderer |
| `frontend/desktop-app/src/main/`、`preload/`、`platform/` | 可写 | 提供进程契约 | IPC schema 变化先记录再改 |
| `frontend/protocol-client/` | 可写 | 提供 schema/样例 | 不得把 schema 真相放进 TypeScript |
| `protocol/schema.json`、`protocol/*.py` | 只读消费 | 唯一 Owner | 前端需变更时提交协议变更请求 |
| `appserver/`、后端 core、数据库 | 禁止 | 唯一 Owner | 前端不能临时改后端修 UI |
| `tests/test_*` Python | 只读观察 | 主要 Owner | 前端通过契约复现问题，不直接重写后端测试 |
| `frontend/desktop-app/tests/`、`frontend/protocol-client/tests/` | 可写 | 可提供 fixture | fixture 变化需附协议版本 |
| `packaging/`、CI | 可写前端构建部分 | 可写 runtime 部分 | 文件级分工，禁止同一脚本无记录覆盖 |

### 1.3 共享文件修改协议

前端需要协议变化时，必须提交以下内容给后端：

```yaml
protocol_change_request:
  request_id: D-F-PROTOCOL-001
  consumer: frontend/desktop-app
  current_schema_version: "<version>"
  requested_method_or_event: "<method/event>"
  reason: "<user-visible requirement>"
  backwards_compatibility: "<yes/no + evidence>"
  generated_types_update: required
  contract_tests: required
  owner: composer-2.5
```

后端未冻结 schema、生成类型和契约测试之前，前端只能使用现有字段，不得在组件里声明临时字段。

---

## §2 前端架构与协议消费

### 2.1 进程边界

```text
Electron Main
  ├─ 启动/监督 appserver
  ├─ 管理窗口、日志、外部编辑器和安全存储入口
  └─ 通过最小 preload API 暴露受控能力
        ↓
preload allowlist
        ↓
Renderer
  ├─ protocol-client transport
  ├─ typed event reducer
  ├─ Thread/Turn/Item/Child Tree projection
  ├─ Approval/Review/File/Settings views
  └─ Grok 只验证视觉状态
        ↕ JSON-RPC / JSONL
appserver / backend truth
```

前端不能把 Main 的权限提升成 Renderer 的任意 Node 权限；不能把后端事件改写成只保留最后一条文本。

### 2.2 前端必须消费的公共对象

| 对象 | 前端责任 | 不允许的推断 |
|---|---|---|
| `Thread` / `Session` | 列表、恢复、分叉、归档、parent/child 导航 | 自己创建后端不存在的 Thread |
| `Turn` | queued/running/waiting/completed/failed/cancelled 投影 | 用 loading 布尔值代替状态机 |
| `Item` | message/tool/command/change/approval/error 增量渲染 | 把所有 Item 拼成纯文本 |
| `ChildSessionEvent` | 展示 Agent、触发方式、状态、预算、权限和失败原因 | 前端自行调度 Child |
| `Review` / `Finding` | 展示 evidence、diff hash、stale、comment | 重新计算审查结论 |
| `Approval` | 显示范围并提交决定 | 前端直接改 PermissionPolicy |
| `ModelSummary` | 展示 provider/model/max output 来源 | 前端从 model id 猜 max token |
| `Capability` | 控制功能入口和降级文案 | 字段存在就假设能力已启用 |

### 2.3 示例代码继承规则

完整 D §5.1–§5.8 中的以下示例必须原样作为前端契约测试 fixture 或文档引用，不得改写成前端专属协议：

- `initialize` / `initialized` 握手树；
- `event_id`、`sequence`、`cursor` 事件 JSON；
- `review/start` 请求和 Review response；
- `checkpoint/list/read/restore` 与 Git hunk 操作；
- capability 列表和恢复流程。

前端可以增加类型注释、fixture 名和渲染测试，但不得改变字段名、方向、终态或错误语义。

---

## §3 公共接口与交接协议

### 3.1 Client transport 接口

```ts
type ClientTransport = {
  initialize(params: InitializeParams): Promise<InitializeResult>;
  request<T>(method: string, params: unknown): Promise<T>;
  subscribe(listener: (event: ProtocolEvent) => void): () => void;
  cancel(requestId: string): Promise<void>;
  close(reason: string): Promise<void>;
};
```

这段接口只表达前端消费边界；后端的业务方法、权限和模型上限仍由公共 schema/服务实现，不能在 TypeScript 中复制。

### 3.2 Reducer 规则

```text
event received
  → validate schema
  → reject unknown/invalid event safely
  → dedupe by event_id
  → check sequence/cursor
  → request replay on gap
  → reduce into projection
  → render status and audit link
```

任何不符合 schema 的事件必须进入可诊断错误态，不能被静默塞入 `message.delta`。

### 3.3 后端交接包

后端每次交接必须提供：

```text
协议版本 / capability snapshot / generated types commit
启动命令 / stdout-stderr 约束 / fixture 路径
成功样例 / 拒绝样例 / 超时样例 / 取消样例 / 崩溃恢复样例
已知限制 / 兼容窗口 / 可回滚 commit
```

前端每次回交必须提供：

```text
消费的协议版本 / UI 状态覆盖表 / 最小复现步骤
组件或 E2E 测试 / typecheck 输出 / 视觉截图（如适用）
IPC contract test / secret 脱敏检查 / 可回滚 commit
```

---

## §4 前端任务卡

### 4.0 卡级施工格式（Composer 必须遵守）

每张 F 卡必须冻结：

```text
优先级 / 工时 / 依赖 / owner
涉及文件白名单
消费的 schema / method / event / capability
是否产生协议变更（默认 none）
验收命令与预期结果
完成判据 checkbox
Grok 视觉辅助范围（没有就写“无”）
后端交接包和回滚 commit
```

每张 F 卡共同继承完整 D §6.0 的四项完成判据；完整 D 对应 D 卡的验收要求不得被本文缩减。

### PhaseD-F1 · Desktop 基线与前端包边界

`P0` / 1–2d / 无依赖，但依赖 Phase 4 壳和 Phase 3 模型摘要 / **owner: Composer 2.5**

**对应基线**：完整 D D1。**涉及文件**：`frontend/desktop-app/`、`frontend/protocol-client/`、前端 package manifest、`frontend/desktop-app/tests/`。**协议变化**：none。**Grok**：无。

**操作步骤**：检查 Electron 入口、Main/Renderer/preload 边界、脚本、Node/Bun 版本、生成类型入口和 OpenTUI 共享类型；记录缺失路径；禁止为了通过检查创建假壳。

**验收命令**：`Test-Path frontend\desktop-app; Test-Path frontend\protocol-client; python -m pytest tests/test_protocol -q`。壳不存在时预期为 `BLOCKED_PREREQUISITE`；完整 D D1 的后端/进程验收仍必须由后端卡完成。

**完成判据**：

- [ ] Desktop 入口、Renderer、Main、preload 和 protocol-client 目录边界已记录；
- [ ] 生成类型来源和 schema 版本已记录；
- [ ] 没有 renderer → Python/HTTP 直连；
- [ ] Composer 已提交可独立回滚 commit。

### PhaseD-F2 · Protocol-client 握手、能力和错误投影

`P0` / 2–3d / 依赖 F1 和后端 DB2 / **owner: Composer 2.5**

**对应基线**：完整 D D2。**涉及文件**：`frontend/protocol-client/`、`frontend/desktop-app/src/protocol/`、协议 fixture、客户端测试。**协议变化**：none；若必须变更，走 §1.3。**Grok**：无。

**必须实现**：`initialize/initialized`、版本范围、client/server capability、稳定 error code、timeout、断开、unsupported feature、overload、配置缺失和 protocol mismatch 的 typed 状态。

**验收命令**：`python -m pytest tests/test_protocol -q; cd frontend\protocol-client; npm test`。前端必须通过真实 appserver fixture 或契约测试证明：未声明能力不显示入口、错误可区分重试/用户处理/不可恢复。

### PhaseD-F3 · Electron Main、preload 与 appserver 连接监督

`P0` / 2–3d / 依赖 F1、F2 和后端 DB3 / **owner: Composer 2.5**

**对应基线**：完整 D D3。**涉及文件**：`frontend/desktop-app/src/main/`、`src/preload/`、`src/platform/`、Electron process tests。**协议变化**：消费 process lifecycle/error events；**Grok**：无。

**必须实现**：启动/关闭/崩溃/重启/孤儿回收、多窗口策略、IPC allowlist、外部 URL 委托系统浏览器、`contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`。

**验收命令**：`python -m pytest tests/test_appserver -q; cd frontend\desktop-app; npm run typecheck`。必须覆盖 appserver 启动失败、立即崩溃、窗口强关、重启恢复、未知 IPC 方法/参数拒绝和连续 20 次启停无孤儿进程。

### PhaseD-F4 · Project / Workspace 前端工作区

`P1` / 2–3d / 依赖 F2、F3 和后端 DB4 / **owner: Composer 2.5**

**对应基线**：完整 D D4。**涉及文件**：`frontend/desktop-app/src/features/projects/`、`src/features/workspaces/`、组件测试。**协议变化**：none。**Grok**：无。

**验收命令**：`python -m pytest tests/test_projects -q; cd frontend\desktop-app; npm run typecheck`。必须证明两个项目不串 cwd、新 Thread 绑定 workspace、不可访问目录有可理解错误、项目移除不删除用户代码。

### PhaseD-F5 · Thread / Turn / Item 与 Child Tree 会话中心

`P0` / 3–4d / 依赖 F2、F3、F4 和后端 DB5 / **owner: Composer 2.5**

**对应基线**：完整 D D5。**涉及文件**：`frontend/desktop-app/src/features/threads/`、`src/stores/`、Child tree components、会话测试。**协议变化**：消费 Thread/Turn/Item/parent-child cursor；**Grok**：无。

**必须实现**：新建、恢复、重命名、归档、分叉；按项目/workspace/状态筛选；展示 Child 的 Agent、触发方式、状态、耗时、预算、权限和失败原因；Parent↔Child 导航；草稿不伪造成输入；删除确认。

**验收命令**：`python -m pytest tests/test_threads -q; cd frontend\desktop-app; npm run typecheck`。必须证明刷新/重启不丢 parent/child tree、Child 工具/审批/预算不混入 Parent、重试不重复 Item、cursor 可恢复。

### PhaseD-F6 · 对话时间线与流式 Item 渲染

`P0` / 3–4d / 依赖 F5 和后端 Item events / **owner: Composer 2.5**

**对应基线**：完整 D D6。**涉及文件**：`src/features/timeline/`、`src/components/items/`、`src/stores/`、前端测试。**协议变化**：none。**Grok**：正常、空、加载、长输出、错误、窄窗口、深色主题。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须覆盖 delta 乱序/重复、1000 Item 虚拟滚动、流式中断保留已收到内容、工具失败不显示成功、不可展示的原始 reasoning 不被渲染。

### PhaseD-F7 · Tool / Command / Background Task 工作台

`P0` / 2–3d / 依赖 F5、F6 和后端 DB6 / **owner: Composer 2.5**

**对应基线**：完整 D D7。**涉及文件**：`src/features/execution/`、`src/features/items/`、前端测试。**协议变化**：消费 Tool/Command/BackgroundTask item states；**Grok**：无。

**验收命令**：`python -m pytest tests/test_execution -q; cd frontend\desktop-app; npm run typecheck`。必须显示工具、参数摘要、风险、cwd、退出码、stdout/stderr、增量、截断、运行/成功/失败/取消/超时/审批状态，并对 Key/Authorization/敏感路径脱敏。

### PhaseD-F8 · Permission Center 与审批呈现

`P0` / 2–3d / 依赖 F2、F7 和后端 DB7 / **owner: Composer 2.5**

**对应基线**：完整 D D8。**涉及文件**：`src/features/approvals/`、`src/features/settings/`、审批组件测试。**协议变化**：消费 Approval、auto-review capability 和 audit records；**Grok**：审批弹层视觉验收。

**必须显示**：动作、工具/命令、cwd、路径、风险、写文件/联网/子进程、作用域、过期时间、拒绝后果。按钮只发送 allow/deny/ask/取消请求，不修改后端 policy。

**验收命令**：`python -m pytest tests/test_approval -q; cd frontend\desktop-app; npm run typecheck`。必须证明一次允许不影响下一次、项目作用域不扩散、撤销生效、无按钮时后端仍拒绝、`approval_id` 可追踪；`approval.auto_review` 未声明时不显示入口。

### PhaseD-F9 · Git Diff / Review / Finding / Checkpoint 工作台

`P0` / 4–5d / 依赖 F4、F5、F7、F8 和后端 DB8 / **owner: Composer 2.5**

**对应基线**：完整 D D9。**涉及文件**：`src/features/review/`、`src/features/git/`、diff/finding/checkpoint 组件和测试。**协议变化**：消费 `review/start`、Review/Finding、checkpoint、git hunk actions；**Grok**：diff 对齐、长行、折叠、空/错误态。

**验收命令**：`python -m pytest tests/test_review -q; cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须保持完整 D §5.5/§5.6 的请求、响应、错误码、diff hash、stale、comment 和恢复语义，不在 UI 重新发起审查或伪造 Review。

### PhaseD-F10 · 文件树、预览、外部编辑器与 Worktree UI

`P1` / 3–4d / 依赖 F4、F5、F9 和后端 DB9 / **owner: Composer 2.5**

**对应基线**：完整 D D10/D11。**涉及文件**：`src/features/files/`、`src/features/preview/`、`src/features/worktrees/`、`src/platform/git/`。**协议变化**：消费 FilePreview/ExternalEditor/Worktree lifecycle；**Grok**：代码、Markdown、图片、二进制、长路径。

**验收命令**：`python -m pytest tests/test_file_preview -q; python -m pytest tests/test_worktrees -q; cd frontend\desktop-app; npm run typecheck`。必须证明只读预览、workspace 外路径拦截、外部编辑器明确动作、两个 Thread 的 worktree 不串目录、删除/prune/handoff 前显示未提交变更。

### PhaseD-F11 · Settings、模型目录、Capabilities、MCP/Skills 面板

`P1` / 3–4d / 依赖 F2、F8、F10 和后端 DB10/DB11 / **owner: Composer 2.5**

**对应基线**：完整 D D12/D13。**涉及文件**：`src/features/settings/`、`src/features/capabilities/`、`src/features/mcp/`、`src/platform/secrets/`。**协议变化**：消费 Settings/Capability/Skill/MCP projections；**Grok**：外部能力错误态视觉验收。

**必须遵守**：模型 max token 只展示 Phase 3 resolver/summary；不从 model id 自行推断；secret 只通过 Main/secure storage；未安装/未授权能力不显示为可用；MCP/Skill/浏览器调用走普通 Tool/Approval/Review Item。

**验收命令**：`python -m pytest tests/test_settings -q; python -m pytest tests/test_capabilities -q; cd frontend\desktop-app; npm run typecheck`。必须证明 global/project/workspace/thread 覆盖一致、Key 不进日志/transcript/crash、能力缺失有降级态。

### PhaseD-F12 · Notifications、长任务、恢复和无障碍视觉系统

`P1` / 3–4d / 依赖 F5、F6、F8、F9、F10 和后端 DB12 / **owner: Composer 2.5**

**对应基线**：完整 D D14/D15。**涉及文件**：`src/features/notifications/`、`src/features/recovery/`、`src/ui/`、`src/components/`、`tests/a11y/`、`tests/visual/`。**协议变化**：none；**Grok**：通知、断线、恢复、主题、布局溢出、图片/文件预览、审批/diff 层级。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须覆盖后台 turn、审批/输入/失败通知、防重复、重启恢复，以及 design tokens、light/dark/high-contrast、键盘 focus、aria、长路径、窄窗口、高 DPI 和不可只靠颜色表达风险。

### PhaseD-F13 · 前端打包、更新 UI 与发布交接

`P0` / 4–5d / 依赖 F2、F3、F11、F12 和后端 DB13 / **owner: Composer 2.5**

**对应基线**：完整 D D16。**涉及文件**：`frontend/desktop-app/`、前端 packaging 配置、安装/升级/错误页组件、前端 CI。**协议变化**：消费 package/appserver compatibility metadata；**Grok**：安装、升级、回滚和错误页视觉验收。

**验收命令**：`python -m pytest tests/test_release -q; cd frontend\desktop-app; npm run typecheck; npm run build`。必须证明产物能启动 appserver 并握手、版本不匹配有清楚错误、更新失败保留旧版本、crash payload 不含 Key/完整 prompt/代码内容；后端 runtime package smoke 由 DB13 合并验收。

---

## §5 前端安全与体验

### 5.1 Secret、IPC、导航和预览

- React state、localStorage、transcript 和 crash payload 不保存 API Key；
- preload 不暴露 `ipcRenderer`、Node `fs`、`child_process` 或完整环境变量；
- IPC 方法名和参数必须 allowlist/schema 校验，未知方法一律拒绝；
- 外部 URL、下载、外部编辑器必须经过明确用户动作或后端审批；
- 文件路径先由后端 canonicalize 和 policy 检查，Renderer 不决定 workspace 外访问；
- 图片、HTML、SVG 预览隔离脚本执行；文件名和内容不能注入 Markdown/HTML。

### 5.2 视觉状态不改变业务语义

所有 `loading`、`empty`、`error`、`disabled`、`running`、`paused`、`completed`、`recovery_required` 都必须映射到后端状态。Grok 可以指出状态不可理解、布局溢出或层级问题，但不能把后端状态改成“看起来完成”。

### 5.3 前端与 LinkAgent

LinkAgent 只通过 `protocol-client`、生成类型、capability、Thread/Turn/Item、Approval、Diff/Review 和 extension manifest 接入。前端不得为 LinkAgent 提供未声明的内部 React state；LinkAgent 也不得迫使 Desktop 复制一套 Agent 状态机。

---

## §6 前端测试与验收

### 6.1 测试分层

| 层级 | 前端必须验证 | 后端配合 |
|---|---|---|
| Protocol contract | 类型、方向、错误、能力和事件 fixture | 提供 schema、真实样例和版本 |
| Unit | reducer、去重、sequence/cursor、UI 状态转换、diff hash 呈现 | 提供事件序列 |
| Component | Item、Approval、Review、Settings、空/错/恢复态 | 提供状态矩阵 |
| IPC/Process | preload allowlist、spawn、关闭、重启、未知参数拒绝 | 提供 appserver 可执行入口 |
| E2E | 项目→Thread→工具→审批→变更→Review→恢复 | 提供真实后端，不用长期 mock |
| Visual | 主题、长文本、窄窗、审批、diff、预览、通知 | 确保状态和事件正确 |
| Package smoke | 安装、启动、握手、升级错误页 | 提供 runtime/schema 兼容信息 |

### 6.2 前端最小 E2E

必须覆盖完整 D §8.2 的 20 个场景；前端重点确认：

1. 流式 delta 重复/乱序不会重复文字；
2. Parent/Child 导航、筛选和 cursor 不丢；
3. 审批弹层不会显示后端未声明的能力；
4. Review finding 能回到文件、行、diff hash 和下一轮输入；
5. appserver 崩溃后 UI 显示 recovery_required，不伪造完成；
6. renderer 无法读文件、启动进程、读 Key 或调用未知 IPC；
7. 视觉截图同时覆盖正常、空、加载、错误、长文本、深色、窄窗口和 focus。

### 6.3 前端机械门

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
git diff --check
python -m pytest -q
cd frontend\protocol-client
npm test -- --run
cd ..\desktop-app
npm run typecheck
npm run test -- --run
npm run build
```

脚手架实际命令不同必须记录真实命令和输出；不能用“本地能跑”代替可复制命令。完整 D 的后端 Python 契约、进程、恢复和发布命令必须与后端文档一起执行。

---

## §7 前端出口与后端合并

### 7.1 前端交付出口

- [ ] F1–F13 完成，且每张卡引用了完整 D 对应卡；
- [ ] 所有协议消费来自冻结 schema/生成类型，没有临时字段；
- [ ] Renderer 无 Python、数据库、任意 HTTP、secret 和未 allowlist IPC；
- [ ] Thread/Turn/Item/Child/Review/Approval 都能幂等投影并恢复；
- [ ] Phase 3 max token 只显示 resolver/summary，不在 UI 重新计算；
- [ ] Grok 的视觉问题已转成组件状态或回归测试；
- [ ] typecheck、unit/component、IPC、E2E、视觉和 build 有真实输出；
- [ ] 已生成前端交接包、已知限制和可回滚 commit。

### 7.2 与后端的交接顺序

```text
后端冻结 schema/capability/fixture
  ↓
前端 protocol-client + reducer
  ↓
Electron Main/preload
  ↓
Renderer features
  ↓
前后端联调与恢复测试
  ↓
完整 D 的跨端 E2E / package smoke / LinkAgent contract
```

前端不能以“后端还没完成”为理由长期保留临时协议；短期 fixture 必须标记版本、来源和删除日期。

### 7.3 完整 Phase D 的前端判定

只有完整 D 的功能、架构、体验、发布出口全部通过，且后端文档的 DB 卡也通过，F 文档不能单独把 Phase D 标记为完成。前端只能输出：`READY_FOR_FULL_D_INTEGRATION`、`BLOCKED_PREREQUISITE` 或 `REJECTED_WITH_EVIDENCE`。

---

## 附录 A · 原 D 卡映射、命令继承和交接模板

| 前端卡 | 完整 D 基线 | 前端主要文件 | 后端依赖 |
|---|---|---|---|
| F1 | D1 | Desktop 壳、协议客户端入口 | DB1 |
| F2 | D2 | protocol-client、协议状态 | DB2 |
| F3 | D3 | Main/preload/platform | DB3 |
| F4 | D4 | projects/workspaces | DB4 |
| F5 | D5 | threads/stores/child tree | DB5 |
| F6 | D6 | timeline/items | DB5 |
| F7 | D7 | execution/items | DB6 |
| F8 | D8 | approvals/settings | DB7 |
| F9 | D9 | review/git/checkpoint views | DB8 |
| F10 | D10/D11 | files/preview/worktrees | DB9 |
| F11 | D12/D13 | settings/capabilities/MCP/Skills | DB10/DB11 |
| F12 | D14/D15 | notifications/recovery/ui/a11y | DB12 |
| F13 | D16 | frontend build/update/error UI | DB13 |

### A.1 前端交接记录模板

```yaml
handoff_id: D-F-HANDOFF-001
card: PhaseD-F5
source_baseline: PHASE-D-RXYCODE-DESKTOP.md#D5
branch: "<frontend branch>"
commit: "<commit>"
protocol_version: "<version>"
capabilities_consumed:
  - threads
  - thread_fork
  - multi_agent
fixtures:
  success: "<path>"
  denied: "<path>"
  reconnect: "<path>"
files_changed:
  - "<frontend-only path>"
tests:
  - "<command and result>"
visual_evidence: "<path or none>"
known_limitations:
  - "<limitation>"
backend_questions:
  - "<unresolved contract question>"
rollback: "<commit>"
owner: composer-2.5
```

**完成定义**：本文新增的是前端执行边界，不改变完整 D 的原始示例、模型适配、协议语义和验收要求；任何冲突必须回到完整 D 公共基线和协议契约测试解决。
