"""Windows 沙箱后端真实测试（v1.4.1）。

真实 spawn 本机子进程验证内核语义：Job 限额 / kill-on-close 杀树 /
受限令牌 + Low IL。每个用例 finally 兜底回收，全部有界（≤15s 墙钟）。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

# A skipif marker is evaluated after collection imports. Skip this native
# suite before importing Windows-only ctypes bindings on Linux/macOS.
if sys.platform != "win32":
    pytest.skip("Windows 专属后端", allow_module_level=True)

import psutil  # noqa: E402

# utils/shell.py 惰性导入 rxycode_runner（生产 supervisor）；测试环境未装
# editable 包时补 packages src 路径（与 tests/web/w7 同一惯例）。
_REPO = Path(__file__).resolve().parents[2]
_runner_src = _REPO / "packages" / "rxycode-runner" / "src"
if _runner_src.is_dir() and str(_runner_src) not in sys.path:
    sys.path.insert(0, str(_runner_src))

from RxyCode.RxyCode1_1_0.core.sandbox.errors import SandboxUnavailableError  # noqa: E402
from RxyCode.RxyCode1_1_0.core.sandbox.manager import (  # noqa: E402
    JobPlan,
    bind_spawned_process,
    open_sandbox_job,
    wrap_command,
)
from RxyCode.RxyCode1_1_0.core.sandbox.policy import SandboxPolicy, from_config  # noqa: E402
from RxyCode.RxyCode1_1_0.core.sandbox.windows import (  # noqa: E402
    LOW_INTEGRITY_SID,
    _close_handle,
    apply_job_to_pid,
    assign_job_to_tree,
    assign_pid_to_job_handle,
    open_job,
    plan_windows_command,
    query_job_limits,
    query_token_integrity,
    resume_process_main_thread,
    spawn_restricted_sync,
    unenforced_constraints,
)

# Deprecated (2026-10-07): a module-wide skipif here was too late to prevent
# importing ctypes.windll during Linux collection; use the import-time gate.


def _policy(**overrides) -> SandboxPolicy:
    base = dict(enabled=True, mode="workspace", workspace_root=Path.cwd(), network="none")
    base.update(overrides)
    return SandboxPolicy(**base)


def _wait_dead(pid: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.1)
    return False


def test_plan_windows_command_builds_job_plan():
    """layer=unit plan（post-W7 track C）：workspace 模式包装成 tokenlaunch
    启动器 argv（受限子进程 Low IL/AppContainer 内核写隔离），JobPlan
    限额照常落到启动器 root 并继承整树；deny_read_globs 仍落空 →
    downgraded 诚实标记。"""
    policy = _policy(max_memory_mb=256, max_processes=4)
    wrapped = plan_windows_command(policy, ["cmd.exe", "/c", "exit"], Path.cwd())
    assert wrapped.backend == "job+token"
    assert wrapped.applied is True
    assert wrapped.downgraded is True  # deny_read_globs 仍未落实
    assert "未落实" in wrapped.detail
    # launcher argv: python <repo>/core/sandbox/tokenlaunch.py --workspace <cwd>
    # -- <argv>（绝对文件路径：spawn cwd 是用户工作区，-m 解析不到包）
    assert Path(wrapped.argv[1]).name == "tokenlaunch.py"
    assert Path(wrapped.argv[1]).is_file()
    assert "--workspace" in wrapped.argv
    assert wrapped.argv[-3:] == ["cmd.exe", "/c", "exit"]
    assert wrapped.job_plan is not None
    assert wrapped.job_plan.max_memory_bytes == 256 * 1024 * 1024
    assert wrapped.job_plan.max_processes == 4
    assert wrapped.job_plan.kill_on_close is True


def test_manager_disabled_passthrough_and_downgrade():
    """layer=unit manager：enabled=False 原样；缺能力时降级/失败两态。"""
    policy = _policy(enabled=False)
    wrapped = wrap_command(policy, ["cmd.exe"], Path.cwd())
    assert wrapped.applied is False and wrapped.downgraded is False

    downgraded = wrap_command(
        _policy(on_missing_capability="downgrade"),
        ["echo", "hi"],
        Path.cwd(),
        os_name="linux",  # 本机无 bwrap → 缺能力
    )
    assert downgraded.applied is False and downgraded.downgraded is True

    with pytest.raises(SandboxUnavailableError):
        wrap_command(
            _policy(on_missing_capability="fail_closed"),
            ["echo", "hi"],
            Path.cwd(),
            os_name="linux",
        )


def test_job_kill_on_close_reaps_process_tree():
    """layer=module kill-tree：spawn 立刻整树指派 → Job 句柄全关 → 全树连坐死亡。
    （Job 语义：只在指派后诞生的子孙自动入 Job——晚半秒指派就会漏杀，
    必须 assign_job_to_tree 圈住现存子孙；2026-10-06 实测。）"""
    proc = subprocess.Popen(
        ["cmd.exe", "/c", "ping -n 60 127.0.0.1 >nul"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    job = None
    tree: list[int] = []
    try:
        job = assign_job_to_tree(proc.pid, JobPlan(kill_on_close=True))
        time.sleep(0.6)
        tree = [proc.pid] + [c.pid for c in psutil.Process(proc.pid).children()]
        assert len(tree) >= 2  # cmd + ping 都在
    finally:
        if job:
            from RxyCode.RxyCode1_1_0.core.sandbox.windows import _close_handle

            _close_handle(job)  # kill-on-close 生效点
    for pid in tree:
        assert _wait_dead(pid), f"pid {pid} 未随 Job 关闭死亡"


def test_job_active_process_limit_blocks_grandchild():
    """layer=module 限额：max_processes=1 时 cmd 的孙进程创建失败。"""
    proc = subprocess.Popen(
        ["cmd.exe", "/c", "ping -n 5 127.0.0.1 >nul"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    job = None
    try:
        job = apply_job_to_pid(proc.pid, JobPlan(max_processes=1, kill_on_close=True))
        exit_code = proc.wait(timeout=10)
    finally:
        if job:
            from RxyCode.RxyCode1_1_0.core.sandbox.windows import _close_handle

            _close_handle(job)
        if proc.poll() is None:
            proc.kill()
    assert exit_code != 0  # timeout.exe 创建被拒


def test_job_process_memory_limit_kills_allocator():
    """layer=module 限额：128MB 限额下分配 300MB 的 python 失败退出。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", "x = 'x' * 300_000_000"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    job = None
    try:
        job = apply_job_to_pid(
            proc.pid, JobPlan(max_memory_bytes=128 * 1024 * 1024, kill_on_close=True)
        )
        exit_code = proc.wait(timeout=15)
    finally:
        if job:
            from RxyCode.RxyCode1_1_0.core.sandbox.windows import _close_handle

            _close_handle(job)
        if proc.poll() is None:
            proc.kill()
    assert exit_code != 0


