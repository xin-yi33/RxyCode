"""Linux 沙箱后端（v1.4.1）：bubblewrap（bwrap）argv 组装。

只做纯函数式 argv 组装：不 spawn 进程、不做二进制存在性探测（detect 层管）、
不读 config。bwrap 的挂载语义是「后 bind 覆盖先 bind」，因此 deny 遮蔽挂载必须
排在 ``--ro-bind / /`` 兜底只读之后。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .types import WrappedCommand
from .policy import SandboxPolicy

_logger = logging.getLogger(__name__)

#: bwrap 基座：随父进程死、独立会话、独立 PID 命名空间。
_BWRAP_BASE: tuple[str, ...] = (
    "bwrap",
    "--die-with-parent",
    "--new-session",
    "--unshare-pid",
)


def _resolve_deny_paths(workspace_root: Path, globs: tuple[str, ...]) -> list[Path]:
    """把 deny glob 按 workspace_root 解析成现存的具体路径（不存在/坏 pattern 跳过）。"""
    resolved: list[Path] = []
    for pattern in globs:
        try:
            matches = list(workspace_root.glob(pattern))
        except (OSError, ValueError, NotImplementedError) as exc:
            _logger.warning("os_sandbox deny_read_glob 无法解析，已跳过: %r（%s）", pattern, exc)
            continue
        for match in matches:
            try:
                if match.exists():
                    resolved.append(match)
            except OSError:
                continue
    return resolved


def _resolve_workspace_cwd(cwd: Path, workspace_root: Path) -> Path:
    """路由纪律：cwd 必须落在 workspace_root 内，不许静默逃逸出沙箱边界。"""
    target = cwd.resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(
            f"sandbox cwd 逃逸 workspace_root: {target} 不在 {workspace_root} 内"
        ) from exc
    return target


def _resolve_extra_write_roots(extra_roots: tuple[Path, ...]) -> list[Path]:
    """显式声明的额外可写根必须真实存在（typo 不能静默变成无效沙箱）。"""
    resolved: list[Path] = []
    for root in extra_roots:
        candidate = root.resolve()
        if not candidate.exists():
            raise ValueError(f"os_sandbox extra_write_root 不存在: {candidate}")
        resolved.append(candidate)
    return resolved


def build_bwrap_command(
    policy: SandboxPolicy,
    argv: list[str],
    cwd: Path,
) -> WrappedCommand:
    """组装完整 bwrap argv：根只读兜底 + workspace 可写 + deny 遮蔽 + 网络隔离。

    一律参数分隔（不拼 shell 字符串），路径全部转 str。bwrap 标志全部排在
    被包装命令之前。
    """
    if not argv:
        raise ValueError("argv 为空")
    workspace_root = policy.workspace_root.resolve()
    target_cwd = _resolve_workspace_cwd(cwd, workspace_root)
    extra_roots = _resolve_extra_write_roots(policy.extra_write_roots)

    bwrap: list[str] = list(_BWRAP_BASE)
    if policy.network == "none":
        bwrap.append("--unshare-net")
    # 文件系统：根兜底只读；workspace 模式把 workspace 重新挂成可写，
    # read-only 模式不加该 bind（workspace 随 / 保持只读）。
    bwrap.extend(["--ro-bind", "/", "/"])
    if policy.mode == "workspace":
        bwrap.extend(["--bind", str(workspace_root), str(workspace_root)])
    # extra_write_roots 是操作者显式 opt-in，read-only 模式下同样生效。
    for root in extra_roots:
        bwrap.extend(["--bind", str(root), str(root)])
    bwrap.extend(["--tmpfs", "/tmp"])
    # deny 遮蔽：挂在 ro-bind 之后（后 bind 覆盖先 bind）。
    # 文件用 /dev/null 盖掉，目录用空 tmpfs 盖掉。
    deny_paths = _resolve_deny_paths(workspace_root, policy.deny_read_globs)
    for path in deny_paths:
        if path.is_dir():
            bwrap.extend(["--tmpfs", str(path)])
        else:
            bwrap.extend(["--ro-bind", "/dev/null", str(path)])
    bwrap.extend(["--chdir", str(target_cwd)])
    bwrap.extend(str(arg) for arg in argv)

    return WrappedCommand(
        argv=bwrap,
        job_plan=None,
        backend="bwrap",
        applied=True,
        detail=(
            f"bwrap mode={policy.mode} network={policy.network} "
            f"deny_mounts={len(deny_paths)} extra_write={len(extra_roots)}"
        ),
    )
