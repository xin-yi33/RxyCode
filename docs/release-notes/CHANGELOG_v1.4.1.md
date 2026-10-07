# CHANGELOG v1.4.1

> 发布版本：v1.4.1；日期：2026-10-07；上一发布版本：v1.4.0。本文档从开发期开始管理：每次对 agent 的
> 新增/优化/修改都必须当日写入本文件（含原因）；内容被撤回时同步删除对应条目。
> 发版后下一版自动新开 `CHANGELOG_v1.4.2.md`，本文件冻结归档。
> 格式约定：每条 = **模块**（`file:line`）：做了什么 —— **原因**。归类：新增 /
> 变更 / 修复 / 废弃。

## 新增

- **log/rotator.py（72h 时间戳日志保留系统）**（新增 `log/rotator.py`）：日志文件
  按 `rxycode_YYYY-MM-DD_HH-MM-SS_<runid>.log` 命名（时间戳在文件名里，不用 mtime，
  避免拷贝/触摸误删）；`RETENTION_HOURS=72`（`RXYCODE_LOG_RETENTION_HOURS` 可覆盖）；
  `prune_old_logs` 按文件名时间戳升序排序后清理超窗文件；`list_log_files` 每次访问
  先清理再按时间戳排序返回 —— 原因：现有 logger 只有轮转没有保留策略与目录治理。
- **Session 工具回合熔断对齐**（`core/agent_v2.py:5596` set / `:6357` reset）：
  `_fast_reply_with_tools` 持有 `_OUTER_BREAKER_HELD` ContextVar，内层
  `_connect_provider_stream` 检测后跳过重试循环里各自的 `breaker.call` ——
  原因：工具回合不经 ainvoke/astream，标记恒 False，同一轮第 2~7 次传输重试
  各计一次失败，会打满 fail_max=5 误开熔断。
- **core/sandbox/ 全新包（OS 级沙箱，仿 Codex 三平台路线）**——LLM 决定的 bash
  命令此前以宿主用户身份裸跑，只有软件闸与 psutil 轮询软限（50ms 竞态窗），缺内核
  强制层：
  - **Windows**（`core/sandbox/windows.py`）：Job Object 内核限额（内存/进程数）+
    `KILL_ON_JOB_CLOSE` 整树连坐（spawn 前建 Job，`CREATE_SUSPENDED` 后绑定 root，
    恢复线程后子孙继承）；受限令牌原语（`spawn_restricted_sync`，宿主不支持时显式降级
    并如实记录）。
  - **Linux**（`core/sandbox/linux.py`）：bubblewrap argv 包装（`--ro-bind / /`、
    workspace 可写、`--unshare-net`、deny globs 遮蔽）。
  - **macOS**（`core/sandbox/macos.py`）：Seatbelt .sb profile + `sandbox-exec -f`。
  - 能力缺失一律显式降级（响亮 log + `downgraded` 标记）或 fail_closed 抛
    `SandboxUnavailableError`——绝不静默 unsandbox。
- **config 新节 `execution.os_sandbox`**（`config/settings.py:353-366`）：enabled
  （默认 **false**，烧熟后评估默认开）、mode、network、deny_read_globs、限额、
  on_missing_capability（downgrade|fail_closed）。
- **测试**：`tests/test_log/test_log_rotator.py`（7 用例 E2E）、
  `tests/test_core/test_sandbox_windows.py`（22 条真实内核与契约测试：kill-tree/限额/venv/降级）、
  `tests/test_core/test_sandbox_linux.py`（10 条 bwrap 纯单测）、
  `tests/test_core/test_sandbox_macos.py`（10 条 Seatbelt 纯单测）、
  `tests/contract/test_retry_policy_contract.py::test_default_config_routes_to_latest_retry_constant`
  （回归门禁：默认配置不得再覆盖最新重试常量）。
- **模块文档**：`docs/modules/log.md` 更新、`docs/modules/sandbox.md` 新建。

## 变更

- **连接重试 5 → 7 次，延迟翻倍末次 128s**（`recovery/error_recovery.py`）：
  `MODEL_RETRY_MAX=7`、`MODEL_RETRY_MAX_DELAY_SECONDS=128.0`（序列 2→4→8→16→32→
  64→128s，≤25% 抖动）——原因：5 次/30s 封顶对慢网/弱代理恢复窗口太窄。
  同步更新 `evals/baselines/retry-policy.json`（transport_retry_max 5→7）、
  `tests/unit/test_retry_policy.py`、`tests/contract/test_retry_policy_contract.py`、
  `docs/modules/recovery.md`、`docs/modules/config.md`（全部路由到新常量）。