def test_spawn_restricted_group_and_il_cap(tmp_path):
    """layer=module 受限令牌 spawn（宿主能力感知）：宿主支持 CreateProcessWithTokenW
    时验证完整链路；不支持时断言 SandboxUnavailableError（显式降级，不静默）。
    （实测：本机一类 Windows Server/未提权宿主上，受限令牌 spawn 恒
    ERROR_ACCESS_DENIED——这是能力缺失面，不是缺陷。）"""
    try:
        rp = spawn_restricted_sync(
            ["cmd.exe", "/c", "ping -n 5 127.0.0.1 >nul"],
            str(tmp_path),
            _policy(),
        )
    except SandboxUnavailableError as exc:
        # 宿主无受限 spawn 能力：显式降级路径必须带原因，不许静默。
        assert "CreateProcessWithTokenW" in str(exc) or "GetLastError" in str(exc)
        return
    try:
        assert rp.detail  # "low-il" 或 restricted-only 显式降级
        if rp.detail == "low-il":
            assert query_token_integrity(rp.pid) == LOW_INTEGRITY_SID
        else:
            assert rp.detail.startswith("restricted-only")
    finally:
        rp.close()
    assert _wait_dead(rp.pid)


def test_spawn_restricted_exit_code_and_cleanup(tmp_path):
    """layer=module 受限 spawn（宿主能力感知）：退出码透传、句柄清理。"""
    try:
        rp = spawn_restricted_sync(
            ["cmd.exe", "/c", "exit", "3"],
            str(tmp_path),
            _policy(),
        )
    except SandboxUnavailableError:
        return  # 能力缺失：显式降级路径即可
    try:
        assert rp.wait(timeout_ms=10000) == 3
    finally:
        rp.close()


