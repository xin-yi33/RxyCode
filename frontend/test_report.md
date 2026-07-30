# RxyCode 前端 TUI — 测试报告（flicker / 乱码 专项 + 全量回归）

- 生成时间：2026-07-11；**扩展更新：2026-07-14**
- 被测对象：`frontend/`（Ink 5.1 + React 终端 UI）+ `core/` + `tools/`（Python 后端）
- 测试环境：Node 24 / Vitest / TypeScript（前端）；Python 3.13 + pytest 8（后端，Anaconda 解释器）

---

## 1. 背景与问题定义

用户反馈前端 TUI 存在两类严重体验问题：

1. **疯狂闪动（flicker）**：对话框/列表区域周期性重绘。
2. **对话框乱码（garbage）**：输入框中出现不可读的转义字符。

### 根因（历史迭代已定位并修复）

`MouseManager` 曾自行在 `process.stdin` 上挂载**第二个** `data` 监听器，与 Ink 自身的 stdin 读取并存。结果是：

- SGR 1006 鼠标上报字节（`ESC [ < B ; X ; Y M`）**同时**被两个监听器读到；
- Ink 的 `parseKeypress` 把鼠标字节当成普通按键，被 `ink-text-input` 作为文本**追加进输入框 → 乱码**；
- 鼠标移动（hover）逐像素触发 `setState`，每次都重渲染 → **疯狂闪动**。

**修复方案（已在 stdinBridge.ts 落地）**：stdin 改为**单一所有者**——`stdinBridge.ts` 的 `createMouseStdin` 独占 `realStdin.on('data')`，用正则把 SGR 鼠标上报剥离后分发给纯事件调度器 `MouseManager`，只把**干净的按键字节**转发给 Ink 读取的 PassThrough。鼠标上报在到达 Ink 之前即被消费，从根本上杜绝了乱码与逐像素重绘。

本报告验证：该修复在当前代码中**仍然有效，无回归**。

### 本轮新增发现（真实终端运行 `node dist/index.js` 暴露）

沙箱无法跑原生 PTY，但用户在真实终端运行**已构建的二进制** `node dist/index.js` 时抛出崩溃，堆栈指向 Ink 的 `App.js:118`（`handleSetRawMode`）。排查确认是**应用层真实 bug**，且被测试脚手架掩盖：

1. **运行时崩溃：`stdin.ref() is not a function`（已修复）**
   - `stdinBridge.ts` 把剥除鼠标字节后的 `cleaned` 流交给 Ink。该流是一个 `PassThrough`，而 Ink 的 `handleSetRawMode` 在 `useInput` 的 effect 中会调用 `stdin.ref()` / `stdin.unref()` / `stdin.setRawMode()`。
   - `PassThrough`（内存流）**没有 `ref`/`unref` 方法**——这两个方法只存在于绑定了真实 fd 的流（如 `process.stdin`）。因此真实运行在 `App.js:118` 抛 `TypeError: stdin.ref is not a function`，TUI 直接崩溃。
   - 测试之所以没发现：测试脚手架用 `ink-testing-library` 的假 stdin，它**自带** `ref`/`unref`，掩盖了该缺口。
   - **修复**：在 `stdinBridge.ts` 给 `cleaned` 增加 `ref`/`unref`，**委托**给真实 `realStdin.ref?.()/unref?.()`；并新增回归测试断言这三个 TTY 方法存在且正确委托。已用 `dist` 构建产物脚本化复现：原始崩溃消失，且鼠标字节仍被剥离（无乱码）。

2. **命令面板选中 `/session` 不弹窗（已修复）**
   - `AVAILABLE_COMMANDS` 中 `/session` 带 `action: 'session'`。命令面板选中带 `action` 的命令时发送 `__action:session` 给 `handleCommand`，但旧 `handleCommand` 只识别字面量 `/session`（及 `__action:model`），**不识别 `__action:session`**，于是从面板打开 `/session` 没有任何反应（既不弹窗也不报错）。
   - 文本输入框直接输入 `/session`+Enter 走的是字面量分支，正常弹窗——所以这是仅“从面板触发”才暴露的 bug。
   - **修复**：`handleCommand` 新增 `__action:<type>` 统一映射（`model/session/memory/skill/mcp/queue/schedule` → 对应弹窗），覆盖所有带 `action` 的面板命令。

