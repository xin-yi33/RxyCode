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
    r"(?<![\w~./\\:])"
    r"(?:"
    r"[A-Za-z]:(?:[\\/][^\s'\"|;>&]*)?"
    r"|\\{1,2}[^\s'\"|;>&]+"
    r"|/[^\s'\"|;>&]*"
    r"|\$\{env:[^\W\d]\w*\}(?:[\\/.\[][^\s'\"|;>&]*)?"
    r"|\$env:[^\W\d]\w*(?:[\\/.\[][^\s'\"|;>&]*)?"
    r"|\$\{[^}\s'\"|;>&]*\}(?:[\\/.\[][^\s'\"|;>&]*)?"
    r"|\$HOME(?!\w)(?:[\\/.\[][^\s'\"|;>&]*)?"
    r"|\$\("
    r"|\$[^\W\d]\w*(?:[\\/.\[][^\s'\"|;>&]*)?"
    r"|%[^\W\d][\w()]*%(?:[\\/.\[][^\s'\"|;>&]*)?"
    r"|~[^\s'\"|;>&]*"
    r")"
)
# Pseudo-device redirect targets that are not real filesystem writes.
_REDIRECT_PSEUDO_TARGETS = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr"})
# A path-shaped relative token (word + separators). Interesting only when it
# carries a '..' segment — plain filenames resolve inside the workspace.
_REL_TARGET = r"(?<![\w~./\\])[^\s'\"|;>&:/\\]+(?:[\\/][^\s'\"|;>&:/\\]*)*"
_MUT_VERB_ALT = (
    r"Remove-Item|Rename-Item|ri|rni|ren|Set-Content|Add-Content|Clear-Content|Out-File|New-Item|Copy-Item|Move-Item|"
    r"Export-Csv|Export-Clixml|Export-Alias|Set-Item|Clear-Item|New-ItemProperty|Set-ItemProperty|Remove-ItemProperty|"
    r"Rename-ItemProperty|Copy-ItemProperty|Move-ItemProperty|Clear-ItemProperty|Start-BitsTransfer|bitsadmin|"
    r"sc|ac|clc|ni|cpi|mi|ci|hh|regsvr32|presentationhost|msiexec|"
    r"installutil|regasm|regsvcs|mshta|rundll32|scrcons|forfiles|schtasks|control|"
    r"cd|chdir|Set-Location|sl|Push-Location|pushd|popd|Pop-Location|"
    r"del|erase|rmdir|rd|rm|mv|cp|copy|xcopy|robocopy|move|rename|replace|mklink|tee|touch|mkdir|install|dd|truncate|"
    r"shred|patch|tar|unzip|7z|cpio|unrar|mkfifo|mknod|ln|zip|gzip|gunzip|bzip2|bunzip2|xz|unxz|compress|uncompress|"
    r"split|csplit|sponge|makecab|extrac32|"
    r"chmod|chown|chgrp|chattr|setfacl|attrib|icacls|cacls|cipher|compact|takeown|xargs|find|sed|perl|ed|ex|vi|vim|nvim|"
    r"view|nano|emacs|fsutil|reg|crontab|visudo|vipw|vigr|format(?!-)|diskpart|mount|umount|mkfs|fdisk|parted|sgdisk|"
    r"wipefs|hdparm|pvcreate|vgcreate|lvcreate|cryptsetup|losetup|"
    r"rsync|scp|rcp|curl|wget|powershell|pwsh|cmd|bash|sh|zsh|dash|env|sudo|doas|su|nohup|nice|time|timeout|parallel|"
    r"iex|Invoke-Expression|Invoke-Command|eval|source|watch|ssh|pkexec|runas|python|python3|py|node|deno|bun|php|ruby|"
    r"osascript|rscript|julia|certutil|expand|esentutl|cscript|wscript|sort|gpg|openssl|awk|gawk|mawk|nawk|iwr|irm|at|batch|for|"
    r"Invoke-WebRequest|Invoke-RestMethod|"
    # Binaries that write output artifacts (compilers, media/document
    # tools, VCS, cloud/infra, archivers of last resort).
    r"gcc|g\+\+|clang(?:\+\+|-cl)?|javac|rustc|cargo|dotnet|msbuild|csc|vbc|fsc|nasm|yasm|masm|cmake|ninja|meson|scons|"
    r"bazel|buck2|gradle|mvn|tsc|webpack|vite|esbuild|rollup|parcel|swig|protoc|flatc|pip3?|gem|composer|nuget|poetry|"
    r"apt|apt-get|dpkg|rpm|dnf|yum|pacman|zypper|brew|snap|flatpak|ffmpeg|ffprobe|ffplay|magick|gm|pandoc|soffice|"
    r"libreoffice|aria2c|axel|yt-dlp|youtube-dl|espeak|lame|oggenc|opusenc|ps2pdf|wkhtmltopdf|weasyprint|enscript|"
    r"a2ps|groff|nroff|tex|latex|pdflatex|xelatex|lualatex|bibtex|dvips|dvipdf|makeindex|img2pdf|pdftk|qpdf|pdfunite|"
    r"inkscape|objcopy|ranlib|pyinstaller|nuitka|makensis|iscc|electron-packager|signtool|osslsigncode|jarsigner|"
    r"apksigner|codesign|srm|wipe|sdelete|octave|sqlite3|mysqldump|pg_dump|mongodump|git|svn|hg|bzr|docker|podman|"
    r"nerdctl|kubectl|helm|vagrant|packer|terraform|ansible|aws|az|gcloud|gsutil|azcopy|rclone|ftp|tftp|sftp|socat|"
    r"systemctl|service|launchctl|gs\b|npm|yarn|pnpm|sphinx-build|hugo|jekyll|flac"
)
_BASH_MUTATING_OPENER_RE = re.compile(
    r"(?ix)"
    r"(?:"
    rf"(?<![$:])\b(?P<verb>{_MUT_VERB_ALT})\b"
    r"(?P<verbseg>[^\n;|&]*)"
    r"|(?:^|[^>])>{1,2}(?P<redirseg>[^\n;|&]*)"
    r"|(?P<dotnetcall>\[[\w.]+\]\s*::\s*\w+\s*\(|New-Object\b|"
    r"\$[^\W\d]\w*(?:\.[^\W\d]\w*)+\s*\()"
    r"(?P<dotnetseg>[^\n;|&]*)"
    r")"
)
# Method names that read or produce content, not a filesystem target —
# ``.Write(data)`` writes into an already-verified handle, ``ReadAllText``
# touches nothing for write purposes.
_DOTNET_CONTENT_RE = re.compile(
    r"(?i)^(?:Read\w*|Get\w*|Exists|OpenRead|OpenText|Combine|Join|"
    r"Enumerate\w*|List\w*|Has\w*|Test\w*|Split|Parse|TryParse|ToString|"
    r"ChangeExtension|Resolve\w*|Measure\w*|Write|WriteLine|print|printf)$"
)
# ``New-Object`` types that cannot write to the path they receive.
_DOTNET_READER_TYPE_RE = re.compile(
    r"(?i)\b(?:StreamReader|TextReader|StringReader|XmlReader|"
    r"BinaryReader|FileInfo|DirectoryInfo|Path)\b"
)
# Word-level verb matcher for carrier commands (``xargs``/``find -exec``)
# whose own segment swallows the nested verb before it can open a segment.
_MUT_VERB_WORDS_RE = re.compile(rf"(?i)\b(?:{_MUT_VERB_ALT})\b")
_PATH_TOKEN_RE = re.compile(rf"(?ix)(?P<t>{_ABS_TARGET}|{_REL_TARGET})")
_DOTDOT_SEGMENT_RE = re.compile(r"\.{2}(?:[\\/]|$)")
_ABS_TOKEN_START_RE = re.compile(r"^(?:[A-Za-z]:|[\\/~$%!])")
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
_SHELL_VAR_RE = re.compile(
    r"^\$(?:\{([^}]*)\}|([^\W\d]\w*))([\\/.\[].*)?$",
    re.IGNORECASE,
)
# A braced name must be a plain identifier (optionally env:-prefixed) to be
# resolvable; ``${arr[i]}``/``${x:-d}``/other expansion ops are not verifiable.
_BRACED_NAME_RE = re.compile(r"(?:env:)?[^\W\d][\w()]*", re.IGNORECASE)
# ``$x = "v"``/``$env:X = "v"`` (PowerShell) and ``X=v``/``X="v"`` (bash)
# assignments, tracked in order.
_ASSIGN_RE = re.compile(
    r"(?is)"
    r"\$(?P<psenv>env:)?(?P<ps>[^\W\d]\w*)\s*=\s*"
    r"(?:\"(?P<psdq>[^\"]*)\"|'(?P<pssq>[^']*)'|(?P<psbare>[^\s;|&'\"]+))"
    r"|\b(?P<sh>[A-Za-z_]\w*)="
    r"(?:(?P<shansi>\$'[^']*'|\$\"[^\"]*\")|\"(?P<shdq>[^\"]*)\"|"
    r"'(?P<shsq>[^']*)'|(?P<shval>[^\s;|&'\"]*))"
)
# A ``NAME=value`` token binds only when it leads the command segment —
# alone or after earlier assignments. The same text as a later argument
# (``Write-Output TEMP=x``) is data, not a binding, and env builtins are
# dialect-dependent (``set`` binds only in cmd, ``export`` only in bash),
# so neither is allowed to prefix a tracked assignment.
_ASSIGN_PREFIX_RE = re.compile(
    r"(?i)\s*"
    r"(?:[A-Za-z_]\w*\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s'\"|;>&]*)?\s*)*$"
)
# Shell-provided names that map to a knowable directory; everything else a
# mutating target could be stays unverifiable.
_BUILTIN_DIR_VARS = ("pwd", "home")
# Pipeline/loop variables are objects, not paths — never tracked names and
# never path targets, so they resolve to themselves (inside the workspace).
_PIPELINE_VARS = frozenset(
    {"_", "psitem", "input", "args", "this", "matches", "foreach", "event"}
)
# Basename-style properties on pipeline objects are always relative names —
# they cannot hold an absolute path (``$_.FullName`` can, so it fails closed).
_PIPELINE_SAFE_PROPS = re.compile(
    r"^\.(?:name|basename|extension)(?:[\\/]|$)", re.IGNORECASE
)
# Verbs that write only under specific flags: their path arguments are
# search/read roots otherwise and must not be false-blocked.
_FIND_MUT_FLAGS_RE = re.compile(
    r"-(?:exec|execdir|delete|fls|fprint|fprintf)\b", re.IGNORECASE
)
_COND_MUT_VERBS = {
    "sed": r"-i\b|--in-place\b",
    "perl": r"-\w*[ie]\b",
    # ``-oFILE``/``-OFILE`` glue the target onto the flag — no word
    # boundary after the letter.
    "curl": r"-[oOT](?:\b|(?=[A-Za-z]:)|(?=[/\\~$.]))|--output\b|--upload-file\b",
    "wget": r"-O(?:\b|(?=[A-Za-z]:)|(?=[/\\~$.]))|--output-document\b",
    "sort": r"-o(?:\b|(?=[A-Za-z]:)|(?=[/\\~$.]))|--output\b|/o\b",
    "gpg": r"-o(?:\b|(?=[A-Za-z]:)|(?=[/\\~$.]))|--output\b",
    "openssl": r"-out\b",
    "awk": r"-i\b|inplace",
    "gawk": r"-i\b|inplace",
    "mawk": r"-i\b|inplace",
    "nawk": r"-i\b|inplace",
    "iwr": r"-OutFile\b|-o(?:\b|(?=[A-Za-z]:)|(?=[/\~$.]))",
    "irm": r"-OutFile\b|-o(?:\b|(?=[A-Za-z]:)|(?=[/\~$.]))",
    "invoke-webrequest": r"-OutFile\b|-o(?:\b|(?=[A-Za-z]:)|(?=[/\~$.]))",
    "invoke-restmethod": r"-OutFile\b|-o(?:\b|(?=[A-Za-z]:)|(?=[/\~$.]))",
}
# Carrier verbs execute their arguments: the nested command is scanned
# recursively (depth-limited). Encoded-payload flags cannot be decoded
# statically and fail closed.
_CARRIER_VERBS = frozenset({
    "xargs", "parallel", "powershell", "pwsh", "powershell.exe", "pwsh.exe",
    "cmd", "cmd.exe", "bash", "sh", "zsh", "dash", "env", "sudo", "doas",
    "su", "nohup", "nice", "time", "timeout", "watch", "ssh", "pkexec",
    "runas", "iex", "invoke-expression", "invoke-command", "eval", "source",
    "cscript", "wscript", "at", "batch",
})
# Carriers/interpreters that execute a payload arriving on stdin when no
# command argument is given (``echo 'rm /etc/x' | sh``). Piped with only
# flag args (or nothing), the payload is unverifiable — fail closed.
# ``ssh``/``at``/``batch`` additionally need a second argument: their
# first token is a host/time spec, not the command itself.
_STDIN_EXECUTORS = frozenset({
    "xargs", "parallel", "powershell", "pwsh", "powershell.exe", "pwsh.exe",
    "cmd", "cmd.exe", "bash", "sh", "zsh", "dash", "env", "sudo", "doas",
    "su", "nohup", "nice", "time", "timeout", "watch", "ssh", "pkexec",
    "runas", "iex", "invoke-expression", "invoke-command", "eval", "source",
    "cscript", "wscript", "at", "batch",
})
_STDIN_TWO_ARG = frozenset({"ssh", "at", "batch"})
_ENCODED_CARRIERS = frozenset(
    {"powershell", "pwsh", "powershell.exe", "pwsh.exe", "cmd", "cmd.exe"}
)
_ENC_FLAG_RE = re.compile(r"-(?:enc|ec|e|encodedcommand)\b", re.IGNORECASE)
# Interpreters run opaque code strings with -c/-e; a write-ish API inside
# makes the target unverifiable — fail closed.
_INTERP_VERBS = frozenset(
    {"python", "python3", "py", "node", "deno", "bun", "php", "ruby",
     "osascript", "rscript", "julia"}
)
_INTERP_CODE_FLAG_RE = re.compile(
    r"(?:-c|-e|-E|-r|--eval|--command|-e:)\b", re.IGNORECASE
)
_CODE_MUT_RE = re.compile(
    r"\b(?:open\s*\(|fopen|write(?:file|text|all|_file|_text|_bytes|bytes|lines)?s?\s*[({]|"
    r"remove|unlink|delete|rmdir|rmtree|makedirs|mkdir\s*\(|rename|replace|copyfile|"
    r"copy2?|move|chmod|chown|truncate|mkfifo|mknod|symlink|link\s*\(|"
    r"os\.system|system|spawn|process\.|\.rm\b|subprocess|popen|eval\s*\(|"
    r"exec\s*\(|__import__|fs\.|do\s+shell\s+script|io\.write|"
    r"file_put_contents|fwrite|set-content|remove-item|out-file|invoke-expression|"
    r"save\w*\s*\(|to_csv|to_excel|to_parquet|to_pickle|to_feather|"
    r"to_hdf|to_latex|to_json|to_html|to_xml|to_stata|to_sql|to_markdown|"
    r"tofile|urlretrieve|ZipFile|TarFile|BZ2File|GzipFile|LZMAFile|Workbook|"
    r"make_archive|unpack_archive|extractall|extract|sqlite3\.connect|"
    r"FileHandler|removedirs|renames|hardlink|lchown|lchmod|chflags|lchflags|"
    r"link_to|touch|write_text|write_bytes|getattr|\.output\s*\(|`)",
    re.IGNORECASE,
)
# Write targets produced at runtime (env/argv/stdin/temp dirs/script
# paths) cannot be checked statically — fail closed. The second group
# covers expressions that *compute* the target (decode/format/join/
# concat/slice/reflection): a quoted hex string is not the real path,
# ``bytes.fromhex('433a…').decode()`` produces it at runtime.
_CODE_DYN_RE = re.compile(
    r"(?:os\.environ|environ\s*\[|getenv|\bsys\.|process\.env|process\.argv|"
    r"\bENV\s*\[|\bARGV\b|expandvars|expanduser|Path\.home|Path\.cwd|"
    r"tempfile|tmpdir|gettempdir|tempnam|mkstemp|mkdtemp|"
    r"__file__|__dirname|__filename|__main__|__builtins__|input\s*\(|readline|"
    r"getlogin|getuser|getpass|\$argv|\$args|param\s*\(|"
    r"fromhex|unhexlify|b64|base64|\bdecode|\bencode|\bchr\s*\(|\bord\s*\(|"
    r"\bbytes\s*\(|bytearray|\bstr\s*\(|\brepr\s*\(|\bint\s*\(|\bhex\s*\(|"
    r"\boct\s*\(|\bbin\s*\(|\.join|\bjoin\s*\(|\bformat|%[sdr]\b|f[\"']|"
    r"\\x[0-9a-f]|\\u[0-9a-f]|setattr|delattr|__import__|importlib|"
    r"\beval(?!\s*\()|\bexec(?!\s*\()|\bcompile(?!\s*\()|"
    r"\bglobals|\blocals|\bvars\s*\(|"
    r"os\.path|os\.getcwd|os\.listdir|os\.walk|os\.scandir|os\.getlogin|"
    r"\.resolve|\babspath|\brealpath|\bglob|listdir|scandir|"
    r"(?:os|shutil|fs|File|Path|io)\.(?:remove|unlink|rmdir|rename|"
    r"replace|mkdir|makedirs|chmod|chown|truncate|symlink|link|mkfifo|"
    r"mknod|removexattr|setxattr|utime|rmtree|copy|copy2|copyfile|"
    r"copytree|move|make_archive|unpack_archive|write|writeFileSync|"
    r"appendFileSync|unlinkSync|renameSync|rmSync|mkdirSync|rm|mv|cp|"
    r"delete|open|writeFile|appendFile|createWriteStream)(?!\s*\()|\.upper|\.lower|"
    r"\.replace|\.strip|\.title|\.casefold|\.split|\.translate|\.group|"
    r"\.sub\b|re\.search|re\.match|\bread\b|\.read|subprocess|check_output|"
    r"popen|urllib|urlopen|requests|json\.|pickle|yaml\.|uuid|random|"
    r"socket|\.time|datetime|\btmp|\bhome\b|homedir|appdata|programdata|"
    r"programfiles|systemroot|windir|userprofile|homepath|homedrive|"
    r"\bcwd\b|curdir|\bpwd\b|['\"]\s*\+|\+\s*['\"]|['\"]\s*\[)",
    re.IGNORECASE,
)
# Path-accepting calls in interpreter inline code. The target argument of
# these must be a literal for the write gate to verify it; a call like
# ``f.write(data)`` whose argument is content is intentionally absent.
_CODE_TARGET_API_RE = re.compile(
    r"(?i)(?<![\w])"
    r"(open|fopen|NamedTemporaryFile|mkstemp|mkdtemp|expanduser|"
    r"copy|copy2|copyfile|copytree|cp|move|rename|replace|remove|unlink|delete|"
    r"rmtree|makedirs|mkdir|rmdir|chmod|chown|truncate|symlink|link|"
    r"hardlink|mkfifo|mknod|setxattr|utime|touch|file_put_contents|"
    r"file_get_contents|writeFileSync|writeFile|appendFileSync|appendFile|"
    r"cpSync|copyFileSync|renameSync|rmSync|rmdirSync|mkdirSync|unlinkSync|"
    r"chmodSync|chownSync|truncateSync|symlinkSync|linkSync|openSync|"
    r"createWriteStream|mkdtempSync|utimesSync|rm|mv|io\.open|"
    r"File\.open|File\.delete|File\.rename|File\.copy|File\.chmod|"
    r"FileUtils\.\w+|save|savefig|savetxt|savez|savez_compressed|tofile|"
    r"to_csv|to_excel|to_parquet|to_pickle|to_feather|to_hdf|to_latex|"
    r"to_json|to_html|to_xml|to_stata|to_sql|to_markdown|urlretrieve|"
    r"ZipFile|TarFile|BZ2File|GzipFile|LZMAFile|Workbook|make_archive|"
    r"unpack_archive|extractall|extract|connect|FileHandler|output|"
    r"removedirs|renames|link_to|symlink_to|hardlink_to|lchown|lchmod|"
    r"chflags|lchflags)\s*\(",
    re.IGNORECASE,
)
# ``Call(args).mutating_method()`` — the target lives on the receiver
# (``Path(os.environ['T']).unlink()``), not in the method's own args.
_CODE_RECV_RE = re.compile(
    r"(?i)[\w.]+\s*\(((?:[^()]|\([^()]*\))*)\)\s*\.\s*"
    r"(?:write_text|write_bytes|touch|unlink|rename|replace|mkdir|rmdir|"
    r"chmod|chown|open|delete|remove|move|copy|link_to|symlink_to|"
    r"hardlink_to|extract|extractall|utime|dump|truncate|"
    r"write|writelines|append)\s*\("
)
# Bare-name receivers whose method mutates the path the name holds —
# ``p.unlink()`` where ``p=Path(x)``. Kept narrow: ``rename``/``copy``/
# ``write`` receivers would false-positive on streams and objects.
_CODE_NAMERECV_RE = re.compile(
    r"(?i)(?<![\w.])([A-Za-z_]\w*(?:\s*\.\s*\w+)*)\s*\.\s*"
    r"(?:unlink|touch|mkdir|rmdir|link_to|symlink_to|hardlink_to|utime)\s*\("
)
# Module/class names that legitimately appear before ``.unlink`` etc —
# ``os.unlink('x')`` is a function call covered by the API scan, not a
# name-bound path receiver.
_CODE_NAMERECV_HEADS = frozenset(
    {
        "os", "sys", "pathlib", "shutil", "io", "fs", "path", "subprocess",
        "re", "json", "functools", "importlib", "builtins", "__builtins__",
        "tempfile", "glob", "stat", "logging", "datetime", "time", "math",
        "collections", "itertools", "platform", "signal", "socket",
        "urllib", "node", "php", "ruby", "python",
    }
)
# ``(expr).method()`` — a parenthesized or subscript receiver
# (``(Path(env)/'x').unlink()``, ``arr[0].unlink()``), optionally through
# attribute hops (``Path(env).parent.unlink()``).
_CODE_PAREN_RECV_RE = re.compile(
    r"(?i)[\)\]](?:\s*\.\s*[A-Za-z_]\w*)*\s*\.\s*"
    r"(?:write_text|write_bytes|touch|unlink|rename|replace|mkdir|rmdir|"
    r"chmod|chown|open|delete|remove|move|copy|link_to|symlink_to|"
    r"hardlink_to|extract|extractall|utime|dump|truncate|"
    r"write|writelines|append)\s*\("
)
# Call heads that construct a path from their arguments — their inner
# expression is checked, the head name itself need not resolve.
_CODE_RECV_CTORS = frozenset(
    {
        "path", "purepath", "posixpath", "windowspath", "pureposixpath",
        "purewindowspath", "file", "directory", "open", "io.open",
        "namedtemporaryfile", "temporaryfile", "bytesio", "stringio",
        "iobase", "pathlib.path",
    }
)
# ``exec``/``eval``/``compile`` calls: safe only when every argument is a
# literal whose body carries no mutating call or dynamic source.
_CODE_EXEC_RE = re.compile(r"(?i)\b(?:exec|eval|compile)\s*\(")
# A dispatched call — ``getattr(os,'remove')(t)``, ``__builtins__['open'](t)``
# or ``partial(os.remove,t)()`` — makes the code unverifiable even when no
# named write API appears.
_CODE_DISP_CALL_RE = re.compile(r"[\)\]]\s*\(")
# A binding value that is itself a mutating callable —
# ``x = os.remove`` / ``x = getattr(os, 'remove')`` — so a later ``x(t)``
# call inherits the literal-only argument rule.
_CODE_CALLABLE_REF_RE = re.compile(
    r"(?i)(?:getattr|setattr|partial|eval|exec|compile|__import__|"
    r"globals|locals|attrgetter|methodcaller|itemgetter)\s*\(|"
    r"^(?:[\w.]+\.)?(?:open|remove|unlink|rename|replace|copy\w*|move|"
    r"rmtree|system|popen|exec\w*|spawn\w*|delete|truncate|mkdir|rmdir|"
    r"chmod|chown|symlink|link|mkfifo|mknod|save|dump|extract\w*|"
    r"urlretrieve|put|install|run|call|check_output|write)\s*$"
)


