# CLI 内存治理记录（2026-10-11）

本文记录 RxyCode CLI 三条内存治理路径、当前验证证据和未关闭事项；primary 集成日期为 2026-10-11。
内存变更现已通过 `apply_patch` 应用到 primary 工作树 `D:/agent-demo/RxyCode/RxyCode1_1_0`，分支为 `feat/phase-g-backend`。
相对 K3 提交 `53e5bae5`，primary 应用的是仅含内存变更的 delta（22 个修改文件、12 个新文件）；post-integration fresh proof 已完成，详见下文。
需重启 RxyCode 才会加载新代码；这不是发布。产品/文件版本仍为 1.4.2，`CHANGELOG_v1.4.3.md` 是此前已有的未来 changelog 文件。

## 范围与 K3 的区分

K3 已验收基线关注会话与模型操作的响应性、并发顺序和状态正确性。
其中包括 AppServer stdin 调度、任务快照代次、会话列表请求序号、模型身份和切换边界等。
本文不重写 K3 的原因分析，也不把 K3 的性能结果并入内存结果。

本文只记录三类内存持有：TUI transcript 原生挂载、空闲 session worker、shell 输出捕获。
它们分别处于 OpenTUI、AppServer worker 生命周期、工具输出捕获路径。
完整对话与任务数据仍由原有状态和持久化路径负责；本轮不以删消息或摘要换内存。

本轮不改版本元数据，不暂存、不提交、不推送；其他既有工作树修改保持原样。

## 原因一：历史 transcript 原生 renderable 长期挂载

此前 `App.tsx` 将过滤后的完整消息数组映射为全部 `ChatLine`。
OpenTUI `ScrollBox` 对视口外内容做绘制裁剪，但裁剪不等于卸载 React/native renderable。
因此滚动区看起来只显示少数行，底层仍可能保留历史行、Markdown 和卡片对象。

调用路径：`frontend/opentui-app/src/App.tsx` 的 `visibleMessages` 和聊天渲染区。
挂载窗口位于 `TranscriptMountWindow.tsx`，区间算法位于 `transcriptMountBudget.ts`。
App 的 PageUp、PageDown、Ctrl+Up、Ctrl+Down 和窗口头尾提示控件调用窗口句柄。

默认窗口最多挂载 80 条消息，前后翻页按 40 条移动，窗口仍保持有界。
顶部提示和 PageUp 可继续加载更早页；底部提示和 PageDown 可返回较新页。
窗口滑动时优先保留屏幕上可见消息锚点，不把向前翻页直接拉回 transcript 尾部。

流式更新不会因用户查看旧页而强制回尾；用户主动发送仍沿用原 sticky-tail 语义。
新会话和 `/clear` 重置到尾部窗口；回尾后较旧消息对应的原生行卸载。
完整 `messages`、工具参数与结果、thought、Final、计划卡、子代理行及 Markdown 内容仍保留。
复制从全量消息状态格式化，不依赖当前挂载页；Revert、Fork 等现有语义不变。

这个预算限制的是消息组件数量，不限制单条消息的字节数或内部复杂度。
计划卡和展开的 thought 仍完整展示；一个超长消息仍可独自占用较多内存。

## 原因二：空闲 session worker 进程常驻

每个 session 可有独立 Agent worker 子进程；即使当前没有请求，进程与运行时仍占用内存。
候选治理路径在 `appserver/idle_policy.py` 定义策略，`server.py` 扫描和回收。
`AgentHost` 提供准备挂起、确认关闭及进程树清理边界。

默认 idle TTL 为 600 秒，默认 idle capacity 为 2 个可安全保留的空闲 worker。
配置键为 `RXYCODE_WORKER_IDLE_SECONDS` 和 `RXYCODE_MAX_IDLE_WORKERS`。
TTL 设为 0 只关闭按时间到期回收，不关闭 idle 数量上限。
数量上限设为 0 表示不保留可安全回收范围内的 idle worker；两项策略分别判断。
该数量只应用于未受保护且可安全挂起的候选，不是所有子进程的绝对上限。

只有父进程状态足以证明空闲的 worker 才是候选对象。
活动 RPC、prompt/warm、引导启动、会话锁、待处理请求、审批、执行、watchdog 或排程均会阻止回收。
状态未知、子代理管理状态不可判定、准备保存失败或 worker 未确认安全持久化时，采取保留策略。

子代理明确关闭且没有 manager 时，可以按关闭状态完成安全检查；状态未知不能作此推断。
新建 session 的 `queued` 占位记录本身表示空会话，不等同于排队中的 prompt。
真实排队的 prompt、运行中的工作和所属 session 的启用/排队排程仍受保护。
worker 先保存并返回 `safe`、`persisted`，父进程在 await 前后复核 host 身份和活动状态，再关闭该 worker。

已完成的 child history 也是保护条件：manager 重启后不能重建 worker-local child tree 和 retry request body。
worker 侧 terminal-child pin 已由 owner 完成，并由新鲜 worker 测试验证其保护 tree 的行为。
本任务不实现 manager rehydrate；rehydration 是后续独立工作。本范围通过保留持有这类历史的 worker，维持 child UI 历史和 retry 能力。
因此这类受保护 worker 可以使实际 idle 进程数超过默认值 2；primary 已集成 pin，集成后 fresh proof 已通过（见下文）。

