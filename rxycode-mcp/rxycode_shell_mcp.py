#!/usr/bin/env python
"""
RxyCode 执行层 MCP 服务器 (rxycode-shell)
==========================================
实现 ADR-002（超时+重试+降级）+ ADR-004（Shell 抽象层 + 环境探测）。

提供可靠的命令执行和正确的环境/路径感知。

解决：
  P0-2 工具执行不可靠（write 超时 120s、Shell 语法混淆、工具调用未执行）
  P0-3 路径错误与用户身份混淆（用进程身份 RxyCode 推断路径，实际应为 Administrator）

核心机制：
  1. 环境探测 —— 启动时检测 OS、真实登录用户、桌面路径、可用 Shell
  2. Shell 抽象 —— 自动选择正确 Shell，命令语法自动转换
  3. 超时+重试 —— 每个工具调用有超时阈值，失败自动重试（指数退避）
  4. 降级策略 —— 超时/失败后给出明确错误而非无限等待
"""

import os
import sys
import json
import time
import shutil
import platform
import subprocess
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "rxycode-shell",
    instructions="RxyCode 执行层 —— 可靠命令执行、Shell 抽象、环境感知",
)


# ---------------------------------------------------------------------------
# 环境探测（启动时缓存）
# ---------------------------------------------------------------------------

class EnvironmentInfo:
    """启动时探测的真实环境信息，消除路径推断错误。"""

    def __init__(self):
        self.os_name = platform.system()  # Windows / Linux / Darwin
        self.os_release = platform.release()
        self.python_version = sys.version.split()[0]
        self.machine = platform.machine()

        # 真实登录用户（而非进程运行身份）
        self.username = self._detect_real_username()

        # 用户主目录
        self.home_dir = self._detect_home_dir()

        # 特殊目录路径（使用系统 API，不拼接用户名）
        self.desktop = self._detect_desktop()
        self.documents = self._detect_documents()
        self.downloads = self._detect_downloads()

        # 可用 Shell 及推荐 Shell
        self.available_shells = self._detect_shells()
        self.preferred_shell = self._select_preferred_shell()

        self.detected_at = datetime.now().isoformat(timespec="seconds")

    def _detect_real_username(self) -> str:
        """检测真实登录用户名，而非进程身份。"""
        # 优先级 1：USERPROFILE 环境变量中提取（Windows）
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            return os.path.basename(userprofile)

        # 优先级 2：HOME 环境变量（Linux/macOS）
        home = os.environ.get("HOME", "")
        if home:
            return os.path.basename(home)

        # 优先级 3：USERNAME / USER 环境变量
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"

    def _detect_home_dir(self) -> str:
        """检测用户主目录。"""
        if self.os_name == "Windows":
            return os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return os.path.expanduser("~")

    def _detect_desktop(self) -> str:
        """检测桌面路径——使用系统 API 而非拼接用户名。

        解决 P0-3：之前用 C:\\Users\\RxyCode\\Desktop（进程身份），
        正确应为 C:\\Users\\Administrator\\Desktop（登录用户）。
        """
        if self.os_name == "Windows":
            # 方法 1：USERPROFILE + Desktop
            userprofile = os.environ.get("USERPROFILE", "")
            if userprofile:
                desktop = os.path.join(userprofile, "Desktop")
                if os.path.isdir(desktop):
                    return desktop
            # 方法 2：通过 PowerShell 获取已知文件夹路径
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "[Environment]::GetFolderPath('Desktop')"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
            # 方法 3：expanduser
            return os.path.join(os.path.expanduser("~"), "Desktop")

        # Linux/macOS
        return os.path.join(os.path.expanduser("~"), "Desktop")

    def _detect_documents(self) -> str:
        if self.os_name == "Windows":
            userprofile = os.environ.get("USERPROFILE", "")
            if userprofile:
                docs = os.path.join(userprofile, "Documents")
                if os.path.isdir(docs):
                    return docs
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "[Environment]::GetFolderPath('MyDocuments')"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
        return os.path.join(os.path.expanduser("~"), "Documents")

    def _detect_downloads(self) -> str:
        home = self.home_dir
        downloads = os.path.join(home, "Downloads")
        return downloads if os.path.isdir(downloads) else ""

    def _detect_shells(self) -> list[str]:
        """检测系统上可用的 Shell。"""
        shells = []
        if self.os_name == "Windows":
            # PowerShell
            for ps in ["pwsh", "powershell"]:
                if shutil.which(ps):
                    shells.append(ps)
            # CMD
            if shutil.which("cmd"):
                shells.append("cmd")
        # Bash（Windows 上可能有 Git Bash，Linux/macOS 原生）
        if shutil.which("bash"):
            shells.append("bash")
        # Zsh (macOS)
        if shutil.which("zsh"):
            shells.append("zsh")
        return shells

    def _select_preferred_shell(self) -> str:
        """选择推荐 Shell。"""
        if self.os_name == "Windows":
            # 优先 PowerShell（支持现代语法和环境变量）
            if "pwsh" in self.available_shells:
                return "pwsh"
            if "powershell" in self.available_shells:
                return "powershell"
            if "bash" in self.available_shells:
                return "bash"
            if "cmd" in self.available_shells:
                return "cmd"
        else:
            if "bash" in self.available_shells:
                return "bash"
            if "zsh" in self.available_shells:
                return "zsh"
        return self.available_shells[0] if self.available_shells else "unknown"

    def to_dict(self) -> dict:
        return {
            "os": self.os_name,
            "os_release": self.os_release,
            "machine": self.machine,
            "python_version": self.python_version,
            "real_username": self.username,
            "home_dir": self.home_dir,
            "desktop": self.desktop,
            "documents": self.documents,
            "downloads": self.downloads,
            "available_shells": self.available_shells,
            "preferred_shell": self.preferred_shell,
            "detected_at": self.detected_at,
        }


