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
- 续接回合恢复权限模式：`Session.prompt` 的 `harness_resume` 分支此前忽略 `permission_mode`——续接后的原循环回落到 `confirm_all`，每次 `bash` 写操作都重新挂起（首轮 `full`→`full_auto` 无审批）。修复：续接同样套 `permission_mode_override`（contextvar 驱动所有门禁判定）。回归 `tests/test_core/test_session.py::test_session_prompt_resume_keeps_permission_mode_override`；部署栈内实测：批准一个挂起调用后原循环在 `full_auto` 下无新增审批地跑到 `succeeded`。

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

### W9 后端：注册登录、提交任务、准入

- **持久化会话（B1）**：浏览器会话改为 `auth_sessions` 表行——cookie token 的 HMAC 摘要是行键，TTL 7 天（`expires_at` 墙钟时间），滑动续期（`last_seen_at` 超 1 天未动才写库刷新）；注销写 `revoked_at`，被禁用用户（`users.disabled_at`）即刻全域失效。API 重启、副本迁移后旧 cookie 仍有效；进程内存里的 `sessions`/`oauth_states` 字典已从主网关移除（device 网关等无 DB 的辅助 app 保留字典回退）。OAuth state 同样落库（`oauth_states`，10 分钟过期 + 浏览器绑定），跨副本可完成回调。
- **注册与登录**：`POST /api/v1/auth/register|login|logout` 全部走 `require_write`（Origin 白名单 + CSRF 双提交）。注册模式 `RXYCODE_WEB_REGISTRATION`：`invite`（默认，需一次性邀请码）/`open`/`closed`；邀请码只存 SHA-256 摘要，用满/过期一律 `INVITE_INVALID`。密码 `scrypt$16384$8$1$` 格式（stdlib scrypt，16 字节随机盐，`compare_digest` 校验）；未知邮箱同样跑一次 scrypt（固定 dummy hash）保持时序一致；错误口令与不存在账号同回 `INVALID_CREDENTIALS`。注册在同一事务里建 User/Organization/Membership/默认项目并直接发会话；`/api/v1/auth/register|login` 有进程内固定窗口限流（每 IP 10/分、每邮箱 5/分，超限 `RATE_LIMITED`）。
- **`/api/v1/me` 契约**：严格按 §5.1 的嵌套-only 形状返回 `{user:{id,kind,email,display_name,github_id}, organization:{id,tenant_id}, membership:{role}, default_project_id}`——`email`/`display_name` 收进 `user` 内，顶层不再带 `user_id/tenant_id/capabilities`；`register`/`login` 返回同一 body（`local_login` 保留旧扁平响应）。`capabilities` 走独立端点；`capabilities.github` 仅在 client_id/secret/redirect_uri 三者齐全时为真，`github/start` 未配置时 503 `AUTH_PROVIDER_NOT_CONFIGURED`。存量 local/github 用户缺默认项目时在 `/me` 或 `POST /tasks` 处惰性补建"默认项目"。
- **注册安全修补**：邀请码消费改为单条原子条件更新（`UPDATE invites SET used=used+1 WHERE code_hash=:h AND used<max_uses AND (expires_at IS NULL OR expires_at>now()) RETURNING`），与用户插入同事务——并发抢同一 `max_uses=1` 邀请码只有一个 201、另一个 `INVITE_INVALID`，`EMAIL_TAKEN` 回滚连带撤回消费。`logout` 改为在**实际返回的** 204 响应上 `delete_cookie("rxy_session")`（原实现对注入 Response 删除后又返回新 Response，`Set-Cookie` 丢失）。
- **Admin CLI**：`python -m rxycode_server.admin`（`RXYCODE_WEB_DATABASE_URL` 取库）：`invite create --uses/--days/--note`（明文码只打印一次）、`invite list`、`user reset-password --email`（新密码从 stdin 读，撤销该用户全部会话）、`user disable --email`（置 `disabled_at` + 撤销会话）。
- **任务提交（B2）**：`POST /api/v1/tasks` 按 (tenant, request_id) 幂等——同摘要重放直接返回原 run（202，不新建会话），不同摘要 409 `REQUEST_CONFLICT`；否则先建会话（标题取消息前 40 字符、去换行）再调 `create_run`，run 创建失败（配额/冲突/活跃）时删除刚建的会话并映射错误：`RunAlreadyActive`→409 `RUN_ACTIVE`、`RunConflict`→409、`QuotaRefused`→429 `QUOTA_EXCEEDED`+`reason`。目标恒为服务端推导的 `cloud:{tenant}:{project}`，不信任请求体 target/model。`POST /api/v1/sessions/{id}/runs` 同语义（会话须属本租户，单会话单活跃 Run 不变式保持）。`runs.created_at` 落库并在每次建 run 时刷新 `sessions.updated_at`。
- **历史接口**：`GET /api/v1/sessions` 返回本租户 50 条最新会话（`updated_at` 降序，各带 `last_run{run_id,status}|null`）；`GET /api/v1/sessions/{id}/runs` 按 `created_at desc, id desc` 游标分页（opaque cursor 编码 `created_at+run_id`），`final_preview` 取该 run `assistant.final` 事件前 200 字符；`GET /api/v1/runs/{id}` 补 `created_at/message/permission_profile`。worker `claimable_run_ids` 改按 `created_at, id` 排序——早建先认领（FIFO）。
- **准入默认值（B4）**：`Limits` 增加 `window_seconds` 与 `queue_max`——窗口模式下任务数/token 只计窗口内 run（token 用 `usage_records` 真实计量加本次估算），`queue_max` 在获取 worker 前统计全局 `pending` 数、超限以 `kind="queue"` 拒绝。`create_app` 仅在 `RXYCODE_QUOTA_*`/`RXYCODE_QUEUE_MAX` 任一存在时安装 gate（`window_seconds=86400`，缺省项取 `DEFAULT_LIMITS`）；都不设时行为与旧版完全一致。compose 给 api 侧默认：并发 1、任务 30/天、token 2M/天、队列 10；同时移除 worker 的 `RXYCODE_WORKER_RUN_TIMEOUT`（v1.4.4 已改为整回合预算裁决）并同步 runbook。
- **SDK**：`apps/web/src/sdk/client.ts` 的 `Me` 更新为 §5.1 嵌套契约（`user/organization/membership/default_project_id`），新增 `getCapabilities/register/login/logout/createTask/createRun/listSessions/listSessionRuns/getRun` 类型化方法。
- **迁移**：`006_auth_and_runs`（幂等，沿用 005 的列存在性检查）——users 加 `email`(唯一)/`password_hash`/`display_name`/`created_at`/`default_project_id`/`disabled_at`，新表 `auth_sessions`/`oauth_states`/`invites`，runs 加 `created_at`+`(session_id,created_at)` 索引并把 `target_id` 扩到 varchar(128)（`cloud:{tenant}:{project}` 需 71 字符），sessions 加 `updated_at`。
- **验证**：`tests/web/w9` 全新独立套件（专用 `rxy-w9-pg:55439`，每测试重置 schema + migrate 到 head）22 passed；`tests/web/w8` 160 passed/4 skipped；`w2` auth 3 passed；threat-model 7 passed；`w5_c04/w6_c05` 会话注入回归通过；`npm --prefix apps/web run typecheck` 通过。既有问题（非本次引入）：`test_w5_c06_contract` 因 compose 一次性服务无 healthcheck 在 HEAD 上同样失败；`w6_c04` 的 bun 渲染断言在本机环境返回空。

### W9 事件链修复

- **`run.status` 全覆盖**：所有改写 `runs.status` 的路径现在都在**同一事务**内追加 `run.status` 事件 + Outbox 行（seq 仍按 `max(runs.event_seq, max(run_events.seq))+1` 分配并回写 `event_seq`）——supervisor `claim`/`commit_terminal`/`request_cancel`/`confirm_cancel`、`recovery.py` 的 `recovery_required`、park→`waiting_approval`、resume→`pending`（含 `api/approvals.py::_resume_question` 与 `approvals/service.py` 审批裁决/过期/取消路径）、`runs/service.py::complete_run`、`notifications/service.py` 直接终态写、以及 `settle_run`；payload 带 `{"status": ...}`，有 lease epoch 时附 `epoch`。`api/runs.py::cancel_run` 原有的 `cancel_requested` 事件不重复发。
- **tool 投影**：`event/tool_begin`→`tool.started`（`{"call_id","tool","title"}`，title 依次取 `arguments.description`→`command`→`path`/`filePath`，截 300 字符）；`event/tool_end`→`tool.completed`/`tool.failed`（协议 `ToolEnd` 没有 `exit_code`/`duration_ms` 字段，未虚构）。
- **delta 合并**：`_RunEmit` 内缓冲连续同 `intermediate` 标志的 `assistant.delta` 文本——缓冲年龄 ≥300ms（新 delta 到达时判定）、≥2KB、非 delta 投影前、标志翻转、显式 `flush()` 任一触发出行；进程内与受限子进程（`TurnChannel.emit`）两条执行路径的成功/失败/取消/park 出口都在外层 `finally` 调 `emit.flush()`，保证残缓冲落库。
- **notify.* 审计**：`event/message_delta|progress|reasoning_snapshot|token_usage` 不再写审计行；其余方法 payload 为 `{"params": model_dump(mode="json")}`、字符串值递归截 2000 字符，不再是 Python repr（不含 `method='...'`）。
- **journal 上限分流**：原 500 行共享计数改为 `assistant.delta` 与 `notify.*` 各自 2000 行上限；`tool.*`/`approval.*`/`question.*`/`run.status`/`assistant.final`/`usage.*` 永不被丢弃。
- **`event/agent_needs_input`（P9）**：W8 的 park/续接路径已由 drain 直接落 `approval.requested`/`question.requested`，drain 中对该通知的投影分支删除——不再重复产出 approval+question 行。
- **SSE 心跳**：follow 模式 15 秒无新事件发 `: ping\n\n`（模块常量 `SSE_HEARTBEAT_SECONDS`，测试可 monkeypatch），防止代理在长 thinking/审批等待期断连；replay 与终态即停语义不变。
- **验证**：新增 `tests/web/w9/test_event_projection.py`（15 条：tool 投影、100 delta 合并 ≤5 行且文本完整、delta/tool 交错保序、>500 delta 不丢 tool/final、notify JSON 可解析、claim/终态/取消/park/resume 的 DB 状态行、flag 翻转与显式 flush、SSE 心跳）；`tests/web/w9` 38 passed；旧契约断言同步修正——`w7_c05`（alembic head `006_auth_and_runs`）、`w2_c03`（create span 的 `telemetry.span` 行计入事件总数）、`w2_c04`（worker 可导入时 seq +1，改为确定性断言）、`w3_c02`（默认项目自动补建后登录态非空 + github/start 需配置凭据）。

- `tests/web/w8` 全套件：160 passed, 4 skipped（AF_UNIX/bwrap 在 Windows 预期跳过）。
- 三条复合验收链（真实 Postgres+Harness+journal：审批挂起→新实例续接→Final Answer；journal unknown→recovery_required；重复续接复用 journal 不重放副作用）：19 passed。
- `test_w7_c05_integration` 真实 compose 栈重启/重认领：PASSED 584 s。
- ruff/AST：触及模块清洁。

### W9 Harness：完成门回执误作废与 full 模式 bash 输出

