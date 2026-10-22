# Web 工作台 UX Contract（不是聊天套壳）

> **Owner**：frontend。`apps/web` React19+TS+Vite，后端权威、前端只投影；Web 只能通过生成的 HTTP/SSE/WS 客户端通信，禁止 import Electron/Node/preload。

## §1 信息架构

| 页面/区块 | 核心功能 | 数据真相与状态 |
|---|---|---|
| `/login`, `/onboarding` | GitHub OAuth、模型 Key（服务端加密）、Project 导入、Target 选择、首个任务 | session user/token、`invalid_origin`, `unauthorized` |
| `/projects`, `/projects/:id` | 工作区列表、仓库/路径、命名、模型、访问范围 | PG Project，empty/loading/failed/ready |
| `/sessions/:id` | 历史对话、实时 Run、计划、Todo、子 Agent 树、审批、用户追问 | Server Session+Run+ordered EventStore |
| `/runs/:id` | SSE/replay、工具、状态、流式回答、成本、日志 | `seq`, `intermediate`, run.status |
| `/devices` | `rxycode connect` 设备配对、离线/在线、授权范围、撤销、急停 | Server device + Runner local grant ACK |
| `/usage`, `/settings` | Token/费用、Key、组织权限、运行偏好、通知 | Server 记录；Key 不可回显 |
| 右侧工作区 | Files/Monaco Diff/xterm Terminal/Browser Preview/Artifacts/Git | 真实 Runner 的工作区和 PTY，不是 UI 假操作 |

**默认桌面布局**：左栏 Project/Session；中栏主对话/Tool Cards/Plan；右栏 Files/Diff/Terminal/Browser/Artifacts；顶栏 Target+Mode+Model+Activity。375px 手机侧栏变抽屉、工作区局部只读，仍可创建 Run、暂停/审批、看结果。视觉样式以既有 Desktop 纯组件与全新 Web 设计系统统一。

## §2 消息流/事件卡

- 每个工具事件由 `call_id` 配对，显示 `target`、开始/执行/已完成/失败/取消/超时、输出截断标记。
- `Run` 状态 queued/running/waiting_approval/waiting_input/recovery_required/succeeded/failed/cancelled 必须有可读文字；在 Server 未确认前不擅自改为 succeeded。
- 子 Agent intermediate 事件只在子 Agent 卡上展示；不能冲到最终答复尾部。`assistant.final` 是主轮最后面向用户的答案。
- SSE 重连显示“重连中/正在补齐历史”，接收 `CURSOR_EXPIRED` 时向用户请求刷新快照；不得静默忽略 seq gap。
- 审批卡显示原始目标/资源/风险/有效期/操作影响，按钮只向 Server 提交决定，过期会显示新的服务端状态。
- 新建/撤销/删除项目要明确加载、空态、权限错误、重试；敏感工作区操作显示来源设备。

## §3 三种 Full 的 UX

- **Local Full**：显示本机真实进程操作警示和 `Local · Native Full · Sandbox OFF`，用户明确开启后不逐工具批准；本机急停可访问。
- **Remote Full**：Web 只能请求本机授权，必须显示 `waiting_for_local_confirmation`，直到 Runner ACK；授权带 scope、expiry、设备身份，不是“在线就可控制”。
- **Cloud Full**：显示云端 Sandbox 内的自动执行，不得使用“正在完全控制你的电脑”的误导文案。

## §4 UX/A11y/Performance 门

WCAG 2.2 AA 目标，键盘焦点/ARIA live/色盲冗余提示，视口 375/768/1440、缩放 200%、长日志虚拟化与 token delta 批量渲染，所有提示可以翻译且长文本不溢出。视觉截图必须与真实 E2E API Trace 一起提供，截图不替代功能验收。参考 [`tests/E2E-FIXTURES.md`](tests/E2E-FIXTURES.md)。