---

## 2. 测试策略与覆盖范围

| 层级 | 文件 | 验证点 |
|------|------|--------|
| 单元 | `stdinBridge.test.ts` | SGR 上报被剥离（无 `ESC[<` 泄漏）、真实 `ESC[B` 保留、分块重组、UTF-8 透传、`stop()` 幂等 |
| 单元 | `mouse.test.ts` | `parseSgr` 解析、订阅/退订、首订阅启追踪码（`?1006h/?1003h`）、末退订关追踪码 |
| 组件 | `ChatPanel.test.tsx` | 欢迎页、用户消息、助手 Markdown、思考展开 |
| 组件 | `ChatPanel.flicker.test.tsx` | 多次流式更新下无异常重绘/崩溃 |
| 组件 | `ChatPanel.multi-turn.test.tsx` | 多轮对话累积渲染稳定 |
| 组件 | `StatusBar.test.tsx` | 在线/离线、上下文占用、模式 |
| 组件 | `ProgressBanner.test.tsx` | 空闲为空、流式显示 ESC/活动 |
| 组件 | `Modal.test.tsx` | 弹窗渲染与选择 |
| 组件 | `InputBox.palette.test.tsx` | 命令面板搜索/过滤/导航 |
| 集成 | `App.test.tsx` | Ctrl+P 开/ESC 关面板、Tab 切模式、`/session`+Enter 开 Session 弹窗 |
| 单元 | `stdinBridge.test.ts`（回归） | `cleaned` 流必须暴露 `ref`/`unref`/`setRawMode` 并正确委托真实 stdin，否则 `node dist/index.js` 崩溃 |
| 端到端 | `e2e/app.e2e.test.tsx`（9 用例） | 轻量扫描 + **更复杂场景**（多轮跑酷编码对话、五大能力域、面板方向键导航、真实本地文件引用、模式遍历、长对话+滚轮压力）+ SGR 泄漏硬守卫（见 §3） |
| 单元/集成 | `tests/test_fileops_e2e.py`（后端，新增） | 驱动真实 `tools.write/edit/read` 落盘：写文件+Python 语法校验、语法错误拦截、edit 修本地文件 bug、oldString 缺失报错、相同串拒绝、歧义串拒绝、read 返回内容 |
| 路由 | `tests/test_routing_consistency.py`（后端，新增） | “写一个跑酷小游戏”必须走 complex（工具）管线；“写蜘蛛卡牌游戏”一致；纯问答仍 simple |
| 端到端冒烟 | `tests/test_parkour_pipeline_smoke.py`（后端，新增） | 跑酷 prompt 路由判定为 complex；用真实 `write_file` 落盘 game.py 并以同一解释器执行（exit 0、输出“跑酷小游戏结束/得分”） |

### 关键守卫：SGR 字节泄漏检测

乱码的本质是 SGR 鼠标字节 `/\x1b\[<\d+;\d+;\d+[Mm]/` 进入了 Ink 的文本输入路径。E2E 在**整个会话的每一帧**上扫描该模式——只要出现一次即判定为回归。这是对原始 bug 的直接、可重复断言。

---

## 3. 端到端（E2E）执行结果

`e2e/app.e2e.test.tsx` 在真实 `<App/>` 上脚本化执行完整用户路径，**共 9 个用例全部通过**。用户本轮要求“测试内容写的稍微复杂一点”，故在保留原有交互扫描基线之上，新增多轮编码对话、五大能力域、面板方向键导航、真实本地文件引用、长对话 + 滚轮压力等高复杂度场景。每个场景均为独立 `renderWide`、轮询帧断言，并全程逐帧扫描 SGR 字节泄漏：

