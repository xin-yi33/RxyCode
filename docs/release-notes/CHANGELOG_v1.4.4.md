# RxyCode v1.4.4 CHANGELOG

> 变更管理约定：开发期随改随记；条目被撤回时同步删除/标注。发版时随版本号滚动为新文件。
> 基线：v1.4.3。产品版本仍是 1.4.3。本文件从空记录开始。

## 默认 Build 工作流合同（默认打开）

当前状态：`execution.build_workflow.enabled` 默认为 true。新的开发目标会进入一次模型判断，同一个目标的续写复用这份判断。澄清、设计、项目文档和文档同步按任务选择。开发任务不能跳过验证。权限、执行边界和证据真实性不能由模型关闭。

下面「接线」里早期写成默认关闭的句子，是开关打开之前的历史记录，不代表现在的默认值。

涉及文件：`core/build_workflow.py`、`core/project_instructions.py`、`core/agent_v2.py`、`core/checkpoints.py`、`config/settings.py`、`tests/test_core/test_build_workflow.py`。

### 接线

- 难度和五个阶段由一次分类决定，不是关键词或长度规则，也不自动打开专家团。同一个目标的续写、工具结果、重试和恢复不再分类。目标变化会保留 workflow 身份、提高 contract revision，并丢掉旧回执。分类文本最多修一次；第二次仍失败就拦住开发写入，不会降成 simple。
- 开发任务不能跳过实现与测试。直达文件写入、会改东西的 shell、会改工作树的 `git`（`checkout`、`restore`、`reset`、`switch`、`clean`），以及 `task` / `spawn_subagent`，在没有合同、澄清未回答或设计批准对不上当前目标和 plan revision 时会被拦住。`git status/diff/log/branch`、只读 shell、读文件和保存普通文字不走这道门。危险命令仍走原来的安全审批。空白或只有空格的 acceptance 不能通过合同校验。
- 成功结束只认真实工具回执。回执要绑上任务身份、revision、工作区、命令、实际 cwd 和当前产出版本。省略 cwd 不能冒充检查目录。无工具结束和 `final_answer` 在缺检查、失败或证据过期时留在原工具循环里。
- `sed -i`、`cp`、`copy`、`git checkout` 以及子代理对代码或测试的修改，会使父任务已有回执失效。只读 shell 和纯文档改动不会。子代理继承父合同，不重新分类，也不把回执算回父任务。
- checkpoint 增加可 JSON 化的 `build_workflow` 字段。旧快照没有该字段时仍可读取。恢复不重置 attempt、journal 或预算。

### 审计