回收目标是 session worker，不是用户启动的 CLI，也不是用户的 AppServer 主进程。
持久化 session 与 memory 留存，后续请求可启动新 worker 继续会话。

## 原因三：shell stdout/stderr 被长时间保留在内存

旧式整体收集大型 stdout/stderr 会令捕获缓冲随输出体积增长。
当前候选路径由 `utils/output_capture.py` 分块读取和捕获，`tools/bash.py` 格式化模型可见结果。

读取块为 64 KiB；每条流的内存预览上限为 48 KiB，保留头尾并标注省略字节数。
合计输出超过 30,000 字节后，捕获器迁移完整 stdout、stderr 到独立 raw artifact。
预览再经脱敏和模型输出字符上限处理；artifact 保留原始字节，供精确检查和校验。

文件写入位于读取路径中，慢磁盘会反压读取，而不是向事件循环另堆无限写任务。
这会把压力传回子进程管道；它不是磁盘空间上限，也不是输出大小硬上限。
capture 错误不得伪装成完整 artifact。

完整 raw artifact 不经过预览脱敏，可能包含秘密或个人数据。
路径及 artifact 只能按原始敏感输出处理；精确保存不等于已脱敏或适合展示。
独立 shell、tools 与 cancellation 检查包含 reader-error 回归并通过；该检查范围标记为 GREEN。

## 新鲜验证记录

下列父代理结果区分候选独立门禁与 primary 集成后 fresh proof；都不是生产用户 footprint 或模型表现数据。
后端组合测试（AppServer、subagents、contracts、cancellation 和真实 AgentV2 两轮生命周期）：
709 passed、1 skipped，用时 106.96 秒。
后续 final shell + all-tools + cancellation gate：1045 passed，用时 47.40 秒，包含 reader-error 回归。
owner worker gate 为 20 passed，parent fresh worker gate 为 19 passed（13.42 秒，含 persisted-child-cap filter）。
reader/consumer fresh gate 为 18 passed，用时 31.03 秒；Ruff 全绿。父代理结果未附 Ruff 的原始调用行。

此前 fresh broad gate 为 9599 passed、47 warnings、0 failed（core/tools/integration/contract，217.51 秒）；primary baseline full 为 9581 passed。
该轮是在未编辑 K3 代码的情况下通过；warnings 不等同于失败，也不代表尚未完成的集成工作已验收。
第一轮 midpoint 为 9587 passed、3 failed，涉及 secret/workspace credential baseline 的 false failures；后续 fresh full 通过，但根因未确定，不归因于本轮改动。
credential-backfill mixed suite 有一次 0 failures；独立运行该 suite 为 12 passed。

最终 combined independent gate：10292 passed、1 skipped、47 warnings，用时 279.94 秒。
准确范围为 core、tools、appserver、subagents、integration、contract、system cancellation、packaging。
这不是“全仓库”或“所有 live”结果；没有据此声称收费/live provider 覆盖。父代理摘要未附原始单行命令，本文不臆造命令。
该组合结果属于已完成的独立候选门禁；primary 集成后的独立 fresh proof 另列如下。

Primary 集成后 fresh proof（2026-10-11）：appserver、subagents、capture/consumers/security、realAgent、cancellation 共 711 passed、1 skipped，用时 75.89 秒。
TUI `bun test`：354 passed、0 failed、70 files，用时 28.52 秒；TypeScript `tsc --noEmit` 无错误。
Ruff 对所有 touched files 检查通过；scoped git diff check 通过。全仓库另有既存且无关的 `evals/prompts` trailing whitespace，保留未改。
primary 与隔离树代码 normalized content 全部匹配；4 个文件恢复原有 LF 行尾，未改变功能。K3 基线 `53e5bae5` 未变，其他既有 WIP 保留。

两轮生命周期验证使用真实 AgentV2 worker，但 provider 回复由 scripted provider 提供。
它不是付费 provider 请求，也不是 live provider 测试。
worker PID 更换后，新 worker 的提示词捕获中仍找到第一轮的旧 marker。
该结果证明这条测试路径观察到跨 worker 的历史恢复，不代表所有生产 provider 的行为。

父代理脚本在 Git 树外的临时目录运行；脚本不是仓库交付物。
仓库内可用以下针对性命令复查；它们不等同于 709 项历史组合结果、10292 项候选 independent gate 或 primary 集成后组合范围。

```powershell
Set-Location frontend/opentui-app
bun test
bun ./node_modules/typescript/bin/tsc --noEmit
Set-Location ../..
python -m pytest tests/test_appserver/test_idle_worker_lifecycle.py tests/integration/test_idle_recycle_real_agent.py
python -m pytest tests/test_core/test_shell_output_capture.py tests/test_core/test_tool_output_spill.py tests/integration/test_bounded_output_preview_security.py
```