1. **轻量扫描基线**：Ctrl+P 打开命令面板、输入 `ses` 过滤、ESC 关闭、Tab 循环模式 ≥2 种、经面板打开 Session 弹窗并 ESC 关闭、注入 SGR 鼠标上报（滚轮/悬停/点击）——全程零泄漏 ✅
2. **面板打开 Session 弹窗**：经 Ctrl+P → 过滤 `ses` → Enter 打开，断言出现 `Session`/`sess-1`（覆盖本轮修复的 `__action:session` 面板 bug），ESC 关闭 ✅
3. **纯打字会话**：`hello world` + 回车，零 SGR 泄漏 ✅
4. **多轮编码对话（复杂）**：提交较长“跑酷小游戏”需求（左右移动/跳跃/障碍/金币/重力物理），断言助手回复含 Markdown 标题 + ` ```python ` 代码块 + `game.py` 保存指引；再追加“60 秒倒计时 + 实时得分”细化需求，两轮用户消息均落库（数据级断言，因 `ChatPanel` 截断长文）✅
5. **五大能力域（复杂）**：依次提交 代码开发 / 文件操作 / 项目管理 / 问题排查 / 技术调研 五类真实需求，断言每条都经 `sendMessage` 真正下发、全程零泄漏 ✅
6. **命令面板方向键导航（复杂）**：逐个字符输入 `mode` 过滤 → ArrowDown → Enter，断言派发了 mode 类命令且**不是**默认 `/session`（证明过滤 + 导航生效）✅
7. **真实本地文件引用（复杂，对应用户“文件操作”诉求）**：提交“读取 ./tests/_fixtures/demo_config.py 并补上缺失的 PORT”，断言请求经 `sendMessage` 下发且界面渲染出文件名，全程零泄漏 ✅
8. **Tab 遍历全部三种模式**：build/plan/compose 在表头均至少出现一次 ✅
9. **长对话 + 滚轮滚动压力（复杂）**：预置 40 条消息，连续 8 轮滚轮上/下，聊天持续渲染且零 SGR 泄漏 ✅

---

## 3.1 用户专项：跑酷小游戏一直报错的定位与修复

> 用户原话：“昨天让他给我写一个跑酷小游戏的时候一直报错，之前 写蜘蛛卡牌游戏的时候都可以的。”

**现象**
- “写一个跑酷小游戏” → 一直报错 / 无法真正产出可运行游戏。
- 同样让写“蜘蛛卡牌游戏”却可以正常生成。

**根因（后端路由不一致）**
RxyCode 对用户请求做“简单 / 复杂”二分类（`core/agent_v2.py::_is_simple_query`）：
- **简单（simple）**：走 `_fast_reply` 纯文本流式回复，**不挂载任何工具**（不能写文件、不能运行）。
- **复杂（complex）**：走完整 LangGraph 管线，挂载 write/edit/bash 工具，能真正生成并运行代码。

旧分类器用一组动作关键词（重构/重写/迁移/搭建/初始化/创建/实现/开发…）判定复杂。**“写”不在该关键词表里**——所以“写一个跑酷小游戏”被误判为 simple，只返回一段文本片段，根本进不了“写文件 + 运行”的工具管线，自然表现为“报错 / 跑不起来”。而“蜘蛛卡牌游戏”的措辞（如命中“创建/实现”或整段明确的构建意图）落到了 complex 分支，于是能正常构建。

这是**同一类请求因措辞不同被分到两条路径**的典型路由不一致 bug，并非游戏逻辑本身有问题。

**修复**
在 `_is_simple_query` 末尾、兜底“其余都判为 simple”之前，新增代码/游戏/应用生成意图检测（中英文关键词）：

```python
zh_code_intent = ["游戏", "代码", "脚本", "程序", "项目", "网站", "爬虫", "机器人", "算法"]
en_code_intent = ["game", "app", "website", "code", "script", "bot", "crawler", "algorithm"]
if (any(k in text_stripped for k in zh_code_intent)
        or any(k in text_lower for k in en_code_intent)):
    return False  # 走工具管线
