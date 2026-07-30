# frontend/ - 前端模块

## 这个文件夹负责什么

React/Ink 终端 UI，包含聊天面板、输入框、命令面板、弹窗、状态栏、鼠标系统和 SSE 流式通信层；该目录没有 Python 文件。

## 核心原理

前后端解耦 + 流式优先：界面组件只关心交互和展示，后端 Python Agent 通过 `/chat/stream` SSE 端点提供能力。思考过程和最终回复均为逐 token 流式推送，前端实时渲染（50ms 批处理）。

## 构建与运行

```bash
cd frontend
npm install      # 安装依赖
npm run build    # tsc 编译到 dist/
npm run dev      # 开发模式 (tsx)
npm test         # 2026-07-25: 28 files / 147 tests
node dist/index.js   # 运行 TUI
```

## 源码结构

- `src/App.tsx`：应用入口组件，组合 Header + ChatPanel + InputBox/Modal/AddModelWizard
- `src/layout.ts`：终端布局自适应辅助（命令面板/弹窗高度随终端行数变化，防溢出和鼠标坐标错位）
- `src/index.tsx`：Ink render 入口
- `src/log.ts`：分级日志
- `src/logo.ts`：ASCII art
- `src/theme.ts`：Catppuccin 风格色板
- `src/types.ts`：类型定义 + 命令注册表（AVAILABLE_COMMANDS）
- `src/mouse.ts`：SGR 1006 鼠标解析 + React Context
- `src/stdinBridge.ts`：stdin 桥接（清理鼠标报告字节）
- `src/testUtil.tsx`：测试辅助（宽终端 render）
- `src/hooks/useApi.ts`：SSE 流式通信层（消息状态、流式渲染、命令发送）
- `src/hooks/sseParser.ts`：跨任意字节分片的 UTF-8/SSE 增量解析器
- `src/apiClient.ts`：Bearer 认证的 API 请求与安全模型 onboarding
- `src/chatHistory.ts`：版本化完整会话恢复与角色映射
- `src/grapheme.ts`：Unicode grapheme 光标和编辑边界
- `src/terminalCursor.ts`、`src/terminalLifecycle.ts`：光标/终端模式安装与异常退出恢复
- `src/components/`：UI 组件目录

## 组件目录

| 组件 | 写了什么 | 功能是什么 |
|---|---|---|
| `ChatPanel.tsx` | 聊天面板 | 渲染用户/思考/工具/助手/系统消息，Static+动态区分离 |
| `InputBox.tsx` | 底部输入框 + 命令面板 | 文本输入、Ctrl+P 命令面板（扁平列表，offset 恒定 4） |
| `Modal.tsx` | 通用弹窗 | 列表选择（session/model/memory/skill/mcp/queue/schedule） |
| `AddModelWizard.tsx` | `/addmodel` 向导弹窗 | 4 步引导输入（名称/Key/URL/昵称），替代旧版步骤塞聊天区 |
| `ApprovalDialog.tsx` | 风险审批弹窗 | 处理关联的 approval request/response |
| `QuestionDialog.tsx` | Agent 提问弹窗 | 选择项、自由文本、取消与超时 |
| `CommandPalette.tsx` | 命令面板 | 键盘导航和命令选择 |
| `CursorInput.tsx` | Unicode 输入 | grapheme 级编辑、粘贴和稳定光标 |
| `Header.tsx` | 顶部状态栏 | 模式、模型名、思考展开状态 |
| `StatusBar.tsx` | 底部状态栏 | 在线状态、上下文窗口、缓存命中率 |
| `ProgressBanner.tsx` | 进度条 | 流式时显示 spinner + 耗时 |
| `Banner.tsx` | 欢迎屏 ASCII art | RxyCode logo |

## 流式渲染机制

前端通过 SSE 接收完整的运行协议：

1. `progress` / `reasoning` / `plan` / `step`：当前轮次的思考和执行进度。
2. `token`：50ms 批处理的实时 assistant 消息。
3. `tool_call` / `tool_result`：按 `message_id` 关联的完整参数、结果和终态。
4. `approval_request` / `question_request`：独立弹窗和对应响应协议。
5. `final` / `error` / `done`：互斥且可关联的运行终态。

默认不启用应用级鼠标捕获，保留终端原生选择、复制和滚动；注入的鼠标报告会被过滤，避免泄漏到输入框。

## 测试

```bash
npm test    # 2026-07-25: 28 files / 147 tests (vitest)
```

测试覆盖：ChatPanel 渲染、InputBox 命令面板、Modal 选择、AddModelWizard 向导、E2E 交互流程、SGR 鼠标泄漏检查。

## 典型协作关系

通过 `http://127.0.0.1:8765` 与后端 API 协作，不直接导入 Python 模块。