- **只读复合命令不再误作废检查回执（H1-1）**：`_shell_invalidates_subject` 新增 `_gate_command_is_readonly` 判定层——按 `_shell_text_outside_quotes` 在引号外切分 `&&`/`||`/`;`/`|`/换行（空段、悬垂 `|`、`shlex` 解析失败一律保守作废）；拒绝命令替换（`$(`/反引号）与任何写重定向（`>`/`>>`/`&>`），仅放行 `2>/dev/null`、`>/dev/null`、`<` 输入重定向及 `2>&1`；逐段取 basename 命中 `core/build_workflow.py::GATE_READONLY_COMMANDS`（pwd/ls/cat/grep/find/sort/date/diff 等 36 个只读命令）或 `classify_tool_risk < WRITE` 才算只读。段切分用未遮罩原文的 `_gate_raw_segments`（`2>&1` 的 `&` 不拆分），`shlex` 词表保留引号内 flag；`GATE_MUTATING_WORDS` 词级谓词拦截 `find -delete/-exec/-execdir/-ok/-okdir/-fls/-fprint*`、`sort -o/--output`（含 `-ro`/`-uo` 聚合）、`date -s/--set`（含 `-us` 聚合）、`file -C/--compile`、`uniq` 第二位置输出参数——引号藏不住；`GATE_MUTATING_ARGS` 原文正则作保守兜底。精确等于必需检查命令的既有豁免不变；`classify_tool_risk` 未动（门禁语义不影响审批）。
- **作废原因进入完成门反馈（H1-2）**：`_bump_workflow_generation` 记录 `工具名: 命令/路径`（截 120 字符），内存只留最近 3 条（不进 `workflow_checkpoint_document`，不落库）。存在 stale 检查时 `_workflow_completion_feedback` 追加中文句：「这些检查在执行之后又被以下操作作废：<原因列表>。请在不再修改工作区之后，把必需检查的命令**逐字**作为最后的工具调用重新执行，中间不要插入其他命令。」
- **full 模式本地 bash 走 `_format_result`（H1-3）**：`tool_orchestrator.py::native_runner`（`full`/`full_auto` + local + production bash）构造 `{"stdout","stderr","exit_code","success"}` 交给 `tools/bash.py::_format_result`——成功无输出得 `[no output]`（旧行为返回空串），非零退出保留 `[error executing bash: …]` + `[exit code: N]`，超长输出走同一截断/spill/脱敏逻辑，超时并入 stderr 提示；`started=False` 直接返回字面量 `[error executing bash: command did not start]`（旧行为也是空串），`build_tool_evidence` 正确判 failed。capture/artifact 等未提供字段取 `_format_result` 自身的 falsy 默认，与正常路径缺省一致。
- **验证**：新增 `tests/test_core/test_full_auto_bash_format.py`（5 条：`true`→`[no output]`、exit 3 错误前缀+退出码、超 MAX_OUTPUT_CHARS 截断、`started=False` 字面量 + `build_tool_evidence` failed、超时提示）；`test_build_workflow.py` 新增 5 条（只读/作废命令表、反馈原因句、原因上限 3、fake-LLM 全回合"写文件→两条检查→只读复合验证→final_answer 一次通过"）；词级谓词加固后 `h1` 焦点用例 5 passed、ruff 清洁。`test_shell_output_capture.py` 4 条失败在干净 `04a330bb` worktree 上同样复现（Anaconda launcher stderr 噪声/真实子进程时序），判定为本机环境既有问题，非本次回归。

### W9 前端：登录注册、控制台外壳、输入框

- 路由按 W9-F1 表重写：`/` 按登录态分发；`/login`、`/register`、`/oauth/callback` 公开；`/app`（新任务首页）、`/app/s/:sessionId`（会话页）、`/app/settings` 由 `AuthGate` 守卫；`/runs/:runId` 兼容旧链接，读取 run 后跳 `/app/s/<sessionId>#run-<runId>`；`/onboarding`、`/projects` 重定向到 `/app`；usage/memory/schedule/workspace/terminal/browser 旧页保留并加守卫，不进导航。旧 `LoginPage`/`ProjectsPage` 从路由移除；`OnboardingPage.tsx`/`ProjectPanel.tsx` 文件保留并标注废弃。
- `AuthGate` 用 TanStack Query 读 `["me"]`：401 全局只处理一次（AuthGate + QueryCache/MutationCache onError）→ `/login?next=<当前路径>`（只接受 `/app…`）；网络错误显示"无法连接服务器"+ 重试，不误判为未登录。登出 `POST /auth/logout` → `queryClient.clear()` → `replace` 到 `/login`。
- 登录/注册页（F2）：居中卡片 + RxyCode 字标；邮箱密码登录、`capabilities.github` 时显示"使用 GitHub 继续"、本地模式显示"本机口令"折叠区；注册页含邀请码（`registration === "invite"` 时必填）、`closed` 时只显示"暂未开放注册"；错误码 → 中文文案集中在 `src/sdk/errors.ts`（含 `QUOTA_EXCEEDED` 按 reason 细分和网络错误"无法连接服务器"）。本机口令登录返回的是旧扁平体，前端随后取一次嵌套 `/me` 再写入 `["me"]`。
- 控制台外壳（F3）：可折叠侧栏（<768px 抽屉 + 遮罩），会话列表 `GET /sessions` 带状态芯片；顶部栏含会话标题、主题切换、控制台入口、账户/登出；`/app` 首页"今天要做什么？"+ 输入框，提交 `POST /tasks` 后跳 `/app/s/<sessionId>` 并刷新 `["sessions"]`；会话页 `GET /sessions/:id` + `GET /sessions/:id/runs` 正序渲染 run：用户消息气泡 + 状态芯片 + `RunTimeline`（props 固定 `{ runId, live }`，F4 再换内部实现；已结束 run 只拉一次、最新活跃 run 走 `useRunEvents`/`reduceEvents` 的 SSE 回放/断线恢复/游标过期重同步）。
- 状态芯片文案统一在 `features/runs/status.ts`：排队中/运行中/等待你的操作/取消中/已完成/失败/已取消/需要恢复；芯片文字使用更深的 `-ink` 变体保证 AA 对比度（`globals.css` 新增 `--rxy-*-ink`，深色主题沿用亮色）。
- 输入框：textarea 自动增高（≤200px），Enter 发送 / Shift+Enter 换行 / IME 组合输入不发送；权限下拉（每步确认/自动执行，默认 confirm）；`request_id` 在按下发送时生成，网络失败重试复用同一 id，2xx/4xx 或改稿后换新 id；草稿按会话存于 Zustand `state/ui.ts`（主题改经 cookie 持久化，满足 bundle 禁用 `localStorage` 的安全断言）。
- SDK：`Me` 嵌套合同、`capabilities`/`register`/`login`/`logout`/`localLogin`/`createTask`/`createRun`/`listRuns`/`listSessions`/`getRun`/`getSession`；CSRF token 内存缓存，403 `FORBIDDEN` 写请求取新 token 重试一次；统一 `ApiError(status, code, detail)`。
- 后端配套小修：`GET /api/v1/sessions/{id}` 返回类型注解 `dict[str, str]` → `dict[str, object]`，否则 `last_run` 对象触发 ResponseValidationError 500。
- 本地开发：`infra/scripts/web-dev.ps1` 一条命令拉起 `rxy-web-dev-pg`（127.0.0.1:55440，trust，db `rxycode`）+ Alembic head + API（mode=local，8000，`RXYCODE_WEB_REGISTRATION=open`，secret 存 `%USERPROFILE%\.rxycode\web-dev.secret`，origins 按 `-UiPort`）；文档见 `docs/deploy/web-runbook.md` 本地开发。Windows 不开 worker，提交后 run 保持"排队中"属预期。
- 旧浏览器测试迁移（保留行为、不弱化安全断言）：`tests/web/w3/` 中 `_login` 改走 `/login` 本机口令；C02 断言 `/app` 会话持久化替代已删除的 `/onboarding`+项目导入；C03 run 页面改走 `/app/s/:sessionId`；C05 终端 WS 握手补发 `Origin`（真实浏览器必发，服务端对无 Origin 客户端 fail-closed）；C06 审批卡交互改为 `page.evaluate(fetch)` 且不再 return promise（修复 route gate 死锁）；C07 响应式/axe 断言改在会话页；C01 删除指向已移除模块 `sessionVisualState.ts` 的 sourcemap 断言，Electron/node builtins/`localStorage` 等安全断言全部保留。
- 验证：`npm --prefix apps/web run typecheck` 与 `build` 通过；`pytest tests/web/w3 -q` 23 passed；`pytest tests/web/w9 -q` 38 passed；Playwright 冒烟（注册→/app→提交→排队中→刷新→登出→后退无数据→重登会话保留）通过；截图在 `~/.rxycode/output/w9-screens/` 与 `w9-review/`，375px 无横向滚动。
- 已记录待返工（随 F4/F5 批处理）：输入框改为单圆角面板内嵌无边框 textarea + 行内权限/发送；活跃 run 时发送按钮应为停止；账户入口移至侧栏底部；会话页占位时间线重复的状态行由 F4 真时间线替换。

### W10-D1 生产镜像

- **三个镜像**（`infra/docker/`，本机构建、不推送，标签 `rxycode-{api,worker,web}:<git-short-sha>`+`:latest`，构建脚本 `infra/scripts/build-images.ps1`，透传 `RXYCODE_BUILD_COMMIT`/`RXYCODE_BUILD_TIME` build-arg）：
  - `api.Dockerfile`：`python:3.12-slim` + 预装 `requirements-web.txt` + `/repo` 白名单负载（根包 `__init__/main/api_server*`、20 个运行时子包——`appserver…validation`，`plugins/` 目录因 `appserver/plugin_service.py` 以 `parents[1]/plugins` 解析而保留——+ `packages/*/src` + `rxycode-server/alembic` + `infra/compose/sandbox-policy.yaml`）+ `/opt/pkg` 桥接包（`RxyCode.RxyCode1_1_0`→`/repo` 软链，与 compose 完全同构）。`CMD python /opt/serve_web.py`（compose 内联脚本落为文件；走 `serve()` 保留 local+非公网绑定拒绝守卫，监听地址由 `RXYCODE_WEB_BIND` 控制，默认 0.0.0.0）。迁移不在入口（D2 负责编排）。
  - `worker.Dockerfile`：同一负载 + `apt-get install bubblewrap`（0.12.0），`ENTRYPOINT worker-entry.sh`（把 compose 内联的"写 config.yaml 部署模型配置"bootstrap 搬进镜像，随后 `exec` drain 保证 PID 1 仍是 python）+ `CMD python -m rxycode_worker.drain`。
  - `web.Dockerfile`：多阶段 `node:22-slim`（`npm ci`+`npm run build`，树形布局与 webbuild 服务一致，补 `/build/frontend/.../sessionVisualState.ts`）→ `caddy:2.11`（与 compose gateway 同 tag），`dist`→`/srv/www`，`infra/compose/Caddyfile` 烘入 `/etc/caddy/Caddyfile`（D2 将换 Caddyfile.prod）。
