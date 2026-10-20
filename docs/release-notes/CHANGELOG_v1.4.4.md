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

### 已知限制（明示，非遗漏）

- 每个挂起调用仅支持一个持久化提问。
- 无 `call_id` 的外部工具结果仍走文本前缀回退。
- `tests/web/w2`–`w6` 全量失败此前定性为本机环境/HEAD 既有问题，未逐条复验。
- 产品版本仍为 1.4.3，JSON-RPC 未改，未自动 commit 或 push。

### 后续规划（W9–W11，2026-10-20）

- 重写 W8 之后的施工文档 `docs/plans/opus5-plan/rxycode -web/phases/PHASE-W9-PRODUCT-CLOSURE-AND-DEPLOYMENT.md`（`docs/plans/` 被 gitignore，仅本地；GPT 草稿归档为 `research/W9-gpt-draft-2026-10-20-superseded.md`）。
- 文档中登记的已核实缺口——其中以下已被上述 W9 后端批次修复：`run.status` 事件缺失、notify.* repr 审计行、流式 token 逐条写（已合并）、`tool_begin` 未投影、`_JOURNAL_CAP` 误丢 tool/approval 行、队列随机序、准入无默认、无注册/无持久会话/无建 Run 路由。尚未修复：run 时间线的完整投影渲染与审批/提问操作（F4/F5）、终态后停止 follow 的产品化收尾、浏览器端到端九场景验收（Q1）。`stale` 误判导致的 token 浪费已由 W9-H1 修复（见上节），输入框已随 W9 前端落地。
- 已定：邮箱 + 密码 + 邀请码注册（GitHub 可选）、控制台面板、首台服务器选境外区域、镜像预构建、W9/W10/W11 分期与日期。
