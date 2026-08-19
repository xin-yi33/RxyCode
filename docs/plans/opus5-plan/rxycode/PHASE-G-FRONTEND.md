# PHASE-G-FRONTEND（合并版）· 前端开发执行文档

> **本文档由两部分合并而成**：
> - **Part 1 权威前端拆分**（原 `PHASE-G-FRONTEND-RXYCODE-DESKTOP.md`）：PhaseG-H1-H13 卡、文件边界、安全红线——**前端验收以此为准**
> - **Part 2 前端开工清单**（原 `PHASE-G-FRONTEND-KICKOFF.md`）：给前端开发者的开工速查（卡表/等卡间隙/增强卡/纪律）
>
> **配套文件**：公共基线+总手册+增强卡见 [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md)；后端见 [`PHASE-G-BACKEND.md`](./PHASE-G-BACKEND.md)。
>
> **合并日期**：2026-08-11　**合并原则**：各部分正文一字未改。


---

# Part · 1 · 权威前端拆分（H1–H13）

> **本部分来源**：原 `PHASE-G-FRONTEND-RXYCODE-DESKTOP.md`（合并时正文一字未改，仅链接映射到新文件名）
# Phase G-H · RxyCode Desktop 前端开发执行文档

> **文档定位**：本文是 [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md) 的前端执行拆分文档，不替换完整 G 文档，也不删除其中的产品定义、协议示例、任务卡验收和完整出口标准。完整 G 文档是公共基线；本文把前端和 Electron Host 的实现责任拆出来，使前端开发者可以独立施工、测试和交接。
>
> **产品名称**：RxyCode Desktop。本文保持完整 G 文档中对 Codex 工作台的交互目标、OpenCode/Codex 上游复用边界、Phase 3 模型上限摘要和 Phase A/D/F 公共契约不变。
>
> **前置条件**：主计划 Phase 0/1/2/3/4 + Phase A/D/F 公共契约已冻结；Phase 4 的 Electron 壳、`frontend/protocol-client/`、`appserver/` 和 `protocol/schema.json` 是否真实存在必须以工作区检查为准。缺失时只能输出 `BLOCKED_PREREQUISITE`，不能用 mock 或临时 HTTP 绕过。
>
> **主文档关系**：完整功能、示例代码和总体验收以 [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md) 为唯一基线；本文只增加前端 owner、前端文件边界、前端任务卡和前后端交接要求。
>
> **基线日期**：2026-08-05　**建议工时**：与完整 Phase G 的 12–16 周总估算并行拆分，不得将两份文档的工时简单相加　**任务卡**：PhaseG-H1–PhaseG-H13（主链 13 张）＋ **追加卡 PhaseG-H14–H19**（P3 批 · Codex 对齐批前端基建，见 §4 卡区；不属主链 26 卡，主链出口门槛不变，立项依据 `research/2026-08-12-agent-native-computer-use-research.md`）

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必须先读) | 模型分工、施工回路、硬约束和协作方式 |
| [§1 拆分真相与文件边界](#1-拆分真相与文件边界) | 哪些代码由前端写、哪些代码禁止前端碰 |
| [§2 前端架构与协议消费](#2-前端架构与协议消费) | Electron、protocol-client、Renderer 和状态投影 |
| [§3 公共接口与交接协议](#3-公共接口与交接协议) | 前端消费的稳定接口和后端交接格式 |
| [§4 前端任务卡](#4-前端任务卡) | PhaseG-H1–J13 具体施工顺序 |
| [§5 前端安全与体验](#5-前端安全与体验) | preload、权限呈现、secret、可访问性和视觉辅助 |
| [§6 前端测试与验收](#6-前端测试与验收) | 单元、组件、进程、E2E、视觉和机械门 |
| [§7 前端出口与后端合并](#7-前端出口与后端合并) | 什么条件下前端可以交付给完整 F |
| 附录 A | 原 D 卡映射、命令继承和交接模板 |

---

## §0 执行手册（必须先读）

### 0.1 本文解决什么问题

完整 G 文档把 Desktop 视为一个整体，但前后端分开开发时必须先冻结边界：

```text
后端：协议 schema、appserver、Session/Thread 真相、权限、工具、Git、恢复
前端：Electron Main、preload、protocol-client、Reducer、Renderer、视觉、打包入口
共享：只通过 protocol/schema.json、生成类型、契约测试和 capability handshake 交接
```

本文不复制一份后端业务逻辑。前端开发者必须先读完整 F 的 §0–§11、附录 A–D；其中的 JSON、状态机、Review、checkpoint、Child Tree、Codex App Server 复用规则和验收要求保持原文不变。

### 0.2 模型分工（硬约束）

| 模型 | 负责 | 禁止 |
|---|---|---|
| **Composer 2.5** | **主写全部前端代码**：Electron Main、preload、React、TypeScript、protocol-client、Reducer、组件、组件测试、E2E、打包和最终合并 | 不得让 Grok 独立实现 Desktop；不得通过前端绕过 appserver、权限或模型 resolver |
| **Grok 4.5** | 仅做卡内标注的多模态辅助：启动 dev server、截屏、视觉回归、图片/文件预览、布局和设计稿对照 | 不写 Python；不改 `protocol/schema.json`；不独立修改前端公共状态模型；不单独提交主链 |
| **Sonnet 5（可选）** | 对 J2/J5/J6/J8/J9/J10/J12 的 diff 做状态、权限旁路、IPC 泄漏和可访问性预审 | 不替代 Composer 实现，不以预审结果替代测试 |
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

`frontend/desktop-app` 不存在时，J1 只能记录缺失清单并输出 `BLOCKED_PREREQUISITE`；不能创建临时目录后把 J2–J13 标记为通过。

### 0.4 每张前端卡的固定回路

```text
LOCATE → READ 完整 F 对应卡 → WRITE → TYPECHECK/LINT
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
| DC-J1 | Renderer 只能经 `frontend/protocol-client` 与 appserver 通信；禁止 import Python、读取数据库、直接调用后端 HTTP | 前端与 CLI/TUI/LinkAgent 分叉 |
| DC-J2 | UI 只投影后端状态，不复制 Agent 路由、工具注册、权限判断、max token resolver 或审计规则 | 多端语义漂移 |
| DC-J3 | 外部能力只能从 capability handshake 进入 UI；未声明能力不得显示为可用 | UI 猜测后端能力 |
| DC-J4 | 每个异步 UI 操作都必须显示 started/progress/completed/failed/cancelled 或 waiting 状态 | loading 假完成、重连丢状态 |
| DC-J5 | `ask`、allow、deny、auto-review 的按钮只提交后端请求；前端不能自行放行 | 权限旁路 |
| DC-J6 | Thread/Turn/Item、Review、Approval、Child Tree 均按 `event_id`/`sequence`/`cursor` 做幂等投影 | 重复事件和乱序破坏历史 |
| DC-J7 | preload 使用 `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`；IPC 只暴露 allowlist API | Renderer 获得 Node/Key/进程权限 |
| DC-J8 | Grok 截图不能替代组件、协议、E2E 和构建测试 | 视觉通过但功能不可靠 |

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
PHASE-G-DESKTOP.md
  = 完整产品、协议、示例、H1–H13 主链（历史表述 H1–H16 属旧体系，实际主链 = H1–H13 + P3 批追加 H14–H19）、完整安全/测试/出口标准的公共基线

PHASE-G-FRONTEND.md
  = Electron/TypeScript/React/protocol-client/视觉/前端测试的施工责任

PHASE-G-BACKEND.md
  = appserver/schema/Session/权限/工具/Git/恢复/后端测试的施工责任
```

完整 F 的原始示例代码不复制成变体。前端只引用并按原文消费：初始化握手、事件 JSON、Review 请求、checkpoint、capability 列表和状态恢复流程必须以完整 F §5 为准。

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
| `AgentEvent`（P3 预留，H18） | 多 Agent 活动投影（委派树/成员状态/预算，消费 E4 事件域） | capability 未声明时渲染任何 Agent 状态；用 mock 数据代替真实事件 |

### 2.3 示例代码继承规则

完整 F §5.1–§5.8 中的以下示例必须原样作为前端契约测试 fixture 或文档引用，不得改写成前端专属协议：

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

每张 H 卡必须冻结：

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

每张 H 卡共同继承完整 F §6.0 的四项完成判据；完整 F 对应 F 卡的验收要求不得被本文缩减。

### PhaseG-H1 · Desktop 基线与前端包边界

`P0` / 1–2d / 无依赖，但依赖 Phase 4 壳和 Phase 3 模型摘要 / **owner: Composer 2.5**

**对应基线**：完整 F H1。**涉及文件**：`frontend/desktop-app/`、`frontend/protocol-client/`、前端 package manifest、`frontend/desktop-app/tests/`。**协议变化**：none。**Grok**：无。

**操作步骤**：检查 Electron 入口、Main/Renderer/preload 边界、脚本、Node/Bun 版本、生成类型入口和 OpenTUI 共享类型；记录缺失路径；禁止为了通过检查创建假壳。

**验收命令**：`Test-Path frontend\desktop-app; Test-Path frontend\protocol-client; python -m pytest tests/test_protocol -q`。壳不存在时预期为 `BLOCKED_PREREQUISITE`；完整 F H1 的后端/进程验收仍必须由后端卡完成。

**完成判据**：

- [x] Desktop 入口、Renderer、Main、preload 和 protocol-client 目录边界已记录；
- [x] 生成类型来源和 schema 版本已记录；
- [x] 没有 renderer → Python/HTTP 直连；
- [x] Composer 已提交可独立回滚 commit。

### PhaseG-H2 · Protocol-client 握手、能力和错误投影

`P0` / 2–3d / 依赖 PhaseG-H1 和后端 PhaseG-B2 / **owner: Composer 2.5**

**对应基线**：完整 F H2。**涉及文件**：`frontend/protocol-client/`、`frontend/desktop-app/src/protocol/`、协议 fixture、客户端测试。**协议变化**：none；若必须变更，走 §1.3。**Grok**：无。

**必须实现**：`initialize/initialized`、版本范围、client/server capability、稳定 error code、timeout、断开、unsupported feature、overload、配置缺失和 protocol mismatch 的 typed 状态。

**验收命令**：`python -m pytest tests/test_protocol -q; cd frontend\protocol-client; npm test`。前端必须通过真实 appserver fixture 或契约测试证明：未声明能力不显示入口、错误可区分重试/用户处理/不可恢复。

### PhaseG-H3 · Electron Main、preload 与 appserver 连接监督

`P0` / 2–3d / 依赖 PhaseG-H1、PhaseG-H2 和后端 PhaseG-B3 / **owner: Composer 2.5**

**对应基线**：完整 F H3。**涉及文件**：`frontend/desktop-app/src/main/`、`src/preload/`、`src/platform/`、Electron process tests。**协议变化**：消费 process lifecycle/error events；**Grok**：无。

**必须实现**：启动/关闭/崩溃/重启/孤儿回收、多窗口策略、IPC allowlist、外部 URL 委托系统浏览器、`contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`。

**验收命令**：`python -m pytest tests/test_appserver -q; cd frontend\desktop-app; npm run typecheck`。必须覆盖 appserver 启动失败、立即崩溃、窗口强关、重启恢复、未知 IPC 方法/参数拒绝和连续 20 次启停无孤儿进程。

### PhaseG-H4 · Project / Workspace 前端工作区

`P1` / 2–3d / 依赖 PhaseG-H2、PhaseG-H3 和后端 PhaseG-B4 / **owner: Composer 2.5**

**对应基线**：完整 F H4。**涉及文件**：`frontend/desktop-app/src/features/projects/`、`src/features/workspaces/`、组件测试。**协议变化**：none。**Grok**：无。

**验收命令**：`python -m pytest tests/test_projects -q; cd frontend\desktop-app; npm run typecheck`。必须证明两个项目不串 cwd、新 Thread 绑定 workspace、不可访问目录有可理解错误、项目移除不删除用户代码。

### PhaseG-H5 · Thread / Turn / Item 与 Child Tree 会话中心

`P0` / 3–4d / 依赖 PhaseG-H2、PhaseG-H3、PhaseG-H4 和后端 PhaseG-B5 / **owner: Composer 2.5**

**对应基线**：完整 F H5。**涉及文件**：`frontend/desktop-app/src/features/threads/`、`src/stores/`、Child tree components、会话测试。**协议变化**：消费 Thread/Turn/Item/parent-child cursor；**Grok**：无。

**必须实现**：新建、恢复、重命名、归档、分叉；按项目/workspace/状态筛选；展示 Child 的 Agent、触发方式、状态、耗时、预算、权限和失败原因；Parent↔Child 导航；草稿不伪造成输入；删除确认。

**验收命令**：`python -m pytest tests/test_threads -q; cd frontend\desktop-app; npm run typecheck`。必须证明刷新/重启不丢 parent/child tree、Child 工具/审批/预算不混入 Parent、重试不重复 Item、cursor 可恢复。

**P3 对接（追加）**：会话中心为 **H15 三分类投影**（置顶/项目/最近）提供数据源——消费 B5 Thread 元数据（pin、`deleted_at`/`restored_at`）；删除语义扩展为**软删除映射**（B17，数据保留可恢复）；回收站列表消费 B17 `thread/list_deleted`。

### PhaseG-H6 · 对话时间线与流式 Item 渲染

`P0` / 3–4d / 依赖 PhaseG-H5 和后端 Item events / **owner: Composer 2.5**

**对应基线**：完整 F H6。**涉及文件**：`src/features/timeline/`、`src/components/items/`、`src/stores/`、前端测试。**协议变化**：none。**Grok**：正常、空、加载、长输出、错误、窄窗口、深色主题。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须覆盖 delta 乱序/重复、1000 Item 虚拟滚动、流式中断保留已收到内容、工具失败不显示成功、不可展示的原始 reasoning 不被渲染。

### PhaseG-H7 · Tool / Command / Background Task 工作台

`P0` / 2–3d / 依赖 PhaseG-H5、PhaseG-H6 和后端 PhaseG-B6 / **owner: Composer 2.5**

**对应基线**：完整 F H7。**涉及文件**：`src/features/execution/`、`src/features/items/`、前端测试。**协议变化**：消费 Tool/Command/BackgroundTask item states；**Grok**：无。

**验收命令**：`python -m pytest tests/test_execution -q; cd frontend\desktop-app; npm run typecheck`。必须显示工具、参数摘要、风险、cwd、退出码、stdout/stderr、增量、截断、运行/成功/失败/取消/超时/审批状态，并对 Key/Authorization/敏感路径脱敏。

**P3 对接（追加）**：工具工作台将由 **H19 扩展来源分组**（内置 / CLI-Hub / 自生成，消费 B14 来源标签）并提供 **预览画廊** 挂载点（CLI-Anything bundle 渲染，文件渲染边界——不隐含 PHASE-I 附件协议）。

### PhaseG-H8 · Permission Center 与审批呈现

`P0` / 2–3d / 依赖 PhaseG-H2、PhaseG-H7 和后端 PhaseG-B7 / **owner: Composer 2.5**

**对应基线**：完整 F H8。**涉及文件**：`src/features/approvals/`、`src/features/settings/`、审批组件测试。**协议变化**：消费 Approval、auto-review capability 和 audit records；**Grok**：审批弹层视觉验收。

**必须显示**：动作、工具/命令、cwd、路径、风险、写文件/联网/子进程、作用域、过期时间、拒绝后果。按钮只发送 allow/deny/ask/取消请求，不修改后端 policy。

**验收命令**：`python -m pytest tests/test_approval -q; cd frontend\desktop-app; npm run typecheck`。必须证明一次允许不影响下一次、项目作用域不扩散、撤销生效、无按钮时后端仍拒绝、`approval_id` 可追踪；`approval.auto_review` 未声明时不显示入口。

### PhaseG-H9 · Git Diff / Review / Finding / Checkpoint 工作台

`P0` / 4–5d / 依赖 PhaseG-H4、PhaseG-H5、PhaseG-H7、PhaseG-H8 和后端 PhaseG-B8 / **owner: Composer 2.5**

**对应基线**：完整 F H9。**涉及文件**：`src/features/review/`、`src/features/git/`、diff/finding/checkpoint 组件和测试。**协议变化**：消费 `review/start`、Review/Finding、checkpoint、git hunk actions；**Grok**：diff 对齐、长行、折叠、空/错误态。

**验收命令**：`python -m pytest tests/test_review -q; cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须保持完整 F §5.5/§5.6 的请求、响应、错误码、diff hash、stale、comment 和恢复语义，不在 UI 重新发起审查或伪造 Review。

### PhaseG-H10 · 文件树、预览、外部编辑器与 Worktree UI

`P1` / 3–4d / 依赖 PhaseG-H4、PhaseG-H5、PhaseG-H9 和后端 PhaseG-B9 / **owner: Composer 2.5**

**对应基线**：完整 F H10/H11。**涉及文件**：`src/features/files/`、`src/features/preview/`、`src/features/worktrees/`、`src/platform/git/`。**协议变化**：消费 FilePreview/ExternalEditor/Worktree lifecycle；**Grok**：代码、Markdown、图片、二进制、长路径。

**验收命令**：`python -m pytest tests/test_file_preview -q; python -m pytest tests/test_worktrees -q; cd frontend\desktop-app; npm run typecheck`。必须证明只读预览、workspace 外路径拦截、外部编辑器明确动作、两个 Thread 的 worktree 不串目录、删除/prune/handoff 前显示未提交变更。

### PhaseG-H11 · Settings、模型目录、Capabilities、MCP/Skills 面板

`P1` / 3–4d / 依赖 PhaseG-H2、PhaseG-H8、PhaseG-H10 和后端 PhaseG-B10/PhaseG-B11 / **owner: Composer 2.5**

**对应基线**：完整 F H12/H13。**涉及文件**：`src/features/settings/`、`src/features/capabilities/`、`src/features/mcp/`、`src/platform/secrets/`。**协议变化**：消费 Settings/Capability/Skill/MCP projections；**Grok**：外部能力错误态视觉验收。

**必须遵守**：模型 max token 只展示 Phase 3 resolver/summary；不从 model id 自行推断；secret 只通过 Main/secure storage；未安装/未授权能力不显示为可用；MCP/Skill/浏览器调用走普通 Tool/Approval/Review Item。

**验收命令**：`python -m pytest tests/test_settings -q; python -m pytest tests/test_capabilities -q; cd frontend\desktop-app; npm run typecheck`。必须证明 global/project/workspace/thread 覆盖一致、Key 不进日志/transcript/crash、能力缺失有降级态。

**P3 对接（追加）**：Settings 页将由 **H16 重构为 8 分区骨架**（左下角入口 + 分区懒加载）——本卡现有能力/模型面板成为其中"模型选择/模型添加/技能管理/MCP 服务管理"分区的实现基础；**团队与模型预留分区**与 PHASE-H H10 三层折叠对齐（后端未合入 → BLOCKED_PREREQUISITE，不 mock）。

### PhaseG-H12 · Notifications、长任务、恢复和无障碍视觉系统

`P1` / 3–4d / 依赖 PhaseG-H5、PhaseG-H6、PhaseG-H8、PhaseG-H9、PhaseG-H10 和后端 PhaseG-B12 / **owner: Composer 2.5**

**对应基线**：完整 F H14/H15。**涉及文件**：`src/features/notifications/`、`src/features/recovery/`、`src/ui/`、`src/components/`、`tests/a11y/`、`tests/visual/`。**协议变化**：none；**Grok**：通知、断线、恢复、主题、布局溢出、图片/文件预览、审批/diff 层级。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须覆盖后台 turn、审批/输入/失败通知、防重复、重启恢复，以及 design tokens、light/dark/high-contrast、键盘 focus、aria、长路径、窄窗口、高 DPI 和不可只靠颜色表达风险。

**P3 对接（追加）**：**H17 运行状态视觉系统**（转圈/蓝点/常驻高亮）与 **GX27** 的"停止 → OS 通知"联动在本卡通知机制上扩展；通知三端实现（Electron `new Notification()` 统一，Linux libnotify 缺失降级应用内横幅）。

### PhaseG-H13 · 前端打包、更新 UI 与发布交接

`P0` / 4–5d / 依赖 PhaseG-H2、PhaseG-H3、PhaseG-H11、PhaseG-H12 和后端 PhaseG-B13 / **owner: Composer 2.5**

**对应基线**：完整 F H16。**涉及文件**：`frontend/desktop-app/`、前端 packaging 配置、安装/升级/错误页组件、前端 CI。**协议变化**：消费 package/appserver compatibility metadata；**Grok**：安装、升级、回滚和错误页视觉验收。

**验收命令**：`python -m pytest tests/test_release -q; cd frontend\desktop-app; npm run typecheck; npm run build`。必须证明产物能启动 appserver 并握手、版本不匹配有清楚错误、更新失败保留旧版本、crash payload 不含 Key/完整 prompt/代码内容；后端 runtime package smoke 由 DB13 合并验收。

**P3 对接（追加）**：打包须包含 **locale 资源**（H14 `locales/` 入包，三端构建）；**macOS/Linux 构建目标 smoke 加入验收**（打包目标已含 nsis/dmg/AppImage/deb——三端启动+握手+语言切换冒烟）。

---

### PhaseG-H14 · i18n 语言本地化基建（P3 批追加卡）

> **性质声明**：H14–H19 为 **P3 批（Codex 对齐批）前端基建卡**，不属于主链 26 卡（B1–B13 + H1–H13），主链出口门槛不变；它们是 GX20/GX22/GX26/GX27/GX25 等增强卡的前端地基，执行顺序在对应 GX 卡之前。立项依据：`research/2026-08-12-agent-native-computer-use-research.md` §6.5。

`P1` / 3–4d / 依赖 H1（Desktop 壳）/ **owner: Composer 2.5**

**对应基线**：无（新增全局基建）。**涉及文件**：`frontend/desktop-app/src/i18n/`（新增：`locales/{zh-CN,en}.json`、`t.ts` 取词、语言上下文）、`src/main/`（`app.getLocale()` 透传）、`src/renderer/src/App.tsx`（挂载语言上下文）。**协议变化**：none；**Grok**：视觉抽查（语言切换后布局不溢出）。

**必须实现**：
- locale 资源 JSON（**zh-CN + en 首批**，用户确认；目录结构预留多语言，后续只加文件不加机制）；
- `t(key, vars)` 取词机制 + 语言上下文（React Context）；全部 UI 静态文案经 `t()` 取词；
- 启动语言：Electron `app.getLocale()` 获取系统语言 → 归一化映射（如 macOS `zh-Hans-CN` → `zh-CN`）→ 首次进入按系统语言显示；
- 切换：常规设置可选语言，持久化（localStorage/settings），重启保持；
- **边界（硬约束）**：只影响 GUI 界面文案（技能→Skills、设置→Settings）；**不影响对话中模型的回复语言**；动态内容（会话文本/工具输出）不入 i18n；
- **跨平台**：`app.getLocale()` 三端一致；locale 归一化覆盖 Windows/macOS/Linux 常见变体。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须证明：切换语言后全部静态文案切换（抽查清单）、对话内容语言不变、重启保持、未知 locale 回退默认、窄窗下长文案不溢出。

**完成判据**：
- [x] `locales/{zh-CN,en}.json` + `t()` 机制落地；
- [x] 系统语言获取 + 归一化 + 首次进入生效；
- [x] 设置切换 + 持久化 + 重启保持；
- [x] 对话回复语言不受影响（验证用例）；
- [x] 全部静态文案迁移完成（GX22 文案清单配合）；单 commit。

### PhaseG-H15 · 会话栏三分类重构（P3 批追加卡）

`P0` / 3–4d / 依赖 H5（会话中心）+ GX8（pin 语义）/ **owner: Composer 2.5**

**对应基线**：Codex 会话侧栏交互（规格：报告 §6.1–6.2）。**涉及文件**：`frontend/desktop-app/src/components/SessionList.tsx`（重构）、`src/lib/sessionCategories.ts`（新增：分类投影规则）、`src/components/SessionListItem.tsx`（扩展：状态区/折叠）、`src/lib/sessionCategories.test.ts`（新增）、`src/components/SessionList.test.tsx`（扩展）。**协议变化**：消费 B5 Thread 元数据（pin、`deleted_at`）；**Grok**：三分类布局与折叠视觉验收。

**必须实现**：
- **三分类投影（置顶 / 项目 / 最近，自上而下）**：置顶 = pin 会话（固定分类顶部）；项目 = 项目目录树（每项目展开其会话）；最近 = 未归类未置顶会话（含回收站投影数据源预留）；
- **折叠交互**：分类均可独立展开/收起；收起时标题右侧 `>` 符号（展开态指向下），与标题间距 4px；
- **hover 高亮**：分类标题/项目/会话条目 hover 高亮，亮度抄 Codex（浅色 ≈ rgba(0,0,0,0.06)、深色 ≈ rgba(255,255,255,0.08)，**以 Codex 实机取样为准**——卡内验收要求截图对照）；
- 分类标题次要灰字体（design token secondary text，随主题）；
- 会话删除 → 回收站投影数据源（消费 B17 `thread/list_deleted`）；置顶整合 GX8 pin；
- **纯投影**：分类/折叠/hover 均为本地 UI 状态，不改后端数据（§5.2 铁律）。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须证明：三分类归属正确、折叠/展开与 `>` 符号方向正确、pin 会话进置顶分类、删除会话进回收站投影、hover 高亮与取样值一致（截图对照）、刷新/重启后折叠状态保持（localStorage）、五态（空分类/加载/错误/窄窗/深色）覆盖。

**完成判据**：
- [x] 三分类投影 + 归属规则生效；
- [x] 折叠/展开 + `>` 符号 + 4px 间距；
- [x] hover 高亮取样值落地（含截图对照记录）；
- [x] 置顶/回收站数据源接入（B17 未合入时回收站区显示 BLOCKED_PREREQUISITE，不 mock）；
- [x] 五态测试通过；单 commit。

### PhaseG-H16 · Settings 页重构框架（P3 批追加卡）

`P0` / 3–4d / 依赖 H11（Settings 现状）+ B10 / **owner: Composer 2.5**

**对应基线**：Codex 设置页交互（规格：报告 §6.4）。**涉及文件**：`frontend/desktop-app/src/components/SettingsPage.tsx`（重构）、`src/features/settings/`（新增：分区骨架 + 8 分区组件目录）、`src/lib/settingsSections.ts`（新增：分区注册表）、`src/components/SettingsPage.test.tsx`（扩展）。**协议变化**：none（各分区消费既有 B10/D5 方法）；**Grok**：左下角入口与分区导航视觉验收。

**必须实现**：
- **入口**：左下角圆角矩形框（圆角 ≈ 6px，取样修正），**设置图标 + "设置"二字**；hover 高亮（同 H15 亮度规格）；
- **8 分区导航骨架**（左导航列表）+ 分区懒加载：
  1. 回收站（GX21 挂载点；B17 未合入 → BLOCKED_PREREQUISITE）
  2. 常规（语言切换挂载 H14、启动行为、默认项目目录、开发者选项）
  3. 外观（主题 system/light/dark/high-contrast 扩展、自定义、字体/字号、密度）
  4. 模型选择（对接 D5 `models/set_active`；**含思考强度选择器——2026-08-12 追加**：档位 = 当前模型 `models/list` 的 `effort_options`（英文档位名），无档位模型禁用，提交 `models/set_active` 带 `effort` optional_field，全局生效，与 CLI `/effort` 读写同一全局设置）
  5. 模型添加（AddModelPanel 直接复用，D5 已实现，**不改后端**）
  6. 技能管理（对接 B11 skill_manager）
  7. MCP 服务管理（对接 B11 mcp/）
  8. **团队与模型（预留）**：多 Agent 开关（F10 `settings.agents.enabled`）+ 多模型角色配置（**对齐 PHASE-H H10 三层折叠设计**）；后端未合入 → 分区隐藏或显示 BLOCKED_PREREQUISITE（禁止 mock）；
- 分区注册表：新增分区只加注册项，不改骨架。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须证明：入口 hover/点击正确、8 分区导航与懒加载、模型添加复用 D5（后端零改动）、**思考强度选择器（档位随模型/无档位禁用/全局生效）**、团队与模型分区未合入时 BLOCKED、五态覆盖、窄窗导航不溢出。

**完成判据**：
- [x] 左下角入口（图标+文字+圆角框+hover）落地；
- [x] 8 分区骨架 + 懒加载 + 注册表机制；
- [x] 模型选择/添加对接 D5（零后端改动验证）；
- [x] 团队与模型预留分区 BLOCKED 路径（不 mock）；
- [x] 对齐 H10 三层折叠的兼容性声明；单 commit。

### PhaseG-H17 · 运行状态视觉系统（P3 批追加卡）

`P0` / 2–3d / 依赖 H12（视觉系统）+ B5（Thread 状态）/ **owner: Composer 2.5**

**对应基线**：Codex 会话运行状态视觉（规格：报告 §6.3）。**涉及文件**：`frontend/desktop-app/src/ui/tokens/status.ts`（扩展 design tokens）、`src/components/StatusIndicator.tsx`（新增：转圈/蓝点）、`src/components/SessionListItem.tsx`（状态区接入）、`src/lib/statusProjection.ts`（新增：B5 状态 → 视觉投影）、`src/components/StatusIndicator.test.tsx`（新增）。**协议变化**：none（消费 B5/事件流已有状态）；**Grok**：转圈动画/蓝点/高亮视觉验收。

**必须实现**：
- **转圈动画**：会话运行中，条目右侧圆环旋转（Codex 样式）；
- **蓝点**：完成态替代转圈位置（同位置平滑过渡）；
- **停止/异常**：OS 系统通知（复用 GX13 通知机制）+ 条目错误态徽标；
- **常驻高亮**：正在运行的会话条目保持 hover 同亮度高亮（不灭）；
- **纯投影（§5.2 铁律）**：所有视觉映射后端 B5 状态机（running/completed/failed/cancelled…），前端不得自造状态；转圈/蓝点/高亮均为投影；
- 跨平台：OS 通知三端（Windows toast / macOS UserNotifications / Linux libnotify——Electron `new Notification()` 统一，Linux libnotify 缺失时降级应用内横幅）。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须证明：转圈↔蓝点↔错误徽标随 B5 状态机正确切换（事件驱动测试）、运行中常驻高亮、停止触发通知（mock 通知层）、状态切换不产生闪烁/重复、五态覆盖。

**完成判据**：
- [x] 转圈/蓝点/错误徽标/常驻高亮四态投影落地；
- [x] 状态全部来自 B5 状态机（无前端自造状态）；
- [x] OS 通知三端实现 + Linux 降级路径；
- [x] 五态测试通过；单 commit。

### PhaseG-H18 · 多 Agent 前端契约预留（P3 批追加卡）

`P1` / 2–3d / 依赖 H16（设置骨架）/ **owner: Composer 2.5**

**对应基线**：多 Agent 专家团设计（`research/2026-08-11-multiagent-expert-team-design-research.md` C5）+ PHASE-E E4 AgentEvent + PHASE-F F12 委派树。**涉及文件**：`frontend/protocol-client/`（AgentEvent 类型消费骨架）、`frontend/desktop-app/src/features/team/`（新增：GX19 挂载点）、`src/lib/agentEvents.ts`（新增：E4 事件投影 reducer 骨架）。**协议变化**：**仅消费侧预留**——protocol/schema.json 中 `agent_*` 事件域**类型占位**（不实现，capability 门控）；**Grok**：无。

**必须实现**：
- AgentEvent 消费投影骨架（agent_started/tool/progress/done/paused/cancelled/budget_exceeded——类型与 reducer 骨架，消费 E4 事件域）；
- capability 门控：PHASE-E/F 未合入时**不显示任何入口/分区（或 BLOCKED_PREREQUISITE）**，**禁止 mock 假协议**（前端开工纪律）；
- 设置页"团队与模型"分区挂载点（H16 第 8 分区）——后端就绪后填内容，未就绪显示 BLOCKED；
- 预留委派树数据接口（F12 数据消费点，GX19 实现时填充）。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须证明：E/F 未合入时界面零多 Agent 痕迹（门控生效）、capability 开关关闭时无入口、类型占位不破坏生成契约（`bun run generate` 一致性）、无任何 mock 数据路径。

**完成判据**：
- [x] AgentEvent 消费骨架 + reducer 类型落地；
- [x] capability 门控生效（未合入零痕迹）；
- [x] 无 mock 路径（代码审查 + 测试验证）；
- [x] 生成类型一致性无破坏；单 commit。

### PhaseG-H19 · CLI 工具面板与预览画廊（P3 批追加卡）

`P1` / 3–4d / 依赖 H7（工具工作台）+ B14（CLI 桥接器）/ **owner: Composer 2.5**

**对应基线**：CLI-Anything 预览栈消费协议（`preview-bundle/v1`、`preview-live/v1`、trajectory——报告 §3.4）。**涉及文件**：`frontend/desktop-app/src/components/ToolCard.tsx`（扩展：来源分组）、`src/features/preview/PreviewGallery.tsx`（新增：bundle 渲染 hero/gallery/video/JSON）、`src/lib/cliTools.ts`（新增：`cli:` 工具消费投影）、`src/components/PreviewGallery.test.tsx`（新增）。**协议变化**：消费 B14 `cli/list` + 工具元数据来源标签；**Grok**：画廊渲染视觉验收。

**必须实现**：
- 工具工作台来源分组：**内置 / CLI-Hub / 自生成**（消费 B14 来源标签；B14 未合入 → 分组降级为仅内置，不 BLOCKED）；
- 预览画廊：渲染 CLI-Anything bundle（hero ≤1280px / gallery / video ≤8s / diff-json），消费本地 bundle 目录（`<project>/.cli-anything/previews/`）或 B14 launch 输出；
- **边界（硬约束）**：画廊是**文件渲染**（本地文件/图片/视频），**不隐含 PHASE-I 图片附件协议**（PHASE-I 未实施，不依赖）；
- bundle 缓存键/性能预算沿用 CLI-Anything 规范（≤25MB）；`summary.json` 紧凑展示（headline/facts/warnings/next_actions）；
- 跨平台：本地文件路径三端（file:// 处理、Windows 盘符/POSIX 路径归一化）；无平台特有依赖。

**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。必须证明：来源分组正确（B14 合入前仅内置组）、画廊渲染 hero/gallery/video/JSON 四类 artifact、缓存键生效、大 bundle 不阻塞 UI（懒加载）、PHASE-I 附件协议零依赖、五态覆盖。

**完成判据**：
- [x] 工具来源分组（内置/CLI-Hub/自生成）；
- [x] 画廊四类 artifact 渲染 + 性能预算；
- [x] 文件渲染边界声明（零 PHASE-I 依赖）；
- [x] 五态测试通过；单 commit。

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

必须覆盖完整 F §8.2 的 20 个场景；前端重点确认：

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

脚手架实际命令不同必须记录真实命令和输出；不能用“本地能跑”代替可复制命令。完整 F 的后端 Python 契约、进程、恢复和发布命令必须与后端文档一起执行。

---

## §7 前端出口与后端合并

### 7.1 前端交付出口

- [ ] J1–J13 完成，且每张卡引用了完整 F 对应卡；
- [x] 所有协议消费来自冻结 schema/生成类型，没有临时字段；
- [x] Renderer 无 Python、数据库、任意 HTTP、secret 和未 allowlist IPC；
- [x] Thread/Turn/Item/Child/Review/Approval 都能幂等投影并恢复；
- [x] Phase 3 max token 只显示 resolver/summary，不在 UI 重新计算；
- [ ] Grok 的视觉问题已转成组件状态或回归测试；
- [ ] typecheck、unit/component、IPC、E2E、视觉和 build 有真实输出；
- [x] 已生成前端交接包、已知限制和可回滚 commit。

**P3 批（Codex 对齐批）附加出口**（H14–H19 + GX19–GX27 前端部分，主链出口达标后执行）：
- [x] H14–H19 六张追加卡完成，且消费协议来自 GXn-PROTO 登记的冻结 schema；
- [x] i18n：全部静态文案经 `t()` 取词（zh-CN + en），切换不影响对话回复语言；
- [x] 会话栏三分类（置顶/项目/最近）+ 折叠/`>`/hover 取样值落地；
- [x] 设置页 8 分区 + 左下角入口 + 团队与模型预留分区（BLOCKED 不 mock）；
- [x] 运行状态视觉（转圈/蓝点/常驻高亮）纯投影 B5 状态机；
- [x] 多 Agent 契约预留零 mock 路径（capability 门控验证）；
- [x] CLI 工具分组 + 预览画廊文件渲染边界（零 PHASE-I 附件协议依赖）；
- [ ] macOS/Linux 构建目标 smoke（locale 入包 + 启动握手）通过。

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
完整 F 的跨端 E2E / package smoke / LinkAgent contract
```

前端不能以“后端还没完成”为理由长期保留临时协议；短期 fixture 必须标记版本、来源和删除日期。

### 7.3 完整 Phase G 的前端判定

只有完整 F 的功能、架构、体验、发布出口全部通过，且后端文档的 DB 卡也通过，H 文档不能单独把 Phase G 标记为完成。前端只能输出：`READY_FOR_FULL_D_INTEGRATION`、`BLOCKED_PREREQUISITE` 或 `REJECTED_WITH_EVIDENCE`。

---

## 附录 A · 原 D 卡映射、命令继承和交接模板

| 前端卡 | 完整 F 基线 | 前端主要文件 | 后端依赖 |
|---|---|---|---|
| J1 | H1 | Desktop 壳、协议客户端入口 | DB1 |
| J2 | H2 | protocol-client、协议状态 | DB2 |
| J3 | H3 | Main/preload/platform | DB3 |
| J4 | H4 | projects/workspaces | DB4 |
| J5 | H5 | threads/stores/child tree | DB5 |
| J6 | H6 | timeline/items | DB5 |
| J7 | H7 | execution/items | DB6 |
| J8 | H8 | approvals/settings | DB7 |
| J9 | H9 | review/git/checkpoint views | DB8 |
| J10 | H10/H11 | files/preview/worktrees | DB9 |
| J11 | H12/H13 | settings/capabilities/MCP/Skills | DB10/DB11 |
| J12 | H14/H15 | notifications/recovery/ui/a11y | DB12 |
| J13 | H16 | frontend build/update/error UI | DB13 |

**P3 批追加卡登记（主链出口后执行，非 J 映射；立项依据 `research/2026-08-12-agent-native-computer-use-research.md`）**：

| 追加卡 | 前端基建 | 对应增强卡 | 后端依赖 | 主要文件 |
|---|---|---|---|---|
| H14 | i18n 基建 | GX22 | — | `src/i18n/`、`locales/{zh-CN,en}.json` |
| H15 | 会话栏三分类重构 | GX20/GX21 | B17 | `src/components/SessionList.tsx`、`src/lib/sessionCategories.ts` |
| H16 | Settings 重构框架 | GX26 | B10/D5 | `src/features/settings/`、`SettingsPage.tsx` |
| H17 | 运行状态视觉 | GX27 | B5 | `StatusIndicator.tsx`、`statusProjection.ts` |
| H18 | 多 Agent 契约预留 | GX19 | E4（未实施→门控） | `src/features/team/`、`agentEvents.ts` |
| H19 | CLI 工具面板+预览画廊 | GX25 | B14 | `PreviewGallery.tsx`、`cliTools.ts` |

### A.1 前端交接记录模板

```yaml
handoff_id: D-F-HANDOFF-001
card: PhaseG-H5
source_baseline: PHASE-G-DESKTOP.md#H5
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

**完成定义**：本文新增的是前端执行边界，不改变完整 F 的原始示例、模型适配、协议语义和验收要求；任何冲突必须回到完整 F 公共基线和协议契约测试解决。


---

# Part · 2 · 前端开工清单

> **本部分来源**：原 `PHASE-G-FRONTEND-KICKOFF.md`（合并时正文一字未改，仅链接映射到新文件名）
# Phase G 开工手册 · 前端专属清单

> **读者**：前端开发者（feat/phase-g-frontend 分支）。
> **你的角色**：Electron 壳、React 界面、协议客户端（protocol-client）的**消费者与实现者**。
> **先读**：[`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md)（总手册，§0-§10 全部适用）+ [`PHASE-G-FRONTEND.md`](./PHASE-G-FRONTEND.md)（你的施工权威文档）。
> **创建**：2026-08-10

---

## §0 你的任务总览

- **主链**：PhaseG-H1 → H13，13 张卡（每张 = 内部依赖 + 等一个后端卡）
- **P3 批追加卡（Codex 对齐批，主链出口后执行）**：PhaseG-H14 → H19（i18n 基建 / 会话栏三分类 / Settings 重构 / 运行状态视觉 / 多 Agent 契约预留 / CLI 工具面板+预览画廊）——完整卡定义见 Part 1 §4，增强卡见总手册 §8
- **增强阶段**：GX1/GX5/GX6/GX10/GX11/GX12/GX14/GX15/GX17/GX19/GX21/GX22/GX27（前端为主）+ GX2/GX3/GX4/GX7/GX8/GX9/GX13/GX16/GX18/GX20/GX23/GX24/GX25/GX26 的前端部分
- **你的第一原则**：**你只消费协议，不生产真相**。Thread 生命周期、权限、预算、模型解析一律来自后端协议；你负责把它们画出来。

---

## §1 必读与前置

1. 总手册 §1 必读清单（完整 G 文档第 3 项**必读全篇**，重点 §3 总体架构、§5 协议与状态契约、§7 安全与隐私）
2. 前置自检（总手册 §2）：7 项 `Test-Path`，缺 → `BLOCKED_PREREQUISITE`（带对应依赖卡号清单）
3. 文件白名单（总手册 §3）：你拥有 `frontend/desktop-app/`、`frontend/protocol-client/`

---

## §2 主链卡表（H1-H13 · 依赖 · 等后端 · 工时 · 验收命令）

> 验收命令为速查版（**全部摘录自原版 G-H 文档对应卡，未自行新增门禁**；如与原文不一致以原文档为准并报告）；完整"必须实现/完成判据"以 G-H 文档对应卡为准。`owner: Composer 2.5` = 由你（前端执行者）完成。

| 卡 | 标题 | 内部依赖 | 等后端 | 工时 | 验收命令（速查） |
|---|---|---|---|---|---|
| **H1** | Desktop 基线与前端包边界 | 无 | Phase 4 壳+Phase 3 | 1-2d | `Test-Path frontend/desktop-app; Test-Path frontend/protocol-client; python -m pytest tests/test_protocol -q` |
| **H2** | Protocol-client 握手、能力和错误投影 | H1 | **B2** | 2-3d | `python -m pytest tests/test_protocol -q; cd frontend/protocol-client; npm test` |
| **H3** | Electron Main、preload 与 appserver 连接监督 | H1, H2 | **B3** | 2-3d | `python -m pytest tests/test_appserver -q; cd frontend/desktop-app; npm run typecheck` |
| **H4** | Project / Workspace 前端工作区 | H2, H3 | **B4** | 2-3d | `python -m pytest tests/test_projects -q; cd frontend/desktop-app; npm run typecheck` |
| **H5** | Thread / Turn / Item 与 Child Tree 会话中心 | H2,H3,H4 | **B5**（含 H5 fixture） | 3-4d | `python -m pytest tests/test_threads -q; cd frontend/desktop-app; npm run typecheck` |
| **H6** | 对话时间线与流式 Item 渲染 | H5 | B5/B6 Item events | 3-4d | `cd frontend/desktop-app; npm run typecheck; npm run test -- --run` |
| **H7** | Tool / Command / Background Task 工作台 | H5, H6 | **B6** | 2-3d | `python -m pytest tests/test_execution -q; cd frontend/desktop-app; npm run typecheck` |
| **H8** | Permission Center 与审批呈现 | H2, H7 | **B7** | 2-3d | `python -m pytest tests/test_approval -q; cd frontend/desktop-app; npm run typecheck` |
| **H9** | Git Diff / Review / Finding / Checkpoint 工作台 | H4,H5,H7,H8 | **B8** | 4-5d | `python -m pytest tests/test_review -q; cd frontend/desktop-app; npm run typecheck; npm run test -- --run` |
| **H10** | 文件树、预览、外部编辑器与 Worktree UI | H4,H5,H9 | **B9** | 3-4d | `python -m pytest tests/test_file_preview -q; python -m pytest tests/test_worktrees -q; cd frontend/desktop-app; npm run typecheck` |
| **H11** | Settings、模型目录、Capabilities、MCP/Skills 面板 | H2,H8,H10 | **B10/B11** | 3-4d | `python -m pytest tests/test_settings -q; python -m pytest tests/test_capabilities -q; cd frontend/desktop-app; npm run typecheck` |
| **H12** | Notifications、长任务、恢复和无障碍视觉系统 | H5,H6,H8,H9,H10 | **B12** | 3-4d | `cd frontend/desktop-app; npm run typecheck; npm run test -- --run` |
| **H13** | 前端打包、更新 UI 与发布交接 | H2,H3,H11,H12 | **B13** | 4-5d | `python -m pytest tests/test_release -q; cd frontend/desktop-app; npm run typecheck; npm run build` |

**你的节奏**：H1 与后端 B1 同日开工；此后每张卡等对应后端卡合入（总手册 §5.1 表）。

---

## §3 等卡间隙工作清单（后端没合时你做什么）

**允许**（不违反 BLOCKED_PREREQUISITE）：
1. H1 延伸：组件框架、设计 tokens、五态组件库（空/加载/错误/窄窗/深色）
2. 预研后端协议示例（B 文档里的 JSON 示例可以搭"假数据渲染层"，**但不能假装接真协议**）
3. 写组件测试框架、视觉回归脚本
4. 读增强文档，把 GX 卡的设计研究清楚（竞品基准调研 §12 P0 十项）

**禁止**：
- 用 mock / 临时 HTTP 冒充已合入的后端卡（红线 1）
- 自己实现 Thread 生命周期 / 权限 / 预算 / 模型解析（红线 2）

---

## §4 你的增强卡（主链完成后，详见 PHASE-G-DESKTOP.md）

| 增强卡 | 你的部分 | 说明 |
|---|---|---|
| GX1 | 任务看板视图（四列投影） | 只读投影 Thread 状态，纯前端 |
| GX2 | 审批卡片 + 权限三档切换器 | 消费 `approval/mode_set` |
| GX3 | diff 行内注释 + 五档 scope 选择器 | 消费 `review/comment/*` |
| GX4 | revert 按钮挂消息 + 检查点时间轴 + 命名快照 | 消费 `checkpoint/rewind` |
| GX5 | Send 三态下拉 + pending 队列 | 纯前端 UI 状态 |
| GX6 | 工具卡片 + Todo 时间线 + 自动折叠 | 纯渲染层 |
| GX7 | statusline + 用量环 | 消费 `event/agent_usage` 事件 |
| GX8 | 会话四件套 + fork 入口 | 消费 `thread/fork` |
| GX9 | Plan 文件面板 + Implement 按钮 | 消费 `plan/*` |
| GX10 | 运行侧栏浮层（四节投影） | 纯前端投影 |
| GX11 | 只读锁定 + 侧栏筛选分组 | 纯前端 |
| GX12 | Prompt suggestions | 纯前端，零 LLM |
| GX13 | 通知设置页三档 + 通知点击聚焦 | 消费 `event/agent_needs_input` |
| GX14 | Ask/Edit/Agent 模式选择器 | **前后端联合**：依赖后端为 `agent/invoke` 扩展 optional field `capability`（枚举 `no_tools`/`edit_only`/`full`，后端工具注册层强制校验——前端状态不构成安全边界）；你负责 UI 展示与发送参数 |
| GX15 | Design Mode 预览标注 | 图片附件协议缺失时 BLOCKED_PREREQUISITE |
| GX16 | 侧聊窗口 + promote | 消费 `thread/side_chat/*` |
| GX17 | 版本卡 | 只读投影 B8 |
| GX18 | Follow-up 建议卡 | 消费 B12 turn 完成事件 |
| GX19 | 多 Agent 活动可视化（P3） | 消费 E4 AgentEvent（E 未合入 → BLOCKED_PREREQUISITE，不 mock）；基建：H18 |
| GX20 | 会话三分类 + 折叠交互（P3） | 消费 B5 pin/`deleted_at` 元数据；基建：H15 |
| GX21 | 回收站 UI（P3） | 消费 `thread/list_deleted` + `thread/purge`；基建：H15 |
| GX22 | i18n 语言本地化（P3） | 纯前端文案清单映射；基建：H14 |
| GX23 | 定时任务 UI（P3） | 消费 `schedule/*`；基建：— |
| GX24 | 插件生态（P3） | 消费 `plugin/*` + G13 能力面板；基建：— |
| GX25 | CLI 工具面板 + 预览画廊（P3） | 消费 `cli/*` + 来源标签 + bundle 目录；基建：H19 |
| GX26 | 设置页重构 8 分区（P3） | 模型选择/添加（D5）、技能（B11）、MCP（B11）、团队与模型预留（H10 对齐）；基建：H16 |
| GX27 | 运行状态视觉（P3） | 纯投影 B5 状态机 + GX13 通知联动；基建：H17 |
| GX28 | Team Manager（P3） | 消费 F18 `team_*` 协议（F18 未合入 → BLOCKED_PREREQUISITE，不 mock）；/team 三层窗口流复用 CommandPalette/category；分组管理/Auto 开关（token 弹窗）/安装两步询问；基建：H16 团队分区 + GX26 |

---

## §5 你的文件白名单（可写范围）

```
frontend/desktop-app/**、frontend/protocol-client/**（消费 + 本地验证；**生成类型产物由后端唯一生成并提交，你禁止提交生成差异**）、
增强卡新增文件（src/features/*、src/components/*）
```

**禁止触碰**：`appserver/**`、`protocol/**`（后端唯一 Owner）、`core/**`、`tests/test_*.py`（只读观察）、`data/`、`credentials.yaml`、`.env*`、`~/.rxycode/`。

**protocol-client 的使用方式**：从 `protocol/schema.json` 生成类型（`bun run generate`），**客户端类型不反向当 schema 真相**；schema 变更由后端产出，你只读消费并确认。**生成类型唯一规则：生成产物由后端在协议变更中生成并提交；你只读消费 + 本地验证（可运行 generate 核对），禁止提交生成差异**（防双人并发生成冲突）。

---

## §6 前端安全红线（G-H §5 原文，逐条遵守）

1. React state、localStorage、transcript 和 crash payload **不保存 API Key**
2. preload **不暴露** `ipcRenderer`、Node `fs`、`child_process` 或完整环境变量
3. IPC 方法名和参数必须 allowlist/schema 校验，**未知方法一律拒绝**
4. 外部 URL、下载、外部编辑器必须经过明确用户动作或后端审批
5. 模型 max token **只展示** Phase 3 resolver/summary，不从 model id 自行推断
6. secret 只通过 Main / secure storage 存取

---

## §7 验收纪律（你的专属提醒）

1. 每张卡：先跑验收命令贴输出（以 G-H 对应卡原版验收为准，含其中要求的 typecheck/test），再逐条勾"完成判据"
2. **五态铁律**：新增组件必须覆盖 空/加载/错误/窄窗/深色 五态（视觉验收最低标准，G-H §8）
3. 视觉验收截图归档到 `frontend/desktop-app/docs/gx-screenshots/`（增强阶段）
4. 大卡（H9/H13）合并靠后，承担 rebase（总手册 §4.1）
5. 后端 fixture 未就绪时：如实 BLOCKED_PREREQUISITE，不 mock
6. 全局 agent baseline 在批次/阶段出口跑一次（不是你每张卡跑）；无 key 时 `PENDING_BASELINE` 如实标注