- **`infra/docker/requirements-web.txt`**：api+worker 共用的全量 pinned 依赖——取运行中 `rxydemo` 容器 `pip freeze` 的并集（api 38 项 + worker 101 项，含 uvicorn[standard] 的 httptools/watchfiles/python-dotenv；`websockets` 取 worker 侧 16.1.1，langgraph-sdk 上界不容 17.3；`rxycode-runner` 不在 PyPI 安装、维持 PYTHONPATH 源码包；pywinpty 为 Windows-only 不入镜像）。`pip install` 时不再依赖 pip 解析的运气——全部 transitive 钉死。
- **`apps/web/package-lock.json`**：新增 npm 锁文件（`npm ci` 的前提；resolved 指向本机已验证可达的 npmmirror 源）。
- **`/api/v1/version`**：`api/version.py`，无鉴权，返回 `{commit, built_at}`——commit 取 `RXYCODE_BUILD_COMMIT`（镜像 ARG 烘入 ENV）否则 `git rev-parse --short HEAD` 否则 `unknown`；built_at 取 `RXYCODE_BUILD_TIME` 否则 `app.state.built_at`（`create_app` 记录的进程启动 ISO 时间）。
- **`.dockerignore`**：在既有文件上扩充 `.env*`、`docs`、`evidence`、`research`、`receipts`、`scratch`、`qa-artifacts`、`tests`、`evals`、`platform_tests`、`**/node_modules`、`**/__pycache__`、`**/build`、`**/dist` 等——三镜像上下文传输约 5.9MB，镜像内 `/repo` 无 tests/docs/.env（`docker exec ls` 核实）。
- **验证**：`powershell -File infra/scripts/build-images.ps1` 三镜像全部构建成功（api 931MB、worker 932MB、web 98.1MB）。`docker run` api 镜像 + dev pg（`host.docker.internal:55440`，裸 `docker run` 需 `--add-host host.docker.internal:host-gateway`）：cloud 模式 `-p` 发布端口后宿主机 curl `GET /api/v1/version` → `{"commit":"6ed5e2fa","built_at":"2026-10-20T15:31:37Z"}`、`/api/v1/auth/capabilities` → `{"mode":"cloud",...}`、`/api/v1/auth/csrf` → 200；`probe_api.py`（app 层 + SELECT 1）通过。local 模式 `RXYCODE_WEB_BIND=127.0.0.1` 容器内三端点 200（serve() 非公网绑定拒绝守卫仍生效）。worker：drain 作为 PID 1 轮询 dev PG 无报错、`probe_worker.py` 通过、`userns_available()`=True（`seccomp=unconfined` 下，bwrap 0.12.0）。web：容器内 Caddy 内部 CA 签发 localhost 证书，`GET /`（SNI localhost）→ 200 返回真实 `index.html`+hashed assets。新增 `tests/web/w9/test_version.py` 3 passed。整栈 `compose up` 级验证归 W10-D2（prod overlay）。
- **偏离说明**：compose 里 worker 的 `cp -a /repo-src /repo` 不再需要（镜像层可写）；web 的 `npm install` 升级为 `npm ci`（锁文件已补齐）；两处 marker 等待循环留给 D2 的 overlay 编排替代。

### W9 前端：F4/F5 时间线与交互卡