- 2026-10-15 复审补丁：被拦截的检查不再登记成通过回执。`shell` 先归一成 `bash`。`git diff --output` 和 `git branch 新分支` 不再当成只读。复合命令里只要有一段不能证明是只读或纯文档，旧回执就失效。回执用 ShellExecutor 实际解析的目录，相对路径不以 workspace 代替会话目录。项目规则正文和新合同记在 turn note 里，前缀冻结后仍能进模型请求。切换目标会清空文档阶段；代码再改会撤销 `doc_sync`。默认 Build 分类前先恢复未完成 checkpoint。当时 `python -m pytest tests/test_core/test_build_workflow.py -q`：31 passed。
- 2026-10-15 相邻路径补丁：纯文档例外只保留能够整句确认的单条操作（一条 `echo` / `Write-Output` / `printf` 重定向，或一条文档到文档的 `cp` / `copy` / `mv` / `move`）。换行、管道、分号、`&` 和脚本块无法整句证明时，旧回执失效，不能靠“提取到的路径都是文档”放过。两个目录参数都先分别解析再比较：工具目录走 ShellExecutor，合同相对目录走 workspace；原始字符串同为 `"."` 不算通过。恢复未完成合同后、发布 turn note 前重新读取适用项目规则，规则正文不写入 checkpoint。当时 `python -m pytest tests/test_core/test_build_workflow.py -q`：33 passed。同轮 `tests/test_core/test_checkpoints.py`：11 passed。
- 2026-10-15 双引号命令替换：PowerShell 和 bash 会执行双引号里的 `$()` 与反引号。这类展开不再被当成字面量，纯文档重定向例外也不再接受它。单引号内容仍视为字面量。`Write-Output "$(Remove-Item mod.py)" > README.md` 会删掉真实的 `mod.py`，完成门随后拒绝。`tests/test_core/test_build_workflow.py`、`tests/test_core/test_checkpoints.py`、`tests/test_core/test_lazy_import_budget.py`：48 passed。
- 2026-10-15 默认打开 Build 合同。新目标走一次分类，同目标续写复用该判断。澄清、设计、项目文档和文档同步由模型按任务选择。开发任务不能把 `build_verify` 设成 skip，检查按这次改动选择，不要求每次跑全量 CI。权限、执行边界和证据真实性不接受模型关闭。`execution.build_workflow.enabled` 默认为 true。`python -m pytest tests/test_core/test_build_workflow.py -q`：35 passed。官网 `https://api.deepseek.com/v1` 不接受模型名 `deepseek-v4.1-flash`，本地 v4.1 配置实际使用的官方名是 `deepseek-flash`。用这个名字做了三次分类：开发任务把验证固定为 run，并选了 `pytest -k parse_line`；解释和只读查找分别判为 question / read_only，并跳过验证；“继续”没有再次调用模型。`rm -rf /` 仍到达执行入口，没有被合同自动放行。随后用同一官方模型在临时目录做了多轮工具循环：合同为 `development` / `build_verify=run`，检查是 `parse_line('')` 断言和 `pytest tests/test_parse_line.py`。文件最终写成返回空列表，两条回执为通过，完成门放行。第一次按片段替换没有落盘，证据层拒绝了那次 edit；模型改用整文件写入后测试通过。
- 同轮回归：`tests/test_core/test_checkpoints.py`、`tests/test_core/test_routing_simple_queries.py`、`tests/test_core/test_request_routing.py`、`tests/test_core/test_status_band.py`、`tests/test_core/test_status_band_module.py`、`tests/test_core/test_approved_plan_implement.py`、`tests/test_agent_evidence_terminal_status.py`、`tests/test_safety_gate.py`、`tests/test_core/test_tool_message_protocol.py`、`tests/test_core/test_tool_journal.py`，135 passed。
- 2026-10-15 合同升级后的完成检查改看当前合同，不再看回合开始时的旧标志。升级说明会追加进当前模型历史。设计等待标记为等待批准：不封 checkpoint，并通过现有 `write_plan` / `event/plan` 交给审批条。批准后按原合同继续实施和验证。
- 未改产品版本，未改 JSON-RPC，未自动 commit 或 push。

## 子 Agent 独立提示词与协作原语（2026-10-14）

原先子 Agent 不合格：角色说明被拼进主 Agent 的 `/fast` 用户消息，工具面几乎只有 `task`/`explore`，运行中也不能按来源接收补充信息。这次不新做第二套模型循环，仍用独立的 `AgentV2` 实例，但提示词、上下文标记和协作工具都归这个实例，不读主会话全文。

涉及文件：`core/subagents/prompt.py`、`core/subagents/collab.py`、`core/subagents/runtime.py`、`core/subagents/manager.py`、`core/agent_v2.py`、`core/builtin_tool_registration.py`、`tools/subagent_collab.py`、`tools/subagent_task_tool.py`、`tests/test_subagents/test_subagent_prompt_and_collab.py`、`tests/test_subagents/test_execution_bridge.py`。

### 1. 新增与修复

