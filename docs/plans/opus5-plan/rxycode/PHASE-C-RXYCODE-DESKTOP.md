# Phase C · RxyCode Desktop 完整桌面端（Coding Workspace）

> **在整条路线中的位置**：这是 [`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的后继扩展，编号 Phase C；它把主计划 Phase 3 已经搭好的 Electron 壳、`appserver` 和协议客户端，补成一个可长期使用的 RxyCode Desktop 工作台。
>
> **产品名称**：RxyCode Desktop。本文借鉴成熟 coding agent 的交互与协议边界，但不复刻任何第三方品牌、私有实现或视觉资产。
>
> **前置条件**：主计划 Phase 0/1/2/3 + [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) + [`PHASE-B-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-B-MULTI-AGENT-ORCHESTRATION.md) 的公共契约已冻结。Phase A/B 的全部高级能力不是单 Agent Desktop 启动的硬依赖；它们通过 capability 握手和 feature flag 接入，不能把 Desktop 绑死在某一个后续 Phase 上。
>
> **后继**：原来的多模型协作文档顺延为 [`PHASE-D-MULTI-MODEL-COLLABORATION.md`](./PHASE-D-MULTI-MODEL-COLLABORATION.md)；多模态顺延为 [`PHASE-E-MULTIMODAL.md`](./PHASE-E-MULTIMODAL.md)；PersonaAgent 预留顺延为 [`PHASE-F-PERSONA-AGENT-INTERFACE.md`](./PHASE-F-PERSONA-AGENT-INTERFACE.md)。
>
> **一句话目标**：让用户可以在一个本地桌面工作台里，管理项目和会话，观察 Agent 的每个执行步骤，审查文件变更，控制权限，恢复中断任务，并在不复制后端业务逻辑的前提下继续扩展 LinkAgent 等薄客户端。
>
> **基线日期**：2026-08-02　**预计工时**：12–16 周（以卡计，不把人的日历估计当作 agent 速度承诺）　**任务卡**：C1–C16

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必须先读) | 谁写、怎么写、什么不许做 |
| [§1 为什么需要新的 Phase C](#1-为什么需要新的-phase-c) | 对主计划 Phase 3 的审计结论 |
| [§2 产品定义](#2-产品定义) | RxyCode Desktop 应该让用户看到什么 |
| [§3 总体架构](#3-总体架构) | Desktop、协议、appserver、Session 的边界 |
| [§4 交互模型](#4-交互模型) | Project、Thread、Turn、Item、Review |
| [§5 协议与状态契约](#5-协议与状态契约) | 事件、请求、恢复、版本兼容 |
| [§6 任务卡](#6-任务卡) | C1–C16 的具体施工顺序 |
| [§7 安全与隐私](#7-安全与隐私) | 权限、密钥、日志、崩溃数据 |
| [§8 测试与视觉验收](#8-测试与视觉验收) | 机械测试、E2E、Grok 的辅助边界 |
| [§9 LinkAgent 扩展契约](#9-linkagent-扩展契约) | 为后续桌面套壳和扩展保留稳定缝隙 |
| [§10 出口标准](#10-出口标准) | 什么状态才算 Desktop 真正完成 |
| [§11 后续扩展](#11-后续扩展) | 不在本 Phase 偷塞范围的能力 |

---

## §0 执行手册（必须先读）

### 0.1 这份文档解决什么问题

主计划 Phase 3 已经定义了一个最小 Desktop 壳：Electron + React、启动 `python -m appserver`、显示会话、流式输出、工具卡片、审批和设置。

这足够验证“桌面客户端能不能接上 Agent”，但不够支撑长期编码工作。用户真正需要的是一个工作台：知道自己在哪个项目、当前有哪些会话、Agent 改了哪些文件、哪些动作有风险、任务是否还在后台运行、出了问题如何恢复，以及审查意见如何回到下一轮 Agent。

本 Phase 不推翻 Phase 3 的壳，也不在 UI 里重写 Agent。它只补齐 Phase 3 没有定义清楚的**产品对象、协议对象、审查对象、持久化边界、进程生命周期和扩展边界**。

### 0.2 模型分工（硬约束）

| 模型 | 负责 | 禁止 |
|---|---|---|
| **Composer 2.5** | **主写全部代码**：Electron、React、TypeScript、协议客户端、appserver 补充契约、测试、打包、CI、前后端联调 | 不得把 Desktop 本体交给 Grok；不得以“前端”名义绕过协议直接 import Python |
| **Grok 4.5** | 仅做卡内标注的**多模态辅助环节**：启动 dev server、截屏核对、视觉回归、图片/文件预览验收、设计稿对照 | 不写 Python；不改协议主契约；不独立实现没有多模态环节的前端卡；不单独提交 Desktop 主链 |
| **Sonnet 5（可选）** | 对 C2、C5、C7、C8、C10、C15 的 diff 做预审，重点找状态遗漏、权限旁路和进程泄漏 | 不代替 Composer 实现；不作为完成标准 |
| **人** | 决定产品取舍、审批默认值、是否接受审查结果、最终合并 | 不用“截图看着像”替代测试和协议验收 |

**主写纪律**：本 Phase 所有卡的实现者默认是 Composer。Grok 只接收卡内明确写出的“视觉辅助环节”，产出回到 Composer 分支收口。

### 0.3 开工前自检

每次开始一张卡前都要执行：

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
git status --short
git branch --show-current
python --version
python -m pytest -q
```

如果工作区有不属于本卡的修改：

1. 不要清理、回退或覆盖它们。
2. 在卡的开始记录实际 dirty files。
3. 新增文件尽量放在本卡的独占目录。
4. 如果共享文件必须修改，先停止并在卡记录里说明冲突点。

### 0.4 每张卡的固定回路

每张卡只做一个可审查单元，固定执行：

```text
LOCATE → READ → WRITE → TYPECHECK/LINT → UNIT TEST → E2E/手工验收 → CHECK DIFF → COMMIT
```

每张卡必须留下：

- 改动文件清单
- 协议/schema 是否变化
- 启动、测试和构建命令
- 真实命令输出
- 已知限制
- 可独立回滚的 commit

“页面能打开”不等于卡完成。Desktop 的完成标准必须同时满足**状态正确、协议正确、权限正确、进程可回收、视觉状态可理解**。

### 0.5 八条不可违反的硬规则

| 编号 | 规则 | 违反后果 |
|---|---|---|
| DC-A1 | Desktop 只能经 `frontend/protocol-client` 与 appserver 通信；不得直接 import Python，不得自己调用后端 HTTP API | 客户端和核心分叉，LinkAgent 无法稳定复用 |
| DC-A2 | UI 不得复制 Agent 业务判断、权限判断、任务路由或工具注册逻辑 | UI 与 CLI/TUI 行为漂移 |
| DC-A3 | 所有外部能力先进入 protocol capability，再进入 UI feature；不能通过“前端先写死”引入隐式契约 | 后续 Phase、LinkAgent 和旧客户端被迫跟着猜 |
| DC-A4 | 所有异步操作必须有 started/progress/completed/failed/cancelled 终态；不能只靠“最后一条文本”判断结束 | 卡死、重复提交和进程重启后状态丢失 |
| DC-A5 | 审批默认收紧；`always allow` 必须带作用域、可撤销、可过期，不能是全局布尔值 | 权限被静默扩大 |
| DC-A6 | 所有 diff、review finding、审批结论都绑定具体的版本或 diff hash | Agent 修改后旧审查结果仍被错误沿用 |
| DC-A7 | Desktop 崩溃、窗口关闭、appserver 崩溃都必须能回收子进程、释放临时资源，并保留可恢复的会话状态 | 孤儿进程、端口占用、会话丢失 |
| DC-A8 | UI 视觉验收不能替代自动化测试；Grok 的截图结论必须回到卡的验收记录 | “看起来没问题”无法回归 |

### 0.6 明确不做的事情

本 Phase 不做：

- 把 RxyCode 改成云端多租户服务
- Kubernetes、Helm、企业 RBAC 和团队计费
- 在 Desktop 中重写多 Agent 编排核心
- 在 Desktop 中自动生成 Skill 或自动修改 EKO
- 为了好看引入一套与协议无关的临时状态管理后端
- 直接复制第三方 Desktop 的品牌、图标、代码和私有交互实现

这些能力可以通过后续 Phase、MCP、Plugin 或 LinkAgent 扩展接入，但必须遵守本文的 capability 和协议边界。

---

## §1 为什么需要新的 Phase C

### 1.1 对主计划 Phase 3 的审计结论

主计划 Phase 3 的 D1–D8 能够形成一个**基础 Desktop 壳**，结论如下：

| 审计项 | 结论 | 说明 |
|---|---|---|
| Electron + React 能否启动 | 可以 | D1 定义了脚手架和 `python -m appserver` 子进程 |
| 能否聊天和流式输出 | 可以 | D2/D3 覆盖会话、消息 delta 和中断 |
| 能否展示工具调用 | 基础可以 | 只有 `tool_begin`/`tool_end`，复杂进度和错误状态未定义 |
| 能否审批危险动作 | 基础可以 | D4 有模态框，但作用域、过期、撤销和审计记录不够明确 |
| 能否配置模型、Key、工作区 | 基础可以 | D5 有页面，但秘钥协议、迁移和多项目作用域需要补齐 |
| 能否打包 | 计划可以 | D6–D8 有打包和 CI 目标，但签名、回滚、崩溃恢复未形成契约 |
| 能否长期管理项目和会话 | 不充分 | 没有完整 Project/Thread/Turn/Item 生命周期 |
| 能否审查代码变更 | 不充分 | 没有 diff、文件变更、review finding、行级反馈契约 |
| 能否使用 worktree/Git 工作流 | 未定义 | 没有分支、worktree、提交和撤销的界面边界 |
| 能否供 LinkAgent 稳定套壳 | 有风险 | 壳能 fork，但扩展点、协议超集和持久化边界不够清楚 |

因此，Phase 3 的定位应当保留为：

> **验证 Electron 壳 + appserver + 协议客户端能够工作。**

本 Phase C 的定位是：

> **把这个壳补成可用于真实编码工作的 RxyCode Desktop 工作台。**

### 1.2 现有 Phase 3 的主要歧义

#### 歧义一：会话列表到底存什么

“会话列表”可能被误解成 React 内存里的数组，也可能被误解成后端 transcript 列表。本 Phase 明确：

- `Thread` 是持久化会话；
- `Turn` 是一次用户输入及其 Agent 工作；
- `Item` 是消息、工具调用、命令、文件变更、审批和错误等可审查单位；
- UI 只负责投影和交互；持久化真相由 appserver/session store 负责。

#### 歧义二：工具卡片什么时候算完成

单独的 `tool_begin`/`tool_end` 不够表达：

- 工具输出持续很久；
- 工具被用户中断；
- 命令失败但 Agent 继续；
- 工具请求审批后暂停；
- Desktop 崩溃后重连；
- 多个工具并发运行。

因此本 Phase 要求每个执行 item 有明确状态机和幂等 `item_id`。

#### 歧义三：审批的“始终允许”允许什么

“always allow”不能直接写成 `true`。它至少要绑定：

```text
workspace / project / tool / action-kind / path-scope / command-pattern / expiry
```

例如“允许读取当前工作区”不能自动等价于“允许运行任意 PowerShell”。

#### 歧义四：桌面端是否负责审计

审计能力必须由核心和协议提供，Desktop 负责可视化：

- CLI 可以输出文本 diff 和审查结论；
- Desktop 可以提供文件列表、双栏 diff、问题定位、行级反馈和一键回传；
- 结论必须绑定 diff hash，不能只存在于某个页面组件的 state 里。

#### 歧义五：LinkAgent 如何复用

LinkAgent 需要的是一个可 fork、可加视图、可加 appserver 方法的薄壳，而不是一堆散落在 UI 组件里的内部 import。本 Phase 会把 shell、协议客户端、平台能力、功能面板和扩展 API 分层。

---

## §2 产品定义

### 2.1 RxyCode Desktop 的一句话

**RxyCode Desktop 是一个本地优先的 AI 编码工作台：用户以项目和会话组织工作，以时间线观察 Agent，以 diff 和审查结果验收变更，以权限中心控制风险。**

### 2.2 用户打开应用后应该能做什么

最小完整路径如下：

```text
打开应用
  ↓
选择或创建项目（本地目录）
  ↓
新建 Thread
  ↓
输入需求
  ↓
Agent 流式工作
  ├─ 读取文件：可展开查看
  ├─ 执行命令：显示命令、输出、退出码
  ├─ 修改文件：显示文件变更摘要
  └─ 高风险动作：请求审批
  ↓
任务完成
  ↓
打开变更审查
  ├─ 查看 diff
  ├─ 查看 review findings
  ├─ 让 Agent 修复某条问题
  └─ 撤销或打开文件
  ↓
测试、提交或继续下一轮
```

### 2.3 推荐的桌面布局

第一版不要把所有功能塞进一个页面，使用固定的三栏骨架：

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 顶栏：项目 / 分支 / 当前模型 / 权限模式 / 运行状态 / 设置             │
├────────────────┬───────────────────────────────────┬─────────────────┤
│ 左栏            │ 中央工作区                         │ 右栏            │
│                │                                   │                 │
│ 项目列表        │ Thread 标题                        │ Inspector       │
│ Thread 列表     │ Turn 时间线                        │ Tool detail     │
│ 工作区入口      │ 消息 / 工具 / 命令 / 文件变更       │ Diff            │
│                │ 审批 / 错误 / 结果                  │ Review findings │
│                │                                   │ File preview    │
├────────────────┴───────────────────────────────────┴─────────────────┤
│ 底部 composer：输入框 / 附件 / 模型 / 权限 / 发送 / 中断               │
└──────────────────────────────────────────────────────────────────────┘
```

右栏必须是可收起的。窄窗口不能因为右栏存在而把中央对话压缩到无法使用。

### 2.4 三种客户端的关系

```text
                   ┌─────────────────────┐
                   │ RxyCode Core/Session │
                   └──────────┬──────────┘
                              │
                   ┌──────────▼──────────┐
                   │ versioned protocol  │
                   └───────┬───────┬──────┘
                           │       │
                 ┌─────────▼─┐ ┌──▼────────────┐
                 │ OpenTUI/CLI │ │ RxyCode      │
                 │ 文本投影    │ │ Desktop      │
                 │              │ │ 富客户端投影 │
                 └──────────────┘ └──────────────┘
```

Desktop 不是另一个 Agent。Desktop 是同一套核心能力的富客户端投影。

### 2.5 必须支持的用户状态

每个主要页面都必须明确以下状态：

| 状态 | 用户应该看到什么 |
|---|---|
| 空 | 下一步应该做什么，不显示空白白板 |
| 加载 | 当前读取的对象和预计等待原因 |
| 运行中 | 当前 turn、工具、命令或审批状态 |
| 暂停 | 为什么暂停、等待谁、如何继续 |
| 中断 | 已停止什么、是否保留已产生的变更 |
| 失败 | 用户可理解的原因、重试或回滚入口 |
| 断线 | appserver 是否存活、是否可以重连 |
| 恢复中 | 正在从 transcript 或快照恢复哪些内容 |
| 权限拒绝 | 哪个动作被拒绝、如何修改范围 |
| 完成 | 变更摘要、测试结果、下一步动作 |

---

## §3 总体架构

### 3.1 分层

```text
┌────────────────────────────────────────────────────────────┐
│ RxyCode Desktop UI                                         │
│ React components / routes / panels / keyboard shortcuts    │
└─────────────────────┬──────────────────────────────────────┘
                      │ view model only
┌─────────────────────▼──────────────────────────────────────┐
│ Desktop application layer                                  │
│ ProjectStore / ThreadStore / ReviewStore / PermissionStore │
└─────────────────────┬──────────────────────────────────────┘
                      │ typed protocol-client
┌─────────────────────▼──────────────────────────────────────┐
│ protocol-client                                             │
│ request/response / notifications / server requests / retry  │
└─────────────────────┬──────────────────────────────────────┘
                      │ stdio JSON-RPC
┌─────────────────────▼──────────────────────────────────────┐
│ Desktop host / process supervisor                           │
│ spawn / handshake / restart / shutdown / crash containment  │
└─────────────────────┬──────────────────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────────────────┐
│ appserver                                                 │
│ protocol handlers / session / safety / tools / persistence  │
└─────────────────────┬──────────────────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────────────────┐
│ core/session + graph + tools + memory + safety + tracing    │
└────────────────────────────────────────────────────────────┘
```

### 3.2 目录边界

建议的新增或收口目录如下：

```text
frontend/
├── protocol-client/              # Phase 2 已有；唯一的协议客户端
├── desktop-app/                  # RxyCode Desktop React UI
│   ├── src/app/                  # 路由、应用容器、生命周期
│   ├── src/features/projects/    # 项目/工作区
│   ├── src/features/threads/     # Thread/Turn/Item
│   ├── src/features/tools/       # 工具/命令/后台任务卡片
│   ├── src/features/review/      # diff/review finding
│   ├── src/features/permissions/ # 审批/权限中心
│   ├── src/features/settings/    # 模型、Provider、工作区设置
│   ├── src/features/files/       # 文件树/预览/外部编辑器
│   ├── src/platform/             # Electron 特有 API 的唯一入口
│   ├── src/state/                # 客户端投影状态，不保存核心真相
│   └── src/ui/                   # 无业务逻辑的通用组件
└── opentui-app/                  # 现有 TUI，继续复用 protocol-client

appserver/
├── __main__.py                   # stdio 入口
├── handlers/                     # 协议 handler
├── lifecycle.py                  # server/session 生命周期
└── persistence.py                # 仅由后端负责的持久化边界

protocol/
├── requests.py                   # 客户端请求
├── notifications.py              # 服务端单向通知
├── server_requests.py             # 服务端请求客户端，如审批
├── types.py                      # Project/Thread/Turn/Item/Review 类型
└── schema.py                     # JSON Schema 生成
```

目录名可以根据已有仓库结构调整，但职责不能合并成一个 `App.tsx` 或一个新的 Python God Object。

### 3.3 Desktop 进程模型

桌面端至少有三个逻辑进程边界：

```text
Electron main process
  ├─ 创建窗口
  ├─ 启动/停止 appserver
  ├─ 管理平台能力
  └─ 不承载 Agent 业务逻辑

Renderer process
  ├─ React UI
  ├─ protocol-client 调用
  ├─ 状态投影
  └─ 不直接访问 Node 文件系统或 Python

appserver child process
  ├─ Session/Agent/tools/safety
  ├─ transcript 和变更状态
  └─ stdout 只输出协议，日志走 stderr
```

### 3.4 为什么不能让 Renderer 直接启动 Python

Renderer 直接启动 Python 会造成：

- 浏览器上下文获得不必要的系统权限；
- 多窗口时产生多个不可控 appserver；
- 关闭窗口时无法可靠回收进程；
- LinkAgent 无法替换 appserver 而不修改 UI；
- 安全审批可能被前端绕过。

因此所有子进程生命周期都必须由 Electron main process 或受控的 host adapter 管理。

### 3.5 本地优先与未来远程

本 Phase 的默认传输是本地 stdio：

```text
Desktop ──stdio JSON-RPC──> local appserver
```

协议设计必须保留未来的 WebSocket/Unix socket/远程 appserver 可能性，但本 Phase 不因为“以后可能远程”而加入登录、租户、云端状态同步等范围。所有 transport-specific 代码集中在 `protocol-client` 和 host adapter。

---

## §4 交互模型

### 4.1 Project、Workspace、Thread、Turn、Item

这些对象必须区分，不能全部叫“session”。

| 对象 | 含义 | 持久化 | 典型操作 |
|---|---|---:|---|
| `Project` | 用户长期工作的项目入口，可包含一个或多个本地目录 | 是 | 创建、打开、重命名、隐藏、删除入口 |
| `Workspace` | 一次具体执行的目录、分支、worktree 和权限范围 | 是 | 打开、切换、创建 worktree |
| `Thread` | 一个可恢复的对话和工作历史 | 是 | 新建、恢复、重命名、归档、分叉 |
| `Turn` | 一次用户输入及其 Agent 执行过程 | 是 | 开始、追加、停止、重试 |
| `Item` | turn 内可独立呈现和审查的单位 | 是 | 展开、复制、定位、审查 |
| `Review` | 绑定某个变更快照的审查结果 | 是 | 查看、回传意见、失效 |

### 4.2 Item 类型

第一版至少支持：

```text
user_message
agent_message
agent_message_delta
reasoning_summary        # 只显示摘要，不暴露不可展示的原始推理
tool_call
tool_output
command_execution
file_change
approval_request
approval_result
review_finding
status_update
error
turn_summary
```

新增 Item 类型必须先进入 protocol schema，再进入 UI。UI 不得根据字符串前缀猜类型。

### 4.3 Tool/Command/Change 三种卡片不能混成一张

| 卡片 | 用户关心的问题 |
|---|---|
| Tool card | Agent 调用了什么能力、参数是什么、结果是什么 |
| Command card | 具体执行了什么命令、在哪个目录、退出码和输出是什么 |
| File change card | 改了哪些文件、增删多少行、是否有冲突 |
| Review finding | 这份具体变更有什么风险，严重程度和证据是什么 |
| Approval card | 哪个动作需要什么范围的许可 |

每张卡都支持收起；长输出默认折叠，不能让一个编译日志撑满整个 Thread。

### 4.4 Thread 生命周期

```text
new
  ↓
ready
  ↓ turn/start
running
  ├─ waiting_approval
  ├─ waiting_input
  ├─ background
  ├─ interrupted
  ├─ failed
  └─ completed
        ↓
      archived
```

合法转移必须由服务端状态决定，UI 只展示状态并发送动作。不能让 UI 直接把 `running` 改成 `completed`。

### 4.5 审查模型

一个 Review 必须绑定：

```text
review_id
thread_id
turn_id
scope                    # working_tree / base_branch / commit / files
base_ref
head_ref
diff_hash
created_at
reviewer
findings[]
status                   # pending / passed / has_findings / stale / failed
```

一个 Finding 至少包括：

```text
finding_id
severity                 # P0 / P1 / P2 / P3 / info
file
start_line
end_line
title
body
evidence
recommendation
status                   # open / accepted / dismissed / fixed / stale
```

当文件再次修改，旧 `diff_hash` 不再匹配，Review 自动进入 `stale`，不能继续显示为“当前已通过”。

### 4.6 审批模型

审批选项不是简单的三个按钮，而是权限决策：

```text
allow_once
allow_for_turn
allow_for_thread
allow_for_project
deny
cancel_turn
```

只有用户明确选择并且后端校验作用域后，权限记录才生效。UI 不能自行写入“始终允许”。

---

## §5 协议与状态契约

### 5.1 初始化握手

Desktop 启动连接后必须先完成：

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

版本不兼容时，Desktop 必须显示可操作的错误：

- 当前 Desktop 版本；
- appserver 版本；
- 需要的协议范围；
- 可用的升级或重新安装入口。

禁止静默降级到一个字段语义不同的旧协议。

### 5.2 请求、通知、服务端请求

| 类型 | 方向 | 例子 | 是否有 response |
|---|---|---|---:|
| Request | Desktop → appserver | `thread/start`、`turn/start`、`review/start` | 是 |
| Notification | appserver → Desktop | `item/started`、`item/delta`、`turn/completed` | 否 |
| Server request | appserver → Desktop | `approval/request`、`question/request` | 是 |

Server request 必须有超时、取消和连接断开处理。审批等待不能无限挂起 appserver。

### 5.3 事件幂等与顺序

每个事件至少包含：

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

客户端必须：

- 依据 `event_id` 去重；
- 依据 `sequence` 检查乱序；
- 发现缺口时请求补发或重新读取 Thread；
- 不因为重复 `completed` 事件重复弹通知；
- 不把网络到达顺序当成业务顺序。

### 5.4 补读与恢复

Desktop 重连后不能只从最后一条文本继续拼接。至少支持：

```text
thread/status
thread/read
turn/items/list
event replay / cursor
```

恢复流程：

```text
发现连接断开
  ↓
保留本地 UI 草稿和最后 cursor
  ↓
重启或重连 appserver
  ↓
重新 initialize
  ↓
读取 Thread 元数据
  ↓
按 cursor 补读 Item
  ↓
校验 running turn 状态
  ├─ 仍在运行：重新订阅
  ├─ 已完成：补齐结果
  ├─ 已中断：显示中断原因
  └─ 状态未知：标为 recovery_required，不得伪造完成
```

### 5.5 能力发现

以下能力必须由 appserver 声明，UI 不能假设存在：

```text
threads
thread_fork
background_turns
command_execution
file_changes
review
worktree
file_preview
browser
mcp
skills
multi_agent
multi_model
vision
```

未声明的能力：

- 不显示不可用按钮；
- 不发出服务端一定会拒绝的请求；
- 仍然可以在设置或帮助页显示“当前版本未提供”。

### 5.6 协议扩展规则

新增字段优先使用可选字段；新增方法使用新方法名；修改现有字段语义必须升级 protocol major。每次 protocol 改动固定执行：

```text
改 protocol/*.py
  ↓
生成 schema.json
  ↓
生成 TypeScript types
  ↓
更新冻结快照
  ↓
跑 protocol contract tests
  ↓
再写 UI
```

禁止先在 React 里定义一个“临时类型”，再反推后端。

---

## §6 任务卡

### C1 · Desktop 基线与包边界冻结

**目标**：确认 Phase 3 的 Electron 壳、`protocol-client` 和 appserver 能作为本 Phase 的稳定基线，不重复重写已有实现。

**内容**：

1. 记录现有 Desktop 启动方式、Node/Bun/Python 版本和构建命令。
2. 确认 Desktop 包的入口、renderer、main process 和 protocol-client 的边界。
3. 确认 OpenTUI 与 Desktop 是否共享生成的 TypeScript types。
4. 添加 capability/version handshake 的测试占位。
5. 输出一份“可复用 / 需要补齐 / 禁止重写”的文件清单。

**验收**：

- 干净环境能启动 Desktop 与 appserver；
- stdout 只有协议数据，日志只在 stderr 或受控日志文件；
- 现有 TUI 测试不因 Desktop 基线整理而回归；
- 没有在 renderer 里新增 Python 或 HTTP 直连。

**禁止**：借 C1 重新整理整个 `frontend/`；没有证据的目录重命名属于独立卡。

### C2 · Protocol handshake、能力发现与错误模型

**目标**：让 Desktop 能知道“当前 appserver 支持什么”，并能把版本错误、能力缺失和服务器错误变成可理解的 UI 状态。

**内容**：

- `initialize` / `initialized`；
- protocol version range；
- client/server capability；
- stable error code；
- request timeout；
- connection closed；
- unsupported feature；
- server overloaded；
- authentication/configuration missing；
- protocol mismatch。

**验收**：

- 新旧版本模拟测试；
- 未声明能力不会出现在 UI；
- 每个错误都有机器可断言的 code；
- UI 能区分可重试、需用户处理和不可恢复错误。

### C3 · Desktop Host 与 appserver 进程监督

**目标**：解决启动、关闭、崩溃、重启、孤儿进程和多窗口生命周期。

**内容**：

1. 由 main process 启动 appserver。
2. 记录 child PID、启动时间、协议版本和退出码。
3. 启动超时可取消，不能无限等待。
4. appserver 崩溃后保留 thread 状态并显示恢复入口。
5. Desktop 退出时发送优雅 shutdown，再执行有限时间的强制回收。
6. 禁止一个窗口关闭导致其他窗口使用的共享 appserver 被误杀；若暂不支持多窗口，必须明确单实例约束。
7. 临时目录、日志句柄和管道在异常路径也要释放。

**验收**：

- appserver 启动失败；
- appserver 启动后立即崩溃；
- Desktop 窗口强制关闭；
- Desktop 重启后恢复 Thread；
- Windows/macOS/Linux 至少各有进程回收测试或明确平台差异；
- 连续启动和退出 20 次不产生孤儿进程。

### C4 · Project / Workspace 管理

**目标**：让用户知道 Agent 当前在哪个项目、哪个目录、哪个分支和哪个权限范围里工作。

**内容**：

- 最近项目列表；
- 添加本地项目目录；
- 项目显示名称与真实路径分离；
- 当前 workspace；
- 当前 branch/worktree；
- 目录不可访问、目录不存在和 Git 非仓库状态；
- 项目级默认模型、权限和终端配置；
- 项目隐藏/移除入口不删除用户代码。

**验收**：

- 打开两个项目不会串 cwd；
- 新 Thread 必须明确绑定 workspace；
- workspace 改变时 UI 和 appserver 都收到新的上下文；
- 路径信息不会被错误展示到另一个项目的 Thread。

### C5 · Thread / Turn / Item 会话中心

**目标**：把“聊天窗口”提升为可恢复、可分叉、可审查的工作历史。

**内容**：

- Thread 新建、恢复、重命名、归档、删除、分叉；
- 按项目、workspace、状态和更新时间筛选；
- Turn 开始、追加输入、steer、中断、重试；
- Item 持久化和分页；
- 会话标题自动生成但允许用户修改；
- 未发送草稿只留在客户端，不伪造成 Agent 输入；
- 归档不等于删除；删除前显示影响范围。

**验收**：

- 重启应用后 Thread 列表和历史一致；
- 分叉 Thread 不会修改父 Thread；
- 重试不会重复写入已经完成的 Item；
- 归档 Thread 不出现在默认 active 列表，但仍可恢复；
- 删除行为有明确确认和后端审计记录。

### C6 · 对话时间线与流式 Item 渲染

**目标**：让用户能在一条可读时间线上理解 Agent 做了什么。

**内容**：

- message delta 合并；
- tool/command/file-change/approval/error 卡片；
- long output 折叠和展开；
- markdown/code block 渲染；
- item 状态图标和文本标签；
- 中断、暂停、继续和失败的明确呈现；
- 大 Thread 的虚拟滚动和分页；
- 不显示不可展示的原始 reasoning，仅显示允许的摘要或状态说明。

**视觉辅助环节**：Grok 可对正常、空、加载、长输出、错误、窄窗口、深色主题截图验收；Composer 负责组件、状态模型、测试和最终合并。

**验收**：

- delta 乱序和重复不会产生重复文字；
- 关掉右栏不影响时间线；
- 1000 个 Item 的 Thread 仍可滚动和定位；
- 流式中断不会丢失已收到的内容；
- 工具失败不被渲染成“成功完成”。

### C7 · Tool、Command、Background Task 工作台

**目标**：把 Agent 的工具执行从一行状态文字升级成可观察、可控制的执行记录。

**内容**：

- 工具名称、参数摘要、风险等级；
- 命令、cwd、环境摘要、退出码；
- stdout/stderr 分离；
- 输出增量和截断提示；
- 运行中、成功、失败、取消、超时、等待审批；
- 后台任务列表；
- 查看最新输出；
- 停止单个任务；
- 进程已退出但输出未读时的通知；
- 用户主动执行的命令与 Agent 工具调用分开标记。

**安全要求**：环境变量、API Key、Authorization header 和敏感路径必须在 UI 和日志中脱敏。

### C8 · Permission Center 与审批流

**目标**：让审批既安全又可理解，且不会因为 UI 约定被绕过。

**权限档位**：

```text
read_only
workspace_write
ask_for_each_risky_action
allow_scoped_actions
full_access（明确危险，默认不可选）
```

**审批卡必须显示**：

- 要执行的动作；
- 工具和命令；
- cwd；
- 受影响路径；
- 风险等级；
- 预计是否会写文件、联网或启动子进程；
- 允许范围；
- 作用域和过期时间；
- 拒绝后的后果。

**验收**：

- 允许一次不会影响下一次；
- 项目级允许不会扩展到其他项目；
- 撤销后旧的允许记录不再生效；
- appserver 重启后只恢复明确持久化的 policy；
- UI 无审批按钮时，后端仍然拒绝未授权动作；
- 所有审批结果有 `approval_id` 并进入 trace。

### C9 · Git Diff 与 Review 工作台

**目标**：让“审计”成为 Desktop 的一等能力，而不是把命令输出塞进聊天窗口。

**内容**：

1. 显示工作区状态、未跟踪文件、修改文件和冲突。
2. 支持 unified diff 和 side-by-side diff。
3. 点击 finding 定位到文件和行。
4. 对大文件和二进制文件显示摘要，不直接把内容全部塞进上下文。
5. 支持 `review/start`：working tree、base branch、commit、指定文件。
6. 显示 P0–P3/info finding，支持展开证据和建议。
7. 允许用户把一条 finding 作为下一轮输入发回 Agent。
8. 变更 hash 改变后，旧 Review 标记 stale。
9. 提供安全的“打开外部编辑器”和“撤销文件变更”入口；撤销前必须显示范围。

**验收**：

- Git 非仓库时不显示假 diff，而是显示可理解的引导；
- 未跟踪文件可在 diff 中被识别；
- review 不修改工作树；
- review 绑定的 diff hash 与界面显示一致；
- Agent 修复后旧 finding 自动失效或标记 fixed，不能保持“当前开放”；
- CLI、Desktop 对同一 review 结果使用同一协议对象。

**视觉辅助环节**：Grok 只负责 diff 对齐、长行换行、折叠、深色主题、错误和空状态的视觉验收；审查语义和 hash 绑定由 Composer 主写并测试。

### C10 · 文件树、预览与外部编辑器

**目标**：让用户从 Agent 的变更直接进入文件上下文，而不必每次手工定位。

**内容**：

- 当前 workspace 文件树；
- 只读文件预览；
- Markdown、纯文本、代码、JSON/YAML、图片的安全预览；
- 文件过大、编码异常和二进制文件的占位提示；
- 从 Item、Diff 或 Review finding 定位文件；
- 用系统默认编辑器打开；
- 不在 Desktop 内偷偷写文件，写入必须来自 Agent 工具或明确用户动作；
- 路径遍历和 workspace 外文件访问检查。

**依赖**：图片预览可以先作为能力项；未来 Phase E 的多模态能力可以复用同一 preview item，不得重新定义另一套文件对象。

### C11 · Git Branch / Worktree 与执行环境

**目标**：支持多个独立工作上下文，降低并行任务互相覆盖的风险。

**内容**：

- 显示当前 branch 和 worktree；
- 创建、打开和关闭 worktree；
- Thread 绑定 workspace/worktree；
- 从当前 Thread handoff 到另一个 worktree；
- worktree 被其他进程删除、分支冲突和路径不可用时给出恢复入口；
- 禁止两个 Thread 默认共享同一个正在修改的目录，除非用户明确确认；
- 不在 C11 自动提交用户代码；
- commit、revert、clean 等破坏性动作必须经过权限中心。

**验收**：

- 两个 Thread 在不同 worktree 修改时不串变更；
- UI 显示的 branch 与后端命令实际 branch 一致；
- 关闭 worktree 前显示未提交变更；
- worktree 创建失败不会留下半成品入口。

### C12 · Settings、模型目录与安全存储

**目标**：把模型、Provider、推理档位、权限、终端和项目偏好放到有作用域的设置系统里。

**设置层级**：

```text
global defaults
  ↓
project settings
  ↓
workspace override
  ↓
thread/turn explicit override
```

**内容**：

- 使用 Phase A 的模型 capability 和 provider registry；
- 模型选择、reasoning/effort、上下文策略；
- API Key 使用系统密钥链或 Electron secure storage；
- 明文配置文件不保存 secret；
- 模型不可用、Key 无效和 quota 错误分开显示；
- 设置变更显示影响范围；
- 变更模型不隐式改变已有 Thread 的历史解释；
- 记录 settings schema version，支持迁移和回滚。

**验收**：

- 日志、错误和 crash payload 不含完整 secret；
- global/project/workspace 层级覆盖可测试；
- Desktop 与 CLI 对同一配置层级的解释一致；
- 模型 capability 未声明时，UI 不显示不支持的输入或工具选项。

### C13 · Skills、MCP、浏览器与可插拔能力面板

**目标**：让外部能力以可发现、可审批、可审计的方式进入 Desktop，而不是散落在 UI 按钮里。

**本卡只做统一入口和能力投影**：

- Skills 列表和启用状态；
- MCP server/tool 列表；
- 工具来源、权限和连接状态；
- 浏览器/网页能力的 capability 占位和错误呈现；
- 每个外部能力都显示来源和所需权限；
- 外部能力调用仍生成普通 Tool/Approval/Review Item。

浏览器的完整自动化实现可以后续扩展，但 Desktop 不能把 browser 设计成一个绕过协议和审批的特殊窗口。

**验收**：

- 未安装/未授权能力不会显示为可用；
- MCP 工具调用和内置工具使用同一套审计链；
- Skill/MCP 失败不会让主 Thread 永久卡住；
- 外部工具的返回数据可以收起、复制和定位来源。

### C14 · Notifications、长任务与恢复体验

**目标**：让用户离开当前 Thread 后，仍然知道 Agent 是否完成、失败或等待审批。

**内容**：

- 后台 turn 状态；
- 系统通知；
- 等待审批通知；
- 等待用户输入通知；
- 长命令完成通知；
- 失败通知；
- 点击通知回到对应 Thread/Item；
- 防重复通知；
- 用户可关闭通知类型；
- Desktop 重启后恢复未完成 Thread 的真实状态。

### C15 · 视觉系统、可访问性和交互一致性

**目标**：让 RxyCode Desktop 具备稳定而可扩展的视觉基础，而不是每张卡各写一套颜色和 loading。

**内容**：

- design tokens：颜色、间距、字体、圆角、阴影、z-index；
- light/dark/high-contrast 主题；
- 键盘导航和 focus ring；
- 关键操作的快捷键；
- aria label、可读状态和错误提示；
- loading/empty/error/disabled/running/paused/completed 组件状态；
- 长文本、长路径、窄窗口和高 DPI；
- 禁止用颜色单独表达风险等级；
- 禁止把截图中的像素值硬编码成业务逻辑。

**Grok 辅助范围**：

- 视觉回归截图；
- 主题对照；
- 复杂布局溢出；
- 图片/文件预览；
- 审批弹层和 diff 面板的视觉层级。

Composer 负责最终组件 API、状态覆盖测试和无障碍语义。

### C16 · 打包、更新、崩溃上报与发布门禁

**目标**：让用户安装的是可诊断、可升级、可回滚的 RxyCode Desktop，而不是开发机上的临时 Electron 文件夹。

**内容**：

- Windows/macOS/Linux 构建；
- Python runtime 和依赖打包；
- protocol schema、generated types 和 appserver 版本绑定；
- 代码签名/公证能力的配置入口；
- 自动更新检查、下载、安装和失败回滚；
- 崩溃报告脱敏、用户同意、关闭入口；
- 诊断包只包含必要的版本、平台、日志摘要和协议状态；
- CI 生成可验证的构建产物和 checksum；
- 安装后首次启动、升级后启动、回滚后启动测试。

**验收**：

- 三平台至少完成 typecheck、unit test、package smoke test；
- 产物能启动 appserver 并完成一次真实协议握手；
- appserver 版本不匹配时能显示清楚错误；
- 更新失败不会删除旧版本；
- crash report 默认不上传代码内容、Key、完整 prompt 或完整工具输出。

---

## §7 安全与隐私

### 7.1 四个边界

```text
用户意图边界       用户输入、审批、取消、review 接受
协议边界           schema、capability、版本、事件
执行边界           appserver、tools、sandbox、子进程
呈现边界           Desktop、CLI、TUI、外部编辑器
```

任何安全规则必须在执行边界生效，不能只在呈现边界隐藏按钮。

### 7.2 Secret 处理

禁止：

- 把 API Key 放进 React state 的持久化快照；
- 把 Key 写入 transcript；
- 把完整环境变量发送给 renderer；
- 把 authorization header 写入工具卡片；
- 把完整 prompt/工具输出无条件上传 crash 服务。

允许：

- renderer 请求“是否已配置”而不是读取 secret；
- main process 使用系统密钥链；
- appserver 只得到完成当前请求所需的 secret；
- 日志使用稳定脱敏占位符。

### 7.3 权限审计

每次允许或拒绝至少记录：

```text
approval_id
thread_id / turn_id / item_id
requested_action
scope
decision
actor = user / policy / timeout
created_at / expires_at
```

权限日志是审计记录，不是用户可编辑的业务数据。

### 7.4 路径和文件预览安全

- 所有路径先 canonicalize；
- workspace 外访问必须由后端 policy 决定；
- symlink 不得绕过路径检查；
- 文件预览默认只读；
- 图片、HTML、SVG 预览必须隔离脚本执行；
- 下载、外部编辑器和打开 URL 需要明确用户动作或审批；
- 文件名和内容不能注入 HTML/Markdown 渲染器。

---

## §8 测试与视觉验收

### 8.1 测试分层

| 层级 | 测什么 | 失败时归属 |
|---|---|---|
| Protocol contract | schema、版本、请求、事件、错误 | protocol/appserver |
| Unit | reducer、状态机、diff hash、权限 scope | core/feature |
| Component | Item 卡片、审批、diff、设置、空/错状态 | Desktop UI |
| Process integration | spawn、握手、关闭、崩溃、重启 | host/appserver |
| E2E | 创建项目→Thread→工具→审批→变更→review | Desktop 全链路 |
| Visual regression | 布局、主题、长文本、弹层、diff | Grok 辅助 + Composer 收口 |
| Package smoke | 安装、升级、启动、协议握手 | release/CI |

### 8.2 最小 E2E 场景

必须覆盖：

1. 新项目创建 Thread，Agent 返回文本。
2. Agent 流式输出被正常渲染。
3. Agent 调用工具并展示输出。
4. 高风险工具等待审批，允许一次后继续。
5. 拒绝审批后 Agent 得到明确拒绝结果。
6. Agent 修改文件，Desktop 显示文件变更。
7. Review 生成 finding，点击 finding 定位 diff。
8. 文件再次修改，旧 Review 进入 stale。
9. Thread 中断后恢复。
10. appserver 崩溃后重启并补读历史。
11. 两个 worktree 的 Thread 不互相串目录。
12. Key 不出现在日志、transcript 或 crash payload。
13. Git 非仓库项目仍能聊天，但不显示伪造的 Git review。
14. 未声明 capability 时相应面板进入禁用/说明态。

### 8.3 视觉验收清单

每张带视觉环节的卡至少提供：

- 正常态截图；
- 空态截图；
- 加载态截图；
- 错误态截图；
- 长文本或长路径截图；
- 深色主题截图；
- 窄窗口截图；
- 键盘 focus 截图或录屏；
- 视觉问题是否影响协议/状态的判断。

Grok 的交付物是视觉观察和复现步骤，不是未经审查的主分支实现。Composer 必须把视觉问题转成可测试的组件状态或回归用例。

### 8.4 完成前的机械门

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
python -m pytest -q
cd frontend\protocol-client
npm test -- --run
cd ..\desktop-app
npm run typecheck
npm run test -- --run
npm run build
```

命令名如果因实际脚手架不同而调整，必须在卡内记录真实命令；不能用“本地能跑”代替可复制的验收命令。

---

## §9 LinkAgent 扩展契约

### 9.1 LinkAgent 应该复用什么

LinkAgent 建在完整 RxyCode Desktop 之上时，理想复用边界是：

```text
复用：
  Electron host
  项目/Thread/Turn/Item 基础 UI
  protocol-client
  diff/review/approval 基础组件
  settings 和安全存储适配层
  打包、更新、崩溃和 CI 基础设施

替换或扩展：
  LinkAgent appserver
  EKO/森林视图
  EKO 检索解释
  LinkAgent 专属协议方法
  LinkAgent 专属导航和只读面板
```

### 9.2 LinkAgent 不应该做什么

- 不直接修改 RxyCode Desktop 的核心 Agent 逻辑；
- 不复制一套 Thread/Approval/Diff 状态机；
- 不绕过 `protocol-client` 读取 Python 对象；
- 不把 EKO 编辑按钮塞进普通文件编辑路径；
- 不把 LinkAgent 专属数据写入 `~/.rxycode/`；
- 不依赖 Desktop 内部未声明的 React component state。

### 9.3 Desktop 扩展点

本 Phase 至少预留：

```text
desktop extension manifest
  ├─ appserver capability additions
  ├─ protocol method additions
  ├─ navigation item
  ├─ panel/inspector item
  ├─ item renderer registration
  ├─ settings section
  └─ permission/review metadata extension
```

扩展注册表必须是可选的；没有 LinkAgent 时，RxyCode Desktop 不得加载或等待 LinkAgent。

### 9.4 LinkAgent 的稳定性要求

LinkAgent L9 依赖的最低稳定契约是：

- `protocol-client` 的 transport 和生成类型流程；
- Project/Workspace/Thread 的基本生命周期；
- approval request 的作用域和回执；
- file change / diff / review 的对象结构；
- extension capability handshake；
- appserver 启动、关闭、重连和错误模型。

这几项必须进入 Desktop 的契约测试，不能只存在于本文的描述里。

---

## §10 出口标准

### 10.1 功能出口

RxyCode Desktop 完成必须满足：

- 用户可以管理多个本地项目和 workspace；
- 用户可以新建、恢复、重命名、归档和分叉 Thread；
- 用户可以看到流式消息和每个执行 Item；
- 工具、命令、文件变更和审批有不同的可读卡片；
- 高风险动作通过后端权限门，不依赖隐藏按钮；
- 用户可以查看 Git diff 和 review findings；
- Review 结果绑定 diff hash，代码变化后自动失效；
- 用户可以定位文件、预览文件和打开外部编辑器；
- 用户可以使用独立 worktree 避免任务互相覆盖；
- appserver/窗口崩溃后不会留下孤儿进程；
- 重启后可以恢复真实 Thread 状态；
- 模型和 Key 设置有作用域且安全存储；
- Skills/MCP/未来浏览器能力走 capability、审批和审计链；
- Windows/macOS/Linux 至少有可验证构建与安装 smoke test。

### 10.2 架构出口

- Desktop 不直接 import Python；
- Desktop 不直接调用 HTTP API；
- UI 不包含 Agent 业务路由；
- protocol schema 是唯一跨语言契约来源；
- OpenTUI 和 Desktop 可以消费同一套类型；
- 所有 server request 有 response、timeout 和 cancel 路径；
- 所有异步 Item 有明确终态；
- 所有 Review/Approval 记录可追溯到 Thread/Turn/Item；
- 所有扩展能力通过 capability 声明；
- LinkAgent 可以在不改 RxyCode core 的情况下 fork/扩展 Desktop 壳。

### 10.3 体验出口

用户不需要打开终端才能回答这些问题：

1. Agent 当前在哪个项目和目录工作？
2. 它现在正在做什么？
3. 它执行过哪些命令？
4. 它改了哪些文件？
5. 哪些动作需要我批准？
6. 这次修改有什么风险？
7. 审查意见是否已经过期？
8. 如果应用崩溃，我能否继续刚才的任务？
9. 我能否安全地撤销某个变更？
10. LinkAgent 能否在不复制整套 Agent 的情况下加自己的视图？

### 10.4 发布前最终回归

```text
协议冻结
  ↓
单 Agent 正常路径
  ↓
审批/拒绝/取消
  ↓
文件变更与 Review
  ↓
Git/worktree 隔离
  ↓
appserver 崩溃恢复
  ↓
Key/日志/crash 脱敏
  ↓
三平台 package smoke
  ↓
LinkAgent extension contract test
  ↓
发布候选版本
```

---

## §11 后续扩展

以下能力在本 Phase 预留接口，但不允许为了“看起来完整”而破坏核心交付：

| 能力 | 本 Phase 处理 | 后续归属 |
|---|---|---|
| 图片输入和多模态 Item | file preview/capability 预留，纯文本路径零回归 | Phase E |
| 多模型专家团 UI | capability 和 Thread/Item 可显示，默认不展开高级控制 | Phase D |
| PersonaAgent | extension manifest 和 settings section 预留 | Phase F |
| 远程 appserver | transport 抽象和 version handshake 预留 | 后续独立 Phase |
| 云端任务/团队协作 | 不做实现 | 独立产品路线 |
| 浏览器 Computer Use | 面板和审批入口可插拔 | 后续能力包 |
| 自动 Skill/EKO 生成 | 不做实现 | LinkAgent / 研究路线 |

**重要**：预留不是提前实现。预留的唯一目标是避免未来必须修改 `Project/Thread/Item/Capability/Approval` 的基础语义。

---

## 附录 A · 卡片完成记录模板

每张 C 卡完成时在 commit 或 PR 描述中复制：

```text
Card: C__
Scope:
Owner: Composer 2.5
Grok visual handoff: none / attached below

Changed files:
-

Protocol/schema changed: yes/no
Generated artifacts refreshed: yes/no
Feature flag/capability:

Commands:
```powershell
# exact commands
```

Verification output:
-

Failure/recovery paths tested:
-

Security/privacy checks:
-

Known limitations:
-

Rollback:
- revert commit `...`
```

---

## 附录 B · 与主计划 Phase 3 的关系

不要把本文的 C 卡重新塞回主计划 D1–D8。两者关系是：

```text
主计划 Phase 3 D1–D8
  = Electron 壳、基础协议接入、最小聊天/审批/设置、可打包

Phase C C1–C16
  = 完整项目/会话工作台、执行可观测性、权限中心、diff/review、worktree、恢复、扩展和发布质量
```

如果主计划 Phase 3 的某个 D 卡尚未完成，Phase C 可以做协议和 UX 设计，但不能通过临时 HTTP 或 mock 逻辑绕过前置产物直接合并到主链。

如果 Phase C 的某张卡需要修改主计划 Phase 3 已完成的协议，必须先更新 protocol/schema 和契约测试，再更新 Desktop；不得在 UI 里私自兼容两个互相矛盾的字段语义。