- **事件归约器**（`features/runs/eventReducer.ts`）：单趟归约同时产出 §5.4 `RunView`（`status`/`activity`/`timeline`/`usage`/`lastSeq`/`leaseEpochs`）与旧 W3/W6 `Projection` 形状（`order`/`answer`/`intermediate`/`tools`/`approvals`/`plans`/`todos`/`agents`/`questions`/`runStatus`）——`reduceEvents(events, initialStatus, statusWatermark, runId)` 签名与旧合同逐位兼容，`view` 为新增字段。输入按 seq 去重、乱序事件挂起等缺口；非 intermediate `assistant.delta` 归并为连续 text 项；`intermediate:true` 只刷新 `activity` 状态行；`tool.started/completed/failed` 按 `call_id` 更新同一行（无 started 时按完成态插入，`exit_code`/`duration_ms` 只在协议带时透传）；`assistant.final` 产出 final 项并删除与正文完全相同的末尾 text 项；`approval.requested/resolved/resumed`、`question.requested/resolved`（含 `header`/`options`/`input_type`）投影为交互卡并在解决后折叠；`turn.paused` 只把非终态、非取消中的 run 显示为"等待你的操作"；`usage.updated` 进 `view.usage`；`worker.lease` epoch 进 `leaseEpochs`；未知类型忽略。`window.__rxyReduce(events, runId, initialStatus)` 仅 `import.meta.env.DEV` 挂载，供 Q1 注入测试。
- **SSE 跟随**（`features/runs/useRunEvents.ts`）：初始 `GET /runs/{id}` —— 401 跳 `/login?next=…`、404 显示"任务不存在"；状态以 `run.status` 事件为权威，初始 `status` 只作种子。终态 `run.status` 到达 → 恰好补拉一次 `follow=0` 全量回放并入归约 → 关死 EventSource、不再重连；终态 run 初次加载也只回放不订阅。SSE 断开按 1s/2s/4s…封顶 30s 退避，每次重连前先 `GET /runs/{id}`，见终态即收尾不再重连；`CURSOR_EXPIRED`（HTTP 409 或 follow 流 `event: error` 帧）→ `cursorExpired`+`snapshotSeq` 交由 UI 显示"重新同步"；卸载时关闭 EventSource 与重试定时器。`fetchRunView(runId)` 一次性视图供控制台使用（不走 SSE）。
- **时间线 UI**（`features/timeline/`）：`Timeline.tsx` 顶部状态行 = 状态芯片（`status.ts` 中文文案）+ activity 截断 + 连接态"重连中…" + 创建时间；`run.created`→用户气泡、text/final→Markdown、tool→`ToolRow`、approval/question→交互卡；跟随滚动（在底部自动滚，离底浮"↓ 新消息"，sticky 在列表末尾、浮于输入框上方）。`ToolRow.tsx`：`▸ {tool} {title}` 灰色紧凑行，运行中 spinner / 完成 ✓ / 失败 ✗，exit code 只在协议提供时显示，点击展开等宽 summary（≤20 行可滚）。`Markdown.tsx`：`react-markdown@10.1.0` + `remark-gfm@4.0.1`（精确钉版，进 `package.json`/`bun.lock`）：代码块带复制按钮、表格横向滚动、http(s)/`mailto:` 链接 `target=_blank rel="noopener noreferrer"`、其他协议渲染为纯文本。
- **审批/问题卡**（`features/approvals/ApprovalItem.tsx`/`QuestionItem.tsx`）：审批卡"需要你批准" + 工具/命令（等宽）/说明/工作目录 + 批准/拒绝；提交前先 `GET /approvals` 取最新 `revision` 再 `POST {approval_id, decision, revision}`；409（`APPROVAL_STALE`）再拉一次——已不在 pending 列表则折叠"已被处理"，仍在则提示重试；网络错误恢复按钮并显示"提交失败，可重试"；`approval.resolved`/`approval.resumed` 折叠为一行（已批准/已拒绝/已过期/已取消）。问题卡：粗体 `header` + `prompt` + 选项按钮（直接提交 `value`）+ 仅 `input_type="text"`（无选项）时渲染自由输入"发送"——服务端对带选项问题只接受选项值（`answer_question` 的 `ValueError` 分支）；挂载时一次性 `GET /questions` 确认仍在 pending（取代旧 2s 轮询），已不在则折叠"已被处理"；409（`QUESTION_STALE`）同审批卡语义。
- **控制台**（`features/console/ConsolePanel.tsx`）：顶栏控制台按钮开/关，Esc 或 × 关闭；≥1280px 为 400px 右侧面板（`xl:static w-[400px]`），以下为 `fixed inset-0` 全屏覆盖层。三页签：**活动** = 会话所有 run 的工具行（全部/仅失败过滤，带 run 前缀 + seq）；**运行** = 每个 run 的 Run ID（可复制）/状态/创建时间/续接次数（`worker.lease` epoch 数减一）/最新 seq/权限模式；**用量** = 每 run 的模型/Tokens/金额 + 会话合计，未上报字段显示"未上报"而非 0。数据用 `fetchRunView` 批量回放（有活跃 run 时 10s 轮询刷新）。旧底部 steering 输入框移除——取消改由输入框的停止键承担，`steerRun` 仍留在 SDK（后端端点真实存在）。
- **输入框返工**（`Composer.tsx`）：单圆角面板，无边框自动增高 textarea（≤200px）+ 行内权限 pill + 圆形发送键；下方提示"Enter 发送，Shift+Enter 换行"；会话有活跃 run（pending/leased/running/waiting_approval/cancel_requested）时发送键变方形**停止**键 → `POST /runs/{id}/cancel`，textarea 禁用，取消中显示 spinner；草稿/`request_id` 幂等逻辑不变。
- **会话页**（`SessionPage.tsx`）：占位 `LiveTimeline` 重复状态行移除——`RunTimeline` 即真时间线（run 详情页锚点 `id="run-<runId>"` 供 `/runs/:id` 兼容跳转）；"加载更早的任务"分页与 5s 活跃轮询保留；`run.final_preview` 仅在回放无 text/final 时兜底显示。
- **侧栏账户条**（`Sidebar.tsx`）：底部新增头像 + 邮箱/昵称按钮，弹出菜单含"设置"（`/app/settings`）与"登出"（`logout` → `queryClient.clear()` → `/login`）；顶栏随之精简为 菜单/标题/控制台/主题 四键。`/app` 空态改为"今天要做什么？"+ 输入框整组垂直居中。
- **SDK 修正**（`sdk/client.ts`/`errors.ts`）：`RunDetail` 对齐 `GET /runs/{id}` 真实字段（无 `final_preview`）；`listApprovals`/`listQuestions` 返回类型补齐 `call_id`/`permission_scope`/`arguments`/`status` 与 `header`/`options`；错误体把 FastAPI `detail` 也映射为 `code`（覆盖 `APPROVAL_STALE`/`QUESTION_STALE`/`RUN_TERMINAL`/`RUN_NOT_FOUND` 等 `HTTPException` 码）并补对应中文文案；`writeJson` CSRF 重试逻辑不变。
- **移除的旧文件**：`features/chat/ChatPage.tsx`、`features/approvals/ApprovalCard.tsx`、`features/plan/PlanDock.tsx`、`features/artifacts/ArtifactPanel.tsx`（占位渲染被真时间线取代，无路由引用）；`features/notifications/RunStatusBanner.tsx` 与 `features/agents/AgentTree.tsx` 保留——`tests/web/w3`（C07 文件存在断言）与 `tests/web/w6`（C04 直接 `renderToStaticMarkup`）仍按其路径驱动。
- **验证**：`tsc --noEmit` 与 `bun run build` 通过；`pytest tests/web/w9 -q` 41 passed；`pytest tests/web/w3 -q` 23 passed（需 `PYTHONPATH` 含 `packages/*/src`——`rxycode_server.main` 引入了 `rxycode_runner`，本机未 `pip install -e` 各包时收集即报 ModuleNotFoundError，属环境前提非本次改动）；Playwright 冒烟（临时脚本，不入库）：注册新用户 → `/app` → 提交任务 → 会话页 run 卡正常（状态"排队中"，worker 缺席属预期）、输入框为停止态、控制台三页签 + Esc 关闭、375px 无横向滚动、无 console error。截图：`%USERPROFILE%\.rxycode\output\w9-f4-screens\`（01-login / 02-app-empty / 03-session / 04-console-run / 05-app-375）。
- **偏离说明**：`RunView` 的 `status` 不受 `statusWatermark` 影响（`run.status` 事件天然幂等重放，旧字段才保留水位语义）；问题卡的自由输入框按 `input_type` 渲染（choice 不显示）——后端对带选项问题拒绝非选项值，显示输入框只会必然失败；控制台不含 steering 输入（F5 只要求三页签）。

### W10-D2 生产 compose 叠加与备份

- **`infra/compose/compose.prod.yaml`**（新）：生产 overlay，`compose.yaml` 不动。api/worker/gateway 换用 D1 镜像 `rxycode-{api,worker,web}:${RXYCODE_IMAGE_TAG:-latest}`——启动不再 pip/apt/npm，也不依赖 repo-src 播种与 marker 文件；`reposync`/`webbuild` 被钉到 `dev-seed` profile（prod `up` 不再启动），`migrate` 保留为一次性服务（api 镜像 + `python -c … upgrade_head`，`depends_on postgres: service_healthy`），api/worker 改以 `depends_on migrate: service_completed_successfully` 排序，gateway 等 api healthy。端口：gateway 只发布 `127.0.0.1:${RXYCODE_HTTP_PORT:-8080}:80`（供主机 tailscaled 回环转发，443 不发布），postgres/redis/minio/api 以 `ports: !reset []` 清空发布；prod 渲染结果中无任何 `/repo-src` 引用。内存上限 `mem_limit`：api 300M / worker 2G / postgres 256M / redis 64M / minio 256M / gateway 64M（D4 实测后再调）。env：`RXYCODE_WEB_MODE=cloud` 与 `RXYCODE_WORKER_EXECUTION=cloud-only` 在 overlay 中钉死不可被 env 覆盖；`RXYCODE_WEB_ORIGINS` 改为 `${RXYCODE_WEB_ORIGINS:?}` 必填（无 insecure 默认），`RXYCODE_LLM_BASE_URL`/`RXYCODE_API_KEY` 同改为必填（无端点的生产 worker 只会认领后失败）；`RXYCODE_WEB_REGISTRATION` 默认 invite、`RXYCODE_WEB_RATE_LIMIT_RPM` 默认 120；`RXYCODE_QUEUE_MAX=0` 即暂停新任务的开关（429，运行中不受影响）。
- **`infra/compose/Caddyfile.prod`**（新）：站点 `:80`（TLS 由 tailscaled 终止，`tailscale funnel --bg --https=443 http://127.0.0.1:8080`），无 `tls internal`；反代规则与 dev 版一致——`/api/*`→`api:8000`（SSE `flush_interval -1` + `X-Forwarded-Proto https` 钉死，公网侧恒为 https），其余→`/srv/www` SPA；preview token 缝与 admin :2019 探针保留；去掉 HSTS（:80 上无意义）。全局 `servers { trusted_proxies static private_ranges }`：信任私网对端注入的 `X-Forwarded-For`，tailscaled 转发后 API 限流/日志拿到真实客户端 IP（部署待验证项：API 日志应见手机公网 IP 而非 Docker 网关）。`caddy validate` + `caddy fmt` 均干净。
- **`infra/scripts/backup.sh` / `restore.sh`**（新，bash，`set -euo pipefail`，无密钥，接受 `-p` project / `--env-file`）：备份 = `compose exec postgres pg_dump -Fc` + 逐卷 tar（`worker-data` 工作区、`minio-data`、`redis-data`、`caddy-*`；跳过 `pg-data`（dump 覆盖）与 `repo-src`/`boot-state`/`web-dist` dev 播种卷，可 `RXYCODE_BACKUP_SKIP_VOLUMES` 调整）→ `$RXYCODE_BACKUP_DIR/<project>/<时间戳>/`（默认 `D:\rxycode-backups`，Windows 路径自动转 /d/…），保留最近 7 份。restore.sh 在项目有运行中容器时拒绝执行；先逐卷擦写恢复 tar，再单独拉起 postgres 做 `pg_restore --clean --if-exists`，结束后停回——栈的启动仍由运营者 `up -d`。
- **`infra/compose/.env.prod.example`**（新）：全部必填/可选变量带注释、无真实值；`.gitignore` 增加 `!.env.prod.example`/`!.env.example` 反豁免使其可入库（其余 `.env*` 仍被忽略）。
- **runbook**：新增"生产部署（自托管 + Tailscale Funnel）"节——前置条件（Tailscale 登录 + 后台开启 Funnel/MagicDNS/HTTPS、`.wslconfig` ≥6G、Docker 数据迁 D:、禁睡眠）、`.env` 放 `D:\rxycode-prod\`、启动/`funnel --bg`/自检/建邀请码命令、E-1/E-2/E-3 手机流量验收（含 >5min SSE 不断流与真实 IP 待验证项）、任务计划程序每日备份、`down`→restore 恢复流程、`RXYCODE_QUEUE_MAX=0` 暂停开关与 retag+`up -d` 回滚。
- **验证（离线）**：`docker compose -f compose.yaml -f compose.prod.yaml config` 渲染干净（仅 gateway 8080 发布、无 repo-src/marker/443）；`bash -n` 两脚本通过；`caddy validate`（caddy:2.11）`Valid configuration`，`fmt` 无差异。整栈 `up` 演练留待运营者按 D3 执行（本机 Docker VM ~1.9G，且需先调 `.wslconfig`）。
- **偏离/发现**：base `compose.yaml` 注释中的 `${VAR}` 字面量使 `compose config` 打一条既有 warning（未改 base 文件）；实测本机 Windows 路径 bind mount 可用（D1 镜像时代），故按卡片采用 `./Caddyfile.prod` bind 挂载覆盖镜像内 `/etc/caddy/Caddyfile`，web.Dockerfile 未改——若 D3 发现 bind 挂载回归，备选是把 Caddyfile.prod COPY 进镜像再以 `--config` 指向。

### W9 egress：TLS 隧道半关闭崩溃

- `rxyw9e2e` 验收栈实测发现：`egress.py::_pipe` 在管道结束时调用 `writer.write_eof()`，TLS transport（连模型上游的 HTTPS）抛 `NotImplementedError`——未捕获，经 `_tunnel` 的 `gather` 传播成 `egress request failed`，隧道在响应收尾时被拆除；同一 run 出现 92/167 次 tool 失败并最终 `recovery_required`。修复为 `can_write_eof()` 守卫 + 补捕 `NotImplementedError`（TLS 不支持半关闭时直接跳过）。
- 回归测试 `tests/web/w9/test_egress_eof.py`（2 条：TLS writer 不调用 write_eof 且不崩、普通 writer 正常半关闭）。

### W9-A1 忘记密码流程

- **后端**（`api/auth.py` + 新模型 + 迁移 `007_password_resets`）：`POST /api/v1/auth/forgot` 恒返回 `{"ok": true}`（形状不泄露邮箱是否存在，无枚举面）；命中已注册邮箱时签发 `secrets.token_urlsafe(32)`，库中只存 HMAC 摘要（`password_resets` 表：token_hash 主键 + user_id + created/expires/used_at），30 分钟有效、一次性，且签发新 token 会立刻作废该用户所有未用旧 token（只有最新邮件链接可用）。`POST /api/v1/auth/reset` 校验 token 未用未过期 → 重写 `password_hash`（scrypt）→ 标记 used_at → **撤销该用户全部 `auth_sessions`**；失败统一 `RESET_INVALID`（未知/已用/过期同码，无 oracle），密码长度不合归 `INVALID_INPUT`（校验在消费 token 之前，token 仍可再用）。限流复用 `AuthRateLimit`：forgot 走 IP 10/min + 邮箱 5/min，reset 走 IP 10/min + token 前缀 5/min。
- **投递**：`RXYCODE_SMTP_URL`（`smtps://` 隐式 TLS / `smtp://` + STARTTLS，新模块 `mailer.py` 仅 stdlib `smtplib`+`EmailMessage`，`RXYCODE_SMTP_FROM` 可指定发件人）配置时走真实邮件；**未配置且 `mode="local"`** 时响应内联返回 `reset_url`（开发兜底，loopback-only 网关）；**cloud 无 SMTP** 时 `capabilities.password_reset=false`，登录页"忘记密码？"链接不渲染——不承诺交付不了的链接。重置链接基址取请求 `Origin`（已被 `require_write` 白名单校验），Vite 开发/Caddy 生产均正确。
- **前端**：新页 `ForgotPasswordPage`（`/forgot`：邮箱 → "如果该邮箱已注册…"统一文案；开发模式显示内联重置链接）、`ResetPasswordPage`（`/reset?token=…`：新密码+确认 → 成功提示"所有会话已退出"→ 去登录；`RESET_INVALID`→"重置链接无效或已过期"）；`LoginPage` 密码标签右侧加"忘记密码？"（仅 `password_reset===true` 时）；路由 `/forgot`、`/reset` 公开挂在 `AuthGate` 外；`sdk/client.ts` 增 `forgotPassword`/`resetPassword`/`Capabilities.password_reset`，`errors.ts` 补 `RESET_INVALID` 中文。
- **生产接入**：`compose.prod.yaml` 透传 `RXYCODE_SMTP_URL`/`RXYCODE_SMTP_FROM`（`${VAR:-}` 可选）；`.env.prod.example` 补注释样例；runbook 环境表 + 段落说明（投递语义、30min/一次性/全会话撤销、local 兜底边界）。
- **测试** `tests/web/w9/test_password_reset.py`（7 条）：完整链路（forgot→local 内联链接→reset→旧密码 401/新密码 200/旧会话 cookie 401）、token 一次性、仅最新链接有效、未知邮箱同形状不落库、过期 token 拒绝且密码不变、capabilities（local=true / cloud 无 SMTP=false）+ cloud 形状一致、非法 token/短密码边界（短密码不消费 token）。

### W9-Q1 端到端验收修复（测试侧）

- `test_e2e.py` 首轮实跑：E-1 身份、E-2 主任务、E-3 审批、E-6 跨租户隔离、证据索引 **通过**；E-4/E-5/E-7/E-8/E-9 失败，逐条定位均为测试设计缺陷而非产品 bug——
  - **E-4**：confirm 档的 run 会停在审批卡上，但测试循环只处理问题卡 → run 永远 `waiting_approval` 超时。修复：循环内复用 E-3 的"批准 pending 审批卡"逻辑。
  - **E-5/E-7/E-8**：E-4 残留的活跃 run 撞 `QUOTA concurrency=1` 准入（产品正确行为），后续 `POST /tasks` 返回"你已有任务在运行"而不跳转。修复：新 `ensure_idle()` 助手——提交类场景前先取消用户全部非终态 run 并等其到达终态（`cancel_requested` 也占并发位，等 worker ack）。
  - **E-9**：`aside[aria-label="控制台"] button:has-text("运行"/"用量")` 子串匹配命中 39 个含同字样的工具行按钮（strict mode violation）。修复：改 `get_by_role(button, name=…, exact=True)`。
  - **E-9（二轮）**：16 个 viewport×theme 浏览器上下文在数秒内并发起建，`/me`/`/sessions` 撞 api 每 IP 240rpm 默认限流 → AuthGate 落"无法连接服务器"卡、`textarea[aria-label="消息"]` 30s 不出。属测试突发非产品信号（限流器本体由模块测试覆盖）；e2e 栈以 `RXYCODE_WEB_RATE_LIMIT_RPM=2000` 拉起，docstring 已注明。
  - **E-2（二轮）**：`kinds` 顺序断言 `i_text < i_tool` 假设"先 narration 后工具"，实测模型首轮直接 tool-call（`['user','tool','text','tool',…]`）——合法行为。断言收窄为真实不变量：user+final+tool 在场、final 最后、tool 先于 final。
- **最终结果（2026-10-21，deepseek-flash 实模型）**：**E-1..E-9 全绿，10 passed / 256s**。E-1 注册/刷新/API 重启保持登录/登出；E-2 主任务带工具行与表格 Final（`succeeded`）；E-3 审批卡批准×2 后取消落 `cancelled`；E-4 N/A（agent 未提问）；E-5 停止→`cancelled`（watchdog ~3s 检出）；E-6 跨租户隔离；E-7 `succeeded`；E-8 并发占用 429"你已有任务在运行"；E-9 40 张 4 视口×双主题截图（控制台/用量/run 视图/审批卡）无横向滚动无白屏。证据落 `~/.rxycode/output/w9-e2e/index.json` + 逐场景 `.events.json` 回放缓存。