- 子 Agent 使用自己的系统提示词。`AgentV2._active_system_prompt()` 只在该实例设置了 `_subagent_system_prompt` 时替换产品提示词，主 Agent 不受影响。提示词开门见山写「你是专门负责{职责}的助手Agent」。
- 上下文来源由运行时按真实发送者写入，模型不能自选。`[FROM_MAIN_AGENT]` 是主协调 Agent 的派发，`[FROM_USER]` 是用户直接发起，`[FROM_SUBAGENT]` 是子 Agent 的协作数据并带 `sender=`。`[TOOL_RESULT]` 只加在发给子模型的工具消息上，不包住原始返回值。未标记文本不是任务指令。
- 职责边界按工作区模式写入提示词。只读、租约写入、隔离工作区分别说明什么可以做、什么必须上报。输出默认是四节 Markdown（结论、证据、职责外事项、阻塞）；调用方给了 `output_schema` 时改为只返回符合该 schema 的 JSON。
- `/fast` 只保留为进入工具循环的路由标记，不再承载角色说明。
- 协作工具成为常驻能力，不再把 explore 当成全部：`spawn_subagent`（`sync` 等待、`async` 立即返回会话 ID、`stream` 立即返回并靠 `child_session` 事件报增量）、`cancel_subagent`、`send_message_to_subagent`、`list_agents`。`task` 仍是同步派发的别名。子 Agent 权限层放行这四项，工作区写权限仍由原策略决定。
- 运行中的补充消息进入该子 Agent 自己的收件箱，下一轮模型调用前注入。`session_id=main` 向主协调 Agent 上报，`list_agents` 能看到职责、运行状态和最近上报。`begin_child` 负责异步启动；取消仍走原会话状态机，并取消对应后台 task。
- 来源标记不再包住工具的原始返回值。错误判断和 `final_answer` 仍看原文；`[TOOL_RESULT]` 只加在准备发给子模型的那条工具消息上。
- 来源不再由模型参数选择。用户 `@agent` 的开场是 `[FROM_USER]`，主协调 Agent 派发是 `[FROM_MAIN_AGENT]`，子 Agent 之间的话是 `[FROM_SUBAGENT]` 并带真实 `sender=`。
- 上报写入父会话收件箱，父 Agent 下一轮模型调用前会读到。异步和流式任务结束后，摘要也进入该收件箱；`list_agents` 同时给出已结束会话的结果摘要。
- `stream` 与 `async` 分开。流式子会话在工具开始前发出 `child_session/tool_call`，结束后发出带结果的 `progress`。模型增量文字在输出当时记为该 child ID 的 `partial_result`，不走父会话的 `message_delta`。每个子任务用自己的上下文出口，并发不会串流。父会话只收摘要。
- 父收件箱同时接在工具循环和普通聊天上。收件箱里还有报告时，这一轮既不读也不写两级应用回答缓存，避免另一会话命中这份报告答案。
- 流式子会话执行工具时，`write_tool_call` / `write_tool_result` 改记到该 child ID，带调用 ID、参数、结果和状态。父会话不再收到 `event/tool_begin` 和 `event/tool_end`。Runtime 包装层不再另发一条同样的工具事件。主 Agent 自己的工具事件不变。
- OpenTUI 把 `child_session/tool_call` 和 `child_session/tool_result` 记到对应子代理卡片，不转成父会话的普通工具消息。Desktop 的 `tool_result` 只结束该工具，子代理仍为 running；完成只认明确终态。工具名同时接受 `tool` 和 `tool_name`。
- Desktop 子代理检查器展开后显示该次工具的调用 ID、状态、参数和结果。子代理状态仍来自会话记录，工具详情不会把它标成完成。
- 验证：`python -m pytest tests/test_subagents/test_subagent_prompt_and_collab.py tests/test_subagents/test_execution_bridge.py tests/test_subagents/test_task_dispatch.py tests/test_core/test_lazy_import_budget.py -q`，52 passed。

### 2. 数据完整性

