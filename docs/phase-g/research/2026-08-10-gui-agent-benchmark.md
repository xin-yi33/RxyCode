# 2026-08-10 · 10 款 AI 编程 GUI Agent 产品基准调研报告

> **调研目的**：为 Phase G（RxyCode Desktop 完整工作台）的前后端 GUI 设计提供可借鉴（可抄袭）的交互模式、组件形态与设计风格基准。
> **调研方法**：三路并发调研，全部基于官方仓库 / 官方文档 / 官方 changelog / 可信评测（抓取日期 2026-08-10），逐条标注来源 URL；官方未公开的细节一律标注"信息不足"，未编造。
> **下游产物**：本报告是 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md)（GX1–GX28 增强任务卡）的立项依据。
> **调研日期**：2026-08-10　**执行**：三路并发子代理 + 主线程综合

---

## §1 调研范围与方法

| 组 | 产品 | 重点 |
|---|---|---|
| 组 1（国际头部） | **OpenAI Codex（重点）**、Claude Code、GitHub Copilot | Codex 桌面应用 + CLI 的完整交互面 |
| 组 2（独立工作台式） | Cursor、Windsurf（已并入 Cognition，现 Devin Desktop 2.0）、Devin（云端） | 从"IDE 增强"到"独立工作台"的形态演进 |
| 组 3（国内 + 网页/云端） | 字节 TRAE（含豆包 MarsCode 体系）、通义灵码 Qoder、Replit Agent、Vercel v0 / Bolt.new | 国内产品 vs 国际产品的设计差异 |

**环境事实**：Windsurf 已被 Cognition 收购并更名为 Devin Desktop 2.0（原 docs.windsurf.com 重定向至 docs.devin.ai）；Cursor 官方 docs 为客户端渲染无法直接抓取，事实取自官方 changelog（逐条验证 URL）；TRAE 于 2026 年 5-6 月经历大改版（SOLO 模式上线、积分计费、TraeWork 上线），本报告以 2026-08 官方文档快照为准。

**统计口径**：本报告覆盖 **10 大品牌 / 11 个产品面**——Devin Desktop 2.0（原 Windsurf）与 Devin 云端为两个产品面（§6/§7 分列）；v0 与 Bolt.new 为两个产品面（§11 并列）；Codex 的 CLI/桌面/Web/IDE 属同一产品面的多形态，合并于 §2；历史品牌沿革（Windsurf→Devin Desktop、通义灵码→Qoder）在各节标注，不重复计数。

**来源分级**（审计与下游引用时必须区分）：
| 级别 | 含义 | 用途 |
|---|---|---|
| `official verified` | 官方仓库/官方文档/官方 changelog 原文 | 可作为增强卡设计的依据 |
| `secondary evaluation` | 可信评测/转引 | 仅作佐证，不单独作为设计依据 |
| `inference` | 从官方描述反推的设计哲学/视觉推断 | **不得冻结为产品行为或安全语义**，仅作风格参考 |

本报告中 Codex"设计哲学"（§2.6）与各桌面应用视觉细节属于 `inference` 级。

**可追溯性约束**：凡进入 GX 增强卡的借鉴来源（§14 映射表），其关键能力必须能逐条追溯到本条 `official verified` / `secondary evaluation` 的源（见 §15 URL）；无法直接验证的内容降级为"待核实/风格参考"，不得作为验收或协议设计依据。

---

## §2 产品一：OpenAI Codex（重点）

### 2.1 产品形态与平台

Codex 是**同一引擎覆盖 5 个面（surface）**的多形态产品：

- **Codex CLI**（Rust 终端 TUI，开源 Apache-2.0）：`codex` 交互模式 + `codex exec` 非交互模式
- **桌面应用**：2026-02 macOS 独立 Codex App → 2026-03 Windows → **2026-07-09 并入 ChatGPT 桌面应用**（Codex 保留独立视图，可设为默认视图）
- **Web**：chatgpt.com/codex（云端 agent）
- **IDE 扩展**：VS Code / Cursor / Windsurf
- **Codex Cloud**：`codex cloud` 提交 / `codex apply` 应用结果到本地

> **与 Phase G 架构高度同构**：CLI 内置 `codex app-server`（JSONL-over-stdio 或 WebSocket 传输），TUI 可 `--remote` 连接远端 app-server——即 **CLI 内核与 GUI 前端是 JSON-RPC 式进程分离**，与我们的 Electron + React + JSON-RPC 桌面工作台架构一致。来源：https://learn.chatgpt.com/codex/developer-commands

### 2.2 GUI 信息架构（桌面应用）

```
┌────────────────────────────────────────────────────────────┐
│ 顶部：视图切换（Chat / Work / Codex）+ 全局命令（Cmd+G 搜索等）│
├──────────┬─────────────────────────────────────────────────┤
│ 左侧栏    │ 中间：对话流 + 底部 Composer                     │
│ • Projects│   • 聊天时侧边栏可浮出：plan / sources /         │
│   - 钉选    │     生成文件 / chat summary（agent 运行中可审阅）│
│ • Chats   │   • Review Pane（diff 审查面板，可含多仓库）      │
│   - 钉选    │   • Artifact 预览面板（文档/表格/PDF/HTML 内联） │
│ • Activity│   • 内嵌浏览器 / 集成终端面板                    │
│   （铃铛=   │   • 权限模式控件位于 Composer 下方               │
│   待关注）  │   • 模型/推理选择、@ 文件引用、附件、图片          │
│ • Quick   │                                                │
│   chat    │                                                │
└──────────┴─────────────────────────────────────────────────┘
```

关键结构事实（均有出处）：
- **Projects 视图**：统一"ChatGPT 项目"与"本地项目"；本地项目支持**多文件夹**（primary 文件夹用于新 chat/Git/AGENTS.md 自动发现，secondary 只读可搜索）。来源：https://learn.chatgpt.com/codex/projects
- **会话组织**：pin 项目/chat、重命名 chat（建议"按产出命名"）、Cmd+G 搜索历史 chat、归档。来源：同上
- **Composer + Quick chat**：Codex 视图"New chat"右侧有 Quick chat 图标（独立普通对话）。来源：同上
- **聊天中侧栏**：任务运行时浮出 agent 的 plan / sources / 生成 files / chat summary，用于中途引导（steer）。来源：https://learn.chatgpt.com/codex/artifacts-viewer
- **权限控件在 Composer 下方**；模型/推理 effort 会话内可切换。来源：https://learn.chatgpt.com/codex/permission-modes

### 2.3 关键交互模式清单（18 条）