### W9-Q1 端到端验收修复（产品侧：bash 写路径分析器后缀误报）

- E-2 复跑暴露真实 bug：完成门禁执行 `test -f hello.py && test "$(python hello.py)" = "hello" && echo A > .p3` 被拦 `[blocked: bash write path not allowed: py]`，run 挂 `waiting_approval`、agent 烧 ~86 万 token / 60+ 轮反复探测后向用户提问（H1 成本问题的又一入口）。
- **根因**（`core/safety/policy.py`）：`_BASH_MUTATING_OPENER_RE` 的 `(?<![$:])\b` 把 `hello.py` 中 `.` 之后的 `py` 当成解释器动词（`.` 是非单词字符，`\b` 成立）；`test`/`cat`/`ls`/`grep`/`echo` 均非 MUT 动词、无人消费尾部参数，于是该 `py` 开出一个"无参解释器调用"事件 → fail-closed。`.php` 同理；`rm -f hello.py` 恰好不炸（`rm` 的 verbseg 吞掉整个尾部）。
- **修复**：opener 与 `_MUT_VERB_WORDS_RE` 统一加 `(?<![^\s/\\]\.)` lookbehind——`.` 前为任意非空白非斜杠字符（`a.py`/`*.py`/`?.php`/`x.{py}` 等所有文件名后缀与 glob）不再开事件；`./rm` 等路径执行体不受影响（`.` 前是 `/`）。
- **回归**：`tests/test_safety_policy.py::test_bash_filename_extension_is_not_an_interp_verb`——良性面（`test -f`/`cat`/`grep`/`echo *.py`/原门禁命令全文/`python hello.py`/`py hello.py`）全放行，恶意面（`rm -rf /`、逃逸重定向、`sed -i` 越界、`xargs rm` 载具）仍拦截；分析器套件 139+1 全绿。

### W9-Q1 端到端验收修复（产品侧：防探测螺旋 + 停泊取消语义）

- **blocked 文案可操作化**（`policy.py::BASH_WRITE_BLOCKED_HINT` + `tool_orchestrator`）：bash 写路径闸的拒绝文案此前只有 `[blocked: …]`，模型不知道"换载具/引号/env/cd 都改变不了结论"（实测一个 run 探测 60+ 轮、烧 ~86 万 token 后向用户提问）；现附加"判定对命令形状是确定性的，内联解释器请改写脚本文件按路径执行"指引。复跑实证：模型首轮即自我纠偏"改成只做目录探查，不调用解释器"。
- **契约提示词防 `-c`**（`agent_v2` 两处 required_checks 提示）：必检命令禁用 `python -c`/`node -e`/`bash -c` 内联载荷（沙箱对不可分析的 `-c` 一律 fail-closed，永远过不了闸），改用"先写小脚本文件、检查命令按路径执行"。复跑后契约命令已变为 `test -f hello.py` + `test "$(python3 hello.py)" = "hello"`。
- **取消结案语义**（`drain.py::_cancel_effects_known`）：`confirm_cancel` 此前对"有前置 attempt 活动"的取消一律 `recovery_required`，且 `cancelled_by_request` 结案路径硬编码 `effects_known=False`——用户点"停止"永远落 `recovery_required`（实测 E-3/E-5 两处）。现判定改为"本 drain 执行取消后子进程可证已死"：`proc` 已收 `returncode`（受控 kill 路径 `_wait_child` kill+wait 收口）或 `proc_identity.is_running()`（psutil 复核 pid+create_time，防 pid 复用误判）为否 → `cancelled`；只有子进程存活无法证伪才 `recovery_required`（audit r13 本意收窄到真未知场景）。单元测试 `test_w7_c05_cancel_effects_known_split`（6 例双向覆盖）。
- **取消检出延迟**（`drain.py::_lease_watchdog`）：watchdog 此前把"租约续约"与"取消检测"绑在同一 `ttl/2` 节奏——120s 租约下停止请求 ~60s 才被看到（实测取消在 lease 后 +0.7s 发出、子进程又跑了 ~58s）。现解耦：状态 SELECT 每 ~3s 轮询（`poll=min(3,interval)`），续约仍按原 `renew_period` 节奏（`min(interval, ttl-margin)`，短 TTL 下保证首次续约先于到期，修正了 poll 重构引入的 `next_renew` 首跳点错误）。回归测试 `test_w7_c05_watchdog_polls_cancel_faster_than_renewal`（ttl=40 时取消 ~3s 检出、turn 早终态时续约 0 次证明解耦）。
- **证据层：只读 git 失败降级为 attempt**（`execution/evidence.py` + `agent_v2`）：`git` 工具静态标 WRITE，但沙箱无 `git` 二进制时 `git status` 之类只读探测失败会把已完成的最终答复整个替换成 `[evidence failed: ...]`（实测 E-2：`hello.py` 写好且检查通过、顺手探了一次 git 失败 → 答案被抹）。`ToolEvidence` 新增有界 `args` 投影字段（仅 ≤200 字符的标量值——够分类调用、不把文件内容/payload 写进 journal），`_evidence_git_failure_is_attempt` 复用 `git_invocation_is_readonly` 判定：`status`/`diff`/`log`/list-only `branch` 等只读子命令失败且有已验证写入 → attempt；`commit`/`push`/`checkout -b` 等改写类仍 critical。测试 `test_failed_readonly_git_probe_does_not_override_written_artifact` / `test_failed_mutating_git_still_overrides_completed_answer` 双向覆盖。
- **完成门回执子句级匹配**（`agent_v2::_command_ran_check` + `_command_effective_workdir`）：`required_checks` 回执此前逐字比对命令文本（`check.command != command`），模型合法的等价修饰全部落空——实测一轮 E-2 里 `test -f hello.py; echo "...exit=$?"`、`cd <run-dir> && test -f hello.py`、脚本内 `python3 hello.py | grep -qx hello` 均 exit 0 但三门全判 missing，agent 烧 ~100 万 token 后向用户提问"门禁判定方式"。现按 `_shell_text_outside_quotes` 掩码定位、**原文**子句比对（`&&`/`||`/`;` 切分、空白归一、管道 `|` 留在子句内、引号内字面量仍区分——`test -f "a"` ≠ `test -f "b"`）：check 的全部子句 ⊆ 已执行命令的子句即记回执；命令内 `cd <dir>` 子句作为无显式 workdir 参数时的等效 cwd（仍走 `_shell_cwd_matches_check` 路径归一化比较，逃逸目录仍不收）。测试 `test_decorated_check_commands_still_record_receipts` 覆盖 echo 后缀 / cd 前缀匹配 / cd 错目录拒绝 / 单元面矩阵；`test_build_workflow.py` 46 条全绿无回归。
- **测试侧有界化**：E-3 批准 ≥2 次（审批+续接双次验证）后主动取消再等终态——confirm 档下啰嗦模型可把"批准→恢复→新审批"循环拖过 600s 死线，场景意图（审批卡出现+恢复可用+取消结案）不变；E-4 开头补 `ensure_idle`（E-3 残留停泊 run 占并发位导致 429）+ 审批上限 8 次后取消归 N/A。

### W10-D3/D4 生产部署实测（CentOS 7.6 VM，2026-10-21）

- **首个真实生产栈已上线**：VMware VM（CentOS 7.6 / kernel 3.10.0-957 / 4C8G）上 `rxyprod` 项目完整跑通——postgres/redis/minio/migrate(007 head)/api/worker/gateway 全 healthy，迁移先于 api/worker 完成（`service_completed_successfully`），网关仅绑 `127.0.0.1:8080`。
- **el7 内核兼容性修复（worker.Dockerfile 换基座）**：生产 worker 镜像基座从 `python:3.12-slim`（Debian 13/trixie, bwrap 0.12）改为 `python:3.12-slim-bookworm`（bwrap 0.8）。bwrap 0.10+ 的 bind 挂载走新 mount API（`open_tree`/`move_mount`，kernel ≥5.2 才有）——在 el7 上 `Can't open source /usr: Function not implemented`（ENOSYS），`userns_available()` 探测失败 → 每条 run 诚实拒绝 `_UnsupportedTarget: userns/bwrap isolation is unavailable`（fail-closed 设计正确触发，没有回落裸跑）。bwrap 0.8 的经典 `mount()` 路径在 3.10 + `seccomp=unconfined` + `user.max_user_namespaces>0` 下完整生产 argv 实测通过（含 `--unshare-net`/`--clearenv`/全 ro-bind 集）。代价：`--overlay`/`--overlay-src`（0.10+）不存在 → 任务私有 apt/pip 覆盖层探测诚实降级，路径保持只读，符合既有设计。
- **VM 基线配置**：`user.max_user_namespaces=15000`（CentOS 7 默认为 0，el7 userns 总开关）已写入 `/etc/sysctl.d/99-rxycode.conf` 持久化；dockerd 代理 drop-in `/etc/systemd/system/docker.service.d/proxy.conf` 指向 Windows 侧 FlClash `http://192.168.88.1:10808`（拉镜像走代理；容器内出站直连可用，`api.deepseek.com` 裸连 401 正常）。
- **API 冒烟实测**（容器内走 `http://gateway` 全 Caddy 链路）：注册 201 / `/me` 200 / 登录 200 / forgot 200 / `POST /api/v1/tasks` 202 → run `7347a13d…` 终态 **`succeeded`**（~160s，442 事件：32 次工具调用、4 轮 recovery、`hello.txt` 落沙箱工作区、门禁回执 `test -f hello.txt && [ "$(cat hello.txt)" = "hello-prod" ]` exit 0、67.3 万 token）。CSRF/Origin/secure-cookie 链工作正常（cloud 模式 secure cookie 要求 https——容器内 http 冒烟需手工携带 cookie，浏览器走 Funnel https 无此问题）。
- **Tailscale Funnel 待授权**：tailscaled 1.104.2 已装好，节点 `rxycode` 待运营者点开登录链接加入 tailnet 后 `tailscale funnel --bg --https=443 http://127.0.0.1:8080` 对外。
- **忘记密码投递缺口补齐——运营者日志投递**（`auth.py` + `main.py` + 前端）：cloud 模式此前无 SMTP 时重置链接被吞（token 签发但无通道送达）。新增 `RXYCODE_RESET_OPERATOR_LOG=1` 显式开关（自托管单管理员场景）：开启后 forgot 把链接 `log.warning` 进 api 日志（`docker logs … | grep "password reset"` 可取），响应体只回 `delivery:"operator-log"` 不带 URL——有日志权限即等于有 DB 权限，威胁模型等价。capabilities 新增 `reset_delivery: smtp|inline|operator-log|none` 字段，`password_reset` 改为四态判定；前端按 operator-log 显示"请联系管理员从服务器日志获取"文案。SMTP 配置路径不变优先。测试 `test_w9_a1_operator_log_delivery` 覆盖全链路（capabilities→forgot→日志取链→reset→登录）；`.env.prod.example`/compose.prod 传参已配。
- 部署目录 `/opt/rxycode/`：`compose.yaml + compose.prod.yaml + Caddyfile.prod + .env`（600，含生成的 pg/minio/web secret 与 deepseek key，`RXYCODE_IMAGE_TAG=3bdaa734`，`RXYCODE_WEB_REGISTRATION=open`）。
- **公网上线：Cloudflare Tunnel + rxycode.xyz**（2026-10-21）：`cloudflared` 装于 VM，隧道 `4e3b5220…` 指向 `http://127.0.0.1:8080`（gateway），`rxycode.xyz`/`www` CNAME 路由已建；systemd 托管 + `protocol: http2`。VM DNS 修复：`192.168.88.2`（VMware NAT DNS）间歇超时 → `nmcli` 换 `8.8.8.8`/`223.5.5.5`；DNS 偶发解析出 AAAA 而 VM 无 v6 → `/etc/gai.conf` 偏好 IPv4。公网冒烟实测：注册 201 / 登录 200 / forgot 200 / 任务提交 202 → run `succeeded`(~85s) / SSE 回放 419 行——**cloudflared 下 SSE 正常**（早前疑虑证伪）。Tailscale Funnel 方案随之废弃。
- **VM 本地加速器 mihomo**（`v1.19.32` compatible 构建）：`/etc/mihomo/config.yaml` mixed-port 7890 + external-controller 9090 + metacubexd 面板（`/etc/mihomo/ui`，受 SAFE_PATHS 限制只能放 workdir 下）；`apply-sub.sh` 一键接订阅（proxy-provider + PROXY/AUTO 组）；`geodata-mode: true` + 预置 `geoip.dat`/`geosite.dat`（MMDB 在线下载在无代理初启时卡死）。dockerd 代理已从 Windows FlClash 改指 VM 本机 `127.0.0.1:7890`——VM 不再依赖宿主机在线。
- **忘记密码改版：6 位验证码**（SMTP 部署时）：`forgot` 在 SMTP 通道下签发 `code:{user_id}:{code}` 的 HMAC 短码（15 分钟有效）进 `password_resets`（复用表，无迁移）；邮件正文只含验证码不含链接。`/auth/reset` 接受 `{email, code, password}`——每用户累计错 5 次焚毁未用码（进程内计数器，与限流器同一"每副本"语义）+ 复用 `auth_rate` 每分钟限流。SMTP 发送失败时降级 operator-log——焚掉已铸验证码、改铸 30 分钟**链接**进日志（operator-log UI 只有链接兑换入口，验证码/链接两种产物不混用）。operator-log/inline 通道仍是 30 分钟链接——管理侧无需变化。前端 `ForgotPasswordPage` 按 `delivery` 分流：`smtp` → 验证码+新密码两步表单；`resetPassword` SDK 签名改对象（`{token}` 或 `{email,code}`）。测试 +4：SMTP 码全流程、5 错焚毁、过期/形状校验、SMTP 失败降级日志。
- **SMTP 路径：中继容器 `smtp-relay`**（`alpine/socat`）：VM 直连出口对 465/587 全断；逐节点扫测发现订阅 56 节点中仅「香港高速02/03」放行 Gmail SMTP → mihomo 加 `MAIL` 组（filter 锁这两节点）+ `DOMAIN-SUFFIX,smtp.gmail.com,MAIL` 规则；relay 容器经 CONNECT `smtp.gmail.com:465` 过 `192.168.88.128:7890` 转发出网，`smtp.gmail.com` 网络别名指向 relay 使 api 容器内 TLS/SNI 不变。实测 `220 smtp.gmail.com ESMTP` 握手成功。全量扫测（运行时把 MAIL filter 展宽为 `.*` 逐节点切换 + CONNECT/TLS 探测，扫完还原配置）确认 56 节点中仅这两节点放行 Gmail SMTP；其间观测到 HK02 瞬时 SSLEOF 抖动 → `mailer.send_mail` 增加一次全新连接重试（`_ATTEMPTS=2`），仍 best-effort 不抛异常。

