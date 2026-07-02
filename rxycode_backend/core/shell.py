"""Shell 抽象层 - 修复 P0-2B Shell 语法混淆

用户反馈问题 (P0-2B):
    Agent 在 bash 工具中使用了 PowerShell 语法:
        $desktopPath = Join-Path $env:USERPROFILE "Desktop"
    导致命令执行失败:
        '$desktop' 不是内部或外部命令,也不是可运行的程序或批处理文件。
        [exit code: 1]
    Agent 混淆了 PowerShell 和 CMD/Bash 的语法,且在失败后未能自动纠正。

架构根因:
    执行层无 Shell 抽象,语法不兼容直接执行导致失败。

修复方案 (ADR-004):
    1. 启动时探测最佳 Shell (PowerShell 优先)
    2. Shell 统一接口: detect_shell / translate_command / execute
    3. 执行前语法校验: 检测 PowerShell 变量 ($) 在 CMD 上下文中的误用
    4. 语法自动转换: 检测到不兼容语法时转换后重试
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from .environment import EnvironmentInfo, ShellType, get_environment


@dataclass
class ExecResult:
    """命令执行结果"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    shell_used: ShellType
    command_executed: str
    translated: bool = False  # 是否经过语法转换

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class ShellSyntaxError(Exception):
    """Shell 语法不兼容错误 (可自动转换)"""


