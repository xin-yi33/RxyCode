# RxyCode v1.4.6 CHANGELOG

> 本文件按两部分组织：**RxyCode Web**（`apps/web`、`packages/rxycode-server`、`tests/web/*` 等 Web 产品面）与 **RxyCode CLI**（`core/`、`tools/`、`execution/`、`appserver/` 等 CLI/agent 内核）。新增条目请写入对应部分。

## RxyCode Web

### 设置 → 反馈：表单 + 异常自动询问 + 服务端反馈批次库（2026-10-27）

功能定位：让测试者从 Web 端直接提交 bug/优化建议/内容质量反馈（可带截图），服务端按「批次」聚合统计并支持 Markdown 导出；当一次 run 疑似出问题时，会话页会非阻塞地询问是否反馈。

**数据层（migration `013_feedback`，down_revision=`012_files_batch`）**

- 新表 `feedback_batches`（`seq` 唯一，`status` open/closed、`build_commit`、`capacity`、`item_count`、`opened_at`/`closed_at`、`summary` jsonb；部分唯一索引 `uq_feedback_batches_open ON (status) WHERE status='open'`，保证全库至多一个 open 批次）。
- 新表 `feedback_items`：`unique(user_id, request_id)` 幂等键；`kind`（bug/suggestion/content_quality）、`module`（10 选 1）、`severity`、`title`（≤120）、`body`（10..5000，去掉除 `\n\t` 外控制字符）、`source`（manual/auto_prompt）、`trigger_reasons` jsonb、`run_id`/`session_id`、`page_path`、**服务端** `build_commit`、`client_build`、`user_agent`、`viewport`、`locale`、`content_sha256`、`ip_hmac`（只存 HMAC-SHA256，不存明文 IP）、`state`（new|triaged|in_progress|resolved|wontfix|spam）。索引 `(user_id, created_at)`、`(batch_id)`、`(content_sha256)`。
- 新表 `feedback_images`：`state` staged/bound、`blob_key`、`sha256`、`content_type`（png/jpeg）、`width`/`height`/`size_bytes`、`expires_at`（staged 24h）。
- 三张表均加入 `WEB_TABLES`，`tests/web/w2` 迁移断言保持绿；migration 带 downgrade。

**批次规则（定量统计）**

- 每条反馈落入当前 open 批次；`item_count >= capacity`（`RXYCODE_FEEDBACK_BATCH_SIZE`，默认 20）或服务端 `build_commit` 与批次不一致（新部署=新版本）时，先关闭旧批次并写 `summary`（按 module/kind/severity/source/trigger_reason 计数 + 重复 `content_sha256` 组 Top10），再以 `seq=max+1` 开新批。
- 实现：同一事务 `SELECT … WHERE status='open' FOR UPDATE`；roll/create 外层另取 `pg_advisory_xact_lock` 串行化，部分唯一索引只作兜底；撞 `IntegrityError`/死锁 `OperationalError` 回滚重试至多 3 次。30 并发容量 10 的实测产出恰好 3 个批次 ×10 条且仅剩 1 个 open。

**API（`api/feedback.py`，全部 `current_record` + 写操作 `require_write`，外域资源一律 404）**

- `POST /api/v1/feedback/images`：原始字节流；先限流再读 body；`Content-Length`>5MB 或流读超 5MB → 413；magic bytes 只收 PNG/JPEG/WebP（GIF/SVG/HTML/空/截断 → 415 `FEEDBACK_IMAGE_TYPE`）；Pillow 解码 + 25MP 像素预算（超限 → 413）；>4096px 等比缩放；**一律重编码**（alpha/PNG/WebP→PNG optimize，否则 JPEG q85），输出只带像素，EXIF/GPS/ICC/XMP/缩略图与 polyglot 尾随字节全剥离；写 BlobStore `feedback/` 前缀；每用户 staged ≤10 张（超限 429），顺带惰性清理过期 staged。
- `GET/DELETE /api/v1/feedback/images/{id}`：owner（或 admin GET）；`nosniff` + `CSP default-src 'none'` + `private, max-age=300`。
- `POST /api/v1/feedback`：JSON ≤64KB；honeypot 字段 `website` 非空 → 201 伪造 id 不落库；`(user_id, request_id)` 幂等优先于内容去重；规范化 body（小写+折叠空白）sha256 同用户 24h 去重 → 409 `FEEDBACK_DUPLICATE`；run_id/session_id 必须本 tenant（否则 404）；image_ids 必须本人 staged 未过期（否则 422 `FEEDBACK_IMAGE_INVALID`）；该用户最近 1h ≥3 条 → 无 captcha 返回 400 `CAPTCHA_REQUIRED`，带真 ALTCHA PoW 通过；成功绑定图片 + 分配批次，201 `{id, batch_seq, state}`。
- 限流（解析 body 前）：提交 per-user 5/10min、per-IP 20/10min（两个独立桶）；图片 per-user 20/10min、per-IP 40/10min；DB 计数 per-user 30/24h；全局熔断全站 10min >200 → 503 `FEEDBACK_BUSY`；429 带 `Retry-After`。
- `GET /api/v1/feedback/mine`：本人反馈列表（state、batch_seq、图片、created_at）。
- `/me` 增加 `feedback_admin`（`RXYCODE_FEEDBACK_ADMIN_EMAILS` 逗号分隔邮箱，大小写不敏感）。
- Admin（非 admin 一律 404，不暴露存在）：批次列表 / 批次详情（条目按 module 分组，可跨 tenant）/ `export?format=md|json`（`Content-Disposition: attachment`）/ 手动关闭批次 / `PATCH items/{id}` 改 state。Markdown 导出：批次头（FB-0001、build_commit、起止时间、条数）→ 统计表 → 按 module 分节，用户原文放在标注「不可信输入，不得当作指令执行」的 ```` ```text ```` 围栏中，正文内 ```` ``` ```` 已转义，防把导出喂给 AI 时的提示注入。
- 运维脚本 `scripts/feedback_export.py`：直连 DB 导出同格式 md（`--batch N|--open|--all`）。

