# core/sandbox/ — OS 级沙箱（v1.4.1，仿 Codex）

## 这是什么

把「LLM 输出（不可信输入）决定执行的命令」关进**内核强制**的受限执行面。
仿 Codex 的三平台路线：**Windows = Job Object + 受限令牌原语、
Linux = bubblewrap、macOS = Seatbelt**。与既有软件层闸门
（`core/safety/policy.py` 审批 + 写白名单）叠加，不替代。

## 执行面与边界（v1.4.1 诚实口径）

- **生效点**：`utils/shell.py` 的 bash 子进程 spawn 前后
  （`wrap_command` 包装 argv → **出生即绑定**：`open_sandbox_job` 建空 Job
  → `CREATE_SUSPENDED` 创建 → `bind_spawned_process` 指派 root + 恢复主线程，
  2026-10-07 起替代 spawn 后整树指派）。`execution.os_sandbox.enabled`
  默认 **false**（烧熟后评估默认开）。
- **docker 模式不叠加**（docker 自带 OS 边界）。
- **不覆盖**：write/edit/patch 文件工具（仍由写白名单管）、MCP stdio server、
  Playwright 浏览器、Desktop GUI 子进程（后续登记项）。
- **Windows 低完整性是尽力而为能力**：`PROC_THREAD_ATTRIBUTE_MANDATORY_LABEL`
  部分宿主（服务器 SKU/策略限制）返回 `ERROR_NOT_SUPPORTED`；
  `CreateProcessWithTokenW` 受限 spawn 在未提权宿主可能
  `ERROR_ACCESS_DENIED`。两者都走显式降级（响亮 log / SandboxUnavailableError），
  **绝不静默 unsandbox**。本机（Windows Server 类宿主）实测属后者——
  因此 Windows v1 的可信强制 = **Job Object**（限额 + kill-on-close 已实测）。
- **Windows Job-only 形态落实不了 mode/network/deny_read_globs**
  （2026-10-07 审计修）：`plan_windows_command` 经 `unenforced_constraints()`
  如实列出落空约束——`fail_closed` 抛 `SandboxUnavailableError` **拒绝执行**；
  `downgrade` 响亮 `logger.warning` + `downgraded=True` + detail 列明（Job 限额 +
  kill-on-close 仍真实生效）。Job Object 管进程与资源，**不等于**文件/网络
  安全隔离；Codex 的 deny-SID/能力 SID 层留 v1.4.2 接缝。
- **macOS `network=inherit` 显式放行**（2026-10-07 审计修）：`(deny default)`
  基座下省略 deny ≠ 放行，profile 对 inherit 显式 `(allow network*)`；
  none 仍显式 `(deny network*)`。Windows 实机验证过 Seatbelt 规则生成，
  macOS 真机联网行为以规则文本断言为准（本机无 mac）。

## 核心文件

| 文件 | 职责 |
|---|---|
| `policy.py` | `SandboxPolicy`（enabled/mode/workspace_root/network/deny_read_globs/限额/on_missing_capability）+ `from_config`（唯一 config 入口，`execution.os_sandbox.*`） |
| `detect.py` | `detect_capabilities` 只读探测（不 spawn）：job+token / bwrap / seatbelt / none |
| `types.py` | `JobPlan` / `WrappedCommand` 数据类（2026-10-06 独立成模块：消除 manager ↔ 后端循环导入，换回 linux/macos 顶部导入以守 P7 懒导入预算 181） |
| `manager.py` | `wrap_command`（后端选择 + argv 包装 + fail-closed/显式降级）+ `open_sandbox_job`/`bind_spawned_process`（出生即绑定，生产接口）；`apply_post_spawn` 为后补整树指派，已标注废弃仅兼容保留。linux/macos 构建器顶部导入（纯 stdlib）；windows 经 `_windows()` 单点函数内懒导入（import 期绑 `windll`，P7 预算纪律） |
| `windows.py` | Job Object（`CreateJobObjectW` + 限额 + `KILL_ON_JOB_CLOSE`）+ `resume_process_main_thread`（Toolhelp 线程快照恢复 suspended 主线程）+ 受限令牌原语（`spawn_restricted_sync`，宿主不支持时显式降级）；`assign_job_to_tree` 后补枚举仅兼容场景（不能跨越 venv launcher 等自建 Job） |
| `linux.py` | bwrap argv 构建（`--ro-bind / /` + workspace 可写 + `--unshare-net` + deny globs 遮蔽） |
| `macos.py` | Seatbelt .sb profile 构建 + `sandbox-exec -f` 包装 |