- **utils/shell.py**（`_execute_controlled` + `_wrap_os_sandbox`）：
  Linux/macOS 在 spawn 前包装 argv；Windows 的最终生产路线是
  `open_sandbox_job` → `CREATE_SUSPENDED` → `bind_spawned_process` → resume，
  Job 句柄持有到收尾关闭。此前的 spawn 后整树扫描仍存在竞态和 venv 嵌套问题，
  已不作为生产路线。docker 模式不叠加 os_sandbox。
- **core/sandbox/manager.py**：`apply_post_spawn` 仅兼容保留并标注废弃；
  生产使用出生即绑定接口，见「修复」中的 Windows venv 根因记录。
- **`docs/modules/recovery.md` 错误分类口径更正**：`FirstTokenTimeoutError` 精确类型
  可重试（2026-09-23 起 `_is_transport_retryable` 放行），`StreamIdleTimeoutError`
  恒禁止 —— 原文「fired stream clocks 均不重试」失准。

## 修复

- **`config/settings.py:260` 旧默认 `transport_retries: 5` 静默覆盖新常量**：
  两个访问器（`_transport_retry_max` / `_stream_transient_retry_max`）cfg 优先，
  导致默认安装实际只重试 5 次而非 7 次——已移除该 key，统一路由到
  `MODEL_RETRY_MAX=7`（废弃注释 + 回归门禁测试锁定）。
- **`tests/test_core/test_runtime_wiring.py` 两个退款用例走真退避、撞 180s
  单测超时搞挂整个全量门禁**（2026-10-06 门禁复跑定位）：重试 5→7 后默认
  预算退避和 ≈254s > 180s，pytest-timeout 挂死会话且不留失败摘要。注入
  `llm._transport_retries = 0`（仓库既有惯例 `test_circuit_breaker.py:135`）——
  用例只验收终态异常的限流退款簿记与熔断短路，与重试次数正交。
- **`core/sandbox/` 引入 P7 懒导入预算回归**（182 ≥ 181 上限，预算注释明确
  禁止抬限吸收）：`JobPlan`/`WrappedCommand` 移入新 `types.py` 消除
  manager ↔ 后端循环导入，linux/macos 构建器（纯 stdlib）改顶部导入，
  windows 保持函数内懒导入（import 期绑 `windll`，非 Windows 宿主不可加载）。
  修复后 180 < 181。
- **`pyproject.toml` 漏装 `core.sandbox`（发版阻断，2026-10-07 外部审计）**：
  显式包清单补 `RxyCode.RxyCode1_1_0.core.sandbox` —— 原因：installed 包里
  `utils/shell.py` 的 sandbox 导入在 `enabled=false` 时也会
  `ModuleNotFoundError`（导入先于 enabled 检查）。既有契约测试
  `test_pyproject_includes_every_core_subpackage` 本可复现，但它不在日常门禁集；
  另加显式断言 `test_pyproject_ships_the_sandbox_subpackage`，并扩展
  `tests/system/test_installed_package.py`：wheel 内容断言 +
  venv 安装后 `wrap_command` disabled 探针（不只源码目录测试）。
- **Windows Job-only 形态无视 mode/network/deny_read_globs（2026-10-07 外部审计）**：
  `plan_windows_command` 旧版恒 `applied=True`，`mode=read-only`/`network=none`/
  敏感读遮蔽配了也不生效却看似生效。新增 `unenforced_constraints()` 诚实清单：
  fail_closed 抛 `SandboxUnavailableError` 拒绝执行；downgrade 响亮
  `logger.warning` + `downgraded=True` + detail 列明落空约束（Job 限额 +
  kill-on-close 仍真实生效）。`spawn_restricted_sync` 同样加 fail_closed 前置
  拒绝 —— 原因：Job Object 管进程与资源，不等于文件/网络安全隔离（Codex 的
  deny-SID/能力 SID 层留 v1.4.2 接缝）。
- **macOS `network=inherit` 实际仍默认禁网（2026-10-07 外部审计）**：
  `(deny default)` 基座下 inherit 分支没写 allow，省略 deny 不等于放行——
  profile 现对 inherit 显式追加 `(allow network*)`（none 仍显式
  `(deny network*)`），单测补 allow 断言。
