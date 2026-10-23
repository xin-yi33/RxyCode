# Phase W9–W11 · Web 产品闭环、上服务器、邀请内测

> 日期：2026-10-20（Asia/Shanghai）。状态：**PLANNED**。本文是 W8 之后唯一的施工入口。
> 仓库：`D:\agent-demo\RxyCode\RxyCode1_1_0`，分支 `feat/rxycode-web`，核对锚点 `d5698c67`。
> 本文替代 GPT 草稿（已归档到 `research/W9-gpt-draft-2026-10-20-superseded.md`，**不作为依据**）。
> 本文所有“现状”结论都已经对照源码或运行中的 `rxydemo` 栈核实过，每条都附有文件和行号或查询结果。

---

## §0 给施工 Agent 的规则（先读完这一节）

1. **一次只领一张卡**（§6）。先读卡片 → 再读卡片列出的文件 → 写失败测试 → 实现 → 跑卡片列出的测试 → 更新 changelog → 交接。
2. **技术栈不变**：前端 React 19 + Vite 7 + TS + Tailwind 4 + React Router 7 + TanStack Query + Zustand；后端 FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL；传输 HTTP + SSE。不引入 Next.js、Redux、WebSocket 聊天流、Celery、K8s。
3. **不碰共享 Harness**（`core/agent_v2.py`、`core/session.py`、`execution/tool_orchestrator.py`），除非卡片明确写了（只有 H1 卡）。Web 不另写 agent loop、超时器或任务完成判断。
4. 后端改接口时，前端 SDK 类型（`apps/web/src/sdk/client.ts`）**在同一张卡里同步改**。
5. 每张卡完成后，在当前版本 changelog（`docs/release-notes/CHANGELOG_v1.4.4.md`，若 1.4.4 已发布则写 `CHANGELOG_v1.4.5.md`）的“新增 RxyCode Web”节下追加条目（见 `AGENTS.md` 第 7 条）。
6. 测试只能用独立的库、端口和 compose project 名。**禁止**连用户的 `rxydemo` 栈去跑会 DROP schema 的夹具。
7. 卡片里写“决策”的地方已经定了，不要重新讨论；写“待验证”的地方，先验证，再按验证结果执行。
8. 不 push，不部署，除非用户明确要求。

---

## §1 现状：哪些能用，哪些不能用

### §1.1 已经可靠的部分（W0–W8 成果，不要重做）

| 能力 | 证据 |
|---|---|
| 持久化 Run 队列 + fenced lease + worker 崩溃恢复 | `rxycode_worker/supervisor.py::claim/renew_lease/commit_terminal`；W7 部署测试 PASSED |
| 每个 run 独立 bwrap 沙箱，平台凭据留在父进程 | `drain.py::run_sandboxed_turn`；W8 套件 168 passed |
| 审批/提问挂起 → 续接原 Harness 循环到 Final | 演示 run `20d4b363…` 实测：question → 3 次 approval → `succeeded` |
| 租户隔离（所有查询都带 `tenant_id`） | `api/projects.py`、`api/runs.py` 每个查询 |
| CSRF + Origin 校验、HttpOnly 会话 cookie | `api/auth.py:60-67, 97-106` |
| 部署栈（Caddy + api + worker + PG + Redis + MinIO） | `infra/compose/compose.yaml`；`rxydemo` 栈 6 个容器 healthy |

### §1.2 阻断上线的问题（按严重程度排序）

| # | 问题 | 证据 | 影响 | 由哪张卡修复 |
|---|---|---|---|---|
| P1 | **网页发不了任务**：没有创建 Run 的 HTTP 路由；前端没有输入框 | `api/runs.py` 只有 GET/cancel/steer；`runs/service.py:147 create_run` 无人调用；`ChatPage.tsx` 没有 Composer | 产品主路径不存在（演示 run 是直接写库建的） | B2、F3 |
| P2 | **前端不知道 run 何时结束**：worker 从不往事件日志写 run 状态变化 | `supervisor.py:145 claim`、`:229 commit_terminal` 只改 `runs.status`；演示 run 的 1746 个事件里**没有一个** `run.status`/`run.completed` | 页面一直显示初始状态；SSE 服务端在终态后关闭流，`useRunEvents.ts:126-155` 的 error 分支会**无限重连** | B3、F4 |
| P3 | **登录状态存在进程内存里** | `main.py:106-107` `app.state.sessions = {}`、`oauth_states = {}`；`auth.py:75` 用 `time.monotonic()` | API 重启后所有人掉线；不能多进程 | B1 |
| P4 | **没有注册**：只有本机口令（cloud 模式禁用）和 GitHub OAuth（需要运营者先建 OAuth App，国内网络也不稳定） | `auth.py:187-264` | 公网用户无法进入 | B1、F2 |
| P5 | **单次任务成本异常**：写一个文件的任务用了 773,379 token / $1.55 | 演示 run `usage.updated`；`question.requested` 显示完成门禁连续 6 轮把 `file_content_exact_line` 判为 stale，检查命令实际退出码为 0 | 上线后成本无法控制 | H1 |
| P6 | **审计事件存的是 Python repr 字符串**，每个流式 token 写两行库 | `drain.py:1062-1065` `{"text": str(notification)[:1500]}`；演示 run：`assistant.delta` 778 行 + `notify.event/message_delta` 638 行 | 前端无法解析；数据库写入量翻倍，在 2G 机器上是瓶颈 | B3 |
| P7 | **工具执行中看不到**：`tool_begin` 只记了名字，没有投影 | `drain.py:904-907` | 长命令执行时界面是空白 | B3、F4 |
| P8 | `_JOURNAL_CAP=500` 对**所有**投影行生效，只有 `assistant.final` 豁免 | `drain.py:78-82, 1038-1040` | 长任务超过 500 行后，tool/approval/question 行都会**丢失** | B3 |
| P9 | `event/agent_needs_input` 同时投影成 question 和 approval，且两者用同一个 id | `drain.py:922-939` | 界面同时出现审批卡和问题卡 | B3（先验证此路径在 W8 之后是否仍会触发） |
| P10 | 队列不是先进先出：`ORDER BY id`，而 id 是随机 uuid hex；`runs` 表没有 `created_at` | `drain.py:189-215`；`models.py:104-145` | 先提交的人可能一直排在后面 | B2 |
| P11 | 准入默认值等于没有限制：并发 10000、任务 100000、token 1000 万 | `quotas/service.py:22-25` | 2C2G 机器和模型账单都没有保护 | B4 |
| P12 | 前端问题 | 见 §1.3 | 用户看到的是半成品 | F1–F5 |
| P13 | 部署问题：启动时在线 `pip install`/`apt-get`；Caddy 用 `tls internal`；端口只绑 127.0.0.1；仍保留已废弃的 `RXYCODE_WORKER_RUN_TIMEOUT=900` | `compose.yaml:270` 及 api/worker 的 `command`；`docs/deploy/web-runbook.md:89` | 不能直接上公网，每次启动都依赖外网 | D1、D2 |

### §1.3 当前前端的具体问题（`apps/web/src`）

| 文件 | 问题 |
|---|---|
| `app/App.tsx:117-167` `LoginPage` | 401（未登录）显示成“API 未就绪”；登录成功后读取 `query.data?.user_id`，但 `/me` 返回的是嵌套结构 `user.id`，所以显示为空；页面上没有登录表单 |
| `app/App.tsx:248-261` 路由 | 没有鉴权守卫；`/` 固定跳转到 `/login`；没有全局导航；各页面互相没有链接 |
| `sdk/client.ts:1` | `Me` 类型是平铺的 `{user_id, tenant_id}`，与后端 `auth.py:280-284` 的嵌套结构不一致；没有 `createRun`/`listRuns`/`logout`；每次写请求都会先额外 GET 一次 `/auth/csrf` |
| `features/onboarding/OnboardingPage.tsx` | 让访客自己选“本地/云端/远程”，与部署模式无关；OAuth 回调成功后停在“已登录”，没有下一步 |
| `features/projects/ProjectPanel.tsx:73-81` | “密钥”输入框提交 `repo_config.secret`，但后端 `projects.py:30-38` 必定返回 400；创建会话后只显示“等待运行” |
| `features/chat/ChatPage.tsx` | 回答、中间文本和工具分三个列表渲染，**顺序丢失**；工具只显示“完成/失败”；Final 是纯文本；没有输入框；`postCommand` 不检查响应状态；无样式 |
| `features/runs/eventReducer.ts` | 不认识 `tool.started`、`run.status` 之外的状态事件、`usage.updated`；`question.requested` 丢掉了 `header`/`options` |
| `features/runs/useRunEvents.ts` | 终态后无限重连（见 P2）；`GET /runs/{id}` 返回 401/404 时仍会进入 `connected`；错误重试固定 400ms，没有退避 |
| `features/approvals/ApprovalCard.tsx` | 问题卡每 2 秒轮询一次；不渲染选项按钮；提交后没有成功/失败反馈；审批卡只显示 path，不显示命令 |
| `features/notifications/RunStatusBanner.tsx` | 有一个什么都不做的“打开审批”对话框和“返回”按钮 |
| `styles/globals.css` | 暖米色主题（`#f6f3ee`），与参考布局不一致 |
| `vite.config.ts` | 没有 `/api` 代理，`npm run dev` 时所有 API 请求都会 404（上次演示我手写了一个 Python 代理才跑通） |

---

## §2 已定决策（施工时不再讨论）

