"""macOS 沙箱后端（v1.4.1）：Seatbelt（sandbox-exec）profile 生成与 argv 组装。

生成 ``.sb`` profile 到临时文件（路径进 ``WrappedCommand.cleanup``，由调用方删），
argv 形如 ``sandbox-exec -f <profile> <原 argv>``。纯 stdlib，不 spawn 进程，
不做二进制存在性探测（detect 层管）。cwd 由 spawn 方直接传给子进程，不进 profile。
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from .types import WrappedCommand
from .policy import SandboxPolicy

_logger = logging.getLogger(__name__)


def _sb_escape(text: str) -> str:
    """Seatbelt profile 字符串字面量转义：先反斜杠、后双引号。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


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


def build_seatbelt_profile(policy: SandboxPolicy) -> str:
    """生成 Seatbelt profile 文本：deny default + 白名单放行。

    Seatbelt 语义：deny 优先于 allow，因此 deny 行与 allow 行的先后无影响，
    这里按「基座 → 文件写 → 网络 → 读遮蔽」的阅读顺序排布。
    """
    workspace_root = policy.workspace_root.resolve()

    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow mach-lookup)",
        "(allow file-read*)",
    ]
    if policy.mode == "read-only":
        # read-only 模式：全文件系统禁写（无视 workspace/extra_write_roots 的写放行）。
        lines.append("(deny file-write*)")
    else:
        escaped_root = _sb_escape(str(workspace_root))
        lines.append(f'(allow file-write* (subpath "{escaped_root}"))')
        lines.append('(allow file-write* (subpath "/tmp"))')
        lines.append('(allow file-write* (subpath "/private/tmp"))')
        for root in policy.extra_write_roots:
            candidate = root.resolve()
            if not candidate.exists():
                raise ValueError(f"os_sandbox extra_write_root 不存在: {candidate}")
            lines.append(f'(allow file-write* (subpath "{_sb_escape(str(candidate))}"))')
    if policy.network == "none":
        lines.append("(deny network*)")
    else:
        # (deny default) 基座下「不写 deny」不等于放行——inherit 必须显式
        # allow（2026-10-07 审计修：旧版 inherit 实际仍默认禁网）。
        lines.append("(allow network*)")
    # deny 读遮蔽：文件用 literal 精确遮，目录用 subpath 整棵遮。
    for path in _resolve_deny_paths(workspace_root, policy.deny_read_globs):
        escaped = _sb_escape(str(path))
        if path.is_dir():
            lines.append(f'(deny file-read* (subpath "{escaped}"))')
        else:
            lines.append(f'(deny file-read* (literal "{escaped}"))')
    return "\n".join(lines) + "\n"


def build_seatbelt_command(
    policy: SandboxPolicy,
    argv: list[str],
    cwd: Path,
) -> WrappedCommand:
    """写 profile 临时文件并组装 ``sandbox-exec -f`` argv。

    cwd 参数不进 profile（Seatbelt 无 chdir 原语），仅保持与 manager 约定的
    后端函数签名一致；spawn 方沿用该 cwd 启动子进程。
    """
    if not argv:
        raise ValueError("argv 为空")
    profile = build_seatbelt_profile(policy)
    descriptor, name = tempfile.mkstemp(prefix="rxycode-sb-", suffix=".sb")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(profile)
    except Exception:
        # 写盘失败的半成品不能留在临时目录。
        Path(name).unlink(missing_ok=True)
        raise
    profile_path = Path(name)
    return WrappedCommand(
        argv=["sandbox-exec", "-f", str(profile_path), *(str(arg) for arg in argv)],
        job_plan=None,
        backend="seatbelt",
        applied=True,
        detail=(
            f"seatbelt mode={policy.mode} network={policy.network} profile={profile_path.name}"
        ),
        cleanup=(profile_path,),
    )
