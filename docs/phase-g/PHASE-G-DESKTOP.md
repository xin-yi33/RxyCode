> **2026-08-20 目录重组**：Phase G 全部文档收口到仓库 `docs/phase-g/`。主链施工：[`backend/PHASE-G-BACKEND.md`](./backend/PHASE-G-BACKEND.md) / [`frontend/PHASE-G-FRONTEND.md`](./frontend/PHASE-G-FRONTEND.md)。增强施工：[`backend/PHASE-G-BACKEND-GX.md`](./backend/PHASE-G-BACKEND-GX.md) / [`frontend/PHASE-G-FRONTEND-GX.md`](./frontend/PHASE-G-FRONTEND-GX.md)。本文仍是产品基线，不再当作两端混写的施工本。

# PHASE-G-DESKTOP（合并版）· RxyCode Desktop 完整文档

> **本文档由三部分合并而成**（原 7 份 Phase G 文档按此结构归并）：
> - **Part 1 权威基线**（原 `PHASE-G-RXYCODE-DESKTOP.md`）：完整产品定义、协议示例、G1-G16 卡、出口标准——**公共基线，验收以此为准**
> - **Part 2 开工总手册**（原 `PHASE-G-KICKOFF.md`）：给前后端两名开发者的协作总纲（前置自检/白名单/git 流程/排期/红线）
> - **Part 3 GUI 增强卡**（原 `PHASE-G-GUI-ENHANCEMENT.md`）：主链出口后的追加阶段 GX1-GX28（P0–P2 批 GX1–GX18 原版 + P3 · Codex 对齐批 GX19–GX28，含 §1 通用纪律/§2 PROTO 登记/§3 出口/§4 排期）
>
> **配套文件**：后端主链 [`backend/PHASE-G-BACKEND.md`](./backend/PHASE-G-BACKEND.md)；后端增强 [`backend/PHASE-G-BACKEND-GX.md`](./backend/PHASE-G-BACKEND-GX.md)；前端主链 [`frontend/PHASE-G-FRONTEND.md`](./frontend/PHASE-G-FRONTEND.md)；前端增强 [`frontend/PHASE-G-FRONTEND-GX.md`](./frontend/PHASE-G-FRONTEND-GX.md)；竞品调研见 `docs/plans/opus5-plan/rxycode/research/2026-08-10-gui-agent-benchmark.md`。
>
> **合并日期**：2026-08-11　**合并原则**：各部分正文一字未改，仅将文件间链接映射到新文件名。

> 🛑 **2026-08-18 · 开任何一张卡之前，先读 [`PHASE-G-CONFLICT-AUDIT.md`](./PHASE-G-CONFLICT-AUDIT.md)**
>
> 本文档成文早于 PHASE-K / L / M / N，也早于仓库现在的目录与协议形态。审计已确证 **9 条会导致照文档施工直接出错**的偏差，其中四条**目前无人认领**。最要紧的三条：
>
> 1. **GX28 依赖一组不存在的协议。** 它声称「纯消费 F18 的 `team_*` 协议」因而免登记 PROTO——但 F18 的交付物里**没有任何协议方法**（全在 `core/agents/*` 与内置工具）。`team/list`、`team/groups`、`team/install` 一个都不存在，也没有任何卡负责建。因为免登记，**连「发现缺失就挂起」的机制都不会触发**。
> 2. **`/team` 在 PHASE-F 与 GX28 里是互斥的两件事**：`PHASE-F:1486` 是 `/team <任务>` 带参强制路由，GX28 是无参打开三层选择窗口。两边都写了「冻结」。
> 3. **目录路径大面积失效**：`src/features/*` 85 处、`appserver/handlers/*` 20 处，仓库里都不存在。前端由 PHASE-M M2 裁定映射，**后端那 20 处目前无人管**。
>
> 另有一节尤其重要：审计表 **§2 是「PHASE-G 已被下游覆盖」索引**。PHASE-FIX 的规则明令施工者「不读整份施工文档，只读本卡 + §0」，所以 OV1（主写模型改 Grok 4.6）、OV3（GUI 纳入基线门）、DM2（设置页四组容器）这些覆盖裁定，**施工者结构性地读不到**。索引放在那里就是为了补这个洞。

> ⚠️ **2026-08-18 追加注记（一）· 本文档只管 Desktop，CLI 不在它的边界内**
>
> 这条写在最前面，因为它决定了「照本文档施工能交付什么」。
>
> **本文档的 ownership 白名单是 `protocol/` + `appserver/` + `frontend/desktop-app/`**（§1 第 4 条 / §3 表 / 红线 5），**不含 `frontend/opentui-app/`**。全文实际涉及 CLI 的地方只有 **GX28 一处**（第 4207 行的 `/team` 命令），且未说明它凭什么豁免白名单。
>
> 后果是：**照本文档把 54 张卡全部做完，OpenTUI（默认 CLI）仍然拿不到其中任何一项能力。** 实测差距包括 `/goal`、`/plugin`、`/usage`、`/diff`、长任务运行态、会话回收站——CLI 一个都没有。
>
> **CLI 侧的对齐归 [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md)**，那份文档同时负责两端共用的长任务内核。本文档**不需要为此改任何一张卡**；GX28 的 CLI 部分保持原样（它已冻结 `/team` 语义，Phase N 直接复用，不重做）。
>
> 另有一条**反向**的信息值得本文档的执行者知道：**CLI 在四处领先 Desktop**——`/effort`（思考强度）、`/permission`（三档审批）、`/schedule`（定时任务）、`/children`+`/child`+`/parent`（子代理导航）。做 GX7 / GX23 / PHASE-M M11 时，`frontend/opentui-app/src/` 里有可直接参考的既有实现。

---

# Part · 1 · 权威基线（G1–G16 公共基线）

> **本部分来源**：原 `PHASE-G-RXYCODE-DESKTOP.md`（合并时正文一字未改，仅链接映射到新文件名）
# Phase G · RxyCode Desktop 完整桌面端（Coding Workspace）

