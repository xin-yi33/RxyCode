"""受限令牌启动器（post-W7 track C）：异步 spawn 链的隔离桥。

异步执行链（asyncio.create_subprocess_exec）无法把令牌/AppContainer
属性注入子进程，所以 Windows ``mode=workspace`` 的 argv 包装为::

    python -m core.sandbox.tokenlaunch --workspace <root> [--write <dir>...]
        [--cwd <dir>] -- <原 argv>

本进程做的事（全部在内核执行面）：

1. 给写域（工作区 + extra_write_roots）授权并标级：
   ``icacls /grant "*<capability-sid>":(OI)(CI)F`` 让 AppContainer 能力
   SID 能写；``/setintegritylevel (OI)(CI)L`` 让 Low IL 子进程不被
   MIC No-Write-Up 拒写。其余宿主文件既不授权也不标 Low——写域收窄
   由内核强制，不是软件闸。
2. 把 TEMP/TMP 重定向到工作区内的 scratch 目录——受限子进程的临时写
   也落在写域内。
3. 优先 ``CreateProcessW`` + ``PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES``
   以稳定派生的 AppContainer SID 出生子进程（免特权；网络默认不可达）；
   宿主不支持时退化为 Low IL spawn（MIC 仍管写域）；再不行退受限令牌
   spawn（需 SE_IMPERSONATE，服务宿主才可能有）。三条路全如实标注。
4. 把本进程自己的 stdin/stdout/stderr 句柄经 STARTF_USESTDHANDLES 原样
   转交子进程——调用方管道直连，启动器不泵数据。
5. 等待并把子进程退出码作为自己的退出码返回。Job 归属靠继承
   （父进程在 Job → 子进程出生即在 Job），kill-on-close 覆盖整棵树。

仅 Windows 可运行；非 Windows 直接拒绝（不静默降级）。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    # 直接以文件路径运行（生产形态：异步 spawn 链的 cwd 是用户工作区，
    # 包上下文不可见）——自举到仓库根再按包相对导入。
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "core.sandbox"

from .policy import SandboxPolicy

_APPCONTAINER_NAME = "RxyCode.Sandbox"


def _icacls(args: list[str]) -> None:
    done = subprocess.run(["icacls", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(
            f"icacls {' '.join(args)} 失败: {done.stdout.strip()} {done.stderr.strip()}".strip()
        )


def _prepare_write_root(path: Path, capability_sid_text: str | None) -> None:
    """标 Low IL（MIC 放行 Low 子进程写）+ 给能力 SID 授权（DACL 放行
    AppContainer 子进程写）。两层都落才构成完整写域。

    Marker 文件做跨进程跳过：marker 被受限子进程篡改/伪造只能导致
    拒绝方向（写域没落实 → 子进程写不进去），绝不可能扩大写权。
    """
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    marker = path / f".rxy-lowil-{(capability_sid_text or 'il').replace('*', '')[-8:]}"
    if marker.exists():
        return
    if capability_sid_text:
        _icacls([str(path), "/grant", f"*{capability_sid_text}:(OI)(CI)F", "/t", "/c"])
    _icacls([str(path), "/setintegritylevel", "(OI)(CI)L", "/t", "/c"])
    try:
        marker.write_text("low-il labelled\n", encoding="ascii")
    except OSError:
        pass


def _grant_rx(path: Path, capability_sid_text: str, marker_dir: Path, recursive: bool) -> None:
    """给能力 SID 授 RX。跨进程 marker 缓存（伪造 marker 只会让授权
    没落实 → 子进程读不进 → 失败方向永远朝拒绝，不会扩大读权）。"""
    marker = marker_dir / (
        "rx-" + hashlib.sha1(str(path).lower().encode("utf-8", "replace")).hexdigest()[:16]
    )
    if marker.exists():
        return
    args = [str(path), "/grant", f"*{capability_sid_text}:(OI)(CI)(RX)", "/c"]
    if recursive:
        args.append("/t")
    _icacls(args)
    try:
        marker.write_text("rx granted\n", encoding="ascii")
    except OSError:
        pass


def _prepare_read_domain(exe: Path, capability_sid_text: str | None, marker_dir: Path) -> None:
    """AppContainer 子进程只能读 ACE 覆盖 All Application Packages/自身
    能力 SID 的对象——用户目录下的解释器/工具默认读不到（venv python
    报 failed to locate pyvenv.cfg）。给能力 SID 授 RX：

    - 可执行文件本身 + 所在目录（同目录 DLL/辅助文件）；
    - venv：根目录（pyvenv.cfg）+ Lib\\site-packages 树；base
      interpreter home（python3xx.dll 所在）+ home\\Lib + home\\DLLs。
    """
    if capability_sid_text is None or sys.platform != "win32":
        return
    targets: list[tuple[Path, bool]] = []
    exe = exe.resolve()
    targets.append((exe, False))
    targets.append((exe.parent, False))
    if exe.parent.name.lower() in ("scripts", "bin"):
        venv_root = exe.parent.parent
        cfg = venv_root / "pyvenv.cfg"
        if cfg.is_file():
            targets.append((venv_root, False))
            if (venv_root / "Lib").is_dir():
                targets.append((venv_root / "Lib", True))
            try:
                for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                    key, sep, value = line.partition("=")
                    if sep and key.strip().lower() == "home":
                        home = Path(value.strip())
                        if home.is_dir():
                            targets.append((home, False))
                            for sub in ("Lib", "DLLs"):
                                if (home / sub).is_dir():
                                    targets.append((home / sub, True))
                        break
            except OSError:
                pass
    marker_dir.mkdir(parents=True, exist_ok=True)
    for target, recursive in targets:
        _grant_rx(target, capability_sid_text, marker_dir, recursive)


def _std_handles() -> tuple[int, int, int]:
    """本进程的标准句柄（转交给受限子进程作它的 stdio）。"""
    windows = importlib.import_module(f"{__package__}.windows")

    get_std = windows.kernel32.GetStdHandle
    get_std.restype = windows.wintypes.HANDLE
    get_std.argtypes = [windows.wintypes.DWORD]
    return (
        int(get_std(windows.STD_INPUT_HANDLE)),
        int(get_std(windows.STD_OUTPUT_HANDLE)),
        int(get_std(windows.STD_ERROR_HANDLE)),
    )


def main() -> int:
    if sys.platform != "win32":
        print("tokenlaunch 仅 Windows 可运行", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="core.sandbox.tokenlaunch")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--write", action="append", default=[])
    parser.add_argument("--cwd", default=None)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    child_argv = list(ns.argv)
    if child_argv and child_argv[0] == "--":
        child_argv = child_argv[1:]
    if not child_argv:
        print("tokenlaunch 缺少目标 argv（-- 之后）", file=sys.stderr)
        return 2

    windows = importlib.import_module(f"{__package__}.windows")

    sid_ptr = None
    sid_text: str | None = None
    try:
        try:
            # Profile 必须先注册——只 Derive 不注册时 SECURITY_CAPABILITIES
            # spawn 报 ERROR_FILE_NOT_FOUND。
            sid_ptr, sid_text = windows.ensure_appcontainer(_APPCONTAINER_NAME)
        except Exception as exc:
            print(
                f"tokenlaunch: AppContainer 不可用，退 Low IL 路径: {exc}",
                file=sys.stderr,
            )
        workspace = Path(ns.workspace).resolve()
        writable = [workspace, *(Path(p).resolve() for p in ns.write)]
        for root in writable:
            try:
                _prepare_write_root(root, sid_text)
            except Exception as exc:
                print(
                    f"tokenlaunch: 写域标记失败，拒绝执行: {exc}",
                    file=sys.stderr,
                )
                return 2

        # 受限子进程的临时写也落在写域内。
        scratch = workspace / ".sandbox-tmp"
        try:
            _prepare_write_root(scratch, sid_text)
        except Exception:
            scratch.mkdir(parents=True, exist_ok=True)
        os.environ["TEMP"] = os.environ["TMP"] = str(scratch)

        # CreateProcessWithTokenW/CreateProcessW 不做 PATH 搜索——先解析
        # argv[0] 全路径。
        resolved = shutil.which(child_argv[0]) or child_argv[0]
        child_argv[0] = resolved
        # AppContainer 下用户目录默认不可读——给解释器/工具的读域授权。
        try:
            _prepare_read_domain(Path(resolved), sid_text, scratch / ".rx-grants")
        except Exception as exc:
            if sid_ptr is not None:
                print(
                    f"tokenlaunch: 读域授权失败，拒绝执行: {exc}",
                    file=sys.stderr,
                )
                return 2
        cwd = str(Path(ns.cwd).resolve()) if ns.cwd else str(workspace)
        stdio = _std_handles()

        proc = None
        if sid_ptr is not None:
            try:
                proc = windows.spawn_appcontainer_sync(child_argv, cwd, sid_ptr, stdio=stdio)
            except Exception as exc:
                print(
                    f"tokenlaunch: AppContainer spawn 失败，退 Low IL: {exc}",
                    file=sys.stderr,
                )
                proc = None
        if proc is None:
            try:
                policy = SandboxPolicy(enabled=True, mode="workspace", workspace_root=workspace)
                proc = windows.spawn_restricted_sync(child_argv, cwd, policy, stdio=stdio)
            except Exception as token_exc:
                proc = windows.spawn_low_il_sync(child_argv, cwd, stdio=stdio)
                print(
                    f"tokenlaunch: 受限令牌不可用，按 Low IL（MIC 写隔离）执行: {token_exc}",
                    file=sys.stderr,
                )
        try:
            return proc.wait(timeout_ms=0xFFFFFFFF)
        finally:
            proc.close()
    finally:
        if sid_ptr is not None:
            windows.advapi32.FreeSid(sid_ptr)


if __name__ == "__main__":
    sys.exit(main())
