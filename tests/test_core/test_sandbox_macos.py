"""Seatbelt（macOS sandbox-exec）后端 profile 与 argv 的纯单元测试——不 spawn。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core.sandbox.manager import WrappedCommand
from RxyCode.RxyCode1_1_0.core.sandbox.macos import (
    _sb_escape,
    build_seatbelt_command,
)
from RxyCode.RxyCode1_1_0.core.sandbox.policy import SandboxPolicy

BuildFn = Callable[[SandboxPolicy, list[str], Path], WrappedCommand]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """造一棵含 .env/.ssh 的 workspace 树，驱动 deny glob 的真实解析。"""
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / ".ssh").mkdir()
    (root / ".ssh" / "id_rsa").write_text("key\n", encoding="utf-8")
    return root.resolve()


@pytest.fixture
def build() -> Iterator[BuildFn]:
    """构造 WrappedCommand 并在用例结束时清掉 profile 临时文件。"""
    created: list[Path] = []

    def _make(policy: SandboxPolicy, argv: list[str], cwd: Path) -> WrappedCommand:
        wrapped = build_seatbelt_command(policy, argv, cwd)
        created.extend(wrapped.cleanup)
        return wrapped

    yield _make
    for path in created:
        path.unlink(missing_ok=True)


def _policy(workspace: Path, **overrides: object) -> SandboxPolicy:
    params: dict[str, object] = {
        "enabled": True,
        "workspace_root": workspace,
        "deny_read_globs": (),
    }
    params.update(overrides)
    return SandboxPolicy(**params)  # type: ignore[arg-type]


def _profile_text(wrapped: WrappedCommand) -> str:
    (profile_path,) = wrapped.cleanup
    return profile_path.read_text(encoding="utf-8")


def test_profile_allows_workspace_write(build: BuildFn, workspace: Path) -> None:
    policy = _policy(workspace, network="inherit")
    wrapped = build(policy, ["echo", "hi"], workspace)
    text = _profile_text(wrapped)
    assert "(version 1)" in text
    assert "(deny default)" in text
    assert "(allow process-exec)" in text
    assert "(allow process-fork)" in text
    assert "(allow mach-lookup)" in text
    assert "(allow file-read*)" in text
    escaped_root = _sb_escape(str(workspace))
    assert f'(allow file-write* (subpath "{escaped_root}"))' in text
    assert '(allow file-write* (subpath "/tmp"))' in text
    assert '(allow file-write* (subpath "/private/tmp"))' in text
    assert "(deny file-write*)" not in text


def test_read_only_denies_all_file_write(build: BuildFn, workspace: Path) -> None:
    policy = _policy(workspace, mode="read-only")
    wrapped = build(policy, ["true"], workspace)
    text = _profile_text(wrapped)
    assert "(deny file-write*)" in text
    escaped_root = _sb_escape(str(workspace))
    assert f'(allow file-write* (subpath "{escaped_root}"))' not in text


def test_network_none_denies_network(build: BuildFn, workspace: Path) -> None:
    policy = _policy(workspace, network="none")
    wrapped = build(policy, ["true"], workspace)
    text = _profile_text(wrapped)
    assert "(deny network*)" in text
    assert "(allow network*)" not in text


def test_network_inherit_keeps_network(build: BuildFn, workspace: Path) -> None:
    """deny default 基座下不写 deny 不等于放行——inherit 必须显式 allow
    （2026-10-07 审计修：旧版 inherit 实际仍默认禁网）。"""
    policy = _policy(workspace, network="inherit")
    wrapped = build(policy, ["true"], workspace)
    text = _profile_text(wrapped)
    assert "(deny network*)" not in text
    assert "(allow network*)" in text


def test_deny_globs_literal_for_file_subpath_for_dir(build: BuildFn, workspace: Path) -> None:
    policy = _policy(workspace, deny_read_globs=("**/.env", "**/.ssh"))
    wrapped = build(policy, ["true"], workspace)
    text = _profile_text(wrapped)
    env_line = f'(deny file-read* (literal "{_sb_escape(str(workspace / ".env"))}"))'
    ssh_line = f'(deny file-read* (subpath "{_sb_escape(str(workspace / ".ssh"))}"))'
    assert env_line in text
    assert ssh_line in text


def test_argv_shape_and_cleanup_registered(build: BuildFn, workspace: Path) -> None:
    policy = _policy(workspace)
    wrapped = build(policy, ["echo", "hi"], workspace)
    (profile_path,) = wrapped.cleanup
    assert wrapped.argv[:3] == ["sandbox-exec", "-f", str(profile_path)]
    assert wrapped.argv[3:] == ["echo", "hi"]
    assert profile_path.exists()
    assert profile_path.suffix == ".sb"
    assert profile_path.name.startswith("rxycode-sb-")
    assert wrapped.backend == "seatbelt"
    assert wrapped.applied is True
    assert wrapped.downgraded is False
    assert wrapped.job_plan is None
    assert "seatbelt" in wrapped.detail


def test_extra_write_root_allow_line(build: BuildFn, workspace: Path, tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    policy = _policy(workspace, extra_write_roots=(extra,))
    wrapped = build(policy, ["true"], workspace)
    text = _profile_text(wrapped)
    assert f'(allow file-write* (subpath "{_sb_escape(str(extra.resolve()))}"))' in text


def test_extra_write_root_missing_raises(workspace: Path, tmp_path: Path) -> None:
    policy = _policy(workspace, extra_write_roots=(tmp_path / "missing",))
    with pytest.raises(ValueError, match="extra_write_root"):
        build_seatbelt_command(policy, ["true"], workspace)


def test_sb_escape_quotes_and_backslashes() -> None:
    assert _sb_escape('a"b\\c') == 'a\\"b\\\\c'
    assert _sb_escape("/plain/path") == "/plain/path"


def test_empty_argv_raises(workspace: Path) -> None:
    policy = _policy(workspace)
    with pytest.raises(ValueError, match="argv"):
        build_seatbelt_command(policy, [], workspace)