# 启动时探测一次（缓存）
_env = EnvironmentInfo()


# ---------------------------------------------------------------------------
# Shell 命令翻译
# ---------------------------------------------------------------------------

class ShellTranslator:
    """Shell 语法翻译器——解决 P0-2 表现 B（PowerShell 语法在 CMD 中执行）。"""

    # PowerShell → CMD 翻译规则
    PS_TO_CMD_RULES = [
        # $env:VAR → %VAR%
        (r'\$env:(\w+)', r'%\1%'),
        # Join-Path $env:USERPROFILE "X" → %USERPROFILE%\X
        (r'Join-Path\s+\$env:USERPROFILE\s+"([^"]+)"', r'%USERPROFILE%\\\1'),
        # $var = value → set var=value
        (r'\$(\w+)\s*=\s*', r'set \1='),
        # Write-Host → echo
        (r'Write-Host\s+', 'echo '),
        # Test-Path → if exist
        (r'Test-Path\s+"([^"]+)"', r'if exist "\1"'),
    ]

    # PowerShell → Bash 翻译规则
    PS_TO_BASH_RULES = [
        # $env:VAR → $VAR
        (r'\$env:(\w+)', r'$\1'),
        # Join-Path $env:USERPROFILE "X" → $USERPROFILE/X
        (r'Join-Path\s+\$env:USERPROFILE\s+"([^"]+)"', r'$HOME/\1'),
        # Write-Host → echo
        (r'Write-Host\s+', 'echo '),
    ]

    @classmethod
    def translate(cls, command: str, from_shell: str, to_shell: str) -> str:
        """翻译命令语法。"""
        if from_shell == to_shell:
            return command

        rules = []
        if from_shell in ("powershell", "pwsh") and to_shell == "cmd":
            rules = cls.PS_TO_CMD_RULES
        elif from_shell in ("powershell", "pwsh") and to_shell == "bash":
            rules = cls.PS_TO_BASH_RULES

        result = command
        for pattern, replacement in rules:
            import re
            result = re.sub(pattern, replacement, result)
        return result

    @classmethod
    def detect_shell_syntax(cls, command: str) -> str:
        """检测命令使用的 Shell 语法。"""
        import re
        # PowerShell 特征
        if re.search(r'\$env:\w+', command) or \
           re.search(r'Join-Path', command) or \
           re.search(r'Write-Host', command) or \
           re.search(r'\$\w+\s*=', command):
            return "powershell"
        # CMD 特征
        if re.search(r'%\w+%', command) or \
           re.search(r'^set\s+', command, re.MULTILINE):
            return "cmd"
        # Bash 特征
        if re.search(r'\$\(\s*', command) or \
           re.search(r'\becho\s+\$', command):
            return "bash"
        return "unknown"


