# RxyCode v1.4.0

RxyCode 把一件软件任务拆开，用工具做完，再核对结果，过程流式回到终端。1.3.0 交出了三栏桌面工作台。1.4.0 把同一套 agent 补到能长跑：上下文有一把统一的尺子，插件按能力安装，专家团可以编组，长任务断了还能续，图像能留在对话里。协议版本仍是 `1.1.0`。

本页只发命令行。资产是 `rxycode-1.4.0.tar.gz`。桌面安装包没有新的 exe、zip 或 AppImage，请继续用 [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0)。整理稿里曾经写成 1.3.1，产品版本是 **1.4.0**。

## 简要说明 / Summary

下面是相对 1.3.0 落在这个版本里的变化。下载本页只会得到 CLI / OpenTUI。

- 新增：上下文占用、微压缩和 LLM compact 共用一把尺子；`/compact`、`/effort` 接通
- 新增：CapabilityRegistry、全局 / 项目 / 会话三级作用域、`rxy plugin` 安装器
- 新增：Team Pack v2、十三支预设团、低配环境按 E0 → E1 → E2 降级
- 新增：`run/*` 持久运行、goal 存在服务端并在重连时注入、Computer Use 作为第六个内置能力
- 新增：`vision` 按结构化图像透传，MCP 带回的图像不再被丢掉
- 新增：OpenTUI 工具卡片、计划面板、后续队列、edit 的绿/红 diff、思考过程边跑边出
- 新增：会话列表和自动标题；Shift+Enter / Ctrl+Enter 换行，Enter 才发送
- 修复：Windows 上新建会话卡在 Starting Agent worker；GLM / OpenCode Go 的 400；只读回答被空的 `[evidence failed]` 替换
- 修复：「不要写入文件」不再被证据门禁当成写任务；需要子代理或 Skill 的请求不再掉进只读 explore
- 修复：`/effort` 在当前模型没有档位时，Esc 只关面板，不再改成 default
- 修复：模型和读工具共用 5 次额外重试，间隔 2s / 4s / 8s / 16s / 30s；网关把整段又发来一次时，界面只留新的那一截
- 变更：产品版本 **1.4.0**；协议保持 `1.1.0`；GitHub Release 只上传 CLI sdist

## 亮点 / Highlights

- **长对话终于有尺子。** 状态栏上的「上下文」和 `/compact` 读 `core/compaction.py` 的同一套占用。旧的工具观察先做微压缩，不够再请模型压缩；已经压过的边界不会再压第二次。
- **插件按能力进出，不按文件名堆在提示词里。** 没打开的能力不会进工具前缀。全局、项目、会话三层可以不一样，切换前能看 diff。
- **专家团从仓库里就能选。** Team Pack v2 解析团队定义，开箱有十三支预设团。机器或模型不够时，降级编译器按 E0 → E1 → E2 往下收，而不是直接失败。
- **长任务杀掉以后还认得出自己。** `run/*` 把运行留在服务端。goal 重连后注回去，不再只靠浏览器里的 localStorage。`/loop` 的时钟在 appserver 启动时恢复；处于暂停的 goal 不会自己醒；被杀掉的 bash 不会复活。
- **图能留下来。** 旧的 `vision` 把图像收成一段字符串，半路上就没了。这一版透传结构化图像，MCP 带回的图进消息，后面的轮次还能引用。
- **终端里看得见它在干什么。** 工具卡片标运行中 / 成功 / 失败和耗时。edit 用绿行和红行标出增删。思考过程在生成的时候就往外推，不必等整轮结束才出一块快照。
- **换行就是换行。** Windows 终端常把 Shift+Enter 收成 `\r\n`，旧版本会直接发出去。现在裸 `\r` 仍是发送，`\r\n` 留在输入框里。
- **重试用同一张表。** 模型网络失败和读工具失败都是最多再试 5 次，等待 2 秒、4 秒、8 秒、16 秒、30 秒。回复已经开始之后的空闲超时不再重试。

## 详细说明 / Details

### 新增功能

#### 上下文、压缩与会话