- 产品版本仍是 1.4.3。JSON-RPC 仍是 1.1.0。没有新的安装包，也没有改协议字段。
- 子 Agent 仍然拿不到主会话全文。`ContextEnvelope` 继续只传任务和引用。
- 同一来源标记不会被重复叠加。未知来源标记会被拒绝。`[FROM_SUBAGENT]` 只表示协作数据，不能冒充用户或主协调 Agent。
- 异步取消不会留下仍在跑的后台 task。懒导入计数仍低于 181。
## 新增 RxyCode Web（2026-10-20，feat/rxycode-web）

在 CLI(OpenTUI)与 GUI(Desktop)之外新增第三条可执行入口：一个可 HTTPS 部署的 Web 面。它不做第二套 Agent 循环——Web 复用共享 `AgentV2`/Harness 循环、`ToolOrchestrator` 与安全门，只新增持久化队列、隔离 worker、租户模型和浏览器前端。

涉及文件：`packages/rxycode-server/src/rxycode_server/`（api/approvals、api/questions、api/runs、api/sse、api/auth、persistence、events、runs、quotas、previews、devices）、`packages/rxycode-worker/src/rxycode_worker/`（drain、ctl、netrelay、supervisor、journal、sandbox）、`core/agent_v2.py`、`core/session.py`、`execution/tool_orchestrator.py`、`execution/evidence.py`、`apps/web/`、`infra/compose/`、`tests/web/`、`docs/architecture/web-rules-supplement-2026-10-20.md`、`evidence/web/`。

### 1. 认证与会话（三条登录路径的边界）

- Web 登录两路：GitHub OAuth（PKCE，state 10 分钟过期）和本地密钥登录。成功签发 `rxy_session` cookie——服务端会话表只存 token 的 HMAC 摘要，TTL 12 小时；`GET /api/v1/auth/csrf` 发 `rxy_csrf` cookie，所有写请求要求 Origin 在白名单且 header/cookie 双提交一致，否则 403。
- 会话按租户隔离：User → Organization → Project → Session/Run，所有 API 按 membership 校验；`rxycode_server.main.serve(mode="local")` 在非回环绑定上直接拒绝启动（`reject_as_public_web_gateway`），公网部署必须 `mode="cloud"`。
- 三条路径互不干扰是结构性结论：CLI/GUI 无账号制——`rxycode config add-model` 把密钥写进 `~/.RxyCode/config.yaml`（`atomic_write_text` 原子写），各自 spawn 自己的 `python -m appserver`（stdio，无端口）；Web 走自己的 Postgres、密钥、cookie 与端口（compose 默认仅绑 127.0.0.1），不读写 `~/.RxyCode`；受限 turn 的 `RXYCODE_DATA_DIR` 指向 run 工作区 `.data`，不指宿主目录。前端同样三分离：终端 / Electron 窗口 / 浏览器（HTTPS+SSE），传输互不相交。CLI 与 GUI 唯一共享的可变文件是 `config.yaml`，原子写保证不被撕成半份。

### 2. Durable run 队列与恢复

- run 是 Postgres 行：`pending → leased → waiting_approval → terminal(failed/succeeded/recovery_required)`。认领走 fenced lease（worker_id + 代次）；worker 崩溃或断连，租约过期后新 worker 重认领同一 run，续接而不是重放。
- side effect 走父进程 journal（run+call 维度的 reservation/outcome）：重认领时 `completed` 直接复用结果、不再执行；`unknown`/`reserved` 一律结算 `recovery_required`，绝不盲放重试——at-most-once，失败关闭。
- 断电验证在真实 compose 栈上做：`docker compose restart postgres api`、kill/recreate worker 后数据无损、过期租约被新 worker 正确重认领（`test_w7_c05_integration`）。

### 3. 审批挂起与续接（共享 Harness checkpoint）

- 需要人工的审批/提问把 `HarnessPaused` 连同原循环的检查点（消息序列含 reasoning 字段、被挂起的调用、后续调用、循环计数、已耗预算）经 `pause_approval` 持久化（`checkpoint_z` 压缩，8 MiB 解压上限）。worker 退出挂起态进程；批准后新 worker 用 `resume_harness_turn` 回到原循环继续走模型修正/测试/Final Answer——不新起一轮，不重放原始 prompt，不许"执行完那一步就算成功"。
- 提问通道同一语义：durable 一问一答、一次性消费；多问批次由工具拒绝 `single_question_only`（每调用一问是已知边界）。