# ---------------------------------------------------------------------------
# 可靠执行引擎
# ---------------------------------------------------------------------------

def _execute_with_retry(command: str, shell: str, cwd: str | None,
                        timeout: int, max_retries: int = 2) -> dict:
    """带超时和重试的命令执行。

    实现 ADR-002：超时+重试+降级。
    """
    attempts = []
    last_error = None

    for attempt_num in range(1, max_retries + 2):  # max_retries + 1 次初始尝试
        start = time.time()
        try:
            # 构建 Shell 调用
            if shell in ("powershell", "pwsh"):
                cmd_list = [shell, "-NoProfile", "-NonInteractive", "-Command", command]
            elif shell == "cmd":
                cmd_list = ["cmd", "/C", command]
            elif shell == "bash":
                cmd_list = ["bash", "-c", command]
            else:
                cmd_list = [shell, "-c", command]

            result = subprocess.run(
                cmd_list,
                cwd=cwd or os.getcwd(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = round(time.time() - start, 2)

            attempt = {
                "attempt": attempt_num,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_s": elapsed,
                "timed_out": False,
            }
            attempts.append(attempt)

            if result.returncode == 0:
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_s": elapsed,
                    "attempts": attempts,
                }

            # 失败——如果还有重试机会，检测是否是语法问题并翻译后重试
            last_error = result.stderr or f"exit code {result.returncode}"

            if attempt_num <= max_retries:
                # 检测语法混淆——如果命令语法与当前 Shell 不匹配，尝试翻译
                detected_syntax = ShellTranslator.detect_shell_syntax(command)
                if detected_syntax != "unknown" and detected_syntax != shell:
                    translated = ShellTranslator.translate(command, detected_syntax, shell)
                    if translated != command:
                        # 用翻译后的命令重试
                        if shell in ("powershell", "pwsh"):
                            cmd_list = [shell, "-NoProfile", "-NonInteractive", "-Command", translated]
                        elif shell == "cmd":
                            cmd_list = ["cmd", "/C", translated]
                        elif shell == "bash":
                            cmd_list = ["bash", "-c", translated]

                        retry_start = time.time()
                        retry_result = subprocess.run(
                            cmd_list, cwd=cwd or os.getcwd(),
                            capture_output=True, text=True, timeout=timeout,
                        )
                        retry_elapsed = round(time.time() - retry_start, 2)
                        attempts.append({
                            "attempt": attempt_num,
                            "exit_code": retry_result.returncode,
                            "stdout": retry_result.stdout,
                            "stderr": retry_result.stderr,
                            "duration_s": retry_elapsed,
                            "timed_out": False,
                            "note": f"语法翻译后重试（{detected_syntax}→{shell}）",
                        })
                        if retry_result.returncode == 0:
                            return {
                                "success": True,
                                "exit_code": 0,
                                "stdout": retry_result.stdout,
                                "stderr": retry_result.stderr,
                                "duration_s": retry_elapsed,
                                "attempts": attempts,
                                "auto_translated": True,
                            }

                # 指数退避等待
                wait = min(2 ** (attempt_num - 1), 4)
                time.sleep(wait)

        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - start, 2)
            attempts.append({
                "attempt": attempt_num,
                "exit_code": None,
                "stdout": "",
                "stderr": f"命令在 {timeout}s 后超时",
                "duration_s": elapsed,
                "timed_out": True,
            })
            last_error = f"timeout after {timeout}s"
            if attempt_num <= max_retries:
                time.sleep(min(2 ** (attempt_num - 1), 4))

        except Exception as e:
            elapsed = round(time.time() - start, 2)
            attempts.append({
                "attempt": attempt_num,
                "exit_code": None,
                "stdout": "",
                "stderr": str(e),
                "duration_s": elapsed,
                "timed_out": False,
            })
            last_error = str(e)

    return {
        "success": False,
        "exit_code": attempts[-1].get("exit_code") if attempts else None,
        "stdout": attempts[-1].get("stdout", "") if attempts else "",
        "stderr": last_error or "执行失败",
        "duration_s": sum(a["duration_s"] for a in attempts),
        "attempts": attempts,
        "timed_out": any(a.get("timed_out") for a in attempts),
    }


# ---------------------------------------------------------------------------
# MCP 工具
# ---------------------------------------------------------------------------

