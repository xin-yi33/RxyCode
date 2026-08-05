# Phase D-B · RxyCode Desktop 后端开发执行文档

> **文档定位**：本文是 [`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) 的后端执行拆分文档，不替换完整 D 文档，也不删除其中的产品定义、协议示例、任务卡验收和完整出口标准。完整 D 文档是公共基线；本文把 appserver、协议、Session 真相、权限、工具、Git、恢复、能力和发布 runtime 责任拆出来，使后端开发者可以独立施工、测试和交接。
>
> **产品名称**：RxyCode Desktop。本文保持完整 D 文档中对 Codex App Server、OpenCode 子代理、Phase 3 模型上限摘要、Phase A/B/C 公共契约和 LinkAgent 扩展边界不变。
>
> **前置条件**：主计划 Phase 0/1/2/3/4 + Phase A/B/C 公共契约已冻结；`appserver/`、`protocol/schema.json`、Phase 3 resolver/summary 和既有 backend tests 是否真实存在必须以工作区检查为准。缺失时只能输出 `BLOCKED_PREREQUISITE`，不得用临时 mock 代替。
>
> **主文档关系**：完整功能、示例代码和总体验收以 [`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) 为唯一基线；本文只增加后端 owner、后端文件白名单、后端任务卡和前后端交接要求。
>
> **基线日期**：2026-08-05　**建议工时**：与完整 Phase D 的 12–16 周总估算并行拆分，不得将两份文档的工时简单相加　**任务卡**：PhaseD-B1–PhaseD-B13

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必须先读) | 模型分工、施工回路、硬约束和协作方式 |
| [§1 拆分真相与文件边界](#1-拆分真相与文件边界) | 后端拥有的唯一真相和前端禁止触碰的部分 |
| [§2 后端架构与 App Server 边界](#2-后端架构与-app-server-边界) | schema、appserver、Session、工具、恢复和发布 runtime |
| [§3 公共接口、事件和状态契约](#3-公共接口事件和状态契约) | 前端唯一可以消费的稳定接口 |
| [§4 后端任务卡](#4-后端任务卡) | PhaseD-B1–B13 具体施工顺序 |
| [§5 后端安全与上游复用](#5-后端安全与上游复用) | 权限、secret、OpenCode/Codex、审计和隔离 |
| [§6 后端测试与验收](#6-后端测试与验收) | 协议、单元、进程、恢复、E2E 和发布验证 |
| [§7 后端出口与前端交接](#7-后端出口与前端交接) | 什么条件下后端可以交付给完整 D |
| 附录 A | 原 D 卡映射、接口冻结和交接模板 |

---

## §0 执行手册（必须先读）

### 0.1 本文解决什么问题

完整 D 的 Desktop 体验必须建立在后端唯一真相之上。前端可以单独开发，但它不能自行决定：

```text
Thread/Turn/Item 的生命周期
Child Session 的隔离、预算、权限和事件
Tool/Command/Git/Review 的真实执行结果
Approval、Auto-review、Secret、Workspace 和路径安全
模型 provider、model_id、max output token 的解析
重连、replay、cursor、checkpoint、stale 和恢复状态
```

本文把上述能力交给后端文档施工；前端只通过 `protocol/schema.json`、生成类型、JSON-RPC/JSONL 和 capability handshake 消费。本文不复制完整 D 的产品和协议定义；完整 D §4/§5 的对象、示例 JSON、状态机、错误码和出口是强制基线。

### 0.2 模型分工（硬约束）

| 模型 | 负责 | 禁止 |
|---|---|---|
| **Composer 2.5** | **主写全部后端代码**：appserver、protocol/schema、Session/Thread/Turn/Item、权限、工具、Git、Review、恢复、模型摘要接入、测试、runtime packaging 和最终合并 | 不得把后端核心交给 Grok；不得为了配合前端复制第二套业务逻辑 |
| **Grok 4.5** | 仅做前端文档指定的视觉辅助；可协助阅读日志、整理复现截图，但不拥有后端实现 | 不写 Python/Rust 后端；不改 schema、权限、数据库、appserver 或后端测试主契约 |
| **Sonnet 5（可选）** | 对 B2/B5/B7/B8/B9/B12 的 diff 做状态、权限、secret、并发、恢复和进程泄漏预审 | 不替代 Composer 实现，不作为完成标准 |
| **前端协作者** | 消费已冻结协议、提交 UI 侧复现、验证生成类型和交接 fixture | 不直接改 `appserver/`、`protocol/` 或后端数据库修复前端问题 |
| **人** | 决定权限默认值、数据保留、是否接受上游复用和发布风险 | 不以 Desktop 能显示为理由放宽后端安全 |

### 0.3 开工前自检

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
git status --short
git branch --show-current
python --version
Test-Path appserver
Test-Path protocol\schema.json
Test-Path tests\test_appserver
python -m pytest -q
```

缺少 `appserver/`、`protocol/schema.json` 或目标测试目录时，B1 只能记录阻塞，不得用一个临时 Python HTTP 服务或内存字典代替正式产物。

### 0.4 每张后端卡的固定回路

```text
LOCATE → READ 完整 D 对应卡与前端消费点 → WRITE
→ TYPECHECK/LINT → UNIT/CONTRACT TEST → PROCESS/INTEGRATION
→ RECOVERY/SECURITY → CHECK DIFF → HANDOFF → COMMIT
```

每张卡必须留下：

- 后端改动文件清单；
- schema、method、event、capability、错误码和版本；
- 成功、拒绝、超时、取消、崩溃、重连和 replay fixture；
- 真实命令输出、已知限制和可回滚 commit；
- 前端可直接消费的最小交接包。

### 0.5 后端继承的八条硬规则

| 编号 | 规则 | 违反后果 |
|---|---|---|
| DC-B1 | `protocol/schema.json` 是跨语言契约唯一来源；先更新 schema/生成类型/contract test，再通知前端 | 前后端字段漂移 |
| DC-B2 | Thread/Turn/Item/Child/Review/Approval 的后端状态是唯一真相，UI 不能反向写状态 | 多端结果不一致 |
| DC-B3 | 所有异步动作有 started/progress/completed/failed/cancelled/waiting 终态，等待审批可取消和超时 | stalled、重试重复、无法恢复 |
| DC-B4 | 权限、workspace、sandbox、secret、路径和网络策略必须在执行边界生效 | UI 隐藏按钮不能算安全 |
| DC-B5 | Phase 3 的 resolver/ModelCatalog 是 max token 唯一来源；未知模型走明确高位默认和 warning，不在 Desktop 猜测 | 模型上限错误或被统一写死 |
| DC-B6 | OpenCode/Codex 能直接复用的核心优先 dependency/fork/vendor/subprocess；semantic-port 必须有不兼容证据 | 重造等价 Runtime |
| DC-B7 | 事件含 `event_id`、对象 id、`sequence`、时间和 payload；重放、去重、乱序和幂等由后端保证 | 前端被迫猜事件顺序 |
| DC-B8 | 日志、transcript、trace、crash payload 和错误不能泄露 Key、完整环境、未授权路径或不可展示原始 reasoning | secret/隐私泄漏 |

### 0.6 明确不做的事情

本后端文档不做：

- 为 Desktop 另造一套与 CLI/TUI/LinkAgent 不同的 Agent Runtime；
- 把权限、模型上限、工具路由和审计判断放入 Renderer；
- 通过临时 HTTP/mock/内存状态绕过 appserver 和 schema；
- 把 Codex 私有桌面实现、OpenCode 品牌或未经核验的源码直接复制进仓库；
- 用统一写死的 8192 替代 Phase 3 的按 `model_id` resolver；
- 将完整 prompt、secret 或工具原始输出无条件写入日志和 crash report。

---

## §1 拆分真相与文件边界

### 1.1 两份执行文档和一份公共基线

```text
PHASE-D-RXYCODE-DESKTOP.md
  = 完整产品、协议、示例、D1–D16、完整安全/测试/出口标准的公共基线

PHASE-D-BACKEND-RXYCODE-DESKTOP.md
  = appserver/schema/Session/权限/工具/Git/恢复/模型摘要/runtime 的施工责任

PHASE-D-FRONTEND-RXYCODE-DESKTOP.md
  = Electron/TypeScript/React/protocol-client/视觉/前端测试的消费责任
```

完整 D §5.1–§5.8 的初始化、事件、Review、checkpoint、capability 和恢复示例必须原样作为后端契约测试 fixture；后端可以增加版本字段或 `x-rxycode-*` 扩展，但不能改变已有字段语义而不升级 protocol major。

### 1.2 文件 ownership 白名单

| 范围 | 后端 Owner | 前端 Owner | 冲突处理 |
|---|---|---|---|
| `appserver/`、后端 core、Session/store、权限、工具、Git | 可写 | 禁止 | 前端通过复现和协议请求修复，不直接改后端 |
| `protocol/schema.json`、`protocol/*.py` | 唯一 Owner | 只读消费 | schema 变更必须生成类型并跑 contract test |
| `tests/test_protocol/`、`tests/test_appserver/`、`tests/test_*` Python | 可写 | 只读观察 | fixture/断言变更必须记录协议版本 |
| Phase 3 ModelCatalog/resolver/summary | 复用 Owner | 禁止复制 | Desktop 只消费摘要 |
| `frontend/protocol-client/` | 提供 schema/fixture | 可写消费 | 不把客户端类型反向当 schema 真相 |
| `frontend/desktop-app/` | 提供进程/接口约束 | 可写 | 后端不能直接改 UI 组件 |
| `packaging/` runtime、Python 依赖、appserver bundle | 可写 | 构建入口配合 | runtime/schema 版本必须绑定 |

### 1.3 后端协议变更单

```yaml
protocol_change:
  request_id: D-B-PROTOCOL-001
  producer: appserver
  consumers:
    - frontend/protocol-client
    - frontend/desktop-app
    - opentui
    - linkagent
  current_schema_version: "<version>"
  change_kind: new_optional_field # new_method | new_event | semantic_change | error_code
  method_or_event: "<method/event>"
  compatibility: "<backward-compatible evidence>"
  generated_types: "<command and commit>"
  fixtures:
    success: "<path>"
    denied: "<path>"
    timeout: "<path>"
    reconnect: "<path>"
  migration: "<required or none>"
  rollback: "<commit>"
  owner: composer-2.5
```

前端未确认消费方式前，后端不得删除字段、复用旧字段表达新语义或改变错误码含义。若必须变更，先更新 schema、生成类型、冻结快照和 contract test，再交接前端。

---

## §2 后端架构与 App Server 边界

### 2.1 后端唯一真相

```text
Provider / ModelCatalog / Phase 3 resolver
        ↓
PrimaryRuntime / Phase B Child / Phase C Coordinator
        ↓
Tool / Permission / Workspace / Git / Review services
        ↓
Session store + event log + checkpoint/audit
        ↓
appserver JSON-RPC / JSONL
        ↕
CLI / OpenTUI / Desktop / LinkAgent
```

Desktop 只能是上述后端的一个客户端。后端不能为了满足一个 UI 组件而创建 UI 专属业务方法；若新增能力，必须进入 capability、公共 method/event 和契约测试。

### 2.2 App Server 生命周期

后端必须支持：

1. `initialize`/`initialized`、协议版本、服务版本、capability、modelProviders 和 permissionProfiles；
2. Request、Notification、Server Request 的方向和 response 关联；
3. appserver 启动、优雅关闭、超时、崩溃、重启、孤儿任务和重连；
4. Thread/Turn/Item 的持久化、分页、fork、archive、cursor 和 replay；
5. Approval/Question 的超时、取消、连接断开和审计；
6. Phase B Child Session 的 parent/child、隔离、预算、权限、事件和终态；
7. Phase 3 的 `model_id` → ModelCatalog → `model_max_output_tokens` / fallback resolver 摘要；
8. LinkAgent 只依赖的公共协议，不依赖 Desktop 内部对象。

### 2.3 OpenCode/Codex 复用边界

Phase B 的 OpenCode 复用规则以 [`PHASE-B-ISOLATED-SUBAGENT.md`](./PHASE-B-ISOLATED-SUBAGENT.md) 附录 C 为准；Phase D 的 Codex/App Server 复用规则以完整 D 附录 C 为准。后端必须先做 dependency/fork/vendor/subprocess 审计，只有明确不兼容时才 semantic-port，并记录 commit、许可证、适配原因、测试和回滚。

---

## §3 公共接口、事件和状态契约

### 3.1 初始化握手（与完整 D §5.1 保持不变）

```text
initialize
  ├─ clientInfo: name/title/version
  ├─ protocolVersion
  ├─ clientCapabilities
  └─ requestedFeatures

initialized notification

server response
  ├─ protocolVersion
  ├─ serverVersion
  ├─ capabilities
  ├─ modelProviders
  └─ permissionProfiles
```

版本不兼容必须返回可机器断言的错误和升级信息，禁止静默降级到字段语义不同的旧协议。

### 3.2 Request、Notification、Server Request

| 类型 | 方向 | 例子 | 后端要求 |
|---|---|---|---|
| Request | Desktop/CLI/TUI → appserver | `thread/start`、`turn/start`、`review/start` | 有 response、timeout、cancel 和 request_id |
| Notification | appserver → 客户端 | `item/started`、`item/delta`、`turn/completed` | 无 response，但必须有 event_id/sequence |
| Server request | appserver → 客户端 | `approval/request`、`question/request` | 有 response、过期、取消、断开处理 |

### 3.3 事件包络（与完整 D §5.3 保持不变）

```json
{
  "event_id": "evt_123",
  "thread_id": "thr_123",
  "turn_id": "turn_456",
  "item_id": "item_789",
  "sequence": 42,
  "created_at": "2026-08-02T00:00:00Z",
  "type": "item/updated",
  "payload": {}
}
```

后端负责持久化和产生单调 sequence；重连可按 cursor 补读；重复请求按 request_id 幂等；重复 completed 不产生重复业务副作用。

### 3.4 Review、checkpoint、Git 和恢复接口

Review 请求、response、通知和错误码必须保持完整 D §5.5 原文：`review/start`、`review/read`、`review/started`、`review/progress`、`review/finding`、`review/completed`、`review/stale`、`review/failed`、`review/cancelled`，以及 `REVIEW_SCOPE_INVALID`、`REVIEW_DIFF_UNAVAILABLE`、`REVIEW_ALREADY_RUNNING`、`REVIEW_CANCELLED`、`REVIEW_TIMEOUT`、`REVIEW_PROTOCOL_MISMATCH`。

文件变更 turn 必须创建 checkpoint；以下方法必须经过后端权限中心：

```text
checkpoint/list
checkpoint/read
checkpoint/restore
git/stage
git/unstage
git/revert
```

恢复后产生新的 diff hash，并令旧 Review stale；Renderer 不能伪造 checkpoint、Review 或 diff hash。

### 3.5 能力和模型摘要

后端必须声明并按真实可用性返回：

```text
threads / thread_fork / background_turns / command_execution
file_changes / review / review_comments / checkpoint / git_hunk_actions
worktree / file_preview / browser / mcp / skills
multi_agent / multi_model / vision / approval.auto_review
```

模型相关能力必须包含来源明确的摘要：

```json
{
  "provider_id": "<provider>",
  "model_id": "<real-model-id>",
  "model_context_window": 0,
  "model_max_output_tokens": 0,
  "limit_source": "model-metadata|provider-catalog|config-override|fallback",
  "is_fallback": false,
  "warning": null
}
```

`model_max_output_tokens` 必须来自 Phase 3 resolver；未知模型才使用预设高位 fallback，并带 warning/来源。不得在 Desktop、CLI、OpenTUI 各写一份 8192。

---

## §4 后端任务卡

### 4.0 卡级施工格式（Composer 必须遵守）

每张 B 卡必须冻结：

```text
优先级 / 工时 / 依赖 / owner
涉及文件白名单
协议变化（schema / method / event / error / capability）
上游复用来源、commit、许可证和适配理由
验收命令与预期结果
完成判据 checkbox
前端交接 fixture 和兼容窗口
```

每张 B 卡共同继承完整 D §6.0 的四项完成判据；完整 D 对应 D 卡的验收要求不得被本文缩减。

### PhaseD-B1 · 后端基线、App Server 包边界与上游复用冻结

`P0` / 1–2d / 无依赖，但依赖 Phase 4 壳、Phase 3 模型摘要和 Phase A/B/C 公共契约 / **owner: Composer 2.5**

**对应基线**：完整 D D1 + 完整 D 附录 C DR1。**涉及文件**：`appserver/`、`protocol/schema.json`、`protocol/`、后端测试、`docs/decisions/desktop-upstream-reuse.md`。**协议变化**：none；**Grok**：无。

**操作步骤**：实际检查 appserver 启动入口、协议输出、schema、生成流程、Phase 3 resolver、Phase B/C 消费面；锁定 Codex App Server/OpenCode 复用来源、commit、许可证和路径；输出“复用/适配/禁止重写”清单。

**验收命令**：`Test-Path appserver; Test-Path protocol\schema.json; python -m pytest tests/test_protocol -q`。缺失时输出带清单的 `BLOCKED_PREREQUISITE`。

**完成判据**：

- [ ] App Server 入口、stdout 协议、stderr 日志和版本已确认；
- [ ] schema 唯一来源和生成类型流程已确认；
- [ ] 上游复用决策、许可证和回滚已记录；
- [ ] Composer 2.5 提交独立 commit，前端可以据此开工。

### PhaseD-B2 · Protocol handshake、能力发现、错误模型和生成契约

`P0` / 2–3d / 依赖 B1 / **owner: Composer 2.5**

**对应基线**：完整 D D2。**涉及文件**：`protocol/schema.json`、`protocol/`、`tests/test_protocol/`、generated types。**协议变化**：`initialize`、capability、error schema；**Grok**：无。

**必须实现**：协议版本范围、client/server capability、stable error code、timeout、closed、unsupported、overloaded、configuration missing、protocol mismatch；更新 schema、生成 TypeScript/Python 类型和冻结快照。

**验收命令**：`python -m pytest tests/test_protocol -q`。必须覆盖新旧版本、能力缺失、错误可重试性、未知字段处理和 schema/生成类型一致性；完成后交接给前端 F2。

### PhaseD-B3 · App Server 进程、生命周期、日志和恢复底座

`P0` / 2–3d / 依赖 B1、B2 / **owner: Composer 2.5**

**对应基线**：完整 D D3。**涉及文件**：`appserver/`、进程生命周期、日志/恢复模块、`tests/test_appserver/`。**协议变化**：process lifecycle/error events；**Grok**：无。

**必须实现**：启动/优雅关闭/超时/崩溃/重启/孤儿任务回收、stdout 只输出协议、stderr/受控日志输出、共享 appserver 的多窗口策略、临时资源释放和 recovery_required 状态。

**验收命令**：`python -m pytest tests/test_appserver -q`。必须覆盖启动失败、立即崩溃、强制关闭、重启恢复、重复启动退出 20 次和未完成任务不伪造完成；Electron Main 的进程调用由前端 F3 联调。

### PhaseD-B4 · Project / Workspace 服务与路径边界

`P1` / 2–3d / 依赖 B2、B3 / **owner: Composer 2.5**

**对应基线**：完整 D D4。**涉及文件**：`appserver/`、`protocol/`、workspace/project store、`tests/test_projects/`。**协议变化**：Project/Workspace methods/events；**Grok**：无。

**必须实现**：最近项目、添加本地目录、显示名/真实路径分离、workspace、branch/worktree、不可访问/不存在/Git 非仓库错误、项目级设置作用域、移除不删除代码、路径 canonicalize 和 symlink 防绕过。

**验收命令**：`python -m pytest tests/test_projects -q`。必须证明两个项目不串 cwd、新 Thread 必须绑定 workspace、workspace 变更产生上下文事件、workspace 外路径后端拒绝。

### PhaseD-B5 · Thread / Turn / Item / Child Session 真相

`P0` / 3–4d / 依赖 B2、B3、B4、Phase B / **owner: Composer 2.5**

**对应基线**：完整 D D5 + Phase B 附录 C。**涉及文件**：`appserver/`、`protocol/`、session store、`tests/test_threads/`、Child event tests。**协议变化**：Thread/Turn/Item、parent/child cursor、replay；**Grok**：无。

**必须实现**：Thread 新建/恢复/重命名/归档/删除/分叉；项目/workspace/status/time filter 所需字段；Turn start/steer/interruption/retry；Item 持久化分页；Parent/Child 的独立 session、Context、Runtime、Tool/Permission、Budget、Trace、lease、事件和生命周期；`parent_session_id`、`root_session_id`、cursor 一致。

**验收命令**：`python -m pytest tests/test_threads -q`。必须证明分叉不改父 Thread、Child 工具/审批/预算不混入 Parent、重试幂等、归档可恢复、Child 失败/取消/孤儿可审计；完成后提供 F5 fixture。

### PhaseD-B6 · Tool、Command、Background Task 执行与事件

`P0` / 2–3d / 依赖 B5、Phase A/B / **owner: Composer 2.5**

**对应基线**：完整 D D7。**涉及文件**：`protocol/`、`appserver/`、tool runner、background task store、`tests/test_execution/`。**协议变化**：Tool/Command/BackgroundTask item states；**Grok**：无。

**必须实现**：工具名/参数摘要/风险、命令/cwd/环境摘要/退出码、stdout/stderr 分离、增量/截断、运行/成功/失败/取消/超时/等待审批、后台任务、停止单任务、未读输出通知、主动命令和 Agent 调用区分；敏感环境变量脱敏。

**验收命令**：`python -m pytest tests/test_execution -q`。必须证明终态完整、取消和超时可达、进程退出后输出可读、主 Thread 不因 Child/后台任务失败而错误完成。

### PhaseD-B7 · Permission Center、Approval、Auto-review 与审计

`P0` / 2–3d / 依赖 B2、B6、Phase A/B / **owner: Composer 2.5**

**对应基线**：完整 D D8 + Phase B 权限契约。**涉及文件**：`protocol/`、`appserver/`、policy/approval service、`tests/test_approval/`、审计测试。**协议变化**：Approval、Auto-review capability、audit records；**Grok**：无。

**必须实现**：`read_only`、`workspace_write`、`ask_for_each_risky_action`、`allow_scoped_actions`、默认不可选的 `full_access`；作用域、过期、撤销、项目边界、approval_id、actor、策略版本；`approval.auto_review` 只读 reviewer 不扩大 sandbox/writable roots/network，连续拒绝达到阈值中断 turn。

**验收命令**：`python -m pytest tests/test_approval -q`。必须证明 UI 不存在时后端仍拒绝、一次 allow 不影响下一次、旧 policy 撤销、重启只恢复明确持久化策略、所有决定可回到 trace。

---

### PhaseD-B8 · Git Diff、Review、Finding、Checkpoint 与细粒度操作

`P0` / 4–5d / 依赖 B4、B5、B6、B7 / **owner: Composer 2.5**

**对应基线**：完整 D D9 和 §5.5/§5.6。**涉及文件**：`protocol/`、`appserver/`、Git/review/checkpoint services、`tests/test_review/`。**协议变化**：`review/start`、Review/Finding、checkpoint、git hunk actions；**Grok**：无。

**必须实现**：working tree/base/head/paths scope、P0–P3/info finding、evidence、diff hash、stale、review/read、幂等 request_id、checkpoint 创建/列出/读取/恢复、stage/unstage/revert、行级 comment 绑定 review/finding/file hash/line range；Review 不修改工作树。

**验收命令**：`python -m pytest tests/test_review -q`。必须覆盖非 Git 仓库、未跟踪文件、重复 start、断线补读、Agent 修复后 finding stale、单 hunk revert、checkpoint restore 后新 diff hash 和审计范围。

### PhaseD-B9 · File Preview、External Editor、Worktree 与执行环境

`P1` / 3–4d / 依赖 B4、B5、B7、B8 / **owner: Composer 2.5**

**对应基线**：完整 D D10/D11。**涉及文件**：`appserver/`、`protocol/`、文件预览/worktree/git backend、`tests/test_file_preview/`、`tests/test_worktrees/`。**协议变化**：FilePreview/ExternalEditor/Worktree lifecycle/handoff/conflict；**Grok**：无。

**必须实现**：只读预览、大小/编码/二进制占位、workspace 外拦截、系统编辑器明确动作、创建/打开/关闭 worktree、Thread 绑定、handoff、冲突/删除/路径不可用、未提交变更检查、半成品恢复、破坏性动作审批；不自动 commit 用户代码。

**验收命令**：`python -m pytest tests/test_file_preview -q; python -m pytest tests/test_worktrees -q`。必须证明路径安全、两个 Thread 不串目录、创建失败无半成品、handoff 可回滚、删除/prune 不误删未提交内容。

### PhaseD-B10 · Settings、ModelCatalog、max token Resolver 与安全存储

`P1` / 2–3d / 依赖 B2、B7、Phase 3 / **owner: Composer 2.5**

**对应基线**：完整 D D12 + 主计划 Phase 3。**涉及文件**：`protocol/`、`appserver/`、Phase 3 resolver/registry、secure storage adapter、`tests/test_settings/`、model tests。**协议变化**：Settings schema/capability、ModelSummary；**Grok**：无。

**必须实现**：global→project→workspace→thread/turn explicit 层级；Provider/model/reasoning/context 设置；系统密钥链；Key 无效/quota/模型不可用分开；设置迁移和回滚；真实 `model_id` 查找 ModelCatalog；按模型元数据或配置覆盖设置 `model_max_output_tokens`；未知模型采用高位 fallback 并携带 warning/source；不能批量写死 8192。

**验收命令**：`python -m pytest tests/test_settings -q`。必须证明层级覆盖、Desktop/CLI 一致、secret 不进日志/transcript/crash、模型摘要显示 `limit_source` 和 fallback、未知模型不静默伪装成已知模型。

### PhaseD-B11 · Skills、MCP、浏览器和可插拔能力后端

`P1` / 3–4d / 依赖 B2、B7、B10 / **owner: Composer 2.5**

**对应基线**：完整 D D13。**涉及文件**：`protocol/`、`appserver/`、capability/skill/MCP services、`tests/test_capabilities/`。**协议变化**：Capability/Skill/MCP projections；**Grok**：无。

**必须实现**：来源、启用状态、连接状态、权限、审计、错误和可取消生命周期；浏览器能力也必须走 capability、Tool、Approval、Review 链，不能成为特殊旁路窗口。

**验收命令**：`python -m pytest tests/test_capabilities -q`。必须证明未安装/未授权能力不显示可用、MCP/Skill 失败不永久卡住 Thread、返回数据可审计/收起/复制/定位来源。

### PhaseD-B12 · Notifications、长任务、恢复、replay 和孤儿回收

`P1` / 2–3d / 依赖 B3、B5、B6、B7 / **owner: Composer 2.5**

**对应基线**：完整 D D14 和 §5.4。**涉及文件**：`protocol/`、`appserver/`、notification/recovery/event log、`tests/test_recovery/`。**协议变化**：Notification/recovery/replay events；**Grok**：无。

**必须实现**：后台 turn、审批/用户输入/长命令/失败通知所需的公共事件；去重；断线保存 cursor；重新 initialize；Thread 元数据和 Item 补读；running/completed/interrupted/unknown → recovery_required；appserver/Host 重启后恢复真实状态。

**验收命令**：`python -m pytest tests/test_recovery -q`。必须覆盖断线、重复连接、事件缺口、replay、进程崩溃、孤儿任务、未完成 turn 和未知状态；前端 F12 只能消费这些状态。

### PhaseD-B13 · Runtime 打包、版本绑定、升级和发布门禁

`P0` / 4–5d / 依赖 B2、B3、B7、B10、B12 / **owner: Composer 2.5**

**对应基线**：完整 D D16。**涉及文件**：`packaging/`、`appserver/`、Python runtime/依赖、`.github/workflows/`、`tests/test_release/`、`docs/`。**协议变化**：package/appserver compatibility metadata；**Grok**：无。

**必须实现**：Windows/macOS/Linux runtime、Python 依赖、schema/generated types/appserver 版本绑定、签名/公证入口、更新失败回滚、脱敏 crash、诊断包和 checksum、首次启动/升级/回滚协议握手。

**验收命令**：`python -m pytest tests/test_release -q`。必须证明产物能启动 appserver 完成真实握手、版本不匹配可诊断、更新失败不删除旧版本、crash report 不含 Key/完整 prompt/完整工具输出；前端 F13 负责 UI build/error surface。

---

## §5 后端安全与上游复用

### 5.1 执行边界必须真正生效

```text
用户意图边界       输入、审批、取消、Review 接受
协议边界           schema、capability、版本、事件、错误
执行边界           appserver、tools、sandbox、子进程、workspace
呈现边界           Desktop、CLI、TUI、外部编辑器
```

安全规则必须在执行边界检查；不能只在前端隐藏按钮。Renderer 没有按钮时，后端仍然必须拒绝未授权 action。

### 5.2 Secret、路径和审计

- Key 只在完成当前请求所需的最小边界中存在；
- 完整环境变量、authorization header、Key、完整 prompt 和不可展示 reasoning 不进 transcript/log/crash；
- 所有路径 canonicalize，workspace 外访问由后端 policy 决定，symlink 不得绕过；
- 审批至少记录 `approval_id`、Thread/Turn/Item、action、scope、decision、actor、created_at、expires_at；
- Review、Finding、checkpoint、Git action 绑定具体版本或 diff hash；
- Tool/Child/Background Task 的失败、取消、超时和孤儿回收都产生可审计终态。

### 5.3 上游复用检查清单

每张涉及 OpenCode/Codex 的卡必须记录：

```text
上游仓库 / 官方文档 / 锁定 commit / license
复用模式：dependency | fork | vendor | subprocess | protocol-alignment | semantic-port
实际复用文件/测试
RxyCode 适配文件和不兼容证据
保留的上游语义
RxyCode 独有扩展：budget / lease / audit / redaction / model summary
验证命令 / 升级风险 / 回滚方式
```

OpenCode 的 Primary/Subagent、Task、权限和 Child Session 语义以 Phase B 附录 C 为准；Codex App Server、Thread/Turn/Item、双向 JSON-RPC、事件和审批边界以完整 D 附录 C 为准。未核验的第三方代码不得进入后端主链。

---

## §6 后端测试与验收

### 6.1 测试分层

| 层级 | 后端必须验证 | 前端配合 |
|---|---|---|
| Protocol contract | schema、版本、method、event、错误、生成类型 | 验证 protocol-client 消费 |
| Unit | resolver、状态机、权限 scope、diff hash、审计、脱敏 | 提供 UI 触发矩阵 |
| Integration | appserver、Provider、Tool、Git、Review、MCP、Child | 提供请求序列 |
| Process | spawn、握手、关闭、崩溃、重启、孤儿回收 | Electron Main 调用 |
| Recovery | cursor、replay、补读、未知状态、checkpoint、stale | Renderer 显示 recovery_required |
| E2E | 项目→Thread→工具→审批→变更→Review→恢复 | 完成 UI 操作链 |
| Security | Key、路径、IPC 入口、权限旁路、日志/crash 脱敏 | 验证 Renderer 无旁路 |
| Package smoke | runtime、schema、appserver 版本、真实握手 | 验证 Desktop build/错误页 |

### 6.2 后端最小 E2E

必须覆盖完整 D §8.2 的 20 个场景；后端必须特别证明：

1. 新项目 Thread 和流式 Item 的持久化；
2. 工具、审批、拒绝、取消、超时和失败终态；
3. Agent 修改文件、Review finding、diff hash、stale、checkpoint restore；
4. Parent→Child 的隔离、权限、预算、事件、失败和返回 Parent；
5. 两个 worktree 不串目录，Git 非仓库不伪造 review；
6. 未声明 capability 的请求后端拒绝并返回稳定错误；
7. appserver 崩溃/重启后 replay 和 recovery_required 正确；
8. `approval.auto_review` 的能力、策略、reviewer、理由和最终决定完整审计；
9. 真实 `model_id`、max token、fallback 和 warning 贯穿 CLI/TUI/Desktop；
10. Key、完整 prompt、工具原始输出和未授权路径不进入不安全输出。

### 6.3 后端机械门

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
git diff --check
python -m pytest -q
python -m pytest tests/test_protocol -q
python -m pytest tests/test_appserver -q
python -m pytest tests/test_projects -q
python -m pytest tests/test_threads -q
python -m pytest tests/test_execution -q
python -m pytest tests/test_approval -q
python -m pytest tests/test_review -q
python -m pytest tests/test_file_preview -q
python -m pytest tests/test_worktrees -q
python -m pytest tests/test_settings -q
python -m pytest tests/test_capabilities -q
python -m pytest tests/test_recovery -q
python -m pytest tests/test_release -q
```

如果某个测试目录仍未由对应卡创建，输出必须明确为 `BLOCKED_PREREQUISITE`；不得创建空测试文件伪造通过。

---

## §7 后端出口与前端交接

### 7.1 后端交付出口

- [ ] B1–B13 完成，且每张卡引用了完整 D 对应卡；
- [ ] schema 是唯一跨语言契约，生成类型和冻结快照一致；
- [ ] Thread/Turn/Item/Child/Review/Approval/Capability/ModelSummary 真实可持久化、可恢复、可审计；
- [ ] 权限、workspace、secret、路径、工具、Git 和 checkpoint 在执行边界生效；
- [ ] Phase 3 max token resolver 按真实 model id 工作，未知模型 fallback 有 warning，不统一写死；
- [ ] OpenCode/Codex 复用记录、许可证、commit、适配原因、测试和回滚齐全；
- [ ] appserver 的启动、关闭、崩溃、重启、replay、孤儿回收有真实输出；
- [ ] 前端已收到版本、capability snapshot、generated types、fixture 和兼容窗口；
- [ ] Composer 2.5 完成最终 diff、测试和 commit。

### 7.2 后端交接包

```yaml
handoff_id: D-B-HANDOFF-001
card: PhaseD-B5
source_baseline: PHASE-D-RXYCODE-DESKTOP.md#D5
branch: "<backend branch>"
commit: "<commit>"
protocol_version: "<version>"
capabilities:
  - threads
  - thread_fork
  - multi_agent
  - approval.auto_review
model_summary:
  provider_id: "<provider>"
  model_id: "<real-model-id>"
  model_max_output_tokens: 0
  limit_source: "<source>"
fixtures:
  success: "<path>"
  denied: "<path>"
  timeout: "<path>"
  reconnect: "<path>"
  child_tree: "<path>"
files_changed:
  - "<backend-only path>"
tests:
  - "<command and result>"
security_review: "<evidence>"
known_limitations:
  - "<limitation>"
frontend_questions:
  - "<unresolved consumer question>"
rollback: "<commit>"
owner: composer-2.5
```

### 7.3 完整 Phase D 的后端判定

只有完整 D 的功能、架构、体验、发布出口全部通过，且前端文档的 F 卡也通过，B 文档不能单独把 Phase D 标记为完成。后端只能输出：`READY_FOR_FULL_D_INTEGRATION`、`BLOCKED_PREREQUISITE` 或 `REJECTED_WITH_EVIDENCE`。

---

## 附录 A · 原 D 卡映射、接口冻结和交接模板

| 后端卡 | 完整 D 基线 | 后端主要文件 | 前端依赖 |
|---|---|---|---|
| B1 | D1/DR1 | appserver/schema/复用记录 | F1 |
| B2 | D2 | schema/protocol/types | F2 |
| B3 | D3 | appserver/lifecycle/recovery | F3 |
| B4 | D4 | project/workspace/path | F4 |
| B5 | D5/Phase B | Session/Child/events | F5/F6 |
| B6 | D7 | Tool/Command/BackgroundTask | F7 |
| B7 | D8 | Permission/Approval/Auto-review | F8 |
| B8 | D9 | Review/Finding/Checkpoint/Git | F9 |
| B9 | D10/D11 | FilePreview/Worktree | F10 |
| B10 | D12/Phase 3 | Settings/ModelSummary/secure storage | F11 |
| B11 | D13 | Capability/Skill/MCP/browser | F11 |
| B12 | D14 | Notification/replay/recovery | F12 |
| B13 | D16 | Runtime/package/version compatibility | F13 |

### A.1 协议冻结检查单

```text
schema changed?
  → update protocol/schema.json
  → generate Python/TypeScript types
  → update frozen snapshot
  → run contract tests
  → update capability/version/error docs
  → provide frontend fixture
  → run recovery/security tests
  → commit and handoff
```

**完成定义**：本文新增的是后端执行边界，不改变完整 D 的原始示例、模型适配、协议语义和验收要求；任何冲突必须回到完整 D 公共基线和协议契约测试解决。