| # | 功能 | 交互描述 | 用户价值 |
|---|------|---------|---------|
| 1 | **权限模式三档**（app） | Composer 下方控件：Ask for approval（默认）/ Approve for me（Auto-review）/ Full access；模式需先启用；沙箱边界与审批维度正交 | 自主度按任务随时切换，低频打扰 |
| 2 | /permissions 预设（CLI） | 会话内选预设（Auto、Read Only 等），显示当前 sandbox 与 writable roots | 终端内即时调节边界 |
| 3 | **自动审查（Auto-review）** | 越界请求转交自动审批审查，执行前展示审查状态与风险；被拒动作可 /approve 重试一次 | 审批降噪 + 可回退 |
| 4 | **Plan 模式 + Goal 模式** | /plan 只规划不改码；/goal 设置/暂停/恢复目标（可数小时数天） | 复杂任务先审方案再动手 |
| 5 | **Review Pane 五档 scope** | Unstaged / Staged / Commit / Branch / **Last turn**；多文件夹可跨仓库（All repos） | diff 审查按"我关心的范围"精确切分 |
| 6 | **diff 行内注释闭环** | 悬停行尾 + 按钮 → 写评论 → 回聊天"请处理内联评论"；支持 inline 与 detached 双模式 | 以行为单位的精准反馈 |
| 7 | **Git 三级操作** | 整包（Stage all/Revert all）→ 单文件 → 单 hunk 三级 stage/unstage/revert | 部分接受 agent 产出 |
| 8 | **PR 反馈融入** | PR 分支上侧栏显示 PR 上下文与评论，diff 旁显示评论，同聊天修复→review→push | 修复闭环不出应用 |
| 9 | **多会话并行** | 每项目多 chat；钉选/重命名/归档/搜索；CLI /new、/rename、/resume、/archive | 并行任务可见、历史可回 |
| 10 | **消息级 fork** | Esc Esc（空输入）= 编辑上一条用户消息并从该点 fork 新 chat；codex fork --last | 分叉探索不丢原路径 |
| 11 | **侧聊 /side** | 从当前 chat 派生临时对话，完成后回主 chat，不污染主转录 | 聚焦追问不打断主任务 |
| 12 | **Mid-turn steering** | Tab 排队下一条；Enter 直接向当前回合注入新指令 | 不停止也能改方向 |
| 13 | **@ 文件引用** | 输入 @ 搜索工作区文件插入路径；@ 菜单列 enabled skills；粘贴图片为 [Image #N] | 显式上下文，引用即交付 |
| 14 | **模型/成本/上下文可见** | /model（含 reasoning effort）、/status、/usage daily/weekly/cumulative、footer 可放 token 计数 | 透明消费，防止失控 |
| 15 | **进度可视化** | footer 可加 task progress/spinner；终端标题显示任务进度；/goal 目标跟踪；/ps 看后台终端输出 | 长任务不黑盒 |
| 16 | **子代理线程** | /agent /subagents 切换当前线程查看/继续子代理工作；后台子代理有视觉标识 | 子代理树可导航 |
| 17 | **跨面切换** | CLI /app 搬到桌面继续；桌面↔云端 chat handoff（含 git worktree 重建）；codex cloud + apply | 换场景不换上下文 |
| 18 | **恢复入口** | resume 保存 transcript + 工作目录；Git checkpoint 建议；auto-review 拒绝可 /approve 重试 | 断点续作、失败重来 |

### 2.4 设计风格

- CLI：ratatui 风格 TUI，header/footer 高信息密度，statusline 可配置（`/statusline` 增删排序：model、context stats、rate limits、git branch、token counters、session id、目录、版本、**task progress**）；`/theme` 换语法高亮；`/personality` 换语气；`/pets` 终端宠物；`/vim` 模式。来源：https://learn.chatgpt.com/codex/cli
- 桌面应用：ChatGPT 设计语言（圆角卡片、composer、侧栏），light/dark 双版本；官方措辞 "Your command center for complex work"、"Keep every chat in view"——**多任务工作台**定位。具体色板/字体官方未公开（信息不足）。

### 2.5 可借鉴清单（对 Phase G）

| 优先级 | 借鉴项 | 说明 |
|---|---|---|
| **P0** | Composer 下方权限模式切换（Ask/Auto-review/Full access 三档） | 审批=模式而非弹窗 |
| **P0** | Review Pane 五档 scope（尤其 **Last turn**） | 完美映射 Thread 模型 |
| **P0** | diff 行内注释闭环 | 各家最强反馈机制 |
| **P0** | 整包/单文件/单 hunk 三级 stage/revert | 部分采纳 agent 产出 |
| **P0** | 会话管理四件套：重命名/钉选/归档/搜索 | 低成本高感知价值 |
| **P0** | 消息级 fork（Esc Esc） | 分叉探索 |
| **P0** | Mid-turn steering：Tab 排队 + Enter 注入 | 核心交互 |
| **P0** | 聊天侧栏浮层（plan/sources/files/summary） | 运行中透明化 |
| **P1** | 可配置 statusline（model/context/tokens/git/task progress） | 底部状态条 |
| **P1** | 上下文剩余指示（"100% context left"） | 长会话防爆 |
| **P1** | /side 侧聊 | 轻量追问 |
| **P1** | Plan 模式 + Goal 模式 | 任务前审方案 |
| **P1** | 自动审查（LLM judge）+ /approve 重试 | 审批降噪 |
| **P1** | /usage 成本显示 | 消费透明 |
| **P2** | Artifact 预览（HTML/文档/表格/PDF + 注解） | 非代码产出审查 |
| **P2** | 内嵌浏览器/集成终端面板 | 后期 |
| **P2** | 定时任务 / 终端宠物 / 主题 / personality | 趣味差异化 |

### 2.6 Codex 设计哲学（从文档反推，均有出处）

1. **会话是原语，项目是组织单元，审批是模式而非弹窗**——权限做成 Composer 下方常驻模式切换，避免逐动作弹窗打断流
2. **审查是一等公民工作区**——Review Pane 独立于聊天流，五档 scope 让"审什么"由用户定义，内联注释 + Git 三级操作 + PR 反馈 = 完整闭环
3. **上下文全程显式化**——footer context 剩余、/status token 用量、/usage 账户消费、模型+effort 显示在 header
4. **一切可恢复、可分叉**——resume（含工作目录还原）、fork（消息级/会话级）、archive/delete、auto-review 拒绝后可重试
5. **无缝换表面**——CLI /app → 桌面、云端 handoff、codex apply；核心是 app-server 进程分离架构（正是我们 Phase G 的架构选择）
6. **任务运行透明 + 可引导**——聊天侧栏浮层、Tab/Enter steering、footer task progress、goal 模式
7. **轻量趣味层**——终端宠物、主题、personality，成本低的品牌化彩蛋

### 2.7 Codex 与 Phase G 的差距清单

**功能缺项**（对照 Codex 桌面应用 + CLI）：

| 类别 | Phase G 缺什么 | 对应 Codex 能力 |
|---|---|---|
| 项目模型 | 多文件夹项目、primary/secondary 语义、AGENTS.md/skills 自动发现域 | Projects 本地项目模型 |
| 会话管理 | 重命名（按产出）、钉选、归档+恢复、Cmd+G 搜索、Activity 待关注视图 | pin/rename/archive/search/activity |
| 会话操作 | /new 命名开线程、/resume 列表、/fork、消息级 fork、/side 侧聊 | 会话生命周期完整集 |
| 审批 | 三档模式、自动审查"审查状态与风险"、被拒 /approve 重试、权限预设 | 审批=模式 |
| Diff 审查 | 五档 scope（含 Last turn）、多仓库审查、内联注释闭环、三级 Git 操作、inline/detached 双模式 | Review Pane |
| 进度/上下文 | footer statusline、/usage 成本、/goal 目标、后台终端 /ps | 状态行体系 |
| 运行中干预 | Tab 排队、Enter 注入、聊天侧栏 plan/sources/files/summary | steering |
| 子代理 | /agent 线程切换、后台子代理视觉标识 | 子代理树导航 |
| 环境 | 集成终端面板、内嵌浏览器、artifact 预览 | 面板族 |
| 上下文注入 | @ 文件补全、图片粘贴、/init 生成 AGENTS.md、memories、/import 导入 | 上下文族 |

**交互缺项**（行为层面）：
- 无"运行中 Send 三态"（Copilot 的 Queue/Steer/Stop 语义更显式——建议融合 Codex 的 Tab/Enter + Copilot 的下拉）
- 无 checkpoint/rewind 等价物（Claude 的 rewind 菜单 + Copilot 的 Restore/Redo 是现成范本）
- 无 OS 通知（回复完成 / 需要确认）
- 无 usage ring / 计划用量环
- 无 transcript 视图模式（Normal/Verbose/Summary）
- 无 prompt suggestions（灰色示例输入）
- 无跨会话消息与来源卡片（Claude Desktop 独有）
- 无 task chips（范围外工作 → 新线程建议）

**架构性差距（建议优先补）**：app-server 分离使 CLI/桌面/IDE 共享同一会话存储与协议——我们已有 JSON-RPC 底座，建议把**会话存储格式、resume 语义（保存工作目录+transcript）、fork 语义**作为协议层一等公民设计，而不是 UI 层功能。

---

## §3 产品二：Claude Code

### 3.1 产品形态

同一引擎多面：终端 CLI、VS Code/Cursor 扩展（inline diffs、@-mention、plan review）、JetBrains 插件、**桌面应用（Chat / Cowork / Code 三 tab）**、Web（claude.ai/code）、移动端 + Remote Control。CLAUDE.md / settings / MCP 跨面共享。来源：https://code.claude.com/docs/en/overview

### 3.2 GUI 信息架构（桌面 Code tab）

```
┌───────────────────────────────────────────────────────────┐
│ 会话工具栏：Env(Local/Cloud/SSH/WSL)｜项目文件夹｜模型｜     │
│             权限模式｜usage ring｜transcript 视图模式       │
├──────────┬────────────────────────────────────────────────┤
│ 侧栏      │ 可拖拽/缩放的 Pane 布局（Views 菜单开启）：      │
│ 会话列表   │  Chat ｜ Diff ｜ Browser ｜ Terminal ｜ File     │
│ 按状态/项目│  Plan ｜ Tasks ｜ Subagent ｜ (iOS Simulator)   │
│ /环境过滤，│  多会话可 Cmd+Click 双 Pane 并排               │
│ 按项目分组 │  每会话独立 worktree（git 隔离）               │
│ + New     │  输入框：+ 附件/技能/连接器/插件、@mention、     │
│           │  / 斜杠命令、/btw 侧聊、权限模式选择器           │
└──────────┴────────────────────────────────────────────────┘
```

来源：https://code.claude.com/docs/en/desktop

### 3.3 关键交互模式清单（16 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | **五档权限模式** | Manual（每动作审批，显示 diff 可接受/拒绝）→ Accept edits → Plan → Auto（分类器后台审查）→ Bypass；Shift+Tab 循环，状态栏徽章 | 新手到无人值守的渐变梯度 |
| 2 | **权限卡（Approval card）** | 动作到达边界时弹卡：命令/编辑、接受/拒绝；对话框 tab 左右切换；Esc 关 | 每个越界动作可审 |
| 3 | **Auto 模式分类器** | 独立模型（Sonnet 5）执行前评估；黑名单（curl/bash、推送 secret、rm -rf 等）；拒绝可 r 重试（Recently denied tab）；连续拒 3 次/累计 20 次自动降级人工 | 审批疲劳的工程化解法 |
| 4 | **Plan 模式 + 计划审批** | 只读探索后输出计划；批准选项：Yes and use auto mode / Yes, manually approve / No, keep planning；Ctrl+G 外部编辑器改计划；批准后自动命名会话 | 方案先行 |
| 5 | **Checkpoint（每 prompt 自动快照）** | 最近 100 个文件快照，随会话持久，30 天清理；/rewind：Restore code and conversation / Restore conversation / Restore code / Summarize from here | 任意点回滚+压缩 |
| 6 | **Rewind 入口** | 空输入 Esc Esc 打开 rewind 菜单；恢复对话后原 prompt 回填可重发 | 键盘可达的回滚 |
| 7 | **Diff 审查** | diff stats 指示器（+12 -1）→ 打开查看器；点击行出注释框；多行注释 Cmd+Enter 批量提交；AI 修复后新 diff 再审 | 可视化+批注 |
| 8 | **Review code 按钮** | 一键让 Claude 审当前 diff，内联评论留在 diff；聚焦编译错/逻辑错/安全漏洞 | 提交前 AI 自检 |
| 9 | **并行会话 + worktree** | 每会话独立 git worktree；Cmd+N 新会话、Ctrl+Tab 循环、Cmd+Click 双 pane 并排；归档即删 worktree | 并行零冲突 |
| 10 | **跨会话消息** | 让 Claude 读/写其他会话；接收方以**来源卡片**展示（发送会话标题+回链）；归档前必弹审批卡 | 多 agent 编排的 GUI 层 |
| 11 | **Task chips** | Claude 发现范围外值得做的事以芯片出现；点击即在新会话（新 worktree）启动 | 主动建议不打断 |
| 12 | **Usage ring** | 模型选择器旁环状图：上下文窗口用量 + 账户计划用量；将满自动 summarize | 用量可视化 |
| 13 | **Transcript 视图模式** | Normal（工具调用折叠）/ Verbose / Summary（只看最终回复和变更）；Ctrl+O 循环 | 多会话降噪 |
| 14 | **Sessions 过滤/分组** | 按状态/项目/环境筛选、按项目分组、重命名、归档 | 会话多不迷路 |
| 15 | **Continue in** | 本地会话推送到 Web/云继续（推分支+摘要+全上下文） | 换面不断档 |
| 16 | **App 权限分级** | 首次用某 app 弹审批卡：Allow for this session / Deny；按 app 类别：View only / Click only / Full control | 屏幕控制安全粒度 |

### 3.4 设计风格

- CLI 高度键盘驱动（60+ 快捷键：Esc Esc rewind、Shift+Tab 循环模式、Ctrl+O transcript、Ctrl+B 后台化、`!` shell 模式、`?` 帮助面板）；状态栏徽章体系（⏸/⏵⏵ + 模式名）；/theme 主题选择器
- 桌面 app 面板化 IDE 风格（可拖拽布局、多 pane）；light/dark 跟随系统；具体视觉 token 未公开（信息不足）
- **Prompt suggestions**：首开会话灰色示例指令（取自 git 历史），回复后基于会话续推，Tab 采纳；复用 prompt cache 成本极低

### 3.5 可借鉴清单

| 优先级 | 借鉴项 | 说明 |
|---|---|---|
| **P0** | 每 prompt 自动 checkpoint + rewind 菜单（代码/对话/摘要三分动作） | "恢复"的完整形态 |
| **P0** | 五档权限梯度 + 模式徽章 | Manual→AcceptEdits→Plan→Auto→Bypass |
| **P0** | diff stats 指示器（+12 -1）→ 点击开审查器 | 微小但极有效 |
| **P0** | 行注释 + 批量提交（Cmd+Enter） | 与 Codex 内联注释互补 |
| **P0** | Review code 按钮（AI 自审当前 diff 内联评论） | 提交前防线 |
| **P1** | 会话级 git worktree 隔离 + 归档即删 | 并行安全 |
| **P1** | 会话双 pane 并排（Cmd+Click） | 对比查看 |
| **P1** | 跨会话消息 + 来源卡片 + 归档前必审批 | 多 agent 协作 |
| **P1** | Task chips | 主动但不抢 |
| **P1** | Usage ring | 可见性 |
| **P1** | Transcript 视图模式 | 多会话场景 |
| **P1** | 侧栏过滤+分组、Prompt suggestions | 引导细节 |
| **P2** | Tasks pane（子代理/后台任务树）、快捷键面板、CI 状态条 | 后期 |

---

## §4 产品三：GitHub Copilot（VS Code + Copilot Workspace/Cloud Agent）

### 4.1 产品形态

- VS Code 内嵌：Chat view（侧栏）、**Agents window**（独立窗口，agent 优先，preview）、Inline chat（⌘I）、Quick Chat
- Copilot cloud agent（原 Copilot Workspace）：issue/PR/comment 触发，产出 PR；IDE 内 "Delegate to cloud agent" 一键转交

### 4.2 GUI 信息架构（Agents window 五大区域）

1. **Sessions list**（跨 workspace 分组、pin、自定义分组、拖拽重排、Open to the Side）
2. **Customizations panel**（agents/skills/instructions/hooks/MCP/plugins 集中管理）
3. **Chat area**（激活会话对话）
4. **Changes panel**（变更+Git 动作；dropdown：Branch changes / Uncommitted / All / **Last agent turn**；"Other Files" 分组工作区外文件）
5. **Files panel**（会话工作区文件浏览）+ Terminal/Tasks/Browser（集成浏览器，tab 属于会话）

来源：https://code.visualstudio.com/docs/agents/run/agents-window

### 4.3 关键交互模式清单（15 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | **Queue / Steer / Stop-and-send** | 回复运行中 Send 变下拉：Add to Queue / Steer with Message（当前工具执行完即停，处理新消息）/ Stop and Send；pending 可拖拽重排 | 运行中干预的三级语义，业界最清晰 |
| 2 | **权限级别** | 输入区下拉：Default / **Assisted permissions（LLM judge）** / Bypass；另有 **Autopilot** 模式 | 自主度连续可调 |
| 3 | **工具审批对话框** | 工具名+输入参数；范围：once / session / workspace / **all future**；敏感工具禁 auto-approve；Chat: Manage Tool Approval 集中管理 | 粒度化信任 |
| 4 | **URL 两步审批** | ①批准域名请求 ②批准响应内容进上下文（防 prompt injection） | 注入防护 GUI 化 |
| 5 | **终端命令 auto-approve 规则** | 按命令粒度 allow/deny（支持正则）；默认放行安全命令、必拦 rm/del | 白名单式降噪 |
| 6 | **敏感文件审批** | glob 规则（`**/.env`: false）→ 该文件编辑前先出 diff 审 | 配置/密钥特殊对待 |
| 7 | **Checkpoint（每请求快照）** | Restore Checkpoint（回滚该请求及之后全部文件变更）；Redo 可恢复；每请求变更文件摘要；**Fork Conversation from checkpoint** | 回合级回滚+分支 |
| 8 | **编辑历史请求** | 任意旧请求可编辑重发：自动回滚该请求及后续文件变更再重发 | 修正意图而非追加 |
| 9 | **Range-based Feedback** | diff 中选区 → Add Feedback → 多条后 Submit Feedback 一次发；agent 修复后逐条 resolve | 精准批注 |
| 10 | **Pending edits 逐条审** | 编辑器覆盖层遍历编辑点，Keep/Undo 单条；hover 内联变更单点接受/拒绝 | 编辑级审批 |
| 11 | **# 上下文提及** | #file #folder #symbol #codebase #terminalSelection #fetch；隐式上下文（活动文件+选区）；图片附件 | 上下文显式组装 |
| 12 | **! 终端直连** | 消息以 ! 开头直接执行 shell（不经 agent/审批），输出进 transcript | 快速命令与对话共存 |
| 13 | **OS 通知** | 两档：notifyWindowOnResponseReceived（回复到达，含预览）/ notifyWindowOnConfirmation（**需要输入/确认时**） | 后台 agent 在场感 |
| 14 | **Delegate to Cloud Agent** | 一键转交云端：确认本地变更是否推送 → 云端起 PR → 完成后加为 reviewer 并通知；View Session / Cancel Job | 本地↔云端切换 |
| 15 | **集成浏览器验证** | Agents window 内浏览器打开 localhost，tab 属于会话；跨会话切换保留 tabs | 验证与聊天同窗口 |

### 4.4 设计风格

完全复用 VS Code 设计系统（主题跟随、Quick Pick、命令面板、JSON settings 驱动）——**无独立视觉语言**；密度编辑器风格可配置；通知/时间戳/Agent Logs 与 Chat Debug view（原始 system prompt/工具载荷）透明化设施齐全。

### 4.5 可借鉴清单

| 优先级 | 借鉴项 | 说明 |
|---|---|---|
| **P0** | Send 下拉三态：Queue / Steer / Stop-and-send + pending 拖拽重排 | 运行中干预标准件 |
| **P0** | 每请求 checkpoint + Restore/Redo + 变更摘要 | 与 Claude rewind 二选一或合并 |
| **P0** | 编辑历史请求（revert 后重发） | 轻量"改主意"路径 |
| **P0** | 审批范围（once/session/workspace/all future） | 信任记忆 |
| **P1** | 权限级别下拉（Default/Assisted judge/Bypass/Autopilot） | 与 Codex 三档同族 |
| **P1** | URL 两步审批 | prompt injection 防护 |
| **P1** | 敏感文件 glob 审批（.env 等） | 安全细节 |
| **P1** | 终端命令 allow/deny 正则规则 | 审批降噪白名单 |
| **P1** | 选区批注（Add Feedback + Submit）+ Mark as Reviewed | diff 审查补强 |
| **P1** | Changes dropdown（Branch/Uncommitted/All/Last agent turn） | 与 Codex 五档 scope 交叉验证 |
| **P2** | 通知双档 / Image carousel / Autopilot / Agent Logs | 后期 |

---

## §5 产品四：Cursor（Anysphere）

### 5.1 产品形态

VS Code 分支（Electron）桌面 IDE；三阶段演进：
- **1.0（2025-06-04）**：Background Agent GA + **Memory 首发** + Bugbot（注：Memory 首发于 1.0 而非 0.51；0.51 页面 404）
- **2.0（2025-10-29）**：新 Agent 界面、**Multi-Agents（8 并行）**、沙箱终端 GA、Cloud Agents
- **3.0（2026-04-02）**：**Agents Window**——独立于 IDE 的 agent 中心窗口，跨本地/worktree/云/SSH 并行

来源：https://cursor.com/changelog/1-0、/2-0、/3-0

### 5.2 GUI 信息架构

```
IDE 模式：Activity Bar + 编辑器（多 Tab）+ 右侧 Agent/Chat 面板（多 Tab 会话，每会话独立模型）
Agent 会话流内（上到下）：
  用户消息 → 思考块(可折叠) → 工具调用卡片(可折叠,带状态)
  → diff 卡片(逐文件展开/折叠, Accept|Reject) → todo 卡片
  → 上下文用量指示(会话末尾) → 输入框(模型选择 + @ pill)
Agents Window(3.0)：agent 列表/会话中心式布局，跨 本地|worktree|云|SSH
```

### 5.3 关键交互模式清单（16 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | 三模式（Chat/Composer/Agent） | 按任务强度选择 | 能力边界明确 |
| 2 | @ 上下文选择（pills 内联显示） | @Files @Docs @Codebase @Folders；2.0 后 agent 自取上下文 | 显式控制上下文边界 |
| 3 | **内嵌 diff 审查** | Agent 消息内 diff 卡片，逐文件展开，Accept/Reject；2.0 跨文件总览 | 细粒度把关 |
| 4 | **终端共享 + 自动执行审批** | Agent 用你的原生终端，后台创建可 Focus 接管；auto-run 采用 **allowlist**；2.0 macOS 默认沙箱终端 | 安全与速度平衡 |
| 5 | Background/Cloud Agents | Cmd/Ctrl+E 控制面板，云端独立环境并行，随时看状态/发消息/接管 | 并行+异步 |
| 6 | **Memory（记忆）** | 1.0 首发：记忆会话事实、per-project、Settings→Rules 管理；1.2 后台生成的记忆需要用户批准 | 跨会话连续性+用户控制 |
| 7 | Plan Mode | 先出计划再执行；2.0 可后台构建、并行 agent 出多个计划 | 先对齐再动手 |
| 8 | **Multi-Agents 并行** | 单 prompt 最多 8 agent 并行，git worktree/远程隔离；/worktree、/best-of-n | 多方案探索 |
| 9 | **消息排队与打断** | Alt+Enter 排队、Cmd+Enter 立即打断；排队消息在工具调用间隙执行 | 不打断即改方向 |
| 10 | **Compact 模式** | 隐藏工具图标、diff 默认折叠、空闲自动隐藏输入框 | 长会话密度可控 |
| 11 | Checkpoint 恢复 | git checkpoint 机制 | 出错可回退 |
| 12 | **上下文用量可见** | 1.3 会话结束显示使用量；1.4 用量汇总（超 50% 配额提醒） | 成本/质量预期 |
| 13 | 每 agent 独立模型 | 每 Tab 不同模型，fork 保留模型 | 分任务用不同模型 |
| 14 | Bugbot → Agent Review | 自动 review PR，评论点击 Fix in Cursor 回编辑器带预填 prompt | review→修复闭环 |
| 15 | **Side Chats + 会话搜索** | /side /btw 旁路只读 agent；Cmd+K 全局搜索历史转录；Cmd+F 会话内 | 不中断+可检索 |
| 16 | Voice / Design Mode | 语音控制；浏览器标注 UI 元素送 agent | 降低交互成本 |

### 5.4 设计风格

深色默认；高信息密度 + 可调（思考/工具/diff 全可折叠）；Compact 模式；上下文 pills、内联代码块、Mermaid 图表表格渲染、todo 卡片、diff 卡片、消息尾部操作菜单（回复/复制/duplicate 会话、导出 markdown）。

### 5.5 可借鉴清单

| 优先级 | 功能 | 说明 |
|---|---|---|
| **P0** | 对话流内嵌 diff 卡片（展开/折叠/逐文件 Accept-Reject） | diff review 核心原型 |
| **P0** | 工具调用流式卡片（状态/耗时/可折叠） | 过程可观察性基础 |
| **P0** | 终端命令审批：auto-run allowlist + 沙箱 | 审批模块直接对应 |
| **P0** | 消息排队/打断（Alt+Enter / Ctrl+Enter） | 低打断 steerability |
| **P0** | 每 agent 独立模型选择 + 每会话 Tab | Thread 概念直接映射 |
| **P0** | Plan 模式 | 规划与执行分离 |
| **P1** | Agent 侧栏（前台+后台/云端一栏管理） | 子代理树+恢复 |
| **P1** | 上下文用量/成本指示器（超 50% 提醒） | 成本透明 |
| **P1** | 上下文 pills | 显式上下文控制 |
| **P1** | Checkpoint 回滚、会话导出 markdown / duplicate | 低成本高价值 |
| **P2** | 会话转录搜索（Cmd+K）、Voice / Design Mode | 后期 |

---

## §6 产品五：Windsurf → Devin Desktop 2.0（Cognition）

### 6.1 产品形态

原名 Windsurf（Exafunction，VS Code 分支），2025 年被 Cognition 收购，现 **Devin Desktop 2.0**（跨平台桌面 IDE）。三类本地 agent：**Cascade**（旗舰，Code/Chat 模式）、**Devin Local**、任意 **ACP 第三方 agent**；另有云端 Devin 会话内嵌。来源：https://docs.devin.ai/desktop/getting-started

### 6.2 GUI 信息架构

```
传统 IDE 模式：VS Code 布局 + Cascade 右侧面板
  Cascade 面板：顶部下拉(多 Cascade 切换) + 会话转录
  → 消息内：工具调用卡(auto-continue) / todo 列表 / checkpoint 时间轴
  → 输入框下：模式选择器(Code|Plan|Ask) + 权限级别选择器 + 模型选择
2.0 新模式：
  Agent Command Center: Kanban 看板(进行中/阻塞/待 review)，本地+云端同列
  Spaces: 会话/PR/文件/上下文按任务聚合(拖拽归组、Cmd+\ 分屏、上下文跨会话继承)
  会话侧栏: 分组/排序/重命名; 运行中会话锁定(只读灰显)
```

来源：https://docs.devin.ai/desktop/agent-command-center、/desktop/spaces、/desktop/cascade/cascade

### 6.3 关键交互模式清单（16 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | Code/Chat 双模式（+2.0 的 Plan/Ask） | 输入框下模式选择器，⌘+. 切换；Chat 只问答、Code 全工具、Ask 只读 | 明确能力边界 |
| 2 | **计划→执行制度化** | Plan 模式：探索→澄清问题（多选卡片）→**产出外部 markdown 计划文件**（~/.devin/plans，会话间持久）→ 点 **Implement** 转 Code；megaplan/ultraplan 强制深度规划 | 计划成为一等产物 |
| 3 | **终端权限 4 级制** | Disabled / Allowlist Only / Auto / Turbo；allow/deny 列表（团队+个人合并，deny 优先） | 完整授权谱系 |
| 4 | **命名检查点与回滚** | 每 prompt 后 checkpoint；**hover 原消息点 revert 箭头**；命名快照；回滚不可逆警告 | 任意步骤可退 |
| 5 | Todo 列表 + 后台规划 agent | 对话内 todo 卡实时跟踪；专用规划 agent 后台细化长期计划 | 长任务不迷失 |
| 6 | 排队消息 | agent 工作时输入排队，Enter 发送、再 Enter 执行、可编辑/删除 | 低打断控制 |
| 7 | Auto-continue | 20 次工具调用上限后可一键 continue 或自动续跑 | 长轨迹不中断 |
| 8 | Real-time awareness | 感知编辑器/终端选择，Continue 接续 | 免重述 |
| 9 | **@-mention 体系** | @web/@docs、@terminal、@历史会话（**只取相关摘要+片段**）、@计划文件、@rules、@problems | 上下文即插即用 |
| 10 | 终端深度集成 | 专用终端（固定 zsh）；选中报错 Ctrl+L 送 agent；Command 模式 Ctrl+I 自然语言生成 CLI 命令 | agent 与人不打架 |
| 11 | **Agent Command Center（Kanban）** | 本地+云端 agent 统一看板；运行中会话锁定只读；筛选/排序/分组 | "agent 即任务" |
| 12 | **Spaces 任务聚合** | 拖拽会话归组；Space 内新会话继承共享上下文；切换恢复原样 | 大任务组织方式 |
| 13 | 并行 Cascade / Arena | 多 Cascade 并行（同文件竞争警告，建议 worktree）；Arena 多实例对比 | 多方案探索 |
| 14 | 云委托（Devin in Desktop） | 本地做好计划一键发云端执行；send queue；断线 Reconnect 横幅 | 本地↔云端接力 |
| 15 | 记忆与规则 | 自动记忆（global/workspace/系统级作用域）+ 用户规则 | 个性化持续化 |
| 16 | 工作流与快速审查 | Workflows（markdown 定义可复用任务流程）；Quick Review 对本地改动跑 agentic review | 模板化 |

### 6.4 设计风格

VS Code 继承 + 深色默认；**2.0 起看板化 + 空间化布局**——从"编辑器+面板"走向"任务工作台"；消息内嵌工具卡/todo/checkpoint 时间轴；**回滚入口直接挂消息上**（revert 箭头），不藏菜单。品牌色 Codeium 紫色系（未直接验证，推断）。

### 6.5 可借鉴清单

| 优先级 | 功能 | 说明 |
|---|---|---|
| **P0** | **计划文件持久化**（外部 markdown，跨会话/@复用，Implement 按钮） | 规划与执行分离最佳参考 |
| **P0** | **回滚入口挂在消息上**（hover revert + 命名快照） | 恢复功能交互成本极低 |
| **P0** | 终端权限 4 级（Disabled/Allowlist/Auto/Turbo）+ allow/deny 列表 | 审批模块完整谱系 |
| **P0** | 模式选择器 Code/Plan/Ask + 权限选择器放输入框下 | 显式模式切换 |
| **P0** | Todo 列表 + 后台规划 agent | 长任务进度可视化 |
| **P0** | 排队消息（可编辑可删） | 低打断控制 |
| **P1** | Agent Command Center Kanban | 多 agent 工作台最佳参考 |
| **P1** | Spaces 任务聚合（拖拽+上下文继承） | 项目级工作台 |
| **P1** | @terminal / @历史会话（片段检索） | 上下文效率 |
| **P1** | 运行中会话锁定只读 | 防误操作细节 |
| **P2** | Arena / Workflows | 后期 |

---

## §7 产品六：Devin（Cognition，云端 AI 程序员）

### 7.1 产品形态

**纯云端 Web 工作台**（app.devin.ai）+ Slack/Teams/Jira 集成 + CLI + MCP；Devin 跑在隔离 VM（自带桌面/浏览器/终端），用户 Web 界面"看它干活、必要时接管"。以 session 为中心，**完全不是 IDE 插件**。来源：https://docs.devin.ai/

### 7.2 GUI 信息架构

```
Home: 任务输入 + 模板入口 + 计划/知识管理入口
会话中心(Sessions): 列表(搜索/筛选/tag/归档/终止/ACU 用量) + 会话详情
会话详情(核心):
┌────────────────────────┬──────────────────────────┐
│ 对话流(进度更新、步骤、   │ 三视图 Tab:              │
│  todo/checkpoint 点)     │  · Shell(命令历史+输出)   │
│  · 计划(可并行子会话)     │  · IDE(实时 VSCode,可接管)│
│  · 请求审批/提问          │  · Desktop(交互式浏览器)  │
│  · 证据(截图/录屏/PR)     │  · Progress(统一时间线)   │
│  · 结束语/报告            │                          │
└────────────────────────┴──────────────────────────┘
企业层: Knowledge / Playbooks / Schedules / Admin(Guardrails/RBAC/Audit)
```

### 7.3 关键交互模式清单（16 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | **会话中心** | 创建/恢复/归档/终止 session；tag；ACU 用量监控；AI 生成 session insights | 异步任务池 |
| 2 | **操作实时可视化（三视图）** | Shell/IDE/Browser 并排实时展示 agent 动作；随时停止接管 | 全程可观察可干预 |
| 3 | **Progress 统一时间线** | 点击任何进度步骤，聚合该步的 shell/编辑/浏览器活动 | 单步因果链清晰 |
| 4 | Shell 命令历史 | 全部命令+输出预览+复制；点击命令**时间导航**到任意时点；只读/可写切换 | 复盘 |
| 5 | IDE 接管 | 内嵌完整 VSCode；停止会话后完全接管；恢复前提示改动 | 半自动协作 |
| 6 | Interactive Browser | 观看/接管浏览器：CAPTCHA、MFA、复杂导航；截图/录屏回传；cookie 会话内持久 | 前端验证通道 |
| 7 | 规划与执行分离 | 会话内 todo 步骤；**Managed Devins 提案→用户批准→并行子会话**（coordinator 监督、ACU 限额） | 大任务并行+闸门 |
| 8 | 审批流 | 并行子会话 proposal→approve；PR 默认创建；Devin Review 跑 agentic 评审 | 交付物受控 |
| 9 | **证据交付** | 自动测试 + **视频录屏**作为完成证明；截图；PR 链接与说明 | 异步信任建立 |
| 10 | Playbooks | 成功会话沉淀为可复用 playbook（含自动化宏/触发器） | 团队经验制度化 |
| 11 | Knowledge 知识库 | 会话自动产出知识建议，组织级去重/合并/冲突解决 | 跨会话经验沉淀 |
| 12 | 会话分析 | 用 Devin 分析过往会话：ACU 花在哪、死胡同、改进 prompt | 自学习闭环 |
| 13 | Schedules | cron 定时/一次性自动会话 | 无人值守 |
| 14 | 异步协作入口 | Slack/Teams tag 开任务；CLI /handoff；服务器端消息队列（Cmd+Enter 排队，刷新不丢） | 把任务"扔"给 AI |
| 15 | 企业治理 | RBAC、Guardrails、审计日志、IP 名单、远程索引、Outposts 私有部署 | 企业信任 |
| 16 | Stacked PRs | 大改动拆成有序可 review 的 PR 栈 | 可审查性 |

### 7.4 设计风格

Web 应用（非 Electron），宽屏工作台式布局：左会话列表 + 右详情（对话+三视图）；深色默认；信息密度中高；强调"进度步骤 + 证据（截图/录屏）"可视化；交互重心从"编辑器"转移到"会话/任务"（像素细节未直接验证，推断）。

### 7.5 可借鉴清单

| 优先级 | 功能 | 说明 |
|---|---|---|
| **P0** | **会话中心**（列表/搜索/tag/归档/恢复/用量） | Thread 列表+恢复直接蓝本 |
| **P0** | 进度步骤 + 统一时间线（每步聚合其活动） | 子代理树节点可复用 |
| **P0** | 计划提案→用户批准→并行子会话（coordinator 模式） | 子代理树+审批合体 |
| **P0** | 任务结束**证据交付**（截图/录屏/PR） | 异步 agent 价值放大器 |
| **P1** | 命令历史 + 时间导航、只读/可写接管 | 恢复/复盘 |
| **P1** | Playbooks（会话→模板）、会话分析（成本/死胡同） | 差异化亮点 |
| **P2** | 定时调度 / 知识库自动沉淀 | 后期 |

---

## §8 产品七：字节 TRAE（及豆包 MarsCode 体系）

### 8.1 产品形态

已分化为 **TraeCode**（AI IDE）与 **TraeWork**（AI 办公工作台，Code/Work 双模式，网页/桌面/移动三端）；中国站 trae.com.cn 与国际站 trae.ai 并行；MarsCode 文档已并入 TraeCode/TraeWork 体系。原"Builder 模式"由 **SOLO 模式**（AI 主导全流程：需求理解→代码生成→测试→成果预览）+ 内置智能体 Agent 承载。来源：https://docs.trae.cn/llms.txt

### 8.2 GUI 信息架构（SOLO 模式三栏工作台）

```
┌─────────────────────────────────────────────────────────────┐
│ 模式切换(SOLO/IDE) │ 顶部导航/账户 │ 展开工具面板 ▣          │
├──────────┬──────────────────────┬──────────────────────────┤
│ 任务管理   │ AI 对话面板            │ 工具面板(实时跟随)         │
│ 面板       │  ─ 对话流(待办清单)    │  编辑器 │ 文档 │ 终端      │
│ (多任务    │  ─ 审批卡片(内嵌)     │  浏览器 │ 代码变更 │      │
│  并行/树)  │  ─ 输入框(权限模式)    │  Figma │ 智能体 │ MCP     │
│           │                       │  ▲工具只读，跟随AI工作阶段 │
└──────────┴──────────────────────┴──────────────────────────┘
  Diff 视图 / 代码变更窗口（点击"查看变更"弹出，独立窗口）
```

**工具面板实时跟随模式**：AI 处于什么工作阶段（写代码/写文档/跑终端/预览网页），面板自动切换对应工具展示产物；处理期工具只读。来源：https://docs.trae.cn/ide_solo-mode.md

### 8.3 关键交互模式清单（12 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | IDE ⇄ SOLO 模式切换 | 左上角一键切换传统 IDE 与 AI 主导 | 按复杂度选协作深度 |
| 2 | **工具面板实时跟随** | AI 工作阶段变化自动切工具视图；处理期只读 | 全程可视化 |
| 3 | **审批卡片（对话流内嵌）** | 访问超权限文件/危险命令时对话流内嵌审批卡片，逐一确认 | 关键操作人控不断流 |
| 4 | **三档权限模式** | 手动审批 / 自动审批（LLM Guardian 代审）/ 完全访问；输入框左下角切换 | 信任度可调 |
| 5 | **Diff 视图（代码变更窗口）** | 点击"查看变更"弹出：文件数、变更行数、文件列表、逐文件 diff | 变更范围一目了然 |
| 6 | **对话流节点自动折叠** | 已完成执行节点自动折叠为摘要（可展开、可开关） | 长任务不刷屏 |
| 7 | Plan 工作流（/Plan） | 分析→在 `.trae/documents/` 生成规划文档→确认后执行；可手改 | 防跑偏 |
| 8 | **Spec 工作流（/Spec）** | 三件套：大纲 spec.md + 任务列表 tasks.md + 验收清单 checklist.md（`.trae/specs/`），随执行自动更新 | 方案+验收标准对齐，文档即资产 |
| 9 | Goal 工作流（/Goal） | 定义目标，AI 多轮续跑每轮自评；"操作岛台"查看/编辑/暂停/删除 | 长任务自动推进 |
| 10 | 多任务并行 + 工作树 | 多任务在隔离 Git worktree 执行避免冲突 | 并行不串扰 |
| 11 | 子智能体 Subagent | Markdown（YAML frontmatter）定义，独立上下文窗口 | 角色化分工 |
| 12 | 记忆/规则/技能/命令 + Hook | 全局+项目两级记忆、Rules、SKILL.md、斜杠命令；Hook 6 类事件触发 Shell | 个性化+自动化 |

### 8.4 设计风格

现代 IDE 风格，浅色为主的深/浅双主题；对话流节点卡片/气泡呈现，审批独立卡片内嵌；中文语境优化明显（完整中文文档、低门槛设计、模板库、技能市场）。完整设计 token 官方未公开（信息不足）。

### 8.5 可借鉴清单

| 优先级 | 可抄对象 | 落点 |
|---|---|---|
| **P0** | 工具面板 + 实时跟随 | 右侧"活动面板"：AI 写代码→自动显示编辑文件；跑命令→显示终端；处理中只读 |
| **P0** | 审批卡片内嵌对话流 | 权限请求在 Thread 流内以卡片出现（非模态弹窗） |
| **P0** | 三档权限模式 | 输入框旁小控件 + 设置页全局默认 |
| **P0** | Diff 视图"查看变更"按钮 | 每个执行节点尾部挂"查看变更" |
| **P1** | 对话流节点自动折叠 | 完成节点折叠为一行摘要（可展开） |
| **P1** | Plan/Spec 文档化工作流 | 执行前生成 plan.md + Spec 三件套 |
| **P1** | Goal 操作岛台 | 常驻底部目标条 |
| **P1** | 多任务并行 + Worktree 隔离 | 项目级多 Thread 并行 |
| **P2** | Subagent Markdown 定义 / 行内+侧边双对话 | 后期 |

---

## §9 产品八：通义灵码 Qoder（阿里）

### 9.1 产品形态

定位"**智能体自主开发工作台**"；Qoder CN（qoder.com.cn，原通义灵码 2026-05-20 更名）与国际站 qoder.com 并行；支持 Qwen/GLM/DeepSeek/Kimi/MiniMax 模型切换。产品族：Desktop（AI IDE）、JetBrains 插件、CLI、Cloud Agents、QoderWork、QoderWake（7×24 数字员工）、Mobile。**一次会话流中可自由切换 Ask/Edit/Agent 三模式**。来源：https://docs.qoder.cn/

### 9.2 GUI 信息架构

```
编辑器区(文件/代码)  │  侧边面板(AI 会话)
                     │  ─ 模式切换: Ask ⇄ Edit ⇄ Agent
                     │  ─ 对话流(规划卡片/待办清单/审批)
                     │  ─ 输入框(模型选择器/优化提示词✨/上下文)
底部: 终端(Agent 命令执行, 运行/取消按钮)
Quest 模式(独立工作流): 输入目标 → 需求澄清 → Spec 共创 → 执行 → 验证
  支持 Local + Worktree 并行、长程运行(最高 26h)、移动端远程查看/审批
```

### 9.3 关键交互模式清单（11 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | Ask/Edit/Agent 三模式会话 | 同会话切换：问答/多文件编辑/自主智能体 | 成本速度自主度按需 |
| 2 | 规划卡片（/plan） | 复杂任务先生成方案规划展示审阅，确认后执行 | 先对齐 |
| 3 | **待办事项列表（聊天底部）** | 状态图标：空心圆=未开始、旋转圆=进行中、复选=完成；新需求自动追加 | 进度一目了然 |
| 4 | **终端命令执行审批** | 每次执行前确认：单击"运行"发送至 IDE 终端、"取消"跳过；后台命令带"后台运行"标记 | 确定性+不阻塞 |
| 5 | Auto-Run 命令白名单 | 设置页配置允许自动执行的命令 | 高信任免审批 |
| 6 | MCP 工具执行前询问 | 每次调用前确认（执行/跳过） | 外部工具可控 |
| 7 | **一键优化提示词 ✨** | 输入框旁"优化输入"：生成目标/约束/实现指导的结构化提示词，可编辑/撤销 | 低门槛高质量 |
| 8 | 工程自动感知 | 自动感知框架/技术栈/相关文件/报错 | 少一步操作 |
| 9 | 快照回滚 + 多次迭代 | 工程级多文件变更后快照回滚 | 可后悔 |
| 10 | Diff View | 编辑/Agent 完成后展示变更 diff | 变更审查 |
| 11 | 专家团/多智能体协同 | 前后端/数据库/运维/测试专家协作；Quest 中 Repowiki + Subagent 端到端 | 领域分工 |

### 9.4 设计风格

官网现代深色科技风（深底+渐变+大卡片+圆角）；IDE 类 VS Code 布局，会话面板卡片化（规划卡/待办/审批均流内卡片）；移动端简化布局；企业级取向（合规/审计/知识库/席位管理/报表）。

### 9.5 可借鉴清单

| 优先级 | 可抄对象 | 落点 |
|---|---|---|
| **P0** | 待办三态图标（空圆/旋转圆/复选） | 子代理树节点+步骤列表统一三态 |
| **P0** | 终端命令审批（运行/取消 + 后台运行标记） | 审批面板命令卡片 |
| **P0** | 规划卡片先审后执行 | 规划以卡片插入对话流 |
| **P1** | 一键优化提示词 ✨ | 输入框附魔棒 |
| **P1** | 三模式会话（Ask/Edit/Agent） | 会话级模式选择器 |
| **P1** | Auto-Run 白名单 / 快照回滚 / 工程自动感知 | 审批+恢复+上下文 |
| **P2** | 专家团 / 移动端审批延伸 / 意图路由 | 后期 |

---

## §10 产品九：Replit Agent（云端 IDE 内的全栈 Agent）

### 10.1 产品形态

网页云端 IDE（Project Editor）+ 桌面客户端；Agent 是"会话式构建"能力：自然语言从 0 构建 Web/移动端/幻灯片应用，自带测试、部署、数据库、域名全套。计费 credits 制。来源：https://docs.replit.com/replitai/agent

### 10.2 GUI 信息架构

```
┌────────────────────────────────────────────────────────────┐
│ 左侧: Thread 列表(主+后台任务线程, 带状态指示器)│ 中部: 聊天 │
│ 右部: 预览(可交互) │ 底部: 任务看板(可展开)                  │
├────────────────────────────────────────────────────────────┤
│ 任务看板: Drafts │ Active │ Ready │ Done  (Kanban 列)        │
│   每卡: 标题+描述摘要+状态图标+时间+三态点菜单                │
│   Ready 卡审查抽屉: 工作日志+测试结果+预览+Apply/Dismiss     │
└────────────────────────────────────────────────────────────┘
 输入框: 模式选择器(Plan/Build, 左下) + Agent Modes(Lite/Economy/Power+Turbo)
```

### 10.3 关键交互模式清单（12 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | **任务清单/看板（Drafts→Active→Ready→Done）** | Agent 将大请求拆任务卡，四列流动；每卡含计划（View plan） | 全程可视化 |
| 2 | **任务规划→接受/修订** | 提议一组任务（各含详细计划），Accept tasks（后台并行）/ Revise plan | 执行前整体审阅 |
| 3 | **隔离副本执行** | 每后台任务在项目隔离副本运行，主版本不动 | 并行零风险 |
| 4 | **Ready 审查抽屉** | 工作日志、测试结果、实时预览 → Apply changes to main version / Dismiss | 合并前完整审查 |
| 5 | **依赖自动排队** | 任务间依赖自动检测，依赖任务 Queued 等前置（并行上限 Core1/Pro10） | 并行不混乱 |
| 6 | **每任务设置菜单** | Auto-apply / Auto-approve plan / Apply / Rename / Review changes / Cancel（固定宽度） | 单次授权 |
| 7 | **Checkpoints** | 功能完成/里程碑/稳定态自动打点，AI 生成描述+时间戳+成本；**回滚/前滚双向**，回滚恢复对话上下文，数据库可选恢复 | 游戏存档式 |
| 8 | Plan Mode / Build Mode | 输入框左下模式选择器；Plan 生成带优先级依赖的任务清单，Start building 一键切 | 先规划后动工 |
| 9 | Agent Modes（Lite/Economy/Power+Turbo） | 成本/速度/质量显性权衡；高级设置含 App testing / Code optimization 开关 | 成本透明 |
| 10 | App Testing | Agent 真实浏览器自动测试并自动修复 | 质量闭环 |
| 11 | Follow-up tasks + Message Queue | 任务完成推荐后续任务；agent 忙时可排队多条消息按序处理 | 连续指挥 |
| 12 | Voice / Web Search / Skills | 语音输入、联网、Agent Skills | 低门槛 |

### 10.4 设计风格

米白/浅灰低对比底色（暗色 #1E1E1F 类）；状态色语义明确（Active 蓝、Ready 绿、Draft 灰、Applying 紫、Done 绿点）；小圆角（6-12px）、细边框、状态徽标；卡片化核心（任务卡/审查抽屉/规划卡/设置菜单全部低阴影卡片）；聊天流与看板双视图共存。

### 10.5 可借鉴清单

| 优先级 | 可抄对象 | 落点 |
|---|---|---|
| **P0** | Drafts→Active→Ready→Done 任务看板 | Thread 视图顶部/侧栏看板；Ready=待审批，Apply=合并 |
| **P0** | 隔离副本 + Apply/Dismiss | 变更落隔离区（worktree/副本），审查通过才 Apply |
| **P0** | Checkpoint 双向回滚（含对话上下文恢复） | 恢复功能照此设计 |
| **P0** | Ready 审查抽屉（工作日志+测试+预览） | diff review 信息架构 |
| **P1** | Plan/Build 模式选择器、依赖自动排队、单次授权菜单、Agent Modes 分段选择器 | 规划/审批/成本 |
| **P2** | Follow-up tasks、Message Queue、状态色系统 | 后期 |

---

## §11 产品十：Vercel v0 与 Bolt.new（网页式 GUI Agent）

### 11.1 产品形态

- **v0**：纯网页 chat，生成高保真 UI 与全栈应用（Next.js/Tailwind/shadcn），一键部署 Vercel 或开 PR；**每次修改产生新版本（version），可 diff、可回退**
- **Bolt.new**（StackBlitz）：网页 chat，浏览器内直接运行全栈项目（WebContainers），"聊天即运行"
- 共同点：无本地 IDE 概念，浏览器内聊天 + 实时可交互预览

### 11.2 GUI 信息架构

```
提示表单(Prompt bar): 输入框+附件+语音🎤+Design+模式/输出类型
├──────────────────────────┬─────────────────────┤
│ 聊天/消息流(左)           │ 预览 Preview(右)      │
│  ─ 生成中进度指示         │  ─ 可交互真实运行     │
│  ─ 版本化(可 diff/回退)   │  ─ Design Mode 叠加  │
│  ─ 排队提示(最多10条)     │   选择/编辑工具       │
└──────────────────────────┴─────────────────────┘
Bolt 首页: "Plan" / "Build now" 双按钮 + 输出类型 + import Figma/GitHub
```

### 11.3 关键交互模式清单（10 条）

| # | 功能 | 描述 | 价值 |
|---|------|------|------|
| 1 | 聊天+实时预览双栏 | 左侧对话、右侧真实运行应用；改代码预览即时刷新 | 即时反馈闭环 |
| 2 | **版本化迭代** | 每次生成/Apply 产生新版本，可 diff、继续迭代、一键回退 | 迭代可追溯 |
| 3 | **Prompt 排队（最多 10 条）** | 生成中继续输入排队，按序执行；可重排/编辑/删除 | 连续指令不等待 |
| 4 | **Design Mode** | 预览叠加设计工具：hover 高亮→点击选中→面板微调或自然语言指令（自动附带选中元素截图） | 所见即所得改 UI |
| 5 | **待定编辑 + Before/After** | 面板调整先 pending，Undo/Redo/Reset、前后对比开关；Apply 才生成新版本 | 提交前反悔 |
| 6 | Inspect 切换 | Cmd+I 在"选择元素"与"正常操作应用"间切换 | 选取不误触 |
| 7 | Tailwind-aware 编辑 | 检测 Tailwind 时面板呈现兼容值 | 修改可落代码 |
| 8 | 语音输入 | 麦克风转写插入输入框，可编辑后发送 | 低门槛 |
| 9 | 自动修复 | v0 智能诊断自动修错；Bolt 自动测试/重构/迭代 | 错误不打断 |
| 10 | Plan/Build 双入口 | 首页两种开始方式 + 输出类型 + Figma/GitHub 导入 | 先想后做 vs 直接做 |

### 11.4 设计风格

v0：Vercel 系黑白极简、大留白、暗色为主、细字重、shadcn 风格组件；Bolt：深色科技风、渐变光效、圆角大卡片、skeleton/加载动效丰富。**共同本质：预览区是主角，聊天区是驱动器；生成过程用视觉进度指示让等待可接受。**

### 11.5 可借鉴清单

| 优先级 | 可抄对象 | 落点 |
|---|---|---|
| **P0** | 版本化迭代（每次变更=新版本，可 diff/回退） | Thread 内每次 Agent 变更生成"版本卡" |
| **P0** | 预览-聊天双栏心智 | 桌面右侧常驻"运行预览"区 |
| **P1** | 元素选择→对话修改（Design Mode 核心） | 预览中 hover 高亮+选中+发到对话 |
| **P1** | 待定编辑 + Before/After + Undo/Redo | 视觉调整先攒 pending |
| **P1** | Prompt 排队（可重排）/ 生成中骨架进度指示 | 输入框+聊天节点 |
| **P2** | 语音输入 / 一键部署/开 PR / Plan-Build 双入口 | 后期 |

---

## §12 合并可借鉴清单（去重，按 P0/P1/P2）

### P0（首版必须有，10 项）

1. **对话流内嵌 diff 卡片**：逐文件展开/折叠、Accept/Reject、多文件总览（Cursor + TRAE）
2. **工具调用流式卡片**：状态/耗时/可折叠，附 auto-continue 按钮（Cursor + Devin Desktop）
3. **终端命令审批：4 级自动执行**（Disabled/Allowlist/Auto/Turbo）+ allow/deny 列表 + 后台运行标记（Devin Desktop + Qoder + TRAE）
4. **检查点与回滚**：每步骤 checkpoint、**revert 入口直接挂消息上**、命名快照、恢复不可逆警告、双向导航（Devin Desktop + Claude + Replit + Copilot）
5. **计划模式**：计划产出外部持久文件，一键 Implement 切换执行；计划可后台构建、多方案（Devin Desktop + Cursor + TRAE/Qoder）
6. **消息排队/打断**：Send 三态（Queue/Steer/Stop-and-send）+ Alt+Enter 排队（可编辑）+ Ctrl+Enter 打断（Copilot + Cursor）
7. **Todo 卡片 + 步骤时间线**（每步聚合其操作）（Cursor + Devin + Qoder）
8. **会话中心**：列表/搜索/恢复/归档/tag/用量（Devin + Cursor + Codex）
9. **多 agent 并行 + 隔离**（worktree），同文件冲突预警（Devin Desktop + Cursor）
10. **@ 上下文 pill 体系**：@Files/@Codebase/@Docs/@Web/@Terminal/@历史会话（Cursor + Devin Desktop）

### P1（第二版，12 项）

11. Agent 管理侧栏/Kanban（本地+后台+云端一栏）（Cursor + Devin Desktop）
12. 上下文窗口用量/成本指示器（会话内 + 超 50% 提醒 + usage ring）（Cursor + Claude + Codex）
13. 模式/权限选择器置于输入框下（Code/Plan/Ask + 权限级别）（Devin Desktop + Qoder）
14. 运行中会话锁定只读 + 侧栏筛选分组（Devin Desktop + Claude）
15. 后台 agent + 系统通知（完成/需输入/待 review 双档）（Cursor + Copilot）
16. 计划文件在 @-mention 中可复用；会话导出 markdown、duplicate 分支（Devin Desktop + Cursor）
17. 记忆与规则：自动生成需用户批准、per-project 管理（Cursor + Windsurf）
18. 命令历史 + 时间导航复盘（Devin）
19. Playbooks/工作流模板（markdown 定义）（Devin + Devin Desktop）
20. diff 行内注释闭环 + 五档 scope（含 Last turn）（Codex）
21. 会话管理四件套：重命名/钉选/归档/搜索 + 消息级 fork（Codex）
22. 对话流节点自动折叠 + Transcript 视图模式（TRAE + Claude）

### P2（储备，8 项）

23. 语音输入（Cursor + v0）
24. 浏览器标注/Design Mode（截图选区+元素送 agent）（Cursor + v0）
25. 同任务多模型并行对比（/best-of-n、Arena）（Cursor + Devin Desktop）
26. 证据交付：截图/录屏回传会话（Devin）
27. 会话转录全文搜索（本地索引）（Cursor + Codex Cmd+G）
28. 定时调度 / 会话分析（Devin）
29. 侧聊 /side（Codex + Claude）
30. 跨会话消息 + 来源卡片（Claude）

---

## §13 竞品共通规律：独立 agent 工作台的"三支柱"

十款产品共同验证了"独立 agent 工作台"的三个支柱：

1. **可观察（Observability）**：流式工具卡 + diff 卡 + 步骤时间线 + todo 卡 + 上下文用量指示——agent 每步在做什么、花多少钱、剩多少上下文，全部可见
2. **可控（Controllability）**：计划→审批→执行 + 权限谱系（3-5 档）+ 回滚/检查点 + 消息排队/打断——用户始终掌握最终决定权，且干预成本极低
3. **可组织（Organizability）**：会话中心 + 多 agent 并行 + 任务聚合（Space/Kanban）+ 侧栏筛选分组——任务多了不迷路

**对 Phase G 的启示**：信息架构采用"项目/Thread（会话中心）→ 步骤时间线（节点流）→ diff/审批（内嵌卡片）"三层；交互直接复用 §12 的 P0 十项。

**国内 vs 国际差异**：国内产品赢在"企业采纳路径"（IDE 内嵌、合规、中文、模型可选），国际产品赢在"单任务体验闭环"（从想法到跑起来的完整可视化）。我们的桌面工作台应**取后者做交互骨架（任务卡+看板+检查点），取前者做能力底座（权限三档、白名单、模型切换）**。

---

## §14 与 Phase G 的映射（增强任务卡立项依据）

> 完整增强任务卡定义见 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md)（GX1–GX28）。