def _code_arg_region(text: str, start: int) -> str:
    """Return the argument region after ``text[start]`` (an opening ``(``).

    Scans balanced brackets outside quotes so a ``)`` inside a literal or a
    nested call does not truncate the region early.
    """
    depth = 0
    quote = None
    end = min(len(text), start + 240)
    i = start
    while i < end:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return text[start:i]
            depth -= 1
        i += 1
    return text[start:end]
# Two-path calls whose destination is also a write target.
_TWO_TARGET_APIS = frozenset(
    {
        "copy", "copy2", "copyfile", "copytree", "cp", "move", "rename",
        "replace", "symlink", "link", "hardlink", "cpsync", "copyfilesync",
        "renamesync", "renames", "extract", "unpack_archive", "urlretrieve",
    }
)
# cmd.exe verbs where ``/x`` tokens are options rather than POSIX paths.
# A ``/flag:value`` or ``/flag=value`` can still carry a target inside the
# flag itself, so the value is checked; the bare flag is skipped.
_CMD_VERBS = frozenset(
    "attrib icacls cacls cipher compact takeown fsutil reg format certutil "
    "expand makecab extrac32 diskpart sort bitsadmin esentutl for del erase "
    "rd rmdir mkdir md copy move ren xcopy robocopy replace mklink forfiles "
    "schtasks regsvr32 msiexec control installutil regasm regsvcs rundll32 "
    "mshta".split()
)
_MAX_CARRIER_DEPTH = 3


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
    cmd: str,
    config: dict,
    workdir: str | None = None,
    _depth: int = 0,
    _piped: bool = False,
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
    def _unescape(text: str) -> str:
        # ``\`` mid-word (``r\m``, ``r\\m``) is a bash escape — strip it.
        # At a word start (``\Windows``, ``\\share``) or after a
        # ``:``/``}``/``%`` it is a path root or suffix, and ``$var\``
        # binds the var's path suffix (``$PWD\inside.txt``) — all stay.
        # `` ` `` (``Set-Cont`ent``) is the PowerShell escape: it is never
        # a path character, so a word-internal `` `<letter>`` drops out.
        out: list[str] = []
        for i, ch in enumerate(text):
            if (
                ch == "`"
                and i + 1 < len(text)
                and text[i + 1].isalnum()
                and i > 0
                and (text[i - 1].isalnum() or text[i - 1] in "_-.")
            ):
                # Mid-word only: ``Set-Cont`ent`` is a PS escape. A leading
                # or paired `` ` `` is bash command substitution and stays
                # for the command-position check.
                continue
            if ch == "\\" and i + 1 < len(text) and text[i + 1].isalpha():
                prev = text[i - 1] if i else ""
                if prev == "\\" or prev.isalnum() or prev == "_":
                    j = i - 1
                    while j >= 0 and (text[j].isalnum() or text[j] == "_"):
                        j -= 1
                    # ``$env:OUT\f`` — the walk stops at ``:``; a ``env:``
                    # prefix belongs to the same ``$`` ref, so keep ``\``
                    # there too (it is the var's path suffix).
                    if j >= 4 and text[j] == ":" and text[j - 3 : j].lower() == "env" and text[j - 4] == "$":
                        out.append(ch)
                    elif not (j >= 0 and text[j] == "$"):
                        continue
                    else:
                        out.append(ch)
                    continue
            out.append(ch)
        return "".join(out)

    # The shell concatenates words before parsing them: ``r'm' x``,
    # ``r"m" x`` and ``r\m x`` all reach the gate as ``rm x``. Collapse
    # word-internal quotes and backslash-escaped letters so the opener
    # sees the verb the shell will actually run. ``\`` only escapes when
    # unquoted — inside 'C:\Users\x' it is a literal path separator.
    # Collapsing quotes can reveal new escapes, so loop to stable.
    prev = None
    while prev != scrubbed:
        prev = scrubbed
        spans = []
        qpos = 0
        while qpos < len(scrubbed):
            if scrubbed[qpos] in "\"'":
                close = scrubbed.find(scrubbed[qpos], qpos + 1)
                end = close if close != -1 else len(scrubbed)
                spans.append((qpos, end))
                qpos = end + 1 if close != -1 else len(scrubbed)
            else:
                qpos += 1
        rebuilt: list[str] = []
        last = 0
        for start, end in spans:
            rebuilt.append(_unescape(scrubbed[last:start]))
            word_before = start > 0 and (
                scrubbed[start - 1].isalnum() or scrubbed[start - 1] == "_"
            )
            word_after = end + 1 < len(scrubbed) and (
                scrubbed[end + 1].isalnum() or scrubbed[end + 1] == "_"
            )
            if end < len(scrubbed) and (word_before or word_after):
                # A quote wedged inside a word (``r'm'``/``x"y"z``) is not
                # a string delimiter — the shell concatenates it into the
                # word, so drop the quote pair and keep the inner text.
                # A free-standing quoted argument stays intact so code
                # literals inside it survive for the interpreter checks.
                rebuilt.append(scrubbed[start + 1 : end])
            else:
                rebuilt.append(scrubbed[start : end + 1])
            last = end + 1
        rebuilt.append(_unescape(scrubbed[last:]))
        scrubbed = "".join(rebuilt)
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
        """Resolve tracked ``$var`` names first, then env forms, vs eff_dir."""
        if raw.startswith("$(") or "`" in raw or raw == "{}":
            # Command substitution executes regardless of position, and an
            # xargs/find ``{}`` placeholder resolves outside our tracking.
            return None
        if depth >= 4:
            return None
        env = re.match(r"^\$\{?env:([^\W\d]\w*)\}?", raw, re.IGNORECASE)
        if env:
            name = "env:" + env.group(1).lower()
            if name in shell_vars:
                # ``$env:X = "v"`` rebinds the process env inside the
                # command — the tracked value wins over the inherited one.
                # A bare ``X=v`` does not bind this namespace.
                return _resolve_value(shell_vars[name] + raw[env.end():], depth + 1)
            return _bash_candidate(raw, eff_dir)
        loopvar = re.match(r"^%+([A-Za-z])($|[\\/.\[])", raw)
        if loopvar:
            # ``%i``/``%%i`` are cmd for-loop vars bound by the enclosing
            # ``for`` — resolve to an in-workspace basename, the same
            # treatment pipeline ``$_`` gets.
            return _resolve_value("x" + raw[loopvar.end(1) :], depth + 1)
        atvar = re.match(r"^@[A-Za-z]+", raw)
        if atvar:
            # ``forfiles`` iteration variables (``@path``/``@fname``/…)
            # bind to each iterated name — a basename placeholder, like
            # the ``for %i`` treatment.
            return _resolve_value("x" + raw[atvar.end() :], depth + 1)
        pct = re.match(r"^%([^\W\d][\w()]*)%", raw)
        if pct:
            # ``%X%`` reads the process env — only an ``$env:X = v``
            # assignment can rebind it inside the command.
            name = "env:" + pct.group(1).lower()
            if name in shell_vars:
                value = shell_vars[name]
                suffix = raw[pct.end() :]
                if not value and not suffix:
                    return None
                return _resolve_value(value + suffix, depth + 1)
            return _bash_candidate(raw, eff_dir)
        bang = re.match(r"^!([^\W\d]\w*)!", raw)
        if bang:
            # ``!X!`` is cmd delayed expansion — same env/tracked lookup
            # as ``%X%``; an unverifiable value fails closed below.
            name = "env:" + bang.group(1).lower()
            if name in shell_vars:
                value = shell_vars[name]
                suffix = raw[bang.end() :]
                if not value and not suffix:
                    return None
                return _resolve_value(value + suffix, depth + 1)
            env_hit = os.environ.get(bang.group(1)) or os.environ.get(
                bang.group(1).upper()
            )
            if env_hit is None:
                return None
            return _resolve_value(env_hit + raw[bang.end() :], depth + 1)
        var = _SHELL_VAR_RE.match(raw)
        if var:
            braced = var.group(1) is not None
            if braced:
                inner = var.group(1)
                if not _BRACED_NAME_RE.fullmatch(inner):
                    return None
                name = inner.lower()
            else:
                name = var.group(2).lower()
            suffix = var.group(3) or ""
            if name in shell_vars:
                # Membership, not truthiness: ``X=""`` is still tracked,
                # and an empty value must not fall back to the process env.
                value = shell_vars[name]
                if not value and not suffix:
                    return None
                if suffix:
                    # ``X=v`` binds only under bash and ``$X=v`` only under
                    # PowerShell — under the other dialect ``$X`` stays
                    # empty and the suffix alone is the target. Check that
                    # interpretation too: ``$X\pwn`` -> ``\pwn`` (drive
                    # root) must not pass because one dialect binds.
                    unset = _bash_candidate(suffix, eff_dir)
                    if unset is not None and not is_write_allowed(unset, config):
                        return unset
                return _resolve_value(value + suffix, depth + 1)
            if name in _PIPELINE_VARS:
                # ``$_``/``$args`` alone are not paths. A property or index
                # (``$_.FullName``/``$args[0]``) can hold an absolute path
                # outside the workspace — unverifiable, fail closed —
                # except basename-style properties, which stay relative.
                if not suffix:
                    return raw
                safe = _PIPELINE_SAFE_PROPS.match(suffix)
                if safe:
                    # Substitute a placeholder basename; a trailing
                    # ``\..\evil`` can still traverse out of the workspace.
                    tail = suffix[safe.end():]
                    return _bash_candidate("x/" + tail if tail else "x", eff_dir)
                return None
            if name in _BUILTIN_DIR_VARS:
                base_dir = eff_dir if name == "pwd" else (
                    os.path.expanduser("~") or None
                )
                return base_dir + suffix if base_dir else None
            value = shell_vars.get(name)
            if value:
                if depth >= 4:
                    return None
                return _resolve_value(value + suffix, depth + 1)
            if var.group(1) is not None:
                # Braced ``${X}`` resolves from the environment when no
                # earlier assignment tracked it; bare ``$X`` fails closed.
                return _bash_candidate(raw, eff_dir)
            return None
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

    def _rescan_tail(text: str) -> None:
        # A verb's segment swallows everything to the next top-level
        # separator, so a ``>`` or nested verb inside it never opened its
        # own event — rescan the tail and merge any blocks it finds.
        for hit in find_bash_disallowed_write_paths(
            text, config, workdir=eff_dir, _depth=_depth + 1, _piped=_piped
        ):
            if hit not in blocked:
                blocked.append(hit)

    # Quoted spans mask assignment detection: 'X=D:\evil' inside quotes is
    # string content, not an assignment (an unclosed quote quotes to EOL).
    quoted_spans: list[tuple[int, int]] = []
    qpos = 0
    while qpos < len(scrubbed):
        if scrubbed[qpos] in "\"'":
            quote = scrubbed[qpos]
            close = scrubbed.find(quote, qpos + 1)
            quoted_spans.append((qpos, close if close != -1 else len(scrubbed)))
            qpos = close + 1 if close != -1 else len(scrubbed)
        else:
            qpos += 1

    def _in_quotes(pos: int) -> bool:
        return any(start <= pos < end for start, end in quoted_spans)

    def _assign_prefix_ok(pos: int) -> bool:
        # The text between the previous separator and the match must be a
        # pure assignment chain (optionally led by an env builtin like
        # ``export``/``set``) — a command word makes ``NAME=v`` an argument.
        seg_start = max(masked.rfind(c, 0, pos) for c in ";|&\n") + 1
        return bool(_ASSIGN_PREFIX_RE.match(masked[seg_start:pos]))

    # Separators inside quotes are literal text, not command boundaries —
    # mask them so 'os.remove("x")' inside one quoted arg stays in the
    # interpreter's segment.
    masked_chars = list(scrubbed)
    for start, end in quoted_spans:
        for pos in range(start, end):
            if masked_chars[pos] in ";|&\n":
                masked_chars[pos] = " "
    masked = "".join(masked_chars)

    # ``$'...'`` ANSI-C / ``$"..."`` locale strings, ``$(...)`` and
    # backticks evaluate at runtime — when they sit where a command name
    # goes the executed verb is unverifiable, so fail closed.
    for m in re.finditer(r"\$'|\$\"|`|\$\(", masked):
        if _in_quotes(m.start()):
            continue
        seg_start = max(masked.rfind(c, 0, m.start()) for c in ";|&\n") + 1
        if _ASSIGN_PREFIX_RE.match(masked[seg_start : m.start()]):
            blocked.append(m.group())

    events = sorted(
        [
            (m.start(), "op", m)
            for m in _BASH_MUTATING_OPENER_RE.finditer(masked)
            # ``>`` inside quotes is literal text (``echo 'a > /x'``), not
            # a shell redirect — only unquoted ``>`` opens a redir seg.
            if not (m.group("redirseg") is not None and _in_quotes(m.start()))
            # ``schtasks /sc`` is a flag, not Set-Content — a whole-token
            # verb glued to ``/`` is a cmd option, never an invocation.
            and not (
                m.group("verb") is not None
                and m.start() > 0
                and masked[m.start() - 1] == "/"
            )
        ]
        + [
            (m.start(), "as", m)
            for m in _ASSIGN_RE.finditer(masked)
            if not _in_quotes(m.start()) and _assign_prefix_ok(m.start())
        ]
    )
    for _, kind, m in events:
        if kind == "as":
            name = m.group("ps") or m.group("sh") or ""
            value = (
                m.group("psdq")
                or m.group("pssq")
                or m.group("psbare")
                or m.group("shdq")
                or m.group("shsq")
                or m.group("shval")
                or ""
            )
            if name and m.group("shansi") is None:
                # ANSI-C ``$'...'``/locale ``$"..."`` values cannot be
                # expanded statically — leave the name untracked so a
                # later reference fails closed. ``$env:X = v`` binds the
                # ``env:`` namespace only — a bare ``X=v`` is not an env
                # assignment in any dialect and must not satisfy it.
                key = ("env:" if m.group("psenv") else "") + name.lower()
                shell_vars[key] = value
            continue
        opener = m
        verb = (opener.group("verb") or "").lower()
        seg = (
            opener.group("verbseg")
            or opener.group("redirseg")
            or opener.group("dotnetseg")
            or ""
        )
        # A verb reached through ``|`` receives stdin from the previous
        # stage; shells/interpreters can then run an unseen payload.
        sep_pos = max(masked.rfind(c, 0, m.start()) for c in ";|&\n")
        piped = sep_pos >= 0 and masked[sep_pos] == "|"
        piped = piped or _piped
        if opener.group("dotnetcall") is not None:
            # ``[IO.File]::WriteAllText(path, x)`` / ``$x.Save(path)`` /
            # ``New-Object IO.StreamWriter path`` write without any shell
            # verb. Literals are masked out of ``seg`` — scan the raw
            # span: a non-content call must take only statically
            # verifiable arguments; every literal and unquoted token in
            # its argument region is a candidate target.
            call = (opener.group("dotnetcall") or "").strip()
            draw = scrubbed[opener.start("dotnetcall") : opener.end()]
            member = call.rstrip("(").rsplit(":", 1)[-1].rsplit(".", 1)[-1].strip()
            if call.lower().startswith("new-object"):
                if not _DOTNET_READER_TYPE_RE.search(draw):
                    dmasked = re.sub(
                        r'"[^"]*"|\'[^\']*\'', " ", draw[call.__len__() :]
                    )
                    for lit in re.finditer(
                        r'"([^"]*)"|\'([^\']*)\'', draw[call.__len__() :]
                    ):
                        _check(lit.group(1) or lit.group(2) or "")
                    for tok in _PATH_TOKEN_RE.finditer(dmasked):
                        t = tok.group("t").rstrip("\\/") or tok.group("t")[:1]
                        if not t.startswith(("-", "+")):
                            _check(t)
                continue
            dirty = call if not _DOTNET_CONTENT_RE.match(member) else ""
            if dirty:
                for cm in re.finditer(r"(?<![\w$])(\w+)\s*\(", draw):
                    if _DOTNET_CONTENT_RE.match(cm.group(1)):
                        continue
                    region = _code_arg_region(draw, cm.end())
                    work = re.sub(r"(?i)(?<![\w])[bru]+(?=['\"])", "", region)
                    work = re.sub(r'"[^"]*"|\'[^\']*\'', "", work)
                    if _CODE_DYN_RE.search(work):
                        blocked.append(member)
                        break
                    bad_arg = False
                    for arg in work.split(","):
                        stripped = re.sub(r"[-+]?\d[\d_]*", "", arg)
                        stripped = re.sub(r"\b\w+\s*=", "", stripped)
                        if re.search(r"[(\[{+*%/&|^~<>!-]|\w", stripped):
                            blocked.append(member)
                            bad_arg = True
                            break
                    if bad_arg:
                        break
                    for lit in re.finditer(
                        r'"([^"]*)"|\'([^\']*)\'', region
                    ):
                        _check(lit.group(1) or lit.group(2) or "")
                    for tok in _PATH_TOKEN_RE.finditer(work):
                        t = tok.group("t").rstrip("\\/") or tok.group("t")[:1]
                        if not t.startswith(("-", "+")):
                            _check(t)
            continue
        if verb == "for":
            # ``for X in GLOB; do <verb>`` — the loop var binds to iterated
            # names, so a mutating body makes the ``in`` set the write
            # source. Register the var as a basename placeholder and check
            # the glob; ``/f`` iterates command output (unverifiable) and
            # ``/r <dir>`` iterates the rooted tree.
            var_m = re.match(r"\s*[%$]?([^\W\d]\w*)\s+in\b", seg)
            if var_m:
                shell_vars[var_m.group(1).lower()] = "x"
            # The mutating body lives past ``do``/``;`` — check the
            # segment plus whatever follows this verb's span.
            if _MUT_VERB_WORDS_RE.search(seg + masked[opener.end() :]):
                flag = re.match(r"\s*/([A-Za-z])", seg)
                if flag and flag.group(1).lower() == "f":
                    blocked.append(verb)
                    continue
                if flag and flag.group(1).lower() == "r":
                    root = re.search(
                        r"(?i)/r(?:oot)?\s+(?:root=)?([^\s'\"()]+)", seg
                    )
                    if root is None:
                        blocked.append(verb)
                        continue
                    _check(root.group(1))
                in_m = re.search(r"(?i)\bin\s+\(?([^\s;'\"()]+)", seg)
                if in_m is None:
                    blocked.append(verb)
                    continue
                _check(in_m.group(1))
            # ``do del C:\x`` sits inside this verb's segment — rescan so
            # the body verb still gets its own check.
            _rescan_tail(seg)
            continue
        if verb in _POP_VERBS:
            _rescan_tail(seg)
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
                if (
                    os.environ.get("CDPATH") or shell_vars.get("cdpath")
                ) and not _ABS_FORM_RE.match(target):
                    # CDPATH can re-root a relative cd anywhere; unverifiable.
                    blocked.append(target)
                    continue
                if verb in _PUSH_VERBS:
                    dir_stack.append(eff_dir)
                eff_dir = os.path.normpath(resolved)
            _rescan_tail(seg)
            continue
        if verb == "find":
            if _FIND_MUT_FLAGS_RE.search(seg):
                blocked.append(verb)
            else:
                _rescan_tail(seg)
            continue
        if verb in _CARRIER_VERBS and not seg.startswith((".", "(")):
            # ``time.sleep(3)`` is a call expression, not the ``time``
            # carrier — a ``.``/``(`` suffix means no command tail.
            if verb in _ENCODED_CARRIERS and _ENC_FLAG_RE.search(seg):
                blocked.append(verb)
                continue
            tail = seg.strip()
            # Unwrap only a fully-quoted payload (``iex 'rm x'``); blind
            # stripping would unbalance quotes inside e.g. ``cmd /c``.
            if len(tail) > 1 and tail[0] in "\"'" and tail[0] == tail[-1]:
                tail = tail[1:-1]
            resolved = tail
            if _SHELL_VAR_RE.match(tail):
                # ``iex $x``/``eval $x``: scan the resolved payload itself.
                resolved = _resolve_value(tail)
                if resolved is None:
                    blocked.append(verb)
                    continue
            if resolved and _depth >= _MAX_CARRIER_DEPTH:
                blocked.append(verb)
                continue
            if piped and verb in _STDIN_EXECUTORS:
                nonflag_words = [
                    w for w in resolved.split()
                    if not w.startswith(("-", "+", "/"))
                ]
                # A piped executor with no visible command runs its stdin;
                # ssh/at/batch consume the first token themselves.
                needed = 2 if verb in _STDIN_TWO_ARG else 1
                if len(nonflag_words) < needed:
                    blocked.append(verb)
                    continue
            sub = find_bash_disallowed_write_paths(
                resolved,
                config,
                workdir=eff_dir,
                _depth=_depth + 1,
                _piped=piped,
            )
            if sub:
                blocked.append(verb)
                continue
            # No nested verbs — the tail itself may be a script path;
            # flag-looking tokens (``-c``/``/c``) are not paths.
            if resolved:
                for token in _PATH_TOKEN_RE.finditer(resolved):
                    t = token.group("t").rstrip("\\/") or token.group("t")[:1]
                    if t.startswith(("-", "+")) or re.match(
                        r"^/[A-Za-z](?::|$)", t
                    ):
                        continue
                    _check(t)
            continue
        if verb in _INTERP_VERBS and _INTERP_CODE_FLAG_RE.search(seg):
            # Literals come from the unmasked ``scrubbed`` span — ``seg``
            # blanks ``;`` inside quotes, which would corrupt code-level
            # statement splitting.
            raw_seg = (
                scrubbed[opener.start("verbseg") : opener.end("verbseg")]
                if opener.group("verbseg") is not None
                else seg
            )
            lit_texts = [
                (lit.group(1) or lit.group(2) or "").strip()
                for lit in re.finditer(r'"([^"]*)"|\'([^\']*)\'', raw_seg)
            ]
            # ``name = expr`` bindings inside the code string are statically
            # visible — ``p='ok.txt'; Path(p).unlink()`` resolves, while
            # ``p=Path(env); p.unlink()`` fails closed. Extracted from the
            # raw literal text because ``seg`` masks ``;`` inside quotes.
            code_src = " ".join(lit_texts)
            code_vars = {}
            for am in re.finditer(
                r"(?<![\w.])([A-Za-z_]\w*)\s*"
                r"(<<=|>>=|\+=|-=|\.=|\*=|/=|%=|\|=|&=|\^=|=)"
                r"(?!=)\s*([^;\n]+)",
                code_src,
            ):
                name, op, value = am.groups()
                if op == "=":
                    code_vars[name] = value
                    continue
                prev = code_vars.get(name, "")
                pm = re.fullmatch(r"['\"]([^'\"]*)['\"]", prev.strip())
                vm = re.fullmatch(r"['\"]([^'\"]*)['\"]", value.strip())
                if pm and vm and op in ("+=", ".="):
                    # ``x='ok'; x+='/sub'`` — pure literal concatenation
                    # stays statically checkable.
                    code_vars[name] = repr(pm.group(1) + vm.group(1))
                else:
                    # ``x+=expr`` with a runtime side — bind a poisoned
                    # expression so later lookups fail closed.
                    code_vars[name] = value.strip() + "+"
            if (
                _CODE_MUT_RE.search(seg)
                or _CODE_DISP_CALL_RE.search(seg)
                or any(
                    _CODE_CALLABLE_REF_RE.search(
                        re.sub(r'"[^"]*"|\'[^\']*\'', "", v).strip()
                    )
                    for v in code_vars.values()
                )
            ):
                # Each write-API's *target* argument must be a plain
                # literal — a computed expression (env/argv/transforms/
                # calls) produces the path at runtime, so fail closed.
                # Content arguments (``f.write(data)``) and literals the
                # code passes through stay allowed and still get checked
                # as paths by the literal loop below.
                dirty = False
                seen_api = False

                def _lookup(name: str, _vars: dict = code_vars):
                    v = _vars.get(name)
                    if v is None:
                        v = shell_vars.get(name)
                    return v

                def _tail_dirty(tail: str) -> bool:
                    """Check a producer/receiver expression.

                    Literals get path-checked, call args get the literal-only
                    rule, and a bare name/attribute chain must resolve to a
                    statically known value.
                    """
                    t_lits = [
                        t.strip("\"'")
                        for t in re.findall(
                            r'"[^"]*"|\'[^\']*\'', tail
                        )
                    ]
                    t_clean = re.sub(r'"[^"]*"|\'[^\']*\'', "", tail)
                    if _CODE_DYN_RE.search(t_clean):
                        return True
                    if re.search(r"[(\[{'\"=]", t_clean):
                        for cm in re.finditer(
                            r"[\w.]+\s*\(((?:[^()]|\([^()]*\))*)\)",
                            tail,
                        ):
                            cwork = re.sub(
                                r'"[^"]*"|\'[^\']*\'', "",
                                cm.group(1),
                            )
                            if _arg_dirty(cwork, cwork.split(",")):
                                return True
                    else:
                        hn = re.match(r"([A-Za-z_]\w*)", tail.strip())
                        if hn:
                            hv = _lookup(hn.group(1))
                            if hv is None or _CODE_DYN_RE.search(
                                re.sub(
                                    r'"[^"]*"|\'[^\']*\'', "", hv
                                )
                            ):
                                return True
                            for hl in re.findall(
                                r'"[^"]*"|\'[^\']*\'', hv
                            ):
                                _check(hl.strip("\"'"))
                    for lit in t_lits:
                        _check(lit)
                    return False

                def _arg_dirty(work: str, check_args: list) -> bool:
                    """Non-literal argument in a target position → dirty."""
                    if _CODE_DYN_RE.search(work):
                        return True
                    for arg in check_args:
                        aval = arg.strip()
                        bound = None
                        if re.fullmatch(r"[A-Za-z_]\w*", aval):
                            bound = _lookup(aval)
                        if bound is not None:
                            # ``p=Path(env); Path(p).m()`` — substitute the
                            # tracked value for the bare-name argument.
                            aval = bound
                            if _CODE_DYN_RE.search(
                                re.sub(r'"[^"]*"|\'[^\']*\'', "", aval)
                            ):
                                return True
                            sub_lits = [
                                t.strip("\"'")
                                for t in re.findall(
                                    r'"[^"]*"|\'[^\']*\'', aval
                                )
                            ]
                            if sub_lits:
                                for lit in sub_lits:
                                    _check(lit)
                                continue
                            arg = aval
                            if re.fullmatch(
                                r"[^\s'\"|;>&(,)\[\]{}+*%/^~!-]+", arg
                            ):
                                # A plain tracked string value is a
                                # literal target — check it as a path.
                                _check(arg)
                                continue
                        stripped = re.sub(r"[-+]?\d[\d_]*", "", arg)
                        stripped = re.sub(r"\b\w+\s*=", "", stripped)
                        if re.search(r"[(\[{+*%/&|^~<>!-]|\w", stripped):
                            return True
                    return False

                for api in _CODE_TARGET_API_RE.finditer(seg):
                    seen_api = True
                    region = _code_arg_region(seg, api.end())
                    # Strip string literals (and their b/r/u prefixes —
                    # ``f`` stays, so f-strings still fail closed) before
                    # inspecting the argument expression: literal text such
                    # as ``'ok.pdf'`` is data, not computed code.
                    work = re.sub(r"(?i)(?<![\w])[bru]+(?=['\"])", "", region)
                    work = re.sub(r'"[^"]*"|\'[^\']*\'', "", work)
                    args = work.split(",")
                    if _arg_dirty(
                        work,
                        args[:2] if api.group(1).lower() in _TWO_TARGET_APIS else args[:1],
                    ):
                        dirty = True
                        break
                # ``Path(args).method()`` receiver args and the args of a
                # dispatched ``getattr(...)()/exec(...)()`` call are write
                # targets too — same literal-only rule.
                for recv in _CODE_RECV_RE.finditer(seg):
                    seen_api = True
                    # The receiver expression is a path producer — route
                    # it through ``_tail_dirty`` so ``Path('ok')/'x'``
                    # literals stay allowed while ``Path(env)`` fails.
                    rwork = re.sub(
                        r"(?i)(?<![\w])[bru]+(?=['\"])", "", recv.group(1)
                    )
                    if _tail_dirty(rwork):
                        dirty = True
                        break
                    # Producer chain: in ``Path(env).with_name('x').write_text``
                    # the matched head is ``with_name`` — the real target
                    # producer (``Path(env)``) sits upstream of the match.
                    tail = re.split(r"[;\n]", seg[: recv.start()])[-1]
                    tail = re.split(r"(?<![=!<>])=(?!=)", tail)[-1].strip()
                    if tail.endswith("."):
                        tail = tail[:-1].strip()
                    if tail and _tail_dirty(tail):
                        dirty = True
                        break
                for recv in _CODE_NAMERECV_RE.finditer(seg):
                    # ``p.unlink()`` — a bare-name receiver that mutates
                    # the path it holds; the name must resolve to a
                    # statically checkable value. Module heads like
                    # ``os.unlink`` are API calls, not receivers.
                    seen_api = True
                    name = recv.group(1)
                    head = name.split(".")[0].strip()
                    if head.lower() in _CODE_NAMERECV_HEADS:
                        continue
                    value = _lookup(head)
                    if value is None:
                        dirty = True
                        break
                    if _CODE_DYN_RE.search(
                        re.sub(r'"[^"]*"|\'[^\']*\'', "", value)
                    ):
                        dirty = True
                        break
                    n_lits = [
                        t.strip("\"'")
                        for t in re.findall(r'"[^"]*"|\'[^\']*\'', value)
                    ]
                    if not n_lits:
                        dirty = True
                        break
                    for lit in n_lits:
                        _check(lit)
                for precv in _CODE_PAREN_RECV_RE.finditer(seg):
                    # ``(expr).method()`` / ``arr[i].method()`` — the
                    # bracketed receiver expression is the write target.
                    seen_api = True
                    depth2 = 0
                    open_i = -1
                    for j in range(precv.start(), -1, -1):
                        if seg[j] in ")]":
                            depth2 += 1
                        elif seg[j] in "([":
                            depth2 -= 1
                            if depth2 == 0:
                                open_i = j
                                break
                    if open_i < 0:
                        dirty = True
                        break
                    inner = seg[open_i + 1 : precv.start()]
                    if inner.strip() and _tail_dirty(inner):
                        dirty = True
                        break
                    # The expression before the bracket decides the head —
                    # ``arr[i]`` needs ``arr`` resolved; ``f()`` needs ``f``
                    # bound (or a known path constructor).
                    phead = seg[:open_i].rstrip()
                    hm = re.search(r"([A-Za-z_]\w*(?:\.\w+)*)\s*$", phead)
                    if hm and phead[: hm.start()].rstrip().endswith("."):
                        # ``expr.attr(...)`` — the head is an attribute
                        # hanging off a preceding expression; judge that
                        # expression as the producer instead
                        # (``Path('ok').with_name('x')``).
                        ptail = phead[: hm.start()].rstrip()[:-1]
                        ptail = re.split(r"[;\n]", ptail)[-1]
                        ptail = re.split(
                            r"(?<![=!<>])=(?!=)", ptail
                        )[-1].strip()
                        if ptail and _tail_dirty(ptail):
                            dirty = True
                            break
                    elif hm:
                        hname = hm.group(1).lower()
                        hbase = hname.split(".")[0]
                        if (
                            hname not in _CODE_RECV_CTORS
                            and hbase not in _CODE_NAMERECV_HEADS
                        ):
                            hv = _lookup(hbase)
                            if hv is None or _CODE_DYN_RE.search(
                                re.sub(
                                    r'"[^"]*"|\'[^\']*\'', "", hv
                                )
                            ):
                                dirty = True
                                break
                for disp in _CODE_DISP_CALL_RE.finditer(seg):
                    # ``getattr(os,'remove')(target)`` — the dispatched
                    # call's argument region is the target.
                    region = _code_arg_region(seg, disp.end())
                    dwork = re.sub(
                        r"(?i)(?<![\w])[bru]+(?=['\"])", "", region
                    )
                    dwork_lits = re.findall(
                        r'"[^"]*"|\'[^\']*\'', dwork
                    )
                    dwork = re.sub(r'"[^"]*"|\'[^\']*\'', "", dwork)
                    if not dwork.strip() and not dwork_lits:
                        continue
                    seen_api = True
                    if _arg_dirty(dwork, dwork.split(",")):
                        dirty = True
                        break
                    for lit in dwork_lits:
                        _check(lit.strip("\"'"))
                for exc in _CODE_EXEC_RE.finditer(seg):
                    # ``exec(x)`` evaluates code — every argument must be a
                    # literal whose body carries no write API, dynamic
                    # source, or nested shell command.
                    region = _code_arg_region(seg, exc.end())
                    e_lits = [
                        t.strip("\"'")
                        for t in re.findall(
                            r'"[^"]*"|\'[^\']*\'', region
                        )
                    ]
                    ework = re.sub(
                        r'"[^"]*"|\'[^\']*\'', "", region
                    )
                    bad = bool(ework.strip())
                    if not bad:
                        for lit in e_lits:
                            if (
                                _CODE_MUT_RE.search(lit)
                                or _CODE_DYN_RE.search(lit)
                                or _MUT_VERB_WORDS_RE.search(lit)
                            ):
                                bad = True
                                break
                    if bad:
                        dirty = True
                        break
                    seen_api = True
                for cname, cvalue in code_vars.items():
                    # ``x = os.remove; x(t)`` — a name bound to a mutating
                    # callable keeps the literal-only argument rule.
                    nval = re.sub(r'"[^"]*"|\'[^\']*\'', "", cvalue)
                    if not _CODE_CALLABLE_REF_RE.search(nval.strip()):
                        continue
                    seen_api = True
                    for call in re.finditer(
                        r"(?<![\w.])" + re.escape(cname) + r"\s*\(", seg
                    ):
                        region = _code_arg_region(seg, call.end())
                        cw_lits = [
                            t.strip("\"'")
                            for t in re.findall(
                                r'"[^"]*"|\'[^\']*\'', region
                            )
                        ]
                        cwork = re.sub(
                            r'"[^"]*"|\'[^\']*\'', "", region
                        )
                        seen_api = True
                        if _arg_dirty(cwork, cwork.split(",")):
                            dirty = True
                            break
                        for lit in cw_lits:
                            if _MUT_VERB_WORDS_RE.search(lit) and (
                                _depth < _MAX_CARRIER_DEPTH
                            ) and find_bash_disallowed_write_paths(
                                lit,
                                config,
                                workdir=eff_dir,
                                _depth=_depth + 1,
                            ):
                                dirty = True
                                break
                            _check(lit)
                    if dirty:
                        break
                # The code itself lives inside a quoted literal — strip
                # the literals nested *inside* the code, not the code
                # string, before the no-API dynamic check.
                code_inner = re.sub(
                    r'"[^"]*"|\'[^\']*\'', "", " ".join(lit_texts)
                )
                if dirty or (not seen_api and (
                    not lit_texts or _CODE_DYN_RE.search(code_inner)
                )):
                    blocked.append(verb)
                    continue
            for text in lit_texts:
                # A literal holding a nested command string recurses —
                # but a literal that is itself interpreter code (``import
                # sqlite3``) is not a shell command.
                if re.match(
                    r"(?i)\s*(?:import|from|def|class|return|with|while|"
                    r"if|elif|else|try|except|finally|lambda|global|"
                    r"nonlocal|print|pass|raise|yield|assert|async|await|"
                    r"continue|break)\b",
                    text,
                ):
                    continue
                if text and _MUT_VERB_WORDS_RE.search(text) and (
                    _depth < _MAX_CARRIER_DEPTH
                ) and find_bash_disallowed_write_paths(
                    text, config, workdir=eff_dir, _depth=_depth + 1
                ):
                    blocked.append(verb)
            # Fall through: path tokens in the code get the generic check.
        cond = _COND_MUT_VERBS.get(verb)
        if cond:
            # Glued flag values (``-oFILE``/``-O..\x``) never become
            # separate tokens — the ``-`` token gets skipped as a flag —
            # so check whatever clings to the flag directly.
            for cm in re.finditer(cond, seg, re.IGNORECASE):
                gm = re.match(
                    r"([A-Za-z]:[\\/][^\s'\"|;>&]*"
                    r"|\.{1,2}[\\/][^\s'\"|;>&]*"
                    r"|[\\/][^\s'\"|;>&]+"
                    r"|[~$][^\s'\"|;>&]*)",
                    seg[cm.end() :],
                )
                if gm:
                    _check(gm.group(1))
        if cond and not re.search(cond, seg, re.IGNORECASE):
            # Read-only form — but the tail may still carry a real ``>``
            # (``curl url > /etc/x``) or a program literal that redirects
            # inside its own language (``awk '{print > "/etc/x"}'``).
            _rescan_tail(seg)
            for lit in re.finditer(r'"([^"]*)"|\'([^\']*)\'', seg):
                for gt in re.finditer(
                    r">{1,2}\s*[\"']?([^\s'\";|&}]+)",
                    lit.group(1) or lit.group(2) or "",
                ):
                    _check(gt.group(1))
            continue
        def _cmd_flag(tok: str, _verb: str = verb) -> bool:
            # ``/x`` is a cmd option only as a whole token — ``/opt/x`` or
            # ``/etc/x`` carry a second separator and stay POSIX targets.
            if _verb not in _CMD_VERBS or not tok.startswith("/"):
                return False
            if _verb == "sort":
                # Dual-dialect: only ``/o`` is a flag on sort.
                return tok.lower() == "/o"
            return bool(re.match(r"^/[A-Za-z][A-Za-z0-9+]*([:=].+)?$", tok))

        nonflag = [
            match
            for match in tokens
            if not match.group("t").startswith(("-", "+"))
            and not _cmd_flag(match.group("t"))
        ]
        if not nonflag:
            # A mutating verb with no verifiable target still mutates
            # (targets can arrive via stdin/xargs) — fail closed.
            blocked.append(verb)
            continue
        # ``-Path:X:\``/``--flag=X:\``/``-flag=/x`` — option-attached
        # targets: the path-token scan truncates at the ``:`` so the
        # drive path never becomes a token. Check the flag value
        # directly, but only when it carries a real path head —
        # ``-std=c++17``/``-f %E``/``PATH=...`` stay data.
        for fvm in re.finditer(
            r"(?i)-{1,2}[A-Za-z][\w-]*[:=]([^\s'\"|;>&=]*)"
            r"|(?<![\w-])(?:of|if|out|output|target|prefix|chdir|"
            r"destination|filepath|backup)[:=]([^\s'\"|;>&=]*)",
            seg,
        ):
            fval = fvm.group(1) or fvm.group(2) or ""
            if (
                re.match(r"[A-Za-z]:[\\/]", fval)
                or fval.startswith(("/", "\\", "~", "$"))
                or _DOTDOT_SEGMENT_RE.search(fval)
            ):
                _check(fval)
        if verb == "tar":
            # ``tar cfX:\x a`` — the ``f`` flag glues the archive path
            # with no separator at all.
            tgl = re.search(
                r"(?i)(?:^|\s)-?[ctx][a-z]*f([A-Za-z]:[\\/][^\s'\"|;>&]*|\.[^\s'\"|;>&]*"
                r"|[\\/][^\s'\"|;>&]+)",
                seg,
            )
            if tgl:
                _check(tgl.group(1))
        for match in tokens:
            raw = match.group("t").rstrip("\\/") or match.group("t")[:1]
            if _cmd_flag(raw):
                # ``/x`` is a cmd option — a ``/flag:value`` form can
                # still smuggle the target inside the flag itself.
                flagval = re.match(r"^/[A-Za-z][A-Za-z0-9+]*[:=](.+)$", raw)
                if flagval:
                    _check(flagval.group(1))
                continue
            if verb in ("icacls", "cacls") and re.match(r"^[A-Za-z]:$", raw) and re.match(
                r"[A-Za-z(]", seg[match.end() :].lstrip()[:1] or " "
            ):
                # ``u:F``/``u:(OI)(CI)F`` grant strings split into a
                # bare ``u:`` token and a perm-letter tail — not a drive.
                continue
            if re.match(r"^[A-Za-z]:$", raw) and re.search(
                r"\bas\s+$", seg[: match.start()]
            ):
                # ``with open(...) as f:`` — a binding colon in inline
                # interpreter code, not a drive root.
                continue
            if re.match(r"^[A-Za-z]:$", raw):
                raw += "\\"
            # Plain relative targets resolve inside the workspace; only
            # '..' traversal or absolute/env forms need the whitelist check.
            if (
                not _ABS_TOKEN_START_RE.match(raw)
                and not _DOTDOT_SEGMENT_RE.search(raw)
                and raw != "{}"
            ):
                # Flag-joined paths (``of=/dev/sda``) hide the target in a
                # value; check the right-hand side separately.
                rhs = raw.split("=", 1)[1] if "=" in raw else ""
                if _ABS_TOKEN_START_RE.match(rhs) or _DOTDOT_SEGMENT_RE.search(rhs):
                    _check(rhs)
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