> **在整条路线中的位置**：这是 [`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的后继扩展，编号 Phase G；它把主计划 Phase 4 规划的 Electron 壳、`appserver` 和协议客户端，补成一个可长期使用的 RxyCode Desktop 工作台，并消费主计划 Phase 3 的模型输出上限摘要。Phase 3/4 产物是否已经落地必须以工作区实测为准，不能由本文档的计划描述代替。
>
> **产品名称**：RxyCode Desktop。本文借鉴成熟 coding agent 的交互与协议边界，但不复刻任何第三方品牌、私有实现或视觉资产。
>
> **前置条件**：主计划 Phase 0/1/2/3/4 + [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) + [`PHASE-D-ISOLATED-SUBAGENT.md`](./PHASE-D-ISOLATED-SUBAGENT.md) + [`PHASE-F-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-F-MULTI-AGENT-ORCHESTRATION.md) 的公共契约已冻结。Phase 3 提供模型上限解析和摘要，Phase 4 提供基础 Desktop 壳。Phase F 的高级能力不是单 Agent Desktop 启动的硬依赖；它们通过 capability 握手和 feature flag 接入，不能把 Desktop 绑死在某一个后续 Phase 上。
>
> **后继**：原来的多模型协作文档顺延为 [`PHASE-H-MULTI-MODEL-COLLABORATION.md`](./PHASE-H-MULTI-MODEL-COLLABORATION.md)；多模态顺延为 [`PHASE-I-MULTIMODAL.md`](./PHASE-I-MULTIMODAL.md)；PersonaAgent 预留顺延为 [`PHASE-J-PERSONA-AGENT-INTERFACE.md`](./PHASE-J-PERSONA-AGENT-INTERFACE.md)。
>
> **一句话目标**：让用户可以在一个本地桌面工作台里，管理项目和会话，观察 Agent 的每个执行步骤，审查文件变更，控制权限，恢复中断任务，并在不复制后端业务逻辑的前提下继续扩展 LinkAgent 等薄客户端。
>
> **基线日期**：2026-08-02　**预计工时**：12–16 周（以卡计，不把人的日历估计当作 agent 速度承诺）　**任务卡**：G1–G16

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必须先读) | 谁写、怎么写、什么不许做 |
| [§1 为什么需要新的 Phase G](#1-为什么需要新的-phase-d) | 对主计划 Phase 4 的审计结论 |
| [§2 产品定义](#2-产品定义) | RxyCode Desktop 应该让用户看到什么 |
| [§3 总体架构](#3-总体架构) | Desktop、协议、appserver、Session 的边界 |
| [§4 交互模型](#4-交互模型) | Project、Thread、Turn、Item、Review |
| [§5 协议与状态契约](#5-协议与状态契约) | 事件、请求、恢复、版本兼容 |
| [§6 任务卡](#6-任务卡) | G1–G16 的具体施工顺序 |
| [§7 安全与隐私](#7-安全与隐私) | 权限、密钥、日志、崩溃数据 |
| [§8 测试与视觉验收](#8-测试与视觉验收) | 机械测试、E2E、Grok 的辅助边界 |
| [§9 LinkAgent 扩展契约](#9-linkagent-扩展契约) | 为后续桌面套壳和扩展保留稳定缝隙 |
| [§10 出口标准](#10-出口标准) | 什么状态才算 Desktop 真正完成 |
| [§11 后续扩展](#11-后续扩展) | 不在本 Phase 偷塞范围的能力 |

---

## §0 执行手册（必须先读）

### 0.1 这份文档解决什么问题

主计划 Phase 4 计划定义了一个最小 Desktop 壳：Electron + React、启动 `python -m appserver`、显示会话、流式输出、工具卡片、审批和设置，并消费 Phase 3 的模型上限摘要。当前开工前必须实际检查 `frontend/desktop-app/`、`frontend/protocol-client/` 和 `appserver/` 是否存在并能启动；不存在时不得把计划中的壳当成已交付产物。

这足够验证“桌面客户端能不能接上 Agent”，但不够支撑长期编码工作。用户真正需要的是一个工作台：知道自己在哪个项目、当前有哪些会话、Agent 改了哪些文件、哪些动作有风险、任务是否还在后台运行、出了问题如何恢复，以及审查意见如何回到下一轮 Agent。

本 Phase 不推翻 Phase 4 的壳，也不在 UI 里重写 Agent。它只补齐 Phase 4 没有定义清楚的**产品对象、协议对象、审查对象、持久化边界、进程生命周期和扩展边界**，并复用 Phase 3 的模型上限解析结果。

### 0.2 模型分工（硬约束）

| 模型 | 负责 | 禁止 |
|---|---|---|
| **Composer 2.5** | **主写全部代码**：Electron、React、TypeScript、协议客户端、appserver 补充契约、测试、打包、CI、前后端联调 | 不得把 Desktop 本体交给 Grok；不得以“前端”名义绕过协议直接 import Python |
| **Grok 4.5** | 仅做卡内标注的**多模态辅助环节**：启动 dev server、截屏核对、视觉回归、图片/文件预览验收、设计稿对照 | 不写 Python；不改协议主契约；不独立实现没有多模态环节的前端卡；不单独提交 Desktop 主链 |
| **Sonnet 5（可选）** | 对 G2、G5、G7、G8、G10、G15 的 diff 做预审，重点找状态遗漏、权限旁路和进程泄漏 | 不代替 Composer 实现；不作为完成标准 |
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

## §1 为什么需要新的 Phase G

### 1.1 对主计划 Phase 4 的审计结论

主计划 Phase 4 的 G1–G8 在设计上能够形成一个**基础 Desktop 壳**，并接入 Phase 3 的模型上限摘要；但本表只描述设计覆盖，不代表工作区已经实现；实现状态必须由 G1 的实测门确认。

| 审计项 | 结论 | 说明 |
|---|---|---|
| Electron + React 能否启动 | 需实测 | G1 定义了脚手架和 `python -m appserver` 子进程，但当前是否存在必须由 G1 检查 |
| 能否聊天和流式输出 | 可以 | G2/G3 覆盖会话、消息 delta 和中断 |
| 能否展示工具调用 | 基础可以 | 只有 `tool_begin`/`tool_end`，复杂进度和错误状态未定义 |
| 能否审批危险动作 | 基础可以 | G4 有模态框，但作用域、过期、撤销和审计记录不够明确 |
| 能否配置模型、Key、工作区 | 基础可以 | G5 有页面，但秘钥协议、迁移和多项目作用域需要补齐 |
| 能否打包 | 计划可以 | G6–G8 有打包和 CI 目标，但签名、回滚、崩溃恢复未形成契约 |
| 能否长期管理项目和会话 | 不充分 | 没有完整 Project/Thread/Turn/Item 生命周期 |
| 能否审查代码变更 | 不充分 | 没有 diff、文件变更、review finding、行级反馈契约 |
| 能否使用 worktree/Git 工作流 | 未定义 | 没有分支、worktree、提交和撤销的界面边界 |
| 能否供 LinkAgent 稳定套壳 | 有风险 | 壳能 fork，但扩展点、协议超集和持久化边界不够清楚 |

因此，主计划 Phase 4 的定位应当保留为：

> **验证 Electron 壳 + appserver + 协议客户端能够工作。**

本 Phase G 的定位是：

> **把这个壳补成可用于真实编码工作的 RxyCode Desktop 工作台。**

### 1.2 现有 Phase 4 的主要歧义

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

### 5.5 Review 协议（冻结版）

`review/start` 是 Desktop、CLI 和 LinkAgent 共用的 JSON-RPC 请求，不是 UI 私有动作。它只读取指定变更，不直接修改工作树。

```json
{
  "method": "review/start",
  "params": {
    "request_id": "req_review_123",
    "thread_id": "thr_123",
    "turn_id": "turn_456",
    "scope": "working_tree",
    "base_ref": null,
    "head_ref": "HEAD",
    "paths": [],
    "criteria": ["correctness", "security", "regression"],
    "reviewer": {"kind": "agent", "agent_id": "reviewer"}
  }
}
```

response：

```json
{
  "request_id": "req_review_123",
  "review_id": "rev_123",
  "status": "pending",
  "diff_hash": "sha256:..."
}
```

服务端必须发送以下通知，并保证 `sequence` 单调、`event_id` 幂等：

```text
review/started
review/progress
review/finding
review/completed
review/stale
review/failed
review/cancelled
```

`review/finding` 的 payload 必须符合 §4.5 的 Finding；`review/completed` 必须返回完整 `Review` 或可通过 `review/read` 补读的引用。客户端断开后可用 `review/read(review_id)` 补读，不得重新启动一次审查来“猜测”结果。

固定错误码：`REVIEW_SCOPE_INVALID`、`REVIEW_DIFF_UNAVAILABLE`、`REVIEW_ALREADY_RUNNING`、`REVIEW_CANCELLED`、`REVIEW_TIMEOUT`、`REVIEW_PROTOCOL_MISMATCH`。相同 `request_id` 重试必须幂等，不得生成多个 Review。

### 5.6 快照、撤销和细粒度 Git 操作

每个产生文件变更的 turn 在首次写入前创建 `checkpoint_id`，记录 workspace、前后 `diff_hash`、文件清单和创建原因。快照只由 appserver/host 创建，Renderer 不能伪造。协议至少提供：

```text
checkpoint/list
checkpoint/read
checkpoint/restore
git/stage
git/unstage
git/revert
```

`checkpoint/restore`、整文件 revert 和 hunk revert 都必须经过权限中心；恢复前显示影响范围，恢复后产生新的 `diff_hash` 并令旧 Review 进入 `stale`。这使 Desktop 具备可解释的 undo/redo 边界，而不是只有一个不可追踪的“撤销”按钮。

### 5.7 能力发现

以下能力必须由 appserver 声明，UI 不能假设存在：

```text
threads
thread_fork
background_turns
command_execution
file_changes
review
review_comments
checkpoint
git_hunk_actions
worktree
file_preview
browser
mcp
skills
multi_agent
multi_model
vision
approval.auto_review
```

未声明的能力：

- 不显示不可用按钮；
- 不发出服务端一定会拒绝的请求；
- 仍然可以在设置或帮助页显示“当前版本未提供”。

### 5.8 协议扩展规则

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

### 6.0 卡级施工格式（Composer 必须遵守）

每张 F 卡都必须先冻结以下六项，再允许写代码：

```text
优先级 / 工时 / 依赖 / owner
涉及文件白名单
协议变化（schema / method / event / none）
验收命令与预期结果
完成判据 checkbox
Grok 视觉辅助范围（没有就写“无”）
```

卡内的命令必须能在当前卡完成后复制执行；不存在的目录只能作为 G1 的前置阻塞，不能用“本地能跑”代替命令。Composer 负责协议、状态、权限、测试和最终合并；Grok 只处理卡内明确标出的截图、视觉回归或文件/图片预览环节。

所有 F 卡共同继承以下完成判据；卡内另列的验收项是在此基础上的增量：

- [ ] 文件改动没有超出本卡白名单；
- [ ] 协议/schema 变化已生成类型并通过 contract test；
- [ ] 单元/集成/E2E 命令有真实输出，失败不能以截图替代；
- [ ] `git diff --check` 通过，已记录未解决限制和可回滚 commit。

**编号消歧**：本文任务卡在提交、分支、测试和交接中统一写作 `PhaseG-G1` 至 `PhaseG-G16`；主计划基础壳卡写作 `Phase4-G1` 至 `Phase4-G8`。禁止只写裸 `G1` 作为跨文档引用。

### G1 · Desktop 基线与包边界冻结

`P0` / 1–2d / 无依赖（但依赖主计划 Phase 4 壳和 Phase 3 模型摘要） / **owner: Composer 2.5**
**涉及文件**：`frontend/desktop-app/`、`frontend/protocol-client/`、`appserver/`、`protocol/schema.json`、`tests/test_protocol/`
**协议变化**：none；**Grok**：无。
**验收命令**：`Test-Path frontend\desktop-app; Test-Path frontend\protocol-client; python -m pytest tests/test_protocol -q`；壳不存在时预期输出 `BLOCKED_PREREQUISITE`。

**目标**：确认 Phase 4 的 Electron 壳、`protocol-client`、appserver 和 Phase 3 模型上限摘要能作为本 Phase 的稳定基线；若壳尚未落地，必须先完成最小启动基线或明确阻塞，不得伪造“已有壳”。

**内容**：

1. 先检查 `frontend/desktop-app/`、`frontend/protocol-client/`、`appserver/`、package manifest 和启动脚本；每个缺失项都记录绝对路径和阻塞原因。
2. 若 Electron 壳存在，记录 Desktop 启动方式、Node/Bun/Python 版本和构建命令；若不存在，按 Phase 4 的最小边界创建可启动壳，或输出 `BLOCKED_PREREQUISITE`，不得继续把后续卡标为可验收。
3. 确认 Desktop 包的入口、renderer、main process 和 protocol-client 的边界。
4. 确认 OpenTUI 与 Desktop 是否共享生成的 TypeScript types。
5. 添加 capability/version handshake 的测试占位。
6. 输出一份“可复用 / 需要补齐 / 禁止重写”的文件清单。

**验收**：

- 干净环境能启动 Desktop 与 appserver；
- 如果前置壳不存在，验收结果必须是带缺失清单的 `BLOCKED_PREREQUISITE`，不能报告通过；
- stdout 只有协议数据，日志只在 stderr 或受控日志文件；
- 现有 TUI 测试不因 Desktop 基线整理而回归；
- 没有在 renderer 里新增 Python 或 HTTP 直连。

**禁止**：借 G1 重新整理整个 `frontend/`；没有证据的目录重命名属于独立卡。

### G2 · Protocol handshake、能力发现与错误模型

`P0` / 2–3d / 依赖 G1 / **owner: Composer 2.5**
**涉及文件**：`protocol/schema.json`、`protocol/`、`frontend/protocol-client/`、`frontend/desktop-app/src/protocol/`、`tests/test_protocol/`
**协议变化**：`initialize`、capability、error schema；**Grok**：无。
**验收命令**：`python -m pytest tests/test_protocol -q; cd frontend\protocol-client; npm test`。

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

### G3 · Desktop Host 与 appserver 进程监督

`P0` / 2–3d / 依赖 G1、G2 / **owner: Composer 2.5**
**涉及文件**：`frontend/desktop-app/src/main/`、`frontend/desktop-app/src/preload/`、`frontend/desktop-app/src/platform/`、`appserver/`、`tests/test_appserver/`
**协议变化**：process lifecycle/error events；**Grok**：无。
**验收命令**：`python -m pytest tests/test_appserver -q; cd frontend\desktop-app; npm run typecheck`。

**目标**：解决启动、关闭、崩溃、重启、孤儿进程和多窗口生命周期。

**内容**：

1. 由 main process 启动 appserver。
2. 记录 child PID、启动时间、协议版本和退出码。
3. 启动超时可取消，不能无限等待。
4. appserver 崩溃后保留 thread 状态并显示恢复入口。
5. Desktop 退出时发送优雅 shutdown，再执行有限时间的强制回收。
6. 禁止一个窗口关闭导致其他窗口使用的共享 appserver 被误杀；若暂不支持多窗口，必须明确单实例约束。
7. 临时目录、日志句柄和管道在异常路径也要释放。
8. BrowserWindow 必须显式设置 `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true`，renderer 只能通过最小 preload API 访问平台能力。
9. preload IPC 必须按方法名和参数 schema allowlist 校验；禁止把 `ipcRenderer`、Node `fs`、`child_process` 或完整环境变量暴露给 renderer。
10. 拒绝未 allowlist 的导航、弹窗和外部协议；外部 URL 必须转交系统浏览器并经过明确用户动作或审批。

**验收**：

- appserver 启动失败；
- appserver 启动后立即崩溃；
- Desktop 窗口强制关闭；
- Desktop 重启后恢复 Thread；
- Windows/macOS/Linux 至少各有进程回收测试或明确平台差异；
- 连续启动和退出 20 次不产生孤儿进程。
- renderer 无法直接读取文件、启动进程或读取 Key；
- preload 的每个 API 都有 IPC contract test，未知方法和错误参数均被拒绝。

### G4 · Project / Workspace 管理

`P1` / 2–3d / 依赖 G2、G3 / **owner: Composer 2.5**
**涉及文件**：`appserver/`、`protocol/`、`frontend/desktop-app/src/features/projects/`、`frontend/desktop-app/src/features/workspaces/`、`tests/test_projects/`
**协议变化**：Project/Workspace methods and events；**Grok**：无。
**验收命令**：`python -m pytest tests/test_projects -q; cd frontend\desktop-app; npm run typecheck`。

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

### G5 · Thread / Turn / Item 会话中心

`P0` / 3–4d / 依赖 G2、G3、G4 / **owner: Composer 2.5**
**涉及文件**：`appserver/`、`protocol/`、`frontend/desktop-app/src/features/threads/`、`frontend/desktop-app/src/stores/`、`tests/test_threads/`
**协议变化**：Thread/Turn/Item、parent/child cursor；**Grok**：无。
**验收命令**：`python -m pytest tests/test_threads -q; cd frontend\desktop-app; npm run typecheck`。

**目标**：把“聊天窗口”提升为可恢复、可分叉、可审查的工作历史。

**内容**：

- Thread 新建、恢复、重命名、归档、删除、分叉；
- 按项目、workspace、状态和更新时间筛选；
- 在 Thread 下展示 parent/child session tree：Child 的 Agent、触发方式、状态、耗时、预算、权限摘要和失败原因可展开查看；
- 支持从 Parent 跳转 Child、从 Child 返回 Parent，并按 Child 子树筛选事件；
- Turn 开始、追加输入、steer、中断、重试；
- Item 持久化和分页；
- 会话标题自动生成但允许用户修改；
- 未发送草稿只留在客户端，不伪造成 Agent 输入；
- 归档不等于删除；删除前显示影响范围。

**验收**：

- 重启应用后 Thread 列表和历史一致；
- 分叉 Thread 不会修改父 Thread；
- Parent/Child session tree 与后端事件中的 `parent_session_id`、`root_session_id` 一致，不因刷新或重启丢失；
- Child 的工具调用、审批、预算和终态只归属于对应 Child，不混入 Parent 的普通消息；
- 从 Parent 进入 Child 再返回 Parent 后，当前选择和事件 cursor 可恢复；
- 重试不会重复写入已经完成的 Item；
- 归档 Thread 不出现在默认 active 列表，但仍可恢复；
- 删除行为有明确确认和后端审计记录。

### G6 · 对话时间线与流式 Item 渲染

`P0` / 3–4d / 依赖 G5 / **owner: Composer 2.5**
**涉及文件**：`frontend/desktop-app/src/features/timeline/`、`frontend/desktop-app/src/components/items/`、`frontend/desktop-app/src/stores/`、`frontend/desktop-app/tests/`
**协议变化**：none；**Grok**：正常/空/加载/错误/窄窗口/深色主题视觉验收。
**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。

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

### G7 · Tool、Command、Background Task 工作台

`P0` / 2–3d / 依赖 G5、G6 / **owner: Composer 2.5**
**涉及文件**：`protocol/`、`appserver/`、`frontend/desktop-app/src/features/execution/`、`frontend/desktop-app/src/features/items/`、`tests/test_execution/`
**协议变化**：Tool/Command/BackgroundTask item states；**Grok**：无。
**验收命令**：`python -m pytest tests/test_execution -q; cd frontend\desktop-app; npm run typecheck`。

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

### G8 · Permission Center 与审批流

`P0` / 2–3d / 依赖 G2、G7 / **owner: Composer 2.5**
**涉及文件**：`protocol/`、`appserver/`、`frontend/desktop-app/src/features/approvals/`、`frontend/desktop-app/src/features/settings/`、`tests/test_approval/`
**协议变化**：Approval、Auto-review capability and audit records；**Grok**：审批弹层视觉验收。
**验收命令**：`python -m pytest tests/test_approval -q; cd frontend\desktop-app; npm run typecheck`。

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

**Auto-review 边界**：当 capability `approval.auto_review` 已声明且当前 approval policy 允许时，可以把本来需要人工确认的越界请求交给独立、只读的 reviewer Agent；Auto-review 不是权限扩大，不能改变 sandbox、writable roots、网络或受保护路径。每次 reviewer 决策必须记录 reviewer id、策略版本、理由、原 approval_id 和最终 allow/deny。连续拒绝达到阈值时必须中断当前 turn，不能让主 Agent 无限重试。

### G9 · Git Diff 与 Review 工作台

`P0` / 4–5d / 依赖 G4、G5、G7、G8 / **owner: Composer 2.5**
**涉及文件**：`protocol/`、`appserver/`、`frontend/desktop-app/src/features/review/`、`frontend/desktop-app/src/features/git/`、`tests/test_review/`
**协议变化**：`review/start`、Review/Finding、checkpoint、git hunk actions；**Grok**：diff 对齐、长行、折叠、空/错误态。
**验收命令**：`python -m pytest tests/test_review -q; cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。

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
10. 提供 staged/unstaged、文件级和 hunk 级 stage/unstage/revert；每个动作都经过权限中心。
11. 支持行级 review comment，评论必须绑定 `review_id`、`finding_id`、文件 hash 和行范围，可作为下一轮 Agent 输入。
12. 每个写入 turn 具有关联 `checkpoint_id`，支持列出、查看和恢复；恢复后生成新的 diff hash。

**验收**：

- Git 非仓库时不显示假 diff，而是显示可理解的引导；
- 未跟踪文件可在 diff 中被识别；
- review 不修改工作树；
- review 绑定的 diff hash 与界面显示一致；
- Agent 修复后旧 finding 自动失效或标记 fixed，不能保持“当前开放”；
- CLI、Desktop 对同一 review 结果使用同一协议对象；
- review/start 重试不会创建重复 Review；
- 单个 hunk revert 不影响同一文件的其他 hunk；
- checkpoint restore 后旧 Review 必须 stale，且可从审计记录解释恢复范围；
- 行级评论能回到对应文件、行和下一轮 Agent 输入。

**视觉辅助环节**：Grok 只负责 diff 对齐、长行换行、折叠、深色主题、错误和空状态的视觉验收；审查语义和 hash 绑定由 Composer 主写并测试。

### G10 · 文件树、预览与外部编辑器

`P1` / 2–3d / 依赖 G4、G5、G9 / **owner: Composer 2.5**
**涉及文件**：`frontend/desktop-app/src/features/files/`、`frontend/desktop-app/src/features/preview/`、`frontend/desktop-app/src/platform/`、`tests/test_file_preview/`
**协议变化**：FilePreview/ExternalEditor capability；**Grok**：代码、Markdown、图片、二进制和超长路径视觉验收。
**验收命令**：`python -m pytest tests/test_file_preview -q; cd frontend\desktop-app; npm run typecheck`。

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

**依赖**：图片预览可以先作为能力项；未来 Phase I 的多模态能力可以复用同一 preview item，不得重新定义另一套文件对象。

### G11 · Git Branch / Worktree 与执行环境

`P1` / 3–4d / 依赖 G4、G5、G8、G9 / **owner: Composer 2.5**
**涉及文件**：`appserver/`、`protocol/`、`frontend/desktop-app/src/features/worktrees/`、`frontend/desktop-app/src/platform/git/`、`tests/test_worktrees/`
**协议变化**：Worktree lifecycle/handoff/conflict events；**Grok**：无。
**验收命令**：`python -m pytest tests/test_worktrees -q; cd frontend\desktop-app; npm run typecheck`。

**目标**：支持多个独立工作上下文，降低并行任务互相覆盖的风险。

**内容**：

- 显示当前 branch 和 worktree；
- 创建、打开和关闭 worktree；
- Thread 绑定 workspace/worktree；
- 从当前 Thread handoff 到另一个 worktree；
- worktree 被其他进程删除、分支冲突和路径不可用时给出恢复入口；
- 创建时明确 base branch/ref、工作树路径、分支或 detached HEAD 策略和 owner；
- 关闭、归档、删除和 prune 前检查未提交变更；崩溃或半成品 worktree 可被发现并恢复；
- handoff 必须记录 source/target workspace、未提交变更、冲突结果和可回滚点；
- 禁止两个 Thread 默认共享同一个正在修改的目录，除非用户明确确认；
- 不在 G11 自动提交用户代码；
- commit、revert、clean 等破坏性动作必须经过权限中心。

**验收**：

- 两个 Thread 在不同 worktree 修改时不串变更；
- UI 显示的 branch 与后端命令实际 branch 一致；
- 关闭 worktree 前显示未提交变更；
- worktree 创建失败不会留下半成品入口；
- 删除、prune、handoff 和崩溃恢复都有幂等测试，不会误删用户未提交内容。

### G12 · Settings、模型目录与安全存储

`P1` / 2–3d / 依赖 G2、G8 / **owner: Composer 2.5**
**涉及文件**：`protocol/`、`appserver/`、`frontend/desktop-app/src/features/settings/`、`frontend/desktop-app/src/platform/secrets/`、`tests/test_settings/`
**协议变化**：Settings schema/capability；**Grok**：无。
**验收命令**：`python -m pytest tests/test_settings -q; cd frontend\desktop-app; npm run typecheck`。

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

**P3 对接（追加，2026-08-12）**：设置页由 **GX26/H16 重构为 8 分区**（左下角入口 + 分区导航：回收站/常规/外观/模型选择/模型添加/技能管理/MCP 服务管理/团队与模型预留）——本卡的设置层级（global→project→workspace→thread）、模型选择/密钥链语义**全部保留**，作为 8 分区中"常规/外观/模型"分区的实现基础；语言设置并入 GX22（i18n）；技能/MCP 分区对接 B11。

### G13 · Skills、MCP、浏览器与可插拔能力面板

`P1` / 3–4d / 依赖 G2、G8、G12 / **owner: Composer 2.5**
**涉及文件**：`protocol/`、`appserver/`、`frontend/desktop-app/src/features/capabilities/`、`frontend/desktop-app/src/features/mcp/`、`tests/test_capabilities/`
**协议变化**：Capability/Skill/MCP projections；**Grok**：浏览器/外部能力错误态视觉验收。
**验收命令**：`python -m pytest tests/test_capabilities -q; cd frontend\desktop-app; npm run typecheck`。

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

### G14 · Notifications、长任务与恢复体验

`P1` / 2–3d / 依赖 G3、G5、G7、G8 / **owner: Composer 2.5**
**涉及文件**：`protocol/`、`appserver/`、`frontend/desktop-app/src/features/notifications/`、`frontend/desktop-app/src/features/recovery/`、`tests/test_recovery/`
**协议变化**：Notification/recovery events；**Grok**：通知、断线、恢复和空状态视觉验收。
**验收命令**：`python -m pytest tests/test_recovery -q; cd frontend\desktop-app; npm run typecheck`。

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

### G15 · 视觉系统、可访问性和交互一致性

`P1` / 3–4d / 依赖 G6、G8、G9、G10 / **owner: Composer 2.5**
**涉及文件**：`frontend/desktop-app/src/ui/`、`frontend/desktop-app/src/components/`、`frontend/desktop-app/tests/a11y/`、`frontend/desktop-app/tests/visual/`
**协议变化**：none；**Grok**：视觉回归、主题、布局溢出、图片/文件预览和审批/diff 层级。
**验收命令**：`cd frontend\desktop-app; npm run typecheck; npm run test -- --run`。

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

### G16 · 打包、更新、崩溃上报与发布门禁

`P0` / 4–5d / 依赖 G2、G3、G12、G15 / **owner: Composer 2.5**
**涉及文件**：`frontend/desktop-app/`、`packaging/`、`.github/workflows/`、`tests/test_release/`、`docs/`
**协议变化**：package/appserver compatibility metadata；**Grok**：安装、升级、回滚和错误页视觉验收。
**验收命令**：`python -m pytest tests/test_release -q; cd frontend\desktop-app; npm run build`。

**目标**：让用户安装的是可诊断、可升级、可回滚的 RxyCode Desktop，而不是开发机上的临时 Electron 文件夹。

**内容**：

- Windows/macOS/Linux 构建；
- **双 release 形式（2026-08-10 定）**：Windows 同时产出便携 zip（`rxycode-desktop-<ver>-win-x64.zip`，解压即用、无安装器、无快捷方式；解压到 `~/.rxycode/desktop` 后 `rxycode gui` 自动发现）和安装版（NSIS `-setup.exe`，桌面快捷方式默认开启、安装时可取消）；macOS dmg 与 Linux AppImage/deb 归综合 Release；**一个 tag 挂所有包**；
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


### 6.0 当前落地状态（2026-08-10 记录）

> 本节记录 Phase G 基础壳能力（即主计划 Phase 4 桌面 MVP）的落地状态。**状态口径：**
> 桌面壳 D1-D8 与 D5 模型/凭据管理已合入 master（提交 9cebdae / d0a4469 起）；
> 2026-08-10 的 D5 完成项（跨平台密钥链、桌面添加模型面板、`rxycode gui`、双 Release 配置）
> 在本地 worktree 已完成并全量验证，**尚未 push GitHub**（待用户测试后统一提交发布）。
> 它是对 G1-G16 计划的**实测补充**，不代表这些卡已全部完成；未完成卡仍按各自判据验收。

| 能力 | 状态 | 实现位置 | 验证 |
|---|---|---|---|
| Electron + React 桌面壳（D1-D8） | ✅ 已合入 | `frontend/desktop-app/`（electron-vite + electron-builder） | typecheck / 136 tests / build / smoke 全绿 |
| 协议客户端单源化 | ✅ 已修复 | 桌面端依赖根 `frontend/protocol-client`（`file:../protocol-client`），删除私有副本 | typecheck + 10/10 tests |
| 模型管理（models/list、presets、discover、onboard、onboard_batch、remove、set_active、test_connection） | ✅ 已实现 | `appserver/model_routes.py` + `protocol/requests.py`（10 个请求模型） | 10874 后端测试全绿；e2e 添加模型全流程 OK |
| 凭据管理（credentials/upsert、delete） | ✅ 已实现 | `appserver/model_routes.py`；密钥经 `credential_store` 加密存储，响应不回显 | 脱敏测试（Luna#3）4/4 |
| 跨平台密钥链（DC4） | ✅ 已实现 | `config/credential_store.py`：Windows DPAPI；macOS Keychain / Linux Secret Service（`keyring` 库）；无桌面环境降级 0600 文件 | `tests/test_core/test_credential_keyring.py` 4/4 |
| 桌面设置页「添加模型」面板 | ✅ 已实现 | `SettingsPage.tsx` AddModelPanel（预设→探测→批量添加） | 截图驱动 + e2e 全流程 |
| `rxycode gui` 命令 | ✅ 已实现 | `main.py` `gui` 子命令：`--desktop-dir` 指定 / 默认 `~/.rxycode/desktop` / dev fallback（npm run dev） | `tests/unit/test_gui_command.py` 5/5 |
| 双 Release 打包 | ✅ 配置就绪 | `electron-builder.yml` win target = nsis（安装版，快捷方式可取消）+ zip（便携包，无快捷方式） | `build:win:zip` 实跑产出 870MB 便携包 |
| 发布 CI 预留 | ⏳ 待启用 | `.github/workflows/release.yml` desktop job（windows-latest，`v*` tag 触发，上传 zip+nsis 产物） | 未实际发 release（等用户测试后统一发） |
| 子代理 UI（@agent、child 树） | ❌ 未做 | — | 归后续迭代 |

**打包版本约束**：`frontend/desktop-app/scripts/prepare-runtime.mts` 不再硬编码 RxyCode 版本
（信任 pyproject），并排除 `frontend/desktop-app` 自身避免 vendored 循环
（`cpSync ERR_FS_CP_EINVAL`）。

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
11. Parent 启动 Child，Child tree 显示 Agent、触发方式、状态、预算和权限摘要。
12. 从 Parent 跳转 Child，Child 的工具/审批/结果可审查，再返回 Parent 且 cursor 不丢失。
13. 两个 worktree 的 Thread 不互相串目录。
14. Key 不出现在日志、transcript 或 crash payload。
15. Git 非仓库项目仍能聊天，但不显示伪造的 Git review。
16. 未声明 capability 时相应面板进入禁用/说明态。
17. Review 支持 staged/unstaged diff、文件级与 hunk 级操作，行级评论能绑定 finding、文件 hash 和行范围。
18. 每个产生文件变更的 turn 都有 checkpoint；恢复 checkpoint 后旧 Review 变成 stale，并能在审计记录中解释影响范围。
19. renderer 无法直接访问文件、进程、Key 或任意 IPC；未知 IPC 方法、参数和外部协议都会被拒绝。
20. `approval.auto_review` 未声明或策略不允许时，UI 不显示自动审查入口；允许时仍保留 reviewer、策略版本和最终决定的审计记录。

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
| 图片输入和多模态 Item | file preview/capability 预留，纯文本路径零回归 | Phase J |
| 多模型专家团 UI | capability 和 Thread/Item 可显示，默认不展开高级控制 | Phase H |
| PersonaAgent | extension manifest 和 settings section 预留 | Phase J |
| 远程 appserver | transport 抽象和 version handshake 预留 | 后续独立 Phase |
| 云端任务/团队协作 | 不做实现 | 独立产品路线 |
| 浏览器 Computer Use | 面板和审批入口可插拔 | 后续能力包 |
| 自动 Skill/EKO 生成 | 不做实现 | LinkAgent / 研究路线 |
| **CLI（OpenTUI）能力对齐** | **不做实现**（本文档 ownership 白名单不含 `frontend/opentui-app/`） | **[`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md)** |
| **长任务持久化（`run/*` 与目标模式）** | **不做实现**（`session/prompt` 是同步 RPC，前端 15 分钟兜底，撑不住长任务） | **同上**（Phase N §3 / N1–N6） |

**重要**：预留不是提前实现。预留的唯一目标是避免未来必须修改 `Project/Thread/Item/Capability/Approval` 的基础语义。

> ⚠️ **2026-08-18 追加注记（五）· 上表末两行是新增的，说明本文档一处容易被误解的边界**
>
> 加这两行是因为：本文档从头到尾没说过「CLI 不归我管」，读者很容易默认「Desktop 做完了 CLI 自然也有」。**实测不是这样**——OpenTUI 的 37 个命令里没有 `/goal`、`/plugin`、`/usage`、`/diff`，也没有长任务运行态。
>
> 长任务那一行同样值得单独点出：`session/prompt` 在 Renderer 侧有 **15 分钟**硬超时（`useConversation.ts:814`），而后端 `task_max_time_seconds` 是 7200 秒。**前端会在后端还好好跑着的时候先掐断**，而且这个兜底用的是「总时长」，appserver 的停滞判定用的是「120 秒无进展」——**两者量纲不同**，一个有进展但要跑 40 分钟的任务会被误杀。处置在 Phase N 的 N1。

---

## 附录 A · 卡片完成记录模板

每张 F 卡完成时在 commit 或 PR 描述中复制：

```text
Card: PhaseG-D__
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

## 附录 B · 与主计划 Phase 3/4 的关系

不要把本文的 F 卡重新塞回主计划 G1–G8。两者关系是：

```text
主计划 Phase 4 G1–G8
  = Electron 壳、基础协议接入、最小聊天/审批/设置、可打包

Phase G G1–G16
  = 完整项目/会话工作台、执行可观测性、权限中心、diff/review、worktree、恢复、扩展和发布质量
```

如果主计划 Phase 4 的某个 F 卡尚未完成，Phase G 可以做协议和 UX 设计，但不能通过临时 HTTP 或 mock 逻辑绕过前置产物直接合并到主链。

如果 Phase G 的某张卡需要修改主计划 Phase 4 已完成的协议，必须先更新 protocol/schema 和契约测试，再更新 Desktop；不得在 UI 里私自兼容两个互相矛盾的字段语义。涉及模型上限时，必须复用主计划 Phase 3 的 resolver 和摘要协议，不得在 UI 里重新实现。

---

## 附录 D · Codex 上游复用与 Desktop 集成协议（追加补充）

本附录是对本文既有 §0–§11、G1–G16 和附录 A–B 的补充，不替换、不删减既有内容。本文的 Desktop 目标仍然是 RxyCode Desktop；“参考 Codex”首先指复用公开可验证的核心、App Server、线程/事件/审批协议和测试思路，不假定能够直接复制一个官方完整桌面 UI，也不复制商标、图标、私有认证或未公开服务。

Phase G 的开发顺序必须遵循：

```text
先审计 Codex 公开仓库与 App Server
  → 能直接依赖则直接依赖
  → 能以 fork/vendor 形式复用则锁定 commit 并保留最小补丁
  → 运行时不兼容则以独立 app-server / protocol adapter 接入
  → 只有存在明确证据时才移植状态机或协议语义
  → RxyCode Desktop 只做视图、交互和边界适配，不复制第二套后端真相
```

### C.1 Codex 上游来源与复用对象

| 来源 | 公开可复用或研究的对象 | 许可证/边界 | Phase G 的使用要求 |
|---|---|---|---|
| [Codex 官方源码仓库](https://github.com/openai/codex) | Codex CLI/Core、线程生命周期、turn/item、事件、审批、工具宿主和 app-server 相关实现 | 以仓库当前 LICENSE 为准；当前公开仓库标注 Apache-2.0 | 锁定 commit；保留 LICENSE/NOTICE；不得把私有服务或凭证带入 RxyCode。 |
| [Codex App Server](https://github.com/openai/codex/tree/main/codex-rs/app-server) | 双向 JSON-RPC/JSONL 通信、initialize、通知、Server Request、错误、能力协商和生命周期 | 以该 commit 的仓库许可证和文件头为准 | 优先复用协议形状、事件时序和测试；不要在 Renderer 里重建 app-server。 |
| [App Server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) | app-server 的启动、客户端交互、方法/通知/请求边界 | 公开文档 | 作为实现和验收的入口资料，并记录实际采用的 commit。 |
| [OpenAI Codex harness architecture](https://openai.com/index/unlocking-the-codex-harness/) | 同一 harness 跨 CLI、IDE、Desktop 等表面复用，长生命周期 app-server、线程管理和客户端协议化 | 作为架构参考，不等同于可直接复制的产品代码 | 只把公开可验证的架构边界纳入 RxyCode 契约；不得据此臆造未公开 API。 |

必须明确：公开仓库可以支持对 Codex Core/App Server 的复用或兼容适配，但不自动等于拥有官方完整 Desktop 的所有前端资产、账号体系、远程服务、产品策略和内部实现。RxyCode Desktop 的“像 Codex”验收对象是可验证的工作流和协议行为，包括线程、turn、item、审批、事件、恢复、项目上下文和可观测性。

许可证与第三方边界：

1. 直接复制或 vendor 代码时，保留对应许可证、版权声明和 NOTICE，并在 `docs/decisions/desktop-upstream-reuse.md` 登记。
2. 仅参考协议、架构或交互行为时，也登记来源 URL、commit/版本、参考范围和没有复制的部分。
3. 不复制 Codex/OpenAI 的商标、品牌图标、私有凭证、账号登录流程或未公开服务端实现。
4. 许可证、依赖传递关系或源码归属未确认时，标记 `BLOCKED_LICENSE_REVIEW`，不得合并到主链。

### C.2 Codex → RxyCode Desktop 对照表

| Codex 对照对象 | RxyCode 现有/新增接入点 | 允许的 RxyCode 扩展 | 禁止做法 |
|---|---|---|---|
| Harness / Core | RxyCode backend、Phase A 审计、Phase D Child、Phase F 编排 | provider、model resolver、budget、audit、workspace lease | 让 Desktop 自己再实现一套模型调用和工具执行核心。 |
| App Server | `appserver/` 或既有 app-server 进程边界 | RxyCode method、capability、审计字段、错误码 | Renderer 直接 import Python、直接操作数据库或绕过 app-server。 |
| 双向 JSON-RPC / JSONL | `protocol/schema.json`、`frontend/protocol-client/` | 版本、能力、扩展命名空间 | 使用临时 HTTP/mock 作为长期协议。 |
| Thread | `Thread` / `Session` | parent、child、fork、archive、workspace | UI 私自生成后端不存在的线程。 |
| Turn | `Turn`、运行状态和取消/重试接口 | retry、resume、budget、approval linkage | 用一个 loading 布尔值掩盖 queued/running/waiting/failed/cancelled。 |
| Item | message/tool/diff/approval/error 等增量项 | item metadata、source、redaction、cursor | 把所有事件压成一段最终文本，丢失审计和恢复信息。 |
| Notification / Event | `ThreadEvent`、`ChildSessionEvent`、前端 reducer | sequence、cursor、replay、idempotency key | 依赖前端接收顺序而不做去重和乱序保护。 |
| Server Request / Approval | `approval.requested`、`approval.resolve`、`question.requested` | actor、expiry、reason、audit id | 超时自动 allow，或让 UI 直接写权限状态。 |
| Capability handshake | `initialize`、`capabilities`、版本协商 | feature flags、B/C/F capability | 前端通过猜测版本或字段存在性决定能力。 |
| Local host / client | Electron Main、protocol client、workspace host | OS integration、日志、进程管理 | 把宿主权限放到 Renderer，或将密钥注入浏览器上下文。 |
| Generated schema/types | schema → Python/TypeScript 类型与契约测试 | `x-rxycode-*` 扩展 | Python、TypeScript、UI 各维护一份互相漂移的字段定义。 |

### C.3 三种 Desktop 复用路径

#### C.3.1 路径一：协议对齐与测试复用

适用于 RxyCode 不直接嵌入 Codex Rust/Python 运行时，但需要获得同等级 Desktop 体验的情况。

```text
RxyCode backend / app-server
  ↕ bidirectional JSON-RPC / JSONL
RxyCode protocol-client
  ↕ typed events + reducer
RxyCode Desktop Renderer
```

此路径必须复用可验证的消息方向、初始化、通知、Server Request、错误、thread/turn/item 生命周期和恢复语义；UI 样式可以是 RxyCode 自有实现，但不能改变后端真相。

#### C.3.2 路径二：直接依赖、fork 或 vendor

当公开组件能在 RxyCode 的构建和许可证边界内稳定运行时，优先采用该路径。

```text
Codex public commit
  → locked dependency / fork / vendor
  → RxyCode thin adapter
  → app-server contract
  → Desktop projection
```

硬要求：

- 记录准确 commit、依赖版本、补丁集、许可证、NOTICE 和升级方法。
- 不把 RxyCode 的模型供应商、凭证、workspace lease 或审计逻辑写进不可升级的上游核心。
- 每次升级先运行协议、事件、恢复和安全回归，再由 Composer 2.5 处理冲突和最终合并。

#### C.3.3 路径三：独立 App Server / 协议适配

当 Codex 上游运行时、语言或线程存储与 RxyCode 不兼容时，使用独立进程和薄适配层，不把状态机复制到前端。

```text
Electron Main / RxyCode Host
  → app-server supervisor
  → RxyCode backend 或兼容适配进程
  → JSON-RPC / JSONL
  → protocol-client
  → Renderer reducer / view model
```

适配边界必须包含：

1. `initialize` 和能力协商；
2. thread/turn/item 的创建、恢复、归档、fork 和结束；
3. notification、server request、错误、取消和超时；
4. approval/question 的请求—响应关联、过期和审计；
5. child session tree、Phase D 事件和 Phase 3 模型上限摘要；
6. 进程崩溃、重启、孤儿任务和重连后的 replay/cursor。

适配层只能转换字段、版本和传输方式，不能把后端的权限、预算、模型上限或事件顺序改成 UI 决策。

### C.4 不得重复建设的核心能力

以下能力一旦已有 Codex 上游对照、RxyCode app-server 或 Phase A/D/F 公共契约，就不得在 F 卡中创建第二套不兼容实现：

| 能力 | 唯一真相位置 | Desktop 允许做的事 |
|---|---|---|
| app-server 通道和握手 | backend/app-server + protocol schema | 连接、展示、重连、能力降级。 |
| thread/turn/item 生命周期 | backend/session store + event log | reducer 投影、筛选、恢复入口。 |
| 事件顺序、去重、replay | backend cursor/sequence 协议 | 保证渲染幂等和断线重放。 |
| approval/question | backend policy + approval service | 展示请求、提交用户决定、显示审计状态。 |
| child 生命周期 | Phase D ChildSessionManager | 展示树、跳转、取消、展开事件。 |
| 模型解析和 max token | Phase 3 resolver/summary protocol | 展示来源、当前值、未知模型降级提示。 |
| workspace、文件写入和安全 | backend lease/sandbox/audit | 展示状态、发起明确操作、显示拒绝原因。 |
| LinkAgent 公共接口 | app-server/protocol contract | 只消费稳定协议，不直接访问内部实现。 |

### C.5 Desktop 上游复用决策记录格式

每个进入 F 卡实现的 Codex 复用点登记在 `docs/decisions/desktop-upstream-reuse.md`。字段不能省略；不适用字段填写 `none`。

```yaml
decision_id: D-UPSTREAM-001
status: proposed # proposed | accepted | blocked | superseded
upstream:
  project: codex
  repository: https://github.com/openai/codex
  reference_url: https://github.com/openai/codex/tree/main/codex-rs/app-server
  commit: "<locked-commit>"
  license: Apache-2.0 # verify against the locked commit
capability: bidirectional-app-server-thread-events
reuse_mode: protocol-alignment # direct-dependency | fork | vendor | protocol-alignment | subprocess | semantic-port
reused:
  - "initialize / notification / server request boundary"
  - "thread-turn-item lifecycle and recovery tests"
adapter_files:
  - "protocol/schema.json"
  - "frontend/protocol-client/<adapter>"
  - "appserver/<adapter>"
adaptation_reason:
  - "RxyCode backend and provider lifecycle differ from Codex runtime"
preserved_semantics:
  - "bidirectional request and notification correlation"
  - "event sequence and replay after reconnect"
rxycode_extensions:
  - "x-rxycode-capabilities"
  - "x-rxycode-audit"
  - "x-rxycode-child-session"
verification:
  commands:
    - "python -m pytest tests/test_protocol -q"
    - "python -m pytest tests/test_appserver -q"
    - "cd frontend\\protocol-client; npm test"
  evidence: "<test output / fixture / review link>"
rollback: "<dependency pin rollback or adapter removal procedure>"
owner: composer-2.5
reviewers:
  - "desktop-contract-review"
  - "security-review"
```

### C.6 DR1 · Codex 上游架构与 App Server 复用审计卡

| 字段 | 内容 |
|---|---|
| 卡号 | DR1 |
| 优先级 | P0 |
| 工时 | 1 人日 |
| 依赖 | 主计划 Phase 4 壳、Phase 3 模型上限摘要、Phase A/D/F 已冻结的公共契约 |
| Owner | Composer 2.5（前后端接口与最终收口） |
| 协作 | 其他 Agent 可并行研究 Codex、检查许可证、整理事件样例或做 UI 视觉辅助；不能在 Composer 正在实现的 schema/app-server 公共文件上直接覆盖。 |
| 涉及文件 | `docs/decisions/desktop-upstream-reuse.md`、`protocol/schema.json`、`frontend/protocol-client/`、`appserver/`、`frontend/desktop-app/`、协议和恢复测试目录 |

操作步骤：

1. 锁定 Codex 仓库、App Server 目录、README、架构文章、commit 和许可证。
2. 为 G1–G16 标注协议对齐、直接依赖、fork/vendor、独立进程适配或 semantic-port。
3. 将 Codex 的公开对象映射到 RxyCode Thread/Turn/Item/Event/Approval/Capability，并标记 RxyCode 扩展。
4. 检查现有 `protocol/schema.json`、app-server 和 protocol-client，确定单一真相位置。
5. 确认 Desktop 不直接运行 Python、不直接访问数据库、不在 Renderer 里做权限/预算/max token 判断。
6. 为握手、事件顺序、恢复、审批、Child Tree 和 LinkAgent 消费面建立契约测试。
7. 记录无法直接复用的原因、适配文件、升级风险、许可证风险和回滚路径。
8. Composer 2.5 复核 diff 和测试结果后，才能把 G1–G16 标记为可实施。

完成判据：

- [ ] 每张 F 卡都有 Codex 对照对象或明确的“不适用”理由。
- [ ] 已确认公开 Codex/App Server 能复用的部分没有被重复造轮子。
- [ ] app-server、schema、protocol-client、Renderer 的边界清晰。
- [ ] Thread/Turn/Item/Event/Approval/Capability 的数据流和错误流都有契约。
- [ ] Composer 2.5 已完成最终审计、测试和合并决策。

验收命令（在实现完成后执行）：

```powershell
git ls-remote https://github.com/openai/codex.git HEAD
git diff --check
Test-Path docs\decisions\desktop-upstream-reuse.md
Test-Path protocol\schema.json
Test-Path frontend\protocol-client
Test-Path appserver
rg -n "codex|app-server|reuse_mode|commit|license|adapter|verification" docs\decisions\desktop-upstream-reuse.md
python -m pytest tests/test_protocol -q
python -m pytest tests/test_appserver -q
```

前置状态说明：上面命令属于 DR1 完成后的目标验收，不表示当前仓库已经具备完整 Desktop。当前若 `frontend/desktop-app`、`tests/test_protocol` 或 `tests/test_recovery` 尚不存在，应按本文既有前置规则输出 `BLOCKED_PREREQUISITE`，先完成主计划 Phase 4/协议测试产物；不得用临时 mock 结果冒充通过。

### C.7 DR2 · Desktop 上游兼容回归门

| 字段 | 内容 |
|---|---|
| 卡号 | DR2 |
| 优先级 | P0 |
| 工时 | 1–2 人日 |
| 依赖 | DR1、G1–G3；涉及 Phase D 时必须同时满足 B 的复用审计出口 |
| Owner | Composer 2.5 |
| 协作 | 前端辅助 Agent 只提供视觉和交互检查；后端、协议、测试由 Composer 2.5 统一收口。 |
| 涉及文件 | `protocol/schema.json`、`appserver/`、`frontend/protocol-client/`、`frontend/desktop-app/`、protocol/appserver/recovery/e2e 测试 |

必须覆盖：

1. 首次 `initialize`、版本不兼容、能力缺失和 feature flag 降级。
2. Thread 创建、恢复、fork、归档、关闭和重连。
3. Turn 的 queued/running/waiting/approval/completed/failed/cancelled 状态。
4. Item 增量、顺序、重复事件、断线 replay、cursor 和最终一致性。
5. Approval/question 的请求—响应关联、拒绝、过期、取消和审计展示。
6. Phase D Child Session Tree 的 parent/child 导航、Child 失败、取消、孤儿回收和权限边界。
7. Phase 3 模型 max token 摘要只通过协议消费，不在 UI 重新推断。
8. app-server 崩溃、Electron 重启、后端重启、重复连接和未完成任务恢复。
9. LinkAgent 只使用公共协议；不得直接依赖 Desktop 内部组件。

验收命令：

```powershell
python -m pytest tests/test_protocol -q
python -m pytest tests/test_appserver -q
python -m pytest tests/test_recovery -q
Push-Location frontend\protocol-client
npm test
Pop-Location
Push-Location frontend\desktop-app
npm run typecheck
npm run test -- --run
Pop-Location
```

完成判据：

- [ ] 正常路径和恢复路径都通过，且测试能证明事件幂等和顺序。
- [ ] UI 不保存第二份 Thread/Turn/Item 权威状态。
- [ ] 审批、权限、预算、模型上限和 workspace 安全边界没有 Renderer 旁路。
- [ ] B 的 Child Tree、Phase 3 的模型摘要、Phase F 的编排结果都能通过同一协议呈现。
- [ ] LinkAgent、CLI、OpenTUI 和 Desktop 使用相同的公共契约。

### C.8 Phase G 追加出口门

既有 §10.1–§10.4 和附录 B 的前置条件继续有效；在此基础上，完整 RxyCode Desktop 还必须满足：

1. G1–G16 每张卡都有 Codex 上游对照、复用路径、许可证记录和适配理由。
2. 每个新建的核心能力都有“为什么不能直接复用公开实现”的证据；没有证据的等价重写不予验收。
3. App Server、协议 schema、Thread/Turn/Item/Event、审批、恢复和 Child 生命周期只有一套后端真相。
4. 公开上游代码、fork/vendor 补丁、生成类型、适配层、测试和回滚说明在同一变更链路中可追踪。
5. Phase D 的子代理树、Phase 3 的模型上限 resolver、Phase F 的编排结果和 LinkAgent 都通过公共协议进入 Desktop；不得分别造 UI 专用接口。
6. Codex 上游升级后，协议、事件、恢复、安全和许可证回归均有可重复的验收命令。
7. 只有 DR1、DR2 和既有 G1–G16 完成定义全部通过，才能将 Phase G 标记为完整 Desktop；否则只能标记为部分接入或阻塞项。

---

## 附录 F · Phase G 前后端拆分执行索引（追加补充）

本附录只增加执行入口，不改变本文既有 G1–G16、协议示例、模型适配、Codex/OpenCode 复用规则和验收标准。为支持两名开发者并行施工，新增两份职责文档：

| 执行文档 | Owner 范围 | 主要任务 | 不能越界 |
|---|---|---|---|
| [`PHASE-G-FRONTEND.md`](./PHASE-G-FRONTEND.md) | Electron Main、preload、React/TypeScript、protocol-client、Reducer、组件、视觉、前端测试、前端打包入口 | PhaseG-H1–I13 | 不写 appserver 业务、schema 真相、权限/工具/模型 resolver |
| [`PHASE-G-BACKEND.md`](./PHASE-G-BACKEND.md) | appserver、protocol/schema、Session/Thread/Turn/Item、Child、权限、工具、Git、Review、恢复、ModelSummary、runtime | PhaseG-B1–D13 | 不直接修改 Renderer/组件，不为 UI 创建私有业务状态 |

### D.1 公共基线和命名规则

```text
PHASE-G-DESKTOP.md
  = 完整产品规格、公共协议、原始示例、G1–G16、完整安全/测试/出口标准
    （前后端施工文档里简称「完整 F」= Full baseline，不是 Phase F 专家团）

PHASE-G-FRONTEND.md
  = 前端施工视图，必须引用完整 F（即本文件）的对应卡

PHASE-G-BACKEND.md
  = 后端施工视图，必须引用完整 F（即本文件）的对应卡
```

原 D 的 G1–G16 编号继续保留，用于完整 Phase G 的产品/验收引用；前后端并行开发时必须使用 `PhaseG-H1`、`PhaseG-B1` 这类带前缀编号，禁止在跨文档交接中只写裸 `G1`。

### D.2 G1–G16 到前后端卡的映射

| 完整 F 基线 | 前端执行卡 | 后端执行卡 | 合并条件 |
|---|---|---|---|
| G1 | PhaseG-H1 | PhaseG-B1 | 壳、appserver、schema 和模型摘要前置检查全部有真实结果 |
| G2 | PhaseG-H2 | PhaseG-B2 | handshake、capability、error schema 和客户端投影一致 |
| G3 | PhaseG-H3 | PhaseG-B3 | Electron Host 与 appserver 生命周期、回收、恢复联调通过 |
| G4 | PhaseG-H4 | PhaseG-B4 | Project/Workspace UI 与后端路径/cwd/worktree 真相一致 |
| G5 | PhaseG-H5 | PhaseG-B5 | Thread/Turn/Item/Child Tree、cursor 和持久化一致 |
| G6 | PhaseG-H6 | PhaseG-B5 | 后端 Item 事件与前端时间线 reducer 的幂等/乱序测试通过 |
| G7 | PhaseG-H7 | PhaseG-B6 | Tool/Command/BackgroundTask 状态、输出和取消一致 |
| G8 | PhaseG-H8 | PhaseG-B7 | Approval、Auto-review、权限作用域和审计一致 |
| G9 | PhaseG-H9 | PhaseG-B8 | Review/Finding/diff hash/checkpoint/hunk 操作一致 |
| G10 | PhaseG-H10 | PhaseG-B9 | 文件预览、路径安全、外部编辑器接口一致 |
| G11 | PhaseG-H10 | PhaseG-B9 | Worktree、handoff、冲突和破坏性动作审批一致 |
| G12 | PhaseG-H11 | PhaseG-B10 | 设置层级、secure storage、ModelSummary 和 Phase 3 resolver 一致 |
| G13 | PhaseG-H11 | PhaseG-B11 | Skills/MCP/browser capability、Tool、Approval、审计一致 |
| G14 | PhaseG-H12 | PhaseG-B12 | 通知、长任务、replay、recovery_required 和孤儿回收一致 |
| G15 | I12 | — | 纯前端视觉、无障碍和交互一致性；仍需通过完整 F 体验出口 |
| G16 | PhaseG-H13 | PhaseG-B13 | 前端 build、runtime package、版本绑定、升级/回滚握手一致 |

### D.3 不变项

以下内容在拆分后必须保持原样或保持等价公共语义：

1. Composer 2.5 主写、Grok 4.5 仅视觉辅助、Sonnet 5 可选预审的模型分工；
2. Phase 3 按真实 `model_id` 解析 `model_max_output_tokens`，未知模型使用高位 fallback 并标记来源；
3. OpenCode 子代理和 Codex/App Server 的上游复用优先、许可证、commit、适配和回滚要求；
4. 完整 F §5 的 initialize、事件 envelope、Review、checkpoint、capability 和恢复示例；
5. 完整 F §8 的测试分层、20 个最小 E2E 场景、视觉验收和机械门；
6. 完整 F §10 的功能、架构、体验和发布出口；
7. Phase D Child Tree、Phase 3 ModelSummary、Phase F 编排和 LinkAgent 都只能经公共协议进入 Desktop。

### D.4 并行开发协议

```text
后端 D1/D2 冻结 schema + capability + fixtures
  ↓
前端 I1/I2 接入 protocol-client + reducer
  ↓
后端继续 D3–D13，前端继续 I3–I13
  ↓
共享协议变更单 + 生成类型 + contract test
  ↓
前后端分别验收，再执行完整 F 的跨端 E2E / package / LinkAgent 门
```

- 两人可以使用不同分支和不同目录并行开发；
- `protocol/schema.json`、`appserver/`、Python backend tests 由后端独占；
- `frontend/desktop-app/`、`frontend/protocol-client/`、前端 tests 由前端独占；
- 共享协议变化必须先由后端提交变更单，前端不能在 UI 中临时兼容两个互相矛盾的字段；
- Composer 2.5 负责两个分支的协议、测试、冲突和最终合并；Grok 不直接合并 Desktop 主链。

### D.5 拆分后的完成定义

前端文档或后端文档单独完成，都只能输出 `READY_FOR_FULL_D_INTEGRATION`。只有：

- I1–I13 和 D1–D13 均完成；
- 完整 F G1–G16 的原始验收均通过；
- 协议、事件、权限、模型摘要、恢复、审计、打包和 LinkAgent contract test 全部通过；
- Composer 2.5 完成最终 diff、真实命令验证和合并 commit；

才能把 Phase G 标记为完整 RxyCode Desktop。


---

# Part · 2 · 开工总手册（双人协作总纲）

> **本部分来源**：原 `PHASE-G-KICKOFF.md`（合并时正文一字未改，仅链接映射到新文件名）
# Phase G 开工手册（总手册）· RxyCode Desktop 前后端分离开发

> **读者**：后端开发者、前端开发者（两人，分别在 GitHub 仓库建分支并行开发）。
> **本文回答**：做什么、从哪开始、谁做什么、怎么配合、怎么验收、什么不许做。
> **配套文档**：后端专属清单 [`PHASE-G-BACKEND.md`](./PHASE-G-BACKEND.md) ｜ 前端专属清单 [`PHASE-G-FRONTEND.md`](./PHASE-G-FRONTEND.md) ｜ 增强任务卡 [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md) ｜ 竞品基准调研 [`research/2026-08-10-gui-agent-benchmark.md`](./research/2026-08-10-gui-agent-benchmark.md)
>
> **创建**：2026-08-10　**基线**：仓库 master（含 Phase 4 壳 `frontend/desktop-app/` 与 Phase D `core/subagents/`）

---

## §0 一页看懂

我们正在把 RxyCode（已经能跑的 AI 编码助手）做成一个**完整的桌面工作台**（RxyCode Desktop）：管理项目、会话、代码审查、权限审批、任务恢复。这是 Phase G，主链执行卡 = 后端 B1-B13（13 张）+ 前端 H1-H13（13 张）= **26 张**（它们是对完整 G 文档 G1-G16 的前后端拆分实施，拆分关系见 G-B/G-H 文档），主链完成后还有 28 张增强卡（GX1-GX28：P0-P2 批 18 张原版 + P3 · Codex 对齐批 10 张，配套前端基建 H14-H19 与后端 B14-B18 追加卡，追加阶段）。

**两个人怎么分工**（一句话）：
- **后端**：App Server、协议（schema）、会话/线程真相、权限、工具、Git、恢复——**产出协议和状态，别人消费它**
- **前端**：Electron 壳、React 界面、协议客户端——**只消费协议，不自己造真相**

**协作规则一句话**：你们之间只有一个交接点——`protocol/schema.json`。后端写它，前端读它。谁改 schema，谁负责生成类型 + 跑契约测试，并通知另一方。

---

## §1 必读文档清单（开工前按顺序读完）

| 顺序 | 文档 | 为什么读 |
|---|---|---|
| 1 | `docs/plans/opus5-plan/README.md` | 项目全景：RxyCode + LinkAgent 两个项目的关系 |
| 2 | `docs/plans/opus5-plan/rxycode/README.md` | RxyCode 路线全景与"基线不绿不算完"的铁律 |
| 3 | `docs/plans/opus5-plan/rxycode/PHASE-G-DESKTOP.md` | **公共基线**：完整产品定义、协议示例、G1-G16 验收、出口标准（必读全篇） |
| 4 | 你那份拆分文档 | 后端读 `PHASE-G-BACKEND.md`；前端读 `PHASE-G-FRONTEND.md` |
| 5 | `docs/plans/opus5-plan/rxycode/PHASE-G-DESKTOP.md` | 主链完成后的 28 张增强卡（追加阶段） |
| 6 | `docs/plans/opus5-plan/rxycode/research/2026-08-10-gui-agent-benchmark.md` | 10 款竞品 GUI 基准调研（借鉴来源，可选读） |

> 权威规则：**完整 G 文档是唯一公共基线**。前后端拆分文档只增加各自 owner、文件白名单、任务卡和交接要求，不替换完整 G。

---

## §2 前置条件自检（开工第一件事，缺一项就停下）

在 `D:\agent-demo\RxyCode\RxyCode1_1_0`（或你的 clone）执行：

| # | 检查项 | 对应依赖卡 | 缺失时 |
|---|---|---|---|
| 1 | `frontend/desktop-app`（Phase 4 壳） | H1/G1 起步 | BLOCKED（H1） |
| 2 | `frontend/protocol-client`（协议客户端） | H1/H2 | BLOCKED（H1） |
| 3 | `appserver`（App Server） | B1/B3 | BLOCKED（B1） |
| 4 | `protocol/schema.json`（协议 schema 唯一交接点） | B1/B2 | BLOCKED（B1） |
| 5 | `config/model_catalog.py`（Phase 3 模型目录） | B10/GX7 | BLOCKED（B10） |
| 6 | `config/model_capabilities.py`（Phase A 能力契约） | B5/B6/B7 | BLOCKED（对应卡） |
| 7 | `core/subagents/runtime.py`（Phase D ChildRuntime 契约） | B5/B6/B7 | BLOCKED（对应卡） |
| **8** | **`protocol/` 内存在 `AgentEvent` / `event/agent`（PHASE-E E4 事件域）** | **GX19** | **2026-08-18 实测通过** |

> **第 8 项是 2026-08-18 追加的**，原表只有 7 项。补它的原因是 GX19 依赖 PHASE-E E3/E4，而本表原先查不到 E——**七项前置里没有一项能反映 E 阶段是否就位**。2026-08-18 实测该项**通过**（`protocol/` 与 TS 生成物三处全中，E 阶段 165 个契约测试全绿），所以它现在是一条会过的检查；补进来是为了让门控**有能力**发现 E 缺失，不是因为 E 缺失。
>
> 第 8 项用符号探测而非 `Test-Path`，因为 E4 交付的是**协议里的事件类型**，没有对应的独立文件——查文件会漏。

```powershell
$items = @("frontend/desktop-app","frontend/protocol-client","appserver","protocol/schema.json","config/model_catalog.py","config/model_capabilities.py","core/subagents/runtime.py")
foreach ($i in $items) { "{0,-40} {1}" -f $i, (Test-Path $i) }
# 第 8 项：E4 事件域（符号探测，非文件探测）
$e4 = @(Select-String -Path (Get-ChildItem -Recurse -Include *.py,*.json -Path protocol) -Pattern 'AgentEvent|event/agent' -List).Count -gt 0
"{0,-40} {1}" -f "protocol: AgentEvent/event/agent (E4)", $e4
```

**纪律**：任何一项为 `False` → 输出 `BLOCKED_PREREQUISITE`（带缺失清单），**禁止用 mock / 临时 HTTP 绕过前置产物**。这是 Phase G 的红线之一。

前置条件为什么是这些（权威依据见完整 G 文档头部）：
- 主计划 Phase 0/1/2/3/4 完成（Phase 3 给模型摘要，Phase 4 给 Electron 壳）
- Phase A / Phase D 公共契约已冻结（Phase A：`config/model_capabilities.py`；Phase D：`core/subagents/` 全套 + `appserver/subagent_routes.py`）；**缺失时输出带卡号（B5/B6/B7 等依赖卡）的 BLOCKED 清单**
- Phase F 的**高级能力不是硬依赖**——通过 capability 握手 + feature flag 接入，不用等 F

---

## §3 分工与文件所有权（白名单，不可越界）

来源：G-B §1.2。**这是防"静默丢代码"的物理边界**。

| 范围 | 后端 | 前端 | 说明 |
|---|---|---|---|
| `appserver/`、后端 core、Session/store、权限、工具、Git | **可写** | **禁止** | 前端发现问题 → 复现 + 协议请求修复，不直接改后端 |
| `protocol/schema.json`、`protocol/*.py` | **唯一 Owner** | 只读消费 | schema 变更必须生成类型并跑 contract test |
| `frontend/protocol-client/` 的**生成类型产物**（由 schema 生成的 TS 类型/`client.ts` 的 generated 区段） | **可写（仅协议变更 PR 内，唯一生成者）** | **只读消费，禁止重新生成提交** | **唯一规则：schema 与生成类型产物均由后端在协议变更中生成并提交**；前端只读消费生成类型，本地 `bun run generate` 验证后**不得提交生成差异**（防止双人并发生成冲突） |
| `frontend/protocol-client/`（其余源码） | 提供 schema/fixture | **可写** | 客户端类型不反向当 schema 真相 |
| `tests/test_protocol`、`tests/test_appserver` 等 Python 测试 | 可写 | 只读观察 | fixture/断言变更必须记录协议版本 |
| Phase 3 ModelCatalog / resolver / summary | 复用 Owner | 禁止复制 | Desktop 只消费摘要 |
| `frontend/desktop-app/` | 提供进程/接口约束 | **可写** | 后端不能直接改 UI 组件 |
| `packaging/` runtime、Python 依赖 | 可写 | 构建入口配合 | runtime/schema 版本必须绑定 |
| **`frontend/opentui-app/`（CLI）** | **禁止** | **禁止（PHASE-G 范围内）** | **见下方注记：本表原本漏列此目录，而 GX28 要改它** |

> ### ⚠️ 追加注记（2026-08-18）：补 `frontend/opentui-app/` 这一行
>
> 本表表头写着「白名单，不可越界」，但原表**没有 `frontend/opentui-app/` 这一行**——而 GX28（`:4207`、`:4235`）要改它。白名单漏列一个正被修改的目录，等于白名单在那个方向上不生效。
>
> **裁定：PHASE-G 范围内该目录一律禁止写入**，CLI 侧改动全部归 [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md)。GX28 涉及 CLI 的部分**拆出去交给 PHASE-N**，GX28 只保留 Desktop 侧。
>
> **为什么不是「加进白名单允许写」**：这个目录现在有**三方要动**——PHASE-K 的 K6 改 `DialogSelect`、PHASE-FIX 改 `stdioTransport.ts`、GX28 改命令注册。三方分属三份文档、无共同 owner、无边界约定，放开写等于约好了在同一个文件上撞车。收敛到 PHASE-N 一个 owner 是目前唯一能定序的办法。
>
> 全文涉及 CLI 仅 3 处：`:366` 是架构图（非规范性，不受此限），另两处即 GX28。详见 [`PHASE-G-CONFLICT-AUDIT.md`](./PHASE-G-CONFLICT-AUDIT.md) X4。

**为什么前端不能碰后端文件**：Thread 生命周期、Child 隔离、权限、模型解析是"真相"，只能有一个生产者。前端自己实现一套 = 双真相 = 迟早不一致。

**交接物定义**（围绕协议的真实产物，不是"只传 schema"）：`protocol/schema.json` 是**唯一协议真相源与长期交接点**；fixture（如 B5 交付的 H5 fixture）、生成类型、运行产物、验收报告都是围绕该协议的交接物，存放于各自模块的 tests/ 目录并在 PR 描述注明版本。

---

## §4 Git 工作流（两人在仓库内建分支 + PR）

### 4.1 分支与合并

```
master（你的 GitHub 仓库，含 Phase 4 壳 + Phase D）
  ├── feat/phase-g-backend    ← 后端开发者
  └── feat/phase-g-frontend   ← 前端开发者
```

1. 各自从 **master** 拉分支：`git checkout -b feat/phase-g-backend origin/master`（后端）/ `git checkout -b feat/phase-g-frontend origin/master`（前端）
2. 每张卡一个 commit → 推分支 → 开 **PR 到 master** → 贴验收命令输出 → 合入
3. **合并节奏：先合小的，后合大的**（大卡承担 rebase 成本）：后端 B5/B8、前端 H9/H13 最后合
4. 合并前先 `git pull --rebase origin/master` 保持分支最新

### 4.2 schema 变更流程（唯一的双人交接仪式）

> 后端要改协议（新增方法/事件/字段）时，**不能直接合**：

1. 填写协议变更单（G-B §1.3 模板）：变更类型限 `new_method` / `new_event` / `new_optional_field`
2. 后端更新 `protocol/schema.json` → **生成类型**（`cd frontend/protocol-client && bun run generate`，**生成产物由后端唯一生成并提交**——生成类型是协议交接物；前端只读消费，本地验证后不提交生成差异）→ 跑 contract test
3. **在前端确认消费方式前，不得合入 master**。在 PR 里 @ 前端："schema 新增 X，消费方式 Y，请确认"
4. 前端确认后合入 → 前端再开工对应卡

> **统一例外条件（主链与 GX 一致）**：所有协议变更（主链卡与 GX 卡）**均须前端确认消费方式后才合入 master**。主链卡的协议变更作为该主链卡 PR 的一部分合入；GX 增强卡的协议变更按增强文档 §1-10 的 `feat/gxN` 分支 + 单 squash commit 模型（后端在分支内先提交协议部分，前端确认消费后补实现，最终一个 GX PR 合入）。**不存在「前端未确认就先行合入」的例外**。

> 若前端对消费方式有异议：后端改协议变更单后重开 PR，**不要**前端直接改 schema（schema 唯一 Owner）。

### 4.3 禁碰清单

- **不要碰 `feat/phase-c-async-core` 分支的在制品文件**（`core/agent_v2.py` 等核心文件——Phase C 正在并行推进，会与 G 分支冲突）
- 不碰 `data/`、`credentials.yaml`、`.env*`（真实密钥，泄密红线）；`~/.rxycode/` 红线精确含义 = 禁止读取/提交/泄露其中真实密钥与用户数据——GX 增强卡向该目录写入运行数据（plans/checkpoints/索引）属正常行为，测试必须走 `RXYCODE_DATA_DIR` 注入目录（增强文档 §1-18）
- 不碰对方白名单内的文件（§3 表）

---

## §5 主链并行排期（26 卡，前后端如何交错）

### 5.1 核心逻辑：后端是主线，前端滞后 1-2 张卡

后端卡只依赖后端卡（B1→B13 串行链）；前端卡每张都依赖"前一张前端卡 + 对应后端卡"：

| 前端卡 | 内部依赖 | 等后端卡 | 前端卡 | 内部依赖 | 等后端卡 |
|---|---|---|---|---|---|
| H1 | 无 | Phase 4 壳+Phase 3 | H8 | H2,H7 | **B7** |
| H2 | H1 | **B2** | H9 | H4,H5,H7,H8 | **B8** |
| H3 | H1,H2 | **B3** | H10 | H4,H5,H9 | **B9** |
| H4 | H2,H3 | **B4** | H11 | H2,H8,H10 | **B10/B11** |
| H5 | H2,H3,H4 | **B5** | H12 | H5,H6,H8,H9,H10 | **B12** |
| H6 | H5 | B5/B6 Item events | H13 | H2,H3,H11,H12 | **B13** |
| H7 | H5,H6 | **B6** | | | |

**开工第一天**：后端做 B1，前端做 H1（互不依赖，同时开工）。

### 5.2 周级节奏示例（后端依赖图 + 前端滞后）

**后端不是单串行链**——按依赖图推进（依据 G-B 卡依赖标注）：

```
B1→B2→B3→B4→B5→B6→B7→B8   （前 8 张串行）
此后按依赖可并行：
  B9（等 B4,B5,B7,B8）│ B10（等 B2,B7,Phase3）│ B12（等 B3,B5,B6,B7）
  B11（等 B2,B7,B10）   ← 与 B9/B12 并行
  B13（等 B2,B3,B7,B10,B12） ← 最后一个收口
```

| 阶段 | 后端在做 | 前端在做 |
|---|---|---|
| 第 1-2 周 | B1 → B2 → B3 | H1（脚手架 + 五态设计）+ H2 预研（等 B2） |
| 第 3-4 周 | B4 → B5 | H3 → H4（等 B3/B4 合入） |
| 第 5-7 周 | B6 → B7 → B8 | H5 → H6/H7 → H8（等 B5/B6/B7） |
| 第 8-10 周 | B9 ‖ B10→B11 ‖ B12（并行） | H9 → H10 → H11（等 B8/B9/B10） |
| 第 11-12 周 | B13（打包/发布门禁） | H12 → H13 |
| 之后 | 主链出口验收 → **追加阶段 28 张增强卡（GX1-GX28：P0-P2 批 GX1-GX18 + P3 · Codex 对齐批 GX19-GX28，含配套 H14-H19/B14-B18 追加卡）** | 同左 |

> 前端**等待期不闲着**：H1 延伸（组件框架、设计 tokens、五态组件库）、预研后端协议示例、写组件测试框架。**允许做"空态/加载态/错误态"占位 UI，但不允许用假数据假装接了真协议**——最终必须接真实 appserver。

### 5.3 卡级依赖权威表

以 `PHASE-G-BACKEND.md`（B1-B13）与 `PHASE-G-FRONTEND.md`（H1-H13）的卡依赖标注为准；本手册的 §5.1 表是速查版，如有出入以原文档为准。**P3 批追加卡（B14-B18/H14-H19/GX19-GX28）不属主链 26 卡**，其依赖标注以各追加卡自身声明与 §8 概览为准。

---

## §6 每张卡的验收纪律（人人必须遵守）

1. **卡内的验收命令必须跑真实命令并贴输出**——不贴输出 = 没做完。**两类验收命令要分清**：①主链卡（B/H）速查表命令**全部摘录自原版 G-B/G-H 对应卡**，不新增、不改写（如发现速查与原文不一致，以原文档为准并报告）；②GX 增强卡的验收命令是 **GX-specific 定向测试**（如 `tests/test_permission_mode`），属新增测试，**不替代**主链对应能力的原版验收——涉及主链能力的 GX 卡（如 GX3 用 B8）仍须保留原版验收作为回归门禁
2. **前置产物缺失 → 输出 `BLOCKED_PREREQUISITE`**，不 mock、不报通过
3. **基线红线（两档）**：
   - 卡级验收：定向测试 + typecheck（全局 agent baseline 不在每张卡跑，避免双人并行时互相覆盖）
   - **批次/阶段出口**：`python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json` 跑一次，记录唯一结果
   - **没有 API key 时**：该批次输出 `PENDING_BASELINE`（如实标注，不标记完成、不豁免）——只有真实 baseline 命令通过后才算出口达标
4. **测试先行**：先写契约/组件测试（红）→ 实现（绿）
5. **UI 五态**：新增组件必须覆盖 空态 / 加载态 / 错误态 / 窄窗口 / 深色主题
6. **单卡单 commit**，Commit 模板见各卡文档

---

## §7 红线清单（违反 = 任务失败）

| # | 红线 | 依据 |
|---|---|---|
| 1 | 缺失前置产物时用 mock / 临时 HTTP 绕过并报告通过 | G-B/G-H 前置条件 |
| 2 | 前端自行决定权限 / 预算 / 模型解析（只消费，不实现） | G-B §0.1 |
| 3 | 在 Desktop 里重写 Agent 核心 / 多 Agent 编排 | G 文档 §11 |
| 4 | 前端反向把 protocol-client 类型当 schema 真相 | G-B §1.2 |
| 5 | 改对方白名单内文件 | 本手册 §3 |
| 6 | 泄露密钥（`data/`、`credentials.yaml`、`.env*`、`~/.rxycode/`） | 主计划 R6 |
| 7 | 为了过 lint/测试修改测试断言或删测试 | 主计划 S4 |
| 8 | 协议删除已有字段 / 改变已有字段语义（必须 new_optional_field + 变更单） | 本手册 §4.2 |

---

## §8 增强阶段（GX1-GX28）概览

主链 26 卡 + 出口标准达成后，进入追加阶段（详见 [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md)）：

- **P0（8 卡）**：任务看板（GX1）、审批卡片+权限三档（GX2）、diff 行内注释+五档 scope（GX3）、Checkpoint 回滚 UI（GX4）、消息排队/打断（GX5）、工具流式卡片+Todo+折叠（GX6）、用量指示器+statusline（GX7）、会话管理四件套+fork（GX8）
- **P1（6 卡）**：Plan 文件持久化（GX9）、运行侧栏浮层（GX10）、只读锁定+筛选（GX11）、Prompt suggestions（GX12）、OS 通知双档（GX13）、模式选择器（GX14）
- **P2（4 卡）**：Design Mode（GX15）、侧聊（GX16）、版本卡（GX17）、Follow-up 推荐（GX18）
- **P3 · Codex 对齐批（9 卡）**：多 Agent 活动可视化（GX19）、会话三分类+折叠（GX20）、回收站 UI（GX21）、i18n 本地化（GX22）、定时任务 UI（GX23）、插件生态（GX24）、CLI 工具+预览画廊（GX25）、设置页重构（GX26）、运行状态视觉（GX27）——立项依据 `research/2026-08-12-agent-native-computer-use-research.md`；前端基建 H14–H19、后端 B14–B18（追加卡，非主链）

**增强阶段的纪律与主链相同**（只添加不修改、协议变更单、BLOCKED_PREREQUISITE、基线红线、五态）。**P3 批新增纪律**：跨平台三端适配（Windows/Linux/macOS，见 P3 批头说明）；hover/圆角等 Codex 视觉取样以实机对照为准。

---

## §9 出口标准（三个状态，分别达标）

**状态一 · Phase G 主链出口**（完整 G 文档 §10 为准）：
1. 主链 26 卡（B1-B13 + H1-H13）全部合入，G 文档 §10 六项出口达标
2. 全量回归 `python -m pytest tests -q --timeout=600` 与改动前同量级通过
3. 真实基线命令通过（无 key 时 `PENDING_BASELINE` 不算达标）
4. 三平台打包（Windows/macOS/Linux）可启动真实握手

**状态二 · GX P0 首版出口**：主链出口达标后，GX1-GX8（P0 批）按增强文档 §2 的 6 项完成——这是增强阶段的最低交付承诺。

**状态三 · GX 全量增强出口**：GX1-GX28（P0+P1+P2+P3）全部按增强文档 §2 的 6 项完成。

**状态四 · P3 · Codex 对齐批出口**（追加定义）：主链出口 + P0/P1/P2 出口达标后：
1. GX19–GX28 全部合入（P0 优先项：GX20/GX26/GX27；P1：GX19/GX21/GX25；P2：GX23/GX24；**GX28 等 PHASE-F F18 合入后执行**，依赖 GX26 团队分区 + GX19），配套前端基建 H14–H19、后端 B14–B18 合入；
2. P3 批验收含：i18n 全量文案覆盖（zh-CN + en）、三分类/回收站/设置重构/状态视觉五态、CLI 工具分组与画廊零 PHASE-I 依赖、多 Agent 预留零 mock 路径；
3. **macOS/Linux 构建目标 smoke 通过**（locale 入包 + 启动握手 + 语言切换）；
4. 批次全局 baseline 执行一次（无 key → `PENDING_BASELINE` 不标记完成）。

---

## §10 常见问题

**Q：前端等后端卡的时候能不能先用假数据做界面？**
A：可以做"空态/加载态/错误态"占位和组件骨架，但**不允许用 mock 假装接了真协议**（红线 1）。真实交互必须等对应后端卡合入后接真 appserver。

**Q：我和对方同时改了一处怎么办？**
A：schema 是唯一交接点（后端写、前端读）；其他文件有白名单（§3）物理隔离。真冲突了：先合小的后合大的（§4.1），后合的人承担 rebase。

**Q：Phase C 分支和我们的分支会不会撞？**
A：Phase C 在 `core/agent_v2.py` 等核心文件（禁碰清单 §4.3）。你们的文件在 `appserver/`、`frontend/desktop-app/`、`protocol/`，白名单已隔离。C 分支合入 master 时若与你们的提交冲突，以"先合小后合大"解决。

**Q：验收命令里的 evals 基线跑不动（没有 API key）？**
A：全局 agent baseline 只在**批次/阶段出口**跑一次（不是每张卡）。没有 key 时：该批次输出 `PENDING_BASELINE`（在 PR 如实注明），**不得标记为完成**；等有 key 的环境跑真实基线通过后，该批次才算出口达标。`dry-run` 不能代替真实基线。


---

# Part · 3 · GUI 增强卡（GX1–GX28 追加阶段，含 P3 · Codex 对齐批）

> **本部分来源**：原 `PHASE-G-GUI-ENHANCEMENT.md`（合并时正文一字未改，仅链接映射到新文件名；P3 批 GX19–GX28 为 2026-08-12 追加）
# Phase G 增强 · GUI 基准增强任务卡（GX1–GX28）

> **文档定位**：本文件是 [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md) 及其前后端拆分文档（[`PHASE-G-BACKEND.md`](./PHASE-G-BACKEND.md)、[`PHASE-G-FRONTEND.md`](./PHASE-G-FRONTEND.md)）的**追加增强附录**。立项依据是 [`research/2026-08-10-gui-agent-benchmark.md`](./research/2026-08-10-gui-agent-benchmark.md)（10 款 GUI agent 基准调研，Codex 重点）。
>
> **不修改原则（硬约束）**：本附录**只添加、不修改**。Phase G 主链执行卡 = PhaseG-B1–B13（后端 13 张）+ PhaseG-H1–H13（前端 13 张）= **26 张**，它们是对完整 G 文档 G1–G16 的前后端拆分实施（拆分关系见 G-B/G-H 头部与附录 A）。这 26 张主链执行卡的编号、依赖、验收命令、完成判据一律不动；本附录的全部增强以 **GX1–GX28** 追加任务卡形式存在（P0–P2 批 GX1–GX18 原版 + **P3 · Codex 对齐批 GX19–GX28 追加**，配套前端基建 H14–H19 与后端 B14–B18 追加卡，立项依据 `research/2026-08-12-agent-native-computer-use-research.md`），作为 **Phase G 主链出口（26 卡合入 + G 文档 §10 达标）之后的追加阶段**执行。
>
> **执行顺序**：主链 26 卡全部合入且 G 文档 §10 出口标准达标后进入追加阶段。**追加阶段按依赖图执行，同一批次内可并行（GX 卡是"任务卡"不是"串行编号"）**；并行可行性见 §3 排期。
>
> **创建**：2026-08-10（P3 批追加：2026-08-12）　**任务卡**：GX1–GX28（P0×8 + P1×6 + P2×4 + P3×10）　**owner**：backend（后端执行者）/ frontend（前端执行者）分别对应

---

## §0 增强卡总览

| 卡 | 功能 | 借鉴来源（调研 §） | 优先级 | 前后端 | 依赖 |
|---|---|---|---|---|---|
| GX1 | 任务看板视图（Drafts/Active/Ready/Done） | Replit §10.3-1/2/4 | P0 | 前端 | H1–H13 完成 |
| GX2 | 审批卡片内嵌对话流 + 权限三档模式 | TRAE §8.3-3/4 + Codex §2.3-1 | P0 | 前端+后端 | B7 + H8 完成 |
| GX3 | diff 行内注释闭环 + Review scope 五档 | Codex §2.3-5/6 | P0 | 前端+后端 | B8 + H9 完成 |
| GX4 | Checkpoint 回滚 UI（revert 挂消息/命名快照） | Devin Desktop §6.3-4 + Replit §10.3-7 | P0 | 前端+后端 | B8 + H9 完成 |
| GX5 | 消息排队/打断（Send 三态） | Copilot §4.3-1 + Cursor §5.3-9 | P0 | 前端（可拆 GX5-B） | H5 + B5（turn steering 核对）完成 |
| GX6 | 工具调用流式卡片 + Todo 步骤时间线 + 节点折叠 | Cursor §5.3-3/10 + Qoder §9.3-3 | P0 | 前端 | H6/H7 完成 |
| GX7 | 上下文用量/成本指示器 + statusline | Codex §2.3-14/15 + Claude §3.3-12 | P0 | 前端+后端 | B10 + H11 完成 |
| GX8 | 会话管理四件套 + 消息级 fork | Codex §2.3-9/10 | P0 | 前端+后端 | B5 + H5 完成 |
| GX9 | Plan 文件持久化 + Implement 按钮 | Devin Desktop §6.3-2 | P1 | 前端+后端 | GX8 完成 |
| GX10 | 聊天侧栏浮层（plan/sources/files/summary） | Codex §2.3-12 | P1 | 前端 | H5 + GX7 完成 |
| GX11 | 运行中会话只读锁定 + 侧栏筛选分组 | Devin Desktop §6.3-11 + Claude §3.3-14 | P1 | 前端 | H5 完成 |
| GX12 | Prompt suggestions（灰色示例输入） | Claude §3.4 | P1 | 前端 | H5 完成 |
| GX13 | OS 通知双档（回复到达/需要确认） | Copilot §4.3-13 | P1 | 前端+后端 | B12 + H12 完成 |
| GX14 | 模式选择器（Ask/Edit/Agent） | Qoder §9.3-1 | P1 | 前端+后端 | H5 + B5 完成（capability 后端校验）；3-4d 单人/1.5-2d 双人并行（含协议/生成类型/契约测试/联调） |
| GX15 | Design Mode 元素选择（预览标注） | v0 §11.3-4/5 | P2 | 前端 | GX17 + 主链图片附件协议存在 |
| GX16 | 侧聊 /side | Codex §2.3-11 + Claude §3.3 | P2 | 前端+后端 | GX8 完成 |
| GX17 | 版本卡（每次变更=新版本，diff/回退） | v0 §11.3-2 | P2 | 前端 | B8 + H9 完成 |
| GX18 | Follow-up 任务推荐 | Replit §10.3-11 | P2 | 前端+后端 | GX1 完成 |
| GX19 | 多 Agent 活动可视化（委派树/成员状态/预算条） | 2026-08-12 报告 §6.8 + 2026-08-11 报告 C5 | P3 | 前端+后端 | F12 + E4 + H18（未合入 → BLOCKED） |
| GX20 | 会话三分类 + 折叠交互（置顶/项目/最近） | 2026-08-12 报告 §6.1–6.2 | P3 | 前端+后端 | B5 + H15 + GX8 |
| GX21 | 回收站 UI（恢复 + 清空弹窗） | 2026-08-12 报告 §6.4-1 | P3 | 前端 | B17 + H15 |
| GX22 | i18n 语言本地化（zh-CN + en） | 2026-08-12 报告 §6.5 | P3 | 前端 | H14 |
| GX23 | 定时任务 UI | 2026-08-12 报告 §6.7 | P3 | 前端+后端 | B16 |
| GX24 | 插件生态（市场 + 管理） | 2026-08-12 报告 §6.6 | P3 | 前端+后端 | B18 |
| GX25 | CLI-Anything 工具接入 + 预览画廊 | 2026-08-12 报告 §3.4/§5 | P3 | 前端+后端 | B14 + H19 |
| GX26 | 设置页重构（8 分区） | 2026-08-12 报告 §6.4 | P3 | 前端+后端 | H16 + B10 + D5 |
  | GX27 | 运行状态视觉（转圈/蓝点/通知/高亮） | 2026-08-12 报告 §6.3 | P3 | 前端 | H17 + GX13 |
  | GX28 | Team Manager（专家团管理与选择） | 2026-08-11 报告 §9.3/C8 + F18 | P3 | 前端+后端 | F18 + GX19 + GX26 |

**P0 批（GX1–GX8）**：首版增强，用户感知最强的 8 项；**P1 批（GX9–GX14）**：第二版；**P2 批（GX15–GX18）**：储备能力；**P3 批（GX19–GX28 · Codex 对齐批）**：GUI 对齐 Codex 交互 + 多 Agent 可视化 + Agent-Native 软件控制（CLI-Anything 混合集成）——前端基建 H14–H19、后端 B14–B18 配套（追加卡，非主链），跨平台三端适配为批内通用约束。
**执行方式**：按依赖图执行；同一批次内可并行（GX 卡是"任务卡"不是"串行编号"），并行可行性见 §3。涉及协议扩展的卡必须走 §1-10 的 GX 跨端流程模板。

---

## §1 通用规范限制（所有 GX 卡必须遵守）

> **环境前提**：所有命令从仓库根目录（`D:\agent-demo\RxyCode\RxyCode1_1_0`）执行；Windows / PowerShell；后端 Python 3.11/3.12（`python`）+ ruff；前端 Node + bun（`cd frontend\desktop-app` 内执行 npm/bun 命令）；协议类型生成 `cd frontend\protocol-client && bun run generate`。

1. **只允许新增**：每张卡只能新增 `frontend/desktop-app/src/features/<name>/`、`tests/` 对应测试文件，以及协议/后端扩展文件；**禁止修改主链 26 张卡涉及文件的既有语义**（bug 修复除外，需在 Commit 里注明）。
2. **协议变更纪律**：任何新增协议方法/事件/字段，必须走 [`PHASE-G-BACKEND.md`](./PHASE-G-BACKEND.md) §1.3 的**协议变更单**（change_kind 限 `new_method` / `new_event` / `new_optional_field`），不得改变已有字段语义，不得删除已有字段。
3. **BLOCKED_PREREQUISITE 纪律**：卡级前置（见 §0 依赖列）未合入时，只能输出带缺失清单的 `BLOCKED_PREREQUISITE`，**不得用 mock/临时 HTTP 绕过**。
4. **文件边界**：遵守 G-B §1.2 ownership 白名单——`protocol/`、`appserver/` 后端唯一 Owner；`frontend/desktop-app/` 前端可写；schema 变更必须生成类型并跑 contract test。
5. **验收命令必须跑真实命令贴输出**。**基线规则（统一口径）**：GX 卡级验收只跑定向测试 + typecheck；全局 agent baseline（`python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json`）按 **P0/P1/P2 批次出口**各执行一次（§2），由验收执行者记录唯一结果；无 API key 时批次输出 `PENDING_BASELINE` 不标记完成。卡级完成判据 = 定向测试通过 + 纳入批次 baseline，**不要求每张卡单独跑全局 baseline**（主链卡仍遵守原版逐卡基线规则，本规则仅适用于 GX 卡）。
6. **单卡单 commit**；Commit 信息模板见各卡。
7. **测试先行**：每张卡先写契约/组件测试（red），再实现（green）。
8. **新增 UI 组件必须同时覆盖**：空态 / 加载态 / 错误态 / 窄窗口 / 深色主题 五态（视觉验收最低标准）。
9. **状态色语义**（新增组件统一使用）：Active=蓝、Ready=绿、Draft=灰、Applying=紫、Done=绿点、Error=红、**Timeout=橙**（GX6 工具卡片 timeout 态使用；橙=可恢复的时限超时，红=不可恢复错误）；各色 token 在增强阶段视觉系统（GX12 同期）定义并满足 WCAG AA 对比度，禁止各卡自行定义色值
10. **GX 跨端流程模板**（任何涉及协议扩展的 GX 卡，前后端顺序冻结）：`主链出口通过 → 后端协议变更单（G-B §1.3）→ 后端产出 schema + 生成类型 + contract test → 前端确认消费方式 → 后端合入 → 前端消费实现 → 双端验收 → GX 单卡 PR`。协议变更单是 GX 卡的后端前置，缺失时输出 `BLOCKED_PREREQUISITE`。
    **提交粒度（统一口径，遵守原版「单卡单 commit」，跨端卡协作细节）**：每张跨端 GX 卡 = **一个临时分支 `feat/gxN`**，具体流程：
1. `feat/gxN` 从**最新 master** 创建（`git checkout -b feat/gxN origin/master`），由后端开发者创建并推送
2. 后端开发者提交协议部分（schema/生成类型/契约测试）到 `feat/gxN` 并推送——schema 在分支内即可供前端消费，前端不需要等 master
3. 前端开发者从该分支拉取（`git fetch origin feat/gxN && git checkout feat/gxN`），提交消费实现（本地可运行 generate 验证，不提交生成差异）
4. 两人**共同维护一个 PR**（`feat/gxN → master`）；review 顺序：协议部分后端自审 → 前端确认消费方式 → 双端验收
5. 最终**只允许该一个 PR squash 为单一 `GXn` commit 合入 master**；后端/前端的个人分支（`feat/phase-g-backend` / `feat/phase-g-frontend`）**不得另开同卡 PR**；feat/gxN 合入后删除
6. 冲突处理：与 master 冲突时先 rebase `feat/gxN` 到最新 master（先合小的后合大的）；中间 commit 不属于 master 历史。同一卡的所有 commit 引用同一协议变更单 ID；前端确认消费方式之前卡状态为 `BLOCKED_PREREQUISITE`；**禁止**把多张卡的协议变更混进一个 commit。
11. **允许修改的注册点/胶水文件**（"只添加"不适用于这些既有入口，但改动仅限最小接线，不改变既有语义）：`frontend/desktop-app/src/app/views/`（视图注册）、`frontend/desktop-app/src/app/router.ts`（路由）、`frontend/desktop-app/src/features/composer/` 的入口索引（如 `index.ts`）、设置页路由注册。
    **GX 接线专用清单**（各 GX 卡允许的最小接线修改，每次修改必须 diff 最小化并在 PR 说明接线范围）：H5 会话列表的 context menu 注册点（GX8）、H9 diff 视图的评论挂载点（GX3）、消息流组件的 revert 按钮挂载点（GX4）、B7 审批事件流的双通道投递挂接（GX2，appserver 侧为新增 `approval_router.py` 消费，不改 B7 事件生产者）。除此之外的既有文件禁止修改。
12. **基线执行规则**：卡级验收只跑定向测试 + typecheck；全局 agent baseline（`python -m evals.cli run --backend agent --compare-baseline ...`）按**批次/阶段出口**执行一次，由验收执行者记录唯一结果，避免双人并行时互相覆盖。没有 API key 时输出 `PENDING_BASELINE`（不标记完成），不豁免。
13. **借鉴来源等级纪律**：GX 卡引用调研的借鉴来源，凡涉及协议 / 权限 / 安全 / 回滚语义的设计依据，只允许来自 `official verified` 级来源（见调研 §1 来源分级）；`secondary evaluation` 仅作佐证；`inference` 级（设计哲学/视觉推断）只作风格参考，**不得写入"语义冻结"或安全要求**。每张 GX 卡的来源在 §14 映射表可追溯。
14. **工时口径**：跨端 GX 卡（含后端协议）的工时**包含**协议变更单、schema/类型生成、contract test、双端联调与验收等待；P0 批按两人并行排期（§3），协议扩展卡串行点即"前端确认消费方式"的等待。单人执行时按工时的 1.5 倍估算。
18. **运行时数据目录规则**：生产使用 `~/.rxycode/`（与主链一致）；**测试使用注入的临时目录（`RXYCODE_DATA_DIR` 环境变量）**，禁止测试污染真实用户目录；`~/.rxycode/` 内的运行数据**不纳入 git 变更**；红线「禁止触碰 `~/.rxycode/`」精确含义 = 禁止读取/提交/泄露其中真实密钥与用户数据（主链 R6），**不等于禁止 GX 功能向该目录写入运行数据**。GX4/GX8/GX9 验收必须包含：路径隔离（测试不写真实目录）、无真实用户目录污染、敏感字段脱敏断言。
16b. **候选名机制**：各 GX 卡冻结的协议方法/事件名（如 `approval/mode_set`、`review/comment/add`）是**设计候选名**——探针确认与既有 schema 方法不重名后沿用；若冲突，以探针结论调整候选名并记录于协议变更单。探针完成前方法名不作为「已冻结事实」用于验收；**各卡验收命令中引用候选名的测试，在对应协议探针 PASS 前不得运行**；探针调整候选名时须同步更新该卡全部引用（涉及文件/示例/判据/Commit）。
17. **探针判定模板（所有协议 GX 卡统一，A/B 路径）**：探针完成后按路径执行——
```text
路径 A（能力已存在）：列出真实方法/事件/字段 + 原版验收命令 → 卡按纯消费/投影完成
路径 B（能力不存在）：新增 GX*-PROTO 子卡（依赖图/owner/协议变更单/后端测试/验收命令补齐）→ 主卡依赖该子卡
```
主卡完成判据统一写「按探针路径 A 或 B 达标」；禁止同时保留两套必选结论。
15. **复用点标注规范**：凡 GX 卡声称"复用主链 X 的能力"，必须标注 `原版卡号 + 协议方法/事件名 + 字段路径 + 原版验收命令所在卡`（如"复用 B8 checkpoint restore：`checkpoint/restore`，字段 `diff_hash`，验收见 G-B B8 卡"）。标注缺失的复用点视为未核准，实现前必须先回原版文档核对补齐。
16. **协议探针（所有新增协议方法的跨端卡，开工前置产物，固定字段模板）**：
```text
Protocol probe: PASS/BLOCKED
Existing methods/events checked: <schema 完整方法/事件清单核对结果>
Namespace result: <归属原版命名空间 或 新命名空间显式声明>
Change request ID: <协议变更单 ID>
Reused original card/method/field/acceptance: <原版卡号+方法+字段+验收>
```
**命名空间注册规则**：新增协议方法**优先归入原版命名空间**——方法名风格为**斜杠分隔**（与既有 `agent/invoke`、`task/start` 一致），前缀即命名空间：`approval/*`（如 `approval/mode_set`）、`review/*`、`checkpoint/*`、`event/agent_*`；确需新命名空间（如 `plan/*`、`thread/*`）必须在协议变更单中**显式声明 namespace 注册**（含与既有方法同名检查结论，全部既有方法/事件清单附在探针中）。探针未完成（PASS）前卡状态为 `BLOCKED_PREREQUISITE`。

---

# P0 批（GX1–GX8）

## GX1 · 任务看板视图（Drafts → Active → Ready → Done）

**借鉴来源**：Replit 任务看板（调研 §10.3-1/2/4，official verified）；Devin Desktop Agent Command Center（§6.3-11，official verified）。
**优先级/工时**：P0 / 4–5d（含状态枚举核对与接线，单人） / 依赖：Phase G 主链 H1–H13 完成 / **owner: frontend（Composer 2.5）**
**背景**：主链的 Thread 列表是平面列表，用户无法一眼看到"哪些任务在跑、哪些待审查、哪些完成"。Replit 证明四列看板（Drafts→Active→Ready→Done）是最有效的任务状态可视化：**Ready = 待审批 = 我们审批+diff review 的天然入口**。

**涉及文件**（新增 feature 文件；`src/app/views/` 仅允许最小接线，见 §1-11）：
- `frontend/desktop-app/src/features/board/BoardView.tsx`（看板主组件）
- `frontend/desktop-app/src/features/board/BoardColumn.tsx`、`TaskCard.tsx`
- `frontend/desktop-app/src/features/board/board.selectors.ts`（Thread→看板列投影）
- `frontend/desktop-app/src/features/board/BoardView.test.tsx`（组件测试）
- `frontend/desktop-app/src/app/views/`（视图注册，新增看板入口）

**规范限制**：
- 只读投影：看板**不新建状态模型**，列状态由 Thread 真实状态派生（drafting / running / awaiting_review / done）；不修改主链 Thread 协议
- 任务卡点击 → 打开对应 Thread（复用主链 H5 会话中心），不复制会话逻辑
- 列定义冻结：Drafts / Active / Ready / Done 四列，不得自定义增列（后续增强再议）
- **未知/失败状态归属冻结**：Thread 状态枚举中凡未列入四列映射的状态（如 `failed` / `cancelled` / `blocked` 等，以主链 H5 状态枚举为准）一律归入 Active 列并显示 Error 徽标——**禁止静默丢弃卡片**；映射表必须覆盖全部枚举值（测试断言：枚举值到列的映射是全函数）
- 拖拽移动卡片仅允许 Drafts↔Active 之间（Ready/Done 由系统状态决定，不允许手动拖）
- 状态色遵循 §1-9

**开发步骤**：
1. 写 `BoardView.test.tsx`（red）：四列渲染、状态投影映射（running→Active 等 4 条映射）、空态/加载态、卡片点击跳转
2. `board.selectors.ts` 实现 Thread→列投影（复用主链 store 的 session 状态）
3. 实现 `TaskCard`（标题/状态徽标/时间/三态点菜单：Open、Rename、Cancel）+ `BoardColumn`（列头计数 + 空态文案）
4. 实现 `BoardView` 聚合，注册视图入口（侧栏图标 + Cmd+K 命令）
5. 五态视觉验收：空态（无 Thread）/ 加载态（骨架）/ 错误态（store 断连）/ 窄窗口（列横向滚动）/ 深色主题

**示例代码**（投影选择器核心）：

```ts
// board.selectors.ts —— 状态投影：不新建状态模型，从 Thread 派生
import { createSelector } from '@reduxjs/toolkit';
import type { ThreadStatus } from '../threads/types';

export type BoardColumnId = 'drafts' | 'active' | 'ready' | 'done';

// 投影规则冻结：四列状态映射（§1-9 状态色语义）
// 示例枚举：实现时以主链 H5 的实际 ThreadStatus 枚举为准补全（H5 未确认的状态不得写死）
// 运行时字符串校验 + 显式 fallback（不依赖 Record 编译期完整性，服务端未知值安全降级）
const STATUS_TO_COLUMN: Record<string, BoardColumnId> = {
  drafting: 'drafts',
  running: 'active',
  awaiting_review: 'ready',   // Ready = 待审批
  done: 'done',
  // 失败/取消/阻塞：不静默丢弃，归 active 列并带 Error 徽标
  failed: 'active',
  cancelled: 'active',
  blocked: 'active',
};

export function mapStatusToColumn(status: string): BoardColumnId {
  return STATUS_TO_COLUMN[status] ?? 'active';  // 未知字符串（含未来新增）一律落 active
}

export const selectBoardColumns = createSelector(
  (s: RootState) => s.threads.items,
  (items) => {
    const columns: Record<BoardColumnId, ThreadCard[]> = {
      drafts: [], active: [], ready: [], done: [],
    };
    for (const t of Object.values(items)) {
      columns[mapStatusToColumn(t.status)].push({
        id: t.id, title: t.title, updatedAt: t.updatedAt,
      });
    }
    return columns;
  },
);
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck
npm run test -- --run
# 契约：四列投影 4 条映射断言 + 拖拽仅限 Drafts↔Active + 五态组件测试全过
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 四列看板正确投影（4 条状态映射断言通过）
- [ ] Ready 列卡片带"审查"入口（打开主链 diff review）
- [ ] 拖拽仅限 Drafts↔Active；Ready/Done 不可手动拖
- [ ] 空/加载/错误/窄窗/深色五态测试通过
- [ ] 协议零变更（本卡纯前端投影）
- [ ] 单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): add GX1 task board view (Drafts/Active/Ready/Done)

Replit-style four-column board projecting Thread status. Read-only
projection; Ready column is the diff-review entry point. No protocol change.
```

---

## GX2 · 审批卡片内嵌对话流 + 权限三档模式

**借鉴来源**：TRAE 审批卡片（调研 §8.3-3/4）；Codex 权限三档模式（§2.3-1）；Qoder 命令审批（§9.3-4）。
**优先级/工时**：P0 / 3–4d / 依赖：B7 + H8 完成 / **owner: frontend 为主 + backend 协议扩展**
**背景**：主链 H8 的审批是模态弹窗（模态打断流）。Codex/TRAE/Qoder 三家共同证明：**审批=模式而非弹窗**——权限请求以卡片内嵌对话流（不断流），配合 Composer 下方常驻的三档权限模式切换（Ask / Auto-review / Full access）。

**涉及文件**：
- `frontend/desktop-app/src/features/approvals/ApprovalCard.tsx`（新增，流内审批卡片）
- `frontend/desktop-app/src/features/approvals/PermissionModeSwitcher.tsx`（新增，输入框旁三档切换）
- `frontend/desktop-app/src/features/approvals/approval.mode.ts`（新增：模式状态管理）
- `frontend/desktop-app/src/features/approvals/ApprovalCard.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`approval/mode_set` 方法，new_method）
- `appserver/handlers/permission.py`（新增：权限模式会话状态 + approval request 路由：卡片/弹窗互斥 + request_id 幂等）
- `appserver/approval_router.py`（新增：审批事件的通道路由与幂等处理——事件名以 B7/B12 实际为准，消费主链 B7 审批服务事件）
- `tests/test_permission_mode.py`、`tests/test_approval_router.py`（新增）

**规范限制**：
- **权限模型（单一规范，不新建平行状态）**：权限策略**沿用主链 B7 的五态模型**（`read_only` / `workspace_write` / `ask_for_each_risky_action` / `allow_scoped_actions` / `full_access`，`full_access` 默认不可选，重启只恢复明确持久化策略）。GX2 的三档是 **UI 预设**，映射到 B7 五态：`Ask`→`ask_for_each_risky_action`（默认）、`Auto`→`allow_scoped_actions`（LLM 代审语义，若 B7 无等价策略则映射回 `ask_for_each_risky_action` 并注明）、`Full`→`full_access`（沿用 B7 显式启用与默认不可选语义）；**不得新增第三套权限状态**。`approval/mode_set` 只写「UI 预设名 + 目标 B7 策略名」，实际生效策略始终来自 B7 服务
- 模式是**会话级**状态（存 appserver，非前端 localStorage）；切换走 `approval/mode_set` 协议
- **full_access 启用（探针决定，闭环要求）**：开工前先核对主链 B7 是否已有 `full_access` 启用方法/字段——**核对结论二选一**：①B7 已有 → 只复用（写出真实方法/字段/验收命令，UI 入口 + 设置页接线）；②B7 没有 → 拆 **GX2-PROTO** 子卡：`approval/full_access_enable` 的 request/response、权限主体（仅设置页已认证会话）、审计字段（actor/时间/来源）、启用生命周期（会话级，重启清除）、调用权限与失败错误码、验收命令全部冻结在协议变更单。`approval/mode_set` 对 `full` 的「未启用」错误码固定为 `full_access_not_enabled`。核对前不得同时写两种方案；结论写入 PR
- **审批幂等（防重复审批/竞态）**：审批事件名**以主链 B7/B12 实际事件为准**（事件命名空间 `event/agent_*`；探针确认后替换占位名 `approval/requested`）；事件带 `request_id`；卡片与模态弹窗**互斥展示**（同一 `request_id` 只在一个通道呈现，路由规则：模式=ask 且风险非高危 → 卡片；高危 → 弹窗）；响应（allow/deny/cancel）以 `request_id` 幂等，重复响应返回 `request_id already handled` 错误；两侧同时打开时状态同步由 appserver 单事件源保证
- 审批卡片**不替代**主链的模态弹窗——弹窗保留为"紧急/高危"动作路径（B7 的 `full_access` 默认不可选逻辑不变）；卡片是新增的低干扰路径
- 卡片动作只发 `allow` / `deny` / `cancel`，不修改后端 policy（与主链 H8 一致）
- 高危命令（rm/删除/写 .env 等，复用主链 B7 风险分级）无论模式如何都走弹窗

**开发步骤**：
1. 后端先行（协议）：`tests/test_permission_mode.py`（red）→ `protocol/` 新增 `approval/mode_set`（**请求/响应结构全文档唯一冻结**：request `{preset: "ask"|"auto"|"full"}`；response `{preset, effective_policy, writable_roots}`；不出现 `{mode}` 变体）→ `appserver/handlers/permission.py` 会话级预设状态（默认 `ask`，重启恢复 `ask`——不持久化高风险预设）
2. 前端：`ApprovalCard.test.tsx`（red）→ 组件（命令/路径/风险徽标/允许/拒绝/取消 + 后台运行标记，五态覆盖）
3. `PermissionModeSwitcher`（输入框旁下拉 + 当前模式徽标，参照 Claude 模式徽章体系 §3.4）
4. 接线：主链事件流（B7 approval 事件）同时投递到卡片渲染器和弹窗渲染器，按模式路由

**示例代码**（后端模式状态 + 协议 handler）：

```python
# appserver/handlers/permission.py —— UI 预设 → B7 策略映射（GX2 新增，不新建权限状态）
from typing import Literal

# UI 预设三档（§规范限制）——映射到主链 B7 五态策略，实际生效策略来自 B7 服务
UIPreset = Literal["ask", "auto", "full"]
# 预设 → B7 策略映射冻结；full 需 B7 显式启用（默认不可选，沿用 B7 语义）
PRESET_TO_B7: dict[UIPreset, str] = {
    "ask": "ask_for_each_risky_action",   # 默认
    "auto": "allow_scoped_actions",       # 若 B7 无等价策略则映射回 ask_for_each_risky_action
    "full": "full_access",                # 显式启用后才可选
}

# approval/mode_set request: {preset: UIPreset}
# response: {"preset": ..., "effective_policy": <B7 策略名>, "writable_roots": [...]}
# 校验：full 未启用（B7 默认不可选）时拒绝，错误码走主链审批审计
```

**验收命令**：
```powershell
python -m pytest tests/test_permission_mode tests/test_approval_router -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：模式切换往返、重启回默认 ask、full_access 启用后可选/未启用拒绝/重启清除、
#       审批卡片五态、request_id 幂等（重复响应报错）、卡片/弹窗互斥路由、事件名探针结论
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `approval/mode_set` 协议落地（含 schema 冻结 + contract test）
- [ ] 三档切换生效；full_access 未启用时拒绝、启用后可选、重启后清除
- [ ] 审批卡片在对话流内渲染（非模态），动作只发 allow/deny/cancel
- [ ] request_id 幂等（重复响应返回已处理错误）；卡片/弹窗互斥路由正确
- [ ] 高危动作仍走主链模态弹窗（双路径并存）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX2 inline approval cards + permission presets

TRAE/Codex-inspired inline approval cards in the thread stream and
UI presets (ask/auto/full) mapped onto the B7 policy model via new
approval/mode_set protocol method. Modal path retained for high-risk.
```

---

## GX3 · diff 行内注释闭环 + Review scope 五档

**借鉴来源**：Codex diff 行内注释闭环与五档 scope（调研 §2.3-5/6）；Claude 行注释批量提交（§3.3-7）；Copilot Range-based Feedback（§4.3-9）。
**优先级/工时**：P0 / 3–4d / 依赖：B8 + H9 完成 / **owner: frontend 为主 + backend 协议扩展**
**强 Protocol probe（§1-16 固定字段）**：实现前必须确认 B8 checkpoint restore 的真实方法名与字段（`name`/`user_prompt`/`seq`/对话截断相关字段是否存在于 B8 schema）——确认前整卡状态 `BLOCKED_PREREQUISITE`；示例中的 `CheckpointService.*`/`ThreadService.truncate_projection_at` 为占位 API，以探针结论替换；缺失能力拆协议卡（如 `GX4-PROTO`）
**背景**：主链 H9 的 diff review 只能看和接受/拒绝，无法"以行为单位反馈"。Codex 的闭环是各家最强：悬停行尾→写评论→回聊天下达→agent 修复→resolve。五档 scope（Unstaged/Staged/Commit/Branch/Last turn）让"审什么"由用户定义，Last turn 完美映射我们的 Thread 回合模型。

**涉及文件**：
- `frontend/desktop-app/src/features/review/InlineComment.tsx`（新增：行内评论气泡）
- `frontend/desktop-app/src/features/review/ReviewScopeSelector.tsx`（新增：五档下拉）
- `frontend/desktop-app/src/features/review/review.comments.ts`（新增：评论状态 store）
- `frontend/desktop-app/src/features/review/InlineComment.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`review/comment/add`、`review/comment/resolve`，new_method）
- `appserver/handlers/review_comments.py`（新增：评论持久化到 review 记录）
- `tests/test_review_comments.py`（新增）

**规范限制**：
- 五档 scope 冻结：`unstaged` / `staged` / `commit` / `branch` / `last_turn`（last_turn = 最近一个 agent 回合的变更）
- **scope 与主链 B8 的对照纪律**：实现前先逐项核对主链 B8 的 `review/start` paths scope 实际支持项——已存在的直接复用；不存在的（如 `last_turn` 的 turn↔diff 关联）**必须走协议变更单**：若缺的是关联字段 → new_optional_field；若缺的是 scope 枚举值/查询语义 → 冻结新增 scope 值的枚举定义、排序规则、空 diff 行为与验收样例（new 枚举值变更，不能只加字段了事）。对照结论写进 PR 描述，未核对前卡状态 `BLOCKED_PREREQUISITE`
- 评论**只读消费** B8 的 diff hash 定位（`file:line` 锚点 + hunk hash），评论本身不进入 git，持久化在 appserver review 记录
- **评论状态机冻结**：`open` → `resolved`（人工 resolve）；hunk 因后续 diff 失效时 `open` → `stale`；`stale` 可 resolve（标记已确认），不可 reopen；`stale` 不删除
- 回聊天下达：评论提交后生成一条**可编辑的**用户消息草稿（"请处理以下内联评论：…"），用户确认后发送——不自动发送
- 后端复用 B8 的 review/read 语义；`review/comment/*` 为 B8 协议的追加方法，不改 B8 字段

**开发步骤**：
1. 后端先行：`tests/test_review_comments.py`（red）→ `protocol/` 新增 `review/comment/add`（request: `{review_id, file, line, hunk_hash, body}`）、`review/comment/resolve`（`{comment_id}`）→ `appserver/handlers/review_comments.py`
2. 前端：`InlineComment.test.tsx`（red）→ hover 行尾按钮（+）→ 评论气泡（textarea + 提交/取消 + 折叠）→ 评论列表（open/stale 徽标 + resolve 按钮）
3. `ReviewScopeSelector`：五档下拉，默认 `last_turn`；切换后 diff 面板按 scope 重投影（复用 B8 review/start 的 paths scope）
4. 下达闭环：评论提交 → 生成消息草稿 → 用户发送 → agent 修复（新 diff）→ 原评论 hunk 失效标记 stale → resolve 入口

**示例代码**（评论组件核心交互）：

```tsx
// InlineComment.tsx —— 行内评论（GX3 核心交互：hover → 评论 → resolve）
export function InlineComment({ file, line, hunkHash }: CommentAnchorProps) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState('');
  const comments = useCommentsForAnchor(file, line, hunkHash); // 只读消费 B8 diff hash

  return (
    <div className="inline-comment" data-line={line}>
      <button className="anchor-btn" onClick={() => setOpen(true)} title="Add comment">+</button>
      {comments.map((c) => (
        <div key={c.id} className={`comment ${c.status}`}>
          <p>{c.body}</p>
          {c.status === 'stale' && <span className="badge">stale</span>}
          {c.status === 'open' && (
            <button onClick={() => dispatch(resolveComment(c.id))}>Resolve</button>
          )}
        </div>
      ))}
      {open && (
        <div className="comment-editor">
          <textarea value={body} onChange={(e) => setBody(e.target.value)} />
          <button onClick={() => { dispatch(addComment({ file, line, hunkHash, body })); setOpen(false); }}>
            Comment
          </button>
        </div>
      )}
    </div>
  );
}
```

**验收命令**：
```powershell
python -m pytest tests/test_review_comments -q
python -m pytest tests/test_review -q   # 主链 B8 回归门禁（GX3 复用 B8 能力）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：五档 scope 投影、评论 add/resolve、hunk 失效 stale 标记、下达草稿生成
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `review/comment/add` / `review/comment/resolve` 协议落地（contract test 通过）
- [ ] 五档 scope 按探针路径执行：B8 已有 scope 直接消费；缺失的 scope 走枚举扩展子卡（GX3-PROTO）
- [ ] hover 行尾按钮 → 评论 → 下达草稿 → 修复 → stale → resolve 全闭环可走通
- [ ] 评论不进 git、不改变 B8 字段语义
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX3 inline diff comments with five-tier review scope

Codex-inspired comment loop (hover -> comment -> draft message -> fix ->
resolve) and review scope selector including last_turn. Comments persist
in appserver review records; git untouched.
```

---

## GX4 · Checkpoint 回滚 UI（revert 挂消息 / 命名快照 / 双向导航）

**借鉴来源**：Devin Desktop 检查点与回滚（调研 §6.3-4）；Replit Checkpoints 双向导航（§10.3-7）；Claude rewind 菜单（§3.3-5/6）；Copilot Restore/Redo（§4.3-7）。
**优先级/工时**：P0 / 3–4d / 依赖：B8 + H9 完成 / **owner: frontend 为主 + backend 扩展**
**背景**：主链 B8 已有 checkpoint（创建/列出/读取/恢复，checkpoint restore 后 diff hash 变化），但 UI 上没有回滚入口——用户找不到"怎么退回去"。四家共识：**回滚入口必须挂在每条消息上（hover revert 箭头）**，配命名快照与不可逆警告，恢复时对话上下文一并回填。

**涉及文件**：
- `frontend/desktop-app/src/features/checkpoints/MessageRevertButton.tsx`（新增：消息 hover revert 箭头）
- `frontend/desktop-app/src/features/checkpoints/CheckpointTimeline.tsx`（新增：检查点时间轴）
- `frontend/desktop-app/src/features/checkpoints/NamedSnapshotDialog.tsx`（新增：命名快照）
- `frontend/desktop-app/src/features/checkpoints/CheckpointTimeline.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`checkpoint/snapshot/create`、`checkpoint/rewind`，new_method）
- `appserver/handlers/checkpoint_rewind.py`（新增：rewind 编排 = checkpoint restore + 对话回填）
- `tests/test_checkpoint_rewind.py`（新增）

**规范限制**：
- **rewind 语义冻结（状态模型一致）**：`checkpoint/rewind` = ①创建新的恢复点（当前状态快照，避免不可逆）②代码恢复到目标 checkpoint ③对话读取面截断到目标点 ④目标 checkpoint 的用户消息回填输入框（可重发）。**历史 checkpoint 全部保留**（时间轴可前滚——"双向导航"指恢复点在时间轴上的双向选择，不是删除历史）；命名快照与自动 checkpoint 同存储（`~/.rxycode/checkpoints/`，运行时数据目录规则见 §1-18）
- **回滚确认**：rewind 前弹确认（含影响文件数/对话条数/可前滚提示）；确认参数 `confirm: true` 必须由用户 UI 动作显式携带
- 命名快照数据结构冻结（appserver 持久化，复用 B8 checkpoint 表追加 `name` 可空字段——协议 new_optional_field）：`{checkpoint_id, seq, name?, file_count, diff_hash, user_prompt, created_at}`
- **回滚后生成新 checkpoint**（记录"回滚动作"本身，保持版本链连续）；前滚 = 选择时间轴后续的 checkpoint 执行同一 rewind 流程
- 只读消费主链 B8 的 checkpoint 数据模型（代码恢复语义复用 B8 `checkpoint restore`）；本卡新增的是「命名快照 + 对话截断投影 + 消息回填」三个能力。**`checkpoint/snapshot/create` 命名快照探针**：先核对 B8 既有 checkpoint 创建方法——已有创建能力且仅需命名参数 → 复用 + new_optional_field（`name`）；语义不同（如手动命名快照与自动打点分离）才新增 `checkpoint/snapshot/create`（new_method）；探针结论写入 PR
- 每 prompt 自动打点沿用主链 B8（本卡不改变打点时机）
- 时间轴默认折叠，hover 展开；30 天清理沿用主链

**开发步骤**（先探针，A/B 路径）：
1. **Protocol probe**（§1-16 固定字段）：核对 B8 checkpoint 创建/恢复的真实方法名与字段（name/user_prompt/seq/对话截断相关字段）——**PASS 前本卡 BLOCKED_PREREQUISITE，不进入实现**
2. 路径 A（B8 已有）：仅实现 UI/投影（revert 箭头/时间轴/命名快照 UI 层），后端零新增
3. 路径 B（缺失）：登记 GX4-PROTO（§2）→ `checkpoint/snapshot/create`（`{name}`）、`checkpoint/rewind`（`{checkpoint_id, confirm: true}`）协议变更单 → `appserver/handlers/checkpoint_rewind.py`（调 B8 服务 + 对话回填）
2. 前端：`MessageRevertButton`（消息 hover 出现 ↶ 箭头 → rewind 确认对话框 → 执行后对话回填）
3. `CheckpointTimeline`（消息流左侧时间轴：自动点 + 命名快照图标，点击跳转预览）→ 五态
4. 双向导航：回滚后时间轴保留后续点（可前滚，Replit 语义）

**示例代码**（rewind 后端编排）：

```python
# appserver/handlers/checkpoint_rewind.py —— rewind 编排（GX4 新增）
# 复用点标注：主链 B8 checkpoint restore（方法名/字段以 B8 schema 实际为准，缺失则 BLOCKED）
from appserver.handlers.checkpoints import CheckpointService  # 主链 B8，只读复用


async def handle_checkpoint_rewind(checkpoint_id: str, confirm: bool) -> dict:
    """rewind = 恢复前快照 + 代码恢复 + 对话截断 + 消息回填（保持版本链连续）。"""
    if not confirm:
        raise ProtocolError("rewind requires explicit confirm=true")
    target = await CheckpointService.get(checkpoint_id)
    # 0) 恢复前快照：把当前状态打成新 checkpoint（版本链连续，前滚入口保留）
    restore_point = await CheckpointService.snapshot(reason="pre-rewind")
    # 1) 代码恢复（B8 既有语义，checkpoint restore 后新 diff hash）
    await CheckpointService.restore(checkpoint_id)
    # 2) 对话截断：该 checkpoint 之后的 user/assistant 消息从会话读取面隐藏（投影，不删除）
    truncated = await ThreadService.truncate_projection_at(checkpoint_id)
    # 3) 回填：checkpoint 对应的用户消息原文回填输入框（前端消费事件）
    return {"restore_point": restore_point.id, "restored_files": target.file_count,
            "truncated_messages": truncated, "refill_prompt": target.user_prompt}
```

**验收命令**：
```powershell
python -m pytest tests/test_checkpoint_rewind -q
python -m pytest tests/test_review -q   # 主链 B8 回归门禁（GX4 复用 B8 checkpoint）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：rewind 三步编排、确认必需、回滚后新 diff hash（沿用 B8 断言）、不可逆警告、失败恢复/幂等
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 按探针路径执行：B8 复用 + new_optional_field，或 GX4-PROTO 新增 `checkpoint/rewind` / `checkpoint/snapshot/create`（协议变更单）
- [ ] revert 箭头挂在消息 hover 上；确认框含影响范围
- [ ] rewind 后代码恢复 + 对话截断 + 原消息回填输入框
- [ ] 命名快照可创建/列示；时间轴双向导航
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX4 checkpoint rewind UI with named snapshots

Devin/Replit/Claude-inspired: revert arrow on message hover, rewind =
code restore + conversation truncation + prompt refill via single
checkpoint/rewind protocol method. Requires explicit confirm.
```

---

## GX5 · 消息排队/打断（Send 三态下拉）

**借鉴来源**：Copilot Queue/Steer/Stop-and-send（调研 §4.3-1）；Cursor Alt+Enter 排队 / Cmd+Enter 打断（§5.3-9）；Codex Tab 排队 / Enter 注入（§2.3-12）。
**优先级/工时**：P0 / 2–3d / 依赖：H5 完成 / **owner: frontend**
**背景**：主链 H5 的对话输入在 agent 运行时是禁用的（用户只能等或停）。Copilot 的"运行中 Send 变下拉"是三家中语义最清晰的运行中干预：Add to Queue（完成后发）/ Steer with Message（当前工具执行完即停，处理新消息）/ Stop and Send。pending 消息可拖拽重排。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/composer/SendDropdown.tsx`（新增：Send 三态下拉）
- `frontend/desktop-app/src/features/composer/pending.queue.ts`（新增：pending 队列 store，可拖拽重排）
- `frontend/desktop-app/src/features/composer/Composer.test.tsx`（新增：三态 + 重排测试）
- `frontend/desktop-app/src/features/composer/steer.message.ts`（新增：steer 协议客户端封装）

**规范限制**：
- 三态语义冻结：`queue`（agent 完成后按序发送）/ `steer`（当前工具调用完成即中断处理新消息）/ `stop_and_send`（停止当前回合并发送）；默认 `queue`；**空闲时 Send = 立即发送**（`send` 即 queue 的立即发送语义，空闲态下拉不出现）
- **steer/stop 的后端语义（先核对，缺失则 BLOCKED 登记制）**：主链 B5 的必须实现含 "Turn start/steer/interruption/retry"（G-B B5 卡）；实现本卡时先核对 `turn/steer`、`turn/interrupt` 方法与中断语义在 schema 中真实存在——存在则直接消费（路径 A）；**不存在（路径 B）→ 本卡报告 `BLOCKED_PREREQUISITE` 并走 §1-17 的 GX*-PROTO 登记流程**（新增子卡须正式列入卡表/依赖图/owner/验收命令/协议变更单，不得在本卡内临时新增协议）。**排期**：先完成协议探针——路径 A 纯前端执行；路径 B 待 GX5-PROTO 登记完成后另行排期。本卡**不做「协议零变更」承诺**（完成判据以实际核对结论为准）
- pending 队列是**前端 UI 状态**（不新增协议方法；发送仍走主链 `agent/invoke`），最多 10 条（借鉴 v0 排队上限）
- 拖拽重排仅限 pending 队列内部；已发送消息不可重排
- 键盘：Alt+Enter = 排队、Ctrl+Enter = 打断并发送（默认，可在设置改）
- 不修改主链 H5 的输入框组件文件——新增 Composer 包装组件（`ComposerGX.tsx`）包裹原输入框

**开发步骤**：
1. `Composer.test.tsx`（red）：三态下拉渲染、pending 队列 push/重排/删除、快捷键映射
2. `pending.queue.ts`（队列状态 + 重排逻辑）
3. `SendDropdown`（agent 运行时 Send 变下拉，非运行时保持普通 Send；带 pending 计数徽标）
4. `ComposerGX` 包装接入主链输入框（props 透传，不碰原组件）
5. 五态：空闲/运行中/队列非空/窄窗（下拉变图标）/深色

**示例代码**（三态下拉核心）：

```tsx
// SendDropdown.tsx —— 运行中 Send 变三态下拉（GX5）
type SendIntent = 'queue' | 'steer' | 'stop_and_send';

export function SendDropdown({ running, onSend }: { running: boolean; onSend: (i: SendIntent) => void }) {
  // 空闲时：Send = 立即发送（queue 的立即发送语义，不出现下拉）
  if (!running) return <button className="btn-primary" onClick={() => onSend('queue')}>Send</button>;
  return (
    <div className="send-menu">
      <button onClick={() => onSend('steer')}>Steer with Message</button>
      <button onClick={() => onSend('stop_and_send')}>Stop and Send</button>
      <button onClick={() => onSend('queue')}>Add to Queue</button>
    </div>
  );
}
// 键盘：Alt+Enter -> queue；Ctrl+Enter -> stop_and_send（挂 ComposerGX keydown）
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三态语义、pending 重排/删除/上限 10、快捷键、运行/空闲两态渲染
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 运行中 Send 变三态下拉；空闲保持普通 Send
- [ ] pending 队列可 push/重排/删除，上限 10 条
- [ ] Alt+Enter / Ctrl+Enter 快捷键生效
- [ ] steer/stop 的协议核对结论写入 PR（B5 已有 → 直接消费；缺失 → GX5-B 协议变更单落地）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX5 send three-state dropdown (queue/steer/stop-and-send)

Copilot/Cursor-inspired mid-run intervention. Pending queue is pure
frontend state (max 10, draggable); steer/stop semantics per B5
turn-steering protocol check (GX5-B protocol change if absent).
```

---

## GX6 · 工具调用流式卡片 + Todo 步骤时间线 + 节点自动折叠

**借鉴来源**：Cursor 工具卡片与 Compact 模式（调研 §5.3-3/10）；Qoder 待办三态（§9.3-3）；TRAE 节点自动折叠（§8.3-6）；Devin 进度时间线（§7.3-3）。
**优先级/工时**：P0 / 3–4d / 依赖：H6/H7 完成 / **owner: frontend**
**背景**：主链 H6/H7 的工具调用已流式渲染，但长会话会刷屏。Cursor/TRAE 共识：**工具调用卡片化（可折叠、带状态与耗时）+ 待办三态（空圆/旋转/复选）+ 完成节点自动折叠为摘要**，长任务不黑盒也不刷屏。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/items/ToolCallCard.tsx`（新增：工具卡片：图标/名称/状态徽标/耗时/参数摘要，可折叠）
- `frontend/desktop-app/src/features/items/TodoTimeline.tsx`（新增：三态待办时间线）
- `frontend/desktop-app/src/features/items/autoFold.ts`（新增：自动折叠规则引擎）
- `frontend/desktop-app/src/features/items/ToolCallCard.test.tsx`（新增）

**规范限制**：
- 工具卡片是**渲染层包装**：数据消费主链 H7 的 Tool/Command/BackgroundTask item states，不新建状态模型
- 状态徽标映射冻结（§1-9 状态色）：running=蓝旋转、success=绿、failed=红、cancelled=灰、timeout=橙、waiting_approval=紫
- **自动折叠规则冻结（错误可观察性优先）**：仅**成功**（success）且无 diff 引用的节点默认折叠为一行摘要（✓ 工具名）；**failed / timeout / waiting_approval 默认展开**（错误详情与恢复动作是用户所需关键信息），cancelled 折叠但保留"已取消"徽标；diff 引用节点（agent 改过的文件）不折叠
- 折叠可整体开关（设置项）；展开保留全部细节
- 待办三态：空心圆=未开始、旋转圆=进行中、复选=完成（Qoder 语义）

**开发步骤**：
1. `ToolCallCard.test.tsx`（red）：六种状态徽标、折叠/展开、耗时显示、auto-continue 按钮（调用主链 B5 retry，先核对存在性，缺失则走协议变更）
2. `ToolCallCard` 实现（消费 H7 item states 投影）
3. `TodoTimeline`（从 Thread 的 planning 状态投影：未开始/进行中/完成）
4. `autoFold` 规则引擎（仅折叠已完成且无 diff 引用的节点）+ 全局开关接线到设置页
5. 五态：空（无工具）/加载/错误/窄窗/深色

**示例代码**（自动折叠规则）：

```ts
// autoFold.ts —— 折叠规则冻结（GX6；错误可观察性优先）
export function shouldAutoFold(item: ToolItem): boolean {
  // 仅折叠：成功 且 无 diff 引用（agent 改过的文件保持展开）
  // failed / timeout / waiting_approval 默认展开（错误详情是恢复任务的关键信息）
  if (item.status !== 'success') return false;
  return !item.referencesDiff;
}
// 折叠渲染：<summary>✓ {item.tool}</summary> + 展开保留全细节
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：六状态徽标映射、折叠规则（完成+无diff引用）、todo 三态、auto-continue
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 工具卡片六状态徽标正确；折叠/展开保留细节
- [ ] auto-continue 复用 B5 retry（核对结论写入 PR；缺失则走协议变更）
- [ ] 待办三态时间线正确投影
- [ ] 自动折叠仅作用于"成功且无 diff 引用"节点；failed/timeout/waiting_approval 默认展开；全局开关生效
- [ ] 锁定范围与 GX5 排队/steer 组合测试通过（Composer 保留）；协议零变更（纯前端）；五态通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX6 tool-call cards, todo timeline, auto-fold

Cursor/Qoder/TRAE-inspired: status badges, three-state todo icons,
auto-fold of completed non-diff tool nodes. Pure rendering layer.
```

---

## GX7 · 上下文用量/成本指示器 + statusline

**借鉴来源**：Codex statusline 与 /usage（调研 §2.3-14/15）；Claude Usage ring（§3.3-12）；Cursor 用量汇总超 50% 提醒（§5.3-12）。
**优先级/工时**：P0 / 2–3d / 依赖：B10 + H11 完成 / **owner: frontend + backend 协议扩展**
**背景**：主链 B10 已有模型摘要（limit_source/fallback）但 UI 不展示消耗。Codex 的 footer statusline（model/tokens/context left/git/task progress）与 Claude 的 usage ring 是"隐性消耗可视化"标准件；Cursor 的超 50% 配额提醒是防爆细节。

**涉及文件**：
- `frontend/desktop-app/src/components/statusbar/Statusline.tsx`（新增：底部状态条，可配置项）
- `frontend/desktop-app/src/components/statusbar/UsageRing.tsx`（新增：用量环）
- `frontend/desktop-app/src/components/statusbar/statusline.config.ts`（新增：可配置项/顺序）
- `frontend/desktop-app/src/components/statusbar/Statusline.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`event/agent_usage` 事件，new_event，符合原版 `event/agent_*` 命名空间；复用 B10 模型摘要）
- `appserver/usage_tracker.py`（新增：会话级 token/成本聚合，消费 Phase 3 摘要；产出 `event/agent_usage`）
- `tests/test_usage_tracker.py`（新增）

**规范限制**：
- statusline 项冻结并可配置（顺序可拖拽/开关）：`model` / `context`（用量环）/ `tokens` / `git_branch` / `task_progress` / `cost`；默认前三项
- 用量数据**唯一来源**是 appserver（`event/agent_usage` 事件），前端不自行计算成本（Phase 3 摘要唯一真相，与主链 B10/H11 一致）
- **成本字段降级规则**：实现前核对主链 schema 的 usage/limit 字段实际存在哪些——**只有 Phase 3 摘要确实提供定价字段时才显示 `cost` 项**；若 schema 无定价字段，`cost` 项隐藏并在 PR 注明（`PENDING_PRICING`），只展示 token/context 用量；不得虚构定价
- 超 50% 上下文：用量环变琥珀色 + 会话内一次性提醒（不打断流）
- 会话切换/恢复后用量从 appserver 重取（不本地缓存跨会话）
- 事件去重：`event/agent_usage` 事件带 `seq`（单调递增），前端以 seq 去重；推送频率：每工具调用 + 每 30s 心跳
- 成本显示单位：本次会话累计（币种以 Phase 3 摘要定价字段为准）

**开发步骤**：
1. 后端先行：`tests/test_usage_tracker.py`（red）→ `appserver/usage_tracker.py`（从 Phase 3 resolver 的 usage accumulator 聚合）→ `event/agent_usage` 事件（new_event，推送频率：每工具调用 + 每 30s 心跳）
2. 前端：`Statusline.test.tsx`（red）→ 组件（默认项渲染/配置开关/顺序）→ `UsageRing`（SVG 环：上下文用量占比 + 阈值变色）→ 50% 提醒
3. 接线：消费 `event/agent_usage` 事件更新状态条；会话切换重取
4. 五态：无会话（隐藏）/加载/错误/窄窗（只显 model+ring）/深色

**示例代码**（用量环组件）：

```tsx
// UsageRing.tsx —— 上下文用量环（GX7，数据来自 event/agent_usage 事件，不自行计算）
export function UsageRing({ usedPct }: { usedPct: number }) {
  const R = 8, C = 2 * Math.PI * R;
  // 阈值冻结：50% 琥珀、90% 红（借鉴 Cursor 超 50% 提醒）；clamp 防非法值
  const pct = Math.min(100, Math.max(0, usedPct));
  const color = pct > 90 ? 'var(--error)' : pct > 50 ? 'var(--warn)' : 'var(--ok)';
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-label={`context ${pct}% used`}>
      <circle cx="10" cy="10" r={R} fill="none" stroke="var(--border)" strokeWidth="3" />
      <circle cx="10" cy="10" r={R} fill="none" stroke={color} strokeWidth="3"
              strokeDasharray={`${C * pct / 100} ${C}`} transform="rotate(-90 10 10)" />
    </svg>
  );
}
```

**验收命令**：
```powershell
python -m pytest tests/test_usage_tracker -q
python -m pytest tests/test_settings -q   # 主链 B10 回归门禁（GX7 消费 Phase 3 摘要）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：usage 事件推送频率、50/90 阈值变色、statusline 配置顺序、会话切换重取
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `event/agent_usage` 事件落地（每工具调用 + 30s 心跳，符合 event/agent_* 命名空间）
- [ ] statusline 默认三项 + 可配置排序/开关
- [ ] 用量环 50%/90% 阈值变色；50% 提醒一次
- [ ] 前端零成本计算（数据全来自 appserver）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX7 usage ring + configurable statusline

Codex/Claude/Cursor-inspired. event/agent_usage from appserver (single
source of truth, Phase 3 summaries); frontend never computes cost.
```

---

## GX8 · 会话管理四件套 + 消息级 fork

**借鉴来源**：Codex 会话管理与消息级 fork（调研 §2.3-9/10）；Claude 会话过滤分组（§3.3-14）。
**优先级/工时**：P0 / 3–4d / 依赖：B5 + H5 完成 / **owner: frontend + backend 协议扩展**
**背景**：主链 H5 会话中心只有列表/新建/恢复。Codex 四件套（重命名/钉选/归档/搜索）+ 消息级 fork（编辑上一条消息从该点分叉新会话）是低成本高感知价值的会话能力全集，也是多任务用户的核心诉求。

**涉及文件**：
- `frontend/desktop-app/src/features/sessions/SessionMenu.tsx`（新增：右键/三点菜单：Rename/Pin/Archive/Search）
- `frontend/desktop-app/src/features/sessions/SessionSearchBar.tsx`（新增：Cmd+G 搜索）
- `frontend/desktop-app/src/features/sessions/ForkConversation.tsx`（新增：消息级 fork 入口）
- `frontend/desktop-app/src/features/sessions/session.search.ts`（新增：本地索引，标题+消息文本）
- `frontend/desktop-app/src/features/sessions/SessionMenu.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`thread/fork`，new_method；`thread/pin`、`thread/archive` 为 B5 既有方法的追加字段语义或 new_optional_field）
- `appserver/handlers/thread_fork.py`（新增）
- `tests/test_thread_fork.py`（新增）

**规范限制**：
- 四件套协议归属冻结（**操作 = new_method，字段 ≠ 操作**）：`rename` / `pin` / `archive` 是**状态变更操作**——先核对主链 B5 是否已有对应 mutation 方法：有 → 直接复用（注明方法名/字段/原版验收）；只有资源字段、无 mutation 方法 → 新增 `thread/rename`、`thread/pin`、`thread/archive`（new_method，探针后提交协议变更单）；**禁止**用 `new_optional_field` 替代操作语义。`search` 为本地索引，不入协议
- **消息级 fork 语义冻结**：`thread/fork`（`{thread_id, message_id, edited_text?}`）→ 新 Thread 从该消息分叉，原 Thread 不变；**fork 点必须是 user message**（assistant 消息 / 工具调用 / 附件不可作 fork 点，请求无效返回协议错误）；空输入 Esc Esc = 编辑上一条用户消息并从该点 fork（Codex 语义）
- **fork 复制规则冻结**：复制到 fork 点为止的 user/assistant 消息（含文本与附件引用）；**不复制**工具调用历史、审批策略、Child 会话（子代理树在原 Thread 保留）
- fork 出的新 Thread 继承原会话的 workspace 绑定（B5 语义），不继承审批策略
- 搜索索引本地构建（sqlite/内存），不入协议；索引构建失败降级为标题搜索；**索引生命周期**：新消息增量入索引、归档/删除线程从索引清除（或标记不可命中）、fork 新线程继承到 fork 点的索引片段；**隐私边界**：索引落盘仅存线程标题与消息文本（含脱敏规则：不含密钥/路径全文，遵循主链 B13 crash 脱敏纪律），索引文件属于用户本地数据（`~/.rxycode/`，运行时数据目录规则见 §1-18），不入协议传输
- 不修改主链 H5 会话列表组件——新增 `SessionMenu` 挂接点（context menu 注册）

**开发步骤**：
1. 后端先行：`tests/test_thread_fork.py`（red）→ `thread/fork` 协议 → `appserver/handlers/thread_fork.py`（复用 B5 Thread 服务：复制到 message_id 的消息 + workspace 绑定）
2. 前端：`SessionMenu.test.tsx`（red）→ 三点菜单四件套 → `SessionSearchBar`（Cmd+G 打开，标题+内容匹配）→ `ForkConversation`（消息 hover "fork" 按钮 + Esc Esc 快捷）
3. 接线：pin 状态存 B5 thread 元数据（new_optional_field）；fork 结果跳转新 Thread
4. 五态：空/加载/错误/窄窗/深色

**示例代码**（fork 协议 handler）：

```python
# appserver/handlers/thread_fork.py —— 消息级 fork（GX8）
async def handle_thread_fork(thread_id: str, message_id: str, edited_text: str | None = None) -> dict:
    """从 message_id 分叉新 Thread；原 Thread 不变（Codex fork 语义）。"""
    src = await ThreadService.get(thread_id)
    cutoff = await MessageService.index_of(message_id)
    new_thread = await ThreadService.create(
        workspace_id=src.workspace_id,          # 继承 workspace 绑定（B5 语义）
        title=f"{src.title} (fork)",
        messages=await MessageService.slice(src.id, 0, cutoff + 1),
    )
    if edited_text:                             # Esc Esc 编辑重发路径
        await MessageService.replace_last(new_thread.id, edited_text)
    return {"thread_id": new_thread.id}
```

**验收命令**：
```powershell
python -m pytest tests/test_thread_fork -q
python -m pytest tests/test_threads -q   # 主链 B5 回归门禁（GX8 复用 B5 Thread 服务）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：fork 三动作（原样/编辑重发/空输入 Esc Esc）、原 Thread 不变、pin/archive/search
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `thread/fork` 协议落地（含 edited_text 路径）
- [ ] 四件套可用：重命名/钉选/归档/搜索（Cmd+G）
- [ ] 消息 hover fork 入口 + Esc Esc 快捷（空输入时）
- [ ] fork 继承 workspace、不继承审批策略；原 Thread 不变
- [ ] 搜索索引失败降级标题搜索
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX8 session management (rename/pin/archive/search) + message-level fork

Codex-inspired. thread/fork protocol method: fork from message id with
optional edited text; Esc-Esc edits last message and forks.
```

**P3 对接（追加，2026-08-12）**：pin 语义由 **GX20 会话三分类**整合——置顶会话归入"置顶"分类（固定分类顶部），pin 操作结果同步刷新分类投影；删除动作改为**软删除映射**（B17，进回收站），本卡归档/搜索语义不变；搜索索引的删除线程排除纪律由 B17 落实。

---

# P1 批（GX9–GX14）

## GX9 · Plan 文件持久化 + Implement 按钮

**借鉴来源**：Devin Desktop 计划文件持久化（调研 §6.3-2）；TRAE Plan/Spec 文档化工作流（§8.3-7/8）。
**优先级/工时**：P1 / 3–4d / 依赖：GX8 完成 / **owner: frontend + backend 协议扩展**
**背景**：主链的 plan（B5 的 planning 状态）不落盘、不可复用。Devin Desktop 证明：**计划成为外部持久 markdown 文件（会话间可 @ 复用），点 Implement 一键转执行**——是"规划与执行分离"的最强制度化形态；TRAE 的 Spec 三件套（大纲/任务/验收清单）是文档即资产的进一步佐证。

**涉及文件**：
- `frontend/desktop-app/src/features/plan/PlanFilePanel.tsx`（新增：计划文件查看/编辑/Implement）
- `frontend/desktop-app/src/features/plan/PlanImplementButton.tsx`（新增）
- `frontend/desktop-app/src/features/plan/PlanFilePanel.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`plan/persist`、`plan/implement`，new_method）
- `appserver/handlers/plan_files.py`（新增：`~/.rxycode/plans/` 计划文件管理）
- `tests/test_plan_files.py`（新增）

**规范限制**：
- 计划文件存放冻结：`~/.rxycode/plans/<thread_id>-<slug>.md`（运行时数据目录规则见 §1-18；不随 git 走，用户目录独立）
- `plan/persist`：把主链 plan 状态导出为 markdown（结构冻结：目标/步骤/验收清单三节）；`plan/implement`：读取计划文件 → 生成 Thread turn（计划作为首条上下文注入）→ 转执行
- 计划文件**只读复用**：@ 引用计划文件 = 注入文件内容进上下文（复用主链 @ 机制，不新增协议）
- Implement 前必须确认（防误触）；实施中的计划文件标记 `implementing` 状态
- 不修改主链 plan 状态机（B5）——persist 是导出视图，implement 是入口

**开发步骤**：
1. 后端先行：`tests/test_plan_files.py`（red）→ `plan/persist` / `plan/implement` → `appserver/handlers/plan_files.py`
2. 前端：`PlanFilePanel.test.tsx`（red）→ 面板（文件树/预览/编辑 markdown/Implement 按钮）→ 接线 @ 引用
3. 五态：无计划/加载/错误/窄窗/深色

**示例代码**（计划文件结构冻结）：

```md
<!-- 计划文件结构冻结（GX9）：目标 / 步骤 / 验收清单 三节 -->
# Plan: <title>
## 目标
<单段目标描述>
## 步骤
- [ ] 1. <step>
## 验收清单
- [ ] <acceptance criterion>
```

**验收命令**：
```powershell
python -m pytest tests/test_plan_files -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：persist 三节结构、implement 生成 turn、@ 引用注入、implementing 状态
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

> ⚠️ **2026-08-18 追加注记（四）· 本卡的 `goal` 节与 `/goal` 命令已被裁定为同一个东西**
>
> 本卡把计划文件冻结为三节 `goal` / `steps` / `acceptance`。**同时** Desktop 里已经有一个 `/goal` 命令（`lib/goalSettings.mts`，存 localStorage 的一段文本），两者同名但互不相干——这是典型的同名异物。
>
> [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) **DN3 已裁定合并**：`/goal` 的目标本体写进本卡的 `goal` 节，完成判据写进 `acceptance` 节，长任务的检查点写进 `steps` 节的完成态。**从此是同一个东西，不建第二套存储。**
>
> **对本卡的影响：零。** 三节结构、存放路径、协议方法、完成判据全部照原样执行——Phase N 的 N5 是本卡的**下游消费方**，不是修改方。反过来说：**N5 依赖本卡，本卡未合入时 N5 输出 `BLOCKED_PREREQUISITE` 且禁止建临时存储**。所以本卡的优先级对 Phase N 的长任务线是硬约束。

**完成判据**：
- [ ] `plan/persist` / `plan/implement` 协议落地
- [ ] 计划文件三节结构冻结；存放于 `~/.rxycode/plans/`
- [ ] Implement 确认框 + implementing 状态
- [ ] @ 引用计划文件注入上下文
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX9 persistent plan files with Implement flow

Devin-Desktop-inspired. plan/persist exports thread plan to
~/.rxycode/plans (goal/steps/acceptance); plan/implement starts execution
with the plan as first-turn context.
```

---

## GX10 · 聊天侧栏浮层（plan / sources / files / summary）

**借鉴来源**：Codex 聊天中侧栏浮层（调研 §2.3-12）。
**优先级/工时**：P1 / 2–3d / 依赖：H5 + **GX7** 完成 / **owner: frontend**
**背景**：agent 运行中用户想看"它在计划什么、引用什么、改了哪些文件、摘要到哪了"——Codex 在聊天中浮出 plan/sources/files/summary 侧栏用于中途引导（steer）。这是运行中透明化的直接实现，全部数据主链已有（B5 plan 状态、B6 工具事件、H5 消息流）；summary 节消费 GX7 的 `event/agent_usage` 用量（GX7 未合入时 summary 节降级隐藏并注明，不阻塞其他三节）。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/runpanel/RunPanel.tsx`（新增：运行中侧栏浮层容器）
- `frontend/desktop-app/src/features/runpanel/PlanSection.tsx`、`SourcesSection.tsx`、`FilesSection.tsx`、`SummarySection.tsx`
- `frontend/desktop-app/src/features/runpanel/RunPanel.test.tsx`（新增）

**规范限制**：
- 只读投影：四节全部消费主链已有数据，**实现前先核对字段真实存在**（B5 plan 状态 / B6 工具事件中的 sources 字段 / H7 文件变更 item / 消息流）——核对缺失的字段（如 sources、summary/完成度）要么走协议变更单补齐，要么该节只投影已有字段并在完成判据注明；不得用「降级隐藏」掩盖接口未定义
- 浮层在 agent 运行中可随时开关（聊天区右上角图标）；运行结束后折叠为摘要行
- summary 节显示：已用 token（消费 GX7 的 event/agent_usage）、当前步骤、完成度
- 不阻塞主对话流（浮层是独立面板，不是模态）

**开发步骤**：
1. `RunPanel.test.tsx`（red）：四节渲染、运行中/结束后状态、开关
2. 四节组件（各消费主链 store 投影）
3. 容器 + 入口图标接线
4. 五态

**示例代码**（面板结构）：

```tsx
// RunPanel.tsx —— 运行中侧栏（GX10，只读投影）
export function RunPanel({ threadId }: { threadId: string }) {
  const running = useThreadRunning(threadId);
  return (
    <aside className="run-panel" aria-label="agent run panel">
      <PlanSection threadId={threadId} />      {/* B5 plan 投影 */}
      <SourcesSection threadId={threadId} />   {/* B6 sources 投影 */}
      <FilesSection threadId={threadId} />     {/* H7 文件变更投影 */}
      {running && <SummarySection threadId={threadId} />}  {/* 运行中才显示摘要 */}
    </aside>
  );
}
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：四节投影、运行中/结束后状态切换、开关、不阻塞对话流
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 字段对照表随 PR 提交（B5 plan/B6 sources/H7 变更/GX7 usage 逐项核对：全部存在 → 纯前端投影；缺失 → 协议子卡 + 本卡 BLOCKED）
- [ ] 运行中可开关；结束后折叠摘要行
- [ ] **GX7 已合入 / 未合入两组测试均通过**（summary 节在未合入时降级隐藏，接口类型 `SummarySection` 可选渲染）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX10 running agent side panel (plan/sources/files/summary)

Codex-inspired. Read-only projection of B5/B6/H7/GX7 data for mid-run
steering. Per field probe: existing fields only; missing fields handled
by separate protocol sub-card, never hidden-and-complete.
```

---

## GX11 · 运行中会话只读锁定 + 侧栏筛选分组

**借鉴来源**：Devin Desktop 运行中会话锁定（调研 §6.3-11）；Claude 会话过滤分组（§3.3-14）。
**优先级/工时**：P1 / 3–4d 单人（双人并行 1.5-2d，含协议变更/生成类型/契约测试/联调）/ 依赖：H5 + B5 完成 / **owner: frontend + backend**
**背景**：多会话并行时，用户可能误操作正在运行的会话（发消息打断、删文件）。Devin Desktop 将运行中会话锁定为只读灰显；Claude 提供按状态/项目筛选与分组。两者都是多会话场景的秩序保障。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/sessions/SessionListFilter.tsx`（新增：筛选/分组）
- `frontend/desktop-app/src/features/sessions/ReadOnlyLock.tsx`（新增：运行中只读锁定 UI）
- `frontend/desktop-app/src/features/sessions/SessionListFilter.test.tsx`（新增）

**规范限制**：
- **只读锁定语义（与 GX5 共存）**：running 会话锁定的是"修改会话配置/历史消息/项目绑定"类操作（编辑历史消息、改设置、归档、删除），**Composer 输入框保留**（GX5 的排队/steer 依赖输入）；会话列表项灰显 + 徽标"running"；停止/完成后解锁
- 锁定不拦截协议层（后端仍接受）——UI 层防误操作（与 Devin Desktop 语义一致：锁定只读灰显）
- 筛选维度冻结：按状态（running/done/awaiting_review/archived）、按项目分组；可组合
- 不修改主链 H5 会话列表组件文件——新增 filter 包装（`SessionListGX.tsx`）

**开发步骤**：
1. `SessionListFilter.test.tsx`（red）
2. `SessionListFilter`（下拉筛选 + 分组视图）与 `ReadOnlyLock`（输入框禁用 + 灰显 + 徽标）
3. `SessionListGX` 包装接入
4. 五态

**示例代码**（锁定投影）：

```ts
// ReadOnlyLock.tsx 语义 —— running 会话锁定配置/历史（GX5 排队输入保留）
const locked = thread.status === 'running';
<Composer disabled={false} placeholder={locked ? 'Running — you can queue (Alt+Enter)' : 'Message...'} />
// 历史消息编辑按钮 / 设置 / 归档 / 删除：locked 时禁用
// 会话列表项：灰显 + running 徽标 + 悬停提示"点击查看只读"
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：running 锁定/解锁、筛选组合、分组、灰显徽标
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] running 会话锁定配置/历史编辑 + 灰显 + 徽标；Composer 保留（GX5 排队）；停止后解锁
- [ ] 筛选（状态×项目）组合可用；分组视图
- [ ] 锁定范围与 GX5 排队/steer 组合测试通过（Composer 保留）；协议零变更（纯前端）；五态通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX11 read-only lock for running sessions + list filtering

Devin-Desktop/Claude-inspired. UI-layer lock: disable configuration /
history mutations while keeping the composer enabled (GX5 queue/steer).
Filter by status/project, group view.
```

---

## GX12 · Prompt suggestions（灰色示例输入）

**借鉴来源**：Claude Prompt suggestions（调研 §3.4）；Codex/Replit 首屏引导。
**优先级/工时**：P1 / 1–2d / 依赖：H5 完成 / **owner: frontend**
**背景**：新用户首次打开会话不知道说什么。Claude 在输入框显示灰色示例指令（取自 git 历史），回复后基于会话续推，Tab 采纳——低成本、高引导价值，且复用 prompt cache 成本极低。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/composer/PromptSuggestions.tsx`（新增）
- `frontend/desktop-app/src/features/composer/suggestions.ts`（新增：建议生成规则）
- `frontend/desktop-app/src/features/composer/PromptSuggestions.test.tsx`（新增）

**规范限制**：
- 建议来源冻结：①新会话空输入 → 从 git 历史提取 3 条（`git log --oneline -3` 首行描述）②有回复后 → 基于最近 2 条消息关键词续推 2 条模板 ③Tab 采纳、Esc 关闭、Enter 直接发
- 建议仅在前 5 条用户消息内出现（之后关闭，避免骚扰）；**git 读取降级与脱敏**：workspace 非 Git 仓库或 `git log` 失败时隐藏建议（或用固定通用模板）；完整 commit 信息脱敏显示（仅取首行主题，不显示作者/邮箱/路径等）
- 不调用 LLM（纯规则/模板），零成本
- 不修改主链输入框组件——`PromptSuggestions` 渲染在输入框上方

**开发步骤**：
1. `PromptSuggestions.test.tsx`（red）
2. `suggestions.ts`（git 历史提取 + 模板续推规则）
3. 组件 + Tab/Esc/Enter 键位接线
4. 五态（重点：空会话引导态）

**示例代码**（建议规则）：

```ts
// suggestions.ts —— 纯规则零成本（GX12）
export function gitBasedSuggestions(history: string[]): string[] {
  // 新会话：git 历史前 3 条 -> "继续 <subject> 的工作" / "审查最近的改动"
  return history.slice(0, 3).map((s) => `继续 ${s} 的工作`);
}
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：来源规则、前 5 条消息窗口、Tab 采纳/Esc 关闭/Enter 发送
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 建议出现窗口（前 5 条消息）与来源规则正确
- [ ] Tab/Esc/Enter 键位可用
- [ ] 零 LLM 调用；五态通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX12 prompt suggestions (git-history based)

Claude-inspired zero-cost placeholder suggestions; Tab to accept, Esc to
dismiss, Enter to send. Rule-based only, no LLM calls.
```

---

## GX13 · OS 通知双档（回复到达 / 需要确认）

**借鉴来源**：Copilot 通知双档（调研 §4.3-13）；Claude OS 通知（§3.3-14）；Cursor 通知（§5.3-15）。
**优先级/工时**：P1 / 2–3d / 依赖：B12 + H12 完成 / **owner: frontend + backend 事件扩展**
**背景**：agent 后台运行时用户切到别的窗口，任务完成或需要审批时没有在场感。Copilot 的双档语义最清晰：①回复到达（含预览，点击聚焦会话）②**需要输入/确认时**（agent 停下来等用户）。off/非聚焦/始终 三档开关。

**涉及文件**：
- `frontend/desktop-app/src/main/notifier.ts`（新增：Electron Main 侧 Notification 封装）
- `frontend/desktop-app/src/features/notifications/NotificationSettings.tsx`（新增：三档设置）
- `frontend/desktop-app/src/features/notifications/NotificationSettings.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`event/agent_needs_input` 事件，new_event，符合原版 `event/agent_*` 命名空间）
- `appserver/needs_input.py`（新增：B12 事件流上的 needs_input 判定；产出 `event/agent_needs_input`）
- `tests/test_needs_input.py`（新增）

**规范限制**：
- 双档语义冻结：`response`（**回合/回复完成时**触发，含 80 字符预览——逐 token 流式事件不触发，防通知轰炸）/ `needs_input`（agent 停等审批/提问）；needs_input 优先级高于 response
- **事件名对照纪律（未完成前卡级 BLOCKED 且不进入排期，二选一流程）**：`B12 事件对照表` + Protocol probe 是本卡正式前置产物——列出：B12 实际事件名 / 本卡用途 / 通知档位 / 去重字段；**探针结论二选一**：①B12 已有完整「等待输入」事件 → 本卡只消费既有事件，**不新增 `event/agent_needs_input`**；②不存在 → 新增 `event/agent_needs_input`（new_event 协议变更单，冻结来源事件、去重字段、验收样例）。对照表与探针未完成前本卡**不进入排期与实现**，状态恒为 `BLOCKED_PREREQUISITE`：`NEEDS_INPUT_EVENTS` 与 `RESPONSE_EVENTS` 的事件名必须逐项核对主链 B12 schema 实际事件名（事件命名空间 `event/agent_*`；占位名 `approval/requested` 不得使用）；**对照完成并更新本卡判定表之前，本卡状态为 `BLOCKED_PREREQUISITE`**——示例中的事件名是占位，不得直接照抄；B12 中不存在的事件名不得使用，改用 B12 实际事件并更新判定表
- 三档开关冻结：off / 非聚焦时 / 始终（默认"非聚焦时"）
- `event/agent_needs_input` 事件由 appserver 在 B12 事件流上判定发出（agent 停等/审批请求时），前端不自行猜测
- 通知点击聚焦对应会话窗口
- 通知内容脱敏（不含密钥/完整工具输出，遵循主链 B13 crash 脱敏纪律）
- 事件去重：同一 `request_id` / 同一 turn 只通知一次

**开发步骤**：
1. 后端先行：`tests/test_needs_input.py`（red）→ `appserver/needs_input.py`（监听 B12 事件流，输出 needs_input 事件）→ 协议 new_event
2. 前端：`NotificationSettings.test.tsx`（red）→ Main 侧 notifier（Electron Notification API）→ 设置页三档
3. 接线：response 事件（消费 B12）/ needs_input 事件 → 通知 + 点击聚焦
4. 五态

**示例代码**（needs_input 判定）：

```python
# appserver/needs_input.py —— 需要确认通知判定（GX13）
# ⚠ 伪代码：事件名一律用 <B12_EVENT_NAME> 占位；实现前必须替换为 B12 事件对照表中的实际事件名
#（事件命名空间 event/agent_*；对照表未完成前本卡 BLOCKED_PREREQUISITE，不进入排期）
NEEDS_INPUT_EVENTS = {"<B12_EVENT_NAME>"}   # 审批请求/agent 提问等（对照表确定）
RESPONSE_EVENTS = {"<B12_EVENT_NAME>"}      # 回合/线程完成（对照表确定）


def classify_notify(event: dict) -> str | None:
    """双档冻结：needs_input 优先于 response；逐 token 流式事件返回 None。"""
    if event.get("type") in NEEDS_INPUT_EVENTS:
        return "needs_input"
    if event.get("type") in RESPONSE_EVENTS:
        return "response"
    return None
```

**验收命令**：
```powershell
python -m pytest tests/test_needs_input -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：双档判定、三档开关、点击聚焦、脱敏
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] B12 事件对照表 + Protocol probe 随 PR 提交（实际事件名逐项核对，无占位名）
- [ ] 按探针结论执行：B12 已有 → 只消费既有事件（零新增）；缺失 → `event/agent_needs_input` 变更单落地
- [ ] 双档通知 + 三档开关（默认非聚焦）
- [ ] 通知点击聚焦会话；内容脱敏
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX13 two-tier OS notifications (response/needs_input)

Copilot-inspired. Per protocol probe: consumes existing B12 wait-input
events when present, or adds event/agent_needs_input via change request
when absent. Click-to-focus, sanitized.
```

**P3 对接（追加，2026-08-12）**：通知机制由 **GX27 运行状态视觉**扩展——"会话停止/异常"触发通知（复用本卡双档通道 + 三档开关）；通知三端实现（Windows toast / macOS UserNotifications / Linux libnotify，Electron `new Notification()` 统一，Linux 缺失降级应用内横幅，2026-08-12 报告 §6.9）。

---

## GX14 · 模式选择器（Ask / Edit / Agent）

**借鉴来源**：Qoder Ask/Edit/Agent 三模式（调研 §9.3-1）；Devin Desktop 模式选择器（§6.3-1）；TRAE 权限模式（§8.3-4）。
**优先级/工时**：P1 / 3–4d 单人（双人并行 1.5-2d，含协议变更/生成类型/契约测试/联调）/ 依赖：H5 + B5 完成 / **owner: frontend + backend**
**背景**：主链会话只有一种"全能力 Agent 模式"。Qoder 证明同一会话流内切换 Ask（只问答）/ Edit（精确编辑不超预期）/ Agent（自主执行）让用户按问题难度匹配成本与自主度——对桌面工作台是刚需：查个问题不必启动完整 agent 回路。

**涉及文件**：
- `frontend/desktop-app/src/features/composer/ModeSelector.tsx`（新增：Ask/Edit/Agent 下拉）
- `frontend/desktop-app/src/features/composer/mode.ts`（新增：会话模式状态，发送时携带 capability 参数）
- `frontend/desktop-app/src/features/composer/ModeSelector.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`agent/invoke` 新增 optional field `capability`，new_optional_field）
- `appserver/tool_registry_capability.py`（新增：capability 白名单强制校验，工具注册层）
- `tests/test_invoke_capability.py`（新增：edit_only 会话拒绝 bash/delete/git 的 contract test）

**优先级/工时**：P1 / 3–4d（后端协议 1-2d + 前端 1-2d）/ 依赖：H5 + B5 完成（capability 后端校验） / **owner: frontend + backend**

**规范限制**：
- 三模式语义冻结：`ask`（只问答，**零工具**，capability=`no_tools`——注意与 B7 的 `read_only` 策略区分，read_only 允许读取类工具）/ `edit`（仅文件编辑工具，capability=`edit_only`）/ `agent`（全工具，capability=`full`，默认）
- **能力限制是后端安全边界，不是前端状态**：模式映射为 `agent/invoke` 请求新增 **optional field `capability`**（**枚举唯一冻结：`no_tools` / `edit_only` / `full`**，对应 ask/edit/agent 三模式），**由 appserver 在工具注册层强制校验**——`edit_only` 会话收到 `bash` / `delete` / `git` 工具调用**直接拒绝（协议错误，不进审批）**；`no_tools` 会话收到任何工具调用直接拒绝。能力是硬边界，审批（GX2 策略）不改变能力边界。前端只负责展示当前模式与发送参数，**前端状态不构成安全边界**
- **与 GX2 的权限预设组合关系（优先级矩阵，冻结）**：GX2 的 UI 预设（Ask/Auto/Full）与 GX14 的能力（ask/edit/agent）是**两个正交维度**——GX2 决定「动作到达边界时怎么审」（策略），GX14 决定「这个 turn 允许调什么工具」（能力）；组合生效规则：①能力是硬边界（edit 模式禁 bash/delete/git，后端强制，与预设无关）②策略是软边界（预设只改变审批通道）③冲突处理：`full_access` 策略不绕过能力硬边界（B7 full_access 与 GX14 能力校验叠加，取更严者）
- 走 GX2 的协议变更单流程扩展 `agent/invoke`（new_optional_field `capability`，request/response/错误码/contract test 在协议变更单中冻结）；若主链 `agent/invoke` 已有等价参数则复用并注明
- Edit 模式的写工具白名单冻结（后端校验）：`edit`/`write` 可、`bash`/`delete`/`git` 禁（直接拒绝（协议错误），不进审批（能力硬边界，与上方一致））
- 模式是**会话级**前端状态，切换不打断运行中 turn（下次发送生效）

> ⚠️ **2026-08-18 追加注记（三）· 本卡定义了与 GX2 的关系，但漏了与 `mode == "plan"` 的关系**
>
> 上面那条「与 GX2 的权限预设组合关系（优先级矩阵，冻结）」写得很好——两个正交维度、取更严者，这正是应该做的。**问题是它只覆盖了三分之二。**
>
> 系统里将有**三套独立的工具门**，全在后端，全会拒绝工具调用：
>
> 1. `mode == "plan"` 的只读门（`core/agent_v2.py:5097`，`PLAN_READONLY_TOOL_NAMES`）——**已实现，正在跑**
> 2. 本卡的 capability 白名单（`edit_only` 禁 `bash`/`delete`/`git`）
> 3. PHASE-K 极简 profile 的工具白名单
>
> 本卡定义了 1↔2 之外的那对（自己 ↔ GX2 审批策略），**但没定义 1↔2 本身**。具体会撞在这里：用户在 `plan` 模式（只读）+ `agent` 能力（全工具）下调 `write`，两道门一个拒一个放。**谁先执行？** `plan` 门返回的是 `[blocked: plan mode is read-only; write was not executed]`，本卡返回的是协议错误——同一个用户动作会因为门的执行顺序不同拿到两种完全不同的反馈，而两种都"合规"。
>
> **要求**：本卡实施前，把上面那张「优先级矩阵（冻结）」补上 `mode` 维度（至少覆盖 `plan × ask/edit/agent` 六格），错误信息取哪一条也要定死。**裁定权在本卡 owner**，[`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) DN7 只负责指出撞点，不代为决定。
>
> **另一处更要紧的：`capability` 挂在了错误的协议方法上。**
>
> 本卡把 `capability` 加为 **`agent/invoke` 的 optional field**。但 `agent/invoke` 是 **@ 提及某个子代理时的分派方法**（`useConversation.ts:780`，只在 `mention.agentIds` 分支里调用）；主对话走的是 **`session/prompt`**（同文件 `:809`）。
>
> 而本卡的 ModeSelector 装在 **composer** 上——那是主对话的输入框。**照本卡实施的结果是：用户在主对话切到 Edit 模式，`capability` 却只会跟着 @ 提及的子代理调用走，主对话这一轮压根不带这个字段。** 用户会看到「我明明选了 Edit，它还是跑了 bash」。
>
> `session/prompt` 已经在携带 `mode` 与 `permission_mode` 两个同类字段（`useConversation.ts:812-813`），**`capability` 属于同一族，应当加在那里**。若确实也需要覆盖 @ 提及路径，则两个方法都加，并在协议变更单里写明两处的优先级。
>
> 顺带一条命名提示：本卡的 Ask/Edit/Agent 叫「模式」，但系统里已经有 `mode`（`build`/`plan`/`compose`）、`permission_mode`（三档审批）、PHASE-K 的 profile（极简/标准）也常被叫「模式」——**四个东西同名**。本卡不必改名（它已冻结），但新文档一律避开这个词。

**开发步骤**：
1. 后端先行（协议）：`tests/test_invoke_capability.py`（red）→ `agent/invoke` 增加 optional field `capability`（默认 `full`，向后兼容）→ `appserver/tool_registry_capability.py` 在工具注册层校验（`edit_only` 会话收到 bash/delete/git 工具调用返回协议错误，走审计）→ contract test
2. 前端：`ModeSelector.test.tsx`（red）→ `mode.ts` + 组件（输入框左上角下拉 + 当前模式徽标）
3. 接线：发送时携带 `capability` 参数 → 主链 invoke；会话级模式状态
4. 五态

**示例代码**（模式→invoke 映射；能力限制由后端强制校验，前端仅展示）：

```ts
// mode.ts —— 三模式语义冻结（GX14）
export const MODE_TO_CAPABILITY: Record<SessionMode, string> = {
  ask: 'no_tools',       // 只问答（零工具；与 B7 read_only 策略区分）
  edit: 'edit_only',     // 仅编辑类工具（后端白名单校验）
  agent: 'full',         // 全工具（默认）
};
// 协议枚举唯一冻结：no_tools / edit_only / full（协议变更单 + schema + 生成类型一致）
// 发送：await invoke({ threadId, text, capability: MODE_TO_CAPABILITY[mode] })
// 安全边界在后端 tool_registry_capability.py，前端状态不构成安全边界
```

**验收命令**：
```powershell
python -m pytest tests/test_invoke_capability -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三模式映射、后端 capability 白名单强制校验（edit_only 拒绝 bash/delete/git）、
#       schema 生成/contract test、切换不打断、默认 agent
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 三模式映射正确（capability 枚举 no_tools/edit_only/full 在 schema/生成类型/契约测试中一致）
- [ ] Edit 模式工具白名单生效（bash/delete/git 禁）
- [ ] 切换不打断运行中 turn
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX14 Ask/Edit/Agent mode selector

Qoder-inspired session modes mapping to invoke capability param.
Edit mode tool allowlist freezes edit/write only. Default agent.
```

---

# P2 批（GX15–GX18）

## GX15 · Design Mode 元素选择（预览标注）

**借鉴来源**：v0 Design Mode（调研 §11.3-4/5）；Cursor Design Mode（§5.3-16）；TRAE 浏览器工具（§8.3 附）。
**优先级/工时**：P2 / 4–5d / 依赖：GX17 完成 / **owner: frontend**
**背景**：桌面工作台的"运行预览"场景（Web 应用验证）下，用户想"指着元素说改这里"。v0 的 Design Mode：预览叠加 hover 高亮 → 点击选中元素 → 面板微调或自然语言指令（自动附带选中元素截图）。是所见即所得式前端迭代的标准件。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/designmode/DesignModeOverlay.tsx`（新增：预览叠加层，hover 高亮/选区/Inspect 切换）
- `frontend/desktop-app/src/features/designmode/ElementInspector.tsx`（新增：选中元素面板：属性微调/pending 编辑）
- `frontend/desktop-app/src/features/designmode/designmode.screenshot.ts`（新增：元素截图附带）
- `frontend/desktop-app/src/features/designmode/DesignModeOverlay.test.tsx`（新增）

**规范限制**：
- **显式前置（开工探针）**：主链图片附件协议必须真实存在（`agent/invoke` 或消息附件方法支持图片附件）——开工前先 `Test-Path`/协议核对；缺失时**整卡直接输出 `BLOCKED_PREREQUISITE`，不进入部分实现**
- 仅在**预览面板**内生效（Cmd+D 切换），不污染正常操作；Esc 取消选择（v0 Inspect 语义）
- 选中元素 → 自然语言指令 = 消息草稿 + 自动附带选中元素截图（走主链图片附件协议）
- 属性微调走 pending 编辑集（Undo/Redo/Reset、Before/After 对比，v0 §11.3-5），Apply 才提交
- 截图与元素信息不进 crash/日志（遵循主链脱敏纪律）
- 兼容性：Tailwind 项目时面板呈现 Tailwind 兼容值（v0 Tailwind-aware，§11.3-7）

**开发步骤**：
1. `DesignModeOverlay.test.tsx`（red）
2. 叠加层（preview iframe/容器的 hover 高亮 + 点击选中 + Inspect 切换）
3. `ElementInspector`（属性面板 + pending 编辑集 + Before/After）
4. 截图附带（捕获元素区域 → 消息草稿附件）
5. 五态

**示例代码**（Inspect 切换语义）：

```ts
// designmode.ts —— Inspect 切换冻结（GX15）
export type InspectState = 'off' | 'selecting' | 'adjusting';
// off: 正常操作预览；selecting: Cmd+D 后 hover 高亮点击选中；
// adjusting: 属性面板调整（pending 编辑集，Apply 才提交）
export function toggleInspect(s: InspectState): InspectState {
  return s === 'off' ? 'selecting' : 'off';  // Esc 从 adjusting 回 selecting，再 Esc 关
}
```

**验收命令**：
```powershell
# 开工探针（图片附件协议存在性）——缺失时整卡 BLOCKED_PREREQUISITE，不进入实现
python -c "import json,pathlib; s=json.loads(pathlib.Path('protocol/schema.json').read_text(encoding='utf-8')); methods=s.get('methods',{}); hit=[k for k,v in methods.items() if 'attachment' in json.dumps(v)]; print(hit)"  # 多路径探针：遍历全部方法找图片附件能力（agent/invoke 或独立附件方法）；输出实际方法名+字段路径；无命中 → BLOCKED_PREREQUISITE
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：Inspect 三态、选区截图附带、pending 编辑集 Undo/Redo/Apply、Tailwind 值
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] Cmd+D 切换 Inspect；Esc 逐级退出
- [ ] 选区截图附带到消息草稿
- [ ] pending 编辑集（Undo/Redo/Reset/Before-After）Apply 才提交
- [ ] 图片附件协议缺失时输出 BLOCKED_PREREQUISITE（不 mock）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX15 design mode element selection on preview

v0/Cursor-inspired. Inspect overlay, element screenshot attachments,
pending edit set with undo/redo and before/after. Blocked if image
attachment protocol missing (BLOCKED_PREREQUISITE, no mock).
```

---

## GX16 · 侧聊 /side（不污染主线程的追问）

**借鉴来源**：Codex /side（调研 §2.3-11）；Claude side chat /btw（§3.3-8）；Cursor /side（§5.3-15）。
**优先级/工时**：P2 / 2–3d / 依赖：GX8 完成 / **owner: frontend + backend 协议扩展**
**背景**：agent 干着长任务，用户想追问"这个方案有风险吗"又不想污染主转录。Codex/Claude/Cursor 三家都有 side chat：从当前会话派生临时对话（只读继承上下文），完成后回主 chat，主转录不变。且 side chat 复用缓存、成本极低。

**涉及文件**：
- `frontend/desktop-app/src/features/sidechat/SideChat.tsx`（新增：侧聊窗口）
- `frontend/desktop-app/src/features/sidechat/SideChat.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`thread/side_chat/create`，new_method；`thread/side_chat/close`）
- `appserver/handlers/side_chat.py`（新增：只读上下文派生会话）
- `tests/test_side_chat.py`（新增）

**规范限制**：
- 侧聊语义冻结：`thread/side_chat/create`（`{thread_id}`）→ 派生临时会话，**只读继承**主会话上下文（历史消息投影，不复制），独立 message 流
- 侧聊完成的结论可 `promote` 回主会话（追加为一条 assistant 摘要消息，需用户确认）；默认不写回
- 侧聊的生命周期绑定主会话（主会话归档/删除 → 侧聊关闭）
- 复用主链缓存（上下文前缀一致 → 缓存命中），成本不计入主会话 usage（独立计数，GX7 的 event/agent_usage 按会话隔离）

**开发步骤**：
1. 后端先行：`tests/test_side_chat.py`（red）→ 协议两方法 → `appserver/handlers/side_chat.py`
2. 前端：`SideChat.test.tsx`（red）→ 侧聊窗口（浮层 + 输入 + 结论 promote 按钮）
3. 接线：消息 hover 菜单"在侧聊中追问"入口
4. 五态

**示例代码**（侧聊派生语义）：

```python
# appserver/handlers/side_chat.py —— 只读派生（GX16）
async def handle_side_chat_create(thread_id: str) -> dict:
    """侧聊 = 只读上下文投影 + 独立消息流（Codex /side 语义）。"""
    parent = await ThreadService.get(thread_id)
    side = await ThreadService.create_side_session(
        parent_id=thread_id,
        context_projection=await MessageService.project_context(parent.id),  # 只读投影
        budget_tag="side",          # 独立 usage 计数（GX7 会话隔离）
    )
    return {"side_thread_id": side.id, "context_tokens": side.context_tokens}
```

**验收命令**：
```powershell
python -m pytest tests/test_side_chat -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：只读派生、独立消息流/usage、promote 需确认、生命周期绑定
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `thread/side_chat/create|close` 协议落地
- [ ] 只读上下文投影（不复制）；独立 usage 计数
- [ ] promote 需确认；默认不写回主会话
- [ ] 主会话归档/删除联动关闭侧聊
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX16 side chat (read-only derived session)

Codex/Claude/Cursor-inspired. thread/side_chat/create projects parent
context read-only, independent message stream and usage accounting;
promote back requires confirmation.
```

---

## GX17 · 版本卡（每次变更 = 新版本，可 diff/回退）

**借鉴来源**：v0 版本化迭代（调研 §11.3-2）；Replit Ready 审查抽屉（§10.3-4）。
**优先级/工时**：P2 / 2–3d / 依赖：B8 + H9 + **GX4** 完成（回退按钮跳转 GX4 rewind，GX4 未合入前该按钮仅展示禁用） / **owner: frontend**
**背景**：v0 的"每次生成/Apply 产生新版本，可 diff、可回退"是网页生成式 agent 的核心心智；映射到桌面工作台 = **每次 agent 回合的变更集合固化为"版本卡"**（版本号 + diff 摘要 + 回退按钮），挂在 Thread 时间线上，与审批/review 天然结合。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/versions/VersionCard.tsx`（新增：版本卡）
- `frontend/desktop-app/src/features/versions/version.timeline.ts`（新增：版本时间线投影）
- `frontend/desktop-app/src/features/versions/VersionCard.test.tsx`（新增）

**规范限制**：
- 版本语义冻结：**版本粒度以探针结论为准**——B8 若确认 turn↔checkpoint 关联（含每 turn 自动打点语义）则「每 turn 一版」；未确认则改为「每个有明确 checkpoint/turn 关联的变更点一版」（协议变更单冻结自动打点语义后才能按 turn 版本化）；版本号单调递增
- **turn↔checkpoint 关联核对**：实现前核对 B8 schema 是否存在 turn 与 checkpoint 的关联字段——存在则直接投影；**不存在则走协议变更单（new_optional_field `turn_id` 挂 checkpoint）或依赖 GX4 的新模型**，并把"协议零变更"改为以核对结论为准
- 版本卡显示：版本号 / 变更文件数 / diff 摘要（+12 -1 风格，Claude §3.3-7）/ 回退按钮（跳转 GX4 的 rewind 流程）
- 回退不删除版本（版本是只读历史，回退 = 新状态 + 保留历史版本）——借鉴 v0 可追溯
- 不新建后端数据：版本卡从 B8 的 checkpoint/diff 记录投影（checkpoint 已含 diff hash；字段名以 B8 实际 schema 为准）

**开发步骤**：
1. `VersionCard.test.tsx`（red）
2. `version.timeline.ts`（从 B8 数据投影版本列表）
3. `VersionCard`（渲染 + 回退入口 → GX4 rewind）
4. 时间线接入 Thread 视图（版本节点与消息流交错）
5. 五态

**示例代码**（版本投影）：

```ts
// version.timeline.ts —— 版本投影（GX17，只读消费 B8；字段以探针结论为准）
// ⚠ 示例占位：c.seq / c.files / c.revertible 等字段名与"每 turn 一版"语义
//   以 Protocol probe 核对 B8 实际 schema 后的结论为准（见规范限制）
export function selectVersions(s: RootState): VersionCard[] {
  return Object.values(s.review.checkpoints).map((c) => ({
    id: c.id,
    version: c.seq,                 // 单调递增（探针确认的关联字段）
    fileCount: c.files.length,      // 探针确认的统计字段
    diffStats: summarize(c.files),  // "+12 -1" 风格
    canRevert: c.revertible,        // 探针确认的回退能力位
  }));
}
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：版本号单调、diff 摘要、回退跳转 rewind、历史保留
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 版本卡按探针结论投影（turn 关联存在 → 每 turn 一版；不存在 → 每个明确 checkpoint/变更点一版；需新增 turn_id 时先完成 GX17-PROTO）
- [ ] diff 摘要（+N -N）+ 回退入口（跳 GX4 rewind）
- [ ] 回退不删除历史版本
- [ ] turn↔checkpoint 关联核对结论写入 PR（B8 已有 → 纯投影；缺失 → 协议变更单或依赖 GX4 关联字段）；五态通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX17 version cards

v0-inspired. Per probe result: turn-aligned or checkpoint-aligned version
cards (monotonic seq, diff stats, revert entry to GX4 rewind). Read-only
projection of B8.
```

---

## GX18 · Follow-up 任务推荐

**借鉴来源**：Replit Follow-up tasks（调研 §10.3-11）；Claude Task chips（§3.3-11）。
**优先级/工时**：P2 / 2–3d / 依赖：GX1 完成 / **owner: frontend + backend 事件扩展**
**背景**：agent 完成主任务后发现"范围外但值得做"的事（如测试缺失、遗留 TODO、潜在重构），Replit 在任务完成后推荐 follow-up 任务（可批量接受）；Claude 以 task chips 出现在对话中，点击即新会话启动。主动但不抢。

**涉及文件**：
- `frontend/desktop-app/src/features/followup/FollowUpSuggestions.tsx`（新增：完成后的建议卡）
- `frontend/desktop-app/src/features/followup/FollowUpSuggestions.test.tsx`（新增）
- `appserver/followup_scanner.py`（新增：turn 完成事件的规则扫描器——纯规则，不调 LLM）
- `tests/test_followup_scanner.py`（新增）

**规范限制**：
- 扫描器**纯规则零 LLM**（成本为零）：turn 完成事件 + 工作区扫描（未覆盖测试文件 / 遗留 TODO / 未提交变更）→ 最多 3 条建议
- 建议卡动作冻结：`Accept`（新建 Thread，建议文本为首条消息）/ `Dismiss` / `Ignore all`；批量接受上限 3
- 建议卡只在主任务完成后出现一次（同一 turn 不重复推荐）
- 建议不进主转录（独立浮层，点击接受才创建 Thread）——Claude Task chips 语义
- 新 Thread 继承 workspace 绑定（B5 语义），不自动执行

**开发步骤**：
1. 后端先行：`tests/test_followup_scanner.py`（red）→ `appserver/followup_scanner.py`（规则扫描 + 上限 3 + 去重）
2. 前端：`FollowUpSuggestions.test.tsx`（red）→ 建议卡（Accept/Dismiss/Ignore all）→ 接受后新建 Thread
3. 接线：消费 B12 的 turn 完成事件
4. 五态

**示例代码**（规则扫描器）：

```python
# appserver/followup_scanner.py —— 纯规则零 LLM（GX18）
RULES = [
    ("missing_tests", lambda ws: ws.untracked_py_files_without_test()),
    ("leftover_todo", lambda ws: ws.find_todo_markers(limit=5)),
    ("uncommitted", lambda ws: ws.git_uncommitted()),
]


def scan(ws) -> list[str]:
    out = []
    for name, fn in RULES:
        if len(out) >= 3:                      # 上限 3 冻结
            break
        for item in fn(ws) or []:
            out.append(f"{name}: {item}")
    return out[:3]
```

**验收命令**：
```powershell
python -m pytest tests/test_followup_scanner -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三条规则、上限 3、去重、一次推荐、Accept 建 Thread
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 规则扫描器落地（零 LLM、上限 3、去重）
- [ ] 建议卡在 turn 完成后出现一次；Accept 新建 Thread
- [ ] 建议不进主转录；新 Thread 继承 workspace
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX18 follow-up task suggestions

Replit/Claude-inspired. Rule-based scanner (zero LLM, max 3, deduped)
on turn completion; Accept creates a new thread inheriting workspace.
```

---

# P3 批（GX19–GX28 · Codex 对齐批）

> **批性质**：本批为 **P3 · Codex 对齐批**（新增批次），追加于 P2（GX15–GX18）之后。立项依据：`research/2026-08-12-agent-native-computer-use-research.md`（Agent-Native Computer Use + GUI Codex 对齐 + CLI-Anything 混合集成）。前端基建依赖 H14–H19（PHASE-G-FRONTEND.md 追加卡），后端依赖 B14–B18（PHASE-G-BACKEND.md 追加卡）。**主链出口门槛与 P0/P1/P2 批次不变**；本批出口定义见 §3。
> **跨平台（通用约束，所有 P3 卡生效）**：Windows/Linux/macOS 三端适配——系统 API（通知/语言/安全存储）按报告 §6.9 平台差异表实现；打包 smoke 覆盖 macOS/Linux 构建目标；禁止仅 Windows 可用依赖（直接 subprocess 调 python/pip，规避 CLI-Anything 的 cygpath 已知坑）。

## GX19 · 多 Agent 活动可视化

**借鉴来源**：DeerFlow SSE + Last-Event-ID（调研报告 §3.5）；Vibe-Trading events.jsonl + live callback（8 项目报告）；多 Agent 专家团设计（2026-08-11 报告 C5/GX19 立项）。
**优先级/工时**：P1 / 3–4d / 依赖：PHASE-F F12（委派树）+ PHASE-E E4（AgentEvent 事件域）+ H18（前端契约预留）/ **owner: frontend + backend 协议扩展**
**背景**：多 Agent 专家团（F）的"看得见才算真"判据（2026-08-11 报告 FM3 可视化证据）——委派树、成员独立状态、团长中转消息流、预算条必须在前端呈现；E/F 未实施前本卡输出 BLOCKED_PREREQUISITE（禁止 mock 假协议）。

**涉及文件**：
- `frontend/desktop-app/src/features/team/TeamView.tsx`（新增：委派树 + 成员状态灯 + 消息流 + 预算条；H18 挂载点填充）
- `frontend/desktop-app/src/lib/agentEvents.ts`（H18 骨架实现：E4 事件投影）
- `protocol/schema.json` + `protocol/*.py`（E4 `agent_*` 事件域——**E 阶段合入后消费，本卡不新增字段**）
- `tests/test_team_view.tsx`（新增）

> ### 追加注记（2026-08-18）：PHASE-E 前置已复核**通过**，本卡的 E 侧门控可以放行
>
> 下方门控说「PHASE-E/F 未合入 → BLOCKED」。为本卡实测了 E 侧：**E3 的 `appserver/agent_runtime.py`（19,100 B，`class AgentRuntime`）与 E4 的 `AgentEvent` / `event/agent` 均在位**，后者覆盖 `protocol/notifications.py`、`protocol/schema.json` 与 `frontend/protocol-client/src/generated/types.ts`（TS 生成物也已同步），E 阶段 165 个契约测试全绿。
>
> 所以本卡「涉及文件」里那句「E 阶段合入后消费」的前提**成立**，`agent_*` 事件域可以直接消费。
>
> **开工前仍建议跑一次**（30 秒，比读 PHASE-E 的勾可靠）：
> ```powershell
> cd D:\agent-demo\RxyCode\RxyCode1_1_0
> Select-String -Path protocol\notifications.py,protocol\schema.json,frontend\protocol-client\src\generated\types.ts -Pattern 'AgentEvent|event/agent' -List
> # 三处全中 = E4 就位。零命中才输出 BLOCKED_PREREQUISITE
> ```
>
> **F 侧门控不受本注记影响**，仍需自行确认 F12（委派树）状态。
>
> **本注记是一次更正。** 同日早些时候此处曾贴出相反结论（称 E4 全仓零命中、门控会错误放行），那是**基于一次过时观测**的误判，已撤回；原委见 [`PHASE-G-CONFLICT-AUDIT.md`](./PHASE-G-CONFLICT-AUDIT.md) 的 X8。

**规范限制**：
- **门控**：PHASE-E/F 未合入 → 本卡 BLOCKED_PREREQUISITE（不 mock、不显示入口）
- 委派树为**真树**（F12 数据消费），禁止前端自造层级；成员状态灯 = E4 AgentEvent 投影（agent_started/tool/progress/done/paused/cancelled/budget_exceeded）
- 预算条 = E3 每 agent 预算池投影（只显示，不计算）；中转消息流 = 团长转发的 ConsultRequest 投影（F7）
- 视觉与 §5.2 铁律一致（纯投影不改变业务语义）；五态覆盖

**开发步骤**：
1. 后端先行：E4 事件域 + F12 委派树协议（E/F 卡范围，本卡等待）
2. 前端：`agentEvents.ts` reducer（H18）→ `TeamView.tsx`（树/状态灯/消息流/预算条）→ `tests/test_team_view.tsx`
3. 接线：capability 门控开关（F10 `settings.agents.enabled`）
4. 五态

**示例代码**（AgentEvent 投影，消费侧）：

```ts
// frontend/desktop-app/src/lib/agentEvents.ts —— E4 AgentEvent 投影（GX19）
type AgentEvent = { session_id: string; agent_id: string; run_id: string; method: AgentMethod; seq: number };
type AgentMethod =
  | "agent_started" | "tool" | "progress" | "done"
  | "paused" | "cancelled" | "budget_exceeded" | "denied";

export const projectAgentState = (events: AgentEvent[]) =>
  events.reduce<Record<string, AgentStatus>>((acc, e) => {
    acc[e.agent_id] = eventToStatus(e.method);   // 纯投影，不产生业务状态
    return acc;
  }, {});
```

**验收命令**：
```powershell
python -m pytest tests/test_protocol -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：E/F 未合入 → BLOCKED_PREREQUISITE（零 mock 路径）；合入后：树/状态灯/预算条随事件流实时投影
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] E/F 合入后委派树/成员状态/预算条随事件流投影
- [ ] capability 门控生效（未合入零痕迹，无 mock）
- [ ] 纯投影验证（前端不产生业务状态）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX19 multi-agent activity visualization

DeerFlow/MAST-informed. Delegation tree + member status + budget bar
projected from E4 AgentEvent stream; capability-gated, no mock paths.
```

---

## GX20 · 会话三分类 + 折叠交互（置顶 / 项目 / 最近）

**借鉴来源**：Codex 会话侧栏（布局/折叠/hover 直接照搬，亮度取样为准）；2026-08-12 报告 §6.1–6.2 规格。
**优先级/工时**：P0 / 3–4d / 依赖：B5（Thread 元数据）+ H15（会话栏重构基建）+ GX8（pin 语义）/ **owner: frontend + backend 协议扩展**
**背景**：会话栏按 **置顶 / 项目 / 最近** 三分类（自上而下）组织：置顶 = pin 会话（固定分类顶部）；项目 = 项目目录树（每项目展开其会话）；最近 = 未归类未置顶会话。折叠/展开与 hover 高亮对齐 Codex（用户确认规格：收起时标题右侧 `>` 符号，与标题间距 4px）。

**涉及文件**：
- `frontend/desktop-app/src/components/SessionList.tsx`（H15 重构产物上实现分类区）
- `frontend/desktop-app/src/lib/sessionCategories.ts`（分类归属规则；H15 已建）
- `protocol/schema.json`（B5 thread 元数据 pin/`deleted_at` 消费——探针确认已有字段则直接复用）
- `tests/test_session_categories.tsx`（新增）

**规范限制**：
- **分类归属规则冻结**：置顶（pin）→ 项目（workspace 绑定）→ 最近（其余）；删除会话 → 回收站投影（B17）
- **折叠交互冻结**：分类标题点击折叠/展开；收起态标题右侧 `>`（展开态 `v`/向下），间距 4px；折叠状态本地持久化（localStorage），不影响后端
- **hover 亮度**：浅色 ≈ rgba(0,0,0,0.06)、深色 ≈ rgba(255,255,255,0.08)，**以 Codex 实机取样为准**（验收含截图对照）
- 分类标题次要灰字体（design token secondary text）；状态色语义不改（沿用现有约定）
- 纯前端投影（不改 B5 数据）；pin 语义复用 GX8（本卡不新增协议方法；若 B5 缺 pin/deleted 字段 → GXn-PROTO 登记 new_optional_field）

**开发步骤**：
1. 后端先行：探针 B5 元数据（pin/deleted_at 是否存在）→ 缺失则 GXn-PROTO 登记
2. 前端：`sessionCategories.ts` 分类规则（red）→ SessionList 三分类区 + 折叠 → hover 取样落地
3. 接线：GX8 pin 操作 → 置顶分类刷新；B17 软删除 → 回收站投影
4. 五态 + 截图对照

**示例代码**（分类归属规则）：

```ts
// frontend/desktop-app/src/lib/sessionCategories.ts —— 三分类归属（GX20）
export type SessionCategory = "pinned" | "project" | "recent";

export function categorize(thread: ThreadMeta, projectId: string | null): SessionCategory {
  if (thread.pinned) return "pinned";                       // 置顶优先
  if (projectId && thread.workspaceId) return "project";    // 项目归属
  return "recent";                                          // 最近兜底
}
```

**验收命令**：
```powershell
python -m pytest tests/test_threads -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三分类归属、折叠/`>` 方向、hover 取样值（截图对照）、pin 进置顶、删除进回收站投影
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 三分类归属规则生效（置顶/项目/最近）
- [ ] 折叠/展开 + `>` 符号 + 4px 间距 + 状态持久化
- [ ] hover 亮度取样值落地（截图对照记录）
- [ ] pin/软删除联动（B5/B17 探针结论记录）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX20 session sidebar categories (pinned/project/recent)

Codex-inspired. Three-category sidebar with fold/unfold chevron and
hover highlight sampled from Codex; pin and trash projection wired.
```

---

## GX21 · 回收站 UI

**借鉴来源**：Codex 会话删除映射（删映射不删文件）；用户规格（垃圾桶图标入口、点击恢复、清空弹窗确认风险操作）。
**优先级/工时**：P1 / 2–3d / 依赖：B17（回收站后端）+ H15（三分类投影）/ **owner: frontend**
**背景**：会话删除 = 软删除映射（数据保留），回收站集中管理：恢复或清空。清空为**风险操作**（永久删除会话记录 + 关联文件），必须弹窗确认。

**涉及文件**：
- `frontend/desktop-app/src/features/settings/TrashSection.tsx`（新增：回收站分区——设置页第 1 分区，H16 挂载点）
- `frontend/desktop-app/src/components/TrashItem.tsx`（新增：条目 + 恢复按钮）
- `frontend/desktop-app/src/components/PurgeConfirmDialog.tsx`（新增：清空弹窗）
- `tests/test_trash_section.tsx`（新增）

**规范限制**：
- 列表：名称/删除时间/原归属分类；每条"恢复"→ 回到原分类（或最近）
- **清空弹窗冻结**：明示"将永久删除会话记录与关联文件"，确认按钮二次确认（默认聚焦取消）；后端 `thread/purge` 请求必须带 `confirm_purge`（B17 拒绝未确认请求）
- 恢复/清空走 B17 协议（`thread/restore`/`thread/purge`）；B17 未合入 → BLOCKED_PREREQUISITE
- 回收站数据消费 B17 `thread/list_deleted`；索引同步排除（GX8 纪律）
- 跨平台：无平台特有依赖（文件删除由后端 purge 处理）

**开发步骤**：
1. 后端先行：B17（本卡等待）
2. 前端：`TrashSection.test.tsx`（red）→ 列表 + 恢复 → PurgeConfirmDialog（弹窗/二次确认）
3. 接线：B17 协议消费；恢复后分类刷新（GX20 联动）
4. 五态

**示例代码**（清空确认弹窗逻辑）：

```tsx
// frontend/desktop-app/src/components/PurgeConfirmDialog.tsx —— 清空弹窗（GX21）
const [confirmOpen, setConfirmOpen] = useState(false);
const [confirmText, setConfirmText] = useState("");

// 风险操作：明示永久删除 + 二次确认，未确认后端拒绝（B17 confirm_purge）
const purge = () =>
  rpc.request("thread/purge", { confirm_purge: true })
     .then(closeDialog)
     .catch((e) => setError(e));   // 后端拒绝路径必须可见
```

**验收命令**：
```powershell
python -m pytest tests/test_trash -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：恢复回原分类、清空弹窗文案/二次确认、未确认请求后端拒绝、索引同步排除
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 回收站列表（名称/删除时间/归属）渲染
- [ ] 恢复动作回正确分类
- [ ] 清空弹窗 + 二次确认（默认取消）+ `confirm_purge` 传递
- [ ] 后端拒绝路径可见（无静默失败）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX21 trash UI with purge confirmation

Soft-delete mapping restore + purge confirm dialog (risk operation,
double confirm, confirm_purge flag); backend rejects unconfirmed purge.
```

---

## GX22 · i18n 语言本地化（文案清单与切换生效）

**借鉴来源**：用户规格（2026-08-12 报告 §6.5）：系统语言初始、常规设置可改、只改 GUI 文案不改对话回复；首批 zh-CN + en。
**优先级/工时**：P1 / 2–3d / 依赖：H14（i18n 基建）/ **owner: frontend**
**背景**：H14 提供机制（locale JSON、`t()`、系统语言、持久化），本卡落实文案清单映射与切换生效验证——"技能→Skills、设置→Settings"式映射全量覆盖。

**涉及文件**：
- `frontend/desktop-app/src/i18n/locales/zh-CN.json` / `en.json`（H14 已建，本卡填充/核对）
- `frontend/desktop-app/src/i18n/wordlist.md`（新增：文案映射清单——中英对照审查记录）
- `tests/test_i18n_coverage.tsx`（新增：覆盖率检查）

**规范限制**：
- **范围冻结**：GUI 静态文案全部入 i18n（侧栏/设置/菜单/状态/按钮/提示/错误文案）；**对话内容、工具输出、模型回复语言不干预**
- 映射清单按组件逐一核对（全量清单见 wordlist.md，验收抽查 ≥ 20 处关键文案）
- 语言切换即时生效 + 重启保持（H14 持久化）；未知 locale 回退默认
- 长文案窄窗不溢出（中文→英文长度变化）；占位符/插值变量不硬编码

**开发步骤**：
1. 核对 H14 基建（`t()` 与 locale 文件存在性）
2. 全量文案清单（wordlist.md）→ 组件逐个迁移（未迁移组件列出清单）
3. `test_i18n_coverage`（覆盖率：静态文案无漏词）
4. 五态 + 切换截图对照

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：切换语言全量生效（≥20 处抽查）、对话回复语言不变、重启保持、窄窗不溢出
```

**完成判据**：
- [ ] wordlist.md 全量映射清单完成（中英对照）
- [ ] 全部静态文案经 `t()` 取词（覆盖率检查通过）
- [ ] 切换生效 + 重启保持 + 未知 locale 回退
- [ ] 对话回复语言不变验证用例
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX22 i18n wordlist and locale switching

zh-CN + en. UI copy only; conversation language untouched. Coverage
test guards missing keys; narrow-window overflow covered.
```

---

## GX23 · 定时任务 UI

**借鉴来源**：用户规格（2026-08-12 报告 §6.7）：任务列表/触发规则/动作/启停/编辑/删除；间隔 + 指定时间触发。
**优先级/工时**：P2 / 2–3d / 依赖：B16（定时任务调度器）/ **owner: frontend + backend 协议消费**
**背景**：后端 B16 提供应用层调度（asyncio，三端一致），前端提供管理界面：创建/编辑/启停/删除定时任务。

**涉及文件**：
- `frontend/desktop-app/src/features/settings/ScheduleSection.tsx`（新增：设置页分区或独立面板）
- `frontend/desktop-app/src/components/ScheduleForm.tsx`（新增：触发规则 + 动作表单）
- `tests/test_schedule_section.tsx`（新增）

**规范限制**：
- 表单字段：名称、触发规则（间隔 N 分钟/小时/天 或 指定时间）、动作（运行指定会话/命令/技能——选择器复用现有 Thread/技能数据源）
- 列表：启停开关、下次触发预览（B16 返回）、编辑/删除
- 消费 `schedule/*` 协议（B16，GXn-PROTO 登记）；B16 未合入 → BLOCKED_PREREQUISITE
- 执行中任务的状态展示（复用 B12 长任务语义）；删除/停用确认（非风险级，普通确认即可）

**开发步骤**：
1. 后端先行：B16（本卡等待）
2. 前端：`ScheduleForm.test.tsx`（red）→ 表单 + 列表 + 启停
3. 接线：`schedule/*` 协议消费；下次触发预览
4. 五态

**验收命令**：
```powershell
python -m pytest tests/test_schedule -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：两种触发规则、启停、编辑、删除、下次触发预览
```

**完成判据**：
- [ ] 创建/编辑表单（间隔 + 指定时间 + 动作选择器）
- [ ] 列表 + 启停 + 下次触发预览
- [ ] 删除/停用确认
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX23 scheduled tasks UI

Interval and fixed-time triggers; run session/command/skill actions;
next-run preview from B16; BLOCKED until scheduler lands.
```

---

## GX24 · 插件生态（市场 + 管理）

**借鉴来源**：Codex plugins 形态 + CLI-Anything SKILL.md 机制（2026-08-12 报告 §6.6）。
**优先级/工时**：P2 / 3–4d / 依赖：B18（插件注册与市场后端）/ **owner: frontend + backend 协议消费**
**背景**：插件 = 命令 + 技能 + 工具/MCP 配置的组合包（manifest 声明）。市场页浏览/安装/卸载/启停；与 G13 能力面板（已安装能力统一入口）、设置页技能/MCP 管理（细粒度控制）三者并存不冲突。

**涉及文件**：
- `frontend/desktop-app/src/features/settings/PluginSection.tsx`（新增：已装插件管理）
- `frontend/desktop-app/src/features/market/MarketPage.tsx`（新增：市场浏览/搜索/安装）
- `tests/test_plugin_section.tsx`（新增）

**规范限制**：
- 市场数据源：B18（本地目录 + 远程 registry）；安装 = 后端校验 + 注册（manifest 校验失败显示原因）
- 已装列表：名称/版本/来源/启停开关/卸载（卸载确认：保留用户配置语义）
- 插件声明的能力（技能/工具/MCP）安装后出现在 G13 能力面板——本卡不重复渲染，只显示"包含能力"摘要
- 消费 `plugin/*` 协议（B18，GXn-PROTO 登记）；B18 未合入 → BLOCKED_PREREQUISITE

**开发步骤**：
1. 后端先行：B18（本卡等待）
2. 前端：`MarketPage.test.tsx`（red）→ 市场列表/搜索/安装 → `PluginSection`（启停/卸载）
3. 接线：`plugin/*` 消费 + G13 面板联动验证
4. 五态

**验收命令**：
```powershell
python -m pytest tests/test_plugin -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：市场浏览/搜索/安装、manifest 失败原因展示、启停、卸载确认、G13 联动
```

**完成判据**：
- [ ] 市场页（浏览/搜索/安装 + 失败原因展示）
- [ ] 已装管理（启停/卸载确认/包含能力摘要）
- [ ] G13 能力面板联动验证
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX24 plugin market and management

Manifest-driven plugins (commands + skills + tool/MCP configs);
market browse/install with failure reasons; G13 capability panel sync.
```

---

## GX25 · CLI-Anything 工具接入 + 预览画廊

**借鉴来源**：CLI-Anything（Apache-2.0）预览栈协议 + 混合集成决策（2026-08-12 报告 §3.4/§5）。
**优先级/工时**：P1 / 3–4d / 依赖：B14（CLI 桥接器）+ H19（工具面板与画廊基建）/ **owner: frontend + backend 协议消费**
**背景**：消费 B14 的 `cli:*` 工具（来源标签 内置/CLI-Hub/自生成），画廊渲染 CLI-Anything 预览 bundle（hero/gallery/video/JSON）——软件控制"软联系"的 GUI 呈现面。

> ⚠️ **2026-08-18 追加注记（二）· 本卡没问题，但它依赖的 B14 有一处会击穿缓存基线**
>
> **先说结论：本卡一个字都不用改。** 表单化调用（`cli/list` + `cli/<tool>/schema` + `cli/launch`）本来就是按需拉 schema，这是对的。
>
> 问题在 **B14**（`PHASE-G-BACKEND.md:493`）：「CLI 工具以 `cli:<软件名>` 前缀**注册进 `tools/registry.py`**」。那个 registry 是进 LLM 工具 schema 的，于是**用户每装一个软件，冻结前缀里就多一个工具定义**——`cli/install` 会当场改变 `tools_digest`，**整个前缀缓存失效**。用户做了一件与对话无关的事，下一轮命中率归零，97%/95% 的基线扛不住。
>
> 处置见 [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) §6.4 与 HN2：B14 改为只注册恒定两个 agent 工具（`cli_list` / `cli_run`），具体软件的 schema 走既有的 `cli/<tool>/schema` 按需拉取。`cli:` 命名空间、同名冻结纪律、来源标签**全部保留**。**本卡消费的协议方法与数据形状不变**，所以本卡的涉及文件、规范限制、完成判据一律照原样执行。

**涉及文件**：
- `frontend/desktop-app/src/components/ToolCard.tsx`（来源分组展示；H19 已扩展）
- `frontend/desktop-app/src/features/preview/PreviewGallery.tsx`（bundle 渲染；H19 已建，本卡补数据源接线）
- `frontend/desktop-app/src/components/CliToolLauncher.tsx`（新增：`cli:gimp <subcommand> --json` 表单化调用）
- `tests/test_cli_tool_panel.tsx`（新增）

**规范限制**：
- **来源分组**：内置 / CLI-Hub / 自生成（B14 来源标签）；B14 未合入 → 仅内置组（不 BLOCKED）
- **画廊边界（硬约束）**：文件渲染（本地 bundle 目录），**不隐含 PHASE-I 图片附件协议**（PHASE-I 未实施，零依赖）
- 决策规则（报告 §5.3）前端提示：registry 有 → 提示"CLI-Hub 现成"；无 → 提示"生成"入口（B15 合入后）
- 预览性能预算沿用 CLI-Anything 规范（hero ≤1280px / ≤25MB / 懒加载）；`summary.json` 紧凑展示
- 跨平台：本地路径三端（file:// 归一化）；禁止平台特有依赖

**开发步骤**：
1. 后端先行：B14（本卡等待其 `cli:*` 协议）
2. 前端：`CliToolLauncher.test.tsx`（red）→ 表单化调用 → 来源分组接线 → 画廊数据源接线
3. 接线：`cli/list` + bundle 目录扫描；B14 未合入时分组降级
4. 五态

**示例代码**（表单化调用）：

```tsx
// frontend/desktop-app/src/components/CliToolLauncher.tsx —— cli: 工具调用（GX25）
// 命令面 → 表单：参数从 cli/<tool>/schema 派生（B14 返回），提交走 cli/launch
const run = () =>
  rpc.request("cli/launch", {
    tool: `cli:${tool.name}`,
    args: fieldValues,            // --json 默认附加
    workspace_id: activeWorkspace,
  });
```

**验收命令**：
```powershell
python -m pytest tests/test_cli_bridge -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：来源分组（B14 未合入仅内置）、表单化调用、画廊四类 artifact、性能预算、零 PHASE-I 依赖
```

**完成判据**：
- [ ] 工具来源分组（内置/CLI-Hub/自生成）生效
- [ ] `cli:launch` 表单化调用（参数派生 + --json）
- [ ] 画廊渲染 hero/gallery/video/JSON + 性能预算 + 懒加载
- [ ] 零 PHASE-I 附件协议依赖（边界声明验证）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX25 CLI tool panel and preview gallery

CLI-Anything bridge consumer: source-grouped tools, form-based launch,
bundle gallery (file-rendering only, no PHASE-I dependency).
```

---

## GX26 · 设置页重构（8 分区）

**借鉴来源**：Codex 设置页交互（左下角入口 + 分区导航）；2026-08-12 报告 §6.4。
**优先级/工时**：P0 / 4–5d / 依赖：H16（设置重构框架）+ B10（Settings 后端）+ D5（模型管理已实现）/ **owner: frontend + backend**
**背景**：设置页重构为 8 分区：回收站 / 常规 / 外观 / 模型选择 / 模型添加 / 技能管理 / MCP 服务管理 / 团队与模型（预留）。入口 = 左下角"设置"图标 + 文字（圆角框 + hover 高亮）。

**涉及文件**：
- `frontend/desktop-app/src/components/SettingsPage.tsx`（H16 重构产物，各分区填充）
- `frontend/desktop-app/src/features/settings/AppearanceSection.tsx`（新增：主题扩展/自定义/字体/密度）
- `frontend/desktop-app/src/features/settings/GeneralSection.tsx`（新增：语言/启动/默认目录）
- `frontend/desktop-app/src/features/settings/ModelSection.tsx`（新增：选择 + AddModelPanel 复用 + **思考强度选择器**）
- `frontend/desktop-app/src/features/settings/SkillSection.tsx`（新增：对接 B11 skill_manager）
- `frontend/desktop-app/src/features/settings/McpSection.tsx`（新增：对接 B11 mcp/）
- `tests/test_settings_sections.tsx`（新增）

**规范限制**：
- **入口冻结**：左下角圆角矩形（圆角 ≈ 6px 取样），设置图标 + "设置"文字，hover 高亮（同 GX20 亮度规格）
- 分区职责冻结：回收站（GX21 挂载）、常规（语言=H14/GX22、启动行为、默认目录、开发者选项）、外观（theme system/light/dark/high-contrast 扩展、自定义、字体/字号、密度）、模型选择（D5 `models/set_active`）、模型添加（**AddModelPanel 直接复用，后端零改动**）、技能管理（B11 skill_manager——**不新造后端**）、MCP 管理（B11 mcp/）、团队与模型（**预留：F10 开关 + H10 三层折叠对齐；Auto 开关独立设置项与开启时 token 消耗弹窗由 GX28 Team Manager 落地；未合入 → BLOCKED_PREREQUISITE 不 mock**）
- **思考强度选择器（2026-08-12 追加，与 CLI `/effort` 共用同一后端通道）**：
  - 位置：**模型选择**分区（模型选择下方）；控件 = 档位下拉/选择列表（英文档位名）
  - 档位来源：**当前激活模型的 `effort_options`**（`models/list` 返回；空列表 = 不支持档位选择 → 控件禁用并显示"当前模型不支持档位选择"）
  - 提交：`models/set_active` 带 `effort` optional_field（或 `/effort` 命令语义），**全局生效**（切换模型后档位随模型能力自动回退，不报错）
  - 显示：当前档位高亮（`models/list` 返回的 `effort` 字段；未设置显示默认 balanced）
  - 与 CLI 一致性：CLI `/effort` 与 GUI 选择器读写同一全局设置（`config/model_manager` 的 `effort` 键），切换即时生效
- 分区注册表：新增分区只加注册项不改骨架（H16 机制）；设置层级（global/project/workspace/thread）既有语义不变（B10）
- 跨平台：安全存储复用 credential_store（DPAPI/Keychain/Secret Service 已跨平台）

**开发步骤**：
1. 后端探针：B11 skill/mcp 接口存在性（已存在——tools/skill_manager.py、mcp/ 代码实证）；`models/list` 的 `effort`/`effort_options` 字段（2026-08-12 已实现）
2. 前端：分区逐个（General → Appearance → Model → Skill → Mcp）→ 入口 → 团队预留；ModelSection 内接思考强度选择器（消费 `effort_options`/`effort`，提交 `models/set_active` 带 effort）
3. 接线：D5/B11 协议消费；AddModelPanel 复用验证；effort 与 CLI `/effort` 互通验证
4. 五态

**验收命令**：
```powershell
python -m pytest tests/test_settings -q; python -m pytest tests/test_capabilities -q
python -m pytest tests/test_appserver/test_model_routes.py -q   # set_active effort + list effort/effort_options
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：8 分区导航/懒加载、模型添加复用 D5（后端零改动）、技能/MCP 对接现有后端、
#       思考强度选择器（档位随模型/无档位禁用/全局生效/与 CLI 互通）、团队预留 BLOCKED
```

**完成判据**：
- [ ] 左下角入口（图标+文字+圆角框+hover）落地
- [ ] 8 分区填充完成（含常规/外观/模型/技能/MCP）
- [ ] AddModelPanel 复用（后端零改动验证）
- [ ] **思考强度选择器：档位随当前模型 `effort_options` 渲染、无档位禁用、提交 `models/set_active` 带 effort、与 CLI `/effort` 读写互通**
- [ ] 团队与模型预留分区 BLOCKED（不 mock）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX26 settings rebuild (8 sections)

Codex-inspired entry and nav; model add reuses D5 panel; skills/MCP
consume existing B11 backends; team section capability-gated.
```

---

## GX27 · 运行状态视觉（转圈 / 蓝点 / 通知 / 高亮）

**借鉴来源**：Codex 会话运行状态视觉（2026-08-12 报告 §6.3）：运行中转圈、完成蓝点、停止通知、运行中常驻高亮。
**优先级/工时**：P0 / 2–3d / 依赖：H17（状态视觉基建）+ GX13（OS 通知机制）/ **owner: frontend**
**背景**：会话条目右侧状态区：运行中转圈动画 → 完成蓝点（同位置平滑过渡）；停止/异常触发 OS 通知 + 错误徽标；运行中会话常驻高亮（同 hover 亮度保持不灭）。

**涉及文件**：
- `frontend/desktop-app/src/components/SessionListItem.tsx`（状态区接入；H17 基建）
- `frontend/desktop-app/src/components/StatusIndicator.tsx`（转圈/蓝点；H17 已建）
- `frontend/desktop-app/src/lib/statusProjection.ts`（B5 状态 → 视觉投影；H17 已建，本卡验证）
- `tests/test_status_projection.tsx`（新增）

**规范限制**：
- **纯投影铁律（§5.2）**：转圈/蓝点/高亮/徽标全部映射 B5 状态机（running/completed/failed/cancelled/paused…），前端不得自造状态或"看起来完成"
- 转圈 → 蓝点平滑过渡（同位置）；停止通知复用 GX13（`event/agent_needs_input` 类事件 + 完成事件）
- 运行中常驻高亮 = hover 同亮度（GX20 取样值）持续保持
- 跨平台：OS 通知三端（Electron `new Notification()`；Linux libnotify 缺失 → 应用内横幅降级）

**开发步骤**：
1. 确认 H17 基建（StatusIndicator/statusProjection 存在性）
2. 状态区接线：SessionListItem 接入 → 事件驱动状态切换测试
3. 通知联动：GX13 事件 → 通知 + 点击聚焦
4. 五态 + 动画截图对照

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：四态（转圈/蓝点/错误徽标/常驻高亮）随 B5 状态机切换、停止触发通知、无闪烁/重复、截图对照
```

**完成判据**：
- [ ] 转圈/蓝点/错误徽标/常驻高亮四态投影落地
- [ ] 状态全部来自 B5 状态机（无前端自造）
- [ ] 停止通知联动 GX13（三端 + Linux 降级）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX27 session run-state visuals

Codex-inspired spinner/blue-dot/error badge/running-highlight, pure
projection of B5 state machine; stop notifications via GX13 channel.
```

---

## GX28 · Team Manager（专家团管理与选择）

**借鉴来源**：Claude Code Skills 双控规范（`disable-model-invocation`/`user-invocable`，2026-08-11 调研）；多 Agent 专家团设计报告 §9.3/C8（2026-08-11）；F18 生态后端（TeamRegistry/TeamImporter/team_install）。
**优先级/工时**：P3 / 5–6d / 依赖：F18（TeamRegistry/TeamImporter/team_install）+ GX19（多 Agent 活动可视化）+ GX26（设置页"团队与模型"分区）/ **owner: frontend + backend 协议消费**
**背景**：专家团生态的"用户侧"落地（F18 是后端）：CLI `/team` 三层窗口流（像选模型一样选专家团）、GUI 分组管理（other / 自定义组 rename/delete）、**Auto 开关（Team 分组下独立设置项 + 开启时 token 消耗弹窗提示）**、team_install 前端（模型主导安装，两步询问：确认 + 选分组）。F18 未合入前本卡输出 BLOCKED_PREREQUISITE（禁止 mock 假生态）。

**涉及文件**：
- `frontend/opentui-app/`（CLI `/team` 命令：复用 CommandPalette + `Command.category` 分组字段，不新造路由）
- `frontend/desktop-app/src/features/team/TeamPicker.tsx`（新增：三层窗口流——分组列表 → 组内团队列表 → 团队详情）
- `frontend/desktop-app/src/features/team/TeamManager.tsx`（新增：分组管理 other/rename/delete）
- `frontend/desktop-app/src/features/team/TeamInstallPanel.tsx`（新增：安装两步询问——确认 + 选分组）
- `frontend/desktop-app/src/features/settings/TeamSection.tsx`（新增：GX26"团队与模型"分区的 Auto 开关独立设置项）
- `protocol/schema.json` + `protocol/*.py`（F18 `team_*` 协议消费——**F18 合入后消费，本卡不新增字段**）
- `tests/test_team_picker.tsx` / `tests/test_team_manager.tsx` / `tests/test_team_section.tsx`（新增）

**规范限制**：
- **门控**：PHASE-F F18 未合入 → 本卡 BLOCKED_PREREQUISITE（不 mock、不显示入口；与 GX19 同款门控纪律）
- **PROTO 登记说明**：本卡**无协议扩展**（F18 的 `team_*` 协议由 PHASE-F 定义，本卡纯消费）——按 §1 通用纪律**无需 GXn-PROTO 登记**；若实施时发现 F18 未提供所需协议方法，挂起等待并走协议变更单，禁止前端自造协议
- **F18b 追加注记（2026-08-19）**：`team/list` `team/groups` `team/group_rename` `team/install` `team/set_active` 已由 PHASE-F F18b 交付。本卡判据不变，仍只消费、不自造协议。
- **/team 三层窗口流（冻结）**：窗口 1 分组列表（内置组 + 用户组 + other）→ Enter 进窗口 2 组内团队列表 → Enter 进窗口 3 团队详情（成员角色/各自职责/团队 description/成本提示：预估 token 倍数 3–5x）→ **Enter 确认使用 / Esc 逐级返回**；CLI 与 GUI 同构
- **分组语义**：内置组不可删；用户组可 rename/delete；**delete 后组内团队自动归 `other` 组**（F18 `teams.groups.yaml` 后端语义，前端只投影不计算）
- **Auto 开关**：位于 GX26"团队与模型"分区内、独立设置项（on/off）；**点击 on 时弹窗提示**："开启后系统将自动判断任务是否使用子代理/多 Agent 专家团并选择合适专家团；可能产生更多 token 消耗（实测 3–15x）。是否开启？"；关闭时整块隐藏（F13 Settings 分层纪律）
- **双控路由与组合语义**：`disable_model_invocation: true` 的团队只可由用户显式选（`/team`），模型自动选择（`/auto`）时不可见（F18 路由索引语义）；**组合状态冻结**——Auto 开启但某团队 disable_model_invocation：该团队不出现在自动路由候选，但 `/team` 手动选择与 token 弹窗不受影响（弹窗提示的是整体 token 消耗，与单团队双控无关）；模型主导安装对被禁团队一律拒绝（仅手动安装可用）
- **安装双路径**：手动（本地目录/zip，4 步：来源→路径→校验预览→确认+选分组）与模型主导（告诉模型名字/URL → 模型安装 → **询问用户确认 + 询问选分组，默认 other**）并存；复用 `download_skill` 的确认交互模式
- 视觉与 §5.2 铁律一致（纯投影不改变业务语义）；五态覆盖

**开发步骤**：
1. 后端先行：F18 TeamRegistry/TeamImporter/team_install（F 卡范围，本卡等待）
2. CLI：`/team` 命令注册（复用 CommandPalette + category）→ 三层窗口流
3. GUI：TeamPicker → TeamManager（分组管理）→ TeamSection（Auto 开关 + 弹窗）→ TeamInstallPanel（两步询问）
4. 接线：capability 门控（F18 未合入零痕迹）；F10 `settings.agents.enabled` 联动 Auto 开关
5. 五态

**示例代码**（CLI /team 窗口流骨架，复用 CommandPalette）：

```tsx
// frontend/opentui-app —— /team 三层窗口流（分组 → 团队 → 详情）
const [view, setView] = useState<"groups" | "teams" | "detail">("groups");
const [group, setGroup] = useState<Group | null>(null);
const [team, setTeam] = useState<TeamSpec | null>(null);

// 窗口 1：分组列表（含 other）→ Enter 进窗口 2
<CommandPalette commands={groups.map(g => ({
  name: g.name, description: `${g.teamIds.length} 个团队`, category: "team",
}))} ... />
// 窗口 3：团队详情（成员角色/职责/成本提示）→ Enter 确认 / Esc 返回
<TeamDetail team={team} onConfirm={() => setActiveTeam(team.id)} onBack={() => setView("teams")} />
// 双控：disable_model_invocation 的团队不出现在模型自动选择索引（F18 路由索引）
```

**验收命令**：
```powershell
python -m pytest tests/test_protocol -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：F18 未合入 → BLOCKED_PREREQUISITE（零 mock 路径）；合入后：/team 三层流可走通、
# 分组 rename/delete 归 other、Auto 开关 on 弹 token 提示、安装两步询问
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] F18 合入后 `/team` 三层窗口流走通（Enter 确认 / Esc 返回逐级）
- [ ] 分组管理：自定义组 rename/delete，delete 后归 other（纯投影验证）
- [ ] Auto 开关独立设置项 + on 时 token 弹窗提示（文案冻结）
- [ ] 双控路由：`disable_model_invocation` 团队在 `/auto` 不可见
- [ ] 安装双路径（手动 4 步 + 模型主导 2 步询问）走通
- [ ] capability 门控生效（F18 未合入零痕迹，无 mock）；五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX28 team manager (picker/groups/auto-toggle/install)

F18-backed team ecosystem UX: /team three-level picker, group mgmt
(other fallback), auto-toggle with token-cost dialog, dual-path install.
Capability-gated, no mock paths.
```

---

## §2 GXn-PROTO 子卡登记机制（探针路径 B 的统一出口）

**触发**：任何协议 GX 卡（GX2/GX3/GX4/GX5/GX7/GX8/GX9/GX13/GX14/GX16/GX18/GX20/GX23/GX24/GX25）的 §1-16 Protocol probe 结论为「能力不存在」时，登记 `GXn-PROTO` 子卡。

**登记表模板**（新增子卡时填入并追加到本表）：

| GXn-PROTO | 触发卡 | owner | 协议变更单 ID | 新增方法/事件 | 主卡依赖 | 状态 |
|---|---|---|---|---|---|---|
| （例）GX5-PROTO | GX5 | backend | CR-GX5-001 | turn/steer、turn/interrupt（new_method） | GX5 等待 | 未登记 |
| GX20-PROTO | GX20 | backend | CR-GX20-001 | thread 元数据 pin/deleted_at（new_optional_field，探针确认缺失时登记） | GX20 等待 | 未登记 |
| GX23-PROTO | GX23 | backend | CR-GX23-001 | schedule/list、create、update、delete、toggle（new_method） | GX23 等待 | 未登记 |
| GX24-PROTO | GX24 | backend | CR-GX24-001 | plugin/list、install、uninstall、toggle（new_method） | GX24 等待 | 未登记 |
| GX25-PROTO | GX25 | backend | CR-GX25-001 | cli/list、install、launch（new_method） | GX25 等待 | 未登记 |

**子卡必须包含**（沿用 §1 通用规范与 §1-10 提交模型）：背景 / 涉及文件（schema、appserver handler、contract test）/ 协议变更单（request/response/error 冻结）/ 开发步骤 / 验收命令 / 完成判据 / Commit 模板 / 与既有方法同名检查结论。

**纪律**：未登记的 `GXn-PROTO` 不存在；**主卡在 `GXn-PROTO` 完成前不得进入排期**（状态 `BLOCKED_PREREQUISITE`）；`GXn-PROTO` 本身按 §1-10 的 feat/gxN 分支 + 单 squash commit 模型执行，变更单 ID 与主卡关联。

---

## §3 追加阶段出口标准

**三个状态，分别达标**（避免"增强阶段完成"的含糊表述）：

| 状态 | 必需卡 | 验收 |
|---|---|---|
| **Phase G 主链出口** | 主链 26 卡（B1-B13 + H1-H13） | 完整 G 文档 §10 出口标准达标——此门开了才能进入追加阶段 |
| **GX P0 首版出口** | GX1-GX8（P0 批） | 本 §3「全量增强出口标准」的 1-6 项对 P0 批生效 |
| **GX 全量增强出口** | GX1-GX28（P0+P1+P2+P3） | 本 §3「全量增强出口标准」的 1-6 项对全部 GX 卡生效 |

**全量增强出口（GX1–GX28）完成的定义**：

1. GX1–GX28 全部合入（P0 批是增强阶段的最低交付承诺，P1/P2/P3 按计划推进；**P0 首版出口不等于全量增强出口**）
2. 每张卡验收命令全部贴过真实输出；全量回归：`python -m pytest tests -q --timeout=600` 与改动前同量级通过
3. 基线通过（`python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json`）——**按批次出口执行一次，记录唯一结果**；无 API key 时该批次输出 `PENDING_BASELINE` 不标记完成
4. 协议变更单全部归档（§1-2）；`protocol/schema.json` 冻结测试绿
5. 前端视觉验收：所有新增组件五态（空/加载/错误/窄窗/深色）截图归档到 `frontend/desktop-app/docs/gx-screenshots/`
6. 主链 26 卡零改动（`git diff` 验证：仅新增文件、协议扩展与 §1-11 允许的注册点接线）

**P3 批（GX19–GX28 · Codex 对齐批）出口附加**（全量增强出口范围内，P3 批单独判定）：
7. 配套追加卡 H14–H19（前端基建）、B14–B18（后端）合入；
8. 三端适配验证：macOS/Linux 构建目标 smoke（locale 入包 + 启动握手 + 语言切换）；系统 API 差异点（通知/语言/安全存储）按 2026-08-12 报告 §6.9 落地；
9. 多 Agent 预留（GX19/H18）零 mock 路径验证（E/F 未合入时 capability 门控生效）；CLI 工具（GX25/H19）零 PHASE-I 附件协议依赖；
10. i18n 全量文案覆盖（zh-CN + en，GX22 wordlist 归档）。

---

## §4 排期与并行（追加阶段）

### 3.0 角色与分支（与总手册 §4 一致）

| 角色 | 分支 | 职责 |
|---|---|---|
| 后端开发者 | `feat/phase-g-backend` | 所有协议变更单、schema、生成类型、contract test、后端实现；**主链协议变更**随主链卡 PR 合入 master；**GX 协议变更**在 `feat/gxN` 临时分支内先行提交（不单独合入 master，最终随 GX PR squash） |
| 前端开发者 | `feat/phase-g-frontend` | 所有 UI 消费；前端确认协议消费方式后更新分支实现 |
| 验收者（双人互为复核） | — | 每卡 PR 检查依赖、BLOCKED 输出、验收命令输出；Done 责任人 = 该卡 owner |

跨端 GX 卡（GX2/GX3/GX4/GX7/GX8/GX9/GX13/GX16/GX18/GX14/GX20/GX23/GX24/GX25/GX26）：后端开发者在自己的分支提交协议部分 → 前端基于该分支（或临时集成分支 feat/gxN）补消费实现 → 最终以一个 GX PR squash 为单一 GXn commit 合入 master（§1-10 提交模型；协议部分不单独合入 master）。

| 批 | 卡 | 并行建议（按依赖图） |
|---|---|---|
| P0 | GX1–GX8 | GX1 为追加阶段首张（受主链出口门槛约束，不提前合入）；GX2/GX3/GX4 后端协议扩展可并行（协议变更单互不重叠：permission/review-comment/checkpoint-rewind）；GX5/GX6 纯前端并行；GX7 后端 usage 先（前端 statusline 等它）；GX8 独立 |
| P1 | GX9–GX14 | GX9 依赖 GX8 后端先；GX10 等 GX7；GX11/GX12 纯前端并行；GX13 后端 needs_input 先；GX14 等 B5 capability 扩展 |
| P2 | GX15–GX18 | GX15 依赖 GX17 + 图片附件协议探针；GX16 依赖 GX8；GX18 依赖 GX1 |
| P3 | GX19–GX28 | 基建先行：H14–H19 + B14–B18 合入后再进卡；协议扩展方法域互不重叠（thread/pin、thread/restore+purge、schedule/*、plugin/*、cli/*）；GX20/GX26/GX27 为 P3 内 P0 优先（会话分类→设置重构→状态视觉，UI 依赖链）；GX21 等 B17；GX22 等 H14；GX25 等 B14+H19；GX19 等 E/F（未合入 → BLOCKED）；GX23 等 B16；GX24 等 B18；**GX28 等 PHASE-F F18（TeamRegistry/TeamImporter/team_install），且排在 GX26 团队分区落地之后（未合入 → BLOCKED）** |

**并行纪律**：同一批内并行的 GX 卡，协议扩展方法名互不重叠（上表已按方法域划分）；如发生重叠，按"先合小的后合大的"串行化。**涉及协议扩展的卡，后端协议 PR 必须先行且前端确认后才实现 UI（§1-10 模板）**。

> 追加阶段同样遵守 G-B/G-H 的文件 ownership 白名单与 schema 唯一 Owner 纪律：**协议变更全部由后端执行者产出，前端只读消费**。

*（完）*