def test_spawn_restricted_with_job_plan_applies_limits(tmp_path):
    """layer=module 受限 spawn + Job（宿主能力感知）：Job 限额真实落到受限 spawn。"""
    try:
        rp = spawn_restricted_sync(
            ["cmd.exe", "/c", "ping -n 5 127.0.0.1 >nul"],
            str(tmp_path),
            _policy(max_processes=2),
        )
    except SandboxUnavailableError:
        return  # 能力缺失：显式降级路径即可
    try:
        from RxyCode.RxyCode1_1_0.core.sandbox.windows import query_job_limits

        flags, active_limit, _ = query_job_limits(rp.job_handle)
        assert active_limit == 2 and flags != 0
        rp.wait(timeout_ms=12000)
    finally:
        rp.close()


def test_apply_job_invalid_pid_raises():
    """layer=unit 失败面：非法 pid → SandboxUnavailableError（不静默）。"""
    with pytest.raises(SandboxUnavailableError):
        apply_job_to_pid(2**22, JobPlan(kill_on_close=True))


def test_unenforced_constraints_lists_only_policy_gaps():
    """layer=unit 诚实清单（post-W7 track C）：workspace 写域与 AppContainer
    主路径的 network=none 已落实，不再出现在落空清单；read-only 全域禁写
    粒度与读遮蔽仍如实列出。"""
    minimal = unenforced_constraints(_policy(network="inherit", deny_read_globs=()))
    assert minimal == []
    full = unenforced_constraints(_policy(mode="read-only", network="none"))
    assert [m.split("（")[0] for m in full] == [
        "mode=read-only",
        "network=none",
        "deny_read_globs",
    ]


def test_unenforced_fail_closed_lists_network_none():
    """layer=unit fail_closed 保守语义：AppContainer 主路径可落实
    network=none，但运行期可能退化到 Low IL 兜底（网络不在管内）——
    fail_closed 下按「不可保证」列出。"""
    missing = unenforced_constraints(
        _policy(network="none", deny_read_globs=(), on_missing_capability="fail_closed")
    )
    assert missing == ["network=none（禁网）"]


def test_plan_windows_command_fail_closed_rejects_unenforced():
    """layer=unit fail_closed：无法落实的约束直接拒执行（2026-10-07 审计修：
    旧版无视 mode/network/deny globs 恒 applied=True）。"""
    policy = _policy(on_missing_capability="fail_closed", mode="read-only", network="none")
    with pytest.raises(SandboxUnavailableError, match="fail_closed"):
        plan_windows_command(policy, ["cmd.exe", "/c", "exit"], Path.cwd())


def test_plan_windows_command_downgrade_marks_only_missing():
    """layer=unit downgrade：workspace 模式落实后，detail 只列仍落空的
    约束（deny_read_globs）；全部落实时不降级。"""
    policy = _policy(network="inherit")
    wrapped = plan_windows_command(policy, ["cmd.exe", "/c", "exit"], Path.cwd())
    assert wrapped.applied is True
    assert wrapped.downgraded is True
    unenforced = wrapped.detail.split("未落实：", 1)[1]
    assert "mode=workspace" not in unenforced
    assert "network" not in unenforced
    assert "deny_read_globs" in unenforced
    # 全落实：不降级、detail 无「未落实」
    clean = plan_windows_command(
        _policy(network="inherit", deny_read_globs=()), ["cmd.exe", "/c", "exit"], Path.cwd()
    )
    assert clean.downgraded is False
    assert "未落实" not in clean.detail


def test_spawn_restricted_fail_closed_rejects_before_spawn(tmp_path):
    """layer=unit fail_closed：受限令牌原语同样拒执行，且不触碰任何 Win32 被调。"""
    with mock.patch(
        "RxyCode.RxyCode1_1_0.core.sandbox.windows._create_low_integrity_restricted_token"
    ) as token_mock:
        with pytest.raises(SandboxUnavailableError, match="fail_closed"):
            spawn_restricted_sync(
                ["cmd.exe", "/c", "exit"],
                str(tmp_path),
                _policy(on_missing_capability="fail_closed"),
            )
    token_mock.assert_not_called()