- **一把占用尺子** — `occupancy_tokens` / `usable_tokens`。状态栏和 compact 触发读同一套数字，不再各算各的。
- **压缩阶梯** — `microcompact_messages` 按价值清理旧的工具观察，而不是整轮扔掉。再往上是 compact boundary、「不二次压缩」的数据模型、两套 compact prompt、`compact_messages` 和 `run_compaction_ladder`。
- **`/compact`** — `core/session.py` 里接到 `if cmd == "/compact":`。
- **`/effort`** — 在 `core/providers/base.py`、`core/providers/openai.py`、`core/agent_v2.py` 三处实装。当前模型没有档位时，面板写明不支持，Esc 只关闭。
- **会话列表与标题** — `core/session_list.py`、`core/session_title.py`。新会话会被记下来，标题由模型补。
- **斜杠与消息动作** — UPDATE-01 的斜杠映射、Search / Fetch / Browse（默认开、可附着 Chrome）、Message Actions、磁盘上按内容寻址的快照和 FileTracker。

#### 核心引擎

相对 1.3.0，核心侧新增约 50 个文件，并改动了约 400 个既有文件。和长跑直接相关的是这些：

- **流什么时候算活着** — `core/agent_v2.py` 增加连接超时、chunk 保活和硬截止：`StreamConnectTimeoutError`、`_resolve_connect_timeout`、`_stream_chunk_is_alive`、`_arm_hard_deadline` / `_cancel_hard_deadline`，以及强制关掉供应商流、清掉句柄。长连接不再一直挂着。
- **中途转向和已批准的计划** — `apply_mid_turn_steers` 在运行中接受转向。`_is_approved_plan_implement`、`_prepare_approved_implement`、`_session_plan_md_path` 把批准过的计划落到会话里的计划文件。计划正文如果没有 Markdown 标题，会补上 `# 计划`，OpenTUI 才打开批准 / 拒绝条。
- **路由意图** — `core/agents/router.py` 的 `RouteIntent`、`parse_route_intent`、`is_open_only_preview_task`。
- **任务存储跨进程** — `appserver/task_store.py` 用跨进程锁认领任务、合并事件。同一条任务被两个进程看到时，不会各写各的。
- **熔断器** — `recovery/circuit_breaker.py` 有冷却窗口和显式的阻断判断，打开之后不会永远开着，也不会在冷却期里继续放行。
- **新模块** — `core/cu/`（Computer Use：绑定、浏览器、启动器、设置、规格）、`core/progress_labels.py`、`core/loop_exit.py`、`core/ttft_clock.py`；工具 `tools/final_answer.py`、`tools/virtual_browser.py`、`tools/launch_intent.py`。
- **计划与验证** — 计划面板、批准后的实施、`validation/` 里的核对，是仓库自己的 plan → execute → validate。LangChain SDK 仍在依赖里。默认一轮对话走这个 harness。

模型传输和读工具共用 OpenCode 那张重试表：额外 5 次，一共最多 6 次请求，间隔 2 / 4 / 8 / 16 / 30 秒，等待带最多 25% 抖动。第一个 token 出来之前的连接超时会重试；内容已经开始之后的空闲超时不重试。本机配置里的 `llm.transport_retries` 或 `tool_retry_attempts` 仍可覆盖这个默认值。

流式正文若是整段重放，或是「到目前为止的全文」又发来一次，只追加新的后缀。工具循环、普通回答和卡住之后的收尾，走同一条去重。

#### 插件与能力（Phase K）

- **登记与默认值** — `CapabilityRegistry` 统一登记能力，并带默认开关表。
- **前缀跟着能力集走** — `PrefixProfile.capability_digest`。能力集变了，前缀才变；默认路径保持逐字节兼容，避免无故打掉缓存。
- **执行门** — 工具常驻前缀加 allowlist。没启用的能力不进模型看得见的工具列表。
- **三级作用域** — 全局、项目、会话。`appserver/capability_routes.py` 暴露协议方法。OpenTUI 有 `/capability` 和状态点；切换前有确认和 diff。
- **插件进程** — Bun 插件边车、pi ExtensionAPI 的一个子集、外部 agent 作为子代理 provider。插件跑在独立进程里，可以预热。
- **安装与信任** — `rxy plugin` 安装器，信任分层和安全门。极简模式与标准模式的前缀档案分开，并有 token / 缓存门禁。
- **连接** — `plugins/` 下是 catalog 和 registry。GitHub、Canva 等走 OAuth。`plugin/catalog`、`plugin/connect/start`、`plugin/connect/callback` 在协议里。token 进用户目录，不进仓库。

