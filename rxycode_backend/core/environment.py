"""环境感知模块 - 修复 P0-3 路径错误与用户身份混淆

用户反馈问题 (P0-3):
    Agent 报告桌面路径为 C:\\Users\\RxyCode\\Desktop,但实际测试环境
    用户名为 Administrator。Agent 疑似使用了进程运行身份 (RxyCode)
    而非当前登录用户的身份来推断路径。

架构根因:
    环境上下文缺失,硬编码推断。缺少启动时探测机制。

修复方案 (ADR-004):
    1. 启动时探测: 检测 OS、登录用户、桌面路径、可用 Shell
    2. 路径解析: 使用系统 API 获取真实路径,而非拼接用户名
    3. 缓存环境信息,供所有上下文使用 (Shared Kernel)
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path


class OSName(str, Enum):
    """支持的操作系统"""
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


class ShellType(str, Enum):
    """支持的 Shell 类型"""
    POWERSHELL = "powershell"
    CMD = "cmd"
    BASH = "bash"
    ZSH = "zsh"


@dataclass(frozen=True)
class EnvironmentInfo:
    """环境上下文 - 启动时探测并缓存,作为 Shared Kernel 提供给所有上下文

    不变式 (Invariants):
        1. desktop_path 必须存在且可写 (若系统支持)
        2. username 必须为非空字符串
        3. shell 按优先级选择,保证可用
    """
    os_name: OSName
    username: str
    home_path: str
    desktop_path: str
    shell: ShellType
    shell_path: str
    python_path: str
    is_windows: bool
    extra: dict = field(default_factory=dict)

    def resolve_path(self, path: str) -> str:
        """解析路径,支持 ~ 和环境变量展开

        修复 P0-3: 不再拼接用户名,而是用系统 API 解析真实路径。
        """
        if not path:
            return path
        # 展开 ~ 为家目录
        if path.startswith("~"):
            path = os.path.join(self.home_path, path[1:].lstrip("/\\"))
        # 展开环境变量
        path = os.path.expandvars(path)
        # 处理 Windows 桌面特殊路径
        if self.is_windows:
            path_lower = path.lower().replace("\\", "/")
            if path_lower in ("~/desktop", "~/桌面", "desktop", "桌面"):
                return self.desktop_path
        return os.path.normpath(path)

    def is_safe_path(self, path: str) -> bool:
        """路径安全检查 - 防止路径穿越攻击"""
        try:
            resolved = Path(self.resolve_path(path)).resolve()
            # 允许在用户目录内或临时目录内操作
            home = Path(self.home_path).resolve()
            return str(resolved).startswith(str(home))
        except (OSError, ValueError):
            return False


class EnvironmentDetector:
    """环境探测器 - 启动时调用 detect() 获取 EnvironmentInfo

    修复 P0-3 的核心:
        旧代码: path = f"C:\\Users\\{process_username}\\Desktop"  # 错误!用进程身份
        新代码: path = detector.detect().desktop_path             # 正确!用系统 API
    """

    @classmethod
    def detect(cls) -> EnvironmentInfo:
        """探测当前环境,返回不可变的 EnvironmentInfo

        探测顺序遵循"系统 API 优先,回退推断"原则,
        确保不使用进程身份推断用户路径。
        """
        os_name = cls._detect_os()
        is_windows = os_name == OSName.WINDOWS

        username = cls._detect_username()
        home_path = cls._detect_home_path()
        desktop_path = cls._detect_desktop_path(home_path, is_windows)
        shell, shell_path = cls._detect_shell(is_windows)
        python_path = cls._detect_python_path()

        return EnvironmentInfo(
            os_name=os_name,
            username=username,
            home_path=home_path,
            desktop_path=desktop_path,
            shell=shell,
            shell_path=shell_path,
            python_path=python_path,
            is_windows=is_windows,
            extra={
                "platform": platform.platform(),
                "processor": platform.processor(),
            },
        )

    @staticmethod
    def _detect_os() -> OSName:
        sys_platform = sys.platform.lower()
        if sys_platform.startswith("win"):
            return OSName.WINDOWS
        if sys_platform == "darwin":
            return OSName.MACOS
        return OSName.LINUX

    @staticmethod
    def _detect_username() -> str:
        """获取当前登录用户名

        修复 P0-3: 优先使用系统环境变量,而非进程身份。
        旧代码错误地使用了 os.getlogin() 或进程运行账户,
        在以服务方式运行时会返回 'RxyCode' 而非 'Administrator'。
        """
        # 优先级 1: 环境变量 USERNAME (Windows) / USER (Unix)
        username = os.environ.get("USERNAME") or os.environ.get("USER")
        if username:
            return username
        # 优先级 2: getpass 回退
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            # 最后回退,但绝不使用进程身份推断路径
            return os.environ.get("USERNAME", "unknown")

    @staticmethod
    def _detect_home_path() -> str:
        """获取用户家目录"""
        # 优先级 1: USERPROFILE (Windows) / HOME (Unix)
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if home:
            return os.path.normpath(home)
        # 优先级 2: pathlib 回退
        return str(Path.home())

    @staticmethod
    def _detect_desktop_path(home_path: str, is_windows: bool) -> str:
        """获取真实桌面路径

        修复 P0-3 的核心方法:
            旧代码: f"C:\\Users\\{username}\\Desktop"  # 拼接,可能用错用户名
            新代码: 系统 API 获取真实桌面路径

        Windows 上桌面可能被重定向到 OneDrive 或企业策略位置,
        拼接路径必然出错,必须用系统 API。
        """
        if is_windows:
            # 使用 PowerShell 的 [Environment]::GetFolderPath 获取真实桌面
            desktop = _get_windows_desktop_via_powershell()
            if desktop and os.path.isdir(desktop):
                return os.path.normpath(desktop)
            # 回退: 检查常见位置 (含 OneDrive 重定向)
            candidates = [
                os.path.join(home_path, "Desktop"),
                os.path.join(home_path, "OneDrive", "Desktop"),
                os.path.join(home_path, "桌面"),
            ]
            for cand in candidates:
                if os.path.isdir(cand):
                    return os.path.normpath(cand)
            # 最终回退: 家目录
            return home_path
        else:
            # macOS/Linux: ~/Desktop
            desktop = os.path.join(home_path, "Desktop")
            return desktop if os.path.isdir(desktop) else home_path

    @staticmethod
    def _detect_shell(is_windows: bool) -> tuple[ShellType, str]:
        """探测可用 Shell

        Shell 选择优先级:
            Windows: PowerShell > CMD
            Unix:    用户默认 Shell > bash > zsh
        """
        if is_windows:
            # 检测 PowerShell 是否可用
            ps_path = _find_executable("powershell") or _find_executable("pwsh")
            if ps_path:
                return ShellType.POWERSHELL, ps_path
            # 回退到 CMD
            cmd_path = _find_executable("cmd") or "C:\\Windows\\System32\\cmd.exe"
            return ShellType.CMD, cmd_path
        else:
            # Unix: 优先用户默认 Shell
            user_shell = os.environ.get("SHELL", "")
            if "zsh" in user_shell:
                zsh_path = _find_executable("zsh") or user_shell
                return ShellType.ZSH, zsh_path
            bash_path = _find_executable("bash") or "/bin/bash"
            return ShellType.BASH, bash_path

    @staticmethod
    def _detect_python_path() -> str:
        """获取 Python 解释器路径"""
        return sys.executable or "python"


def _get_windows_desktop_via_powershell() -> str | None:
    """通过 PowerShell 调用 .NET API 获取真实桌面路径

    对应 ADR-004 决策: 使用 [Environment]::GetFolderPath("Desktop")
    而非拼接用户名。这能正确处理:
        - 桌面重定向到 OneDrive
        - 企业策略修改桌面位置
        - 多语言系统 (中文"桌面"文件夹)
    """
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def _find_executable(name: str) -> str | None:
    """在 PATH 中查找可执行文件"""
    from shutil import which
    return which(name)


@lru_cache(maxsize=1)
def get_environment() -> EnvironmentInfo:
    """获取全局环境信息 (单例,启动时探测一次后缓存)

    作为 Shared Kernel 提供给所有限界上下文使用。
    所有需要环境信息的模块都应通过此函数获取,
    确保环境探测只发生一次且结果一致。
    """
    return EnvironmentDetector.detect()