### W10-D5 验证码体系 + ALTCHA 人机校验（2026-10-22）

- **统一邮箱验证码设施**：`password_resets` 表泛化为三用途——`code:register:{email}` / `code:login:{user_id}` / `code:reset:{user_id}`（复位码绑定 user_id 防邮箱枚举后跨号兑换），均存 HMAC-SHA256 摘要、15 分钟有效、每用户累计错 5 次焚毁未用码、签发即焚旧码（仅最新一封有效）。新端点 `POST /auth/register/code`、`POST /auth/login/code`；`forgot` 复用同一设施（SMTP 下签发 `reset` 码）。投递分流不变：SMTP→邮件正文只含验证码；inline→响应体 `dev_code`；operator-log→链接进日志（复位码管理侧例外，保留链接产物，见上节）。`capabilities` 新增 `code_delivery`（smtp/inline/operator-log/none）与 `captcha:"altcha"`。
- **注册需邮箱验证码**（`code_delivery != "none"` 时）：`/auth/register` 校验 `email+code`（`CODE_REQUIRED`/`CODE_INVALID`/`CODE_EXPIRED` 错误族）；`none` 投递档不强制——无发信通道时不把注册关死。发送端点按邮箱限流 + 统一成功文案（防注册探测）。
- **登录双模式**：`/auth/login` 接受 `{email,password}` 或 `{email,code}`；验证码登录 = 已注册用户发码 → 验码签发同一 session cookie（复用密码登录的全部会话/CSRF 语义）；错误码计数与焚毁同复位码。
- **ALTCHA 人机校验**（开源 PoW，自研实现 wire format，无第三方依赖）：`GET /auth/altcha` 签发 HMAC 签名挑战（salt 带 `expires`，20 分钟、10 万难度）；服务端 `altcha.py::verify_payload` 纯密码学校验（签名→哈希→过期→一次性焚毁，`_ReplayRegistry` 每副本防重放）。`/auth/register`、`/auth/login`、`/auth/forgot`、`/auth/register/code`、`/auth/login/code` 五端点强制 `captcha` 字段，缺失/伪造/重放一律 `CAPTCHA_REQUIRED`/`CAPTCHA_INVALID`。配合既有 `auth_rate` 限流构成注册/登录双闸门。
- **前端**：新增 `AltchaWidget`（`altcha` npm 包 web component，`challengeurl=/api/v1/auth/altcha` + `auto=onload` 静默解题，`statechange→verified` 回调交付 payload；每次提交后 remount 取新挑战——挑战一次性，发码与最终提交各自消耗一枚）。`RegisterPage`：邮箱+「发送验证码」按钮（60s 冷却）+ 6 位码输入 + ALTCHA；`LoginPage`：「密码登录/验证码登录」分段切换（`code_delivery` 开时才显示码页签），码模式内嵌发送按钮 + ALTCHA；`ForgotPasswordPage` 首个表单加 ALTCHA。SDK：`Capabilities.code_delivery`/`captcha`、`register`/`login`/`forgotPassword` 扩展字段、`requestRegisterCode`/`requestLoginCode` 新方法。手机版：验证码行 `min-w-0` 防溢出、认证卡片 `p-6 sm:p-8`。
- **测试**：w9 helper 全部接入真实 PoW 求解（`_solve_captcha` 暴力试 number 直到 SHA-256 命中）；新增 `tests/web/w9/test_email_codes.py`（4 条：注册码签发/校验、登录码全流程、过期/非法、5 错焚毁——焚毁用例单独关该路由限流器隔离计数器）；`test_password_reset.py`/`test_auth.py`/`test_runs_api.py` 既有用例改为带真 captcha 求解。w9 全量 **69 passed**。

### W10 BYOK 后端：用户自带模型密钥与按 run 模型快照（PRD 后端部分，2026-10-22）

- **目标**：普通 Web 用户必须自带模型 API key（BYOK），部署方的共享平台 key 只服务显式白名单用户。本节仅为后端（迁移/API/worker/部署面）；前端设置页后续落地。
- **迁移 `009_byok`**：新表 `model_connections`（AES-256-GCM 密封的凭据持有行：ciphertext/nonce/key_id/credential_version/state/test_status/test_error/tested_at + provider/base_url/transport，索引 (tenant_id, owner_user_id)）与 `user_models`（用户模型目录，id 即 `model_ref`，(connection_id, model_id) 唯一，connection 删除级联）；`users.default_model_ref`；`runs` 增加不可变提交时快照列 `model_ref/model_id/provider_id/provider_name/credential_source/connection_id/credential_version`（无外键——连接删除后历史仍在）。`WEB_TABLES` 补齐两张新表与此前遗漏的 `email_codes`。
- **加密与 keyring**（`rxycode_server.byok`）：AES-256-GCM，每次加密取 96-bit 随机 nonce；AAD 绑定 `rxycode-byok:v1:{tenant}:{owner}:{connection}:{credential_version}`——改任何一段都解不开，杜绝跨用户/跨连接/跨版本重放。keyring 文件经 `RXYCODE_BYOK_KEYRING_FILE` 指定，JSON `{"active","keys"}`，按 (path, mtime) 惰性加载缓存；旧 key_id 在轮换后继续可解。`python -m rxycode_server.byok.keyring generate <path>` 生成 0600 keyring 且拒绝覆盖。缺/坏 keyring → `BYOKUnavailable`（503 `BYOK_UNAVAILABLE`），未知 key_id/篡改/错误 AAD → `BYOKDecryptError`，**无任何明文/base64/临时 key 回落**。
- **API**（`api/models.py`，全部 `current_record` + 写操作 `require_write`；每条查询同时过滤 tenant_id 与 owner_user_id，他人资源一律 404）：`GET /models/providers`（复用 `config/model_manager` preset 表）、`GET /models/access`、`POST/GET/PATCH/DELETE /model-connections`、`POST …/clear-key`、`POST …/discover`（解密 key 调 `discover_provider_models`，返回 `added` 标记）、`POST …/models`（added/exists/invalid 分类）、`POST …/test`（无 model_id 走免费 `/models` 探测；有 model_id 必须 `allow_billable:true` 否则 400 `BILLABLE_TEST_NOT_CONFIRMED`）、`GET /models` + `POST /models/default` + `DELETE /models/{ref}`（删模型/连接清默认）。任何响应都不含 key——包括掩码；错误文本经 `_redact` 剥 key。自定义 base_url 经 `byok.netguard.vet_base_url`：仅 https、无 userinfo、DNS 必须全解析到公网地址（同 worker egress `_ip_blocked` 规则）→ 否则 400 `INVALID_BASE_URL`；`RXYCODE_BYOK_ALLOW_PRIVATE=1` 为仅测试/开发逃生门。
- **提交绑定**（`api/runs.py` + `runs/service.py`）：`_TaskIn`/`_RunIn` 增加 `model_ref`；`byok.resolver.resolve_run_model` 在**建任何行之前**解析——显式 ref → 自己的 user_model（否则 404 `MODEL_NOT_FOUND`），`"platform"` → 仅 `RXYCODE_PLATFORM_MODEL_USERS` 白名单（否则 404），缺省 → 用户默认 → 白名单平台兜底 → 强制开启时 403 `BYOK_REQUIRED`（拒绝即零 run 零孤儿 session）；连接 revoked/无 key → 409 `MODEL_UNAVAILABLE`；keyring 缺失 → 503。快照写入 runs 列 + `run.created` payload 的 `model` 块（永不含 key）；`request_model_ref` 参与幂等 digest——同 request_id 换模型 = 409 `REQUEST_CONFLICT`；run detail/列表 DTO 增加 `model` 块（旧行 `null`）。`RXYCODE_BYOK_ENFORCE` 缺省时 cloud 开、local 关。
- **worker 按 run 网关**（`drain.py` + `egress.py`）：`_resolve_run_gateway` 在执行时按快照列解析——`byok` 源在父进程读连接行、核 `credential_version`（不符 → `CREDENTIAL_CHANGED`；清除/吊销/已删 → `MODEL_UNAVAILABLE`）、解密（keyring 缺 → `BYOK_UNAVAILABLE`）并构造 `ModelGateway(vet=True)`；`platform` 源在**执行时**重查白名单（不符 → `PLATFORM_NOT_ALLOWED`）；无快照且强制开 → `BYOK_REQUIRED`，强制关 → 旧 env 网关（保 W7/W8 行为）。拒绝走共享 finalizer：`run.error` payload 带稳定 `code`，不重试、不回落平台 key。`ModelGateway` 新增 `vet`：gateway hop 前跑 `evaluate`，私有解析一律 403（`ALLOW_PRIVATE` 才放行），连接用已审查地址且 TLS `server_hostname` 用域名——检查与连接之间不重解析。`_build_child_config`/`_prepare_child_data_dir` 新增 `model_override`：子进程只看到快照 model_id + `api_key:"confined"` + loopback base_url，BYOK run 即使宿主机没有 config.yaml 也会落子配置；usage ledger `model_id` 用快照而非 env。
- **部署面**：`compose.prod.yaml` api/worker 注入 `RXYCODE_BYOK_ENFORCE=1`、`RXYCODE_BYOK_KEYRING_FILE=/run/secrets/byok-keyring.json`（宿主机文件只读挂载，默认 `/opt/rxycode/secrets/byok-keyring.json`）、`RXYCODE_PLATFORM_MODEL_USERS`；worker 的 `RXYCODE_LLM_BASE_URL`/`RXYCODE_API_KEY` 由必填改可选（BYOK run 不需要平台 key）；api 注入 `RXYCODE_LLM_MODEL`（仅显示）。`.env.prod.example` 同步新变量（全占位符）。两容器均以 uid 0 运行，宿主机 keyring 建议 `root:root 0600`。
- **测试**：`tests/web/w9/test_byok_crypto.py`（9 条：roundtrip/nonce 唯一/篡改/跨 AAD/缺 keyring/未知 key_id/轮换可解/CLI 拒覆盖）、`test_byok_api.py`（11 条：建连/金丝雀不出现在响应与 DB 密文/PATCH 版本语义/跨用户全动词 404/发现与加入分类/默认设置清除/私网 URL 拒绝与放行/缺 keyring 503 无行/付费测试门槛/access 形状）、`test_byok_runs.py`（8 条：强制拦截零孤儿、快照列+事件 echo、外ref 404、清 key 409、平台白名单、续跑拦截、request_id+model 冲突、DTO 与旧行 null）、`test_byok_worker.py`（纯 python+pg：gateway 解析全错误码、子进程配置无密钥、vet 私网拒绝/放行回环上游注入真 Bearer）。**VM 真 Postgres 上 w9 全套 105 passed**（`9167ada`，CentOS 7.6 + docker pg 16）。
- **修复**：dev `infra/compose/compose.yaml` 补 `RXYCODE_BYOK_ENFORCE`——worker `_byok_enforced()` 在变量缺省时按 cloud 语义默认强制，dev 栈不配会导致 api 放行而 worker 全拒 `BYOK_REQUIRED`。