def test_resume_thread_failure_raises_instead_of_silent_success(tmp_path):
    """layer=unit 回归（2026-10-07 审计）：ResumeThread 失败返回 0xFFFFFFFF
    （DWORD），Python 里为真值——旧代码 `if not ResumeThread(...)` 会把失败
    当成成功放行。mock 全部 Win32 面，断言失败路径抛错且已建进程被杀。"""
    from RxyCode.RxyCode1_1_0.core.sandbox import windows

    def fake_create_with_token(*call_args):
        pi_ref = call_args[8]  # byref(pi)
        pi_ref._obj.hProcess = 111
        pi_ref._obj.hThread = 222
        pi_ref._obj.dwProcessId = 333
        pi_ref._obj.dwThreadId = 444
        return 1

    with (
        mock.patch.object(windows, "_create_low_integrity_restricted_token", return_value=999),
        mock.patch.object(
            windows,
            "_new_low_il_attribute_list",
            side_effect=SandboxUnavailableError("mock: IL 能力缺失"),
        ),
        mock.patch.object(
            windows.advapi32, "CreateProcessWithTokenW", side_effect=fake_create_with_token
        ),
        mock.patch.object(windows.kernel32, "ResumeThread", return_value=0xFFFFFFFF),
        mock.patch.object(windows.kernel32, "TerminateProcess") as terminate,
        mock.patch.object(windows.kernel32, "WaitForSingleObject", return_value=0) as wait,
        mock.patch.object(windows, "_close_handle") as close_handle,
    ):
        with pytest.raises(SandboxUnavailableError, match="ResumeThread"):
            spawn_restricted_sync(["cmd.exe", "/c", "exit"], str(tmp_path), _policy())
    assert terminate.call_count == 1
    terminated_handle, terminate_code = terminate.call_args.args
    assert terminated_handle.value == 111
    assert terminate_code == 1
    assert wait.call_count == 1
    waited_handle, wait_timeout = wait.call_args.args
    assert waited_handle.value == 111
    assert wait_timeout == 3000
    close_handle.assert_has_calls(
        [
            mock.call(222),
            mock.call(111),
            mock.call(999),
        ]
    )
    assert close_handle.call_count == 3


# ---- 出生即绑定（2026-10-07 验收缺陷修：venv launcher 自建 Job 冲突）---------

_CREATE_SUSPENDED = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)


def _popen_suspended(argv, cwd=None, stdout=subprocess.PIPE):
    """CREATE_SUSPENDED 起子进程——与 shell.py 沙箱分支同款创建形态。"""
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED,
    )


@pytest.fixture(scope="module")
def venv_python(tmp_path_factory):
    """真实 venv（CPython 3.13 的 venv launcher 自建 Job 并把解释器放进去——
    2026-10-07 验收 GetLastError=5 缺陷的被试）。"""
    venv_dir = tmp_path_factory.mktemp("venv-sandbox")
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
        check=True,
        timeout=240,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return venv_dir / "Scripts" / "python.exe"


def test_resume_process_main_thread_resumes_newborn():
    """layer=unit 原语：suspended 新生 cmd 恢复后退出码正常透传。"""
    proc = _popen_suspended(["cmd.exe", "/c", "exit", "7"], stdout=subprocess.DEVNULL)
    try:
        assert resume_process_main_thread(proc.pid) == 1
        assert proc.wait(timeout=10) == 7
    finally:
        if proc.poll() is None:
            proc.kill()


def test_bind_spawned_process_assigns_and_resumes():
    """layer=module 生产链路：open_sandbox_job → suspended spawn → bind →
    正常执行；Job 限额标志真实落上。"""
    wrapped = plan_windows_command(_policy(), ["cmd.exe"], Path.cwd())
    job = open_sandbox_job(wrapped)
    assert job
    proc = _popen_suspended(["cmd.exe", "/c", "exit", "5"], stdout=subprocess.DEVNULL)
    try:
        bind_spawned_process(job, proc.pid)
        assert proc.wait(timeout=10) == 5
        flags, _, _ = query_job_limits(job)
        assert flags & 0x00002000  # KILL_ON_JOB_CLOSE
    finally:
        if proc.poll() is None:
            proc.kill()
        _close_handle(job)


def test_bind_failure_keeps_suspended_and_never_runs(tmp_path):
    """layer=module fail-closed：绑定失败 → root 保持 suspended、从未执行——
    终止即「整树回收」（无子孙可漏），不吞 GetLastError、不放行未约束进程。"""
    marker = tmp_path / "must_not_exist.txt"
    proc = _popen_suspended(
        ["cmd.exe", "/c", f'echo ran> "{marker}"'],
        cwd=str(tmp_path),
        stdout=subprocess.DEVNULL,
    )
    try:
        with pytest.raises(SandboxUnavailableError):
            bind_spawned_process(0xFFFFFFF0, proc.pid)  # 非法 Job 句柄
        time.sleep(0.8)
        assert not marker.exists()  # 从未运行过
    finally:
        if proc.poll() is None:
            proc.kill()


