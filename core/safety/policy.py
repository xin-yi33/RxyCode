"""Safety policy: risk levels, tool classification, write-path whitelist
and dry-run detection.

Adapted from OpenHands (MIT) openhands/security/ — the three-tier
SecurityRisk model (LOW/MEDIUM/HIGH mapped to READ/WRITE/DANGER) and the
confirmation-policy concept. Only the design is ported; no code is
vendored.
"""

from __future__ import annotations

import os
import re
from enum import IntEnum
from pathlib import Path
from typing import Any


class RiskLevel(IntEnum):
    """Three-tier tool risk model (OpenHands SecurityRisk LOW/MEDIUM/HIGH)."""

    READ = 0    # OpenHands LOW — inspection only, no side effects
    WRITE = 1   # OpenHands MEDIUM — modifies files / runs commands
    DANGER = 2  # OpenHands HIGH — potentially destructive / irreversible


#: Canonical tool names for aliases. Orchestrator, risk, and subagent
#: permissions must share this table so ``open``/``shell`` cannot miss
#: ``open_file``/``bash`` policy.
TOOL_NAME_ALIASES: dict[str, str] = {
    "web_search": "websearch",
    "search_web": "websearch",
    "web_fetch": "webfetch",
    "fetch_url": "webfetch",
    "open": "open_file",
    "browser": "open_file",
    "shell": "bash",
    "final-answer": "final_answer",
    "finalanswer": "final_answer",
}


def canonical_tool_name(name: str) -> str:
    """Return the registered tool name for an alias or mixed-case label."""
    lowered = (name or "").strip().lower()
    return TOOL_NAME_ALIASES.get(lowered, lowered)


#: Static risk table for built-in tools. Missing entries default to WRITE
#: (fail-safe: unknown tools are treated as side-effecting).
TOOL_RISK_TABLE: dict[str, RiskLevel] = {
    # READ — pure inspection
    "read": RiskLevel.READ,
    "view": RiskLevel.READ,
    "grep": RiskLevel.READ,
    "glob": RiskLevel.READ,
    "ls": RiskLevel.READ,
    "webfetch": RiskLevel.READ,
    "websearch": RiskLevel.READ,
    "datetime": RiskLevel.READ,
    # 2026-10-13 K例复审：纯目录检索元工具——不触发写审批/快照（不得因此
    # 降低被发现 MCP 工具自身的风险，它们的 risk 各自独立分类）。
    "tool_search": RiskLevel.READ,
    "final_answer": RiskLevel.READ,
    "history": RiskLevel.READ,
    "diagnostics": RiskLevel.READ,
    "vision": RiskLevel.READ,
    "question": RiskLevel.READ,
    "skill": RiskLevel.READ,
    # WRITE — side effects, reversible
    "write": RiskLevel.WRITE,
    "edit": RiskLevel.WRITE,
    "patch": RiskLevel.WRITE,
    "open_file": RiskLevel.WRITE,
    "bash": RiskLevel.WRITE,  # escalated to DANGER dynamically by classify_bash_command
    "format": RiskLevel.WRITE,
    "change_directory": RiskLevel.WRITE,
    # Installing external instructions or executable server definitions is
    # high risk even when the operation only writes configuration files.
    "download_skill": RiskLevel.DANGER,
    "download_mcp": RiskLevel.DANGER,
    "download_file": RiskLevel.WRITE,
    "file_download": RiskLevel.WRITE,
    # Stateful multi-operation tools default to a mutating classification.
    # ``classify_tool_risk`` only downgrades explicitly read-only operations.
    "memory": RiskLevel.WRITE,
    "task": RiskLevel.WRITE,
    # DANGER — installs packages / touches git remotes & history
    "installer": RiskLevel.DANGER,
    "git": RiskLevel.DANGER,
    "workflow": RiskLevel.DANGER,
}


def register_tool_risk(name: str, level: RiskLevel) -> None:
    """Register/override the static risk level for a tool name."""
    TOOL_RISK_TABLE[name] = level


def get_tool_risk(name: str) -> RiskLevel:
    """Return the static risk level for a tool; unknown tools default WRITE."""
    canonical = canonical_tool_name(name)
    if canonical in TOOL_RISK_TABLE:
        return TOOL_RISK_TABLE[canonical]
    return TOOL_RISK_TABLE.get(name, RiskLevel.WRITE)