**纳入/不纳入的筛选原则**（为什么竞品 P0 不全等于我们的 GX P0）：
1. **只纳"与我们的架构（Electron + JSON-RPC + Thread 模型）直接可映射"的能力**——例如权限三档映射主链 B7、diff 注释映射 B8；"云端 VM / 浏览器接管 / 定时调度"类依赖我们当前没有的部署形态，不纳入
2. **只纳"主链完成后的增量"**——凡是主链 26 卡已覆盖的（如基础 diff review、审批、checkpoint 数据层）不在 GX 重复立项，GX 只补交互层与新增组件
3. **成本门槛**：零/低 LLM 成本优先（如 GX12 prompt suggestions 纯规则、GX18 follow-up 纯规则）；依赖大量 LLM 调用的（如 Devin 会话分析、知识库自动沉淀）列入 P2 储备或明确不纳入
4. **借鉴级别约束**：GX 卡的设计依据只允许 `official verified` / `secondary evaluation` 级来源；`inference` 级（设计哲学、视觉推断）仅作风格参考，不得冻结为协议或安全语义
5. **竞品仅为 UI 依据**：本映射表中的竞品能力只回答"界面长什么样、交互怎么做"；**所有安全 / 回滚 / 协议 / 权限语义一律以原版 Phase G 的 B/H 卡 schema 与验收为准**（GX 卡中的"语义冻结"均指原版协议的语义，竞品模式不构成协议依据）