上述 shell 针对性命令只是仓库内的定向复查方式；独立 shell + tools + cancellation gate 已 GREEN，primary 集成后 fresh proof 也已通过。

## 父代理隔离基准

TUI baseline/candidate RSS 对照使用 k=3 个新进程/侧，未强制 GC。
worker fixture 与 shell first-run fixture 各为 k=1 单次运行，不是重复试验或统计估计。
100 次 PageUp/PageDown 是单次交互循环观察；不把它写作 k=3 对照。
以下数字来自专用 fixture 和临时探针。
它们用于比较相同场景，不外推为真实用户 footprint、生产模型性能或全局内存上限。

| 场景 | 基线 | 有界候选 | 说明 |
|---|---:|---:|---|
| 1000 条混合 transcript 的 native nodes | 9354 | 760 | 候选窗口含 80 条消息；760 是实际 fixture 的 native 节点数 |
| transcript 加载 RSS（3 次，bytes） | 315817984 / 337043456 / 310845440 | 161804288 / 165912576 / 161718272 | 新进程；未强制 GC |
| transcript 峰值 RSS（3 次，bytes） | 350187520 / 352903168 / 346230784 | 183779328 / 188907520 / 193282048 | 同一基准协议 |
| 100 次真实 PageUp/PageDown 后 native nodes | — | 760 | 单次交互循环；窗口持续有界；最终 RSS 250494976，峰值 322064384 bytes |

Bun allocator 不保证释放对象后立刻把已提交内存还给操作系统。
所以 native 节点下降并不等于 RSS 同比例下降，也不承诺 RSS 硬上限。
长消息、完整会话 JSON、活跃 worker 与持久化任务仍可继续增长。

worker fixture（k=1）中，4 个 warm stub worker 收敛到默认 idle capacity 内的 2 个 worker。
对应 RSS 为 315740160 → 157863936 bytes；旧代码对照为 4 → 4，RSS 314974208 bytes。
受保护的 completed-child-history worker 不受该数量上限约束。这是 stub worker 单次场景，不是实际用户模型进程的节省比例。

100 MB capture-only stdout+stderr fixture（k=1，first run）的基线峰值 RSS 为 276885504 bytes，基线 RSS 为 66514944 bytes。
有界候选首轮峰值 RSS 为 69169152 bytes，基线 RSS 为 68366336 bytes。
有界候选产生 stdout/stderr 两条各 50 MB raw artifact；父代理核对首批样本 SHA-256。
该 capture-only fixture 的旧计时约 0.22 秒，不是完整 Bash 工具管线耗时。

| 匹配的 100 MB 完整 Bash 管线（k=3，交替 arm 顺序） | 旧路径 | 新路径 |
|---|---:|---:|
| 峰值 RSS（bytes） | 395722752 / 396038144 / 396079104 | 82452480 / 81969152 / 82087936 |
| 耗时（秒） | 1.2662917 / 1.2767355 / 1.2336625 | 1.2725090 / 1.3111838 / 1.2606214 |

旧路径每轮将两路输出合为一个 100 MB raw artifact；新路径每轮生成两条各 50 MB artifact。
三组配对中，旧路径峰值约 377–378 MiB，新路径约 78 MiB；新路径峰值 RSS 约低 79%。
测得耗时处于本次样本变动范围内，不据此声称速度提升。
新路径每轮 `capture_error=null`；父代理已核对首批样本 artifact 的 SHA-256。
完整 Bash 管线与 capture-only 的约 0.22 秒测量范围不同，不作横向耗时比较；所有数值仅是 fixture 结果，不构成用户进程内存或生产性能承诺。

以上 RSS/节点数据不代表真实用户进程、模型 provider 性能、缓存/token 使用或系统级 ceiling。
单条巨大消息、完整消息 JSON、活跃 worker、存储任务和输出 artifact 磁盘用量仍不受统一上限约束。

## 当前边界与待办

Primary 集成后 fresh proof：backend 范围 711 passed、1 skipped（75.89 秒）；TUI 354 passed、0 failed（70 files，28.52 秒）；tsc、Ruff touched files 与 scoped diff check 均通过。
独立 shell + all-tools + cancellation 1045 passed（47.40 秒，含 reader-error）；worker owner/parent 20/19 passed（parent 13.42 秒，含 persisted-child-cap filter）；reader/consumer 18 passed（31.03 秒）。
在 manager rehydrate 支持到位前，受保护进程可能超过 idle capacity；这不是绝对进程数上限。
本任务没有实现 child-history rehydration，该能力留作独立后续工作。
primary 源码已于 2026-10-11 集成；需重启 RxyCode 加载，当前不是发布，产品版本仍为 1.4.2。本次按用户授权将内存治理代码、测试、模块说明、Changelog 与本文报告提交本地 master，不推送；仅显式纳入本文报告，不修改 .gitignore，不纳入计划文档或其他 WIP。
归一化代码与隔离树匹配；K3 基线不变，其他 WIP 保留。后续仍应保留本文测试范围和限制，不将局部 fixture 变成产品级内存承诺。