class ShellExecutor:
    """Shell 抽象层 - 统一跨平台命令执行

    修复 P0-2B 的核心:
        旧代码: 直接执行 Agent 生成的命令,不校验语法 -> PowerShell 语法在 CMD 中失败
        新代码: 执行前校验语法,不兼容时自动转换,确保命令在正确的 Shell 中运行
    """

    def __init__(self, env: EnvironmentInfo | None = None) -> None:
        self.env = env or get_environment()

    # ---------------------------------------------------------------
    # 语法校验 - 检测 Shell 语法不兼容 (P0-2B 修复核心)
    # ---------------------------------------------------------------

    def validate_syntax(self, command: str, target_shell: ShellType | None = None) -> list[str]:
        """校验命令语法是否与目标 Shell 兼容

        返回不兼容的语法问题列表,空列表表示兼容。

        这是 P0-2B 的关键修复:
            在执行前检测 PowerShell 变量 ($) 在 CMD 上下文中的误用,
            避免直接执行导致 '$desktop' 不是内部或外部命令的错误。
        """
        target = target_shell or self.env.shell
        issues: list[str] = []

        if target == ShellType.CMD:
            issues.extend(self._check_powershell_in_cmd(command))
        elif target == ShellType.BASH:
            issues.extend(self._check_powershell_in_bash(command))
            issues.extend(self._check_cmd_in_bash(command))

        return issues

    def _check_powershell_in_cmd(self, command: str) -> list[str]:
        """检测 PowerShell 语法在 CMD 中的误用"""
        issues = []
        # PowerShell 变量: $env:, $varName
        if re.search(r"\$env:", command, re.IGNORECASE):
            issues.append("CMD 不支持 PowerShell 的 $env: 变量语法")
        if re.search(r"\$\w+", command):
            issues.append("CMD 不支持 PowerShell 的 $ 变量语法")
        # PowerShell cmdlet
        if re.search(r"\b(Get-|Set-|New-|Join-Path|Write-Output)\w*-?\w*\b", command):
            issues.append("CMD 不支持 PowerShell cmdlet (如 Join-Path)")
        # PowerShell 调用 .NET
        if "[Environment]" in command or "::" in command:
            issues.append("CMD 不支持 PowerShell 的 .NET 调用语法")
        return issues

    def _check_powershell_in_bash(self, command: str) -> list[str]:
        """检测 PowerShell 语法在 Bash 中的误用"""
        issues = []
        if re.search(r"\$env:", command, re.IGNORECASE):
            issues.append("Bash 不支持 PowerShell 的 $env: 变量语法,应使用 $ENV 或直接 $变量")
        if re.search(r"\b(Get-|Set-|New-|Join-Path)\w*-?\w*\b", command):
            issues.append("Bash 不支持 PowerShell cmdlet")
        return issues

    def _check_cmd_in_bash(self, command: str) -> list[str]:
        """检测 CMD 语法在 Bash 中的误用"""
        issues = []
        if re.search(r"%\w+%", command):
            issues.append("Bash 不支持 CMD 的 %变量% 语法,应使用 $变量")
        return issues

    # ---------------------------------------------------------------
    # 语法转换 - 自动修复不兼容语法
    # ---------------------------------------------------------------

    def translate_command(self, command: str, target_shell: ShellType | None = None) -> str:
        """将命令转换为目标 Shell 兼容的语法

        当检测到语法不兼容时,尝试自动转换而非直接失败。
        转换不了的抛出 ShellSyntaxError。
        """
        target = target_shell or self.env.shell

        if target == ShellType.POWERSHELL:
            return self._to_powershell(command)
        elif target == ShellType.CMD:
            return self._to_cmd(command)
        elif target in (ShellType.BASH, ShellType.ZSH):
            return self._to_bash(command)
        return command

    def _to_powershell(self, command: str) -> str:
        """转换为 PowerShell 语法"""
        result = command
        # CMD %VAR% -> PowerShell $env:VAR
        result = re.sub(r"%(\w+)%", r"$env:\1", result)
        return result

    def _to_cmd(self, command: str) -> str:
        """转换为 CMD 语法

        复杂的 PowerShell 语法无法安全转换到 CMD,
        此时应强制使用 PowerShell 执行而非降级到 CMD。
        """
        issues = self._check_powershell_in_cmd(command)
        if issues:
            raise ShellSyntaxError(
                f"命令包含 CMD 不兼容的 PowerShell 语法,无法自动转换: {'; '.join(issues)}。"
                f"建议: 将目标 Shell 切换为 PowerShell 执行此命令。"
            )
        return command

    def _to_bash(self, command: str) -> str:
        """转换为 Bash 语法"""
        result = command
        # PowerShell $env:VAR -> Bash $VAR
        result = re.sub(r"\$env:(\w+)", r"$\1", result, flags=re.IGNORECASE)
        # CMD %VAR% -> Bash $VAR
        result = re.sub(r"%(\w+)%", r"$\1", result)
        return result

    # ---------------------------------------------------------------
    # 执行 - 统一接口,自动处理 Shell 选择与语法
    # ---------------------------------------------------------------

    def execute(
        self,
        command: str,
        timeout: int = 60,
        cwd: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ExecResult:
        """执行命令 - 自动选择最佳 Shell 并校验语法

        执行流程 (修复 P0-2B):
            1. 用默认 Shell 校验语法
            2. 若不兼容,尝试转换语法
            3. 转换失败则切换到兼容的 Shell (如 PowerShell)
            4. 执行并返回结构化结果
        """
        import time
        start = time.time()

        shell_to_use = self.env.shell
        command_to_run = command
        translated = False

        # 步骤 1: 语法校验
        issues = self.validate_syntax(command, shell_to_use)
        if issues:
            # 步骤 2: 尝试转换语法
            try:
                command_to_run = self.translate_command(command, shell_to_use)
                translated = True
            except ShellSyntaxError:
                # 步骤 3: 转换失败,切换 Shell
                # CMD 不兼容 PowerShell 语法 -> 切换到 PowerShell
                if shell_to_use == ShellType.CMD:
                    shell_to_use = ShellType.POWERSHELL
                    command_to_run = command  # 用原始命令,PowerShell 能执行
                    translated = False
                else:
                    # 其他情况无法自动修复,抛出明确错误
                    raise ShellSyntaxError(
                        f"命令语法与所有可用 Shell 不兼容: {'; '.join(issues)}"
                    )

        # 步骤 4: 执行
        cmd_args = self._build_command(command_to_run, shell_to_use)
        full_env = self._build_env(env_vars)

        try:
            proc = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=full_env,
                encoding="utf-8",
                errors="replace",
            )
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_ms=duration_ms,
                shell_used=shell_to_use,
                command_executed=command_to_run,
                translated=translated,
            )
        except subprocess.TimeoutExpired as e:
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                exit_code=-1,
                stdout=e.stdout or "" if isinstance(e.stdout, str) else "",
                stderr=f"命令执行超时 (超过 {timeout}s)",
                duration_ms=duration_ms,
                shell_used=shell_to_use,
                command_executed=command_to_run,
                translated=translated,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                exit_code=-2,
                stdout="",
                stderr=f"命令执行异常: {type(e).__name__}: {e}",
                duration_ms=duration_ms,
                shell_used=shell_to_use,
                command_executed=command_to_run,
                translated=translated,
            )

    def _build_command(self, command: str, shell: ShellType) -> list[str]:
        """构建 subprocess 命令参数"""
        if shell == ShellType.POWERSHELL:
            return [self.env.shell_path, "-NoProfile", "-NonInteractive", "-Command", command]
        elif shell == ShellType.CMD:
            return [self.env.shell_path, "/c", command]
        else:  # bash/zsh
            return [self.env.shell_path, "-c", command]

    def _build_env(self, env_vars: dict[str, str] | None) -> dict[str, str]:
        """构建环境变量"""
        full_env = dict(os.environ) if (os := _get_os_module()) else {}
        if env_vars:
            full_env.update(env_vars)
        return full_env


def _get_os_module():
    """延迟导入 os,避免循环依赖"""
    import os
    return os


def safe_execute(command: str, timeout: int = 60, cwd: str | None = None) -> ExecResult:
    """便捷函数: 安全执行命令

    自动处理 Shell 选择、语法校验、超时。
    供 bash 工具调用,修复 P0-2B。
    """
    executor = ShellExecutor()
    return executor.execute(command, timeout=timeout, cwd=cwd)