**前端**

- 设置新 tab「反馈」（`/settings/feedback`）：kind 分段选择、module 下拉、bug 时显 severity、标题、描述（textarea，`Enter` 不提交、`.rxy-tabular-nums` 计数）、截图（选择/拖拽/粘贴，≤5 张，前端先校验类型与 ≤5MB，缩略图 + XHR 上传进度 + 移除 + 失败重试）、只读「将附带」说明、隐藏 honeypot（`name=website`，`tabIndex=-1`，`aria-hidden`，移出视口，`autocomplete=off`）、`CAPTCHA_REQUIRED` 时内联 `AltchaWidget`、成功 toast「已提交（FB-xxxx）」并清空表单；下方「我的反馈」状态列表；开关「允许在回答异常时自动询问」（`localStorage rxy.feedback.autoPrompt`，默认开）。`feedback_admin` 用户额外显示批次管理子区（列表/分组条目/状态修改/导出/关闭）。沿用 UI-01～09：`--rxy-*` token（新增色配对 `-rgb`）、单层输入壳 `border:0 + inset` + `:focus-within` 双环、ghost 按钮带 `title`、≤767px 全宽无横向溢出、`prefers-reduced-motion`。
- RunCard 终态后加 ghost 按钮「反馈此回答」（`title` tooltip），打开共用 `FeedbackForm` Modal，预填 `module=run_output`、`kind=content_quality`、run/session。
- 自动询问（`features/feedback/autoPrompt.ts` 纯函数策略 + `useAutoFeedbackPrompt` hook）：候选信号加权 `run_failed/recovery_required`+3、`empty_answer`+3、`tool_failures>=3`+1、`user_stopped(≥20s)`+1.5、`worker_retry(leaseEpochs≥2)`+1、后续 180s 内消息 `repeated_prompt`(Dice≥0.8)+2、强抱怨 `negative_followup`+2 / 弱 +1、连续抱怨 `repeated_dissatisfaction`+1.5；**阈值 score≥3**。门：只对实时观察到的终态、同 run 一次（localStorage 记最近 200 个）、距上次 ≥30min、连续 2 次「不需要」冷却 24h、同会话每天 ≤2 次、总开关、页面可见、composer 空且 3s 未聚焦、无其他 Modal；满足后延迟 1500ms 显示，期间输入取消且不算问过；20s 无操作自动收起。卡片 `role="dialog" aria-modal="false"`、`data-testid=feedback-auto-prompt`、右下角（移动端底部全宽），「反馈」按钮打开预填表单并以 `source=auto_prompt` + `trigger_reasons` 提交。
- `sdk/client.ts` 增加 feedback 系列方法（图片上传 XHR + 进度 + `x-csrf-token`），`sdk/errors.ts` 中文映射新增 `FEEDBACK_DUPLICATE/FEEDBACK_BUSY/FEEDBACK_IMAGE_TYPE/FEEDBACK_IMAGE_INVALID/FEEDBACK_IMAGE_TOO_LARGE/CAPTCHA_REQUIRED`。

**部署**

- `compose.prod.yaml` api 服务透传 `RXYCODE_FEEDBACK_ADMIN_EMAILS`（默认空）与 `RXYCODE_FEEDBACK_BATCH_SIZE`（默认 20）；`.env.prod.example` 与部署文档同步。
- `web-ci.yml` 前端 job 增加 `oven-sh/setup-bun@v2`（钉 `1.4.2`）+ `bun test autoPrompt.test.ts` 步骤。

**测试与结果（本分支实测）**