| # | 决策 | 理由 |
|---|---|---|
| D-1 | **注册方式 = 邮箱 + 密码 + 邀请码**。GitHub OAuth 保留，作为“已配置才显示”的可选按钮 | 用户要求“简易为主”；不依赖 OAuth App 和 GitHub 在国内的可达性；邀请码同时承担内测期的防滥用和成本控制 |
| D-2 | 不做邮箱验证码、找回密码、手机号。忘记密码由运营者用 CLI 重置（B1 提供） | 首版最简；SMTP 是另一套运维 |
| D-3 | 密码哈希使用 **Python 标准库 `hashlib.scrypt`**（n=2^14, r=8, p=1, 16 字节盐），不新增依赖，也不自己写加密算法 | 标准库基于 OpenSSL；不需要额外引入 argon2/bcrypt |
| D-4 | 注册时服务端自动创建组织、成员关系和一个“默认项目”。用户在首页直接输入任务即可，**不需要先理解项目/会话** | 参考截图的首页就是一个输入框 |
| D-5 | **“控制台” = 两个东西**：① 登录后的应用主界面（侧栏会话列表 + 任务区 + 输入框）；② 进入某个任务后，右侧可展开的 **Agent 控制台面板**（活动：每条工具命令、状态、退出码和输出预览；运行：run 状态、worker、续接次数、事件序号；用量：token 和费用）。首版**不做**交互式终端（`terminal_ws.py` 在云端的隔离尚未审计） | 用户要求“进入 agent 后要有控制台”；让用户能看到 agent 正在做什么 |
| D-6 | 一个会话 = 一个独立的沙箱工作区；同一会话内追问会延续文件和记忆 | 现状：工作区路径为 `/work/runs/<tenant>/<session>`（演示 run 中可见）。**待验证**：B2 卡用两次连续 run 确认第二次能看到第一次的文件和对话 |
| D-7 | Run 的 target 由服务端推导为 `cloud:{tenant_id}:{project_id}`，前端不传 | `drain.py:1226-1243`：`cloud-only` 和 `sandboxed-local` 两种模式都接受租户匹配的 `cloud:*` |
| D-8 | 权限档前端只给两个选项：“每步确认”（`confirm`，默认）和“自动执行”（`full`，沙箱内自动批准） | W8 已定：`full` 只是审批语义，不扩大隔离边界 |
| D-9 | Markdown 渲染使用 `react-markdown` + `remark-gfm`（选择发布超过 7 天的版本并锁定），**不开启 raw HTML**；链接只允许 `http(s):`/`mailto:` | 维护良好的标准方案；默认不渲染 HTML，XSS 面最小 |
| D-10 | **（2026-10-20 用户决定）服务器 = 用户自己的 Windows 主机**（16 核、约 30G 内存，Docker Desktop + WSL2），**对外暴露 = Tailscale Funnel**。已核实的 Funnel 特性（[官方文档](https://tailscale.com/docs/features/tailscale-funnel)）：公网地址固定为 `https://<机器名>.<tailnet名>.ts.net`，**不支持自定义域名**（因此不需要再申请免费域名）；只能监听 443/8443/10000 端口；证书由 tailscaled 自动申请（Let's Encrypt），TLS 在本机终止；流量有不可调整的带宽上限；反向代理只支持转发到 `http://127.0.0.1:<端口>`；tailscaled 会注入 `X-Forwarded-For: <真实客户端 IP>`。部署方式：**Windows 主机上安装 Tailscale 客户端**，执行 `tailscale funnel --bg --https=443 http://127.0.0.1:8080`，gateway 只把端口发布到主机的 `127.0.0.1:8080` | 用户决定；不需要公网 IP、端口转发和域名 |
| D-11 | 镜像在本机构建（就是这台主机），启动时**不再在线执行 `pip install`/`apt-get`/`vite build`**；不需要镜像仓库 | 启动不能依赖外网（W7 时 PyPI/Debian 源多次不通） |
| D-14 | 自托管的前提条件：① Docker Desktop 的 WSL2 虚拟机内存现在只有约 2G（`docker info` 显示 `MemTotal≈2.05G`，没有 `~/.wslconfig`），上线前需要运营者创建 `%USERPROFILE%\.wslconfig` 设置 `memory=8GB`（需要重启 WSL/Docker，**由用户本人执行**）；② 主机关闭自动睡眠，Docker Desktop 设为开机自启（容器已配置 `restart: unless-stopped`）；③ 不把任何 Windows 目录挂载进容器（现有 compose 已经如此） | 2G 虚拟机跑不了真实任务；主机睡眠 = 网站下线 |
| D-12 | 首版容量：1 个 worker 容器（`drain_once` 本身就是串行执行，`drain.py:6273-6287`），每个用户同时最多 1 个活跃 run，全局排队上限 10 | 先保守，D4 实测后再调 |
| D-13 | 分期编号：**W9 = 产品闭环（本地可用）**，**W10 = 上服务器（私有 staging）**，**W11 = 邀请内测**。W12 及以后的内容见 §8 | 回答“W8 后面的内容放在哪” |

---

## §3 范围外（首版不做）

- 匿名使用、免费公开注册（邀请码之外）
- 找回密码、邮箱验证、手机号、第二种 OAuth
- 交互式终端、浏览器预览、设备配对、定时任务、记忆页面在主导航中的入口（代码保留，路由加鉴权，不放进导航）
- 文件上传、语音、图片
- BYOK（用户自带模型 key）、计费/充值
- 多问题批量提问（W8 已明示只支持一个挂起调用一个问题）
- 复制 ChatGPT 的 bundle、品牌、DIL/DPU、Sentinel 指纹协议（REA 材料只用来参考布局和交互反馈）

---

## §4 目标用户流程（W9 结束时必须全部能走通）

```
1. 打开 https://<域名>/            → 未登录 → 跳转 /login
2. 点“注册” → /register            → 填邮箱、密码、邀请码 → 提交
3. 注册成功 → 自动登录 → /app       → 首页只有一个大输入框
4. 输入“写一个 hello.py 并运行” → 回车
   → 前端：按钮立即变为“提交中”；服务端 202 后显示“排队中”
   → 自动创建会话，URL 变为 /app/s/<sessionId>，侧栏出现这个会话
5. Worker 认领 → 状态变为“运行中”
   → 时间线按真实顺序显示：说明文字 → 工具“运行中”行 → 工具完成（含退出码）→ 说明文字 → …
6. Agent 请求审批 → 时间线内出现审批卡（命令、目录、批准/拒绝）
   → 点“批准” → 卡片变为“已批准” → 任务续接
7. Agent 提问 → 时间线内出现问题卡（标题、选项按钮、自由输入）→ 回答 → 续接
8. 完成 → 显示 Markdown Final（代码块、表格、列表）→ 状态变为“已完成”，SSE 停止
9. 点右上角“控制台” → 右侧面板：活动（每条命令和输出）/ 运行 / 用量
10. 在同一会话继续输入“把它改成打印当前时间” → 新 run，能看到上一次的文件
11. 刷新页面 → 历史完整；API 重启 → 仍然保持登录
12. 侧栏底部账户菜单 → 退出 → 回到 /login；后退键不能看到之前的数据
```

---

## §5 接口合同（前后端以此为准）

统一约定：所有接口前缀为 `/api/v1`；错误响应格式保持现有的 `{"code": "..."}`（`main.py:135-138`）；写请求需要 `Origin` 在白名单内，且 `x-csrf-token` 与 `rxy_csrf` cookie 一致（`auth.py:60-67`）。

### §5.1 认证（B1）

| 方法 / 路径 | 请求 | 成功响应 | 错误 |
|---|---|---|---|
| `GET /auth/capabilities` | — | `200 {"mode":"cloud","password":true,"registration":"invite","github":false,"local":false}`（`registration` 取值：`invite`/`open`/`closed`；`github` 仅在 client_id、secret、redirect_uri 都配置时为 true） | — |
| `GET /auth/csrf` | — | 已存在，不改 | — |
| `POST /auth/register` | `{"email","password","invite_code","display_name?"}` | `201` + 设置 `rxy_session` cookie，body 与 `/me` 相同 | `400 INVALID_INPUT`（邮箱格式错误、密码长度不在 8–128 之间）· `403 INVITE_INVALID` · `403 REGISTRATION_CLOSED` · `409 EMAIL_TAKEN` · `429 RATE_LIMITED` |
| `POST /auth/login` | `{"email","password"}` | `200` + cookie，body 与 `/me` 相同 | `401 INVALID_CREDENTIALS`（邮箱不存在和密码错误**返回相同**的错误码和相近的耗时）· `429 RATE_LIMITED` |
| `POST /auth/logout` | `{}` | `204`，服务端撤销会话并清除 cookie；重复调用也返回 204 | — |
| `GET /me` | — | `200 {"user":{"id","kind","email","display_name","github_id"},"organization":{"id","tenant_id"},"membership":{"role"},"default_project_id"}`（保持现有嵌套结构，只追加字段） | `401 UNAUTHORIZED` |
| `POST /auth/local/login`、`GET /auth/github/*` | 已存在 | 保留。`github/start` 在未配置时改为返回 `503 AUTH_PROVIDER_NOT_CONFIGURED`，不再生成空 client_id 的授权链接 | |

规则：

- 邮箱先 `strip().lower()` 再存储和比较，数据库唯一索引。
- 限流：`register` 和 `login` 每个 IP 每分钟 10 次、每个邮箱每分钟 5 次（复用 `api/ratelimit.py` 的计数方式，按路由单独计数）。
- 会话 cookie 设置不变（`HttpOnly`，`SameSite=Lax`，cloud 模式 `Secure`），有效期 7 天（滑动续期：`last_seen_at` 超过 1 天时更新 `expires_at`）。
- 邀请码只存 sha256 摘要，记录 `max_uses`、`used`、`expires_at`。注册成功时在同一事务中 `used += 1`。

### §5.2 Run 与会话（B2）

| 方法 / 路径 | 请求 | 成功响应 | 错误 |
|---|---|---|---|
| `POST /sessions/{session_id}/runs` | `{"message": str(1..20000), "request_id": str(8..64，前端每次发送生成一个 uuid，网络重试时复用), "permission_profile": "confirm"\|"full"}` | `202 {"run_id","status":"pending","session_id","events_url":"/api/v1/runs/{id}/events"}` | `404 SESSION_NOT_FOUND` · `409 RUN_ACTIVE`（该会话已有活跃 run）· `409 REQUEST_CONFLICT`（相同 request_id 但内容不同）· `429 QUOTA_EXCEEDED {"code","reason"}` · `400 INVALID_INPUT` |
| `POST /projects/{project_id}/sessions` | 已存在 `{"title"}` | 已存在 | — |
| `POST /tasks`（**便捷入口**） | `{"message","request_id","permission_profile","project_id?"}` | `202 {"run_id","session_id",...}`：在一个事务里创建会话（标题取 message 的前 40 个字符）+ run；`project_id` 缺省时使用默认项目 | 同上 |
| `GET /sessions/{session_id}/runs?limit=10&before=<cursor>` | — | `200 {"runs":[{"run_id","status","created_at","message","final_preview"}],"next_cursor"}`，按 `created_at` 降序排列；`final_preview` 取 `assistant.final` 文本的前 200 个字符，没有则为 null | `404` |
| `GET /projects/{project_id}/sessions` | 已存在 | **追加**字段：`updated_at`、`last_run: {"run_id","status"} \| null`；按 `updated_at` 降序排列 | — |
| `GET /sessions` | — | `200 {"sessions":[...]}`：当前租户最近 50 个会话（跨项目，字段同上），供侧栏使用 | — |
| `GET /runs/{run_id}` | 已存在 | **追加** `created_at`、`message`、`permission_profile` | — |
| `GET /runs/{run_id}/events` | 已存在 | 不改 | — |
| `POST /runs/{run_id}/cancel` | 已存在 | 不改 | — |
| `GET/POST /runs/{run_id}/approvals` | 已存在 | 不改。**注意**：POST 的 `revision` 必须等于 GET 返回的该审批的当前 `revision`（`approvals/service.py:497-499`）| `409 APPROVAL_STALE` |
| `GET/POST /runs/{run_id}/questions` | 已存在 | GET 的每个问题**追加** `header`、`options:[{label,value}]`（数据已经在 `question.requested` 的 payload 中） | — |

规则：

- 服务端从会话推导 target：`cloud:{tenant_id}:{project_id}`（D-7）。HTTP handler **不调用模型**、不等待执行完成；调用 `create_run` 时**不传** `model` 参数。
- `create_run` 抛出的 `RunAlreadyActive` → 409 `RUN_ACTIVE`，`RunConflict` → 409 `REQUEST_CONFLICT`，`QuotaRefused` → 429 `QUOTA_EXCEEDED`。
- 迁移 `006`：`runs.created_at TIMESTAMPTZ NOT NULL DEFAULT now()`（已有行回填为迁移执行时间）+ 索引 `(session_id, created_at)`；`sessions.updated_at`（创建 run 时更新）。`claimable_run_ids` 改为 `ORDER BY created_at, id`。

### §5.3 事件合同（B3 后端写入 → F4 前端消费）

**原则**：事件日志里的每一行都必须是结构化 JSON；前端只认下表中的类型，其他类型一律忽略。

| 事件类型 | 何时写入 | payload | 前端行为 |
|---|---|---|---|
| `run.created` | 已存在（`create_run`） | `{message, permission_profile, ...}` | 时间线第一项：用户消息 |
| `run.status` | **新增**：在 `claim`、`commit_terminal`、`request_cancel`、park（waiting_approval）、resume 的**同一个事务里**写入 | `{"status": "leased"\|"running"\|"waiting_approval"\|"cancel_requested"\|"succeeded"\|"failed"\|"cancelled"\|"recovery_required", "epoch"?: int}` | 更新状态标签；收到终态后补拉一次事件，然后关闭 SSE |
| `assistant.delta` | 已存在；**改为合并写入**：同一段文本每 300ms 或累计 2KB 落一行；遇到任何非 delta 事件前先把缓冲区 flush | `{"text", "intermediate": bool}` | `intermediate=true` → 只更新顶部的“正在…”状态行，不进入时间线；否则追加到当前文本块 |
| `tool.started` | **新增**：由 `event/tool_begin` 投影 | `{"call_id", "tool", "title"}`。`title` 取 `arguments.description`，其次 `arguments.command`，再次 `arguments.path`，截断到 300 字符 | 时间线插入一行灰色工具行，状态为“运行中” |
| `tool.completed` / `tool.failed` | 已存在 | `{"call_id","tool","status","summary"}`，若协议中有 `exit_code` 和 `duration_ms` 则一并带上（**不要编造**） | 按 `call_id` 更新**原来那一行**，不新增行 |
| `approval.requested` / `approval.resolved` / `approval.resumed` | 已存在 | 不改 | 时间线内的审批卡 |
| `question.requested` / `question.resolved` | 已存在 | 不改（已含 `header`、`options`） | 时间线内的问题卡 |
| `turn.paused` | 已存在 | 不改 | 状态显示“等待你的操作” |
| `assistant.final` | 已存在 | 不改 | Final 节点，Markdown 渲染 |
| `usage.updated` | 已存在 | `{tokens, amount, currency, model_id}` | 控制台“用量”页签；会话顶栏显示 token 数 |
| `notify.*` | **修改**：`event/message_delta`、`event/progress`、`event/reasoning_snapshot`、`event/token_usage` **不再写审计行**（它们已经有投影）；其他 method 的 payload 改为 `{"params": <model_dump(mode="json")>}`，每个字符串字段截断到 2000 字符 | — | 忽略（仅审计） |

`_JOURNAL_CAP` 改为：只对 `assistant.delta` 和 `notify.*` 限量（合并写入后上限提到 2000）；`tool.*`、`approval.*`、`question.*`、`run.status`、`assistant.final`、`usage.*` **永不丢弃**。

### §5.4 前端投影类型（F4 实现，作为 reducer 的输出契约）

```ts
type TimelineItem =
  | { kind: "user"; seq: number; text: string }
  | { kind: "text"; seq: number; text: string }                    // 连续的非 intermediate delta 合并为一块
  | { kind: "tool"; seq: number; callId: string; tool: string; title: string;
      status: "running" | "completed" | "failed"; summary?: string; exitCode?: number }
  | { kind: "approval"; seq: number; approvalId: string; tool: string; command: string;
      status: "pending" | "approved" | "rejected" | "expired" }
  | { kind: "question"; seq: number; questionId: string; header: string; prompt: string;
      options: { label: string; value: string }[]; answer?: string }
  | { kind: "final"; seq: number; text: string }

type RunView = {
  runId: string
  status: string            // 来自 run.status，初始值来自 GET /runs/{id}
  activity: string          // 最近一条 intermediate delta，例如 “Analyzing your request...”
  timeline: TimelineItem[]  // 严格按 seq 排序，按 (runId, seq) 去重
  usage: { tokens?: number; amount?: string; currency?: string } // 未上报的字段保持 undefined，不要写 0
  lastSeq: number
}
```

---

## §6 施工卡

> 格式：目标 · 改哪里 · 怎么改 · 测试 · 完成标准。标注 ∥ 的卡可以并行。
> owner 一列对应 `.agents/skills/` 里应该调用的技能。

### 轨道 A：后端

#### W9-B1 · 认证持久化 + 邮箱注册/登录/退出 + 邀请码 ∥

- **owner**：backend；skill：`security-and-hardening`、`api-and-interface-design`
- **改哪里**：`persistence/models.py`、新增 `alembic/versions/006_auth_and_runs.py`（与 B2 共用同一个迁移文件，**B1 负责创建，B2 往里追加**；如果两张卡由不同 agent 并行施工，B2 改用 `007`）、`api/auth.py`、`main.py`、新增 `rxycode_server/admin.py`（CLI）
- **怎么改**：
  1. 表结构：`users` 追加 `email`（唯一，可空）、`password_hash`、`display_name`、`created_at`；新增 `auth_sessions(token_hash PK, user_id, tenant_id, created_at, expires_at, last_seen_at, revoked_at)`、`oauth_states(state PK, verifier, browser_hash, expires_at)`、`invites(code_hash PK, max_uses, used, expires_at, note, created_at)`。
  2. `current_record` / `_issue` / `_drop_current` 改为读写 `auth_sessions`；删除 `app.state.sessions` 和 `oauth_states` 字典；时间一律使用 `datetime.now(timezone.utc)`，不再用 `time.monotonic()`。
  3. 按 §5.1 实现 `capabilities`、`register`、`login`、`logout`；`/me` 追加字段。注册在一个事务里完成：User + Organization + Membership(owner) + Project(name="默认项目") + 邀请码 `used+1`。邮箱唯一约束冲突 → 409。
  4. `github/start` 在未配置时返回 503。
  5. 运营 CLI：`python -m rxycode_server.admin invite create --uses 5 --days 14 [--note xx]`（只在终端打印一次明文邀请码）、`invite list`、`user reset-password --email x`（从 stdin 读取新密码）、`user disable --email x`（撤销该用户所有会话）。数据库地址读取 `RXYCODE_WEB_DATABASE_URL`。
  6. 环境变量 `RXYCODE_WEB_REGISTRATION=invite|open|closed`，默认 `invite`。
- **测试**（新增 `tests/web/w9/test_auth.py`，使用独立 PG）：注册 → `/me` 正确；邮箱大小写和首尾空格规范化；重复注册 409；邀请码错误、过期、用尽各返回 403；登录密码错误与邮箱不存在返回相同错误码；登出后 `/me` 401；**重新 `create_app`（模拟 API 重启）后旧 cookie 仍然有效**；会话过期返回 401；未带 CSRF 头的写请求返回 403；cloud 模式下 `local/login` 返回 403；限流第 11 次返回 429；`github/start` 未配置返回 503；CLI 重置密码后旧会话失效。
- **完成标准**：上述测试全部通过；`tests/web/w2` 中与认证相关的回归测试通过（先检查夹具是否会 DROP schema，必须改用独立库）。

#### W9-B2 · 提交 Run + 会话历史 + FIFO 队列 ∥（依赖 B1 的迁移文件）

- **owner**：backend + protocol；skill：`api-and-interface-design`
- **改哪里**：`api/runs.py`（或新建 `api/tasks.py`）、`api/projects.py`、`runs/service.py`（只新增查询函数，不改 `create_run` 的事务逻辑）、`persistence/models.py`、迁移文件、`rxycode_worker/drain.py::claimable_run_ids`
- **怎么改**：按 §5.2 实现全部接口；`claimable_run_ids` 改为按 `created_at` 排序；创建 run 时更新 `sessions.updated_at`。
- **测试**（`tests/web/w9/test_runs_api.py`）：POST 返回 202，数据库中出现 run 和 `run.created` 事件；相同 request_id + 相同内容返回同一个 run_id；相同 request_id + 不同内容返回 409；同一会话已有活跃 run 时返回 409 `RUN_ACTIVE`；访问其他租户的 session 返回 404；`POST /tasks` 同时创建会话和 run；GET 列表分页正确；`claimable_run_ids` 先返回较早创建的 run；**模型地址不可达时 POST 仍能在 1 秒内返回 202**。
- **D-6 验证**（在 compose 栈中手动或自动执行一次）：同一会话连续提交两次 run，第二次 run 能读到第一次创建的文件，并能引用第一次的对话内容。若验证失败 → 停下来，在交接中报告，不要自行修改 Harness。
- **完成标准**：测试通过；`create_app().openapi()` 中能看到新增路由。

#### W9-B3 · 事件链修复（worker 侧）∥

- **owner**：worker；skill：`agent-core-boundaries`
- **改哪里**：`rxycode_worker/drain.py::_projection_rows`、`_RunEmit`、`_JOURNAL_CAP`；`rxycode_worker/supervisor.py::claim / commit_terminal / request_cancel`，以及 park/resume 时修改 run 状态的位置；`rxycode_server/events/store.py`（如需支持在已有事务内追加事件）
- **怎么改**：按 §5.3 实现：
  1. `run.status`：在修改 `runs.status` 的**同一个事务**里追加事件和 Outbox（参照 `commit_terminal` 中 `_close_run_span(conn=conn)` 的写法——它已经是在同一事务内写事件）。
  2. `tool.started` 投影。
  3. delta 合并写入：在 `_RunEmit` 中维护缓冲区，满足时间（300ms）或大小（2KB）阈值时 flush；任何非 delta 投影写入之前先 flush；turn 结束（成功、失败、暂停）时也要 flush。确认受限子进程（`emitter` 为 `TurnChannel.emit` 时）同样走这个缓冲逻辑。
  4. `notify.*` 审计行改为结构化 payload，高频 method 不再写审计行。
  5. `_JOURNAL_CAP` 的豁免范围按 §5.3 调整。
  7. SSE 心跳：`api/sse.py` 的 follow 流目前没有任何保活（已核实，文件中没有 heartbeat/ping），任务在长时间思考或等待审批时，链路上的代理（Tailscale Funnel、Caddy、浏览器）可能因长时间无数据而断开。follow 模式下每 15 秒没有新事件就发送一行 SSE 注释 `: ping\n\n`（注释行不会触发前端的 `onmessage`）。测试：follow 一个无新事件的 run，20 秒内至少收到一次 `: ping`。
  6. P9：先用测试确认 `event/agent_needs_input` 在 W8 park 路径下是否还会发出。如果不会发出 → 删除这个分支；如果会发出 → 根据 payload 区分是审批还是提问，只投影一种。
- **测试**（`tests/web/w9/test_event_projection.py`，纯单元测试，不需要 PG 的部分用假 emitter）：`tool_begin` → `tool.started`；100 个连续 delta → 合并后不超过 5 行，且文本完整；delta 和 tool 交替出现时 seq 顺序与发生顺序一致；超过 500 个 delta 后 `tool.*` 和 `assistant.final` 仍然写入；`notify.*` 的 payload 能被 `json` 解析且不含 `method='`；`claim`/`commit_terminal` 之后事件日志中出现 `run.status`（需要 PG，放在 W8 风格的 DB 测试中）。
- **回归**：`tests/web/w8` 全套（168 passed / 4 skipped 为基线）。
- **完成标准**：重新跑一次与演示相同的任务，事件总行数**下降到原来的 1/3 以下**；事件中出现 `run.status`（leased → … → succeeded）和 `tool.started`。

#### W9-B4 · 准入默认值与配置清理 ∥

- **owner**：backend + ops
- **改哪里**：`quotas/service.py`、`infra/compose/compose.yaml`、`docs/deploy/web-runbook.md`
- **怎么改**（已核对 `quotas/service.py` 现状：`_usage` 统计的是租户**全部历史**的 run 数和按空格分词的 token 估算；没有时间窗口；没有全局排队上限）：
  1. `Limits` 追加两个可选字段：`window_seconds: int | None = None`（None = 现有的全历史口径，保持向后兼容）、`queue_max: int | None = None`。
  2. `window_seconds` 有值时，`_usage` 只统计 `runs.created_at`（B2 新增）在窗口内的 run；token 用量改为窗口内这些 run 的 `usage_records.tokens` 之和（真实计量）再加上本次消息的估算值。
  3. `queue_max` 有值时，`reserve` 在获取 worker 之前统计全局 `status='pending'` 的 run 数量，达到上限即以 `kind="queue"` 拒绝（`_refuse` 的映射表补上 `queue`）。
  4. **只有在设置了环境变量时才安装收紧的 gate**：`create_app` 读取 `RXYCODE_QUOTA_CONCURRENCY`、`RXYCODE_QUOTA_TASKS_PER_DAY`、`RXYCODE_QUOTA_TOKENS_PER_DAY`、`RXYCODE_QUEUE_MAX`，只要其中任意一个存在就调用 `install_gate(QuotaGate(limits=Limits(..., window_seconds=86400, queue_max=...), capacity=RunWorkers()))`，未设置的项使用 `DEFAULT_LIMITS` 中的值；都不存在时行为与现在完全一致（W2–W8 的测试不受影响）。`compose.yaml` 中 api 服务设置默认值 `1 / 30 / 2000000 / 10`。
  5. HTTP 映射：`QuotaRefused` → `429 {"code":"QUOTA_EXCEEDED","reason": <kind>}`。
  6. 删除 `compose.yaml` 中的 `RXYCODE_WORKER_RUN_TIMEOUT` 和 `docs/deploy/web-runbook.md:89` 中的对应说明（已确认 `rxycode_worker` 源码中没有任何地方读取它）。
  7. **不改** `_active_slots` 的 TTL 逻辑（`tests/web/w5/test_w5_c06_unit.py` 中的 `ttl_gate` 用例覆盖了现有行为；worker 本身是串行执行，超过 TTL 的长任务最多只会让同一用户多排一个队）。
- **测试**：同一用户提交第二个活跃 run 返回 429 `reason=concurrency`；全局 pending 达到上限后返回 429 `reason=queue`；窗口外的旧 run 不计入当日任务数；被拒绝的请求不占用 worker、不调用模型；不设置环境变量时 `active_gate()` 仍然使用 `DEFAULT_LIMITS`；`tests/web/w5/test_w5_c06_unit.py` 回归通过。

### 轨道 H：Harness 成本（唯一允许修改共享 Harness 的卡）

#### W9-H1 · 完成门禁在 Web 沙箱中反复判 stale（P5）∥

- **owner**：runtime；skill：`agent-runtime`、`agent-quality`
- **现象（已观察到的事实）**：演示 run `20d4b3639a4d4be09e12a54cc1d92fdb` 中，文件已经正确写入，检查命令退出码为 0，但完成门禁连续 6 轮报告 `stale=file_content_exact_line,directory_listing_includes_file`，最终触发了一次向用户的提问，总计 773,379 token。
- **2026-10-20 排查结论（已用真实数据核实）**。数据来源：worker 卷中该 run 的门禁检查点 `.data/checkpoints/cp_cbb3d115….json`、轨迹 `.data/logs/trajectories/e13b5673….jsonl`，以及用 `core.agent_v2._shell_shape_is_unproven` 和 `classify_tool_risk` 对全部 bash 命令的重放（脚本 `%TEMP%\h1_replay.py`）：
  1. **与 Web 沙箱无关，是共享 Harness 的门禁规则导致的**。检查点里的回执身份字段（workspace_id、cwd、workflow_id）都正确；stale 的原因是 `subject_hash` 中的写入代数（`write_generation`）不一致。一个只写一个文件的任务，写入代数被推到了 **23**。
  2. 推高写入代数的主要是**只读的验证命令**。`_shell_invalidates_subject`（`core/agent_v2.py:6367`）对任何含有 `| ; & 换行` 的命令都直接判为“可能写入”（`_shell_shape_is_unproven`，`:1032`），一律推高写入代数并作废全部回执。实际例子：`pwd && ls -1`、`ls -1 && echo '---' && cat hello-rxycode.txt`、`cat x; od -c x | tail -2`、`md5sum x; ls -1 | grep -c x`、`date +%H:%M:%S && <检查命令>`。重放结果：14 次 bash 调用推高了代数，其中大多数是只读命令。
  3. **门禁反馈不说原因**。`_workflow_completion_feedback`（`:5931`）只输出 `stale=<检查ID>`，模型不知道是“后面的命令让检查作废了”，于是开始尝试各种绕路办法：`touch` 文件、写临时脚本、加时间戳、包一层 `sh -c`、最后向用户提问——每一种办法又会推高一次代数。
  4. **“自动执行（full）”模式的 bash 路径返回格式不一致（已确认）**。轨迹中模型 4 次**逐字**执行检查命令（09:52:15、:39、:49、:59），命令字符串与合同完全一致，返回结果却是空字符串 `''`，轨迹状态为 error；同一条命令末尾加上 `print('content OK')` 就“通过”了。原因：permission 为 full/full_auto 且 target 为 local 时，`execution/tool_orchestrator.py:1919-1954` 的 `native_runner` 直接返回原始 stdout——成功但无输出时返回 `''`（普通路径 `tools/bash.py::_format_result` 返回 `[no output]`，已在 worker 容器中验证）；**进程没有启动时也返回 `''`**（第 1944–1945 行），与成功无输出无法区分；而且这条路径**不做**输出截断和脱敏。空字符串被 `log/log_helpers.py::classify_agent_result` 判为失败（“模型未返回可见结果”），界面和轨迹显示失败，模型于是开始用 `echo`/`$?` 包装检查命令，这又触发了第 2 点的回执作废。（轨迹中另外两次 `SyntaxError` 是模型自己改写命令时引入的换行，与此无关。）
  5. 结果：第一次 attempt 用时 95 秒，输入 token 达 565,860，最终以向用户提问结束。另外，该 run 的 `notify.event/tool_begin` 审计行只有 27 条，而轨迹中第一次 attempt 就有 42 次工具调用——这印证了 P8（`_JOURNAL_CAP` 计数被 message_delta 审计行占满之后，其他行被丢弃）。
- **怎么改**（共享 Harness，CLI 和 Web 同时生效，不能给 Web 加特例）：
  1. **只读复合命令不再作废回执**：在 `_shell_invalidates_subject` 中，把命令按引号外的 `&&`、`||`、`;`、`|`、换行拆成多段；只要满足以下全部条件就判定为只读、不推高代数：没有命令替换（`$(`、反引号）；没有写文件的重定向（`>`、`>>`、`&>`；只允许 `2>/dev/null`、`>/dev/null` 和 `<` 输入重定向）；每一段用 `shlex.split` 解析后，命令名（取 basename）属于**门禁专用的只读白名单**，或者 `classify_tool_risk("bash", {"command": 段})` 低于 `RiskLevel.WRITE`。拆分时复用现有的 `_shell_text_outside_quotes`，**不要**另写一个 shell 解析器。任何不满足条件的情况维持现在的保守行为（推高代数）。
     - **为什么需要单独的白名单**（已核实）：`classify_tool_risk` 只把 `pwd`、`ls`、`echo` 判为 READ，`cat`、`od`、`tail`、`grep`、`wc`、`stat`、`md5sum`、`date` 都判为 WRITE。它决定的是**审批**，偏保守是正确的，**不能修改**它。门禁白名单只影响“是否作废检查回执”，不影响审批。
     - 白名单（常量放在 `core/build_workflow.py`）：`pwd ls echo printf cat head tail od wc grep egrep fgrep stat md5sum sha1sum sha256sum file date which test [ true diff cmp find du df basename dirname realpath sort uniq cut tr`。逐项排除会写入或改变状态的参数：`find` 含 `-delete`/`-exec`/`-execdir`/`-ok`/`-fprint*`、`sort` 含 `-o`/`--output`、`date` 含 `-s`/`--set` 时，按写入处理。
  2. **门禁反馈说明原因**：`_bump_workflow_generation` 记录本次推高的原因（工具名 + 截断到 120 字符的命令或路径），保存在内存中最近的 3 条即可，不写入检查点。`_workflow_completion_feedback` 在有 stale 时追加一句：“这些检查在执行之后又被以下操作作废：<原因列表>。请在不再修改工作区之后，把必需检查的命令**逐字**作为最后的工具调用重新执行，中间不要插入其他命令。”
  3. **统一 full 模式 bash 的结果格式**：`native_runner` 不再自己拼字符串，改为把 `result` 组装成 `tools/bash.py::_format_result` 需要的 dict（`stdout`、`stderr`、`success`、`exit_code`，以及 `_artifact_paths`/`_shape_long_output` 读取的其他字段——施工时逐一核对这些辅助函数读取了哪些键），并调用 `_format_result(..., command)` 返回。这样成功无输出时返回 `[no output]`，失败时保留 `[error executing bash: …]` + 退出码，大输出走同样的截断和脱敏。`not result.started` 改为返回 `[error executing bash: command did not start]`。
- **测试**：
  - `_shell_invalidates_subject` 的表驱动测试：`pwd && ls -1`、`ls -1 && echo '---' && cat a.txt`、`cat a; od -c a | tail -2`、`md5sum a; ls -1 | grep -c a`、`ls -1 2>/dev/null` → 不作废；`echo x > a.txt`、`ls | tee out.txt`、`cat $(ls)`、`touch a && cat a`、`rm -f a; ls`、`python3 -c "..."`（单独出现或在复合命令中）→ 仍然作废。
  - 门禁反馈：先执行检查，再执行一条写入命令，`_workflow_completion_feedback` 的输出中包含那条写入命令。
  - full 模式 bash（`permission=full_auto`、`target_id=local`，经过 `ToolOrchestrator` 的 native 路径）：`true` → `[no output]`；`exit 3` → 以 `[error executing bash:` 开头且包含 `[exit code: 3]`；输出超过 `MAX_OUTPUT_CHARS` 时被截断；进程未启动（mock `LocalNativeBackend.run_command` 返回 `started=False`）→ `[error executing bash: command did not start]`，且 `build_tool_evidence` 判为 failed。
  - 用确定性的假 LLM 跑完整的 Build 工作流回合：写文件 → 执行两条检查 → 执行 `cat x; ls` → final_answer，应当一次通过。
  - 回归：`tests/test_core` 中与 build workflow / completion gate 相关的现有测试全部通过（用 `rg -l "check_completion|_workflow_completion_feedback|_shell_invalidates_subject" tests` 找出这些测试）。
- **完成标准**：上述测试通过；用演示 run 的相同 prompt 在 Web 上真实跑一次，token 用量下降到原来的 1/5 以下，且不再出现 stale 提问。不允许用关闭门禁或放宽身份匹配的方式绕过。

### 轨道 F：前端（只做 `apps/web`）

#### W9-F1 · 开发环境、SDK、路由守卫 ∥

- **owner**：frontend；skill：`frontend-ui-engineering`
- **改哪里**：`vite.config.ts`、`sdk/client.ts`、`app/App.tsx`（路由部分）、新增 `app/AuthGate.tsx`、`app/routes.tsx`
- **怎么改**：
  1. `vite.config.ts` 增加 `server.proxy["/api"] = { target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000", changeOrigin: false, ws: true }`。后端本地启动时 `allowed_origins` 必须包含 `http://127.0.0.1:5173`。
  2. SDK：`Me` 类型改为 §5.1 的嵌套结构；新增 `capabilities`、`register`、`login`、`logout`、`createTask`、`createRun`、`listRuns`、`listSessions`、`getRun`；CSRF token 在内存中缓存，收到 403 `FORBIDDEN` 时刷新一次后重试；所有写请求统一检查响应状态，失败时抛出 `ApiError`（**删除** `ChatPage.tsx` 中的 `postCommand`）。
  3. 路由：

     | 路径 | 页面 | 鉴权 |
     |---|---|---|
     | `/` | 已登录 → `/app`，否则 → `/login` | — |
     | `/login`、`/register` | F2 | 已登录则跳转到 `/app` |
     | `/app` | 新任务首页（F3） | 需要登录 |
     | `/app/s/:sessionId` | 会话页（F3/F4） | 需要登录 |
     | `/app/settings` | 账户：邮箱、主题、退出 | 需要登录 |
     | `/runs/:runId` | 兼容旧链接：读取 run → 跳转到 `/app/s/<sessionId>#run-<runId>` | 需要登录 |
     | `/oauth/callback` | 仅在 `capabilities.github` 为 true 时有意义；成功后跳转到 `/app` | — |
     | `/onboarding`、`/projects` | 跳转到 `/app` | — |
     | 其他旧页面（usage/memory/schedule/workspace/terminal/browser） | 保留，加鉴权，不放进导航 | 需要登录 |

  4. `AuthGate`：用 TanStack Query 读取 `["me"]`；401 → 跳转 `/login?next=<当前路径>`（`next` 只接受以 `/app` 开头的站内路径）；网络错误 → 显示“无法连接服务器”和重试按钮（不要显示成“未登录”）。
- **测试**：`npm --prefix apps/web run typecheck`；`npm --prefix apps/web run build`。

#### W9-F2 · 登录 / 注册页 ∥（依赖 F1 的 SDK；可以先用 B1 的接口合同写，B1 完成后联调）

- **owner**：frontend；skill：`frontend-ui-engineering`
- **改哪里**：新增 `features/auth/LoginPage.tsx`、`RegisterPage.tsx`、`AuthLayout.tsx`；删除 `App.tsx` 中的旧 `LoginPage`
- **页面规格**：
  - 居中卡片，宽 400px，上方是 RxyCode 字标，背景为中性浅灰。
  - 登录：邮箱、密码、“登录”按钮；下方链接“没有账号？注册”；`capabilities.github` 为 true 时显示分隔线和“使用 GitHub 继续”；`capabilities.local` 为 true（仅本地开发）时显示“本机口令”折叠区。
  - 注册：邮箱、密码（显示“至少 8 位”）、邀请码（`registration === "invite"` 时显示且必填）、“注册”按钮；`registration === "closed"` 时显示“暂未开放注册”，并隐藏表单。
  - 错误码 → 中文文案：`INVALID_CREDENTIALS`=“邮箱或密码错误”、`EMAIL_TAKEN`=“该邮箱已注册”、`INVITE_INVALID`=“邀请码无效或已用完”、`RATE_LIMITED`=“尝试过于频繁，请稍后再试”、网络错误=“无法连接服务器”。
  - 提交中按钮禁用并显示“正在登录…”；Enter 键提交；首个输入框自动聚焦；输入框使用正确的 `autocomplete`（`email`、`current-password`、`new-password`）。
  - 成功 → `queryClient.setQueryData(["me"], me)` → 跳转到 `next` 或 `/app`。
- **测试**：Playwright（Q1 中实现）；本卡至少截图浅色/深色、375px 和 1280px 各一张交给验收方。

#### W9-F3 · 应用外壳 + 首页 + 会话页 + 输入框（依赖 F1；接口依赖 B2）

- **owner**：frontend；skill：`frontend-ui-engineering`、`agent-surface`
- **改哪里**：`styles/globals.css`、新增 `app/AppShell.tsx`、`features/sidebar/Sidebar.tsx`、`features/console/NewTaskPage.tsx`、`features/session/SessionPage.tsx`、`features/composer/Composer.tsx`；`ProjectPanel.tsx`/`OnboardingPage.tsx` 从路由中移除（文件先保留）
- **布局**（参考 `D:\agent-demo\rea_out\evidence\chat_state.png`，只参考布局，不复制品牌）：

```
┌──────────────┬───────────────────────────────────────────┬───────────────┐
│ RxyCode   [≡]│ 会话标题          ● 运行中  12.3k tok  [控制台]│ 控制台面板     │
│ [+ 新任务]    │                                           │ (F4，默认收起) │
│              │        ┌ 时间线，最大宽度 768px，居中 ┐        │ 活动│运行│用量 │
│ 今天          │        │ 用户消息（右对齐浅灰气泡）   │        │               │
│ ● 写 hello…  │        │ 文本块                     │        │               │
│ ◐ 修复登录…  │        │ ▸ bash  pwd && ls   运行中 │        │               │
│ 更早          │        │ [审批卡]                   │        │               │
│ ✓ …          │        │ Final（Markdown）          │        │               │
│              │        └───────────────────────────┘        │               │
│              │  ┌───────────────────────────────────────┐ │               │
│ ─────────    │  │ 输入任务…                              │ │               │
│ user@x.com ▾ │  │ [每步确认 ▾]                       (↑) │ │               │
└──────────────┴──┴───────────────────────────────────────┴─┴───────────────┘
```

  - **颜色 token**（替换 `globals.css` 中的暖米色）：浅色：背景 `#ffffff`、侧栏 `#f9f9f9`、前景 `#0d0d0d`、次要文字 `#6b6b6b`、边框 `#e5e5e5`、用户气泡 `#f3f3f3`；深色：背景 `#212121`、侧栏 `#171717`、前景 `#ececec`、次要文字 `#a3a3a3`、边框 `#333333`、用户气泡 `#2f2f2f`。状态色：运行中蓝 `#2563eb`、等待操作琥珀 `#d97706`、成功绿 `#16a34a`、失败红 `#dc2626`。状态**同时显示文字**，不能只靠颜色。
  - **侧栏**（宽 260px，可折叠；<768px 时变为抽屉）：“新任务”按钮 → `/app`；会话列表来自 `GET /sessions`，按今天/昨天/更早分组；每项左侧状态点：运行中（蓝色脉冲）/等待你（琥珀）/完成（无点）/失败（红）。有活跃 run 的会话每 5 秒刷新一次列表（只在存在活跃 run 时轮询）。底部账户菜单：邮箱、设置、主题切换、退出。
  - **首页 `/app`**：垂直居中显示一行“今天要做什么？”和输入框；提交时调用 `POST /tasks` → 跳转到 `/app/s/<sessionId>`，并把新会话插入侧栏列表顶部（`invalidateQueries(["sessions"])`）。
  - **会话页 `/app/s/:id`**：`GET /sessions/:id` + `GET /sessions/:id/runs?limit=10`，按时间正序渲染每个 run 的时间线（F4 组件）；已结束的 run 只拉一次事件（`follow=0`）；只有最新的活跃 run 订阅 SSE；顶部“加载更早”按钮使用 `next_cursor`。
  - **输入框**：`textarea` 自动增高（最多 200px，超出后内部滚动）；Enter 发送，Shift+Enter 换行，**IME 组合输入期间（`event.nativeEvent.isComposing`）Enter 不发送**；空内容时禁用发送按钮；左下角为权限下拉（每步确认 / 自动执行）；发送时按钮立即变为“提交中”（spinner），服务端返回 202 后清空输入框；失败时**保留草稿**，显示错误码对应的文案，重试时复用同一个 `request_id`；有活跃 run 时发送按钮变为方形“停止”按钮 → `POST /runs/{id}/cancel` → 显示“取消中”，直到收到 `run.status=cancelled`。输入框固定在底部，时间线底部预留与输入框实际高度相同的空间（使用 `ResizeObserver`）。
  - 新事件到达时，如果用户停留在底部则自动滚动；如果用户已经向上滚动，则显示“↓ 新消息”按钮。
- **测试**：typecheck + build；在 375/768/1280/1440 宽度、浅色/深色下截图。

#### W9-F4 · 时间线 reducer + Markdown + Agent 控制台面板（依赖 B3 的事件合同）

- **owner**：frontend；skill：`agent-surface`、`frontend-ui-engineering`
- **改哪里**：重写 `features/runs/eventReducer.ts`（输出 §5.4 的 `RunView`）、修改 `features/runs/useRunEvents.ts`、新增 `features/timeline/Timeline.tsx`、`ToolRow.tsx`、`Markdown.tsx`、`features/console/ConsolePanel.tsx`；`ChatPage.tsx` 改为渲染 `Timeline`（或直接删除，由 `/runs/:id` 跳转替代）
- **reducer 规则**：按 seq 去重和排序（保留现有缺口等待逻辑）；连续的非 intermediate `assistant.delta` 合并为同一个 `text` 项，遇到其他类型的项后开始新的文本块；`tool.started` 插入一项，`tool.completed`/`tool.failed` 按 `callId` 更新原项（如果没有对应的 started，就以完成状态插入）；收到 `assistant.final` 后，**删除**最后一个与 Final 文本完全相同的 `text` 项（避免重复显示）。
- **`useRunEvents` 修复**：`GET /runs/{id}` 返回 401 → 跳转登录；404 → “任务不存在”；状态以 `run.status` 事件为准；收到终态 → 补拉一次 `follow=0` → 关闭连接，**不再重连**；SSE 出错时按 1s、2s、4s… 最长 30s 退避重连，并在每次重连前先 `GET /runs/{id}`，若已经是终态则停止重连；组件卸载时关闭所有连接和定时器。
- **组件**：
  - `ToolRow`：一行灰色小字，内容为“▸ {tool} {title}”加状态（运行中显示 spinner / ✓ / ✗ 及退出码），点击展开 `summary`（等宽字体，最多显示 20 行，可滚动）。
  - `Markdown`：`react-markdown` + `remark-gfm`；代码块带复制按钮；表格可横向滚动；链接 `target="_blank" rel="noopener noreferrer"`；非 `http(s):`/`mailto:` 的链接渲染为纯文本。
  - 顶部状态行：`activity` 文字 + 状态标签（排队中 / 运行中 / 等待你的操作 / 已完成 / 失败 / 已取消 / 需要恢复）。
  - **`ConsolePanel`**（D-5，点击顶栏“控制台”按钮切换；≥1280px 时为右侧 400px 面板，<1280px 时为全屏覆盖层，Esc 关闭）：
    - **活动**：当前会话所有 run 的工具行，按时间排列，显示完整的 title、状态、退出码和 summary，支持筛选（全部/失败）。
    - **运行**：run_id（可复制）、状态、创建时间、续接次数（`worker.lease` 事件的 epoch 数量）、最新事件 seq、权限档。
    - **用量**：每个 run 的 tokens、费用（来自 `usage.updated`），以及会话合计；没有上报的显示“未上报”。
- **测试**：`apps/web` 目前没有单元测试运行器。**决策**：reducer 的测试放到 Q1 的 Playwright 中，通过注入真实格式的事件数组（使用 `page.evaluate` 调用打包后暴露的 `window.__rxyReduce`——只在 `import.meta.env.DEV` 时挂载）来验证。如果施工者认为必须引入单元测试运行器，可以添加 `vitest`（锁定版本），但只能用于 `src/features/runs/*.test.ts`。

#### W9-F5 · 审批卡和问题卡（依赖 F4）

- **owner**：frontend；skill：`agent-surface`
- **改哪里**：`features/approvals/ApprovalCard.tsx` 拆分为 `ApprovalItem.tsx` 和 `QuestionItem.tsx`，放在时间线中渲染；删除 `RunStatusBanner.tsx` 中无用的对话框
- **审批卡**：标题“需要你批准”；显示工具名、命令（等宽字体）、`description`、工作目录；按钮“批准”和“拒绝”。点击后按钮禁用并显示“提交中…”；先 GET 获取最新 `revision` 再 POST；409 `APPROVAL_STALE` → 重新拉取状态，如果已处理则显示“已被处理”；网络失败 → 恢复按钮并显示“提交失败，可重试”。收到 `approval.resolved` 后卡片折叠为一行“已批准 / 已拒绝”。
- **问题卡**：`header` 作为粗体标题，`prompt` 作为正文；`options` 渲染为按钮组（点击直接提交该选项的 `value`）；另外提供一个自由输入框和“发送”按钮；提交状态的处理与审批卡相同；收到 `question.resolved` 后折叠为“你的回答：…”。**删除**每 2 秒一次的轮询，改为由 SSE 事件驱动刷新（收到 `question.requested` 时拉取一次）。
- **测试**：Q1 中的 E-3、E-4。

### 轨道 Q：联调验收

#### W9-Q1 · 本地端到端联调（依赖 B1–B4、F1–F5；H1 可以并行，不阻塞）

- **owner**：quality；skill：`agent-quality`、`webapp-testing`
- **环境**：独立的 compose project（例如 `-p rxyw9e2e`，不要用 `rxydemo`），`RXYCODE_WORKER_EXECUTION=sandboxed-local`，真实模型（deepseek-flash，key 从运营者环境读取，不写进任何文件）。前端用 `npm run build` 后由 Caddy 提供服务，与生产形态一致。
- **用 Python Playwright + pytest**（`requirements.txt:26` 中已有 `playwright`），新增 `tests/web/w9/test_e2e.py`。
- **场景**（每个场景都要保存截图和事件日志作为证据）：

  | ID | 步骤 | 通过条件 |
  |---|---|---|
  | E-1 身份 | 用 CLI 创建邀请码 → 注册 → 跳转 `/app` → 刷新 → `docker restart` api → 刷新 → 退出 → 后退 | 每一步状态都正确；重启 api 后仍保持登录；退出后后退看不到数据 |
  | E-2 主任务 | 首页输入“创建 hello.py 打印 hello，然后运行它，最后用一个表格总结你做了什么”，选择“自动执行” | 时间线顺序为：文本 → 工具（运行中 → 完成）→ … → Markdown Final（包含表格）；状态最终为“已完成”，**SSE 连接关闭**（通过 Network 面板或 Playwright 的 request 计数确认之后没有新的 events 请求） |
  | E-3 审批 | 同一会话，“每步确认”，输入“把 hello.py 改成打印当前时间并运行” | 出现审批卡 → 批准 → 任务续接 → Final；第二次 run 能看到 hello.py（验证 D-6） |
  | E-4 提问 | 输入一个需要澄清的任务（例如“帮我选一种语言写个排序，然后写出来”） | 如果 agent 提问：选项按钮可点，回答后任务续接；如果 agent 没有提问：记录为 N/A，不算失败 |
  | E-5 取消 | 输入长任务 → 运行中点“停止” | 先显示“取消中”，再显示“已取消”；侧栏状态点更新 |
  | E-6 隔离 | 注册用户 B → 访问 A 的 `/app/s/<id>` 和 `/api/v1/runs/<A 的 run>` | 页面显示“不存在”，接口返回 404 |
  | E-7 断线 | E-2 运行期间执行 `page.context().set_offline(True)` 5 秒后恢复 | 重连后没有重复的时间线项，也没有丢失 Final |
  | E-8 准入 | 用户 A 已有活跃 run 时，在另一个会话中再提交一个 | 显示“你已有任务在运行” |
  | E-9 视觉 | 375/768/1280/1440 × 浅色/深色，覆盖登录、首页、运行中、审批、Final、控制台面板 | 没有横向滚动条；输入框不遮挡内容；人工查看截图，不能出现空白页 |

- **完成标准**：E-1 到 E-9 全部通过（E-4 允许 N/A），形成报告 `docs/reports/WEB-W9-ACCEPTANCE-<日期>.md`：包含实际执行的命令、通过/失败/跳过数量、截图路径和每个任务的 token 用量。**这就是“最基础的内容框架完成”的判定标准。**

### 轨道 D：上服务器（W10）

#### W10-D1 · 生产镜像

- **owner**：ops
- **改哪里**：新增 `infra/docker/api.Dockerfile`、`worker.Dockerfile`、`web.Dockerfile`（多阶段：node 构建 `apps/web` → 把 `dist` 复制进 caddy 镜像），新增 `infra/scripts/build-images.ps1`
- **怎么改**：依赖在镜像构建时安装，使用锁定的版本（从当前 compose 中 api/worker 的 `pip install` 列表和 `requirements.txt` 整理出一份 `infra/docker/requirements-web.txt`，带版本号）；worker 镜像预装 `bubblewrap`；镜像标签使用 `git rev-parse --short HEAD`，在本机构建，不推送镜像仓库（D-11）；镜像中**只包含**发布需要的文件（使用 `.dockerignore` 排除 `.env*`、`docs/plans`、`node_modules`、`tests`、`evals`、REA 材料等）；API 在 `/api/v1/version` 返回 `{commit, built_at}`。
- **完成标准**：断开外网后，用这些镜像 `docker compose up` 能够全部变为 healthy。

#### W10-D2 · 生产 compose overlay + 真实证书 + 备份

- **owner**：ops；skill：`local-agent-process-isolation`（审查 worker 的隔离设置）
- **改哪里**：新增 `infra/compose/compose.prod.yaml`、`infra/compose/Caddyfile.prod`、`infra/scripts/backup.sh`、`infra/scripts/restore.sh`；更新 `docs/deploy/web-runbook.md`
- **怎么改**：
  1. overlay 使用 D1 的镜像（替换 `python:3.12-slim` + 启动脚本），去掉 `reposync`/`webbuild`/`migrate` 的标记文件机制，改为由 api 镜像的入口先执行 `alembic upgrade head` 再启动（或保留一个使用同一镜像的一次性 migrate 服务）。
  2. 端口：gateway 只发布 `127.0.0.1:${RXYCODE_HTTP_PORT:-8080}:80`（供主机上的 Tailscale Funnel 转发）；postgres 等服务在生产 overlay 中**去掉**端口映射（使用 compose 的 `ports: !reset []`，需要 Docker Compose v2.24 及以上版本，施工时先检查 `docker compose version`）。
  3. `Caddyfile.prod`：站点为 `:80`（TLS 由 tailscaled 终止）；保留现有的反向代理规则（`/api/*` 到 api，SSE 关闭缓冲 `flush_interval -1`）；在全局 `servers` 选项中设置 `trusted_proxies static private_ranges`，让 Caddy 保留 tailscaled 注入的 `X-Forwarded-For`，API 限流才能拿到真实客户端 IP。**待验证**：部署后用手机流量访问，在 API 日志中确认记录的 IP 是手机的公网 IP，而不是 Docker 网关地址；如果拿不到真实 IP，所有用户会共用一个限流桶，此时必须把 `RXYCODE_WEB_RATE_LIMIT_RPM` 调大，限流改为依赖 B1 中按邮箱的登录限流和 B4 中按账户的额度。因为浏览器看到的是 https，`RXYCODE_WEB_MODE=cloud` 的 `Secure` cookie 可以正常工作。
  4. 各服务设置内存上限（初始值：api 300M、worker 2G、postgres 256M、redis 64M、minio 256M、gateway 64M；D4 实测后再调）。
  5. `RXYCODE_WEB_MODE=cloud`、`RXYCODE_WORKER_EXECUTION=cloud-only`、`RXYCODE_WEB_REGISTRATION=invite`、`RXYCODE_WEB_RATE_LIMIT_RPM=120`。
  6. 备份：每天 `pg_dump` + 打包 worker 工作区卷，保留 7 天；`restore.sh` 在 staging 上演练一次。
  7. 暂停新任务的开关：`RXYCODE_QUEUE_MAX=0` → 所有新提交返回 429，正在运行的任务不受影响。
- **完成标准**：在本机用 overlay 启动（域名用 `localhost` 测试）全部 healthy；备份 → 删除 → 恢复演练成功。

#### W10-D3 · 首次上服务器（私有 staging）

- **运营者要准备**（AI 不能代办）：注册 Tailscale 账号；在本机安装 Windows 版 Tailscale 并登录；在管理后台的 DNS 页确认 MagicDNS 和 HTTPS 证书已开启，并开启 Funnel（官方文档步骤）；记下本机的 `<机器名>.<tailnet名>.ts.net`（可以先在管理后台把机器名改成好记的名字，例如 `rxycode`）；`.wslconfig` 内存设置（D-14）；模型 API key。
- **步骤**（写进 runbook，逐条执行并记录输出）：在本机一个**不在 git 仓库内**的目录（例如 `D:\rxycode-prod\.env`）创建 `.env`（包括 `RXYCODE_WEB_SECRET`（32 字节以上随机值）、数据库密码、MinIO 密码、`RXYCODE_API_KEY`、`RXYCODE_WEB_ORIGINS=https://<机器名>.<tailnet名>.ts.net`）→ `docker compose -p rxyprod --env-file D:\rxycode-prod\.env -f compose.yaml -f compose.prod.yaml up -d` → 确认 `curl http://127.0.0.1:8080/api/v1/auth/csrf` 返回 200 → `tailscale funnel --bg --https=443 http://127.0.0.1:8080`（`--bg` 会让配置在重启后保留）→ `tailscale funnel status` 确认已公开 → 检查 Linux 沙箱可用（worker 日志中的 userns/bwrap 自检；不可用时 worker 必须拒绝执行，不能退回到宿主执行）→ 用 CLI 创建自己的邀请码 → 用手机流量（不是家里 Wi-Fi，也不要在手机上登录 Tailscale）打开 `https://<机器名>.<tailnet名>.ts.net` 注册 → 跑一遍 E-2 和 E-3 → 用 Windows 任务计划程序设置每日备份。生产栈使用独立的 project 名 `rxyprod`，与开发/演示栈（`rxydemo`）互不干扰。
- **完成标准**：外网可以通过 https 访问且证书受信任；E-1、E-2、E-3 在生产栈上通过，其中 E-2 运行超过 5 分钟时 SSE 不断流（验证 Funnel 链路下的长连接）；回滚方法验证过（把镜像标签切回上一个版本后 `up -d`）；主机重启后整个栈和 Funnel 会自动恢复。

#### W10-D4 · 容量与成本实测

- **owner**：ops + quality
- **测量**：空闲时各容器内存（参考值：本机 `rxydemo` 栈空闲时 gateway 27M、api 92M、worker 111M、redis 15M、postgres 31M、minio 204M，合计约 480M，**这不是运行任务时的数据**）；跑 1 个 E-2 任务时的 worker 内存峰值（含沙箱子进程）和 CPU；5 个浏览器同时打开会话页、各自保持 SSE 连接时 api 的内存和 CPU；3 个用户同时提交时的排队表现（第 2、3 个用户应看到“排队中”，而不是白屏或报错）。
- **决策规则**：如果运行 1 个任务时总内存超过 1.6G（2G 机器）→ 升级到 4G，或者把 MinIO 换成云厂商的对象存储（节省约 200M）。**不能**通过关闭沙箱、杀掉长任务或删减功能来省内存。
- **完成标准**：形成容量表（空闲 / 1 个任务 / 5 个连接）和每个任务的平均 token 与费用，写进验收报告。
- **主机已实测（2026-10-21）**：AMD Ryzen 7 8845H（8C/16T）、内存 27.8G（空闲 12.2G）；**Docker Desktop VM 上限仅 ~1.9G**（无 `.wslconfig`）——按计划的服务限额合计 ~2.9G，D2 落地前必须先调大 `.wslconfig`（建议 6G）或把 MinIO 换外部对象存储；C 盘仅剩 10.6G（Docker 数据默认在 C 盘 vhdx，镜像构建前先迁移 Docker 数据到 D 盘或清出空间）；D 盘余 41.1G。`rxydemo` 栈空闲合计约 480M 仍在线，测容量时需扣除或先停。Tailscale 未安装（PATH 与 `C:\Program Files\Tailscale` 均无）——D3 的运营者准备项确认仍未完成。

---

## §7 时间表

按“一个主开发者 + 多个 AI agent 并行施工”的节奏估算。日期是目标，**门禁没有通过就顺延，不降低标准**。

| 日期 | 轨道 A 后端 | 轨道 F 前端 | 其他 | 里程碑 / 运营者要做的事 |
|---|---|---|---|---|
| **10-20 周二** | B1+B2+B4 开工 | — | 本文定稿；H1 开始复现 | 已决定：自己的主机 + Tailscale Funnel（D-10） |
| **10-21 周三** | B1 认证 + 迁移 | F1 开发环境/SDK/路由 | H1 继续 | 运营者：注册 Tailscale、安装 Windows 客户端、开启 Funnel；设置 `.wslconfig`（D-14） |
| **10-22 周四** | B2 Run API + B4 准入 | F2 登录注册页 | B3 事件链；H1 继续 | — |
| **10-23 周五** | B3 收尾，B1/B2 联调 | F3 外壳/首页/会话页/输入框 | H1 出结论（找到根因或交接已排除的可能性） | **检查点：浏览器能注册、能提交任务、侧栏能看到会话** |
| **10-24 周六** | 修复联调中发现的问题 | F4 时间线 + 控制台面板 | — | — |
| **10-25 周日** | 修复问题 | F5 审批/提问卡 | Q1 开始 | — |
| **10-26 周一** | — | — | **Q1 完成 E-1 到 E-9** | **M1：基础内容框架完成**（§4 的 12 步在本地全部走通） |
| **10-27 周二** | — | — | D1 镜像 + D2 overlay | — |
| **10-28 周三** | — | — | **D3 上服务器** | **M2：首次上服务器**（私有 staging，只有自己使用） |
| **10-29 周四** | — | — | D4 容量实测 + 修复 | 根据 D4 结果决定是否升级配置 |
| **10-30 – 11-05** | 每天修复反馈的问题 | 每天修复反馈的问题 | W11 邀请 3–5 人 | **M3：邀请内测**。每天查看：失败的 run 数量、平均 token、内存峰值、用户反馈 |
| **11-06** | — | — | 内测复盘 | **决策点**：扩大邀请（10–30 人）还是继续修复 |
| 11-06 之后 | §8 的 W12 | | | |

以后如果想换成自己的域名：Funnel 不支持自定义域名，届时需要换成其他隧道方案或云服务器，只需修改 D2/D3，不影响 W9 的代码。

自托管的风险（运营者知悉即可）：主机关机或断网 = 网站下线；Funnel 中继服务器在国内的访问速度和稳定性需要在 D3 用国内手机网络实测；Funnel 有不可调整的带宽上限；`*.ts.net` 地址会公开机器名和 tailnet 名；家用宽带的服务条款可能不允许对外提供服务；在大陆境内对公众提供网站服务可能涉及 ICP 备案要求。

---

## §8 W12 及以后（按需排序，内测数据决定优先级）

| 优先级 | 内容 | 启动条件 |
|---|---|---|
| P1 | 工作区文件浏览和 Diff 查看（复用 `FileTree`/`DiffReview` 和 `api/workspace.py`，先验证云端 target 下是否可用） | 内测用户需要查看产物 |
| P1 | 产物下载（复用 `api/artifacts.py`） | 同上 |
| P1 | 会话重命名、删除、搜索 | 会话数量变多 |
| P1 | 找回密码（需要 SMTP） | 有用户忘记密码 |
| P2 | 运行中追加指令（`steer`，接口已存在，`api/runs.py:88`） | 用户反馈需要中途纠正 |
| P2 | 子 Agent 检查器（复用 `AgentTree.tsx`，需要先确认子 agent 的事件在 drain 中有投影） | 任务开始使用子 agent |
| P2 | GitHub 仓库导入和 PR | 用户希望处理自己的仓库 |
| P2 | 交互式终端（需要先对 `terminal_ws.py` 在云端的隔离做安全审计） | — |
| P3 | 控制面与执行面分离、多个 worker | D4 实测排队时间过长 |
| P3 | BYOK、计费 | 准备收费 |
| P3 | 公开注册（关闭邀请码）+ Turnstile 等人机验证（必须在服务端校验） | 内测稳定，成本模型清楚 |

---

## §9 上线检查清单（M2 之前逐项勾选）

- [ ] §4 的 12 步在本地全部走通（Q1 报告）
- [ ] H1 已解决，或单任务成本已知且准入额度与之匹配
- [ ] API 重启后保持登录（B1）
- [ ] 事件日志中有 `run.status`，前端在任务结束后不再重连（B3、F4）
- [ ] 每用户 1 个活跃 run、全局排队上限、每日额度均已生效（B4）
- [ ] 镜像启动不依赖外网（D1）
- [ ] 生产栈只有 gateway 发布到主机 `127.0.0.1:8080`，只通过 Tailscale Funnel 对外；PG/Redis/MinIO 不可从外部访问（D2）
- [ ] 外网 https 证书受信任，`Origin` 白名单只有 `https://<机器名>.<tailnet名>.ts.net`（D2）
- [ ] API 日志中记录的是真实客户端 IP（D2 待验证项）
- [ ] `.wslconfig` 内存已调大，主机不会自动睡眠，重启后栈和 Funnel 自动恢复（D-14）
- [ ] worker 沙箱自检通过；沙箱不可用时拒绝执行（D3）
- [ ] 备份和恢复演练过一次（D2）
- [ ] 有暂停新任务的开关和回滚方法（D2、D3）
- [ ] `.env` 不在 git 中，日志中没有密钥、cookie 或邀请码明文
- [ ] changelog 已记录 W9/W10 的全部变更

---

## §10 交给施工 Agent 的提示词模板

> 在 `D:\agent-demo\RxyCode\RxyCode1_1_0`（分支 `feat/rxycode-web`）工作。先阅读 `AGENTS.md` 和 `docs/plans/opus5-plan/rxycode -web/phases/PHASE-W9-PRODUCT-CLOSURE-AND-DEPLOYMENT.md` 的 §0、§2、§5，然后**只做卡片 `<卡片ID>`**（§6）。
> 开始前执行 `git status --short` 和 `git log -1`，不要改动与本卡无关的文件，也不要撤销别人的改动。
> 按卡片中“改哪里 / 怎么改 / 测试 / 完成标准”执行；接口以 §5 为准，如果发现代码与本文不一致，先报告具体的文件和行号，不要自行改合同。
> 测试只能用独立的数据库和 compose project 名，不能连 `rxydemo`。
> 完成后：在当前版本的 changelog 中追加条目；交接内容包括改动的文件、执行过的测试命令及结果（通过/失败/跳过数量）、剩余风险、下一张卡。没有用户授权不要 commit 或 push。

---

## 附录 A：REA 材料中借鉴了什么

| REA 观察（`D:\agent-demo\rea_out\REPORT.md`） | RxyCode 如何使用 |
|---|---|
| 侧栏 + 主区 + 底部圆角输入框（`chat_state.png`） | F3 布局 |
| `composer-height-resource`：输入框高度变化时调整正文区域 | F3：用 `ResizeObserver` 为时间线底部预留空间 |
| `native-composer-submit-state`：提交状态独立管理 | F3：提交中 → 排队中 → 运行中，各状态分开显示 |
| `content` 帧带 `messageId` + `revision`，支持 append/replace | 我们使用 `(run_id, seq)` + `call_id` 达到同样效果，不改传输协议 |
| `control` 帧中的 `terminal-received` 明确告知流结束 | B3 的 `run.status` 终态事件 + F4 收到终态后关闭连接 |
| `resume-token` 续流 | 已有：`Last-Event-ID` / `after_seq` |
| Sentinel + Turnstile 反滥用 | 首版使用邀请码 + 限流 + 额度；公开注册前再接入 Turnstile（服务端校验） |
| 登录页的“登录 / 免费注册”双按钮 | F2 的登录/注册互相链接 |
| Octane、DPU、DIL（模型生成可执行 UI） | **不采用**：与当前技术栈无关，并且会引入执行不可信代码的风险 |

## 附录 B：本文核实时使用的命令

```text
# 演示 run 的事件类型分布（rxydemo 栈，只读查询）
select type, count(*) from run_events where run_id='20d4b3639a4d4be09e12a54cc1d92fdb' group by type order by 2 desc;
# 结果摘要：assistant.delta 778 / notify.event/message_delta 638 / notify.event/progress 97 / tool.completed 20 /
#           notify.event/tool_begin 27 / approval.requested 3 / question.requested 1 / assistant.final 1 /
#           usage.updated 1（tokens=773379, amount=1.54675800 USD）；没有任何 run.status 事件

# 路由清单
grep "@router\.(get|post|put|delete|websocket)\(" packages/rxycode-server/src/rxycode_server  → 没有创建 Run 的 POST 路由

# 空闲内存
docker stats --no-stream  → gateway 27M / api 92M / worker 111M / redis 15M / postgres 31M / minio 204M
```
