> **增强卡施工已拆出**：[PHASE-G-BACKEND-GX.md](./PHASE-G-BACKEND-GX.md)（本分支只改这份 + 本文件）。不要再往本文追加 GX。

# PHASE-G-BACKEND（合并版）· 后端开发执行文档

> **本文档由两部分合并而成**：
> - **Part 1 权威后端拆分**（原 `PHASE-G-BACKEND-RXYCODE-DESKTOP.md`）：PhaseG-B1-B13 卡、协议变更单、文件白名单——**后端验收以此为准**
> - **Part 2 后端开工清单**（原 `PHASE-G-BACKEND-KICKOFF.md`）：给后端开发者的开工速查（卡表/交接项/增强卡/纪律）
>
> **配套文件**：公共基线+总手册+增强卡见 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md)；前端见 [`PHASE-G-FRONTEND.md`](../frontend/PHASE-G-FRONTEND.md)。
>
> **合并日期**：2026-08-11　**合并原则**：各部分正文一字未改。


---

# Part · 1 · 权威后端拆分（B1–B13）

> **本部分来源**：原 `PHASE-G-BACKEND-RXYCODE-DESKTOP.md`（合并时正文一字未改，仅链接映射到新文件名）
# Phase G-B · RxyCode Desktop 后端开发执行文档