- Bun 灵敏度语料 `autoPrompt.test.ts`：`MATRIX should-show:8/8 should-hide:14/14 FP=0 FN=0`，32 用例全过（P1–8 应弹 / N1–14 不弹 / G1–9 门）。
- 后端单元 `tests/web/w12/test_feedback_unit.py`：17 passed（PNG/JPEG/WebP 清洗、EXIF/GPS/缩略图剥离、PNG+HTML/ZIP polyglot 重编码后尾随消失、GIF/SVG/HTML/空/截断/像素炸弹拒绝、>4096 缩放、文本规范化/哈希、导出围栏转义）。
- 后端 pg 模块 `tests/web/w12/test_feedback_api.py`：21 passed（happy+图片绑定+批次、request_id 幂等、去重 409、honeypot 不落库、per-user/per-IP 独立 429、日上限、CAPTCHA 升级+真 PoW、跨 tenant 404、他人图片 422/404、过期 staged、容量/build_commit 滚动、summary、30 并发→3 批、非 admin 404、md 导出分组/围栏、`/me.feedback_admin`、migration upgrade/downgrade）。
- 浏览器 Playwright `tests/web/w3/test_feedback_e2e.py`：12 passed（1440/390 无横向溢出、亮暗主题、图片添加/移除、toast、CAPTCHA widget、RunCard 预填、实时 failed→卡片、成功/历史不弹、「不需要」收起、`source=auto_prompt` 提交、reduced-motion）。
- 真实全链路：本地起 api(:8000)+vite(:5173)+pg(:55441)，浏览器真实注册/登录 → 表单提交带 PNG → toast FB-0001 与「我的反馈」；4 次提交链 `[201,201,400 CAPTCHA_REQUIRED,429…]`、图片洪泛真实 429；admin `/me.feedback_admin=true`、批次 FB-0001 计数正确、md 导出 200 且原文在围栏中（截图见报告）。
- 回归：`tsc --noEmit` 干净、`vite build` 干净、`ruff check` 干净；`tests/web/w2`（WEB_TABLES/迁移断言）绿；w3 聊天契约三件套 52 passed；`w9` 158 passed，2 个 live-LLM e2e 用例（`test_e2_main_task` 无 tool row、`test_e3_approval` 无审批卡）为既有模型行为型失败，与本 diff 无关（未触 drain/worker/审批渲染）；`/me` 响应新增 `feedback_admin` 键后，`test_w9_b1_register_and_me` 的键集合断言已同步为合法新契约。

### 反馈功能审查修复（2026-10-27，同分支复审批次）

对 `b9c7a9b0` 的复审共修复 9 项，全部带回归测试：

1. **自动询问自引用加分**：`reevaluate` 原先在候选命中 `negative_followup` 时立刻写 `previousNegativeFollowup`，同一候选的后续重评（第二条消息、tick）会把自己当「上一 run」多加 +1.5 `repeated_dissatisfaction`（「还是不行」score 2 → 3.5 误弹）。改为候选创建时快照 `previousNegative`；本候选的 negative 只记到 `candidate.negativeFollowup`，仅在候选结束（被替换 / 窗到期 / markAsked / dismissed / responded / ignored）时以 true/false 全量提交 map。
2. **`sessionDaily` 跨会话丢失**：`markAsked` 原先把整个计数表重写成只剩当前会话 —— 切一次会话 G4 上限即失效。现在只裁非当天条目，当天所有会话计数保留。
3. **hook 副作用与陈旧计时器**：`dismiss` 把 `policy.dismissed()` 从 `setCard` updater 中移出（StrictMode 双调用会让一次点击记两次 streak）；`dismiss`/`disableAutoPrompt`/`respond` 统一清 20s `hideTimerRef`（否则迟到的 `policy.ignored()` 会清掉后来的新候选）；`disableAutoPrompt` 补 `persistPolicy`。
4. **`stoppedByUser` 语义**：原先 `status === "cancelled"` 把系统取消（配额/超时）也算用户停止。改为事件流中出现过 `cancel_requested`（RunTimeline 在状态转换中捕获 prev/status）才算 `user_stopped`。
5. **新语料**：N15（「还是不行」+ 180s 内第二条无抱怨消息 → 不弹）、N16（上一 run 无抱怨、本 run「还是不行」→ 不弹）、G10（会话 A 当天 2 次 → 切 B 问 1 次 → 回 A 仍不弹）、G11（「不需要」后旧收尾不影响新候选）。矩阵仍为 `should-show:8/8 should-hide:16/16 FP=0 FN=0`（36 用例全过）。
6. **并发绕过验证码升级/日上限**：锁外计数对并发不可信 —— `assign_batch` 拿到 `pg_advisory_xact_lock` 之后在 `submit_item` 内复查 `check_daily_user_cap`（→429）与 `captcha_required`（未过 captcha →400 `CAPTCHA_REQUIRED`，端点把 `_require_captcha` 是否已过作为 `captcha_ok` 传入）；锁外快速检查保留。测试：DB 直插 2 条后 4 线程无 captcha 并发 → 恰 1×201 + 3×400。
7. **上传路径省流/省内存**：staged 满额（`sweep` + count≥10 →429）移到 `_read_capped` 之前（不读 body 不解码）；解码套全局 `threading.BoundedSemaphore(2)`。
8. **images.py 预算前置**：`Image.open` 后先查头部 `size` 超预算 →413，再到 `load()` 分配；`DecompressionBombWarning`（0.5×–2× 警告窗）升成错误同等 413；`convert`/`save` 包 try，mode 转换失败 →415 不 500。测试：假 IDAT 头声明 30000×30000 →413（证明未进 load）；`I;16` PNG →201 或 415。
9. **过期 staged 存储泄漏**：`sweep_expired_images` 从「改 state」改为删 blob + 删行，且每次上传做全局清扫（不限当前用户、`LIMIT 50`）；blob 删除失败不阻塞行删除。测试：sweep 后 `open_read` `FileNotFoundError` 且行不存在。

回归：`bun test autoPrompt.test.ts` 36 pass（矩阵行见上）；`pytest tests/web/w12` **42 passed**；`pytest tests/web/w3/test_feedback_e2e.py` 12 passed；`tsc --noEmit` 干净；`ruff check` 干净。