#### 专家团（Phase L）

- **Team Pack v2** — Agent Plugins 1.0 的解析器，加两级路由索引。`AgentSpec.extra` 上可以绑角色级的 `ecosystem.*`。
- **从一句话到骨架** — `/team-new` 走需求澄清，工坊插件给出团队骨架。
- **开箱的十三支** — 分类和共享角色库，预设团矩阵十三支。
- **两个发行形态** — `rxycode-teams` 单仓双版本，以及 `rxycode-minimal`。另有兼容性检查和用户端体检。
- **降级** — 编译器按 E0 → E1 → E2 把团队收到当前环境放得下的一档。

普通对话在专家团默认关闭时仍走单代理。

#### 长跑与 CLI 对等（Phase N）

- **`run/*`** — 持久运行的协议，CLI 和桌面源码两侧都有运行态呈现。长任务可见、可续。
- **goal** — 数据模型在服务端存储，重连时重新注入。桌面侧删掉只放在 localStorage 里的那份实现。
- **CLI 自己的设置与命令** — 设置窗口分区；命令注册；`/plugin`；`/profile` 在极简和标准之间切换；`/usage`、`/diff`、回收站、审批内联。
- **Computer Use** — 注册为第六个内置能力，并翻转默认值。`cli_list` / `cli_run` 使用固定的工具面。
- **调度** — `/loop` 的时钟在 appserver 启动时恢复。`/goal` 处于 pause 时不自动 resume。被杀掉的 bash 不复活。

#### 多模态（Phase I）

- **`vision` 重写** — 旧契约是字符串，图像在 HTTP 到模型的路上被降级。这一版透传结构化图像内容。
- **MCP** — 工具层不再丢掉 MCP 返回的图像。
- **记忆与缓存** — 图像进入消息之后，后续轮次可以引用。多模态内容参与缓存键，避免串到别的请求上。
- **桌面附件** — 源码里可以拖入图片。本页不发布新的桌面安装包，见文末资产。
- **角色、评测与配额** — 视觉 Agent 角色、多模态评测，以及清理和配额。

#### 多模型协作（Phase H）

- 一个模型做完一段之后，可以把上下文和状态交给另一个模型（handoff）。
- `core/agents/client_settings.py` 给角色绑定不同的模型客户端。
- 桌面设置页和 CLI 都能配置模型组合。不同分工可以放进评测矩阵里对比。
- 多 agent 运行时和这套多模型交接接在一起。

#### Persona、Skill 与构造接口（Phase J）

- Skill 头部可以用 frontmatter 声明元数据。
- 协议里预留 `persona` 命名空间，现有方法保持原样。
- 有蒸馏数据采集埋点，以及质量信号回填。
- 外部 Skill 按信任分级。`AgentSpec` 有稳定的程序化构造接口。

#### OpenTUI

前端 OpenTUI 新增约 50 个文件。日常看得到的是这些：

- **工具卡片** — `frontend/opentui-app/src/ToolCard.tsx`。running / ok / failed 颜色不同，显示 `durationMs`。成功后收成 `✓ 工具名`。失败给出重试入口。
- **edit 的 diff** — `lib/toolDisplay.ts` 的 `buildEditDiff` 把 edit / patch 收成增、删、上下文三种行。增加行用绿色和行首 `+`，删除行用红色和行首 `-`。
- **计划面板与后续队列** — `PlanPane.tsx`、`followupQueue.ts`、`FollowupQueueBar.tsx`。
- **思考过程** — 每个 reasoning 片段到达时就推一条快照。跑的过程中看得到，不必等任务结束。
- **会话列表** — `dialog/DialogSessionList.tsx`。
- **其它显示** — `lib/thinkingDisplay.ts`、`lib/markdownDisplay.ts`。`/help` 可以用方向键滚动。隔离子 agent 默认开启。