#: Dangerous shell command patterns (case-insensitive regex). Keep this an
#: easily-extensible plain list — add new entries at the end.
#: Adapted from OpenHands (MIT) openhands/security/ dangerous-command
#: heuristics, extended with Windows patterns (reg delete / format).
DANGEROUS_COMMAND_PATTERNS: list[str] = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+(/\*|/|~)(?=\s|$)",  # rm -rf / | /* | ~
    r"\bsudo\s+rm\s+-[a-zA-Z]*r",                                          # sudo rm -r...
    r"\bmkfs(\.\w+)?\s",                                                   # mkfs / mkfs.ext4
    r"\bdd\s+.*\bof=/dev/",                                                # dd of=/dev/sda
    r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",                              # curl ... | sh
    r"\bwget\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",                              # wget ... | sh
    r"\bgit\s+push\b.*\s(--force|-f)\b",                                   # git push --force / -f
    r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?777\s+/\s*$",                    # chmod -R 777 /
    r">\s*/dev/sd[a-z]",                                                   # > /dev/sda
    r"\bshutdown\b",                                                       # shutdown ...
    r"\breboot\b",                                                         # reboot
    r"\breg\s+delete\b",                                                   # reg delete (Windows)
    r"\bformat\s+[a-zA-Z]:",                                               # format C: (Windows)
    # PowerShell recursive/force deletes — often used for destructive probes
    r"\bRemove-Item\b[^\n]*(-(Recurse|Force)\b)[^\n]*(-(Recurse|Force)\b)",
    r"\bri\b[^\n]*(-(Recurse|Force)\b)[^\n]*(-(Recurse|Force)\b)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_COMMAND_PATTERNS]

# 黑名单：命中后一律不执行。full_auto 和人工批准都不能放行。
# 相对路径的项目清理（rm -rf ./build）不在这里。
_CATASTROPHIC_PREFIXES = (
    # Linux
    "/bin", "/sbin", "/usr", "/lib", "/lib64", "/etc", "/boot", "/dev",
    "/proc", "/sys", "/run", "/var", "/opt", "/home", "/root", "/tmp",
    # macOS
    "/system", "/library", "/volumes", "/applications", "/private", "/cores",
    "/users",
)
_COMMAND_EDGE = (
    r"(?:^|[;&|`\n(])\s*"
    r"(?:(?:sudo|cmd(?:\.exe)?\s+/c|powershell(?:\.exe)?\s+-command|"
    r"pwsh(?:\.exe)?\s+-command)\s+)*"
)
_WIN_CRITICAL_PROCESS = r"(?:lsass|csrss|winlogon|smss|services|wininit)"


def _shell_scan_text(command: str) -> str:
    return re.sub(r"['\"]", "", command or "")


def _normalize_path_token(token: str) -> str:
    text = token.strip().replace("\\", "/")
    text = re.sub(r"^//\?/([a-zA-Z]:)", r"\1", text)
    for env_name in ("systemroot", "windir"):
        text = re.sub(rf"(?i)^%(?:{env_name})%", "c:/windows", text)
        text = re.sub(rf"(?i)^\$env:{env_name}", "c:/windows", text)
    return text.rstrip("/")


def _is_catastrophic_path(token: str) -> bool:
    raw = _normalize_path_token(token)
    if not raw:
        return True
    lower = raw.lower()
    if lower in {"/", "/.", "/*", "~", "~/", ".", "..", "*", "$home"}:
        return True
    if any(lower == prefix or lower.startswith(prefix + "/") for prefix in _CATASTROPHIC_PREFIXES):
        return True
    if re.fullmatch(r"[a-z]:", lower):
        return True
    return re.match(
        r"^[a-z]:/(windows|program files|program files \(x86\)|users|programdata)(/|$)",
        lower,
    ) is not None