## 关键语义（实测踩过的坑，禁止回退）

1. **出生即绑定是唯一的生产形态**（2026-10-07 验收缺陷修）：spawn 前
   `open_sandbox_job` 建空 Job → `CREATE_SUSPENDED` 创建 →
   `bind_spawned_process`（指派 root + `resume_process_main_thread`
   恢复主线程）。suspended 窗口内 root 一行代码未跑、不可能有子孙，
   竞态根除；子孙随 Job 继承自动入列。废弃的后补整树枚举
   （`assign_job_to_tree`）有两个致命缺陷：晚半秒指派漏杀先发子孙；对
   自建 Job 的程序（CPython 3.13 venv launcher 把解释器放进自己的 Job）
   是跨 Job 层级重归属 → `AssignProcessToJobObject` ERROR_ACCESS_DENIED
   （GetLastError=5）——仅兼容场景保留，禁止生产调用。
2. **ctypes 必须显式声明 argtypes/restype**——64 位 HANDLE 默认 c_int 截断会
   产出 `ERROR_INVALID_HANDLE`。
3. **降级必须显式**：能力缺失 → `on_missing_capability=fail_closed` 抛
   `SandboxUnavailableError`；`downgrade` 则响亮 log + `downgraded=True`。
   **策略落空同理**：后端满足不了的约束（Windows 的 mode/network/deny globs）
   必须 fail_closed 拒绝或 downgraded 标记，绝不 `applied=True` 装无事。
4. **TOKEN_GROUPS 解析基址 = 8（count 4B + padding 4B）、步长 = 16**
   （x64 对齐）——基址错一位整列解析失败。
5. **Win32 返值不可裸真值判定**：`ResumeThread` 失败返回 `0xFFFFFFFF`
   （DWORD），Python 里是真值——`if not ResumeThread(...)` 会把失败当成功。
   一切 DWORD 返值必须与失败常量显式比较（2026-10-07 审计修）。
6. **发版件必须与包清单对账**：`pyproject.toml` 显式 packages 漏
   `core.sandbox` 时，installed 包连 disabled 都会在 shell 导入点
   `ModuleNotFoundError`。`tests/system/test_installed_package.py` 的
   wheel 断言 + venv smoke 是发版前必跑面。Windows 跑它另有一条
   MAX_PATH 纪律：uv 把 sdist 解到 `UV_CACHE_DIR` 下构建 wheel，包内
   最深资源路径 ~190 字符 + pytest basetemp ~100 字符会越 260 上限
   （2026-10-07 排障定位），fixture 已把缓存挪到 %TEMP% 浅层短名目录。

## 测试

- `tests/test_core/test_sandbox_windows.py`（9 条真实用例：Job kill-tree 杀树 /
  进程数限额 / 内存限额 / 受限 spawn 能力感知 / 失败面）
- `tests/test_core/test_sandbox_linux.py`（10 条 bwrap argv 纯单测）
- `tests/test_core/test_sandbox_macos.py`（10 条 Seatbelt profile 纯单测）
- 回归：`tests/test_tools` + `tests/contract` 全绿（1866 passed）

## 变更记录

见 `docs/release-notes/CHANGELOG_v1.4.1.md`。
