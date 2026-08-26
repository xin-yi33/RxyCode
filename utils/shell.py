"""Cross-platform command execution with enforceable sandbox policies."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
import locale
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from typing import Any

import psutil

from ..config.settings import load_config
from ..core.session_runtime import (
    current_working_directory,
    initial_working_directory,
)


_MONITOR_INTERVAL_SECONDS = 0.05
_DOCKER_CID_PATTERN = re.compile(r"^[a-fA-F0-9]{12,64}$")

# POSIX heredoc: `python - <<'PY'` ... `PY`. The `head` group keeps any
# leading command prefix (e.g. `cd /d X && python - <<'PY'`), the `prog`
# group captures the interpreter, and `body` is everything up to the line
# that holds exactly the closing marker.
_HEREDOC_RE = re.compile(
    r"^(?P<head>.*?)"
    r"(?P<prog>[A-Za-z0-9_./+-]+?)\s+-\s*<<['\"]?"
    r"(?P<marker>[A-Za-z_][A-Za-z0-9_]*)['\"]?\s*\r?\n"
    r"(?P<body>.*?)"
    r"^\s*(?P=marker)\s*$",
    flags=re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class _ExecutionPolicy:
    mode: str
    cwd: Path | None
    workspace_root: Path | None
    docker_image: str
    docker_network: str
    max_memory_mb: int
    max_cpus: float
    max_processes: int


@dataclass(frozen=True)
class _ResourceViolation:
    resource: str
    observed: int
    limit: int
    unit: str = ""

    def message(self) -> str:
        suffix = self.unit
        return (
            f"[resource_limit] {self.resource} limit exceeded: "
            f"observed={self.observed}{suffix}, limit={self.limit}{suffix}"
        )


def _failure(
    message: str,
    *,
    error_type: str,
    resource_limit: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "stdout": "",
        "stderr": message,
        "exit_code": -1,
        "success": False,
        "error_type": error_type,
    }
    if resource_limit is not None:
        result["resource_limit"] = resource_limit
    return result


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_config_value(
    execution: dict[str, Any],
    sandbox: dict[str, Any],
    docker: dict[str, Any],
    limits: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    """Read flat execution keys first while supporting grouped config."""
    if key in execution:
        return execution[key]
    if key in limits:
        return limits[key]
    if key in docker:
        return docker[key]
    if key in sandbox:
        return sandbox[key]
    return default


def _non_negative_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"execution.{key} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"execution.{key} must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise ValueError(f"execution.{key} must be a non-negative integer")
    return parsed


def _non_negative_float(value: Any, key: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"execution.{key} must be a non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"execution.{key} must be a non-negative number"
        ) from exc
    if parsed < 0:
        raise ValueError(f"execution.{key} must be a non-negative number")
    return parsed


def _resolve_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except (ValueError, OSError):
        return False
    return True


class ShellExecutor:
    def __init__(self):
        self.os_name = sys.platform
        self.shell_type = self._detect_shell()
        self.user_home = str(Path.home())
        self.desktop_path = self._detect_desktop()

    def _detect_shell(self) -> str:
        if self.os_name == "win32":
            return "powershell" if self._has_powershell() else "cmd"
        return "bash"

    def _has_powershell(self) -> bool:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "echo ok"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _detect_desktop(self) -> str:
        if self.os_name == "win32":
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "[Environment]::GetFolderPath('Desktop')",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
        return str(Path.home() / "Desktop")

    def _translate_heredoc(self, command: str) -> str | None:
        """Rewrite a POSIX heredoc into a PowerShell here-string invocation.

        Windows PowerShell has no ``<<'MARKER'`` redirection. Agent-written
        bash habits like ``python - <<'PY'`` (read script from stdin) fail on
        PowerShell with a parser error. Rewrite the heredoc as ``python -c``
        with a here-string argument so the embedded script still runs.

        Returns the rewritten command, or ``None`` when the command does not
        start with an interpreter-fed heredoc.
        """
        match = _HEREDOC_RE.match(command)
        if not match:
            return None
        head = match.group("head")
        # The head may carry cmd-style chains (`cd /d X && python - <<'PY'`);
        # translate those bits the same way the powershell branch would.
        head = self._translate_powershell_head(head)
        prog = match.group("prog")
        body = match.group("body").rstrip("\r\n")
        return f"{head}{prog} -c @'\n{body}\n'@"

    def _translate_powershell_head(self, head: str) -> str:
        """Translate cmd/POSIX bits that commonly prefix a heredoc head."""
        if "&&" in head:
            head = re.sub(r"\s*&&\s*", "; ", head)
        head = re.sub(
            r"\bcd\s+/d\s+",
            "Set-Location ",
            head,
            flags=re.IGNORECASE,
        )
        head = re.sub(
            r"(?<![\w-])\bls\s+(-[alAR]+)(?=\s|[;&|]|$)",
            lambda m: "Get-ChildItem"
            + (" -Force" if "a" in m.group(1).lower() else "")
            + (" -Recurse" if "r" in m.group(1).lower() else ""),
            head,
            flags=re.IGNORECASE,
        )
        # The Docker adapter exposes the session root as /workspace.  When
        # the same command is executed directly on Windows, the session cwd
        # is already that root; mapping it to C:\\workspace is both wrong and
        # expensive because it causes a failed tool round and model repair.
        head = re.sub(
            r"\bcd\s+/workspace(?:/([^\s;&|]+))?",
            lambda m: "Set-Location ."
            if not m.group(1)
            else "Set-Location .\\" + m.group(1).replace("/", "\\"),
            head,
            flags=re.IGNORECASE,
        )
        return head

    def _is_powershell_syntax(self, command: str) -> bool:
        patterns = [
            r"\$\w+\s*=",
            r"\$env:",
            r"\(Join-Path",
            r"Write-Host",
            r"Test-Path",
            r"Get-ChildItem",
            r"Set-Location",
            r"\[Environment\]::",
            r"powershell",
            # PowerShell call operator: `& 'C:\path\app.exe' args`
            r"^\s*&\s*['\"]",
        ]
        return any(re.search(pattern, command) for pattern in patterns)

    @staticmethod
    def _protect_quoted(command: str) -> tuple[str, list[tuple[str, int]]]:
        """保护引号内的文本：替换为占位符，避免转换误改（luna R2/R3）。

        返回 (masked, 还原表)。还原表元素为 (原文, 占位符索引)。
        - 成对引号（' 和 "）整段保护；
        - 转义引号（\\" 或反引号 `）不结束保护范围；
        - 未闭合引号：从引号开始到行尾全部保护（luna R3-1）；
        - 哨兵使用随机前缀，避免与原文碰撞（luna R3-3）。
        """
        import uuid

        sentinel = f"\x00DSMLQ{uuid.uuid4().hex[:8]}\x00"
        masked_chars: list[str] = []
        restores: list[tuple[str, int]] = []
        i = 0
        n = len(command)
        quote: str | None = None
        quoted_start = -1
        while i < n:
            ch = command[i]
            if quote is None:
                if ch in ("'", '"'):
                    quote = ch
                    quoted_start = i
                else:
                    masked_chars.append(ch)
                i += 1
                continue
            # 在引号内：处理转义
            if ch == "\\" and i + 1 < n:
                i += 2  # 跳过转义字符对
                continue
            if ch == "`" and i + 1 < n:
                i += 2  # PowerShell 反引号转义
                continue
            if ch == quote:
                quoted = command[quoted_start:i + 1]
                idx = len(restores)
                restores.append((quoted, idx))
                masked_chars.append(f"{sentinel}{idx}{sentinel}")
                quote = None
                i += 1
                continue
            i += 1
        if quote is not None:
            # 未闭合引号：保护到行尾（luna R3-1）
            quoted = command[quoted_start:]
            idx = len(restores)
            restores.append((quoted, idx))
            masked_chars.append(f"{sentinel}{idx}{sentinel}")
        return "".join(masked_chars), restores

    @staticmethod
    def _restore_quoted(masked: str, restores: list[tuple[str, int]]) -> str:
        """把保护占位符还原为原始引号文本（单次扫描，luna R3-3）。"""
        if not restores:
            return masked
        import re

        pattern = re.compile(r"\x00DSMLQ[0-9a-f]{8}\x00(\d+)\x00DSMLQ[0-9a-f]{8}\x00")
        by_idx = {idx: quoted for quoted, idx in restores}

        def _repl(m):
            return by_idx.get(int(m.group(1)), m.group(0))

        return pattern.sub(_repl, masked)

    def translate_command(self, command: str) -> tuple[str, str]:
        needs_powershell = self._is_powershell_syntax(command)
        actual_shell = self.shell_type
        if needs_powershell and self.shell_type == "cmd":
            actual_shell = "powershell"

        # POSIX heredocs have no PowerShell equivalent. Rewrite
        # `python - <<'PY'` into a here-string so agent-written bash-style
        # Python snippets run on Windows PowerShell.
        if actual_shell in ("cmd", "powershell"):
            heredoc = self._translate_heredoc(command)
            if heredoc is not None:
                return heredoc, "powershell"

        if actual_shell == "powershell":
            # grep/find 的 pattern 参数在引号内，必须先于引号保护解析。
            command = self._translate_grep_find(command)
            # ``%~dp0`` is a cmd batch-file variable. Outside a batch file,
            # the session workdir is the meaningful equivalent.
            command = re.sub(r"%~dp0", ".", command, flags=re.IGNORECASE)
            # luna R2: 保护引号内文本，转换只作用于引号外，避免误改
            # echo "2>/dev/null" 之类的输出文本。
            masked, quoted_restores = self._protect_quoted(command)
            command = self._translate_powershell_outside_quotes(masked)
            command = self._restore_quoted(command, quoted_restores)
            # Keep stderr from native version probes inside cmd.exe. If the
            # model already emitted ``cmd /c "java -version" 2>&1``, leaving
            # the redirection outside makes PowerShell classify Java's normal
            # version stderr as a terminating error.
            command = re.sub(
                r'(?<![\w-])\bcmd(?:\.exe)?\s+/c\s+(["\'])'
                r'(java|javac|python3?|node|npm|mvn|gradle)\s+'
                r'(--version|-version)\1\s+2>&1',
                lambda m: (
                    f'cmd.exe /d /c "{m.group(2)} {m.group(3)} 2>&1"'
                ),
                command,
                flags=re.IGNORECASE,
            )
            command = self._wrap_mysql_client_for_powershell(command)
        elif actual_shell == "cmd":
            command = command.replace("$env:USERPROFILE", "%USERPROFILE%")
            command = command.replace("$env:APPDATA", "%APPDATA%")
            command = command.replace("$env:LOCALAPPDATA", "%LOCALAPPDATA%")
            command = command.replace("$env:TEMP", "%TEMP%")
            command = command.replace("powershell -Command ", "")
            command = command.replace("powershell -c ", "")
        return command, actual_shell

    @staticmethod
    def _ps_single_quote(text: str) -> str:
        """PowerShell 安全字符串字面量（luna R4-1）。

        用单引号包裹，内部 ' 转义为 ''（PS 语义）。避免 json.dumps 的
        反斜杠转义（PS 不认）与 $ 变量展开（双引号会展开）。
        """
        return "'" + (text or "").replace("'", "''") + "'"

    @staticmethod
    def _invokes_mysql_client(command: str) -> bool:
        """True only when the mysql CLI is the program being run.

        ``MYSQL_URL``, ``-like "MYSQL*"``, and ``Get-Command mysql`` must stay
        in PowerShell. A case-insensitive ``\\bmysql\\b`` also matches those.
        """
        if re.search(
            r"\b(Get-Command|Get-ChildItem|Get-Alias|Select-String)\b",
            command,
            flags=re.IGNORECASE,
        ) and re.search(r"mysql\.exe\s+-", command, flags=re.IGNORECASE) is None:
            return False
        if re.search(r"-like\s+[\"']MYSQL", command, flags=re.IGNORECASE):
            return False
        if re.search(
            r'(?:^|[;&|]\s*)\s*(?:&\s*)?["\']?(?:[A-Za-z]:\\[^"\';&|\n]*\\)?mysql\.exe\b',
            command,
            flags=re.IGNORECASE,
        ):
            return True
        return (
            re.search(
                r"(?:^|[;&|]\s*)\s*(?:&\s*)?[\"']?mysql(?:\.exe)?(?:\s+-|\s*$)",
                command,
            )
            is not None
        )

    def _wrap_mysql_client_for_powershell(self, command: str) -> str:
        """Run the mysql CLI through cmd.exe so WinPS 5 does not fail the tool.

        The official client writes password-on-CLI warnings to stderr.
        PowerShell 5 turns that into NativeCommandError even when the query
        succeeded. Unquoted ``-e "SELECT 1; SHOW DATABASES;"`` is also split
        on ``;``. cmd.exe keeps mysql's native status and SQL separators.
        """
        if not self._invokes_mysql_client(command):
            return command
        if re.search(r"(?<![\w-])\bcmd(?:\.exe)?\s+/d\s+/c\b", command, flags=re.IGNORECASE):
            prefix = "$ErrorActionPreference='Continue'; "
            return command if command.startswith(prefix) else prefix + command
        return (
            "$ErrorActionPreference='Continue'; cmd.exe /d /c "
            + self._ps_single_quote(command)
        )

    def _translate_grep_find(self, command: str) -> str:
        """B7: POSIX grep/find → PowerShell（pattern 参数在引号内，
        必须早于引号保护解析）。

        B8: 支持 ``;`` 分隔链中的 grep（如 ``cd X ; grep ...``）——
        用 re.sub 匹配任意命令位置，不限于开头。
        """
        # POSIX `grep -n "pat" file` / `grep 'pat' file` → Select-String
        # （支持多文件参数 file1 file2；DOTALL 支持真实换行 pattern）。
        def _grep_repl(m):
            return (
                "Select-String -Pattern "
                + self._ps_single_quote(m.group(2))
                + " "
                + m.group(3)
            )

        command = re.sub(
            r"(?<![\w-])\bgrep\b(?:\s+-n)?\s+"
            r"([\"'])(.*?)\1\s+(\S.*)$",
            _grep_repl,
            command,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # POSIX `grep -rl "pat" dir` → Select-String 递归目录搜索
        command = re.sub(
            r"(?<![\w-])\bgrep\b(?:\s+-rl|\s+-r\s+-l)?\s+"
            r"([\"'])(.*?)\1\s+(\S+)(\s+\S+)*",
            lambda m: (
                "Get-ChildItem "
                + m.group(3)
                + " -Recurse -File | Select-String -Pattern "
                + self._ps_single_quote(m.group(2))
            ),
            command,
            flags=re.IGNORECASE,
        )
        # POSIX `find <path> -name "pat"` → Get-ChildItem -Recurse -Filter
        command = re.sub(
            r"(?<![\w-])\bfind\s+(\S+)(?:\s+-maxdepth\s+\d+)?\s+-type\s+d\s+-i?name\s+([\"'])(.*?)\2",
            lambda m: (
                "Get-ChildItem -Path "
                + m.group(1)
                + " -Recurse -Directory -Filter "
                + self._ps_single_quote(m.group(3))
            ),
            command,
            flags=re.IGNORECASE,
        )
        command = re.sub(
            r"(?<![\w-])\bfind\s+(\S+)(?:\s+[^|;]*?)?\s+-name\s+"
            r"([\"'])(.*?)\2",
            lambda m: (
                "Get-ChildItem -Path "
                + m.group(1)
                + " -Recurse -Filter "
                + self._ps_single_quote(m.group(3))
            ),
            command,
            flags=re.IGNORECASE,
        )
        return command

    def _translate_powershell_outside_quotes(self, command: str) -> str:
        """对 powershell 分支的引号外文本应用全部 POSIX→PS 转换。"""

        # Windows PowerShell 5.x rejects bash/cmd `&&`; PS 7+ accepts it.
        # Prefer `;` so agent-written cmd-style chains run on WinPS 5.
        if "&&" in command:
            command = re.sub(r"\s*&&\s*", "; ", command)
        # A bare `&` used as a command separator (bash habit:
        # `cmd1 & cmd2 & cmd3`) is a parser error on PowerShell 5, where
        # `&` is the call operator. Rewrite separators to `;`, while
        # preserving the call-operator form `& 'path'` / `& $var`.
        command = re.sub(
            r"\s+&\s+(?=[^'\"$\s&])",
            "; ",
            command,
        )
        # cmd.exe `cd /d X` → PowerShell Set-Location
        command = re.sub(
            r"\bcd\s+/d\s+",
            "Set-Location ",
            command,
            flags=re.IGNORECASE,
        )
        # The container-facing tools use /workspace as a portable session
        # root.  Direct Windows execution must keep the already selected cwd
        # instead of resolving that synthetic path as C:\\workspace.
        command = re.sub(
            r"\bcd\s+/workspace(?:/([^\s;&|]+))?",
            lambda m: "Set-Location ."
            if not m.group(1)
            else "Set-Location .\\" + m.group(1).replace("/", "\\"),
            command,
            flags=re.IGNORECASE,
        )
        # POSIX `ls -la` / `ls -l` / `ls -a` → PowerShell Get-ChildItem,
        # whose aliased `ls` rejects the GNU-style `-la` flag bundles.
        command = re.sub(
            r"(?<![\w-])\bls\s+(-[alAR]+)(?=\s|[;&|]|$)",
            lambda m: "Get-ChildItem"
            + (" -Force" if "a" in m.group(1).lower() else "")
            + (" -Recurse" if "r" in m.group(1).lower() else ""),
            command,
            flags=re.IGNORECASE,
        )
        # POSIX mkdir -p has no direct PowerShell equivalent.  Use -Force so
        # this remains idempotent, and keep each path as a separate argument
        # so quoted paths containing spaces are preserved.
        def _mkdir_repl(match: re.Match[str]) -> str:
            raw_paths = match.group(1).strip()
            # The capture intentionally stops before ``>`` but may retain the
            # numeric descriptor from ``2>&1``.  It is redirection syntax, not
            # a second directory path.
            raw_paths = re.sub(r"\s+\d+\s*$", "", raw_paths).strip()
            paths = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', raw_paths)
            return (
                "New-Item -ItemType Directory -Force -Path "
                + ", ".join(paths)
                + " | Out-Null"
            )

        command = re.sub(
            r"(?<![\w-])\bmkdir\s+-p(?:\s+-[A-Za-z][A-Za-z0-9_-]*)*\s+([^\r\n;&|>]+)",
            _mkdir_repl,
            command,
            flags=re.IGNORECASE,
        )
        # PowerShell's ``mkdir`` alias accepts one positional path, while
        # POSIX/cmd callers commonly pass several paths in one invocation
        # (``mkdir src bin``).  Translating only ``mkdir -p`` left that
        # otherwise harmless command looking successful when followed by
        # ``echo`` even though one or more directories were never created.
        # Handle the plain form as well, but leave an already-generated
        # ``New-Item`` command untouched.
        command = re.sub(
            r"(?<![\w-])\bmkdir\s+(?!-)([^\r\n;&|>]+)",
            _mkdir_repl,
            command,
            flags=re.IGNORECASE,
        )
        # POSIX ``rm -rf path`` is the common clean-build idiom. Preserve its
        # recursive/force semantics explicitly instead of passing ``-rf`` to
        # PowerShell's Remove-Item parameter parser.
        command = re.sub(
            r"(?<![\w-])\brm\s+-rf(?:\s+-[A-Za-z][A-Za-z0-9_-]*)*\s+([^\r\n;&|>]+)",
            lambda m: "Remove-Item -Recurse -Force -LiteralPath " + m.group(1).strip(),
            command,
            flags=re.IGNORECASE,
        )
        # POSIX find . -type f is frequently used for an artifact inventory;
        # without this translation Windows executes find.exe, which has a
        # different syntax and causes a needless model retry.
        command = re.sub(
            r"(?<![\w-])\bfind\s+(\S+)(?:\s+-maxdepth\s+\d+)?\s+-type\s+f\b",
            r"Get-ChildItem -Path \1 -Recurse -File",
            command,
            flags=re.IGNORECASE,
        )
        command = re.sub(
            r"(?<![\w-])\bfind\s+(\S+)(?:\s+-maxdepth\s+\d+)?\s+-type\s+d\b",
            r"Get-ChildItem -Path \1 -Recurse -Directory",
            command,
            flags=re.IGNORECASE,
        )
        # POSIX ``wc -l file`` is commonly used to verify generated source
        # length. PowerShell has no ``wc`` command; keep the same scalar
        # line-count meaning instead of triggering model recovery on Windows.
        command = re.sub(
            r"(?<![\w-])\bwc\s+-l\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)",
            lambda m: "Get-Content -LiteralPath " + m.group(1) + " | Measure-Object -Line | Select-Object -ExpandProperty Lines",
            command,
            flags=re.IGNORECASE,
        )
        # Resolve one or more executables using PowerShell's command lookup.
        command = re.sub(
            r"(?<![\w-])\bwhich\s+([A-Za-z][A-Za-z0-9_.+\-]*(?:\s+[A-Za-z][A-Za-z0-9_.+\-]+)*)",
            lambda m: (
                "Get-Command "
                + ",".join(m.group(1).split())
                + " | Select-Object -ExpandProperty Source"
            ),
            command,
            flags=re.IGNORECASE,
        )
        # POSIX/cmd ``where java`` is parsed as PowerShell's Where-Object
        # alias. Resolve it explicitly so environment probes do not trigger
        # a needless model recovery on Windows. Do not swallow the ``2`` from
        # a following ``2>&1`` redirect (that produced ``Get-Command chrome,2``).
        command = re.sub(
            r"(?<![\w-])\bwhere\s+([A-Za-z][A-Za-z0-9_.+\-]*(?:\s+[A-Za-z][A-Za-z0-9_.+\-]+)*)",
            lambda m: "Get-Command " + ",".join(m.group(1).split()) + " | Select-Object -ExpandProperty Source",
            command,
            flags=re.IGNORECASE,
        )
        # ``uname -a`` is a common POSIX environment probe. Return a stable
        # Windows OS description instead of invoking an unavailable binary.
        command = re.sub(
            r"(?<![\w-])\buname(?:\s+-[A-Za-z]+)?\b",
            "[Environment]::OSVersion.VersionString",
            command,
            flags=re.IGNORECASE,
        )
        # Windows PowerShell reports a non-zero wrapper exit code for several
        # runtimes whose version probe writes informational text to stderr
        # (notably ``java -version``). Let cmd.exe preserve native status.
        command = re.sub(
            r"(?<![\w-])\b(java|javac|python3?|node|npm|mvn|gradle)\s+"
            r"(--version|-version)\b(\s+2>&1)?",
            lambda m: (
                f'cmd.exe /d /c "{m.group(1)} {m.group(2)}'
                f'{" 2>&1" if m.group(3) else ""}"'
            ),
            command,
            flags=re.IGNORECASE,
        )
        # cmd.exe `dir /b <path>` (bare-name listing) → Get-ChildItem -Name.
        # ``ver`` is a cmd.exe builtin; invoking it directly in PowerShell
        # creates a deterministic command-not-found failure and an avoidable
        # recovery round.
        command = re.sub(
            r"(?<![\w-])\bver\b",
            "cmd.exe /d /c ver",
            command,
            flags=re.IGNORECASE,
        )
        # Without this, WinPS parses `/b` as a path and errors.
        command = re.sub(
            r"\bdir\s+/s\s+/b\s+(\S+)",
            lambda m: "Get-ChildItem -Path " + m.group(1) + " -Recurse -Name",
            command,
            flags=re.IGNORECASE,
        )
        command = re.sub(
            r"\bdir\s+/b\b(\s+\S+)?",
            lambda m: "Get-ChildItem"
            + (" -Path " + m.group(1).strip() if m.group(1) else "")
            + " -Name",
            command,
            flags=re.IGNORECASE,
        )
        # cmd.exe `dir <path> /b` (flag after path) → same translation.
        command = re.sub(
            r"\bdir\b(\s+\S+)\s+/b\b",
            lambda m: "Get-ChildItem -Path " + m.group(1).strip() + " -Name",
            command,
            flags=re.IGNORECASE,
        )
        # cmd.exe stdout discard `2>nul` / `2>NUL` → PowerShell `2>$null`.
        command = re.sub(
            r"\b2>nul\b",
            "2>$null",
            command,
            flags=re.IGNORECASE,
        )
        # B7: POSIX stdout discard `2>/dev/null` → PowerShell `2>$null`.
        command = re.sub(
            r"\b2>/dev/null\b",
            "2>$null",
            command,
            flags=re.IGNORECASE,
        )
        # B7: POSIX `pwd` → PowerShell Get-Location（PS 别名可用但显式更稳）。
        # 只在命令位置转换（行首 / ; / 起始），避免误改引号内文本。
        command = re.sub(
            r"(^|;\s*)(?<![\w-])\bpwd\b",
            r"\1Get-Location",
            command,
            flags=re.IGNORECASE,
        )
        # B7: POSIX `cat file` → PowerShell Get-Content（PS 无 cat 命令）。
        cat_match = re.match(
            r"(?<![\w-])\bcat\s+(\S+)",
            command,
            flags=re.IGNORECASE,
        )
        if cat_match:
            cat_file = cat_match.group(1)
            if not cat_file.startswith(("|", "&", ";")):
                command = "Get-Content " + cat_file + command[cat_match.end():]
        # B7: POSIX `cmd1 || cmd2` 失败回退 → `cmd1; if (-not $?) { cmd2 }`。
        # WinPS 5 rejects ``||``. Rewrite every unquoted segment, not just one.
        if "||" in command:
            parts = [part.strip().rstrip(";").strip() for part in command.split("||")]
            if len(parts) >= 2 and all(parts):
                rebuilt = parts[0]
                for part in parts[1:]:
                    rebuilt = f"{rebuilt}; if (-not $?) {{ {part} }}"
                command = rebuilt
                command = re.sub(
                    r"(\{\s*)(?<![\w-])\bpwd\b",
                    r"\1Get-Location",
                    command,
                    flags=re.IGNORECASE,
                )
        # bash `| head -N` / `| tail -N` → PowerShell Select-Object.
        command = re.sub(
            r"\|\s*head\s+-n\s+(\d+)",
            lambda m: f"| Select-Object -First {m.group(1)}",
            command,
            flags=re.IGNORECASE,
        )
        command = re.sub(
            r"\|\s*head\s+-(\d+)",
            lambda m: f"| Select-Object -First {m.group(1)}",
            command,
            flags=re.IGNORECASE,
        )
        command = re.sub(
            r"\|\s*tail\s+-n\s+(\d+)",
            lambda m: f"| Select-Object -Last {m.group(1)}",
            command,
            flags=re.IGNORECASE,
        )
        command = re.sub(
            r"\|\s*tail\s+-(\d+)",
            lambda m: f"| Select-Object -Last {m.group(1)}",
            command,
            flags=re.IGNORECASE,
        )
        # cmd.exe `start cmd /k ...` is cmd.exe syntax; Start-Process is the PS form.
        # Common agent mistake: `start cmd /k python foo.py`
        start_cmd = re.match(
            r"^\s*start\s+cmd\s+/k\s+(.+)$",
            command,
            flags=re.IGNORECASE,
        )
        if start_cmd:
            inner = start_cmd.group(1).strip().replace("'", "''")
            command = (
                "Start-Process -FilePath cmd.exe "
                f"-ArgumentList '/k','{inner}'"
            )
        return command

    def _build_command(self, command: str) -> list[str]:
        translated, actual_shell = self.translate_command(command)
        if actual_shell == "powershell":
            return ["powershell", "-NoProfile", "-Command", translated]
        if actual_shell == "cmd":
            return ["cmd", "/c", translated]
        return ["bash", "-c", translated]

    def _execution_policy(self, workdir: str) -> _ExecutionPolicy:
        config = load_config()
        execution = _as_mapping(config.get("execution"))
        sandbox = _as_mapping(execution.get("sandbox"))
        docker = _as_mapping(execution.get("docker"))
        limits = _as_mapping(execution.get("resource_limits"))

        mode_value = execution.get("sandbox_mode", sandbox.get("mode", "workspace"))
        mode = str(mode_value or "workspace").strip().lower()
        if mode not in {"host", "workspace", "docker"}:
            raise ValueError(
                "execution.sandbox_mode must be one of: host, workspace, docker"
            )

        launch_dir = initial_working_directory()
        current_dir = current_working_directory(launch_dir)
        root_value = execution.get(
            "workspace_root", sandbox.get("workspace_root", launch_dir)
        )
        workspace_root = _resolve_path(root_value or launch_dir, base=launch_dir)
        if mode in {"workspace", "docker"}:
            if not workspace_root.exists() or not workspace_root.is_dir():
                raise ValueError(
                    f"execution.workspace_root is not a directory: {workspace_root}"
                )
            session_base = (
                current_dir
                if _is_within(current_dir, workspace_root)
                else workspace_root
            )
            candidate = (
                _resolve_path(workdir, base=session_base)
                if workdir
                else session_base
            )
            if not _is_within(candidate, workspace_root):
                raise ValueError(
                    "sandbox workdir escapes execution.workspace_root: "
                    f"{candidate} is outside {workspace_root}"
                )
            if not candidate.exists() or not candidate.is_dir():
                raise ValueError(f"sandbox workdir is not a directory: {candidate}")
            cwd: Path | None = candidate
        else:
            cwd = _resolve_path(workdir, base=current_dir) if workdir else None
            if not workdir:
                cwd = current_dir

        image_value = _first_config_value(
            execution, sandbox, docker, limits, "docker_image", ""
        )
        if not image_value and "image" in docker:
            image_value = docker["image"]
        docker_image = str(image_value or "").strip()
        if mode == "docker" and not docker_image:
            raise ValueError(
                "execution.docker_image is required when sandbox_mode=docker"
            )
        if mode == "docker" and (
            docker_image.startswith("-")
            or any(character.isspace() for character in docker_image)
            or "\x00" in docker_image
        ):
            raise ValueError("execution.docker_image is not a valid image reference")

        network_value = _first_config_value(
            execution, sandbox, docker, limits, "docker_network", "none"
        )
        if "network" in docker and "docker_network" not in execution:
            network_value = docker["network"]
        docker_network = str(network_value or "none").strip() or "none"

        max_memory_mb = _non_negative_int(
            _first_config_value(
                execution, sandbox, docker, limits, "max_memory_mb", 4096
            ),
            "max_memory_mb",
        )
        max_cpus = _non_negative_float(
            _first_config_value(
                execution, sandbox, docker, limits, "max_cpus", 2.0
            ),
            "max_cpus",
        )
        max_processes = _non_negative_int(
            _first_config_value(
                execution, sandbox, docker, limits, "max_processes", 128
            ),
            "max_processes",
        )
        return _ExecutionPolicy(
            mode=mode,
            cwd=cwd,
            workspace_root=(
                workspace_root if mode in {"workspace", "docker"} else None
            ),
            docker_image=docker_image,
            docker_network=docker_network,
            max_memory_mb=max_memory_mb,
            max_cpus=max_cpus,
            max_processes=max_processes,
        )

    @staticmethod
    def _container_workdir(policy: _ExecutionPolicy) -> str:
        assert policy.workspace_root is not None
        assert policy.cwd is not None
        relative = policy.cwd.relative_to(policy.workspace_root)
        if relative == Path("."):
            return "/workspace"
        return "/workspace/" + relative.as_posix()

    @staticmethod
    def _new_docker_cidfile() -> Path:
        descriptor, name = tempfile.mkstemp(prefix="rxycode-docker-", suffix=".cid")
        os.close(descriptor)
        path = Path(name)
        path.unlink(missing_ok=True)
        return path

    def _docker_argv(
        self,
        policy: _ExecutionPolicy,
        argv: list[str],
        *,
        shell_command: str | None,
        cidfile: Path,
    ) -> list[str]:
        assert policy.workspace_root is not None
        docker_argv = [
            "docker",
            "run",
            "--rm",
            "--cidfile",
            str(cidfile),
            "--network",
            policy.docker_network,
            "--mount",
            (
                "type=bind,source="
                f"{policy.workspace_root},target=/workspace"
            ),
            "--workdir",
            self._container_workdir(policy),
        ]
        if policy.max_memory_mb > 0:
            docker_argv.extend(["--memory", f"{policy.max_memory_mb}m"])
        if policy.max_cpus > 0:
            docker_argv.extend(["--cpus", f"{policy.max_cpus:g}"])
        if policy.max_processes > 0:
            docker_argv.extend(["--pids-limit", str(policy.max_processes)])
        docker_argv.append(policy.docker_image)
        if shell_command is None:
            docker_argv.extend(argv)
        else:
            docker_argv.extend(["/bin/sh", "-lc", shell_command])
        return docker_argv

    @staticmethod
    def _process_kwargs(cwd: Path | None, os_name: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str(cwd) if cwd is not None else None,
        }
        if os_name == "win32":
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        return kwargs

    def execute(self, command: str, workdir: str = "", timeout: int = 60) -> dict:
        """Run the same controlled async implementation from synchronous callers."""

        def run() -> dict:
            return asyncio.run(self.execute_async(command, workdir, timeout))

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()

        # A synchronous tool can be invoked from an application-owned event loop.
        # Run its private loop on another thread instead of nesting asyncio.run().
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(context.run, run).result()

    async def execute_async(
        self,
        command: str,
        workdir: str = "",
        timeout: float = 60,
    ) -> dict:
        return await self._execute_controlled(
            self._build_command(command),
            workdir=workdir,
            timeout=timeout,
            shell_command=command,
        )

    async def execute_argv_async(
        self,
        argv: list[str],
        workdir: str = "",
        timeout: float = 60,
    ) -> dict:
        """Run an argv command without ever enabling subprocess shell mode."""
        if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv
        ):
            return _failure(
                "[sandbox_error] argv must be a non-empty list of strings",
                error_type="sandbox_error",
            )
        return await self._execute_controlled(
            list(argv),
            workdir=workdir,
            timeout=timeout,
            shell_command=None,
        )

    async def _execute_controlled(
        self,
        argv: list[str],
        *,
        workdir: str,
        timeout: float,
        shell_command: str | None,
    ) -> dict[str, Any]:
        try:
            policy = self._execution_policy(workdir)
        except Exception as exc:
            return _failure(
                f"[sandbox_error] {exc}", error_type="sandbox_error"
            )
        if not math.isfinite(timeout) or timeout < 0:
            return _failure(
                "[sandbox_error] timeout must be a finite non-negative number",
                error_type="sandbox_error",
            )

        cidfile: Path | None = None
        spawn_argv = argv
        spawn_cwd = policy.cwd
        if policy.mode == "docker":
            cidfile = self._new_docker_cidfile()
            spawn_argv = self._docker_argv(
                policy,
                argv,
                shell_command=shell_command,
                cidfile=cidfile,
            )
            spawn_cwd = None

        process: asyncio.subprocess.Process | None = None
        communicate_task: asyncio.Task | None = None
        monitor_task: asyncio.Task | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *spawn_argv,
                **self._process_kwargs(spawn_cwd, self.os_name),
            )
            communicate_task = asyncio.create_task(process.communicate())
            if policy.mode in {"host", "workspace"} and (
                policy.max_memory_mb > 0 or policy.max_processes > 0
            ):
                monitor_task = asyncio.create_task(
                    self._monitor_process_tree(process, policy)
                )

            waiters = {communicate_task}
            if monitor_task is not None:
                waiters.add(monitor_task)
            done, _ = await asyncio.wait(
                waiters,
                timeout=max(0, timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            # A completed monitor_task does NOT mean the command finished: it
            # may have returned early (root exited, orphaned children still
            # hold the pipes).  Only communicate_task completing counts as
            # normal completion; anything else after the deadline is a timeout
            # (or a resource violation).
            if monitor_task is not None and monitor_task in done:
                violation = monitor_task.result()
                if violation is not None:
                    await self._cleanup_process(process, cidfile)
                    await self._cancel_task(communicate_task)
                    return _failure(
                        violation.message(),
                        error_type="resource_limit",
                        resource_limit=violation.resource,
                    )
            if communicate_task not in done:
                await self._cleanup_process(process, cidfile)
                await self._cancel_task(communicate_task)
                return _failure(
                    f"[timeout after {timeout}s]", error_type="timeout"
                )

            stdout, stderr = await communicate_task
            # Decode subprocess output as UTF-8 first. Python 3.6+ on Windows
            # writes UTF-8 to pipes regardless of the console code page, and
            # locale.getpreferredencoding() commonly returns cp936/gbk on
            # zh-CN systems — decoding UTF-8 bytes as GBK produced mojibake
            # (e.g. 测 → 娴嬭瘯). Fall back to the system locale encoding only
            # when UTF-8 decoding fails.
            def _decode_output(data: bytes | None) -> str:
                if not data:
                    return ""
                try:
                    return data.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    fallback = locale.getpreferredencoding(False) or "utf-8"
                    return data.decode(fallback, errors="replace")

            stdout_text = _decode_output(stdout)
            stderr_text = _decode_output(stderr)
            # Stable result schema: every outcome carries ``error_type``
            # (None on normal success/exit), so callers can use
            # result["error_type"] without KeyError on success paths.
            result: dict[str, Any] = {
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": process.returncode,
                "success": process.returncode == 0,
                "error_type": None,
            }
            if policy.mode == "docker" and process.returncode != 0:
                detail = stderr_text.strip() or "docker run returned a non-zero exit code"
                result["stderr"] = f"[docker_sandbox] {detail}"
                result["error_type"] = "docker_sandbox"
            return result
        except asyncio.CancelledError:
            if process is not None:
                await self._cleanup_process(process, cidfile)
            await self._cancel_task(communicate_task)
            raise
        except FileNotFoundError as exc:
            if process is not None:
                await self._cleanup_process(process, cidfile)
            if policy.mode == "docker":
                return _failure(
                    "[docker_sandbox] Docker runtime is unavailable; "
                    "host execution was not attempted",
                    error_type="docker_sandbox",
                )
            return _failure(f"[spawn_error] {exc}", error_type="spawn_error")
        except Exception as exc:
            if process is not None:
                await self._cleanup_process(process, cidfile)
            if policy.mode == "docker":
                return _failure(
                    f"[docker_sandbox] Docker sandbox failed: {exc}; "
                    "host execution was not attempted",
                    error_type="docker_sandbox",
                )
            return _failure(str(exc), error_type="execution_error")
        finally:
            await self._cancel_task(monitor_task)
            if cidfile is not None:
                cidfile.unlink(missing_ok=True)

    async def _monitor_process_tree(
        self,
        process: asyncio.subprocess.Process,
        policy: _ExecutionPolicy,
    ) -> _ResourceViolation | None:
        memory_limit_bytes = policy.max_memory_mb * 1024 * 1024
        while process.returncode is None:
            try:
                root = psutil.Process(process.pid)
                candidates = [root, *root.children(recursive=True)]
                by_pid = {candidate.pid: candidate for candidate in candidates}
                live_processes = []
                total_rss = 0
                for candidate in by_pid.values():
                    try:
                        if not candidate.is_running():
                            continue
                        live_processes.append(candidate)
                        total_rss += candidate.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.ZombieProcess):
                        continue
                    except psutil.AccessDenied:
                        return _ResourceViolation(
                            "process_monitor", observed=1, limit=0
                        )
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                await asyncio.sleep(_MONITOR_INTERVAL_SECONDS)
                continue
            except psutil.AccessDenied:
                return _ResourceViolation("process_monitor", observed=1, limit=0)

            if memory_limit_bytes > 0 and total_rss > memory_limit_bytes:
                observed_mb = (total_rss + 1024 * 1024 - 1) // (1024 * 1024)
                return _ResourceViolation(
                    "memory", observed=observed_mb, limit=policy.max_memory_mb, unit="MB"
                )
            if (
                policy.max_processes > 0
                and len(live_processes) > policy.max_processes
            ):
                return _ResourceViolation(
                    "processes",
                    observed=len(live_processes),
                    limit=policy.max_processes,
                )
            await asyncio.sleep(_MONITOR_INTERVAL_SECONDS)
        return None

    @staticmethod
    async def _cancel_task(task: asyncio.Task | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _cleanup_process(
        self,
        process: asyncio.subprocess.Process,
        cidfile: Path | None,
    ) -> None:
        if cidfile is not None:
            await self._terminate_docker_container(cidfile)
        await self._terminate_process_tree(process)

    async def _terminate_docker_container(self, cidfile: Path) -> None:
        try:
            container_id = cidfile.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return
        if not _DOCKER_CID_PATTERN.fullmatch(container_id):
            return
        try:
            kwargs: dict[str, Any] = {
                "stdout": asyncio.subprocess.DEVNULL,
                "stderr": asyncio.subprocess.DEVNULL,
            }
            if self.os_name == "win32":
                kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            killer = await asyncio.create_subprocess_exec(
                "docker", "rm", "--force", container_id, **kwargs
            )
            await asyncio.wait_for(killer.wait(), timeout=5)
        except Exception:
            # The docker run client may already have removed the container.
            pass

    async def _terminate_process_tree(
        self, process: asyncio.subprocess.Process
    ) -> None:
        """Best-effort, bounded cleanup for a command and all descendants.

        Works even when the root process has already exited while its children
        survive (they may be holding the stdout/stderr pipes open, which is
        exactly what keeps ``communicate()`` blocked): POSIX kills the process
        group (the child was spawned with ``start_new_session=True``, so the
        group outlives the leader), Windows walks the parent chain from the
        recorded pid and kills every descendant.

        POSIX: after SIGTERM the whole process group is polled; if any member
        survives the grace period (e.g. it ignores SIGTERM or the root exited
        early), the group escalates to SIGKILL.
        """
        pid = process.pid
        if self.os_name == "win32":
            await self._win_terminate_tree(pid)
            if process.returncode is None:
                process.kill()
        else:
            try:
                # start_new_session=True makes the child a group leader whose
                # group id == its pid; the group persists while any child in
                # it is alive, so this reaches orphaned descendants too.
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                if process.returncode is None:
                    process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            if self.os_name != "win32":
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            if process.returncode is None:
                process.kill()
            await process.wait()

        if self.os_name != "win32":
            await self._posix_ensure_group_gone(pid)

    async def _posix_ensure_group_gone(self, group_id: int) -> None:
        """Poll the process group until empty; escalate to SIGKILL when any
        member ignores SIGTERM (or the root exited before the group drained).

        ``psutil`` enumerates actual group members, so a group whose leader
        already exited is still detected through its surviving members.  Each
        pid is guarded individually (a process may exit between enumeration
        and the getpgid probe); an enumeration failure is treated as
        "cannot confirm empty" and escalates conservatively rather than
        returning as if the group were gone.  After SIGKILL the group is
        polled again until it is actually empty.
        """
        import logging

        logger = logging.getLogger(__name__)

        def _members() -> list[int]:
            """Group member pids; None-like sentinel is not used — a probe
            failure yields a full-process scan retry inside the loop."""
            pids: list[int] = []
            for p in psutil.process_iter():
                try:
                    if os.getpgid(p.pid) == group_id:
                        pids.append(p.pid)
                except (psutil.NoSuchProcess, ProcessLookupError, OSError):
                    # Exited between iteration and probe; it is not a member
                    # anymore.  A failure to probe the WHOLE scan is handled
                    # by the outer loop's conservative escalation instead.
                    continue
            return pids

        deadline = asyncio.get_running_loop().time() + 2.0
        while True:
            try:
                members = _members()
            except Exception as exc:
                logger.warning(
                    "process group %s enumeration failed (%s); escalating "
                    "conservatively",
                    group_id,
                    type(exc).__name__,
                )
                members = None
            if members == []:
                return
            if members is None or asyncio.get_running_loop().time() >= deadline:
                if members is not None:
                    logger.warning(
                        "process group %s still has members %s after SIGTERM; "
                        "escalating to SIGKILL",
                        group_id,
                        sorted(members),
                    )
                try:
                    os.killpg(group_id, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                # Confirm the group actually drained after SIGKILL.
                kill_deadline = asyncio.get_running_loop().time() + 1.0
                while True:
                    try:
                        remaining = _members()
                    except Exception as exc:
                        logger.warning(
                            "process group %s re-enumeration failed after "
                            "SIGKILL (%s); cannot confirm cleanup",
                            group_id,
                            type(exc).__name__,
                        )
                        remaining = None
                    if remaining == []:
                        return
                    if asyncio.get_running_loop().time() >= kill_deadline:
                        logger.warning(
                            "process group %s still visible %s after SIGKILL",
                            group_id,
                            sorted(remaining) if remaining else "?",
                        )
                        return
                    await asyncio.sleep(0.1)
            await asyncio.sleep(0.1)

    async def _win_terminate_tree(self, pid: int) -> None:
        """Terminate every descendant of ``pid`` (and the root if alive).

        The PowerShell walk re-enumerates survivors after killing and the
        whole sequence is retried (WMI is best-effort); if a target is still
        alive after the retries, the failure is recorded for diagnostics.
        """
        import logging

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        async def _run(argv: list[str]) -> set[int] | None:
            """Run the killer; return the surviving PID set (empty = clean),
            or None when the command itself failed."""
            try:
                killer = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=flags,
                )
                stdout, _ = await asyncio.wait_for(killer.communicate(), timeout=6)
                for line in stdout.decode("utf-8", errors="replace").splitlines():
                    if line.startswith("ALIVE="):
                        raw = line.split("=", 1)[1].strip()
                        if not raw:
                            return set()
                        try:
                            return {
                                int(part)
                                for part in raw.split(",")
                                if part.strip().isdigit()
                            }
                        except ValueError:
                            return None
                return None
            except Exception:
                return None

        walk_script = (
            f"$root = {int(pid)}; "
            "$all = @(Get-CimInstance Win32_Process); "
            "$queue = @($root); $targets = @(); "
            "while ($queue.Count -gt 0) { "
            "$p = $queue[0]; $queue = @($queue | Select-Object -Skip 1); "
            "foreach ($c in @($all | Where-Object { $_.ParentProcessId -eq $p })) { "
            "$targets += $c.ProcessId; $queue += $c.ProcessId } }; "
            "$targets = @($targets | Sort-Object -Unique); "
            "$targets | ForEach-Object { "
            "Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; "
            "Stop-Process -Id $root -Force -ErrorAction SilentlyContinue; "
            "Start-Sleep -Milliseconds 300; "
            "$alive = @(); "
            "foreach ($t in $targets) { "
            "if (Get-Process -Id $t -ErrorAction SilentlyContinue) "
            "{ $alive += $t } }; "
            "if (Get-Process -Id $root -ErrorAction SilentlyContinue) "
            "{ $alive += $root }; "
            'Write-Output ("ALIVE=" + ($alive -join ","))'
        )
        # Walk + kill, then re-enumerate surviving PIDs; retry up to 3 times.
        surviving: set[int] | None = None
        for _ in range(3):
            surviving = await _run(["powershell", "-NoProfile", "-Command", walk_script])
            if surviving is not None and not surviving:
                break
            await asyncio.sleep(0.3)
        if surviving:
            logging.getLogger(__name__).warning(
                "process tree cleanup incomplete on Windows: pid(s) %s under "
                "root %s still alive after retries",
                sorted(surviving),
                int(pid),
            )
        # Fallback for the live-root case ONLY when the walk itself failed
        # (surviving is None): taskkill on an already-reaped PID is a no-op at
        # best and a PID-reuse kill at worst, so it must never run against a
        # possibly-dead pid — confirm the root is still alive first.
        if surviving is None:
            root_alive = await _run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "$root = " f"{int(pid)}; "
                        "if (Get-Process -Id $root "
                        "-ErrorAction SilentlyContinue) { "
                        'Write-Output ("ALIVE=" + $root) } '
                        'else { Write-Output "ALIVE=" }'
                    ),
                ]
            )
            if root_alive:
                await _run(["taskkill", "/PID", str(int(pid)), "/T", "/F"])


shell_executor = ShellExecutor()
