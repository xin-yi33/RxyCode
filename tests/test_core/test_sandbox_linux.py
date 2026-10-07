"""bwrap（Linux bubblewrap）后端 argv 组装的纯单元测试——不 spawn 真实 bwrap。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core.sandbox.linux import build_bwrap_command
from RxyCode.RxyCode1_1_0.core.sandbox.policy import SandboxPolicy


def test_windows_native_suite_skips_before_platform_imports():
    """The Linux/macOS collector must never load Windows ctypes bindings."""
    suite = Path(__file__).with_name("test_sandbox_windows.py")
    code = """
import builtins, importlib.util, sys, pytest, psutil
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.endswith('sandbox.windows'):
        raise AssertionError('platform binding imported before module skip')
    return original_import(name, *args, **kwargs)
sys.platform = 'linux'
builtins.__import__ = guarded_import
spec = importlib.util.spec_from_file_location('windows_native_suite', sys.argv[1])
try:
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
except pytest.skip.Exception as exc:
    assert exc.allow_module_level
    print('NATIVE_SUITE_SKIPPED_BEFORE_IMPORT')
else:
    raise AssertionError('Windows native suite was not skipped')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(suite)],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_SUITE_SKIPPED_BEFORE_IMPORT" in result.stdout


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """造一棵含 .env/.ssh 的 workspace 树，驱动 deny glob 的真实解析。"""
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / ".ssh").mkdir()
    (root / ".ssh" / "id_rsa").write_text("key\n", encoding="utf-8")
    return root.resolve()


def _policy(workspace: Path, **overrides: object) -> SandboxPolicy:
    params: dict[str, object] = {
        "enabled": True,
        "workspace_root": workspace,
        "deny_read_globs": (),
    }
    params.update(overrides)
    return SandboxPolicy(**params)  # type: ignore[arg-type]


def _subseq_index(argv: list[str], seq: list[str]) -> int:
    """argv 中连续子序列 seq 的起始下标；不存在则断言失败。"""
    for i in range(len(argv) - len(seq) + 1):
        if argv[i : i + len(seq)] == seq:
            return i
    raise AssertionError(f"{seq!r} 不在 argv 中: {argv!r}")


def test_workspace_mode_exact_argv_snapshot(workspace: Path) -> None:
    """workspace + network=inherit：完整 argv 快照，bwrap 标志全部在被包装命令之前。"""
    cwd = workspace / "src"
    policy = _policy(workspace, network="inherit")
    wrapped = build_bwrap_command(policy, ["echo", "hello"], cwd)
    assert wrapped.argv == [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(workspace),
        str(workspace),
        "--tmpfs",
        "/tmp",
        "--chdir",
        str(cwd),
        "echo",
        "hello",
    ]
    assert wrapped.backend == "bwrap"
    assert wrapped.applied is True
    assert wrapped.downgraded is False
    assert wrapped.job_plan is None
    assert wrapped.cleanup == ()
    assert "workspace" in wrapped.detail


def test_network_none_unshares_net(workspace: Path) -> None:
    policy = _policy(workspace, network="none")
    wrapped = build_bwrap_command(policy, ["true"], workspace)
    assert wrapped.argv[:5] == [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-net",
    ]


def test_network_inherit_keeps_net(workspace: Path) -> None:
    policy = _policy(workspace, network="inherit")
    wrapped = build_bwrap_command(policy, ["true"], workspace)
    assert "--unshare-net" not in wrapped.argv


def test_read_only_mode_skips_workspace_bind(workspace: Path) -> None:
    """read-only：不加 workspace 的 rw bind，其余基座（ro-bind / --chdir）保持。"""
    policy = _policy(workspace, mode="read-only")
    wrapped = build_bwrap_command(policy, ["true"], workspace)
    assert "--bind" not in wrapped.argv
    _subseq_index(wrapped.argv, ["--ro-bind", "/", "/"])
    _subseq_index(wrapped.argv, ["--chdir", str(workspace)])


def test_extra_write_roots_bound_after_workspace(workspace: Path, tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    policy = _policy(workspace, extra_write_roots=(extra,))
    wrapped = build_bwrap_command(policy, ["true"], workspace)
    workspace_idx = _subseq_index(wrapped.argv, ["--bind", str(workspace), str(workspace)])
    extra_idx = _subseq_index(wrapped.argv, ["--bind", str(extra.resolve()), str(extra.resolve())])
    assert extra_idx > workspace_idx


def test_extra_write_root_missing_raises(workspace: Path, tmp_path: Path) -> None:
    policy = _policy(workspace, extra_write_roots=(tmp_path / "missing",))
    with pytest.raises(ValueError, match="extra_write_root"):
        build_bwrap_command(policy, ["true"], workspace)


def test_deny_globs_mask_files_and_dirs_after_ro_bind(workspace: Path) -> None:
    """文件 → --ro-bind /dev/null 遮蔽；目录 → --tmpfs 遮蔽；且都挂在 ro-bind 之后。"""
    policy = _policy(workspace, deny_read_globs=("**/.env", "**/.ssh"))
    wrapped = build_bwrap_command(policy, ["true"], workspace)
    ro_bind_idx = _subseq_index(wrapped.argv, ["--ro-bind", "/", "/"])
    env_idx = _subseq_index(wrapped.argv, ["--ro-bind", "/dev/null", str(workspace / ".env")])
    ssh_idx = _subseq_index(wrapped.argv, ["--tmpfs", str(workspace / ".ssh")])
    assert env_idx > ro_bind_idx
    assert ssh_idx > ro_bind_idx
    assert "deny_mounts=2" in wrapped.detail


def test_deny_globs_ignore_missing_paths(workspace: Path) -> None:
    policy = _policy(workspace, deny_read_globs=("**/.aws/**", "**/*.pem"))
    wrapped = build_bwrap_command(policy, ["true"], workspace)
    assert "/dev/null" not in wrapped.argv


def test_cwd_outside_workspace_raises(workspace: Path, tmp_path: Path) -> None:
    policy = _policy(workspace)
    with pytest.raises(ValueError, match="workspace_root"):
        build_bwrap_command(policy, ["true"], tmp_path)


def test_empty_argv_raises(workspace: Path) -> None:
    policy = _policy(workspace)
    with pytest.raises(ValueError, match="argv"):
        build_bwrap_command(policy, [], workspace)