def _recursive_delete_hits_system(text: str) -> bool:
    patterns = (
        r"(?:sudo\s+)?rm\b(?P<tail>[^;&|\n]*)",
        r"\b(?:Remove-Item|ri|rmdir|rd|del|erase)\b(?P<tail>[^;&|\n]*)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            tail = match.group("tail")
            recursive = re.search(
                r"(?:^|\s)(?:-[a-zA-Z]*r[a-zA-Z]*|--recursive|-Recurse|/s)\b",
                tail,
                re.IGNORECASE,
            )
            if match.group(0).lower().startswith("rm") and not recursive:
                continue
            if not match.group(0).lower().startswith("rm") and not recursive:
                continue
            tokens = []
            for tok in tail.split():
                if not tok or tok.startswith("-"):
                    continue
                if tok.lower() in {"/s", "/q", "/f"}:
                    continue
                tokens.append(tok)
            if not tokens:
                return True
            if any(_is_catastrophic_path(tok) for tok in tokens):
                return True
    return False


_ALWAYS_DENIED: tuple[tuple[str, str], ...] = (
    (r"\bmkfs(\.\w+)?\b", "格式化文件系统"),
    (r"\bdd\b[^\n]*\bof=/dev/", "把数据写入磁盘设备"),
    (r"\bdiskutil\s+erase", "擦除 macOS 磁盘"),
    (_COMMAND_EDGE + r"format(?:\.com)?\s+[a-z]:", "格式化 Windows 磁盘"),
    (r"\b(?:Format-Volume|Clear-Disk|Initialize-Disk|Clear-Partition)\b", "清除或初始化磁盘"),
    (_COMMAND_EDGE + r"diskpart\b", "进入 diskpart"),
    (_COMMAND_EDGE + r"(?:shutdown|reboot|halt|poweroff)\b", "关机或重启"),
    (r"\b(?:Stop-Computer|Restart-Computer)\b", "关机或重启"),
    (_COMMAND_EDGE + r"init\s+[06]\b", "切换到关机或重启运行级别"),
    (r"\bsystemctl\s+(?:poweroff|reboot|halt)\b", "systemctl 关机或重启"),
    (r":\(\)\s*\{", "fork bomb"),
    (r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?(?:sh|zsh|fish|pwsh|powershell)\b", "把下载内容直接送进 shell"),
    (r"\breg(?:\.exe)?\s+delete\b", "删除注册表"),
    (r"\bbcdedit\b[^\n]*/delete\b", "删除启动项"),
    (r"\bcipher(?:\.exe)?\s+/w\b", "覆盖擦除磁盘空闲空间"),
    (r"\bvssadmin\s+delete\s+shadows\b", "删除卷影副本"),
    (r"\b(?:powershell|pwsh)(?:\.exe)?\b[^\n]*\s-(?:enc|encodedcommand)\b", "编码后的 PowerShell 看不清内容"),
    (r"\bchmod\s+(?:-[a-zA-Z]*R[a-zA-Z]*\s+)?(?:777|000|a\+rwx)\s+/", "递归改写根目录权限"),
    (r">\s*/dev/(?:sd|nvme|mmc|disk|rdisk)", "重定向写入磁盘设备"),
    (r"\b(?:shred|wipefs)\b[^\n]*\s/dev/", "擦除磁盘设备"),
    (r"\b(?:sfdisk\s+--delete|parted\b[^\n]*\bmklabel\b)", "改写分区表"),
    (_COMMAND_EDGE + r"fdisk\s+/dev/(?!.*\s-l\b)", "改写磁盘分区"),
    (r"\bkill\s+(?:-9\s+)?-1\b", "结束全部进程"),
    (r"\becho\s+[bco]\s*>\s*/proc/sysrq-trigger", "触发内核紧急重启或关机"),
    # macOS
    (r"\bcsrutil\s+(?:disable|clear)\b", "关闭 macOS 系统完整性保护"),
    (r"\bnvram\s+-[cd]\b", "清除 macOS NVRAM"),
    (r"\basr\s+restore\b", "用 asr 整盘恢复"),
    # Windows
    (r"\bwmic\s+shadowcopy\s+delete\b", "删除 Windows 卷影副本"),
    (r"\bwbadmin\s+delete\s+catalog\b", "删除 Windows 备份目录"),
    (r"\bbcdedit\b[^\n]*\s/(?:set|import|createstore)\b", "改写 Windows 启动配置"),
    (r"\bsdelete(?:64)?(?:\.exe)?\b", "安全擦除磁盘"),
    (r"\bfsutil\s+usn\s+deletejournal\b", "删除 NTFS USN 日志"),
    (r"\btaskkill\b[^\n]*\s/im\s+" + _WIN_CRITICAL_PROCESS + r"\.exe\b", "结束 Windows 关键进程"),
    (r"\bStop-Process\b[^\n]*\b" + _WIN_CRITICAL_PROCESS + r"\b", "结束 Windows 关键进程"),
    (r"\bnet\s+user\b[^\n]*\s/delete\b", "删除 Windows 用户"),
)


def hard_denied_shell_reason(command: str) -> str | None:
    """Return why this shell command is on the hard blacklist, or None.

    A match must not run. Approval and full_auto do not override it.
    """
    text = _shell_scan_text(command).strip()
    if not text:
        return None
    if _recursive_delete_hits_system(text):
        return "递归删除指向系统目录、磁盘根或用户主目录"
    find_delete = re.search(
        r"(?i)\bfind\s+(\S+)[^\n;|&]*-(?:delete|exec\s+rm)\b",
        text,
    )
    if find_delete:
        start = find_delete.group(1)
        # find . -name '*.pyc' -delete 是项目内清理。根和系统目录不是。
        if start not in {".", "./", ".."} and _is_catastrophic_path(start):
            return "find 从系统目录或根目录删除文件"
    for pattern, reason in _ALWAYS_DENIED:
        if re.search(pattern, text, re.IGNORECASE):
            return reason
    return None

# A deliberately small allow-list for shell probes that have no filesystem,
# process, package, network, or repository side effect.  Bash itself remains
# WRITE by default; only a command made entirely from these segments can be
# downgraded to READ.  Keeping this list narrow is important because an
# arbitrary shell command must never become auto-approved merely because it
# happens to contain a read-looking verb.
_READ_ONLY_BASH_SEGMENTS = [
    re.compile(r"^(?:pwd|Get-Location)\s*$", re.IGNORECASE),
    re.compile(
        r"^(?:ls|ls\.exe|dir|Get-ChildItem)(?:\s+-[\w-]+)*"
        r"(?:\s+(?:['\"][^'\"<>|]+['\"]|[A-Za-z0-9_.:/\\~-]+))?\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:echo|Write-Output)(?:\s+[^<>|]+)?$", re.IGNORECASE),
    re.compile(r'^"[^"<>|]+"$'),
    re.compile(r"^(?:where|where\.exe)\s+[A-Za-z0-9_.-]+\s*$", re.IGNORECASE),
    re.compile(
        r"^(?:node|python3?|py|java|javac|npm)(?:\.exe|\.cmd)?\s+"
        r"(?:--version|-version|-V)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^pip(?:3)?(?:\.exe)?\s+show(?:\s+[A-Za-z0-9_.\-]+)+\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^grep(?:\.[A-Za-z]+)?(?:\s+-\w+)*\s+(?:-E\s+)?['\"][^'\"]+['\"]\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^node(?:\.exe|\.cmd)?\s+--check\s+[A-Za-z0-9_./\\-]+\.(?:js|mjs|cjs)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^git\s+(?:status(?:\s+--[\w-]+)*|log(?:\s+[^<>|]+)?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:cmd(?:\.exe)?\s+/c\s+)?ver\s*$", re.IGNORECASE),
]

# Stderr-only redirects are not filesystem writes. Agents routinely append
# ``2>&1`` to version probes; treating ``>`` as a write would force those
# probes through WRITE approval and then fail the whole task when a missing
# Windows alias such as ``python3`` returns exit 1.
_STDERR_ONLY_REDIRECT_RE = re.compile(
    r"(?:2>&1|2>\s*/dev/null|2>\s*nul|2>\s*\$null)\s*",
    re.IGNORECASE,
)


def _is_read_only_bash_probe(command: str) -> bool:
    """Return true only for a complete, known-safe environment probe.

    Splitting on shell control/pipeline separators is intentionally simple and
    conservative.  Any segment not in the explicit allow-list keeps the
    command at WRITE, while dangerous-pattern matching still runs first.
    """
    if not command:
        return False
    normalized = _STDERR_ONLY_REDIRECT_RE.sub(" ", command)
    if any(token in normalized for token in (">", "<", "`", "$(", "${")):
        return False
    # ``pip show … | grep -E "^(Name|Version)"`` is an env probe. The grep
    # pattern contains ``|``, which would otherwise split the quoted string
    # and keep the command at WRITE.
    if re.search(r"\bpip(?:3)?(?:\.exe)?\s+show\b", normalized, re.I) and not re.search(
        r"\b(?:pip\s+install|npm\s+install|python3?\s+\S+\.py|Set-Content|Out-File|rm\s+)\b",
        normalized,
        re.I,
    ):
        return True
    segments = re.split(r"(?:&&|\|\||[;&|])", normalized)
    return bool(segments) and all(
        any(pattern.fullmatch(segment.strip()) for pattern in _READ_ONLY_BASH_SEGMENTS)
        for segment in segments
        if segment.strip()
    )


def classify_bash_command(cmd: str) -> RiskLevel:
    """Dynamically classify a shell command.

    Destructive patterns escalate to DANGER.  A narrow set of complete,
    read-only environment probes is READ so normal startup inspection does not
    block the user on an approval dialog.  Unknown shell remains WRITE.
    """
    if not cmd:
        return RiskLevel.WRITE
    for pat in _COMPILED_PATTERNS:
        if pat.search(cmd):
            return RiskLevel.DANGER
    if _is_read_only_bash_probe(cmd):
        return RiskLevel.READ
    return RiskLevel.WRITE


def classify_tool_risk(name: str, args: Any = None) -> RiskLevel:
    """Classify one invocation using both its tool name and arguments.

    Multi-operation tools fail closed: only known read-only operations are
    downgraded. Missing or future operations retain the conservative static
    WRITE/DANGER classification.
    """
    name = canonical_tool_name(name)
    operation = ""
    if isinstance(args, dict):
        operation = str(args.get("operation", "")).strip().lower()

    if name == "memory" and operation in {"search", "list"}:
        return RiskLevel.READ
    if name == "download_skill":
        return RiskLevel.DANGER
    if name == "download_mcp":
        return RiskLevel.DANGER
    if name == "task" and operation in {"list", "get"}:
        return RiskLevel.READ
    if name == "workflow":
        if operation in {"status", "wait"}:
            return RiskLevel.READ
        if operation == "cancel":
            return RiskLevel.WRITE
        return RiskLevel.DANGER

    risk = get_tool_risk(name)
    # 废弃代码（2026-09-21）：if name in {"bash", "shell"} — shell 已由
    # canonical_tool_name 归一到 bash，禁止再按双名分支。
    # if name in {"bash", "shell"} and isinstance(args, dict):
    if name == "bash" and isinstance(args, dict):
        command_risk = classify_bash_command(str(args.get("command", "")))
        # Bash is statically WRITE, but a complete, allow-listed probe is
        # explicitly READ.  Unknown commands retain the static fail-closed
        # WRITE level; dangerous patterns still escalate to DANGER.
        if command_risk is RiskLevel.READ:
            return RiskLevel.READ
        return max(risk, command_risk)
    return risk


def apply_mcp_hint(name: str, risk: RiskLevel, annotations: Any | None) -> RiskLevel:
    """Unknown MCP stays at least WRITE. Hints may only raise risk.

    ``readOnlyHint`` does not lower a level. ``destructiveHint`` raises to
    DANGER. ToolSpec text is not an annotation and is not read here.
    """
    hints = annotations if isinstance(annotations, dict) else {}
    if canonical_tool_name(name) not in TOOL_RISK_TABLE and hints:
        risk = max(risk, RiskLevel.WRITE)
    if hints.get("destructiveHint") is True:
        risk = max(risk, RiskLevel.DANGER)
    return risk


def _resolve(path: str) -> Path:
    from ..session_runtime import resolve_session_path

    return resolve_session_path(path)



def _is_within(target: Path, base: Path) -> bool:
    """Prefix check on resolved paths (guards against ../ escapes and
    sibling-prefix confusion like /tmp/work2 vs /tmp/work)."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def is_write_allowed(path: str, config: dict) -> bool:
    """Whitelist check for write targets. Allowed roots:
    - the current working directory
    - the RxyCode output dir (~/.rxycode/output/ or RXYCODE_OUTPUT_DIR)
    - every entry of config ``safety.allowed_write_paths``
    """
    from ..session_runtime import current_working_directory

    safety = (config or {}).get("safety", {}) or {}
    allowed_extra = safety.get("allowed_write_paths", []) or []

    # Windows drive paths (``C:\\...`` / ``C:/...``) are absolute on Windows but
    # NOT on POSIX: Path("C:\\x").is_absolute() is False on Linux, so
    # resolve_session_path would wrongly treat them as relative to the cwd and
    # report them as "inside the workspace". On non-Windows hosts, treat any
    # drive-prefixed path as an escape unless it is explicitly whitelisted
    # (safety fix S12, Luna rev). On Windows this is already handled by
    # Path.is_absolute(), so only apply when the platform does not see it as
    # absolute.
    drive_path = re.match(r"(?i)^[a-z]:[\\/]", path)
    if drive_path and not Path(path).is_absolute():
        for extra in allowed_extra:
            try:
                if _resolve(extra) == _resolve(path):
                    return True
            except Exception:
                continue
        return False

    try:
        target = _resolve(path)
    except Exception:
        return False

    roots: list[Path] = [current_working_directory().resolve()]
    try:
        # Import from the concrete package module, not sys.modules lookup,
        # so tests that stub config.settings in sys.modules don't break us.
        import importlib
        _settings = importlib.import_module("RxyCode.RxyCode1_1_0.config.settings")
        _get_output_dir = getattr(_settings, "get_output_dir", None)
        if _get_output_dir is None:
            raise AttributeError("get_output_dir missing")
        dated_output = _get_output_dir().resolve()
        roots.extend((dated_output, dated_output.parent))
    except Exception:
        pass

    for extra in allowed_extra:
        try:
            roots.append(_resolve(extra))
        except Exception:
            continue

    execution = (config or {}).get("execution", {}) or {}
    root_value = execution.get("workspace_root")
    if root_value:
        try:
            roots.append(_resolve(str(root_value)))
        except Exception:
            pass

    return any(_is_within(target, root) for root in roots)


#: git 只读子命令：无写副作用，不应被“写路径白名单”拦截。
READONLY_GIT_OPS = frozenset(
    {
        "status",
        "diff",
        "log",
        "branch",
        "show",
        "blame",
        "ls-files",
        "rev-parse",
        "remote",
        "describe",
        "shortlog",
        "grep",
    }
)

_CD_TOOL_NAMES = frozenset({"cd", "change_directory"})


def is_write_path_gate_exempt(tool_name: str, args: Any) -> bool:
    """WRITE/DANGER 工具的写路径闸豁免（2026-09-23）。

    - ``cd``/``change_directory`` 只切换会话 cwd，本身不写文件；切换后
      的写操作仍会按新 cwd 逐个过闸。旧行为把 cd 也拦下，工作区被降级
      到 scratch 时 agent 连自救都做不到（"被环境阻塞、无法推进"）。
    - 只读 ``git`` 子命令（status/diff/log/…）没有写副作用，拦在
      *写* 路径白名单上属于误伤。
    """
    name = str(tool_name or "").strip().lower()
    if name in _CD_TOOL_NAMES:
        return True
    if name == "git" and isinstance(args, dict):
        op = str(args.get("operation") or "status").strip().lower()
        return op in READONLY_GIT_OPS
    return False


#: 写路径闸拒绝文案的可操作指引：告诉 agent 如何自救，而不是让它得出
#: “环境阻塞、重试无用”的结论。
WRITE_PATH_BLOCKED_HINT = (
    "hint: use the cd tool to switch into the target directory first (cd "
    "is exempt from this gate), or add the directory to "
    "safety.allowed_write_paths in the config."
)


# Absolute path literals that often appear in shell write/delete probes.
_ABS_PATH_RE = re.compile(
    r"(?P<path>"
    r"[A-Za-z]:[\\/][^\s'\"|;>&]+"  # Windows drive path
    r"|/(?:Users|home|tmp|var|etc|root)[^\s'\"|;>&]*"  # common Unix abs roots
    r")"
)
# Mutating verbs / redirects whose *target path* must stay inside the whitelist.
# Paths that only appear inside -Value/-Content payloads are ignored; here-string
# contents stay visible because they can be executed (iex, Invoke-Expression).
_ABS_TARGET = (
    r"(?<![\w~./\\])"
    r"(?:"
    r"[A-Za-z]:[\\/][^\s'\"|;>&]*"
    r"|\\{1,2}[^\s'\"|;>&]+"
    r"|/[^\s'\"|;>&]*"
    r"|\$\{env:[^\W\d]\w*\}(?:[\\/][^\s'\"|;>&]*)?"
    r"|\$env:[^\W\d]\w*(?:[\\/][^\s'\"|;>&]*)?"
    r"|\$\{[^\W\d]\w*\}(?:[\\/][^\s'\"|;>&]*)?"
    r"|\$HOME(?!\w)(?:[\\/][^\s'\"|;>&]*)?"
    r"|\$[^\W\d]\w*(?:[\\/][^\s'\"|;>&]*)?"
    r"|%[^\W\d][\w()]*%(?:[\\/][^\s'\"|;>&]*)?"
    r"|~[^\s'\"|;>&]*"
    r")"
)
# Pseudo-device redirect targets that are not real filesystem writes.
_REDIRECT_PSEUDO_TARGETS = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr"})
# A path-shaped relative token (word + separators). Interesting only when it
# carries a '..' segment — plain filenames resolve inside the workspace.
_REL_TARGET = r"(?<![\w~./\\])[^\s'\"|;>&:/\\]+(?:[\\/][^\s'\"|;>&:/\\]*)*"
_BASH_MUTATING_OPENER_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b(?P<verb>Remove-Item|Rename-Item|ri|rni|ren|Set-Content|Add-Content|Clear-Content|Out-File|New-Item|Copy-Item|Move-Item|"
    r"sc|ac|clc|ni|cpi|"
    r"cd|chdir|Set-Location|sl|Push-Location|pushd|popd|Pop-Location|"
    r"del|erase|rmdir|rd|rm|mv|cp|tee|touch|mkdir|install)\b"
    r"(?P<verbseg>[^\n;|&]*)"
    r"|(?:^|[^>])>{1,2}(?P<redirseg>[^\n;|&]*)"
    r")"
)
_PATH_TOKEN_RE = re.compile(rf"(?ix)(?P<t>{_ABS_TARGET}|{_REL_TARGET})")
_DOTDOT_SEGMENT_RE = re.compile(r"\.{2}(?:[\\/]|$)")
_ABS_TOKEN_START_RE = re.compile(r"^(?:[A-Za-z]:|[\\/~$%])")
_ABS_FORM_RE = re.compile(r"(?i)^(?:[a-z]:[\\/]|[\\/])")
# Directory-change verbs whose target becomes the effective cwd for the rest
# of the command; pop-verbs restore a pushed location (fail closed on an
# empty stack — the resulting directory cannot be verified).
_CD_VERBS = frozenset({"cd", "chdir", "set-location", "sl"})
_PUSH_VERBS = frozenset({"pushd", "push-location"})
_POP_VERBS = frozenset({"popd", "pop-location"})
# Plain shell variable targets (``Set-Content $out x`` / ``> $OUT``) resolve
# through assignments tracked earlier in the command; untracked names fail
# closed. $HOME/$env:/${...} forms are matched by the earlier alternatives.
_SHELL_VAR_RE = re.compile(r"^\$([^\W\d]\w*)$", re.IGNORECASE)
# ``$x = "v"`` (PowerShell) and ``X=v`` (bash) assignments, tracked in order.
_ASSIGN_RE = re.compile(
    r"(?is)"
    r"\$(?P<ps>[^\W\d]\w*)\s*=\s*"
    r"(?:\"(?P<psdq>[^\"]*)\"|'(?P<pssq>[^']*)'|(?P<psbare>[^\s;|&'\"]+))"
    r"|\b(?P<sh>[A-Za-z_]\w*)=(?P<shval>[^\s;|&'\"]*)"
)
# Shell-provided names that map to a knowable directory; everything else a
# mutating target could be stays unverifiable.
_BUILTIN_DIR_VARS = ("pwd", "home")
# Pipeline/loop variables are objects, not paths — never tracked names and
# never path targets, so they resolve to themselves (inside the workspace).
_PIPELINE_VARS = frozenset(
    {"_", "psitem", "input", "args", "this", "matches", "foreach", "event"}
)


def _expand_env_candidate(raw: str) -> str | None:
    """Resolve ``$env:``/``${env:X}``/``%VAR%``/``$HOME``/``~`` prefixes.

    Returns ``None`` when an env-prefixed target cannot be resolved — the
    caller must then fail closed instead of letting the literal form count
    as a relative in-workspace path.
    """
    match = re.match(r"^\$\{env:([^\W\d]\w*)\}", raw, re.IGNORECASE)
    if not match:
        match = re.match(r"^\$env:([^\W\d]\w*)", raw, re.IGNORECASE)
    if match:
        value = os.environ.get(match.group(1)) or os.environ.get(
            match.group(1).upper(), ""
        )
        return value + raw[match.end() :] if value else None
    match = re.match(r"^\$\{([^\W\d]\w*)\}", raw)
    if match:
        name = match.group(1)
        if name.upper() == "HOME":
            return str(Path.home()) + raw[match.end() :]
        value = os.environ.get(name) or os.environ.get(name.upper(), "")
        return value + raw[match.end() :] if value else None
    if raw.upper().startswith("$HOME"):
        return str(Path.home()) + raw[5:]
    if raw.startswith("~"):
        expanded = os.path.expanduser(raw)
        return expanded if expanded != raw else None
    if raw.startswith("%"):
        match = re.match(r"^%([^\W\d][\w()]*)%", raw)
        if match:
            value = os.environ.get(match.group(1)) or os.environ.get(
                match.group(1).upper(), ""
            )
            return value + raw[match.end() :] if value else None
        expanded = os.path.expandvars(raw)
        return expanded if expanded != raw else None
    return raw


def _bash_candidate(raw: str, eff_dir: str | None) -> str | None:
    """Expand env prefixes, then resolve relative targets against ``eff_dir``."""
    candidate = _expand_env_candidate(raw)
    if candidate is None:
        return None
    if eff_dir and not _ABS_FORM_RE.match(candidate):
        candidate = os.path.join(eff_dir, candidate)
    return os.path.normpath(candidate)


def find_bash_disallowed_write_paths(
    cmd: str, config: dict, workdir: str | None = None
) -> list[str]:
    """Return mutating target paths outside the write whitelist.

    Workspace sandbox only constrains cwd; without this check, agents can still
    ``Set-Content C:\\Users\\...`` and escape. Used by ToolOrchestrator.

    Only verb/redirect *targets* are considered so that writing a relative
    report that *mentions* an absolute path in its body is not false-blocked.
    Relative targets are resolved against ``workdir`` (the shell's requested
    cwd, falling back to ``execution.workspace_root``), and cd/pushd/popd
    verbs update the tracked effective directory so chained ``cd ..`` forms
    cannot re-root a later relative write.
    """
    if not cmd:
        return []
    execution = (config or {}).get("execution", {}) or {}
    mode = str(execution.get("sandbox_mode") or "workspace").strip().lower()
    if mode == "host":
        return []
    # Drop -Value/-Content payloads and PowerShell here-strings so report
    # bodies that quote blocked paths do not false-trigger.
    scrubbed = re.sub(
        r"(?is)(?<![A-Za-z])(-(?:Value|Content))\s+"
        r"(@\"[\s\S]*?\"@|@'[\s\S]*?'@|'[^']*'|\"[^\"]*\")",
        " ",
        cmd,
    )
    # Here-strings keep their contents visible to the target scan: an
    # ``iex @"..."@`` or ``$x = @"..."@; iex $x`` payload would otherwise hide
    # the whole command behind the erase. -Value/-Content payloads were
    # already scrubbed above, so report bodies stay unaffected.
    scrubbed = re.sub(r'@\"|\"@', " ", scrubbed)
    # PowerShell (`` ` ``) and bash (``\``) line continuations join the next
    # line into the same command; collapse them so targets past a newline
    # stay inside the scanned segment.
    scrubbed = re.sub(r"[\\`]\r?\n", " ", scrubbed)
    base = workdir
    if not base:
        try:
            from ..session_runtime import current_working_directory

            base = str(current_working_directory())
        except Exception:
            base = None
    if not base:
        base = execution.get("workspace_root") or None
    eff_dir: str | None = None
    if base:
        try:
            eff_dir = os.path.normpath(str(base))
        except Exception:
            eff_dir = None
    dir_stack: list[str | None] = []
    shell_vars: dict[str, str] = {}
    blocked: list[str] = []
    seen: set[tuple[str | None, str]] = set()

    def _resolve_value(raw: str, depth: int = 0) -> str | None:
        """Resolve env forms, then tracked ``$var`` names, against eff_dir."""
        var = _SHELL_VAR_RE.match(raw)
        if var:
            name = var.group(1).lower()
            if name in _PIPELINE_VARS:
                return raw
            if name in _BUILTIN_DIR_VARS:
                if name == "pwd":
                    return eff_dir
                return os.path.expanduser("~") or None
            value = shell_vars.get(name)
            if value is None or depth >= 4:
                return None
            return _resolve_value(value, depth + 1)
        return _bash_candidate(raw, eff_dir)

    def _check(raw: str) -> None:
        if raw in _REDIRECT_PSEUDO_TARGETS:
            return
        # Same token is re-checked when the effective directory moved —
        # '..' means something different after each 'cd'.
        key = (eff_dir, raw)
        if key in seen:
            return
        seen.add(key)
        candidate = _resolve_value(raw)
        if candidate is None or not is_write_allowed(candidate, config):
            blocked.append(raw)

    events = sorted(
        [
            (m.start(), "op", m)
            for m in _BASH_MUTATING_OPENER_RE.finditer(scrubbed)
        ]
        + [(m.start(), "as", m) for m in _ASSIGN_RE.finditer(scrubbed)]
    )
    for _, kind, m in events:
        if kind == "as":
            name = m.group("ps") or m.group("sh") or ""
            value = (
                m.group("psdq")
                or m.group("pssq")
                or m.group("psbare")
                or m.group("shval")
                or ""
            )
            if name:
                shell_vars[name.lower()] = value
            continue
        opener = m
        verb = (opener.group("verb") or "").lower()
        seg = opener.group("verbseg") or opener.group("redirseg") or ""
        if verb in _POP_VERBS:
            if dir_stack:
                eff_dir = dir_stack.pop()
            else:
                blocked.append(verb)
            continue
        tokens = list(_PATH_TOKEN_RE.finditer(seg))
        if verb in _CD_VERBS or verb in _PUSH_VERBS:
            if not tokens:
                # Bare cd/pushd heads to the profile dir — outside the
                # workspace and unverifiable, so fail closed.
                blocked.append(verb)
                continue
            for match in tokens:
                raw = match.group("t").rstrip("\\/") or match.group("t")[:1]
                if re.match(r"^[A-Za-z]:$", raw):
                    raw += "\\"
                _check(raw)
            target = next(
                (
                    match.group("t")
                    for match in tokens
                    if not match.group("t").startswith(("-", "+"))
                ),
                None,
            )
            if target is None:
                # ``cd -``/``cd -L`` and other flag-only forms retarget to
                # OLDPWD/HOME — unverifiable, so fail closed.
                blocked.append(verb)
                continue
            target = target.rstrip("\\/") or target[:1]
            resolved = _resolve_value(target)
            if resolved is not None and is_write_allowed(resolved, config):
                if os.environ.get("CDPATH") and not _ABS_FORM_RE.match(target):
                    # CDPATH can re-root a relative cd anywhere; unverifiable.
                    blocked.append(target)
                    continue
                if verb in _PUSH_VERBS:
                    dir_stack.append(eff_dir)
                eff_dir = os.path.normpath(resolved)
            continue
        for match in tokens:
            raw = match.group("t").rstrip("\\/") or match.group("t")[:1]
            if re.match(r"^[A-Za-z]:$", raw):
                raw += "\\"
            # Plain relative targets resolve inside the workspace; only
            # '..' traversal or absolute/env forms need the whitelist check.
            if not _ABS_TOKEN_START_RE.match(raw) and not _DOTDOT_SEGMENT_RE.search(
                raw
            ):
                continue
            _check(raw)
    return blocked


def is_dry_run(config: dict) -> bool:
    """Dry-run is on when config ``safety.dry_run`` is true or the
    RXYCODE_DRY_RUN env var holds a truthy value."""
    env = os.environ.get("RXYCODE_DRY_RUN", "")
    if env.strip().lower() in ("1", "true", "yes", "on"):
        return True
    safety = (config or {}).get("safety", {}) or {}
    return bool(safety.get("dry_run", False))


def summarize_args(args: Any, max_chars: int = 200) -> Any:
    """Produce a compact, truncated representation of tool args for
    approval prompts and audit logs."""
    if isinstance(args, dict):
        out = {}
        for k, v in args.items():
            s = v if isinstance(v, str) else repr(v)
            if len(s) > max_chars:
                s = s[:max_chars] + "..."
            out[k] = s
        return out
    s = args if isinstance(args, str) else repr(args)
    return s[:max_chars] + "..." if len(s) > max_chars else s