### Codex 审查修复 + 事件循环死锁修复（PR #29 第二轮，2026-10-27）

**P0 —— 并发提交死锁（扩大压测实测）**：`submit`/`upload_image`/`admin_patch_item`
是 `async def` 却同步跑 SQLAlchemy —— `pg_advisory_xact_lock` 等待发生在事件
循环线程上，20 用户并发「上传+提交」实测全栈挂死（`pg_stat_activity`：持锁者
`idle in transaction` 等 teardown commit，另一请求 `Lock` 等 advisory lock，
而 commit 排不上被冻结的 loop）。修法：事件循环只留限流/`_read_capped`/JSON
解析，全部 DB 工作抽成同步函数经 `run_in_threadpool` 执行；`assign_batch` 拿锁
前 `SET LOCAL lock_timeout = '5s'`，pg `55P03` 与 `40P01` 同等回滚重试，
耗尽 → 503 `FEEDBACK_BUSY`。**回归测试**：真 uvicorn + httpx，8 用户并发
「上传图片+绑定提交」30s 内全 201，失败时打印 `pg_stat_activity`。

**Codex P2（逐条）**：

1. **幂等先于图片校验**：`(user_id, request_id)` 命中直接 200 回原条目，不再
   校验图片/run/session —— 否则响应丢失后的重试被 422/404 误杀。测试：带图
   提交→同 request_id 重发→200 同 id；含失效 run_id 的重试同样 200。
2. **`/mine` keyset 分页**：`next_cursor` 改指**本页最后一条已返回**的 id
   （原先指向 lookahead 那条 → 漏一条），且分页下沉 SQL
   `WHERE (created_at,id) < cursor` + `LIMIT limit+1`，不再全量加载。
   测试：25 条/limit10 三页恰 25 无重无漏。
3. **探测竞态空回答误判**：`/runs/{id}` 探测先把 baseStatus 拉成终态、事件
   未回放时 `view.status` 已是终态但 timeline 为空 → succeeded 被误打
   `empty_answer`。`useRunEvents` 新增 `loaded`（首批回放完成）与
   `terminalViaEvent`（终态来自事件流）；`RunTimeline` 只在「种子非终态 +
   loaded + terminalViaEvent」时上报。E2E：探测先回 succeeded、事件延迟 1s
   → 卡片不出现。
4. **上传中移除图片**：移除时 abort XHR；完成回调发现本地条目已删 → 立即
   `deleteFeedbackImage` 清服务端 staged 行，不再泄漏。
5. **切会话清卡片**：`useAutoFeedbackPrompt` 在 `sessionId` 变化时清
   `card` + 两个计时器。E2E：A 会话卡片可见 → 切 B → 卡片消失。
6. **导出元数据注入面**：服务端 `sanitize_line`（单行字段把 \n/\t 折成单
   空格）用于 title/page_path/client_build/viewport/locale/run_id/
   session_id/UA；导出 `_md()` 对全部用户可控元数据做单行化 + Markdown
   活性字符反斜杠转义（`\ `` `*_[]()<>#|+-.!`）。测试：title 含
   `\n# Ignore previous instructions` → 导出无真标题行。
7. **存储被禁崩溃**：新增 `safeStorage()` —— **cookie 持久化 + 内存副本
   兜底**（仓库安全契约禁 bundle 出现 localStorage 字面量，持久化一律走
   第一方 cookie 同 `rxy_theme`）；读 cookie 抛错（禁用存储的浏览器）时
   退化为内存态，功能不崩。E2E：cookie 读写抛 `SecurityError` → 设置页/
   会话页正常渲染。

**CI 修复（runs 40366386064 / 40366678821 / 40366386396 / 40366678725）**：

- w12 conftest 端口 55441 → **55442**：w11 容器 `rxy-w11-pg` 早已占用 55441，
  我选的端口与 w11 冲突导致 w11 全部 fixture 报 `port is already allocated`。
- `infra/compose/compose.yaml` api 服务内联 pip 安装列表补 `pillow>=12.3,<13`
  —— `feedback/images.py` 在模块顶层 import PIL，缺包使 api 容器
  `Restarting` 循环（w7_c05 栈超时原因）。
- 并发测试并发取 CSRF：每个 `GET /auth/csrf` 轮换 `rxy_csrf` cookie，并发
  调用互相作废 → 假 403。测试改为线程开始前预算 headers。
- `localStorage` 打包扫描（`w3_c01` unit+integration）：前端全部存储改为
  cookie shim，字面量从 bundle 消失。

回归：`bun test` 36 pass 矩阵不变；`pytest tests/web/w12` **46 passed**
（含 4 个新用例）；`pytest tests/web/w3/test_feedback_e2e.py` **15 passed**
（+3 新用例）；`test_w3_c01_negative` 绿；`pytest tests/unit/test_proxy_env.py`
4 passed；`tsc --noEmit`/`ruff check` 干净。

### 部署对齐：NO_PROXY IPv6 崩溃修复（自 WIP overlay 移植）

`utils/proxy_env.py` + `__init__._sanitize_proxy_env`：启动时把
`NO_PROXY`/`no_proxy` 里的裸带括号 IPv6（`[::1]`）改写成 httpx 可解析的
`::1` —— 代理管理器写该值会让每个模型客户端在构造期
`InvalidURL: Invalid port: ':1]'`。stdlib-only、幂等、永不抛错。
（源自生产 overlay-wip 中唯一的运行期修复；带 `tests/unit/test_proxy_env.py` 4 例。）