#### 桌面工作台在源码里的增量（Phase M）

这些改动在仓库的桌面源码里，**不包含在本页的安装包中**。要一个现成的桌面程序，请下载 v1.3.0 的 Windows 安装器、便携 zip 或 Linux AppImage。

- GUI 行为有量化基线、绝对基线门和欠账表。
- 前端超时有纪律，`agent/invoke` 不再把界面卡死在等待上。
- Composer 的 `+` 菜单补上「插件」和「专家团」。插件页升为一级导航，里面是三个 tab。
- 桌面端双模式解禁。`multiagent` 开关和思考强度在界面上分层显示。
- 专家团详情面板是六段式版式，并带 L1 摘要契约。
- `features/` 重排为 39 个模块：agents、approvals、board、capabilities、checkpoints、cli、composer、files、followup、git、mcp、plan、plugins、preview、projects、recovery、recycle、review、runpanel、schedule、sessions、settings、skills、team、threads、timeline、workspaces、worktrees 等。

#### Muse Spark 供应商（Phase O）

新增 `MuseSparkProvider`，注册进 catalog，不改既有供应商的兜底行为。仓库里有对应单测和文档。星火平台上的知识库、工作流问答节点、一句话创建智能体，这次没有逐项对上代码，不写入本页的已交付功能。

#### 传输、双开、Skills 与活动层（Phase UPDATE-02）

- **客户端构造** — `TransportContext` 与 ClientFactory（OpenCode Go）。`session_id` 贯穿 primary、child 和 eval。evals runner 与 scheduler 收口到同一个 factory。
- **CLI 双开** — 短期是私有 AppServer 加隔离的 data dir。正式形态是 socket / named pipe 加 lease，多个 CLI 可以连同一个 AppServer。
- **稳定前缀** — `STABLE_PREFIX_CORE` 把中英写作规则钉在前缀里，方便缓存命中。
- **Skills** — 含惰性加载。Team / Compose、Todo、Activity Shelf 在对应轨道里。
- **DeerFlow 投影** — Context middleware、SkillPackage 投影、Channel 契约和参考 adapter、Channel 市场元数据。
- **最终答案** — 走受限的 Markdown AST，避免把未过滤的标记直接灌进渲染。
- **桌面输入框** — 源码里的 Composer 以 Markdown 为先（Milkdown / ProseMirror）。同样只在源码中，不在本页的桌面安装包里。

#### 工程收口（Phase FIX3，14 张卡）

- **密钥** — 已知外部报告里的 API key 副本统一脱敏，文档里登记凭据所有者和轮换记录，避免 `sk-` / `ark-` 形态进入日志或产物。
- **启动** — `main.py` 的导入不再顺便把程序拉起来。启动逻辑在显式的 CLI launcher 里，脚本引用和打包更安全。
- **安装契约** — `pyproject` 的 packages 去重。装出来的 wheel 可以核对内容，避免「源码能跑、装完缺模块」。
- **Docker** — `.dockerignore` 收紧，构建上下文不再吞进无关大文件。
- **文档与类型** — 默认传输写成和代码一致的 stdio JSON-RPC，HTTP-SSE 是 fallback。依赖 constraints、bare import 收缩、渐进的 Python 类型门，属于维护性修复。
- **评测** — 「当前工作目录」这类本地任务不再被误判成必须联网。GAIA 优先读本地附件，最终答案行格式固定。BFCL 的可选参数和同一工具连打可以过。检索失败看得见，并能换引擎。附件类型走已有的 `read` / `bash` / `vision`。评测 journal 按 session 隔离，或在 busy 时加大重试。

### 修复的 Bug

