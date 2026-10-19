# Post-W7-C01 后续轨 B + C 实施记录（2026-10-19）

依据卡面裁定（嵌套 PHASE-W7 表 C01 行，commit 112dd24）：「W7-C02 到 C06
完成后，先做 B，再做 C」。两条轨均已落地并通过测试。

## B：写路径闸拦截的 bash → 普通模式转人工审批

- `execution/tool_orchestrator.py` §2 bash 闸门：`blocked_paths` 命中时
  读运行时权限模式（`_permission_mode_override` ContextVar →
  `safety.permission_mode` → 默认 confirm_all）。`full`/`full_auto`
  保持拦下即拒、不弹审批；其余模式把 `gate_blocked_paths` 记下来，
  继续走 §4 审批链。
- §4 中 `explicit_command`/`auto_approve` 两条捷径对闸门升级的请求
  显式失效（`and not gate_blocked_paths`）——闸门不能被自动批准级别
  旁路。
- `core/safety/approval.py`：`ApprovalRequest.gate_blocked_paths` 字段
  （`to_event` 输出供审批界面点名写目标）；`request_approval` 对
  gate-escalated 请求跳过 always-allow 缓存的读和写——否则一次
  always_allow 会永久绕过写路径闸。
- 批准后执行仍过 `_invoke_and_finish` → 正常走 `os_sandbox` 内核沙箱。
- 测试（`tests/test_safety_gate.py::TestBashGateEscalation`，44/44 绿）：
  confirm_all/auto_edit 下出审批事件且携带 `gate_blocked_paths`；
  批准→执行、拒绝→不执行；full_auto → `[blocked]` 且零审批事件；
  always_allow_level 不落缓存。

## C：三平台 OS 沙箱按权限模式自动开关 + Windows 内核写隔离

- `core/sandbox/policy.py::from_config`：`execution.os_sandbox.enabled`
  未显式配置时按权限模式推断（full/full_auto → False，其余 → True）；
  显式 enabled 优先。
- `utils/shell.py::_wrap_os_sandbox`：运行时权限模式取
  `_permission_mode_override`（ContextVar，per-request）→ config
  `safety.permission_mode`。Full 下不包 argv、不建 os Job；reaping
  Job（kill-on-close 回收）与急停路径在 `wrapped_cmd is None` 分支
  照常生效。
- `core/sandbox/windows.py`：
  - `ensure_appcontainer(name)`：`CreateAppContainerProfile` +
    `DeriveAppContainerSidFromAppContainerName`（失败显式抛）。
  - `spawn_appcontainer_sync`：`PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`
    让子进程以能力 SID 出生（免特权）；Low IL 经 AppContainer 语义。
  - `spawn_low_il_sync`：`PROC_THREAD_ATTRIBUTE_MANDATORY_LABEL` 兜底
    （宿主不支持 MANDATORY_LABEL 时抛）。
  - `plan_windows_command`：workspace 模式 argv →
    `python <repo>/core/sandbox/tokenlaunch.py --workspace <root>
    [--write <dir>] --cwd <dir> -- <argv>`；JobPlan（限额 +
    kill-on-close）照旧绑启动器 root，子孙经 Job 继承。
  - `unenforced_constraints`：workspace 写隔离与 network=none 由
    AppContainer 落实（能力 SID 写域 + 无网络能力）；`deny_read_globs`
    仍如实列为未落实。
- `core/sandbox/tokenlaunch.py`（新）：写域授权（能力 SID F + Low IL
  标级）→ 读域授权（解释器/venv 目录 RX：`pyvenv.cfg` → `home=` base
  + `Lib`/`DLLs` 递归；跨进程 marker 缓存，伪造方向只会失败闭合）→
  AppContainer spawn → stdio 转发 → 透传退出码。stdio 句柄经
  STARTF_USESTDHANDLES 原样转交，启动器不泵数据。
- 真机验证：AppContainer 子进程 `whoami /groups` 含
  `Mandatory Label\Low Mandatory Level S-1-16-4096`；写工作区文件
  成功，写 `C:\Users\Administrator` 报「拒绝访问」；venv python 在
  沙箱内 `import json/tempfile` 正常（TEMP 由 AppContainer 重定向到
  `Packages\RxyCode.Sandbox\AC\Temp`）。
- 测试：`tests/test_core/test_sandbox_windows.py` 25/25 绿（含
  `test_tokenlaunch_appcontainer_write_isolation` 真 spawn 负测 +
  `test_from_config_auto_toggle_by_permission_mode` 开关矩阵 +
  `test_venv_python_through_production_shell` 生产 shell e2e）；
  `tests/test_core/test_shell_sandbox_resources.py` 13/13 绿
  （4 条资源测试显式固定 `os_sandbox.enabled=False` 保持被测面）。
- 已知限制：AppContainer 配置文件名为固定 `RxyCode.Sandbox`（能力 SID
  稳定可复用）；读域授权只覆盖解释器/工具目录，任意路径的可执行文件
  若 ACL 不含 All Application Packages 会读不到——按失败闭合处理。

## 未做（边界）

- Full 模式下 reaping Job 仍回收整棵树，但不提供文件/网络/读路径隔离
  ——与裁定一致（Full = 用户确认后解除权限隔离，保留回收/急停）。
- `deny_read_globs` 在 Windows 仍落空并如实报告。