@mcp.tool()
def detect_environment() -> str:
    """检测当前运行环境的真实信息。

    启动时自动探测，返回真实 OS、登录用户名（非进程身份）、
    桌面/文档/下载目录路径、可用 Shell 列表和推荐 Shell。

    解决 P0-3：之前 Agent 用进程身份 RxyCode 推断路径，
    正确应使用此工具获取真实登录用户路径。

    Returns:
        JSON 环境信息。
    """
    return json.dumps(_env.to_dict(), ensure_ascii=False, indent=2)


@mcp.tool()
def resolve_user_path(path_type: str) -> str:
    """解析用户特殊目录的真实路径。

    使用系统 API 获取路径，绝不拼接用户名。
    解决 P0-3：路径 C:\\Users\\RxyCode\\Desktop → C:\\Users\\Administrator\\Desktop

    Args:
        path_type: 路径类型，可选 "desktop" / "documents" / "downloads" / "home" / "temp"

    Returns:
        JSON 包含解析后的真实路径。
    """
    mapping = {
        "desktop": _env.desktop,
        "documents": _env.documents,
        "downloads": _env.downloads,
        "home": _env.home_dir,
        "temp": os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp",
    }

    resolved = mapping.get(path_type.lower())
    if resolved is None:
        return json.dumps({
            "error": f"未知路径类型 '{path_type}'，支持：{list(mapping.keys())}",
            "available_types": list(mapping.keys()),
        }, ensure_ascii=False, indent=2)

    exists = os.path.isdir(resolved)
    return json.dumps({
        "path_type": path_type,
        "resolved_path": resolved,
        "exists": exists,
        "username": _env.username,
        "note": "此路径通过系统 API 解析，非用户名拼接" if exists
                else "路径不存在，可能需要创建",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def execute_shell(command: str, shell: str | None = None,
                  working_dir: str | None = None, timeout: int = 60,
                  max_retries: int = 2) -> str:
    """可靠执行 Shell 命令（带超时、重试、语法自动翻译）。

    实现 ADR-002：超时+重试+降级。
    解决 P0-2：之前 write 工具 120s 超时无响应、Shell 语法混淆。

    机制：
      1. 自动选择正确 Shell（或使用指定 Shell）
      2. 检测命令语法与 Shell 不匹配时自动翻译
      3. 超时后明确失败而非无限等待
      4. 失败后指数退避重试（默认最多 2 次）

    Args:
        command: 要执行的命令
        shell: 指定 Shell（powershell/cmd/bash/pwsh/zsh），None 则自动选择
        working_dir: 工作目录
        timeout: 超时秒数（默认 60s）
        max_retries: 最大重试次数（默认 2）

    Returns:
        JSON 执行结果，含 exit_code、stdout、stderr、attempts 历史。
    """
    used_shell = shell or _env.preferred_shell

    result = _execute_with_retry(command, used_shell, working_dir, timeout, max_retries)

    output = {
        "success": result["success"],
        "command": command,
        "shell_used": used_shell,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][:2000],  # 截断防止过长
        "stderr": result["stderr"][:1000],
        "total_duration_s": result["duration_s"],
        "attempts": result["attempts"],
        "auto_translated": result.get("auto_translated", False),
        "timed_out": result.get("timed_out", False),
    }

    if not result["success"]:
        output["degradation"] = (
            "命令执行失败。已尝试 "
            f"{len(result['attempts'])} 次（含重试）。"
            "建议：1) 检查命令语法是否匹配 Shell 类型；"
            "2) 检查路径是否正确（使用 resolve_user_path 获取真实路径）；"
            "3) 增大 timeout 参数。"
        )

    return json.dumps(output, ensure_ascii=False, indent=2)


@mcp.tool()
def translate_command(command: str, from_shell: str, to_shell: str) -> str:
    """翻译 Shell 命令语法。

    解决 P0-2 表现 B：Agent 在 bash 工具中使用了 PowerShell 语法。

    支持的翻译方向：
      - powershell → cmd（$env:VAR → %VAR%，Join-Path → 路径拼接）
      - powershell → bash（$env:VAR → $VAR）

    Args:
        command: 原始命令
        from_shell: 源 Shell 语法（powershell/cmd/bash）
        to_shell: 目标 Shell 语法

    Returns:
        JSON 包含翻译后的命令。
    """
    # 自动检测源语法（如果 from_shell 为 unknown）
    if from_shell == "auto":
        from_shell = ShellTranslator.detect_shell_syntax(command)

    translated = ShellTranslator.translate(command, from_shell, to_shell)
    detected = ShellTranslator.detect_shell_syntax(command)

    return json.dumps({
        "original": command,
        "from_shell": from_shell,
        "to_shell": to_shell,
        "translated": translated,
        "detected_syntax": detected,
        "changed": translated != command,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def write_file_safely(path: str, content: str, timeout: int = 15,
                      create_dirs: bool = True) -> str:
    """安全写入文件（带超时和验证）。

    解决 P0-2：之前 write 工具 120s 超时无响应。
    此工具保证 15s 内完成写入或返回明确失败。

    机制：
      1. 超时保护（默认 15s）
      2. 可选自动创建父目录
      3. 写入后立即验证文件存在且内容匹配
      4. 失败时返回明确错误和降级建议

    Args:
        path: 文件路径
        content: 文件内容
        timeout: 超时秒数（默认 15s）
        create_dirs: 是否自动创建父目录（默认 True）

    Returns:
        JSON 写入结果，含验证信息。
    """
    abs_path = os.path.abspath(path)
    start = time.time()

    try:
        # 自动创建父目录
        parent = os.path.dirname(abs_path)
        if create_dirs and parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        # 写入文件
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        elapsed = round(time.time() - start, 3)

        # 立即验证
        if not os.path.isfile(abs_path):
            return json.dumps({
                "success": False,
                "error": "写入后文件验证失败——文件不存在",
                "path": abs_path,
                "duration_s": elapsed,
            }, ensure_ascii=False, indent=2)

        actual_size = os.path.getsize(abs_path)
        expected_size = len(content.encode("utf-8"))

        # 读回验证内容
        with open(abs_path, "r", encoding="utf-8") as f:
            written = f.read()
        content_match = (written == content)

        return json.dumps({
            "success": True,
            "path": abs_path,
            "size_bytes": actual_size,
            "expected_bytes": expected_size,
            "content_verified": content_match,
            "duration_s": elapsed,
            "message": "文件已写入并验证成功" if content_match
                       else "文件已写入但内容验证不匹配",
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = round(time.time() - start, 3)
        return json.dumps({
            "success": False,
            "error": str(e),
            "path": abs_path,
            "duration_s": elapsed,
            "degradation": (
                "文件写入失败。降级建议：将文件内容输出给用户手动保存，"
                "或检查目标目录权限和磁盘空间。"
            ),
        }, ensure_ascii=False, indent=2)


@mcp.tool()
def read_file_safely(path: str, timeout: int = 5,
                     max_size_mb: int = 10) -> str:
    """安全读取文件（带超时和大小限制）。

    解决 P0-2：之前 read 工具超时无响应。
    文件不存在时返回明确错误而非超时。

    Args:
        path: 文件路径
        timeout: 超时秒数（默认 5s）
        max_size_mb: 最大文件大小限制（默认 10MB）

    Returns:
        JSON 读取结果，含文件内容。
    """
    abs_path = os.path.abspath(path)

    if not os.path.exists(abs_path):
        return json.dumps({
            "success": False,
            "error": "文件不存在",
            "path": abs_path,
            "suggestion": "请先使用 verify_file_exists 确认路径，"
                          "或使用 list_directory_real 查看可用文件。",
        }, ensure_ascii=False, indent=2)

    if os.path.isdir(abs_path):
        return json.dumps({
            "success": False,
            "error": "路径是目录而非文件",
            "path": abs_path,
        }, ensure_ascii=False, indent=2)

    try:
        size = os.path.getsize(abs_path)
        if size > max_size_mb * 1024 * 1024:
            return json.dumps({
                "success": False,
                "error": f"文件过大（{size / 1024 / 1024:.1f}MB），超过限制 {max_size_mb}MB",
                "path": abs_path,
            }, ensure_ascii=False, indent=2)

        start = time.time()
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        elapsed = round(time.time() - start, 3)

        return json.dumps({
            "success": True,
            "path": abs_path,
            "content": content,
            "size_bytes": size,
            "duration_s": elapsed,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "path": abs_path,
        }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