- **Starting Agent worker 直到超时** — Windows 上 worker 的 `prompt` 不再和导入抢 `stdin.readline`。新会话的第一句不再卡死。`appserver/agent_worker.py`。
- **GLM / OpenCode Go 400** — `core/providers/glm.py` 丢掉网关不认识的多余字段。
- **只读回答变成空的 `[evidence failed]`** — 兜底写入之后不再把已经得到的只读回答替换掉。面对用户的失败句保持中文说明，不再把内部的 evidence 字样拼进那句话。
- **评测串台** — AgentV2 工厂补上 `set_session`。顺序评测不再共用 MemoryManager 的 `latest`。
- **OAuth** — token 的 POST 复用 authorize URL 里的同一个 `client_id`。
- **桌面连不上 appserver** — 桌面端会抢占 appserver 锁，`rxycode gui` 不再因为锁冲突连不上。该修复在源码里；本页仍不发布新的桌面安装包。
- **回退把后面的提示也藏了** — 只隐藏被截断的回退窗口，更晚的提示保留。
- **自我介绍进了工具回路** — identity chat 走聊天，不再进工具循环。
- **Shift+Enter 直接发送** — ConPTY 把换行收成 CRLF。裸 CR 是发送，CRLF 是换行。Ctrl+Enter 同样换行。
- **「不要写入文件」却被要求交出写文件证据** — 否定句先拿掉。同一句里后面还有「创建文件 report.md」这种肯定要求时，写文件门禁仍在。
- **要子代理，却进了只能 read / grep / ls 的 explore** — 请求里提到子代理、并行或 Skill 时留在父代理。那边才有 `task` 和 `skill`。
- **`/effort` 一按 Esc 就变成 default** — 没有档位就显示不支持。Esc 只关面板，不改当前档位。
- **同一段话贴四次** — 兼容网关有时重发整段，或重发到目前为止的全文。界面只追加新后缀。
- **bind digest 因换行不一致** — Windows 检出 CRLF、Linux 检出 LF 时重新绑定，摘要对齐。

### 变更

- 产品版本 **1.4.0**：`pyproject.toml`、安装脚本、OpenTUI 头部、MCP `clientInfo`、`protocol` 的应用版本。协议版本保持 `1.1.0`（`protocol/version.py`）。`appserver/` 新能力用显式握手和能力快照暴露；没实现的标成 `False`，不藏起来。
- **测试目录改成硬分层** — `tests/` 下是 `unit / integration / contract / e2e / live / stress_test / system / fixtures`，再按主题分（`test_appserver`、`test_protocol`、`test_capabilities`、`test_cache`、`test_mcp`、`test_tools` 等）。主工作区 `tests/` 约 415 个 Python 文件。这是目录规模，不是「全部测试已经通过」的结论。
- **`appserver/`** 扩成会话内服务层，约 52 个模块：权限、审批、thread fork、side chat、review、checkpoint rewind、回收站、调度、项目、插件、用量、worktree、preview、recovery、follow-up、plan files、capability、子代理和团队路由等。
- **`core/`** 约 105 个模块，含 `agents/`（blackboard、budget、coordinator、mailbox、registry、router、runtime、sop）、`subagents/` 和 `providers/`。
- **文档** — Phase 规划收在 `docs/plans/opus5-plan/rxycode/`。该目录不打进发布用的 sdist 清单；克隆完整仓库才能看到。
- **本页资产** — 只有 `rxycode-1.4.0.tar.gz`。没有新的 Desktop exe、便携 zip 或 AppImage。

## 安装 / Install

下面只装终端里的 `rxycode`。装完输入 `rxycode`，打开的是 OpenTUI。这个包里没有 Electron。桌面程序请用上一节所说的 v1.3.0 安装包；已经装过桌面端的机器，仍可以用 `rxycode gui` 把它拉起来。

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.0/install.ps1 | iex"
rxycode
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.0/install.sh | sh
rxycode
```

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.4.0" rxycode
```

用本页的源码包：

```bash
python -m pip install rxycode-1.4.0.tar.gz
rxycode
```

## 资产 / Assets

- `rxycode-1.4.0.tar.gz` — CLI / OpenTUI 源码分发

桌面安装包不在这个 tag 上。Windows 安装器、便携 zip 和 Linux AppImage 仍在 [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0)。

完整列表见 [CHANGELOG.md](../../CHANGELOG.md)。