### W10 前端：访客入口 + BYOK 设置 + Composer 模型选择（PRD 前端部分，2026-10-22）

- **访客 `/app` 壳**（PRD §3.2/E2E-01）：`/app` 路由摘掉整页 AuthGate——访客即刻看到侧栏/顶栏/输入框；`/` 无条件跳 `/app`，不再有"确认登录中"等待屏。`s/:sessionId` 与 `settings` 仍是私有子路由（AuthGate 就地拦截 → SPA 跳 `/login?next=…`）。`useAuth`（`features/auth/useAuth.ts`）统一三态：pending/authed/guest，`/me` 的 401=访客语义、5xx/断网=unavailable（显示"无法连接服务器"可重试，不冒充登出）。全局 401 处理细化：`["me"]` 探测永不重定向；`/app` 内 **mutation** 的 401 交给发起处弹就地登录层（保草稿），后台 query 的 401 才 SPA 跳登录；`/forgot`/`/reset` 加入 PUBLIC_PATHS（此前会自跳循环）。新增 `app/nav.ts` `appNavigate`——query cache/EventSource 等 React 树外回调也走 `router.navigate`（SPA），整页 `location.assign` 会丢内存 Zustand 草稿，全仓仅剩 OAuth 外链与兜底用硬跳。
- **动作级登录**：`LoginPrompt` 模态层（原生 `<dialog>`）——访客点发送/模型按钮时弹出，"去登录"置 `ui.pendingIntent` 后 SPA 跳 `/login?next=<当前页>`；登录返回后 Composer 显示"草稿已保留，确认后发送"横幅（**绝不自动重发**，PRD §3.3）；登录中止自动清标记。发送途中会话失效（mutation 401）同路径就地弹层。
- **Composer**（`Composer.tsx`）：提交体新增 `model_ref`；`undefined`=跟随服务端 `default_model_ref`。`modelRef` 存入 `ComposerDraft`（`patchDraft` 局部更新），**模型/权限/文本都属幂等范围**——任何一项变更即重置 `requestId`。`BYOK_REQUIRED` 错误附"去添加 API Key"链接直达 `/app/settings?section=models`；Enter 发送在 `<dialog>[open]` 时让位（输入法 isComposing 判定保留）。
- **ModelPicker**（`features/console/ModelPicker.tsx`）：发送键左侧的模型选择弹层——按 provider 分组、搜索过滤、键盘上下+Enter 选中、不可用项灰显附原因（revoked/no_key）、平台/个人徽标、"默认"标记、空目录/加载失败各带"模型设置"入口；运行中禁用（title 说明）；访客点击 → 登录提示层；选中写 `draft.modelRef` 并重置 requestId。
- **设置页 BYOK 分区**（`SettingsPage.tsx` + `settings/`）：外观 / 模型与BYOK / 账号 三个分区，`?section=models` 可深链。`ModelsSection`：连接卡片（<640px）/表格（≥640px）双布局，骨架/错误+重试/内容三态；新建/编辑连接（`ConnectionFormDialog`：provider 预设下拉+自定义、`type=password` 密钥框+显隐、字段级错误、编辑仅提交变更字段）；`DiscoverPanel`（发现模型：搜索、勾选、全选、批量加入、手动 ID，已加入项 checked+disabled "已添加"、已存在/无效分色 chip、失败不清空已选）；连接操作（测试 [计费确认]、清 key、删除）全部走 `ConfirmDialog`；默认模型单选 + access 横幅（require_byok/平台授权/密钥环状态）。
- **会话页模型回显**（`SessionPage.tsx`/`ConsolePanel.tsx`）：每条 run 顶部展示提交时解析的模型快照（显示名 · provider · 平台/个人徽标），历史 run 如实标"未记录（历史任务）"——不用当前选择补写过去（FR-17/CON-02）。
- **Esc 分层**：`ConsolePanel` 与 `usePopover` 在有 `dialog[open]` 时不响应 Esc——一次按键只关最上层。
- **草稿身份隔离**：`useLogout` 统一登出路径——成功/会话已失效（401）都先 SPA 回 `/app` 再 `queryClient.clear()+resetDrafts()`（先导航后清缓存，避免 AuthGate 竞态把用户送去 /login）；失败留在原地内联报错。`useRunEvents` SSE 401 恢复改 `appNavigate`。
- **SDK**：`client.ts` 增加 BYOK 全套类型（`ModelConnection`/`ModelItem`/`ModelsAccess`/`ProviderPreset`/`DiscoverResult`/`ConnectionTestResult`/`RunModel`）与 12 个模型端点方法；`RunSummary`/`RunDetail` 增 `model` 块；`createTask`/`createRun` 接受 `model_ref`。`errors.ts` 补 7 个 BYOK/模型错误码文案 + `errorWithCode`（"文案（CODE）"便于对账）。
- **验证**：`tsc --noEmit` 0 错；`vite build` 通过（413 模块）。浏览器端到端归 E2E-01..06 验收。

### W10 延迟测量与启动优化（PRD §9，2026-10-22）

- **分段计时**（`drain.py`）：每条 run 落一组耐久 `run.phase` 事件（与 `run.created` 同一事件日志，含 `elapsed_ms` 相对基准）——`child_started`/`imports_ready`/`agent_assembled`/`prompt_dispatched`/`first_event`/`terminal`。子进程侧的边界（imports_ready、agent_assembled）经 ctl 通道白名单 `phase` op 上报，父进程盖章入库——拆分 `worker.lease → agent_started` 的 13s 黑盒为 import/sandbox/assemble/dispatch 实测段，不再靠猜。`tests/web/w9/test_phase_timing.py`（215 行）覆盖事件序列与 elapsed 语义。
- **启动优化**：worker 镜像层 `compileall` 预编译字节码（子进程不再现编译 .pyc）；`userns.py` 探测负缓存加 TTL（此前一次失败后每次 run 重探测）；bwrap/overlay 探测结果进程内缓存。

### W10 生产部署与端到端验收（2026-10-21，镜像 `e0124b8`）

- **部署**：VM `/opt/rxycode/src` git checkout → `68023e9`，迁移 `009_byok` 应用（`model_connections`/`user_models`/runs 快照列落库），keyring `/opt/rxycode/secrets/byok-keyring.json`（root:root 0600、只读挂入 api/worker），`RXYCODE_BYOK_ENFORCE=1`、`RXYCODE_PLATFORM_MODEL_USERS` 白名单生效。
- **关键修复**（`e0124b8`）：`config/model_endpoint.py` 的 `require_https` 校验补 loopback 豁免（`_is_loopback_host`：localhost/127.x/::1）——此前该豁免只存在于本地未提交的工作区，VM 部署后子进程模型 `http://127.0.0.1:18881`（egress 回环）+ 占位凭据被误拒，首个 run 在 AgentV2 构造处 `ValueError`。教训：BYOK 依赖散落在未提交工作区的改动必须随迁移一起提交，已修复并同步。
- **基础设施事故**：VM `net.ipv4.ip_forward` 被重置为 0 → 容器外网全断（netguard 如实拒 `base_url host does not resolve`）。已 `sysctl -w` 恢复并落 `/etc/sysctl.d/99-docker-forward.conf` 持久化；dockerd 代理改指 VM 本地 mihomo（127.0.0.1:7890→构建期用 LAN IP 192.168.88.128:7890 作 build-arg）。
- **实测分段**（warm，worker 进程已暖）：claimed 69ms → gateway_resolved 222ms → env_ready 255ms → sandbox_probed 289ms（TTL 缓存命中，冷启动为 9.7s）→ child_spawned 325ms → child_started 1155ms → imports_ready 2386ms → agent_assembled 4080ms → prompt_dispatched 4342ms → final 6449ms。**lease→agent 组装 ≈4.0s**（基线 13.068s，×3.2）；距离 ≤3s 目标差约 1s，残余在子进程 spawn+import+assemble，需 warm 池才能再压，记为后续项。"你好"→final ≈6.4s（≤8s 达标）；SSE 增量实时推送可见。
- **E2E 证据**（生产 `https://rxycode.xyz`，浏览器实测）：访客 `/app` 壳可见（侧栏"登录后查看历史会话"+输入框+模型选择器）；发送→"发送任务需要登录"模态→"去登录"SPA 跳 `/login?next=/app`；登录态模型弹层显示平台模型+搜索+管理入口；设置 `?section=models` 深链到 BYOK 分区；连接创建/拉取模型/测试连接/清除/删除全链路（假 key 下发现失败显示 `认证失败（auth）`、目录保留）；run 卡片回显模型快照（deepseek-flash · 平台额度 · 平台）；运行中模型选择器禁用；停止按钮"取消中…"→DB `cancelled`；`tool_begin→tool.completed→final_answer→succeeded` 全事件链。