def test_venv_python_runs_under_born_in_job_sandbox(venv_python, tmp_path):
    """layer=module 验收复现面：venv Python（launcher 自建 Job）在出生即绑定下
    正常执行——验收 3/3 失败的同款场景。"""
    job = open_job(JobPlan(kill_on_close=True))
    proc = _popen_suspended([str(venv_python), "-c", "print('VENV_JOB_OK')"])
    try:
        bind_spawned_process(job, proc.pid)
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0
        assert b"VENV_JOB_OK" in out
    finally:
        if proc.poll() is None:
            proc.kill()
        _close_handle(job)


def test_venv_grandchild_reaped_by_kill_on_close(venv_python):
    """layer=module 验收核心项：venv 解释器派生的孙进程在 launcher 自建 Job
    （嵌套于我方 Job）内——关我方句柄连坐回收整层。"""
    code = (
        "import subprocess, time; "
        "subprocess.Popen(['ping', '-n', '60', '127.0.0.1'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "time.sleep(60)"
    )
    job = open_job(JobPlan(kill_on_close=True))
    proc = _popen_suspended([str(venv_python), "-c", code], stdout=subprocess.DEVNULL)
    tree: list[int] = []
    try:
        bind_spawned_process(job, proc.pid)
        time.sleep(4)  # launcher 完成转发、解释器跑起来、孙进程派生
        assert proc.poll() is None
        tree = [proc.pid] + [c.pid for c in psutil.Process(proc.pid).children(recursive=True)]
        assert len(tree) >= 2, "venv 解释器应已派生孙进程"
    finally:
        _close_handle(job)  # kill-on-close 生效点
    for pid in tree:
        assert _wait_dead(pid), f"pid {pid} 未随 Job 关闭死亡"


def test_venv_active_process_limit_still_applies(venv_python):
    """layer=module 限额仍在：max_processes=2 时 venv 解释器 + 孙进程占满后，
    第 3 个进程创建失败。"""
    code = (
        "import subprocess; "
        "subprocess.run(['cmd', '/c', 'exit', '0']); "
        "subprocess.run(['cmd', '/c', 'exit', '0'])"
    )
    job = open_job(JobPlan(max_processes=2, kill_on_close=True))
    proc = _popen_suspended([str(venv_python), "-c", code], stdout=subprocess.DEVNULL)
    try:
        bind_spawned_process(job, proc.pid)
        exit_code = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
        _close_handle(job)
    assert exit_code != 0  # 第 2 个 cmd 创建被 ACTIVE_PROCESS 限额拒绝


def test_venv_python_through_production_shell(tmp_path, monkeypatch, venv_python):
    """layer=e2e 验收直接面：生产 _execute_controlled 链跑 venv python ——
    2026-10-07 验收 3/3 失败的同款 execute_argv_async 直起 argv 路径。"""
    from RxyCode.RxyCode1_1_0.utils import shell as shell_module

    cfg = {
        "execution": {
            "sandbox_mode": "workspace",
            "workspace_root": str(tmp_path),
            "os_sandbox": {
                "enabled": True,
                "mode": "workspace",
                "network": "inherit",
                "on_missing_capability": "downgrade",
            },
        }
    }
    monkeypatch.setattr(shell_module, "load_config", lambda: cfg)
    executor = object.__new__(shell_module.ShellExecutor)
    executor.os_name = "win32"
    executor.shell_type = "powershell"
    executor.user_home = ""
    executor.desktop_path = ""
    executor.watchdog_checkpoints = shell_module.WATCHDOG_CHECKPOINTS
    executor.watchdog_idle_cpu_percent = shell_module.WATCHDOG_IDLE_CPU_PERCENT
    executor.watchdog_idle_kill_after = shell_module.WATCHDOG_IDLE_KILL_AFTER
    executor.watchdog_observe_seconds = shell_module.WATCHDOG_OBSERVE_SECONDS

    result = asyncio.run(
        executor.execute_argv_async(
            [str(venv_python), "-c", "print('VENV_SHELL_OK')"],
            workdir=str(tmp_path),
        )
    )
    assert result["stdout"].strip() == "VENV_SHELL_OK", result
    assert result["success"] is True


