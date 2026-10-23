# 产品 PRD · 从 AI Coding CLI 到 Hybrid AI Agent 全栈平台

> **Owner**：product / frontend + backend；**Status**：Frozen goals，交互调整须 ADR；关联 W3/W4/W5/W6/W7。

## §1 产品定位和可验证主张

**一句话**：一套 Agent 内核，多种执行目标，在真正持久化的 Web 工作台中完成 Coding、Browser、Computer Use 的真实任务，并允许用户授权远端操控本机。

**与 Web 套壳的可测试差异**：1) Web HTTP 断开不终止 Run；2) 重连按序回放 tool/status；3) Run 独立可取消/审批/恢复；4) 相同 AgentV2 支持 CLI/Desktop/Web；5) 工具实际在 Native Runner 或 Cloud Sandbox 运行；6) 有身份归属/审计/指标。任一条仅 UI 模拟不通过。

## §2 三种运行模式的用户语义

| 模式 | 访问方式 | 执行地点 | 权限/隔离 | 产品承诺 |
|---|---|---|---|---|
| Local | `rxycode web` → `localhost` | 同一台本机 Worker+Native Runner | Ask/Auto/Full；Full 关闭 OS Sandbox | shell、文件、窗口、桌面直接操作 |
| Cloud | 用户登录 HTTPS Web | 云端 Worker + Sandbox Runner | 受隔离租户工作区，即使 Full 不突破租户边界 | 后台持久任务、GitHub PR |
| Hybrid | HTTPS Web + `rxycode connect` 本地设备 | 云端 Worker（或隐私模式本地 Worker）+ 用户设备 Native Runner | 本机授予目标/时效/能力，Remote Full 无逐项审批 | 跨设备工具执行，用户可本机急停 |

**远程隐私提示**：即使工具在本机，文件内容/输出仍可能回到云端 Worker 和模型提供方。需要“本机私有模式”时，Agent Worker、密钥和上下文也必须留在本机，不能冒充仅 Runner 本地就实现了端到端本地隐私。

## §3 关键人物与核心旅程

**初次接入**：GitHub 登录（local 无需账号）→ 模型配置（密钥服务端加密，默认 BYOK）→ 导入 Git 仓库或选择本地目录 → 选择 Local / Cloud / Remote 设备 → 权限预设 → 演示任务 → 结果验证。移动端允许监督/审批/查看产物，不要求手机代替完整 IDE。

**主场景 A — Cloud Coding**：用户导入示例 repo→输入“为登录接口添加测试并修复”→ Run 落库→计划/工具轨迹→分支隔离→代码 Diff→运行测试→人工审查→经许可创建 PR→生成可追踪结果。关网页后 Worker 持续；第二天登录能看到终态、成本、文件产物。

**主场景 B — Native Full**：用户在本机执行 `rxycode web`→选 local, full→一次性明确告知原生执行→输入“打开编辑器、修改项目、启动服务器”→Native Runner 原样调用 OS→UI 显示窗口/终端状态；**不允许偷偷插入 Docker/WSL/gVisor**。用户可用本机急停中断。

**主场景 C — Remote Full**：设备登录 `rxycode connect`→Web 选择在线设备→本机托盘确认项目/会话/能力/过期时间 Full grant→模型调工具→Runner 判断 grant 有效→真实桌面操作→用户在 Web 查看设备和任务；撤销后立即拒绝新调用并处理在途调用。

**主场景 D — Long-running Multi-agent**：Plan→Coder→Reviewer→Tester（模型角色真实隔离）→审批等待释放 Worker→恢复继续→所有节点含耗时/token/结果，受预算 guard 控制。

## §4 用户必须看见的页面

`/login`, `/onboarding`, `/projects`, `/projects/:id`, `/sessions/:id`, `/runs/:id`, `/devices`, `/artifacts/:id`, `/usage`, `/settings/{models,security,integrations}`, `/admin`（部署者可选）。Workspaces 主界面：左栏项目/会话，中栏消息/计划/子 Agent/审批，右栏 Files/Diff/Terminal/Browser/Artifacts。状态 `queued/running/waiting_approval/waiting_input/recovery_required/succeeded/failed/cancelled` 不能只靠动画猜测。

## §5 范围与严格验收

| 能力 | 必须最终可用 | 不算完成的伪实现 |
|---|---|---|
| Live Coding | 真实改文件、真实执行测试、可审 Diff | UI 假工具卡或纯文本测试结果 |
| Session/Run | 登录跨天检索、持久化事件、断线续传 | localStorage 做历史唯一来源 |
| Local Full | 原生 Shell/桌面/文件，无 Sandbox | Sandbox bind mount 假扮宿主 |
| Remote Full | WSS 连接、设备授权、撤销、审计、急停 | 只有云端页面上一个 Full 按钮 |
| Cloud | 独立工作区、资源隔离、出口策略、预览 | 在 Server 宿主上跑不受限 subprocess |
| AI | LangGraph 工具循环、真实团队委派、Checkpoint | 一次模型调用返回长文本假进度 |
| 求职 | 可访问 Demo、E2E、Benchmark、CI、文档 | 静态截图、虚构指标 |

## §6 非功能验收（候选目标值，不得写成现有事实）

- 所有测试不允许 `skip` 代替必需场景；公共 Demo 无本机 Runner Full 权限。
- HTTP API P95（排除 Agent 总运行时间）设计目标 ≤ 500ms，SSE 本地 1s 内看到已提交事件目标；这些只是阶段目标，W7 必须填真实数值与测量方法，不能无证据设为 PASS。
- UX 目标：没有空白无限加载，错误/取消/权限拒绝均有明确可操作提示；键盘可达、屏幕阅读器状态提示。
- 记录真实成功率、TTFE（first event）、Run wall time、成本与每任务工具数量；性能改善必须有同任务集基线对比。