> **文档定位**：本文是 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的后端执行拆分文档，不替换完整 G 文档，也不删除其中的产品定义、协议示例、任务卡验收和完整出口标准。完整 G 文档是公共基线；本文把 appserver、协议、Session 真相、权限、工具、Git、恢复、能力和发布 runtime 责任拆出来，使后端开发者可以独立施工、测试和交接。
>
> **产品名称**：RxyCode Desktop。本文保持完整 G 文档中对 Codex App Server、OpenCode 子代理、Phase 3 模型上限摘要、Phase A/D/F 公共契约和 LinkAgent 扩展边界不变。
>
> **前置条件**：主计划 Phase 0/1/2/3/4 + Phase A/D/F 公共契约已冻结；`appserver/`、`protocol/schema.json`、Phase 3 resolver/summary 和既有 backend tests 是否真实存在必须以工作区检查为准。缺失时只能输出 `BLOCKED_PREREQUISITE`，不得用临时 mock 代替。
>
> **主文档关系**：完整功能、示例代码和总体验收以 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 为唯一基线；本文只增加后端 owner、后端文件白名单、后端任务卡和前后端交接要求。
>
> **基线日期**：2026-08-05　**建议工时**：与完整 Phase G 的 12–16 周总估算并行拆分，不得将两份文档的工时简单相加　**任务卡**：PhaseG-B1–PhaseG-B13（主链 13 张）＋ **追加卡 PhaseG-B14–B18**（P3 批 · Codex 对齐批，见 §4 卡区；不属主链 26 卡，主链出口门槛不变，立项依据 `research/2026-08-12-agent-native-computer-use-research.md`）

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必须先读) | 模型分工、施工回路、硬约束和协作方式 |
| [§1 拆分真相与文件边界](#1-拆分真相与文件边界) | 后端拥有的唯一真相和前端禁止触碰的部分 |
| [§2 后端架构与 App Server 边界](#2-后端架构与-app-server-边界) | schema、appserver、Session、工具、恢复和发布 runtime |
| [§3 公共接口、事件和状态契约](#3-公共接口事件和状态契约) | 前端唯一可以消费的稳定接口 |
| [§4 后端任务卡](#4-后端任务卡) | PhaseG-B1–F13 具体施工顺序 |
| [§5 后端安全与上游复用](#5-后端安全与上游复用) | 权限、secret、OpenCode/Codex、审计和隔离 |
| [§6 后端测试与验收](#6-后端测试与验收) | 协议、单元、进程、恢复、E2E 和发布验证 |
| [§7 后端出口与前端交接](#7-后端出口与前端交接) | 什么条件下后端可以交付给完整 F |
| 附录 A | 原 D 卡映射、接口冻结和交接模板 |

---

## §0 执行手册（必须先读）

### 0.1 本文解决什么问题

完整 F 的 Desktop 体验必须建立在后端唯一真相之上。前端可以单独开发，但它不能自行决定：

```text
Thread/Turn/Item 的生命周期
Child Session 的隔离、预算、权限和事件
Tool/Command/Git/Review 的真实执行结果
Approval、Auto-review、Secret、Workspace 和路径安全
模型 provider、model_id、max output token 的解析
重连、replay、cursor、checkpoint、stale 和恢复状态
```

本文把上述能力交给后端文档施工；前端只通过 `protocol/schema.json`、生成类型、JSON-RPC/JSONL 和 capability handshake 消费。本文不复制完整 F 的产品和协议定义；完整 F §4/§5 的对象、示例 JSON、状态机、错误码和出口是强制基线。

### 0.2 模型分工（硬约束）

| 模型 | 负责 | 禁止 |
|---|---|---|
| **Composer 2.5** | **主写全部后端代码**：appserver、protocol/schema、Session/Thread/Turn/Item、权限、工具、Git、Review、恢复、模型摘要接入、测试、runtime packaging 和最终合并 | 不得把后端核心交给 Grok；不得为了配合前端复制第二套业务逻辑 |
| **Grok 4.5** | 仅做前端文档指定的视觉辅助；可协助阅读日志、整理复现截图，但不拥有后端实现 | 不写 Python/Rust 后端；不改 schema、权限、数据库、appserver 或后端测试主契约 |
| **Sonnet 5（可选）** | 对 F2/F5/F7/F8/F9/F12 的 diff 做状态、权限、secret、并发、恢复和进程泄漏预审 | 不替代 Composer 实现，不作为完成标准 |
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

缺少 `appserver/`、`protocol/schema.json` 或目标测试目录时，F1 只能记录阻塞，不得用一个临时 Python HTTP 服务或内存字典代替正式产物。

### 0.4 每张后端卡的固定回路

```text
LOCATE → READ 完整 F 对应卡与前端消费点 → WRITE
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
| DC-F1 | `protocol/schema.json` 是跨语言契约唯一来源；先更新 schema/生成类型/contract test，再通知前端 | 前后端字段漂移 |
| DC-F2 | Thread/Turn/Item/Child/Review/Approval 的后端状态是唯一真相，UI 不能反向写状态 | 多端结果不一致 |
| DC-F3 | 所有异步动作有 started/progress/completed/failed/cancelled/waiting 终态，等待审批可取消和超时 | stalled、重试重复、无法恢复 |
| DC-F4 | 权限、workspace、sandbox、secret、路径和网络策略必须在执行边界生效 | UI 隐藏按钮不能算安全 |
| DC-F5 | Phase 3 的 resolver/ModelCatalog 是 max token 唯一来源；未知模型走明确高位默认和 warning，不在 Desktop 猜测 | 模型上限错误或被统一写死 |
| DC-F6 | OpenCode/Codex 能直接复用的核心优先 dependency/fork/vendor/subprocess；semantic-port 必须有不兼容证据 | 重造等价 Runtime |
| DC-F7 | 事件含 `event_id`、对象 id、`sequence`、时间和 payload；重放、去重、乱序和幂等由后端保证 | 前端被迫猜事件顺序 |
| DC-F8 | 日志、transcript、trace、crash payload 和错误不能泄露 Key、完整环境、未授权路径或不可展示原始 reasoning | secret/隐私泄漏 |

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
PHASE-G-DESKTOP.md
  = 完整产品、协议、示例、H1–H16、完整安全/测试/出口标准的公共基线

PHASE-G-BACKEND.md
  = appserver/schema/Session/权限/工具/Git/恢复/模型摘要/runtime 的施工责任

PHASE-G-FRONTEND.md
  = Electron/TypeScript/React/protocol-client/视觉/前端测试的消费责任
```

完整 F §5.1–§5.8 的初始化、事件、Review、checkpoint、capability 和恢复示例必须原样作为后端契约测试 fixture；后端可以增加版本字段或 `x-rxycode-*` 扩展，但不能改变已有字段语义而不升级 protocol major。

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
PrimaryRuntime / Phase D Child / Phase F Coordinator
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
6. Phase D Child Session 的 parent/child、隔离、预算、权限、事件和终态；
7. Phase 3 的 `model_id` → ModelCatalog → `model_max_output_tokens` / fallback resolver 摘要；
8. LinkAgent 只依赖的公共协议，不依赖 Desktop 内部对象。

### 2.3 OpenCode/Codex 复用边界

Phase D 的 OpenCode 复用规则以 [`PHASE-D-ISOLATED-SUBAGENT.md`](./PHASE-D-ISOLATED-SUBAGENT.md) 附录 D 为准；Phase G 的 Codex/App Server 复用规则以完整 F 附录 D 为准。后端必须先做 dependency/fork/vendor/subprocess 审计，只有明确不兼容时才 semantic-port，并记录 commit、许可证、适配原因、测试和回滚。

---

## §3 公共接口、事件和状态契约

### 3.1 初始化握手（与完整 F §5.1 保持不变）

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

### 3.3 事件包络（与完整 F §5.3 保持不变）

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

Review 请求、response、通知和错误码必须保持完整 F §5.5 原文：`review/start`、`review/read`、`review/started`、`review/progress`、`review/finding`、`review/completed`、`review/stale`、`review/failed`、`review/cancelled`，以及 `REVIEW_SCOPE_INVALID`、`REVIEW_DIFF_UNAVAILABLE`、`REVIEW_ALREADY_RUNNING`、`REVIEW_CANCELLED`、`REVIEW_TIMEOUT`、`REVIEW_PROTOCOL_MISMATCH`。

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

每张 B 卡共同继承完整 F §6.0 的四项完成判据；完整 F 对应 F 卡的验收要求不得被本文缩减。

### PhaseG-B1 · 后端基线、App Server 包边界与上游复用冻结

`P0` / 1–2d / 无依赖，但依赖 Phase 4 壳、Phase 3 模型摘要和 Phase A/D/F 公共契约 / **owner: Composer 2.5**

**对应基线**：完整 F H1 + 完整 F 附录 D DR1。**涉及文件**：`appserver/`、`protocol/schema.json`、`protocol/`、后端测试、`docs/decisions/desktop-upstream-reuse.md`。**协议变化**：none；**Grok**：无。

**操作步骤**：实际检查 appserver 启动入口、协议输出、schema、生成流程、Phase 3 resolver、Phase F 消费面；锁定 Codex App Server/OpenCode 复用来源、commit、许可证和路径；输出“复用/适配/禁止重写”清单。

**验收命令**：`Test-Path appserver; Test-Path protocol\schema.json; python -m pytest tests/test_protocol -q`。缺失时输出带清单的 `BLOCKED_PREREQUISITE`。

**完成判据**：

- [x] App Server 入口、stdout 协议、stderr 日志和版本已确认；
- [x] schema 唯一来源和生成类型流程已确认；
- [x] 上游复用决策、许可证和回滚已记录；
- [x] Composer 2.5 提交独立 commit，前端可以据此开工。

> 2026-08-19 · `feat/phase-g-backend` · luna R3 **PASS**（R1/R2 FAIL 已按最小清单修完）。DR1 判据 4（完整 Thread/Turn/Item 契约）显式未完成，归 B2/B5/B7/B12。

### PhaseG-B2 · Protocol handshake、能力发现、错误模型和生成契约

`P0` / 2–3d / 依赖 F1 / **owner: Composer 2.5**

**对应基线**：完整 F H2。**涉及文件**：`protocol/schema.json`、`protocol/`、`tests/test_protocol/`、generated types。**协议变化**：`initialize`、capability、error schema；**Grok**：无。

**必须实现**：协议版本范围、client/server capability、stable error code、timeout、closed、unsupported、overloaded、configuration missing、protocol mismatch；更新 schema、生成 TypeScript/Python 类型和冻结快照。

**验收命令**：`python -m pytest tests/test_protocol -q`。必须覆盖新旧版本、能力缺失、错误可重试性、未知字段处理和 schema/生成类型一致性；完成后交接给前端 J2。

> 2026-08-19 · `feat/phase-g-backend` · luna R3 **PASS**（R1/R2 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-001`。

### PhaseG-B3 · App Server 进程、生命周期、日志和恢复底座

`P0` / 2–3d / 依赖 F1、F2 / **owner: Composer 2.5**

**对应基线**：完整 F H3。**涉及文件**：`appserver/`、进程生命周期、日志/恢复模块、`tests/test_appserver/`。**协议变化**：process lifecycle/error events；**Grok**：无。

**必须实现**：启动/优雅关闭/超时/崩溃/重启/孤儿任务回收、stdout 只输出协议、stderr/受控日志输出、共享 appserver 的多窗口策略、临时资源释放和 recovery_required 状态。

**验收命令**：`python -m pytest tests/test_appserver -q`。必须覆盖启动失败、立即崩溃、强制关闭、重启恢复、重复启动退出 20 次和未完成任务不伪造完成；Electron Main 的进程调用由前端 J3 联调。

> 2026-08-19 · `feat/phase-g-backend` · luna R2 **PASS**（R1 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-002`。

### PhaseG-B4 · Project / Workspace 服务与路径边界

`P1` / 2–3d / 依赖 F2、F3 / **owner: Composer 2.5**

**对应基线**：完整 F H4。**涉及文件**：`appserver/`、`protocol/`、workspace/project store、`tests/test_projects/`。**协议变化**：Project/Workspace methods/events；**Grok**：无。

**必须实现**：最近项目、添加本地目录、显示名/真实路径分离、workspace、branch/worktree、不可访问/不存在/Git 非仓库错误、项目级设置作用域、移除不删除代码、路径 canonicalize 和 symlink 防绕过。

**验收命令**：`python -m pytest tests/test_projects -q`。必须证明两个项目不串 cwd、新 Thread 必须绑定 workspace、workspace 变更产生上下文事件、workspace 外路径后端拒绝。

> 2026-08-19 · `feat/phase-g-backend` · luna R2 **PASS**。协议变更单 `G-PROTOCOL-003`。

### PhaseG-B5 · Thread / Turn / Item / Child Session 真相

`P0` / 3–4d / 依赖 F2、F3、F4、Phase D / **owner: Composer 2.5**

**对应基线**：完整 F H5 + Phase D 附录 D。**涉及文件**：`appserver/`、`protocol/`、session store、`tests/test_threads/`、Child event tests。**协议变化**：Thread/Turn/Item、parent/child cursor、replay；**Grok**：无。

**必须实现**：Thread 新建/恢复/重命名/归档/删除/分叉；项目/workspace/status/time filter 所需字段；Turn start/steer/interruption/retry；Item 持久化分页；Parent/Child 的独立 session、Context、Runtime、Tool/Permission、Budget、Trace、lease、事件和生命周期；`parent_session_id`、`root_session_id`、cursor 一致。

**验收命令**：`python -m pytest tests/test_threads -q`。必须证明分叉不改父 Thread、Child 工具/审批/预算不混入 Parent、重试幂等、归档可恢复、Child 失败/取消/孤儿可审计；完成后提供 J5 fixture。

> 2026-08-19 · `feat/phase-g-backend` · luna R5 **PASS**（R1–R4 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-004`。H5 fixture 在 `tests/test_threads/fixtures/`。

### PhaseG-B6 · Tool、Command、Background Task 执行与事件

`P0` / 2–3d / 依赖 F5、Phase A/D / **owner: Composer 2.5**

**对应基线**：完整 F H7。**涉及文件**：`protocol/`、`appserver/`、tool runner、background task store、`tests/test_execution/`。**协议变化**：Tool/Command/BackgroundTask item states；**Grok**：无。

**必须实现**：工具名/参数摘要/风险、命令/cwd/环境摘要/退出码、stdout/stderr 分离、增量/截断、运行/成功/失败/取消/超时/等待审批、后台任务、停止单任务、未读输出通知、主动命令和 Agent 调用区分；敏感环境变量脱敏。

**验收命令**：`python -m pytest tests/test_execution -q`。必须证明终态完整、取消和超时可达、进程退出后输出可读、主 Thread 不因 Child/后台任务失败而错误完成。

> 2026-08-19 · `feat/phase-g-backend` · luna R4 **PASS**（R1–R3 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-005`。

### PhaseG-B7 · Permission Center、Approval、Auto-review 与审计

`P0` / 2–3d / 依赖 F2、F6、Phase A/D / **owner: Composer 2.5**

**对应基线**：完整 F H8 + Phase D 权限契约。**涉及文件**：`protocol/`、`appserver/`、policy/approval service、`tests/test_approval/`、审计测试。**协议变化**：Approval、Auto-review capability、audit records；**Grok**：无。

**必须实现**：`read_only`、`workspace_write`、`ask_for_each_risky_action`、`allow_scoped_actions`、默认不可选的 `full_access`；作用域、过期、撤销、项目边界、approval_id、actor、策略版本；`approval.auto_review` 只读 reviewer 不扩大 sandbox/writable roots/network，连续拒绝达到阈值中断 turn。

**验收命令**：`python -m pytest tests/test_approval -q`。必须证明 UI 不存在时后端仍拒绝、一次 allow 不影响下一次、旧 policy 撤销、重启只恢复明确持久化策略、所有决定可回到 trace。

> 2026-08-19 · `feat/phase-g-backend` · luna R7 **PASS**（R1–R6 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-006`。验收 `tests/test_approval` 28 passed。

---

### PhaseG-B8 · Git Diff、Review、Finding、Checkpoint 与细粒度操作

`P0` / 4–5d / 依赖 F4、F5、F6、F7 / **owner: Composer 2.5**

**对应基线**：完整 F H9 和 §5.5/§5.6。**涉及文件**：`protocol/`、`appserver/`、Git/review/checkpoint services、`tests/test_review/`。**协议变化**：`review/start`、Review/Finding、checkpoint、git hunk actions；**Grok**：无。

**必须实现**：working tree/base/head/paths scope、P0–P3/info finding、evidence、diff hash、stale、review/read、幂等 request_id、checkpoint 创建/列出/读取/恢复、stage/unstage/revert、行级 comment 绑定 review/finding/file hash/line range；Review 不修改工作树。

**验收命令**：`python -m pytest tests/test_review -q`。必须覆盖非 Git 仓库、未跟踪文件、重复 start、断线补读、Agent 修复后 finding stale、单 hunk revert、checkpoint restore 后新 diff hash 和审计范围。

> 2026-08-19 · `feat/phase-g-backend` · luna **PASS**（R1–R7 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-007`。验收 `tests/test_review` 18 passed。

### PhaseG-B9 · File Preview、External Editor、Worktree 与执行环境

`P1` / 3–4d / 依赖 F4、F5、F7、F8 / **owner: Composer 2.5**

**对应基线**：完整 F H10/H11。**涉及文件**：`appserver/`、`protocol/`、文件预览/worktree/git backend、`tests/test_file_preview/`、`tests/test_worktrees/`。**协议变化**：FilePreview/ExternalEditor/Worktree lifecycle/handoff/conflict；**Grok**：无。

**必须实现**：只读预览、大小/编码/二进制占位、workspace 外拦截、系统编辑器明确动作、创建/打开/关闭 worktree、Thread 绑定、handoff、冲突/删除/路径不可用、未提交变更检查、半成品恢复、破坏性动作审批；不自动 commit 用户代码。

**验收命令**：`python -m pytest tests/test_file_preview -q; python -m pytest tests/test_worktrees -q`。必须证明路径安全、两个 Thread 不串目录、创建失败无半成品、handoff 可回滚、删除/prune 不误删未提交内容。

> 2026-08-19 · `feat/phase-g-backend` · luna **PASS**（R1–R4 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-008`。验收 `tests/test_file_preview` + `tests/test_worktrees` 12 passed。

### PhaseG-B10 · Settings、ModelCatalog、max token Resolver 与安全存储

`P1` / 2–3d / 依赖 F2、F7、Phase 3 / **owner: Composer 2.5**

**对应基线**：完整 F H12 + 主计划 Phase 3。**涉及文件**：`protocol/`、`appserver/`、Phase 3 resolver/registry、secure storage adapter、`tests/test_settings/`、model tests。**协议变化**：Settings schema/capability、ModelSummary；**Grok**：无。

**必须实现**：global→project→workspace→thread/turn explicit 层级；Provider/model/reasoning/context 设置；系统密钥链；Key 无效/quota/模型不可用分开；设置迁移和回滚；真实 `model_id` 查找 ModelCatalog；按模型元数据或配置覆盖设置 `model_max_output_tokens`；未知模型采用高位 fallback 并携带 warning/source；不能批量写死 8192。

**验收命令**：`python -m pytest tests/test_settings -q`。必须证明层级覆盖、Desktop/CLI 一致、secret 不进日志/transcript/crash、模型摘要显示 `limit_source` 和 fallback、未知模型不静默伪装成已知模型。

**完成判据**：
- [x] `settings/get|set|models|diagnose|rollback` 协议落地（G-PROTOCOL-009）
- [x] global→project→workspace→thread/turn 覆盖 + Desktop/CLI 同一解释
- [x] secret 走 credential_store，不进日志/JSON/crash
- [x] 真实 model_id 查 ModelCatalog；未知模型高位 fallback + warning，不伪装
- [x] 单 commit

### PhaseG-B11 · Skills、MCP、浏览器和可插拔能力后端

`P1` / 3–4d / 依赖 F2、F7、F10 / **owner: Composer 2.5**

**对应基线**：完整 F H13。**涉及文件**：`protocol/`、`appserver/`、capability/skill/MCP services、`tests/test_capabilities/`。**协议变化**：Capability/Skill/MCP projections；**Grok**：无。

**必须实现**：来源、启用状态、连接状态、权限、审计、错误和可取消生命周期；浏览器能力也必须走 capability、Tool、Approval、Review 链，不能成为特殊旁路窗口。

**验收命令**：`python -m pytest tests/test_capabilities -q`。必须证明未安装/未授权能力不显示可用、MCP/Skill 失败不永久卡住 Thread、返回数据可审计/收起/复制/定位来源。

**完成判据**：
- [x] `capabilities/list|get|set_enabled|invoke|cancel|audit` 协议落地（G-PROTOCOL-010）
- [x] 未安装/未授权 available=false；浏览器非旁路
- [x] Skill/MCP 失败终态 + 可取消 + 不卡住 Thread
- [x] 返回可审计/收起/复制/定位来源
- [x] 单 commit

### PhaseG-B12 · Notifications、长任务、恢复、replay 和孤儿回收

`P1` / 2–3d / 依赖 F3、F5、F6、F7 / **owner: Composer 2.5**

**对应基线**：完整 F H14 和 §5.4。**涉及文件**：`protocol/`、`appserver/`、notification/recovery/event log、`tests/test_recovery/`。**协议变化**：Notification/recovery/replay events；**Grok**：无。

**必须实现**：后台 turn、审批/用户输入/长命令/失败通知所需的公共事件；去重；断线保存 cursor；重新 initialize；Thread 元数据和 Item 补读；running/completed/interrupted/unknown → recovery_required；appserver/Host 重启后恢复真实状态。

**验收命令**：`python -m pytest tests/test_recovery -q`。必须覆盖断线、重复连接、事件缺口、replay、进程崩溃、孤儿任务、未完成 turn 和未知状态；前端 J12 只能消费这些状态。

**完成判据**：
- [x] `recovery/*` + `notifications/*` 协议落地（G-PROTOCOL-011）
- [x] 通知去重、cursor 单调、replay/gap、重启 recovery_required
- [x] 不伪造 complete；孤儿回收；initialize 补读
- [x] 单 commit

### PhaseG-B13 · Runtime 打包、版本绑定、升级和发布门禁

`P0` / 4–5d / 依赖 F2、F3、F7、F10、F12 / **owner: Composer 2.5**

**对应基线**：完整 F H16。**涉及文件**：`packaging/`、`appserver/`、Python runtime/依赖、`.github/workflows/`、`tests/test_release/`、`docs/`。**协议变化**：package/appserver compatibility metadata；**Grok**：无。

**必须实现**：Windows/macOS/Linux runtime、Python 依赖、schema/generated types/appserver 版本绑定、签名/公证入口、更新失败回滚、脱敏 crash、诊断包和 checksum、首次启动/升级/回滚协议握手。

**验收命令**：`python -m pytest tests/test_release -q`。必须证明产物能启动 appserver 完成真实握手、版本不匹配可诊断、更新失败不删除旧版本、crash report 不含 Key/完整 prompt/完整工具输出；前端 J13 负责 UI build/error surface。

**完成判据**：
- [x] 三端 runtime 绑定 + initialize.package + release/status|diagnose（G-PROTOCOL-012）
- [x] 更新失败保留旧版；CURRENT.txt 回滚；crash 脱敏
- [x] 真实进程握手 + check_bind 发布门禁
- [x] 单 commit

---

### PhaseG-B14 · CLI-Hub 接入与 CLI 工具桥接器（P3 批追加卡）

> **性质声明**：本卡与 B15–B18 为 **P3 批（Codex 对齐批）追加卡**，不属于主链 26 卡（B1–B13 + H1–H13），不改变主链出口门槛（主链出口达标后才进入 P3 批，纪律见 PHASE-G-DESKTOP.md §3 与 §8）。立项依据：`research/2026-08-12-agent-native-computer-use-research.md` §3/§5（CLI-Anything 混合集成）。

`P1` / 3–4d / 依赖 Phase D 子代理隔离（SB3）+ B6 工具执行 / **owner: Composer 2.5**

**对应基线**：CLI-Anything（Apache-2.0）CLI-Hub 机制（semantic-port，复用模式见 §5.3 清单）。**涉及文件**：`appserver/handlers/cli_tools.py`（新增）、`appserver/cli_hub_service.py`（新增：registry 拉取/缓存/venv 管理）、`tools/registry.py`（`cli:` 前缀注册扩展）、`protocol/schema.json`（`cli/*` 方法）、`tests/test_cli_bridge.py`（新增）、`scripts/cli_venv.py`（新增：独立 venv 创建/解析）。**协议变化**：`cli/list`、`cli/install`、`cli/launch`（new_method，登记 GXn-PROTO）；**Grok**：无。

> ⚠️ **2026-08-18 追加注记 · 下方「必须实现」第 3 条会击穿前缀缓存基线，实施前先读这段**
>
> 第 3 条原文是「CLI 工具以 `cli:<软件名>` 前缀**注册进 `tools/registry.py`**」。`tools/registry.py` 的工具名进 LLM 工具 schema，所以照此实施会有三个后果：
>
> 1. 工具条数随用户装了多少软件而变 → `tools_digest` 随之变 → **这个能力不可能是 PHASE-K 的 L0**，只能是 L1（开关要重开会话）；
> 2. 常驻 token 成本随用户环境线性增长，且**条数不受我们控制**；
> 3. **最严重**：`cli/install` 一执行就改变 `tools_digest`，**整个前缀缓存当场失效**。用户装个软件，下一轮命中率归零——97% / 95% 的缓存基线扛不住这个。
>
> **处置**（[`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) §6.4 / HN2 / N13）：第 3 条改为——`cli:<软件名>` **只作为 `cli_list` / `cli_run` 两个 agent 工具的参数取值存在，不进 `tools/registry.py`**；具体软件的 schema 由 `cli_list` 在调用时返回（数据源就是本卡已有的 `cli/<tool>/schema`，不新建）。这是 PHASE-K K9/K10 给 skills 用的同一套渐进披露机制。
>
> **其余六条必须实现项、协议方法、验收命令、完成判据一律不动。** `cli:` 命名空间、D13 同名冻结纪律、来源标签全部保留——它们管的是软件标识，与工具注册是两回事，那部分设计是对的。N13 会补一条断言：**装 0 / 1 / 20 个软件时 `PrefixProfile.identity()` 逐字节相同**。

**必须实现**：
- CLI-Hub registry 拉取与本地缓存（`~/.cli-hub/*_cache.json`，TTL 1 小时，失败回退缓存）——语义对齐 CLI-Anything `registry.py`；
- **独立 venv 隔离**：每个已安装 CLI（或共享 cli 环境）运行于独立 venv，经子进程调用（复用 B6 ExecSessionManager 隔离先例），**禁止污染 RxyCode 主环境**；
- **工具注册命名空间冻结**：CLI 工具以 `cli:<软件名>` 前缀注册进 `tools/registry.py`，与内置工具隔离；沿用 D13 工具名冻结纪律（**禁止同名覆盖**）；
- 工具来源标签（builtin / cli-hub / self-generated）进工具元数据（G13 能力面板消费）；
- 软件缺失/venv 创建失败/命令超时的结构化错误（含安装指引——语义对齐 CLI-Anything `_backend.py` 的 `shutil.which` + 指引模式）；
- **跨平台**：venv 路径三端差异（Windows `Scripts\python.exe` vs POSIX `bin/python`）统一解析；`shutil.which` 语义一致；**禁止引入 cygpath/bash 依赖**（直接 subprocess 调 python/pip，规避 CLI-Anything 的 Windows 已知坑）；
- 冲突解法（报告 §5.2 C-A~C-E）落实现：`cli:` 命名空间（C-A）、独立 venv（C-B）、registry 优先决策规则（C-C）、来源标签（C-D）、生成质量三级阶梯（C-E，含"生成失败模式"记录接口）。

**验收命令**：`python -m pytest tests/test_cli_bridge -q; python -m pytest tests/test_execution -q`（B6 回归门禁）。必须证明：安装/卸载/启停/launch 全链路（用一个真实 registry 软件或本地 fixture 包）、venv 隔离（主环境 site-packages 不受污染）、`cli:` 前缀工具不与内置工具冲突、来源标签正确、三端 venv 路径解析单测通过。

**完成判据**：
- [x] `cli/list`/`cli/install`/`cli/launch` 协议落地（含 GXn-PROTO 登记）；
- [x] 独立 venv 隔离验证（主环境零污染）；
- [x] `cli:` 前缀命名空间 + 同名冻结纪律生效；
- [x] 来源标签进入工具元数据；
- [x] 三端 venv 路径/子进程调用单测通过；
- [x] 主链 B6 回归无破坏；单 commit（批次 baseline 按既有出口纪律执行）。

> 2026-08-19 · `feat/phase-g-backend` · luna **PASS**（R1–R4 FAIL 已按最小清单修完）。协议变更单 `G-PROTOCOL-013`。验收 `tests/test_cli_bridge` 16 passed + `tests/test_execution` 回归。N13：`cli:<name>` 不进 `tools/registry.py`。

### PhaseG-B15 · 生成器能力（HARNESS 7 阶段技能化）（P3 批追加卡）

`P2` / 2–3d / 依赖 B14 / **owner: Composer 2.5**

**对应基线**：CLI-Anything（Apache-2.0）HARNESS.md + OpenCode 参考实现（`opencode-commands/`，semantic-port + vendor 混合，§5.3 清单记录 license/锁定 commit）。**涉及文件**：`docs/agents/harness/HARNESS.md`（vendor，新增）、`appserver/skills/` 或 `tools/skill_manager.py` 注册的 7 阶段技能模板（新增）、`tests/test_harness_skill.py`（新增）。**协议变化**：none（复用技能通道）；**Grok**：无。

**必须实现**：
- HARNESS.md vendor 入库（Apache-2.0 合规：保留版权头与 LICENSE 记录，§5.3 上游复用清单填写）；
- 7 阶段指令模板（Analyze→Design→Implement→Plan Tests→Write Tests→Document→Publish）改编为 RxyCode 技能（基于 OpenCode 参考实现的 `subtask: true` 模式）；含 `/refine` 迭代与 `/validate` 命令；
- 生成产物直接落到 B14 的独立 venv 通道（生成→安装→launch 闭环）；
- **挂起条件（C8）**：Phase B 缓存落地前本卡不启动；启动前须先完成 B14 消费型集成并记录生成失败模式；
- 生成质量三级阶梯落地：生成 → refine → 降级手写 command 包装（记录回灌）。

**验收命令**：`python -m pytest tests/test_harness_skill -q`。必须证明技能模板可触发、HARNESS 规范完整 vendor（含 license 记录）、失败模式记录接口可用；**挂起条件未满足时输出 BLOCKED_PREREQUISITE（不 mock）**。

**完成判据**：
- [x] HARNESS.md vendor + license 合规记录（§5.3 清单）；
- [x] 7 阶段技能模板 + refine/validate 注册；
- [x] 生成→安装→launch 闭环（B14 通道）；
- [x] 挂起条件声明 + BLOCKED_PREREQUISITE 路径验证；
- [x] 单 commit。

> 2026-08-19 · `feat/phase-g-backend` · luna **PASS**。C8 真实基线 91.22% < 99%，generate/refine/wrapper 均 `BLOCKED_PREREQUISITE`（未 mock）。vendor `docs/agents/harness/` 锁定 `6f372d36f8ea43dd2af23fda96646c8088ac7d2f`。闭环实现于 `_install_launch`，仅缓存落地后执行。

### PhaseG-B16 · 定时任务调度器（P3 批追加卡）

`P1` / 3–4d / 依赖 B5（Thread 服务）+ B12（长任务恢复）/ **owner: Composer 2.5**

**对应基线**：现有 `scheduler/`（cron.py + manager.py，已存在，先读其 README/代码再扩展）。**涉及文件**：`scheduler/`（扩展）、`appserver/handlers/schedule.py`（新增）、`protocol/schema.json`（`schedule/*` 方法）、`tests/test_schedule.py`（新增）。**协议变化**：`schedule/list`、`schedule/create`、`schedule/update`、`schedule/delete`、`schedule/toggle`（new_method，登记 GXn-PROTO）；**Grok**：无。

**必须实现**：
- 触发规则：间隔（每 N 分钟/小时/天）+ 指定时间；动作：运行指定会话/命令/技能；
- **跨平台（关键决策）**：调度在**应用层用 asyncio 实现**（间隔触发 + 到点触发），**不依赖系统 cron / launchd / Task Scheduler**——保证 Windows/Linux/macOS 三端行为一致；
- 任务持久化 + 崩溃恢复（appserver 重启后任务状态恢复，对齐 B12 恢复语义）；孤儿任务回收；
- 任务执行复用 B5 Thread 通道（运行指定会话 = 恢复 Thread + 发送消息，不得绕过权限/预算）；
- 并行执行上限与排队（防任务风暴）；执行结果审计（对齐 §5.2）。

**验收命令**：`python -m pytest tests/test_schedule -q; python -m pytest tests/test_threads -q`（B5 回归门禁）。必须证明：间隔/到点两种规则、重启恢复、三端行为一致（纯 asyncio 无平台依赖）、任务执行走 B5 通道不绕过权限、并发上限生效、审计可回溯。

**完成判据**：
- [x] `schedule/*` 协议落地（含 GXn-PROTO 登记）；
- [x] 应用层调度（无系统 cron 依赖）实现并三端一致；
- [x] 持久化 + 崩溃恢复 + 孤儿回收；
- [x] 任务执行走 B5 通道（权限/预算不可绕过）；
- [x] B5 回归无破坏；单 commit。

> 2026-08-19 · `feat/phase-g-backend` · luna **PASS**。协议变更单 `G-PROTOCOL-014`。验收 `tests/test_schedule` 10 passed + `tests/test_threads` 回归。

### PhaseG-B17 · 回收站后端（P3 批追加卡）

`P1` / 2–3d / 依赖 B5 / **owner: Composer 2.5**

**对应基线**：无（新增能力；语义对齐 Codex 会话删除映射）。**涉及文件**：`appserver/`（Thread 服务扩展）、`protocol/schema.json`（`thread/deleted_at` 字段 + `thread/purge` 方法）、`tests/test_trash.py`（新增）。**协议变化**：thread 元数据 new_optional_field `deleted_at`/`restored_at`；`thread/purge`（new_method，登记 GXn-PROTO）；**Grok**：无。

**必须实现**：
- **删除 = 映射删除**：`thread/delete`（或 B5 既有删除语义）改为软删除——置 `deleted_at`，会话数据与记录保留，从会话列表/索引排除；
- 恢复：`thread/restore`（置空 `deleted_at`，回到原分类或"最近"）；
- **清空**：`thread/purge`（永久删除会话记录 + **关联文件**；前端必须弹窗确认风险——见 GX21；后端同样在请求语义中显式标记 `confirm_purge`，未确认拒绝）；
- 索引排除纪律（GX8 搜索索引：删除线程从索引清除或标记不可命中）；回收站列表查询（`thread/list_deleted`）；
- 跨平台：路径 canonicalize 三端一致（purge 删文件时 Windows/Linux 大小写语义差异处理）；关联文件定位基于 workspace 绑定（B4 路径边界），禁止越界删除。

**验收命令**：`python -m pytest tests/test_trash -q; python -m pytest tests/test_threads -q`（B5 回归门禁）。必须证明：软删除后数据完整可恢复、purge 需显式确认（无确认拒绝）、purge 后记录与关联文件不可恢复、索引同步排除、恢复回到正确分类、越界路径拒绝。

**完成判据**：
- [x] `deleted_at`/`restored_at` 字段 + `thread/purge` 协议落地（含 GXn-PROTO 登记）；
- [x] 软删除/恢复/清空三动作 + purge 显式确认；
- [x] 索引排除纪律生效；
- [x] 关联文件删除路径安全（workspace 边界）；
- [x] B5 回归无破坏；单 commit。

> 2026-08-20 · `feat/phase-g-backend` · luna **PASS**。协议变更单 `G-PROTOCOL-015`。验收 `tests/test_trash` 11 passed + `tests/test_threads` 回归。

### PhaseG-B18 · 插件注册与市场后端（P3 批追加卡）

`P2` / 3–4d / 依赖 B11（Skills/MCP 可插拔能力后端）/ **owner: Composer 2.5**

**对应基线**：Codex plugins 形态 + CLI-Anything SKILL.md 机制（semantic-port）。**涉及文件**：`appserver/handlers/plugin.py`（新增）、`protocol/schema.json`（`plugin/*` 方法）、`tests/test_plugin.py`（新增）。**协议变化**：`plugin/list`、`plugin/install`、`plugin/uninstall`、`plugin/toggle`（new_method，登记 GXn-PROTO）；**Grok**：无。

**必须实现**：
- **插件形态**：manifest 声明的组合包（命令 + 技能 + 工具/MCP 配置）；manifest 校验（字段完整性、版本、路径安全——禁止安装期路径穿越/符号链接逃逸，对齐 GX8 搜索索引与 B13 crash 脱敏纪律）；
- 来源：本地目录 + 远程 registry（可配置）；安装 = 校验 + 复制到插件目录 + 注册到 G13 能力面板；
- 启停：`plugin/toggle` 控制能力面板可见/可用；卸载 = 移除注册 + 清理（保留用户配置的确认语义）；
- 与 B11（Skills/MCP）关系：插件是"组装单元"，安装时把声明的技能/工具/MCP 配置注册进既有通道，**不另造执行路径**；
- 跨平台：插件路径三端一致（`~/.rxycode/plugins/`，运行时数据目录规则），安装校验不依赖平台特定机制。

**验收命令**：`python -m pytest tests/test_plugin -q; python -m pytest tests/test_skills -q`（B11 回归门禁，如有）。必须证明：manifest 校验拒绝非法包（含路径穿越）、安装后技能/工具/MCP 注册生效、toggle 启停、卸载清理、与既有 Skills/MCP 通道无冲突。

**完成判据**：
- [x] `plugin/*` 协议落地（含 GXn-PROTO 登记）；
- [x] manifest 校验（含安全校验）生效；
- [x] 安装→注册（技能/工具/MCP）→启停→卸载闭环；
- [x] B11 回归无破坏；单 commit。

> 2026-08-20 · `feat/phase-g-backend` · luna **PASS**。协议变更单 `G-PROTOCOL-016`。验收 `tests/test_plugin` 8 passed + `tests/test_capabilities` B11 回归。

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

OpenCode 的 Primary/Subagent、Task、权限和 Child Session 语义以 Phase D 附录 D 为准；Codex App Server、Thread/Turn/Item、双向 JSON-RPC、事件和审批边界以完整 F 附录 D 为准。未核验的第三方代码不得进入后端主链。

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

必须覆盖完整 F §8.2 的 20 个场景；后端必须特别证明：

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

- [x] F1–F13 完成，且每张卡引用了完整 F 对应卡；
- [x] schema 是唯一跨语言契约，生成类型和冻结快照一致；
- [x] Thread/Turn/Item/Child/Review/Approval/Capability/ModelSummary 真实可持久化、可恢复、可审计；
- [x] 权限、workspace、secret、路径、工具、Git 和 checkpoint 在执行边界生效；
- [x] Phase 3 max token resolver 按真实 model id 工作，未知模型 fallback 有 warning，不统一写死；
- [x] OpenCode/Codex 复用记录、许可证、commit、适配原因、测试和回滚齐全；
- [x] appserver 的启动、关闭、崩溃、重启、replay、孤儿回收有真实输出；
- [x] 前端已收到版本、capability snapshot、generated types、fixture 和兼容窗口；
- [x] Composer 2.5 完成最终 diff、测试和 commit。

> 2026-08-20 · `feat/phase-g-backend` · 后端判定 **READY_FOR_FULL_D_INTEGRATION**。交接包 `docs/decisions/G-BACKEND-HANDOFF.md`。完整 Phase G 仍须前端 H 卡消费后才能标记完成（§7.3）。

### 7.2 后端交接包

```yaml
handoff_id: D-B-HANDOFF-001
card: PhaseG-B5
source_baseline: PHASE-G-DESKTOP.md#H5
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

### 7.3 完整 Phase G 的后端判定

只有完整 F 的功能、架构、体验、发布出口全部通过，且前端文档的 H 卡也通过，B 文档不能单独把 Phase G 标记为完成。后端只能输出：`READY_FOR_FULL_D_INTEGRATION`、`BLOCKED_PREREQUISITE` 或 `REJECTED_WITH_EVIDENCE`。

---

## 附录 A · 原 D 卡映射、接口冻结和交接模板

| 后端卡 | 完整 F 基线 | 后端主要文件 | 前端依赖 |
|---|---|---|---|
| F1 | H1/DR1 | appserver/schema/复用记录 | J1 |
| F2 | H2 | schema/protocol/types | J2 |
| F3 | H3 | appserver/lifecycle/recovery | J3 |
| F4 | H4 | project/workspace/path | J4 |
| F5 | H5/Phase D | Session/Child/events | J5/J6 |
| F6 | H7 | Tool/Command/BackgroundTask | J7 |
| F7 | H8 | Permission/Approval/Auto-review | J8 |
| F8 | H9 | Review/Finding/Checkpoint/Git | J9 |
| F9 | H10/H11 | FilePreview/Worktree | J10 |
| F10 | H12/Phase 3 | Settings/ModelSummary/secure storage | J11 |
| F11 | H13 | Capability/Skill/MCP/browser | J11 |
| F12 | H14 | Notification/replay/recovery | J12 |
| F13 | H16 | Runtime/package/version compatibility | J13 |

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

**完成定义**：本文新增的是后端执行边界，不改变完整 F 的原始示例、模型适配、协议语义和验收要求；任何冲突必须回到完整 F 公共基线和协议契约测试解决。


---

# Part · 2 · 后端开工清单

> **本部分来源**：原 `PHASE-G-BACKEND-KICKOFF.md`（合并时正文一字未改，仅链接映射到新文件名）
# Phase G 开工手册 · 后端专属清单

> **读者**：后端开发者（feat/phase-g-backend 分支）。
> **你的角色**：App Server、协议（schema）、Session/Thread 真相、权限、工具、Git、恢复的**唯一生产者**。
> **先读**：[`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md)（总手册，§0-§10 全部适用）+ [`PHASE-G-BACKEND.md`](./PHASE-G-BACKEND.md)（你的施工权威文档）。
> **创建**：2026-08-10

---

## §0 你的任务总览

- **主链**：PhaseG-B1-B13，13 张卡，**按依赖图执行**（B1-B8 为前段主链串行；B9/B10/B12 可并行，B11 等 B10，B13 收口）
- **P3 批追加卡**：PhaseG-B14-B18（CLI-Hub 接入/生成器/定时任务/回收站/插件市场——主链出口达标后执行；详见 Part 1 §4 卡区与 DESKTOP §8）
- **增强阶段**：GX2/GX3/GX4/GX7/GX8/GX9/GX13/GX16/GX18 的后端协议部分（主链完成后）
- **你的第一原则**：**你产出真相（协议+状态），别人消费**。schema 是唯一的双人交接点，你独占写权限。

---

## §1 必读与前置

1. 总手册 §1 必读清单（完整 G 文档第 3 项**必读全篇**）
2. 前置自检（总手册 §2）：5 项 `Test-Path`，缺 → `BLOCKED_PREREQUISITE`
3. 文件白名单（总手册 §3）：你拥有 `appserver/`、`protocol/`、Python 测试

---

## §2 主链卡表（B1-B13 · 依赖 · 工时 · 验收命令）

> 验收命令为速查版（**全部摘录自原版 G-B 文档对应卡，未自行新增门禁**；如与原文不一致以原文档为准并报告）；完整"必须实现/完成判据"以 G-B 文档对应卡为准。卡内标注的 `owner: Composer 2.5` = 由你（后端执行者）完成。

| 卡 | 标题 | 依赖 | 工时 | 验收命令（速查） |
|---|---|---|---|---|
| **B1** | 后端基线、App Server 包边界与上游复用冻结 | 无（Phase 4 壳+Phase 3 摘要+A/D/F 契约） | 1-2d | `Test-Path appserver; Test-Path protocol/schema.json; python -m pytest tests/test_protocol -q` |
| **B2** | Protocol handshake、能力发现、错误模型和生成契约 | B1 | 2-3d | `python -m pytest tests/test_protocol -q`（新旧版本/能力缺失/错误重试/未知字段/schema-类型一致性） |
| **B3** | App Server 进程、生命周期、日志和恢复底座 | B1, B2 | 2-3d | `python -m pytest tests/test_appserver -q`（启动失败/崩溃/重启/20 次启停/未完成任务不伪造完成） |
| **B4** | Project / Workspace 服务与路径边界 | B2, B3 | 2-3d | `python -m pytest tests/test_projects -q`（两项目不串 cwd/Thread 绑 workspace/越界拒绝） |
| **B5** | Thread / Turn / Item / Child Session 真相 | B2,B3,B4,Phase D | 3-4d | `python -m pytest tests/test_threads -q`（分叉不改父/Child 不混入/重试幂等/归档可恢复/孤儿可审计；**完成后提供 H5 fixture**） |
| **B6** | Tool、Command、Background Task 执行与事件 | B5, Phase A/D | 2-3d | `python -m pytest tests/test_execution -q`（终态完整/取消超时可达/退出后可读/主 Thread 不因 Child 失败误完成） |
| **B7** | Permission Center、Approval、Auto-review 与审计 | B2, B6, Phase A/D | 2-3d | `python -m pytest tests/test_approval -q`（无 UI 仍拒绝/一次 allow 不扩散/撤销/重启只恢复持久化策略/可回 trace） |
| **B8** | Git Diff、Review、Finding、Checkpoint 与细粒度操作 | B4,B5,B6,B7 | 4-5d | `python -m pytest tests/test_review -q`（非 Git 仓库/未跟踪/重复 start/断线补读/stale/单 hunk revert/checkpoint restore 后新 diff hash） |
| **B9** | File Preview、External Editor、Worktree 与执行环境 | B4,B5,B7,B8 | 3-4d | `python -m pytest tests/test_file_preview -q; python -m pytest tests/test_worktrees -q` |
| **B10** | Settings、ModelCatalog、max token Resolver 与安全存储 | B2, B7, Phase 3 | 2-3d | `python -m pytest tests/test_settings -q`（层级覆盖/secret 不进日志/limit_source/未知模型不伪装） |
| **B11** | Skills、MCP、浏览器和可插拔能力后端 | B2, B7, B10 | 3-4d | `python -m pytest tests/test_capabilities -q`（未安装不显示/失败不卡 Thread/可审计） |
| **B12** | Notifications、长任务、恢复、replay 和孤儿回收 | B3,B5,B6,B7 | 2-3d | `python -m pytest tests/test_recovery -q`（断线/重复连接/事件缺口/replay/崩溃/孤儿/unknown→recovery_required） |
| **B13** | Runtime 打包、版本绑定、升级和发布门禁 | B2,B3,B7,B10,B12 | 4-5d | `python -m pytest tests/test_release -q`（产物启动真实握手/版本不匹配可诊断/更新失败不删旧版/crash 脱敏） |

**P3 批追加卡表（B14–B18 · 主链出口达标后执行 · 完整卡定义见 Part 1 §4）**：

| 卡 | 标题 | 依赖 | 工时 | 验收命令（速查） |
|---|---|---|---|---|
| **B14** | CLI-Hub 接入与 CLI 工具桥接器 | Phase D + B6 | 3-4d | `python -m pytest tests/test_cli_bridge -q; python -m pytest tests/test_execution -q`（venv 隔离/`cli:` 前缀/来源标签/三端 venv 路径） |
| **B15** | 生成器能力（HARNESS 7 阶段技能化） | B14 | 2-3d | `python -m pytest tests/test_harness_skill -q`（**挂起条件：Phase B 缓存未落地 → BLOCKED_PREREQUISITE**） |
| **B16** | 定时任务调度器 | B5, B12 | 3-4d | `python -m pytest tests/test_schedule -q; python -m pytest tests/test_threads -q`（应用层 asyncio 调度/三端一致/重启恢复/走 B5 通道） |
| **B17** | 回收站后端 | B5 | 2-3d | `python -m pytest tests/test_trash -q; python -m pytest tests/test_threads -q`（软删除/恢复/purge 显式确认/索引排除） |
| **B18** | 插件注册与市场后端 | B11 | 3-4d | `python -m pytest tests/test_plugin -q`（manifest 校验/注册闭环/启停/卸载清理） |

**后端依赖图（不是单串行链）**：

```
B1→B2→B3→B4→B5→B6→B7→B8   （前 8 张串行）
此后按依赖可并行：
  B9（等 B4,B5,B7,B8）│ B10（等 B2,B7,Phase3）│ B12（等 B3,B5,B6,B7）
  B11（等 B2,B7,B10）   ← 与 B9/B12 并行
  B13（等 B2,B3,B7,B10,B12） ← 最后一个收口
```

**你是主线**：前端每张卡都在等你对应卡合入（详见总手册 §5.1 表）。

---

## §3 每卡完成后交接给前端什么（你的产出 = 前端的输入）

| 你完成 | 前端才能开工 | 交接物 |
|---|---|---|
| B1 | H1 | 包边界冻结结论 + schema 现状确认 |
| B2 | H2 | schema 冻结 + 生成类型 + contract test 绿 |
| B3 | H3 | appserver 进程生命周期事件（Electron Main 依赖） |
| B4 | H4 | Project/Workspace 协议方法与事件 |
| B5 | H5 | Thread/Turn/Item 协议 + **H5 fixture**（B5 验收明确要求） |
| B6 | H6/H7 | Tool/Command/BackgroundTask item states + Item events |
| B7 | H8 | Approval 协议 + 审计记录 |
| B8 | H9 | review/start、Review/Finding、checkpoint 协议 |
| B9 | H10 | FilePreview/ExternalEditor/Worktree 协议 |
| B10/B11 | H11 | Settings/Capability/MCP/Skill 协议 + Phase 3 摘要消费面 |
| B12 | H12 | Notification/recovery/replay 事件 |
| B13 | H13 | 打包产物 + 版本兼容 metadata |

---

## §4 你的增强卡（主链完成后，详见 [../PHASE-G-DESKTOP.md](../PHASE-G-DESKTOP.md) 与 [PHASE-G-BACKEND-GX.md](./PHASE-G-BACKEND-GX.md)）

| 增强卡 | 你的部分 | 协议变更 |
|---|---|---|
| GX2 | `approval/mode_set`（UI 预设 → B7 策略映射） | new_method（approval/ 前缀） |
| GX3 | `review/comment/add`、`review/comment/resolve` | new_method |
| GX4 | `checkpoint/snapshot/create`、`checkpoint/rewind`（三步编排） | new_method |
| GX7 | `event/agent_usage` 事件（usage_tracker，消费 Phase 3） | new_event |
| GX8 | `thread/fork` | new_method |
| GX9 | `plan/persist`、`plan/implement`（~/.rxycode/plans/） | new_method |
| GX13 | `event/agent_needs_input` 事件（B12 流判定） | new_event |
| GX16 | `thread/side_chat/create`、`thread/side_chat/close`（只读派生） | new_method |
| GX14 | `agent/invoke` 新增 optional field `capability`（枚举 no_tools/edit_only/full，工具注册层强制校验） | new_optional_field |
| GX18 | followup_scanner（纯规则零 LLM） | 无（消费 B12 事件） |

> 增强卡的通用规范限制（只添加不修改/协议变更单/BLOCKED_PREREQUISITE/基线红线/单 commit）见增强文档 §1。

---

## §5 你的文件白名单（可写范围）

```
appserver/**、protocol/**（schema 唯一 Owner）、config/model_catalog 复用、
tests/test_protocol、tests/test_appserver、tests/test_*（Python）、
packaging/**、增强卡新增文件（appserver/handlers/*、tests/test_*）、
frontend/protocol-client/** 的生成类型区段（仅限协议变更 PR 内由 schema 生成的产物；其余源码归前端）
```

**禁止触碰**：`frontend/**`（前端唯一 Owner）、`core/agent_v2.py` 等 Phase C 在制品（总手册 §4.3）、`data/`、`credentials.yaml`、`.env*`。`~/.rxycode/` 禁止读取/提交/泄露其中密钥与用户数据；向该目录写入运行数据（GX4/GX8/GX9 的 plans/checkpoints/索引）属正常，测试走 `RXYCODE_DATA_DIR` 注入目录。

---

## §6 协议变更单模板（你独占，但必须走仪式）

改 schema 前填写（G-B §1.3 权威模板），附在 PR 描述：

```yaml
protocol_change:
  request_id: G-PROTOCOL-XXX
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "<version>"
  change_kind: new_optional_field   # new_method | new_event | new_optional_field
  method_or_event: "<method/event>"
  compatibility: "<backward-compatible evidence>"
  generated_types: "<bun run generate 命令和 commit>"
  fixtures: { success: ..., denied: ..., timeout: ..., reconnect: ... }
  migration: "<required or none>"
  rollback: "<commit>"
```

**铁律**：前端未确认消费方式前不得合入（总手册 §4.2）；不得删除已有字段、不得改变已有字段语义。

**生成类型提交规则**：协议 PR 中，你更新 schema 后运行 `cd frontend\protocol-client && bun run generate`，**生成产物随你的协议 PR 一并提交**（生成类型是协议交接物，白名单已授权协议 PR 内后端写入生成区段；非协议 PR 不碰该目录）。前端在 PR 中确认消费方式后合入。

---

## §7 验收纪律（你的专属提醒）

1. 每张卡：先跑验收命令贴输出，再在 PR 里逐条勾"完成判据"
2. **你验收时的特别责任**：B5 完成后必须提供 H5 fixture——这是前端 H5 的开工依赖，漏了会阻塞对方
3. **基线两档**：卡级验收跑定向测试；全局 agent baseline 在批次/阶段出口跑一次并记录唯一结果。没有 API key 时输出 `PENDING_BASELINE`（如实标注，不标记完成）——真实基线通过才算出口达标
4. 大卡（B5/B8/B13）合并靠后，承担 rebase（总手册 §4.1）