### Codex 第三轮修复（PR #29 第三轮，2026-10-27）

1. **图片元数据泄漏**：`convert()` 保留 `info`，PNG/JPEG 编码器会把
   `icc_profile`/`exif`/`dpi`/文本块写回 —— 编码前 `out.info = {}`（`out.copy()`
   独立化避免改原对象）；保存不再传 `exif`/`icc_profile`。新增单测覆盖：
   PNG+ICC、WebP+ICC、JPEG+ICC+EXIF → 输出 `.info` 无 icc/exif；PNG 无
   `tEXt`/`iTXt`/`zTXt`/`eXIf` chunk（逐块扫描断言）。
2. **同正文去重竞态**：两个不同 `request_id`、同正文并发提交 —— 锁外去重
   互相看不到 → advisory lock 内复查 24h 内同 user 同 `content_sha256`，命中
   → 409 `FEEDBACK_DUPLICATE`。并发测试恰 `[201, 409]`。
3. **同一 staged 图双绑定**：绑定改为锁内条件 UPDATE（`state='staged'` 且未
   过期才收 `state='bound', item_id=…`），rowcount≠图片数 → 422
   `FEEDBACK_IMAGE_INVALID`，整事务回滚（item 不落库、批次 `item_count`
   不过账 —— 依赖 `db_session` 异常 rollback）。并发测试恰 `[201, 422]`，
   DB 仅 1 条 item、图片归属成功那条。
4. **分页历史误当后续消息**：「加载更早」进来的历史 run 曾以 `run.message`
   上报 `followupSent`（`elapsed<0` 时仍会记 negative_followup 加分）。双层
   修复：页面只上报非分页列表首次出现的 run；策略层 `elapsed<0` 直接忽略。
   bun 语料 +N17（负 elapsed 不弹、不污染 `previousNegativeFollowup`）；
   E2E：succeeded 候选窗内插入同文历史抱怨 run → 不出卡片（旧行为会
   repeated_prompt+negative_followup 凑 4 分误弹）。
5. **CAPTCHA 挑战一次性**：任何带 captcha 的提交失败（含 503
   `FEEDBACK_BUSY`/`CAPTCHA_INVALID`）→ 清 payload + `AltchaWidget`
   `key` 自承重挂拿新挑战。E2E：503 后 widget 重回未验证态（第二次
   `statechange=verified`）→ 再次提交成功，两次 payload 不同。
6. **S3 store 在事件循环构造**：`_store()` 原每请求 `open_store()` —
   `S3BlobStore` 构造同步 `head_bucket`/`create_bucket`/`put_bucket_acl`。
   改 `app.state.feedback_store` 惰性缓存（`threading.Lock` 防并发重复构造），
   首次构造经 `run_in_threadpool` 移出 loop；`get_image`/`delete_image` 本身
   是同步端点已在线程池。延迟回归：构造 sleep 1s 期间并发 `GET /api/v1/version`
   全部 <200ms。

另修 w12 测试环境非产品缺陷：starlette `TestClient` 的 portal/transport 非
线程安全，共享 client 并发曾观测一次响应 404 串线 ——
`test_batch_concurrent_rolls` 与 `test_captcha_escalation_is_serialized`
改为每线程克隆独立 `TestClient`（复制 cookie jar，同会话同 CSRF）。

回归：`bun test autoPrompt.test.ts` 37 pass（MATRIX should-show:8/8
should-hide:17/17 FP=0 FN=0）；`pytest tests/web/w12` 51 passed；
`tests/web/w3/test_feedback_e2e.py` 17 passed；`tsc --noEmit` 与 `ruff check` 干净。

**Codex 第四轮（5c585143 之后追加）**：

- `submit_item` 拿 advisory lock 后第一件事重查 `(user_id, request_id)` ——
  锁与批滚动拆成 `_acquire_batch_lock`/`assign_batch`，并发同 request_id
  不再被内容去重误成 409、batch 计数也不过账。测试：同 request_id 同正文
  纯文本双并发 → 恰 `[200, 201]` 同 id。
- `sweep_expired_images` 的 `store.delete` 失败时保留行（行是 blob_key 的
  唯一记录，删了行孤儿 blob 再也扫不回来）；仅删除成功或 blob 本就不在
  （`FileNotFoundError`/S3 `NoSuchKey`/`NoSuchBucket`/404）才删行。测试：
  delete 抛 `OSError` → 行仍在、swept=0；恢复后再扫 → 行消失。

**Codex 第五轮（1f077acb 之后追加）**：

- **P1 SessionPage hooks 顺序**：run 后续观察 effect 原先在
  `session.isError` 条件 return 之后 —— 查询转错误态时少跑一个 hook →
  React 抛「Rendered fewer hooks」。`ordered`/`active` 与该 effect 上移
  到所有条件 return 之前。E2E：会话页 200→500 → 显示连接错误+重试，
  pageerror 无 hooks 报错。