### W11 安全加固：验证码发送限流 / 注册防批量 / 单设备登录锁 / 单副本数据库备份（2026-10-23）

- **验证码发送频率上限**：`_Window` 增加 `window_seconds` 参数（原 60s 语义不变），`AuthRateLimit` 新增 `check_code(route, ip, email)`——每邮箱 5 次 / 5 分钟 + 每 IP 15 次 / 5 分钟两个固定窗口桶，超限一律 429 `RATE_LIMITED`。`/auth/register/code`、`/auth/login/code`、`/auth/forgot` 三条发码路径在既有按分钟限流与 ALTCHA 之外全部接入。
- **注册防批量（每 IP 每小时）**：`AuthRateLimit` 再增 `register_hour` 桶——同一 IP 每小时最多 5 次**成功**注册；`check_register_hour` 在建用户/扣邀请码之前拒（429 `RATE_LIMITED`），`record_register` 只在用户行 flush 成功后计数，失败尝试不占额度。
- **真实客户端 IP**（`api/client_ip.py`）：部署链路 uvicorn `proxy_headers` 已把网关注入的 XFF 写回 `scope["client"]`；新 helper 在直接对等方仍为私网/回环地址（compose 网关、TestClient/unix 传输）时才采信 `CF-Connecting-IP`（CF 覆写不可伪造前缀）与 `X-Forwarded-For`（从右往左跳过可信私网跳），公网直连一律退回对等 IP。全部限流键（auth 各端点 + `RateLimitMiddleware`）统一改用它。同时把 compose.yaml 与 `infra/docker/serve_web.py` 的 `forwarded_allow_ips` 由 `"*"` 收紧为私网网段——uvicorn 改取 XFF 中首个非可信跳，杜绝客户端伪造 XFF 前缀刷限流桶。
- **单设备登录锁**：迁移 `010_device_locks` 建表（`user_id` PK → `users.id`、`token_hash`、`created_at`、`last_seen_at`）；同一账号数据面只服务一个会话。`_issue` 在登录/注册/OAuth/local 发会话时同事务认领锁；`current_record` 统一加 `_device_gate`——非持锁会话打数据面一律 409 `{"code":"DEVICE_IN_USE"}`（会话本身不吊销，另一台设备的自动登录不受影响），持锁请求顺带刷新 `last_seen_at` 作 keepalive；持锁方闲置 >10 分钟锁即过期，非持锁方请求自动接管（死设备困不死账号）。`/api/v1/auth/*` 与 `/api/v1/me` 豁免——被顶掉的设备仍能看状态与夺回。新增 `GET /api/v1/auth/device`（`{"status":"active"|"held_elsewhere"|"none"}`）与 `POST /api/v1/auth/device/claim`（require_write，`{"claimed":true}`，无条件接管）。
- **每日数据库备份**：`infra/scripts/backup_pg.sh`——对 `rxyprod` 项目的 `postgres` 服务 `pg_dump -Fc` 落 `/opt/rxycode/backups/rxycode-<日期>.dump` 并删除其余 `rxycode-*.dump`（单副本轮转）；runbook 补 crontab 行（每日 03:10）与 `pg_restore --clean --if-exists` 恢复步骤。
- **测试**：新增 `tests/web/w9/test_rate_and_device.py`——同邮箱 5 分钟窗第 6 次发码 429、5 分钟窗独立生效（预填桶隔离 60s 桶）、每 IP 15 次/5 分钟、每 IP 每小时 5 次成功注册（第 6 次 429、失败不计数）、设备锁全链路（登录夺锁 → 被顶会话 `held_elsewhere` + 数据面 409、`/auth/*`/`/me` 豁免可达、claim 无条件接管、last_seen 超龄自动释放并被下个请求接管）。

### W11 前端：Markdown 时间线 / 工具卡 / 思考链 / 单设备模态 / 取消直通 / 关于对话框（2026-10-23）

- **Markdown 渲染**：`components/Markdown.tsx`——`react-markdown` + `remark-gfm`，不渲染裸 HTML，链接限 http(s)/mailto 且 `target=_blank rel=noopener`；assistant 文本块与时间线接入。
- **工具调用卡**：`ToolRow.tsx` 展示工具名、参数、结果、状态、exit code、耗时，可折叠；`eventReducer.ts` 将 tool journal 通知与投影 tool 事件按 `call_id` 合并。
- **思考链**：中间 `assistant.delta` 聚合为 ThinkingBlock——流式 shimmer、完成后自动折叠、`▸` 展开。
- **模型切换提示**：Composer 切换模型即显 "已切换模型为 {名称}，下次任务生效"（4s），运行中锁定不可切。
- **单设备 UI**：`DeviceConflictModal`——任一 query/mutation 在 `queryClient.onError` 命中 409 `DEVICE_IN_USE` 即弹层，"在此设备继续使用" 走 claim 后全量失效查询；设置页新增"安全"行（当前设备状态 + 切换按钮）。
- **取消直通**：pending/未租用 run 的取消不再等 worker 认领——API 直接把 `cancel_requested` 落成终态 `cancelled`（含自愈：`cancel_requested` 且无 lease_owner 的历史卡死一并终态），修掉了"取消要点好几次"；活跃 run 仍由 worker supervisor 走 cancel_requested → confirm_cancel → cancelled/recovery_required。
- **输入净化**：task/run 消息在 pydantic 边界剥离 C0 控制字符——粘贴含 NUL 的日志行曾让 `session_texts` 插入炸 `UntranslatableCharacter`（500）。
- **关于对话框**：设置页"关于"按钮 → Modal 展示产品名与后端构建戳（`GET /api/v1/version`，commit + built_at）。
- **生产验收证据**（镜像 `49ca62dc`，2026-10-23）：发码 1–5 = 200、第 6 发 = 429 `RATE_LIMITED`；双会话设备锁全链路（顶掉 → 数据面 409、`/me` 200、claim 夺回）；真实 BYOK run 用 `deepseek-flash` 完成并渲染 markdown 加粗 + 两条思考链 + bash 工具卡；设备冲突模态与抢占按钮实测通过；移动视口 390px 布局正常（chat-only）。实测并发模型：每用户在途 = 1（第 2 单 429 `QUOTA_EXCEEDED`），队列深 10，worker 串行——高并发上限即 worker 数。
- **测试**：`test_pending_cancel_direct`（pending 取消直通终态 + 二次取消 409）。

### W12 会话工作区文件 API + 多用户并发扩容（2026-10-23，镜像 `3a8526c8`/`aa5581a6`）

- **会话工作区文件面**：`GET /api/v1/sessions/{id}/files` 列出 agent 写入会话工作区（`{tenant}/{session}` 目录，在共享 `worker-data` 卷上）的非隐藏文件；`GET /api/v1/sessions/{id}/files/download?path=` 流式下载——路径穿越/绝对路径/符号链接一律 403/404，下载上限 32MiB，dotfile（`.turn-result.json` 等内部文件）永不可见。api 容器以只读方式挂 `worker-data:/workspaces-ro`（prod overlay 的 api `volumes: !reset` 会把 base 挂载清掉，故在 prod overlay 显式补回）。前端会话页新增「工作区文件」折叠面板（运行中 10s 轮询，文件名+大小+下载链接）——这就是 Notion/ChatGPT 式"agent 产出的文件用户可见"的服务端工作区模式。
- **多用户并发实测**：`--scale worker=4` 起 4 个 drain，4 个不同用户 0.7s 内提交 4 个任务全部 202，4s 内被 4 个不同 `lease_owner`（`drain-{hostname}-1`）并行认领并同时保持执行 77s+。**并行度 = worker 副本数**，PG `FOR UPDATE` 认领保证同一 run 不被两个 worker 拿走，按 `--scale worker=N` 线性扩。当前生产保留 4 个 worker（VM 7.8G 内存，worker mem_limit 2g 为上限非预留）。Redis 的角色只是 SSE 事件扇出，不参与排队——并发瓶颈在 worker 数而非 Redis。
- **测试**：`tests/web/w9/test_session_files.py` 3 条全绿（pg 实测）——列表/下载/穿越 403/dotfile 404/跨租户 404/未配置 root 404。
- **事故**：部署时发现 api 容器只剩 keyring 挂载——prod overlay api `volumes:` 无 !reset 的对齐缺口导致 base 卷被清，补回 `worker-data:/workspaces-ro:ro` 修复。

### 已知限制（明示，非遗漏）

- **终局应答证据门误报**（本轮实测发现）：`final_answer` 工具把"仅 pwd 只读调用"的应答判为"声称副作用无 WRITE/DANGER 证据"，最终文本被替换成 `[evidence failed: ...]`——Harness 条款校验器的误报（run 仍 succeeded、工具确实执行）。与 BYOK 无关，归 agent-runtime 后续修。
- **warm lease→agent_assembled ≈4.0s** vs PRD ≤3s 目标：残余瓶颈为子进程 fork/入口（~0.8s）+ Python import（~1.2s，compileall 后）+ AgentV2 组装（~1.7s），需子进程 warm 池继续压缩；分段计时已就位可复核。
- 本地 Docker Desktop 引擎仍不稳定（此前 E: 盘满导致），pg 依赖测试均在 VM 执行。

- **Provider 错误被记为 `succeeded`**（W9 验收发现，未修）：模型上游 402/5xx 时 agent 把 `to_user_facing_error` 的错误文案当正常 final answer 走完回合，run 终态 `succeeded`——E-2/E-3 在欠费期间的表现（零工具行、零审批、"succeeded"）。正确语义应为 `failed`（可重试）或至少带错误标记，涉及 Harness 终态映射，留待额度恢复后一并处理。
- **`/repo` Harness 源码在沙箱内可读**（W9 验收发现）：被拦的 agent 会 grep `/repo` 找绕过（`direct_python_c_argv`、sys.path 注入 import core）。bwrap 仍强制写边界所以只是"难看"不是逃逸，但建议后续把 Harness 源码移出 agent 可见挂载。
- 每个挂起调用仅支持一个持久化提问。
- 无 `call_id` 的外部工具结果仍走文本前缀回退。
- `tests/web/w2`–`w6` 全量失败此前定性为本机环境/HEAD 既有问题，未逐条复验。
- 产品版本仍为 1.4.3，JSON-RPC 未改，未自动 commit 或 push。

### 后续规划（W9–W11，2026-10-20）

- 重写 W8 之后的施工文档 `docs/plans/opus5-plan/rxycode -web/phases/PHASE-W9-PRODUCT-CLOSURE-AND-DEPLOYMENT.md`（`docs/plans/` 被 gitignore，仅本地；GPT 草稿归档为 `research/W9-gpt-draft-2026-10-20-superseded.md`）。
- 文档中登记的已核实缺口——其中以下已被上述 W9 后端批次修复：`run.status` 事件缺失、notify.* repr 审计行、流式 token 逐条写（已合并）、`tool_begin` 未投影、`_JOURNAL_CAP` 误丢 tool/approval 行、队列随机序、准入无默认、无注册/无持久会话/无建 Run 路由。尚未修复：run 时间线的完整投影渲染与审批/提问操作（F4/F5）、终态后停止 follow 的产品化收尾、浏览器端到端九场景验收（Q1）。`stale` 误判导致的 token 浪费已由 W9-H1 修复（见上节），输入框已随 W9 前端落地。
- 已定：邮箱 + 密码 + 邀请码注册（GitHub 可选）、控制台面板、首台服务器选境外区域、镜像预构建、W9/W10/W11 分期与日期。