### 4. 整回合预算

- `AgentV2.run` 与 `resume_harness_turn` 统一在 `_under_turn_budget` 下：只计执行时间（挂起等待不计），超时由共享 `timeout_decision` 引擎裁决，`turn.max_extensions`/`turn.hard_cap_seconds` 封顶，拒绝即取消。drain 的 900 秒外层 `wait_for` 已删，`RXYCODE_WORKER_RUN_TIMEOUT` 不再被读取；租约存活本身不算进度。

### 5. 沙箱与凭据边界

- 每个受限 turn 在 bwrap 用户/pid/ipc/uts namespace + 私有 netns 中执行，只读最小根文件系统，仅该 run 工作区可写。egress 全部走子进程回环 relay → 父进程 allowlist 网关：CONNECT/绝对 URI/模型网关三态，真实凭据由父进程在上游注入，沙箱内不存在真 key。
- relay 移到独立守护线程 + 自己的事件循环：根因是 `tiktoken` 在 agent 事件循环里同步下载词表，转发该请求的 relay 与循环共命运造成自死锁（run 永远 `leased`）。relay 是网络生命线，现在 agent 循环任意同步阻塞都不会冻结它。
- 子进程配置改为 schema 派生构造（`_default_config()` 减去 `mcpServers`/`rag`/`appserver` 等宿主段），不再"复制后按正则擦洗"；凭据字段按 `_is_credential_key` 在任意深度剔除，`max_tokens`/`token_budget` 保留。r21–r25 安全审计的 Shell sanitizer 问题逐项处置并写入 `evidence/web/WEB-W8-C01/NOTES.md`。
- 工具结果判定不再猜 stdout 前缀：`ToolEvidence` 带 `call_id`，orchestrator 按调用记录 `{status, executed, exit_code, approval}`，`AgentV2._tool_is_error` 以结构化记录为准（`failed` 为错；`rejected`/`dry_run` 非错；`not_found` 保持历史兼容为错），文本前缀只在无记录时回退。发给模型的结果原文不变。

### 6. 部署面

- `infra/compose/compose.yaml`：gateway(Caddy，HTTPS+内部 CA，只绑回环) → api(uvicorn `rxycode_server`) → postgres/redis/minio；worker=`python -m rxycode_worker.drain`；migrate/webbuild 为一次性任务，启动顺序靠 marker 文件（本机 Docker Desktop 不支持 Windows bind mount，工作树以 tar 流入 `repo-src` 卷）。
- 三个 pip 装包服务透传 `PIP_INDEX_URL`（默认 `https://pypi.org/simple`，不设即不变）——本机容器到 pypi.org 全程 SSL EOF 时可用镜像完成 bootstrap。
- secrets 全走环境变量，文件内无明文；`cloud:*` 目标才执行，Full=审批语义而非隔离级别。

### 验证

- `tests/web/w8` 全套件：168 passed, 4 skipped（AF_UNIX/bwrap 在 Windows 预期跳过）。
- 三条复合验收链（真实 Postgres+Harness+journal：审批挂起→新实例续接→Final Answer；journal unknown→recovery_required；重复续接复用 journal 不重放副作用）：19 passed。
- `test_w7_c05_integration` 真实 compose 栈重启/重认领：PASSED 584 s。
- ruff/AST：触及模块清洁。

### 已知限制（明示，非遗漏）

- 每个挂起调用仅支持一个持久化提问。
- 无 `call_id` 的外部工具结果仍走文本前缀回退。
- `tests/web/w2`–`w6` 全量失败此前定性为本机环境/HEAD 既有问题，未逐条复验。
- 产品版本仍为 1.4.3，JSON-RPC 未改，未自动 commit 或 push。