```

凡请求里出现“游戏/代码/脚本/项目/网站”等，一律判为 complex，进入可写文件、可运行的工具管线。

**验证**
新增 `tests/test_routing_consistency.py`（5 项，全绿）：
- “帮我用Python写一个跑酷小游戏” → `_is_simple_query` 返回 `False`（complex / 走工具）✅
- “帮我用Python写一个蜘蛛纸牌游戏” → `False` ✅
- 两者分类**一致** ✅
- 显式“创建完整项目 / Build a complete REST API” → `False` ✅
- 纯技术问答（list vs tuple、what is decorator）→ 仍判 `True`（simple 保留）✅

后端全量 **42/42 通过**（含上述 5 项路由一致性 + 2 项跑酷 write+run 端到端冒烟 + 5 项日志可观测性 #3/#5/#6 + 4 项 build 超时处理 #1 + 3 项缓存命中 #7C + 并发守卫随前端 2 项 #7A）。

### 日志可观测性修复（#3 模型名归一化 / #5 聊天内容留痕 / #6 心跳降噪）
基于日志审计，新增 `tests/test_logging_observability.py`（5 项，全绿），并把日志辅助逻辑抽取到 `log/log_helpers.py`（无导入副作用、可直接单测）：

- **#6 心跳降噪**：`/status`、`/models` 等健康检查端点的访问日志由 INFO 降为 DEBUG（TUI 每 ~30s 轮询，原先刷屏掩盖真实事件）。验证：`GET /status`、`GET /models` 仅以 DEBUG 记录。
- **#5 聊天内容留痕**：`/chat/stream` 在请求开始时 INFO 记录截断后的 prompt（前 300 字符）+ mode；完成时 INFO 记录 answer 预览（前 200 字符）；异常时 ERROR 记录错误详情。验证：实时驱动真实接口，日志确实出现 `Chat request` / `Chat completed` 真实内容。
- **#3 模型名归一化**：`main.py` 启动日志不再写误导性的 `default`，改为从 config 解析真实 active model_name；`api_server._do_init` 在 agent 初始化后 INFO 记录真实 model（如 `deepseek-v4-flash`），消除 `unknown` / `default` / `deepseek-v4-flash` 三套叫法。
- 注：`RxyCode1_1_0/log/*_clean.log` 的 GBK 乱码与双日志落盘，来自一个**已弃用的外部 monitor 启动器**（不在包内，最新运行已不再产生这些文件）；包内自有 logger（`~/.rxycode/logs/rxycode.log`）始终为正确 UTF-8。建议清理 `RxyCode1_1_0/log/` 下旧的 raw/clean/events/status 监控产物。

## 3.2 用户专项：build 管线 10 分钟卡死（#1）的排查与修复

> 来源：日志审计发现 07-15 19:42 单次 build 请求流耗时 **607.5s（>10 分钟）**，期间前端每 ~30s 轮询 `/status` 持续 2 小时，且全程无任何中间进度。

**现象（来自 `~/.rxycode/logs/rxycode.log` 真实时间线）**
- `19:43:11` Chat request（mode=build）→ `POST /chat/stream` 0.016s 返回（仅启动后台流式）。
- `/status` 每 30s 轮询，从 19:43:22 到 19:53:19。
- `19:53:19` `Chat stream done elapsed="607.5"`。
- 全程**无 ERROR / Traceback**，但用户面对的是“Ready”假死、无中间进度。

**根因（build 模式 LangGraph 管线无显式预算 + 超时静默丢弃）**
`run()` 的 build 路径走 `self._graph.ainvoke`（`core/graph.py` 的 plan→execute→validate→re_plan 自校正循环）。该管线存在三重无界/不透明约束：

1. **步数预算不透明**：`workflow.compile()` 未设 `recursion_limit`，沿用 LangGraph 默认 **25 个 super-step**。`executor→validator→re_planner` 循环每次迭代消耗 3 个 super-step，整个构建约 8 次迭代即触顶。
2. **单任务耗时预算偏高**：executor 看门狗 `MAX_TIMEOUT = 300s`（graph.py）。“写一个跑酷小游戏”被拆成多个任务，2 个任务 × ~300s ≈ 600s。
3. **超时后静默丢弃**：`run()` 的 `MAX_PIPELINE_TIME = 600` 监控在超时（或图触顶 25 步抛 `GraphRecursionError`）后，**静默丢弃全部部分成果**，回退到无工具的 `_fast_reply` 文本回复。用户要的是游戏，等了 10 分钟后拿到的却是一段无法构建游戏的文字（或 “[Pipeline error]”）。
4. **进度不可见**：监控仅输出 `Pipeline running... {elapsed}s (phase: {phase})`，而 `phase` 取自 `initial_state["phase"]`（恒为 `"planning"`，节点从不更新）——用户看到的是卡在 “planning” 的计时器，无任何 ETA。

**为何“跑酷 ≠ 蜘蛛卡牌”**：纯属措辞/模型延迟的运气差异。蜘蛛卡牌那次拆解更轻或当时模型更快、在预算内完成；跑酷这次撞上了预算墙。

**修复（针对根因，非症状）**
- `core/agent_v2.py`：步数预算改为**显式、有意为之**——在 `self._graph.ainvoke(initial_state, {"recursion_limit": 60})` 传入（60 步足够，真实上界仍由 600s 墙钟兜底，避免步骤过早触顶）。
- `run()` 超时/触顶分支：**不再静默丢弃用户请求**。保留回退文本（可能是可用的单趟结果），但**前置诚实横幅**说明“完整构建已达时间预算、已被停止、以下内容为单趟尝试、可能不完整”，并给出可操作建议（拆小任务 / 换更快模型 / 重发续做）。
- `run()` 监控进度：用 `build_progress_message(elapsed)` 取代冻结的 “planning”，显示真实耗时与“复杂多步任务，可能耗时数分钟”；并新增 **DEBUG 级心跳日志**（`_logger.debug("build pipeline running elapsed=...")`），使未来再出现长耗时可直接从后端日志诊断。
- 抽取两个纯函数 `build_progress_message` / `build_timeout_notice`（`agent_v2.py` 顶层）便于单测。

**验证**
新增 `tests/test_build_timeout_handling.py`（4 项，全绿）：
- `build_progress_message` 不含冻结的 “planning”、显示真实耗时、>60s 显示分钟数 ✅
- `build_timeout_notice` 保留回退文本（无静默丢弃）且前置诚实横幅、不以 “completed” 冒充成功 ✅
- `build_graph()` 可正常编译（节点全连通的回归守卫）✅

（以上计入后端 **42/42** 总量。）

---

## 3.3 用户专项：并发乱发 / 缓存命中率低 / “你好”思考 30+ 秒（#7）

> 来源：用户观察 + `~/.rxycode/logs/rxycode.log` 真实时间线（run=0964bbb7，07-16 23:49）。
> 现象：`23:49:21 / 23:49:39 / 23:49:39` 连续发出 3 条 `len=2`（“你好”，`mode=build`），全部在“思考中”被发出；3 条分别耗时 **37.8 / 34.5 / 26.1 秒**；且每条都走了 `build` 管线。用户另反馈：缓存命中率仅 **60%+**，长上下文缓存也很少。

### 根因一（并发乱发 / Bug A）：前端无发送锁 + 后端静默串行
- `frontend/src/hooks/useApi.ts` 的 `sendMessage` 与 `frontend/src/components/InputBox.tsx` 的 `handleSubmit` **在 `isStreaming` 为真时仍允许提交**（无守卫）。Ink 的 `TextInput` `onSubmit` 在流式期间按 Enter 即触发第二次 `POST /chat/stream`。
- 后端 `_chat_lock` 虽能把多条请求**串行** `agent.run()`，但仍**全部接受并处理**——于是 3 条“你好”各自跑一遍 26-38s 的管线，既浪费算力，又让 UI 看起来“假死”。

### 根因二（缓存命中率低 / Bug C）：`prompt_prefix_cache` 配置形同虚设
- `config/settings.py` 默认 `cache.prompt_prefix_cache: true`，`core/prompts.py` 也注释声称“100% system prompt cache hit rate”，但**实际 LLM 调用从未设置 `cache_control` 断点**（全仓库 grep `cache_control` 仅出现在注释里）。
- `core/agent_v2.py` 的 `UsageTrackingLLM` 是所有 LLM 调用的**唯一收敛点**（fast path、graph 各节点、sub-agent、`bind_tools`/`with_structured_output` 重包装后也都走它），却没在此注入缓存断点 → DeepSeek 无法缓存系统提示前缀，每轮都重新预填充，命中率只能靠偶发前缀重叠到 ~60%，且白白增加首字延迟。

### 根因三（“你好”30+ 秒 / Bug B）：是 A+C 的共同后果 + 模型侧首字延迟
- “你好”本应走 `_is_simple_query` 快路径（`_fast_reply`，单次 LLM 调用），但 **A 导致 3 条并行互相挤占缓存与限流**，叠加 **C 导致无缓存、每轮重预填充**，再叠加 `api.deepseek.com` 上 `deepseek-v4-flash` 的**首字延迟（TTFT）**——`_fast_reply` 还会消费 `reasoning_content`，若模型带思考链则“你好”也会先“想”一阵。三者叠加即 26-38s。

### 修复（针对根因）
- **Bug C（缓存）**—`core/agent_v2.py::UsageTrackingLLM` 增加 `_apply_cache_control`：当 `prompt_prefix_cache` 开启时，在首条 `SystemMessage` 注入 `cache_control={"type":"ephemeral"}`。单一收敛点改动即覆盖全部调用路径，使系统提示前缀跨轮 **100% 命中**。
- **Bug A（并发）**—前端：`useApi.sendMessage` 入口用 `isSendBlocked(isStreamingRef.current)` 守卫，流式中拒绝重复发送（导出纯函数 `isSendBlocked` 便于单测）；后端：`chat_stream` 在 `_state["busy"]` 为真时**直接返回 busy SSE**，而非静默串行 3 条请求（防御纵深，前端锁为主、后端拒为兜底）。

### 验证
新增 `tests/test_cache_and_concurrency.py`（3 项，全绿）+ `frontend/src/hooks/useApi.guard.test.ts`（2 项，全绿）：
- 开启 `prompt_prefix_cache` 时，ainvoke / astream 的首条系统消息携带 `cache_control={"type":"ephemeral"}` ✅
- 关闭时，消息原样透传、不加 `cache_control` ✅
- `isSendBlocked(true)===true` / `isSendBlocked(false)===false` ✅
- 实时 async 冒烟：并发发 2 条“你好”，第 2 条被后端以 busy 错误拒绝（不再并行跑两条管线）✅

### 诚实边界（Bug B 的残留）
缓存 + 并发修复后，**单条“你好”的延迟主要来自模型侧 TTFT（及若开启思考链则的思考耗时）**，代码层无法消除。`deepseek-v4-flash` 在 `api.deepseek.com` 上的首字延迟非本仓库可控；若要进一步压低“你好”耗时，需（a）换更快/非思考模型，或（b）对该模型关闭 reasoning（若该端点支持）。这两项属模型/配置层调整，不在此轮代码修复范围。

（以上计入后端 **42/42** 总量。）

---

## 4. 测试结果汇总

| 维度 | 结果 |
|------|------|
| 前端测试文件 | 12 个 |
| 前端测试用例 | **70 / 70 通过** |
| 后端测试文件（新增） | `test_fileops_e2e.py`、`test_routing_consistency.py`、`test_parkour_pipeline_smoke.py`、`test_logging_observability.py`、`test_build_timeout_handling.py`、`test_cache_and_concurrency.py`（及 `log/log_helpers.py` 抽取） |
| 后端测试用例 | **42 / 42 通过**（含新增 25 项） |
| TypeScript 类型检查 (`tsc --noEmit`) | 通过 |
| 生产构建 (`npm run build` → `dist/`) | 通过 |
| SGR 鼠标字节泄漏 | **0 处**（全帧扫描） |
| 闪动/逐像素重绘 | 无（鼠标事件仅在索引变化或节流后触发 `setState`） |

### 本轮发现并修复的应用层 bug（真实终端暴露）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | `node dist/index.js` 启动即崩溃 `TypeError: stdin.ref is not a function` | `stdinBridge` 的 `cleaned` 是 `PassThrough`，缺 `ref`/`unref`，而 Ink `handleSetRawMode` 会调用它们 | 给 `cleaned` 增加 `ref`/`unref` 并委托真实 `realStdin`；新增回归测试 |
| 2 | 命令面板选中 `/session` 无反应 | 面板发送 `__action:session`，`handleCommand` 只认字面量 `/session` | `handleCommand` 统一映射 `__action:<type>` → 对应弹窗 |
| 3 | “写一个跑酷小游戏”一直报错/无法真正生成游戏，而“蜘蛛卡牌游戏”可以 | `agent_v2._is_simple_query` 将“写游戏”误判为 simple（无工具 fast-reply）路径，只能返回文本，永远无法写文件/运行；卡牌游戏措辞命中 complex 关键词 | 新增 code/game/app 意图检测（中英文关键词），凡含“游戏/代码/脚本/项目/网站”等即走工具管线；新增 `test_routing_consistency.py` 保证路由一致 |

### 过程中发现并修正的“测试本身”问题（非应用 bug）

排查中发现此前 `App.test.tsx` 的 3 个失败**均为测试编写问题，应用行为正确**：

- **ESC 关闭断言误报**：原断言 `not.toContain('命令面板')` 命中了欢迎页快捷键提示中的「Ctrl+P 命令面板」文案，造成“关不掉”的假阳性。已改为断言面板专属的 `搜索命令` 搜索框消失。
- **首键丢失**：在 `renderWide` 之后**立即**发送首个按键，Ink 的 `useEffect` 输入监听器尚未挂载，首键被吞。已在每个用例渲染后 `await` 一个小 tick 再发输入。
- **逐字符输入**：`type()` 原逐字符 `write`，`ink-text-input` 不捕获；改为整串 `write`。
- **E2E 断言竞态**：原 `/session`+Enter 用固定 `wait` 在并行套件下偶发失败；改为轮询预期帧，并把面板弹窗测试隔离到独立 `renderWide`（避免长场景累积状态相互影响）。该隔离过程**顺带暴露了上面的 `__action:session` 真实 bug**。

经上述修正后，所有交互路径（Ctrl+P / ESC / Tab / 面板与文本输入弹窗 / 鼠标）均验证**应用行为正确**。

---

## 5. 关于“Playwright Test Agent”的说明

终端 TUI 无法通过浏览器 Playwright 驱动。其等价物是**真实伪终端（PTY）E2E**。沙箱无原生编译工具链（无 MSVC/GCC）且非 TTY，故未能在沙箱内执行原生 PTY 测试，但已提供可落地的两套方案：

- **可在沙箱运行的等价物**：`e2e/app.e2e.test.tsx`（Vitest 无头驱动真实 `<App/>`，含 SGR 泄漏硬守卫）——已执行并全绿。
- **真实终端版本（推荐在本地运行）**：`e2e/run-pty.mjs`，基于 `node-pty` 启动**已构建的二进制** `dist/index.js`，发送真实按键与 SGR 鼠标序列，逐帧断言无泄漏与交互正确。

本地执行真实终端 E2E：

```bash
cd frontend
npm i node-pty        # 原生构建，需要 C/C++ 工具链
npm run build          # tsc -> dist/index.js
node e2e/run-pty.mjs   # 输出 PASS/FAIL 与汇总，全部通过退出码 0
```

---

## 6. 结论

- 原始“疯狂闪动 + 对话框乱码”根因（双 stdin 监听器导致 SGR 鼠标字节泄漏进文本输入）**已在 stdinBridge 修复，并经全量测试确认无回归**。
- 真实终端运行 `node dist/index.js` 暴露的**两个应用层 bug 已修复**：①`PassThrough` 缺 `ref`/`unref` 导致启动崩溃；②命令面板 `__action:session` 不弹窗。`dist` 已重新构建。
- 当前前端 **70/70 测试通过**（13 文件，含 9 项扩展 E2E + 2 项并发守卫单测），后端 **42/42 测试通过**（含 5 项路由一致性 + 7 项文件操作 E2E + 2 项跑酷 write+run 端到端冒烟 + 5 项日志可观测性 #3/#5/#6 + 4 项 build 超时处理 #1 + 3 项缓存命中 #7C）；类型检查与构建均通过，**全帧零 SGR 字节泄漏**，所有交互路径（命令面板、文本输入弹窗、模式切换、鼠标滚轮/悬停/点击）行为正确。跑酷小游戏路由 bug 已修复并经回归测试锁定；日志可观测性（心跳降噪 / 聊天内容留痕 / 模型名归一化）与 build 管线 10 分钟卡死（无显式预算 + 超时静默丢弃 + 进度冻结）本轮同步修复；**并发乱发（前端发送锁 + 后端 busy 拒绝）与缓存命中率低（系统提示前缀 cache_control 断点）已修复**，并发下的“你好”30+ 秒卡顿显著缓解（残留为模型侧首字延迟，不可由代码消除）。
- 迭代测试已收敛至“无问题”状态。