| 增强卡 | 功能 | 主要借鉴来源 | 前后端 |
|---|---|---|---|
| GX1 | 任务看板视图（Drafts/Active/Ready/Done） | Replit §10.3-1 | 前端 |
| GX2 | 审批卡片内嵌对话流 + 权限三档模式 | TRAE §8.3-3/4 + Codex §2.3-1 | 前端+后端 |
| GX3 | diff 行内注释闭环 + Review scope 五档（含 Last turn） | Codex §2.3-5/6 | 前端+后端 |
| GX4 | Checkpoint 回滚 UI（revert 挂消息/命名快照/双向导航） | Devin Desktop §6.3-4 + Replit §10.3-7 | 前端+后端 |
| GX5 | 消息排队/打断（Send 三态） | Copilot §4.3-1 + Cursor §5.3-9 | 前端 |
| GX6 | 工具调用流式卡片 + Todo 步骤时间线 + 节点自动折叠 | Cursor §5.3-3/10 + Qoder §9.3-3 | 前端 |
| GX7 | 上下文用量/成本指示器 + statusline | Codex §2.3-14/15 + Claude §3.3-12 | 前端+后端 |
| GX8 | 会话管理四件套 + 消息级 fork | Codex §2.3-9/10 | 前端+后端 |
| GX9 | Plan 文件持久化 + Implement 按钮 | Devin Desktop §6.3-2 | 前端+后端 |
| GX10 | 聊天侧栏浮层（plan/sources/files/summary） | Codex §2.3-12 | 前端 |
| GX11 | 运行中会话只读锁定 + 侧栏筛选分组 | Devin Desktop §6.3-11 + Claude §3.3-14 | 前端 |
| GX12 | Prompt suggestions（灰色示例输入） | Claude §3.4 | 前端 |
| GX13 | OS 通知双档（回复到达/需要确认） | Copilot §4.3-13 | 前端+后端 |
| GX14 | 模式选择器（Ask/Edit/Agent） | Qoder §9.3-1 | 前端+后端 |
| GX15 | Design Mode 元素选择（预览标注） | v0 §11.3-4/5 | 前端 |
| GX16 | 侧聊 /side | Codex §2.3-11 + Claude §3.3 | 前端+后端 |
| GX17 | 版本卡（每次变更=新版本，diff/回退） | v0 §11.3-2 | 前端 |
| GX18 | Follow-up 任务推荐 | Replit §10.3-11 | 前端+后端 |