- **`ResumeThread` 失败会被当成成功（2026-10-07 外部审计）**：失败返值
  `0xFFFFFFFF`（DWORD）在 Python 是真值，旧 `if not ResumeThread(...)` 判定
  反向——改为显式 `== 0xFFFFFFFF` 比较。该路径（`spawn_restricted_sync`）
  v1.4.1 未接主链，属防御性修复，mock 全 Win32 面的回归测试锁定。
- **`tests/system/test_installed_package.py` 在 Windows 深 tmp 下假失败
  （测试基建，2026-10-07 排障）**：uv 构建 wheel 会把 sdist 解到
  `UV_CACHE_DIR` 下，包内最深资源路径 ~190 字符 + pytest basetemp ~100
  字符越 Windows 260 上限——最长的 `core/agents/teams/.../skills/
  planning-and-task-breakdown.md` 复制报 ENOENT（同环境手动构建全过，
  定位过程排除包内容与陈旧 `build/` 残留）。fixture 改用 `%TEMP%` 浅层
  短名缓存目录并归入 finally 清理。
- **Windows Job 沙箱跑 venv Python 必败（GetLastError=5，2026-10-07 真实
  验收缺陷 A）**：CPython 3.13 的 venv launcher 自建 Job 并把真解释器放进
  去——「spawn 后补整树指派」对它等于跨 Job 层级重归属，
  `AssignProcessToJobObject` 恒 ERROR_ACCESS_DENIED。执行面改为**出生即
  绑定**：`open_sandbox_job`（spawn 前建空 Job）→ `CREATE_SUSPENDED`
  创建子进程 → `bind_spawned_process`（指派 root + 新增
  `resume_process_main_thread` 经 Toolhelp 线程快照恢复主线程——asyncio
  的 Popen 拿不到线程句柄）。suspended 窗口内 root 一行代码未跑、不可能
  有子孙，竞态根除；子孙随 Job 继承自动入列，venv launcher 等自建 Job
  合法嵌套于我方 Job 之下（验收的嵌套冲突场景转为合法拓扑）。绑定失败
  fail-closed：`sandbox_error` + 清理 suspended root（root 从未运行，即
  整树回收），不吞 GetLastError、不放行未约束进程。
  `apply_post_spawn`/`assign_job_to_tree` 标注废弃注释（仅兼容保留/晚扫
  原语，生产零调用）；manager 的 backend 懒导入合并为 `_windows()` 单点
  （P7 预算 179 < 181，未抬限）。
- **主链测试 mock 落后于生产 opener（验收 B 项，测试维护）**：
  `tests/integration/test_agent_main_chain.py` 从 `os.startfile` 改 mock
  `_open_on_windows`（Path 入参）——生产 `tools/open_file.py:234` 已优先
  走该边界（subprocess.Popen cmd /c start），startfile 只是内部 fallback。
  保留「确实发起打开」断言，不再误调真实 host opener。
- **6 条测试引用 0 字节 PHASE-UPDATE-01.md（验收 C 项，文档/验收依赖）**：
  gitignored 计划文档缺失或为空时，4 份 docs manifest 与 e2e
  `test_e2e_ss_05` 一致 skip（e2e 原仅判 is_file，扩为空文本同判）——
  不虚构关键词求绿；可分发契约断言应落在协议/实现上。

## 废弃

- **`core/agent_v2.py` `_parse_dsml_tool_calls_legacy`**：~75 行整段注释 + 废弃说明
  （全库零调用方；live 用 `:5904` 的非 legacy 版）。
- **`history/` 包**（`history/__init__.py` + `tracker.py` 头部注释）：生产零引用
  （tools/edit|write 不 import），用户级 Undo 权威是 `session/revert` + 磁盘快照；
  保留注释存档，接线或删除二选一前不再扩散引用。
- **`lsp/` 包**（`lsp/__init__.py` 头部注释）：experimental，全库零 import。
- **`scheduler/manager.py`**（文件头注释）：仅 api_server fallback（Ink）使用，
  live OpenTUI 的 /loop 权威是 `appserver/schedule_service.py`。
- **`recovery/error_recovery.py` / `core/agent_v2.py:1817/3811` / 两个 retry 测试文件**
  顶部：`废弃代码（2026-09-23 版）：MODEL_RETRY_MAX = 5 / 30s 上限` tombstone 注释。

## 兼容性说明