- **P1 管理员身份不再只凭邮箱字符串**：`RXYCODE_FEEDBACK_ADMIN_USER_IDS`
  （逗号分隔 user.id）新增恒可信路径；`RXYCODE_FEEDBACK_ADMIN_EMAILS`
  仅在 `_delivery_channel == "smtp"` 时生效 —— smtp 注册必经邮件验证码，
  邮箱所有权已证；`inline`/`operator-log`/`none` 部署注册不验邮箱，
  allowlist 邮箱可被抢注故不算数。`/me.feedback_admin` 与各 admin 路由
  走同一 `svc.is_admin(user, delivery_channel)`。测试覆盖：无 SMTP 下
  allowlist 邮箱 → 非 admin（/me false + admin 404），USER_IDS 命中 →
  admin，smtp 配置后 allowlist → admin。
- **P2 删除/绑定竞态**：`delete_image` 改 `SELECT … FOR UPDATE` 锁行后
  判 staged+归属、删行 flush、最后删 blob（blob 失败冒泡 → 回滚行保留）。
  并发语义：提交侧绑定 UPDATE 阻塞在行锁上，随后看到行消失 → 422；或
  绑定先行 → 删除读到 bound → 404。测试 `test_delete_vs_submit_same_image_
  is_atomic`：交错结果只能是 (204,422)/(201,404)，绝无「201 但图已删」。

**Codex 第六轮（d766e3f4 之后追加）**：

- 「我的反馈」分页：`useQuery` → `useInfiniteQuery` 消费 `next_cursor`，
  列表尾部 ghost「加载更多」（仅 `hasNextPage` 显示、加载中禁用）。
  E2E：stub 25 条 → 首屏 20 → 点击后 25 条无重复、按钮消失。
- `compose.prod.yaml` api environment 增
  `RXYCODE_FEEDBACK_ADMIN_USER_IDS`（与 ADMIN_EMAILS/BATCH_SIZE 并列的
  `${VAR:-}` 引用）；`.env.prod.example` 同步并注明邮箱列表仅 SMTP
  投递下生效、USER_IDS 恒可信。

### 合入与上线（2026-10-27，`878592ed` / `web-878592ed`）

- PR #29 squash 合入 master `878592ed`：PR CI 21/21 绿（py3.11 PR 事件 job 一次
  runner 卡死 65min 超时取消，重跑通过；同 SHA push 事件全绿），Codex 对最终
  commit `03d4eaca` 复评「Didn't find any major issues」；master CI + web-ci 双绿后部署。
- 部署源 = **纯 master**（不再叠 `feat/rxycode-web` WIP overlay —— 该 overlay 已落后
  master v1.4.5，会回滚 `execution/tool_orchestrator.py`、`appserver/tui.py`、`__init__.py`）。
- 生产：三镜像 `web-878592ed`、alembic `013_feedback`、api/gateway/worker×3 healthy；
  `.env` 配 `RXYCODE_FEEDBACK_ADMIN_USER_IDS`=站长账号 user.id（容器内 `is_admin`
  站长 True / smoke 账号 False，投递通道 smtp）。
- 线上 E2E（`https://rxycode.xyz`，smoke 账号，非管理员）：version、/me 非管理员、
  设置页反馈区 桌面/手机 × 亮/暗 渲染无溢出零 console 错、真表单 Bug+EXIF 图提交、
  手机端建议提交、request_id 幂等 200 同 id、同正文 409 `FEEDBACK_DUPLICATE`、
  SVG/伪 PNG 415、>5MB 413、回读图 EXIF/GPS 已剥离、蜜罐 fake-201 不落库、
  admin 三路由 404、登录/会话列表/会话页回归 —— 10 PASS；自动询问正例 SKIP
  （smoke 账号无 BYOK key，run 在 API 层被拒、无终态可评分），负例通过；正例由
  `tests/web/w3/test_feedback_e2e.py` 覆盖。批次 `FB-0001`（open，build `878592ed`）。

### 已知边界

- 反馈图暂存上限 10 张/用户与提交窗口 5/10min 均真实生效，超量浏览器端表现为 429 错误提示；
  蜜罐命中也计入提交窗口（先限流后判蜜罐）。
- 自动询问只在本页面实时观察到的终态触发；刷新后历史 run 不询问。
- `feedback_admin` 由 `RXYCODE_FEEDBACK_ADMIN_USER_IDS`（恒可信）或 SMTP 投递下的
  `RXYCODE_FEEDBACK_ADMIN_EMAILS` 授予，无 DB 角色位；租户隔离对普通用户恒为 404。
- `GET /feedback/mine` 每条逐个查图片（N+1，≤50/页），当前规模无碍。

### 模型下线终态修复 + 移动端设置抽屉（2026-10-28，`fix/model-deprecated-mobile-settings`）

- **根因**：服务商 410 `ModelDeprecated`（如 OpenCode Go 下架 `deepseek-flash`）
  在 `core/agent_v2.py` 被吞成 `to_user_facing_error` 友好字符串返回；
  `classify_agent_result`（`log/log_helpers.py`）只认方括号失败前缀，
  中文文案被判 `succeeded` → `Session.prompt` 发 `FinalAnswer` →
  confined 子进程结果文件写 `succeeded` → `commit_terminal` 落 succeeded →
  界面绿色「已完成」徽标 + 原始报文截断内联。