_HOST_JOB_HELPER = """
import subprocess, sys, time
import psutil
from RxyCode.RxyCode1_1_0.core.sandbox.types import JobPlan
from RxyCode.RxyCode1_1_0.core.sandbox.windows import (
    _close_handle, assign_pid_to_job_handle, open_job, resume_process_main_thread)

p = subprocess.Popen(["cmd.exe", "/c", "exit", "9"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000004)  # CREATE_SUSPENDED（winbase.h）
job = open_job(JobPlan(kill_on_close=True))
try:
    assign_pid_to_job_handle(job, p.pid)  # 宿主在 outer Job 内，inner 应为嵌套
    resume_process_main_thread(p.pid)
    rc = p.wait(timeout=15)
    time.sleep(1.5)  # Job 异步收账
    alive = [c.pid for c in psutil.Process().children(recursive=False)]
    ok = rc == 9 and p.pid not in alive
    print("HOST_JOB_PROBE_OK" if ok else f"BAD rc={rc} alive={alive}")
finally:
    _close_handle(job)
    if p.poll() is None:
        p.kill()
"""


def test_host_already_in_job_still_binds_newborn(tmp_path):
    """layer=module 验收项「宿主已有 Job」：调用方自己已在某个 Job 里时，
    suspended 新生儿的创建期绑定仍然成立（新房新生儿出生时不在任何 Job，
    入 Job 形为合法嵌套）。宿主策略禁止跨会话指派时按能力面显式 skip。"""
    helper_src = tmp_path / "host_job_helper.py"
    helper_src.write_text(_HOST_JOB_HELPER, encoding="utf-8")
    outer = subprocess.Popen(
        [sys.executable, str(helper_src)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    outer_job = 0
    try:
        try:
            outer_job = open_job(JobPlan(kill_on_close=True))
            assign_pid_to_job_handle(outer_job, outer.pid)
        except SandboxUnavailableError as exc:
            outer.kill()
            outer.wait(timeout=10)
            pytest.skip(
                f"宿主禁止把活动进程指派入 Job（同 2026-10-07 受限 spawn 的宿主能力面）: {exc}"
            )
        out, err = outer.communicate(timeout=60)
        assert b"HOST_JOB_PROBE_OK" in out, err.decode("utf-8", "replace")[-400:]
    finally:
        if outer.poll() is None:
            outer.kill()
        _close_handle(outer_job)


def test_from_config_auto_toggle_by_permission_mode():
    """layer=unit（post-W7 track C）：os_sandbox.enabled 未显式配置时按
    权限模式自动开关——普通模式开，Full/Full-Auto 解除；显式值优先。"""
    cfg = {"execution": {"os_sandbox": {}}}
    assert (
        from_config(cfg, workspace_root=Path.cwd(), permission_mode="confirm_all").enabled is True
    )
    assert from_config(cfg, workspace_root=Path.cwd(), permission_mode="auto_edit").enabled is True
    assert from_config(cfg, workspace_root=Path.cwd(), permission_mode="full").enabled is False
    assert from_config(cfg, workspace_root=Path.cwd(), permission_mode="full_auto").enabled is False
    # 显式 enabled 覆盖模式推断（两个方向都要）
    assert (
        from_config(
            {"execution": {"os_sandbox": {"enabled": True}}},
            workspace_root=Path.cwd(),
            permission_mode="full",
        ).enabled
        is True
    )
    assert (
        from_config(
            {"execution": {"os_sandbox": {"enabled": False}}},
            workspace_root=Path.cwd(),
            permission_mode="confirm_all",
        ).enabled
        is False
    )


def test_tokenlaunch_appcontainer_write_isolation(tmp_path):
    """layer=module（post-W7 track C）：真 AppContainer spawn——工作区内
    可写、工作区外（用户目录）写被内核拒绝。这就是 Windows 的普通模式
    执行权限隔离。"""
    import subprocess as sp

    outside = tmp_path.parent / "must_never_exist_tkprobe.txt"
    outside.unlink(missing_ok=True)
    ws = tmp_path / "ws"
    launcher = Path(__file__).resolve().parents[2] / "core" / "sandbox" / "tokenlaunch.py"
    argv = [
        sys.executable,
        str(launcher),
        "--workspace",
        str(ws),
        "--cwd",
        str(ws),
        "--",
        "cmd.exe",
        "/c",
        f"echo inside> inner.txt & type inner.txt & echo x > {outside} & dir {outside}",
    ]
    done = sp.run(argv, capture_output=True, text=True, timeout=180)
    assert "inside" in done.stdout, done.stdout + done.stderr
    assert (ws / "inner.txt").read_text().strip() == "inside"
    assert not outside.exists(), f"workspace-escape write succeeded: {done.stdout}{done.stderr}"