---

## §15 来源清单（官方来源，抓取日期 2026-08-10）

- OpenAI Codex：https://github.com/openai/codex ；https://learn.chatgpt.com/codex/app 、/cli 、/projects 、/permission-modes 、/developer-commands 、/code-review 、/artifacts-viewer 、/whats-new
- Claude Code：https://code.claude.com/docs/en/overview 、/desktop 、/interactive-mode 、/checkpointing 、/permission-modes
- GitHub Copilot：https://code.visualstudio.com/docs/copilot/copilot-chat ；/docs/agents/run/agents-window 、/approvals 、/review-code-edits ；https://docs.github.com/en/copilot/using-github-copilot/coding-agent
- Cursor：https://cursor.com/changelog/0-50 、/1-0 、/1-2 、/1-3 、/1-4 、/2-0 、/3-0
- Devin Desktop / Windsurf：https://docs.devin.ai/desktop/getting-started 、/desktop/cascade/cascade 、/desktop/cascade/modes 、/desktop/terminal 、/desktop/agent-command-center 、/desktop/spaces 、/desktop/devin 、/desktop/cascade/memories 、/desktop/cascade/workflows 、/desktop/cascade/arena 、/desktop/cascade/worktrees 、/desktop/quick-review
- Devin 云：https://docs.devin.ai/ 、/work-with-devin/devin-session-tools 、/work-with-devin/advanced-capabilities 、/cloud/outposts/overview
- TRAE：https://docs.trae.cn/llms.txt 、/ide_solo-mode.md 、/ide_tool-panel.md 、/ide_spec-and-plan-workflows.md 、/ide_permission-and-approval.md 、/ide_subagents.md 、https://www.trae.ai/ 、https://www.trae.com.cn/
- Qoder：https://docs.qoder.cn/user-guide/agent.md 、/user-guide/overview-of-chat.md 、/user-guide/qodercn-quest-overview.md 、/user-guide/edit.md 、/user-guide/diffview.md 、https://qoder.com.cn/ 、https://www.aliyun.com/product/lingma
- Replit：https://docs.replit.com/replitai/agent 、/core-concepts/agent/task-system.md 、/features/agent/task-board.md 、/features/agent/plan-mode.md 、/features/version-control/checkpoints-and-rollbacks.md 、/features/agent/agent-modes.md 、/features/platforms/desktop-app.md
- v0：https://v0.dev/docs/text-prompting 、/docs/design-mode ；Bolt.new：https://bolt.new/

**信息充分性声明**：Codex/Claude/Copilot/Devin/TRAE/Qoder/Replit/v0 官方文档信息充分；Cursor 视觉细节基于 changelog 描述（官方 docs 客户端渲染不可抓取）；各桌面应用精确色板/字体/间距官方未公开，均标注"信息不足"；Windsurf 收购后品牌为 Devin Desktop 2.0。