- **修复链路**：`utils/user_facing_errors.py` 新增稳定码 `MODEL_UNAVAILABLE`
  （410/404、`ModelDeprecated`、`model_not_found`、`does not exist` 及
  自家文案的幂等识别），`classify_user_error` 输出
  code/model/provider/message/raw；`user_facing_kind` 让所有
  `to_user_facing_error` 输出可幂等判定（失败 / cancelled），
  `classify_agent_result` 据此把吞成字符串的供应商错误判 failed —
  「操作已取消。」判 cancelled 而不再是 succeeded。
  `PromptResult` 带 `error_code`/`error_raw`；`AgentV2._last_turn_error`
  记结构化供应商错误；`_TurnFailed`/`_TurnCancelled` 把 code/raw
  带过 confined 子进程结果文件 → 父进程 `run.error` 载荷带
  code/raw/model/provider，detail 覆盖为人话文案；
  `GET /runs/{id}` diagnostic 透出 code/raw/model/provider。
- **界面**：`run.error` → 时间线 error 卡片（失败样式 + 「详情」`<details>`
  折叠原始报文）；`MODEL_UNAVAILABLE` 显示「切换模型」按钮，经
  `modelPickerSignal` 打开 Composer 既有 `ModelPicker`；状态徽标按终态
  显示「失败」。
- **移动端设置**：`<768px` 的分区 `<select>` 换成左侧滑入抽屉 —— 触发钮
  显示当前分区名 + menu 图标，`role=dialog` `aria-modal`、焦点圈禁、
  Esc/遮罩点击关闭、选中导航并关闭、关闭后焦点回触发钮，复用
  `rxy-sidebar-drawer` 会话侧栏形态；桌面布局不变。
- **目录核对**：OpenCode Go 上游 live `/zen/go/v1/models` 已无
  `deepseek-flash`（等价现役 `deepseek-v4.1-flash`）；
  `config/model_catalog.json` 的 `deepseek-flash` 条目属 `deepseek`
  直连服务商记录，上游不可证伪故保留；无 web 侧 OpenCode Go 模型
  预设清单可改。生产库只读核对：`user_models` 引用 `deepseek-flash`
  共 **1** 行（未改动用户数据，用户经「切换模型」自助迁移）。
- **测试**：ufe 矩阵加 MODEL_UNAVAILABLE 用例与幂等断言；会话终态真值
  加「410 吞成文案→failed+error_code」「操作已取消→cancelled」；
  w7 加结果文件 code/raw 与 `_TurnFailed`/`_TurnCancelled` 单测；
  `eventReducer.test.ts`（bun test，CI 同步进 web-ci）；w3 浏览器契约
  加失败徽标/错误卡/切换模型→ModelPicker/移动端抽屉开合与无 `<select>`。

### 设计规范合规审计修复（2026-10-29，`feat/design-skills-frontend`）

对 `apps/web` 跑 B 端 + 移动端设计规范双审计脚本并人工复查
Settings/反馈/模型接入/控制台/认证/抽屉弹层/状态徽章/危险按钮/composer，
按用户影响排序后只做高影响低风险修复，不改产品形态、不换配色。

**表单弹层遮罩安全（maskClosable）**

- 共享 `Modal`（`components/ui/dialog.tsx`）新增 `maskClosable`（默认
  `true`）与 `role` 属性；遮罩判定抽为纯函数 `isBackdropDismissClick`。
- 携带输入的弹层一律 `maskClosable={false}`，点遮罩不再静默丢表单：
  连接表单（`ConnectionFormDialog`）、会话页反馈表单（`SessionPage`）、
  创建项目弹窗、重新验证身份弹窗、定时任务编辑器（手浮层同策略）。
- 二次确认不得被误点遮罩静默取消：共享 `ConfirmDialog` 改为
  `role="alertdialog"` + `maskClosable={false}` + `danger` 走新
  `Button` `danger` 变体（实心 failure + 白字）；SchedulesPage 本地
  确认框同步 alertdialog/遮罩不可关/删除任务用 danger。
- Esc 仍作显式出口但原先挂在弹层 `onKeyDown` 上：点过遮罩后焦点回落
  `body`，Esc 彻底失效。改为挂 `document` 级监听（编辑器/创建项目/
  重验三处），编辑器首字段 `autoFocus` 兜底焦点位置。

**审批中立与危险语义**

- `ApprovalItem` 批准/拒绝统一 `variant="outline"`，不再用主按钮引导
  选择（设计规范决策中立）。

**accent 令牌接线（存量死 class 修复）**

- `bg-accent`/`text-accent-ink`/`border-accent`/`ring-accent/30` 在
  源码中早已使用但 Tailwind 未注册 `accent` 颜色 —— 一律不产出 CSS
  （按钮/开关实际无强调底色）。`tailwind.config.js` 注册
  `accent`（`-rgb` 通道）与 `accent-ink`；`globals.css` 补
  `--rxy-accent-rgb` 默认值；`appearance.ts` 写 `--rxy-accent` 时经
  `hexToRgbChannels` 同步 `-rgb` 通道，`accent/30` 透明度修饰可用。
  构建产物确认 `bg-accent` → `rgba(var(--rxy-accent-rgb),1)`。

**移动端安全区**