- 日志保留策略默认 72h；`RXYCODE_DATA_DIR` 重定向与既有测试隔离约定兼容。
- 熔断对齐不改变任何对外语义（重试计数语义修正：同一逻辑拉流计一次）。
- 重试 7 次/128s 对默认安装生效（`transport_retries` 本地覆盖键仍有效）。
- **OS 沙箱默认关闭**（`execution.os_sandbox.enabled=false` 时行为与 v1.4.0 逐字节
  一致）；开启后仅影响 bash 子进程执行面；write/edit/patch 仍由写白名单管；MCP /
  Playwright / Desktop GUI 子进程 v1.4.1 未纳入（后续登记项）。
- **平台差异**：Linux 需 bwrap、macOS 需 sandbox-exec、Windows 走内核 Job Object；
  后端不可用且 downgrade 时命令仍执行但不在沙箱内（响亮警告）；fail_closed 时拒绝。
- **Windows 低完整性尽力而为**：`PROC_THREAD_ATTRIBUTE_MANDATORY_LABEL` 在服务器
  SKU/策略受限宿主返回 `ERROR_NOT_SUPPORTED`；`CreateProcessWithTokenW` 受限 spawn
  在未提权宿主 `ERROR_ACCESS_DENIED`——均显式降级如实记录。Windows v1.4.1 可信
  强制层 = **Job Object**（已实测）。

## 验证记录

以下全量计数保留实现阶段的复跑记录；发布验收的新结果单列在发布说明中，
不将历史计数冒充本次独立复测。Linux/macOS 套件验证参数与策略契约，
不代表已经在对应平台完成原生沙箱安全验收。


- 沙箱四套件全绿：Windows **22 条**（真实内核语义：birth-binding 后 venv
  Python 正常执行 / venv 孙进程连坐回收 / ACTIVE_PROCESS 限额仍生效 / 宿主
  已有 Job 探针 / suspended 原语 / bind 失败 fail-closed 从未运行断言；
  另有审计修 fail_closed/downgrade 诚实标记、ResumeThread mock 回归）、
  Linux 10 条、macOS 10 条（inherit 显式 `(allow network*)` 断言）、
  shell 资源 **12 条**（+2 出生即绑定接线 mock：CREATE_SUSPENDED 标志 +
  bind 失败 sandbox_error）。
- 验收 B/C 项套件：`tests/integration/test_agent_main_chain.py`（mock 对齐
  `_open_on_windows` 后通过）、`tests/test_docs` + e2e session catalog：
  **以 6 条 skip 替代验收时的 6 条文档红**（gitignored 计划文档缺失/为空
  即跳过，不虚构内容）。
- 日志套件 `tests/test_log` 7 条全绿；既有日志测试 22 条无回归。
- `tests/test_tools` + `tests/contract`：1866 passed。
- 打包契约 `tests/unit/test_packaging_contract.py`：18 passed（含新
  `test_pyproject_ships_the_sandbox_subpackage`）。
- 安装树系统测试 `tests/system/test_installed_package.py`：**3 passed**
  （uv 真实构建 wheel+sdist、venv 安装冒烟；新增 core.sandbox wheel 内容断言
  与 installed 树 `wrap_command` disabled 探针；顺手修复 Windows MAX_PATH 假
  失败，见「修复」段）。
- 质量门 `tests/test_appserver tests/test_bridge tests/test_cache tests/test_core`：
  **8255 passed / 4 skipped / 0 failed**（1062.60s，2026-10-06 复跑）；
  2026-10-07 审计修后复跑 **8260 passed / 4 skipped / 0 failed**（1045.79s）；
  2026-10-07 验收缺陷修（出生即绑定）后最终复跑 **8270 passed / 4 skipped /
  0 failed**（1123.60s，新增 10 条：沙窗 8 条出生即绑定/venv 真实链路 +
  shell 资源 2 条接线 mock）。
- 层门禁 `tests/integration tests/contract tests/unit tests/test_log
  tests/test_providers`：**1814 passed**（2026-10-07 验收修后，含打开入口
  mock 对齐的 `test_agent_main_chain.py`）。
- `tests/test_tools`：**993 passed**（2026-10-07 验收修后，bash 工具共享
  的 shell.py 生产路径无回归）。
  修复了复跑中定位出的两处本版本引入的门禁阻断（重试真退避挂死会话、
  P7 懒导入预算 182≥181，见「修复」段）后全量通过；历史顺序依赖型 flake
  （stall / credential）两轮均未复现。
- 懒导入预算 `scripts/count_lazy_imports.py`：**180 < 181**（预算注释禁止抬限，
  以 types.py 重构达标；2026-10-07 审计修后复测仍达标）。
- `ruff check`：新增/修改文件全过（含 2026-10-07 审计修的全部文件）。