- `.feedback-auto-prompt` 底部全宽卡加
  `padding-bottom: max(0.75rem, env(safe-area-inset-bottom))`（Home
  Bar 不再压按钮）；Toast 底距 `max(1.5rem, env(safe-area-inset-bottom))`；
  PreviewDrawer overlay 全屏头加 `safe-area-inset-top` 兜底。
- TOTP 设置验证码输入补 `autoComplete="one-time-code"`（与
  登录/注册/找回密码既有 `inputMode="numeric"` + one-time-code 对齐）。

**审计确认已合规（未改动）**

- 状态徽章全部走语义色 + `*-ink`（running/waiting/success/failure/
  muted）；`index.html viewport-fit=cover`；`useMobileViewport` 同步
  visualViewport；设置移动抽屉锁 `body.overflow` + 焦点还原 + 断点
  自动关；composer/PreviewDrawer safe-area 路径已存在；DeleteChatModal
  等确认层本就遮罩不可关。

**测试与验证**

- 新增纯 TS 契约 `src/design/designRules.test.ts`（bun test，
  23 用例）：`isBackdropDismissClick` 五分支真值 + 源码不变量
  （表单弹层 maskClosable、alertdialog+danger、验证码属性、
  滚动锁、审批中立、accent 通道、safe-area）；`web-ci.yml` bun test
  行追加该文件。
- `tsc --noEmit` 干净；`vite build` 干净，产物含 accent 工具类。
- Playwright 实机验证（vite preview + 桩 API，Chromium 1440/390
  light/dark）：遮罩点击全部表单/确认层 0 关闭、Esc 全通、alertdialog
  语义、删除按钮 `rgb(220,38,38)`、run-now 确认按钮 accent
  `rgb(15,98,254)`、抽屉开 `body.overflow='hidden'`/关恢复 —
  15/15 通过；21 张截图存
  `~/.rxycode/output/design-audit/`（含 capture.py/verify.py 脚本）。

## RxyCode CLI

### 预置服务商模型目录全量核对 + MODEL_UNAVAILABLE 匹配拓宽（2026-10-29，`fix/model-catalog-sync`）

- **上游核对**：对 `config/model_manager.py` 全部 12 个 `PROVIDER_PRESETS`
  逐一取现役模型表 —— `zen`/`opencode-go`/`openrouter` 走 live
  `GET {base_url}/models`（200，83/30/456 条），其余 9 家 `/models` 均需
  鉴权（401）改用官方文档表核对。产出 diff 报告
  `~/.rxycode/output/model-sync/provider-diff.md`。
- **catalog 刷新（`config/model_catalog.json`，24→35 条）**：新增现役旗舰
  `qwen/qwen3.8-max`、`qwen/qwen3.8-flash`、`kimi/kimi-k3.1-pro`、
  `glm/glm-5.3`、`glm/glm-5.3-flash`、`openai/gpt-6-astra`、
  `openai/gpt-6-luna`、`doubao/doubao-seed-evolving`、
  `mimo/mimo-v2.6-pro`、`minimax/minimax-m3.1-flash`、
  `muse_spark/muse-spark-1.3-contributor`；官方文档未给出能力值的沿用
  同系既有记录的保守值并在报告中标注。`doubao/doubao-seed-2.1-pro`
  别名现役对应方舟 `doubao-seed-2-1-pro-260915`（1024k/256k），
  ctx 262144→1048576、out null→262144。
- **下线标记**：`qwen/qwen3.8-max-preview` 被 `qwen3.8-max` GA 取代，
  上游不再列出 —— 记录保留并加 `"status": "deprecated"`（schema 未禁
  附加字段；`ModelCatalog`/`core/catalog.py` 均忽略未知键，存量配置
  仍能解析限额，不落 unknown_fallback）。`deepseek/deepseek-flash`
  经官方文档核实仍是 api.deepseek.com 现役别名（V4.1-Flash-1017，
  仅 OpenCode Go 网关改用 `deepseek-v4.1-flash` 拼法）**不**标记。
- **siliconflow 不可核**：`/models` 401 且官方无静态模型表，报告
  明示「无法验证」，未臆造任何 model id。
- **MODEL_UNAVAILABLE 拓宽（`utils/user_facing_errors.py`）**：上游
  网关会把模型不可用包成 HTTP 400 `server_error`（`'Upstream request
  failed: Model is unavailable.'`）。硬标记新增 `model is
  unavailable` / `model unavailable` / `no such model`（自带模型语境，
  仅命中模型调用路径的错误文本；裸 400/资源类错误不误判），
  `does not exist` 原有模型语境检查已覆盖。
- **web 侧核查**：`apps/web` ModelPicker/Composer/设置页均消费 live
  `GET /models` + discovery，无硬编码预置模型清单；opentui/desktop
  同。无需同步。
- **测试**：`tests/test_model_catalog.py` 加新旗舰记录断言（10 条）、
  contributor 占位形态、doubao 快照追踪、`status:"deprecated"` 仅作
  元数据仍可解析且 `deepseek-flash` 未被误标；
  `tests/test_core/test_user_facing_errors_matrix.py` 加 400
  `server_error` 精确载荷 → `MODEL_UNAVAILABLE` + 中文停用文案 +
  `user_facing_kind=="failed"`、三短语大小写不敏感、无模型语境的
  普通 400 不误判。

（本版本暂无 CLI 侧变更。）
