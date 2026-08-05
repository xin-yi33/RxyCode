"""Deterministic request routing for AgentV2 (P6).

Replaces scattered keyword lists inside ``agent_v2.py`` with a single,
testable module.  Priority order (per 00-EXECUTION-PLAN.md P6):

1. Explicit user directives (``/full``, ``/fast``, ``/pipeline``)
2. Structured signals (paths, URLs, mode flags)
3. Conservative keyword heuristics (legacy, narrow lists)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Tool allowlists used by fast-reply routing
# ---------------------------------------------------------------------------

SOCIAL_CHAT_TOOL_NAMES = frozenset({"datetime"})
GIT_ONLY_TOOL_NAMES = frozenset({"git", "read", "ls", "grep", "glob"})
GIT_FORCE_RE = re.compile(
    r"必须调用\s*git|只能使用\s*git|only\s+(?:use\s+)?git\s+tool|git\s+工具.*operation",
    re.IGNORECASE,
)
SOCIAL_CHAT_ROLE_INSTRUCTION = (
    "This is social or emotional chat. Respond warmly in dialogue. "
    "Do not create markdown files, write code to disk, or run shell commands "
    "unless the user explicitly asks for a file or runnable artifact. "
    "If they mention errors from a prior turn, acknowledge and comfort them "
    "instead of launching tools or a build pipeline. "
    "Do NOT dump prior coding tasks, games, parkour, or large code blocks "
    "unless the user explicitly asks to continue that work. "
    "For short greetings (e.g. 你好 / hello), reply with a brief friendly "
    "greeting only — no code, no file contents, no prior-task recap."
)
PURE_SOCIAL_GREETING_RE = re.compile(
    r"^(?:你好|您好|hello|hi|hey|在吗|谢谢|thank you|thanks)"
    r"(?:[!！。.\s]*)$",
    re.IGNORECASE,
)

# Relative path token (calc.py, src/foo.py) — not Windows drive-letter paths.
_RELATIVE_FILE_RE = re.compile(
    r"\b(?:[\w.-]+/)*[\w.-]+\.(?:py|pyw|js|ts|tsx|jsx|go|rs|java|cpp|c|h|hpp|"
    r"md|json|yaml|yml|toml|ini|cfg|txt|sh|bat|ps1)\b",
    re.IGNORECASE,
)
_MODIFY_INTENT_RE = re.compile(
    r"(?:\b(fix|debug|patch|repair|modify|edit|bug)\b|修复|修改|调试)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Explicit routing directives (highest priority)
# ---------------------------------------------------------------------------


class RoutingDirective(Enum):
  AUTO = "auto"
  FORCE_FAST = "fast"
  FORCE_FULL = "full"


_DIRECTIVE_RE = re.compile(
    r"^\s*/(?P<cmd>full|fast|pipeline)\b(?:\s+|$)",
    re.IGNORECASE,
)


def parse_routing_directive(text: str) -> tuple[RoutingDirective, str]:
    """Return directive and user text with the leading slash command removed."""
    match = _DIRECTIVE_RE.match(text or "")
    if not match:
        return RoutingDirective.AUTO, text
    cmd = match.group("cmd").lower()
    if cmd in {"full", "pipeline"}:
        directive = RoutingDirective.FORCE_FULL
    else:
        directive = RoutingDirective.FORCE_FAST
    stripped = (text[match.end():] if match.end() <= len(text) else "").lstrip()
    return directive, stripped or text.strip()


# ---------------------------------------------------------------------------
# Inventory (P6 documentation — 25 legacy keyword routing sites)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingSite:
    id: str
    location: str
    triggers: str
    decides: str
    misroute_risk: str


ROUTING_INVENTORY: tuple[RoutingSite, ...] = (
    RoutingSite("R01", "request_routing.GIT_FORCE_RE", "git-only phrases", "Fast-reply tool allowlist", "Low"),
    RoutingSite("R02", "request_routing.PURE_SOCIAL_GREETING_RE", "hello/你好", "Social role hint", "Low"),
    RoutingSite("R03", "has_creation_product_intent", "写+游戏/ build+app", "Social vs code disambiguation", "High"),
    RoutingSite("R04", "is_social_chat", "emotion/play-game phrases", "Skip LangGraph", "Medium"),
    RoutingSite("R05", "is_simple_query.en_patterns", "build full/entire, multi-step", "Full pipeline", "High"),
    RoutingSite("R06", "is_simple_query.zh_always_complex", "分步/逐步", "Full pipeline", "Medium"),
    RoutingSite("R07", "is_simple_query.zh_action+scope", "重构+整个", "Full pipeline", "High"),
    RoutingSite("R08", "is_simple_query.length", ">500 chars", "Full pipeline", "Low"),
    RoutingSite("R09", "is_simple_query.zh_code_intent", "游戏/代码/脚本", "Tool pipeline", "High"),
    RoutingSite("R10", "is_simple_query.en_code_intent", r"\\b(game|app|code)\\b", "Tool pipeline", "High"),
    RoutingSite("R11", "is_simple_query.zh_file_ops", "读文件/写文件", "Tool pipeline", "Medium"),
    RoutingSite("R12", "is_simple_query.en_file_ops", "read file", "Tool pipeline", "Medium"),
    RoutingSite("R13", "detect_download_intent.url", "http(s) file URL", "Download tool path", "Low"),
    RoutingSite("R14", "detect_download_intent.download_url", "下载+URL", "Download tool path", "Low"),
    RoutingSite("R15", "detect_download_intent.package", "npx/pip package", "MCP/skill download", "Medium"),
    RoutingSite("R16", "detect_download_intent.skill_patterns", "install skill X", "download_skill", "Medium"),
    RoutingSite("R17", "detect_download_intent.mcp_patterns", "install mcp X", "download_mcp", "Medium"),
    RoutingSite("R18", "detect_file_operation.code_gen_skip", "game/code keywords", "Skip direct file op", "Medium"),
    RoutingSite("R19", "detect_file_operation.list_kw", "list+path", "Direct ls", "Low"),
    RoutingSite("R20", "detect_file_operation.read_kw", "read+cat+path", "Direct read", "Low"),
    RoutingSite("R21", "detect_file_operation.write_patterns", "create file path", "Direct write", "Medium"),
    RoutingSite("R22", "should_use_subagents", "并行/同时/batch", "parallel_requested flag", "Low"),
    RoutingSite("R23", "agent_v2._run_impl mode", "plan/compose/build", "Top-level path", "High"),
    RoutingSite("R24", "agent_v2._run_compose build phase", "is_simple_query(user_input)", "Compose build path", "High"),
    RoutingSite("R25", "parse_routing_directive", "/full /fast /pipeline", "Explicit override (P6)", "Mitigation"),
)


def has_creation_product_intent(text: str) -> bool:
    """True when the user asks to create/build a product (game, app, …)."""
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    zh_create = (
        "写一个", "写个", "编写", "实现", "开发", "创建", "做个", "做一个",
        "帮我写", "生成一个", "生成个",
    )
    zh_products = (
        "游戏", "代码", "脚本", "程序", "项目", "网站", "爬虫", "机器人", "算法",
    )
    if any(c in text_stripped for c in zh_create) and any(
        p in text_stripped for p in zh_products
    ):
        return True
    if re.search(
        r"\b(build|create|implement|write|make)\b.*\b(game|app|website|code|script|bot)\b",
        text_lower,
    ):
        return True
    return False


def is_social_chat(text: str) -> bool:
    """Narrow emotional/social chat that must not enter LangGraph."""
    text_stripped = text.strip()
    if not text_stripped or len(text_stripped) > 300:
        return False
    text_lower = text_stripped.lower()
    if re.search(r"https?://", text_stripped):
        return False
    if re.search(r"[A-Za-z]:\\|/home/|~/", text_stripped):
        return False
    if has_creation_product_intent(text_stripped):
        return False

    social_signals = (
        "伤心", "难过", "不理我", "陪我", "你好", "您好", "谢谢", "在吗",
        "倾诉", "安慰", "孤独", "郁闷", "好伤心", "很难过",
        "你却说", "你却报", "怎么又报错", "你说 error", "你说error",
        "how are you", "i'm sad", "im sad", "i am sad", "feel sad",
        "lonely", "upset", "you said error",
    )
    has_social = any(s in text_stripped for s in social_signals) or any(
        s in text_lower for s in social_signals if s.isascii()
    )
    play_game = any(
        p in text_stripped
        for p in ("玩游戏", "陪我玩", "找我玩", "找朋友玩", "一起玩")
    )
    if play_game and not has_creation_product_intent(text_stripped):
        return True
    if has_social and not has_creation_product_intent(text_stripped):
        return True
    return False


def resolve_fast_reply_tool_allowlist(
    user_input: str,
    allowed_tool_names: frozenset[str] | None,
) -> frozenset[str] | None:
    """Return tool allowlist for fast-reply (E6 social whitelist)."""
    if allowed_tool_names is not None:
        return allowed_tool_names
    if is_social_chat(user_input):
        return SOCIAL_CHAT_TOOL_NAMES
    if GIT_FORCE_RE.search(user_input):
        return GIT_ONLY_TOOL_NAMES
    return None


def is_simple_query(
    text: str,
    *,
    directive: RoutingDirective = RoutingDirective.AUTO,
) -> bool:
    """True when the request can use the tool-aware fast-reply path."""
    if directive == RoutingDirective.FORCE_FAST:
        return True
    if directive == RoutingDirective.FORCE_FULL:
        return False

    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    if has_structured_pipeline_signal(text_stripped):
        return False

    en_patterns = [
        r"\b(build|create|implement)\b.*\b(full|complete|entire|whole)\b",
        r"\b(step[- ]by[- ]step|multi[- ]step|phase\d)\b",
        r"\b(refactor|rewrite|migrate)\b.*\b(entire|whole|all|codebase|project)\b",
        r"\b(set up|setup|scaffold)\b.*\b(project|app|application|framework)\b",
        r"\bci/cd\b",
    ]
    for pat in en_patterns:
        if re.search(pat, text_lower):
            return False

    zh_always_complex = ["分步", "分阶段", "逐步", "分层"]
    if any(k in text_stripped for k in zh_always_complex):
        return False

    zh_actions = ["重构", "重写", "迁移", "搭建", "初始化", "创建", "实现", "开发"]
    zh_scopes = ["整个", "全部", "所有", "完整", "全面", "系统", "从零", "新项目", "整个项目"]
    if any(k in text_stripped for k in zh_actions) and any(
        k in text_stripped for k in zh_scopes
    ):
        return False

    if len(text_stripped) > 500:
        return False

    if is_social_chat(text_stripped):
        return True

    zh_code_intent = ["游戏", "代码", "脚本", "程序", "项目", "网站", "爬虫", "机器人", "算法"]
    en_code_intent = [r"\b(game|app|website|code|script|bot|crawler|algorithm)\b"]
    if any(k in text_stripped for k in zh_code_intent) or any(
        re.search(p, text_lower) for p in en_code_intent
    ):
        return False

    zh_file_ops = [
        "读取文件", "读文件", "打开文件", "编辑文件", "写入文件", "写文件",
        "创建文件", "删除文件", "查看文件", "修改文件",
    ]
    en_file_ops = [r"\b(read|open|edit|write|create|delete|view)\s+file\b"]
    if any(k in text_stripped for k in zh_file_ops) or any(
        re.search(p, text_lower) for p in en_file_ops
    ):
        return False

    return True


def should_use_subagents(user_input: str) -> bool:
    """True when the graph should mark parallel_requested."""
    text_lower = user_input.lower()
    multi_task_patterns = [
        r"同时|并行|一起|分别|各自",
        r"at the same time|in parallel|simultaneously",
        r"多个|多个文件|多个任务",
        r"批量|batch",
    ]
    return any(re.search(pattern, text_lower) for pattern in multi_task_patterns)


def detect_download_intent(text: str) -> tuple[str, str, str] | None:
    """Return (type, name, package) for skill/mcp/file downloads."""
    text_lower = text.lower().strip()

    url_pattern = (
        r"(https?://[^\s]+\.(?:zip|tar|gz|pdf|doc|docx|xls|xlsx|ppt|pptx|txt|md|"
        r"json|xml|csv|jpg|jpeg|png|gif|mp3|mp4|exe|msi|dmg|deb|rpm|apk|ipa))"
    )
    url_match = re.search(url_pattern, text, re.IGNORECASE)
    if url_match:
        return ("file", url_match.group(1), "")

    download_url_patterns = [
        r"(?:下载|download)\s*(?:这个|这个文件|文件)?\s*(https?://[^\s]+)",
        r"(?:从|from)\s*(https?://[^\s]+)\s*(?:下载|download)",
        r"(?:帮我|please)\s*(?:下载|download)\s*(https?://[^\s]+)",
    ]
    for pattern in download_url_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return ("file", match.group(1), "")

    if "下载" in text or "download" in text_lower:
        url_match2 = re.search(r"(https?://[^\s]+)", text)
        if url_match2:
            return ("file", url_match2.group(1), "")

    match = re.search(r"(npx|pip)\s+(-y\s+)?([@\w/.-]+)", text)
    if match:
        package = match.group(3)
        name = package.split("/")[-1].replace("@", "")
        if "skill" in text_lower:
            return ("skill", name, package)
        return ("mcp", name, package)

    skill_patterns = [
        r"(?:下载|安装|添加|获取|load|install|download|add)\s*(?:一个|the)?\s*(?:skill|插件)\s*(?:叫|名为|叫作|叫做|named|called)?\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*",
        r"(?:我要|我想|请|帮我|please)\s*(?:下载|安装|添加|获取|load|install|download|add)\s*(?:一个|the)?\s*(?:skill|插件)\s*(?:叫|名为|叫作|叫做|named|called)?\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*",
        r"(?:下载|安装|添加|获取|load|install|download|add)\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*\s*(?:这个|个)?\s*(?:skill|插件)",
        r"(?:我要|我想|请|帮我|please)\s*(?:下载|安装|添加|获取|load|install|download|add)\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*\s*(?:这个|个)?\s*(?:skill|插件)",
        r"(?:find-skill|/find-skill|/addskill)\s+([a-zA-Z0-9_-]+)",
        r"(?:skill|插件)\s*(?:叫|名为|叫作|叫做|named|called)?\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*",
    ]
    for pattern in skill_patterns:
        match = re.search(pattern, text_lower)
        if match:
            name = match.group(1).strip()
            if name and len(name) > 1:
                return ("skill", name, "")

    mcp_patterns = [
        r"(?:下载|安装|添加|获取|load|install|download|add)\s*(?:一个|the)?\s*(?:mcp|mcp服务器|mcp server)\s*(?:叫|名为|叫作|叫做|named|called)?\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*",
        r"(?:我要|我想|请|帮我|please)\s*(?:下载|安装|添加|获取|load|install|download|add)\s*(?:一个|the)?\s*(?:mcp|mcp服务器|mcp server)\s*(?:叫|名为|叫作|叫做|named|called)?\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*",
        r"(?:mcp|mcp服务器|mcp server)\s*(?:叫|名为|叫作|叫做|named|called)?\s*[`\"']*([a-zA-Z0-9_-]+)[`\"']*",
    ]
    for pattern in mcp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            name = match.group(1).strip()
            if name and len(name) > 1:
                return ("mcp", name, "")

    return None


def detect_file_operation(text: str) -> dict | None:
    """Detect direct read/write/list operations with an absolute path."""
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    code_gen_indicators = [
        "game", "function", "class", "script", "html", "js", "python", "program",
        "code", "implement", "build", "generate", "write a", "create a", "write me",
        "写一个", "创建一个", "小游戏", "代码", "函数", "脚本", "程序",
    ]
    if any(ind in text_lower for ind in code_gen_indicators):
        return None

    path_match = re.search(r"[A-Za-z]:[\\\/][^\s]+", text_stripped)
    detected_path = path_match.group(0) if path_match else None

    list_kw = ["list", "ls", "列出", "显示文件", "查看文件"]
    if any(k in text_lower for k in list_kw) and detected_path:
        return {"op": "list", "path": detected_path}

    read_kw = ["read ", "cat ", "读取", "查看文件"]
    if any(k in text_lower for k in read_kw) and detected_path:
        return {"op": "read", "path": detected_path}

    write_patterns = [
        r"(?:创建|写入|新建|create|write)\s*(?:一个|a)?\s*(?:文件|file)\s*[：:\s]*([^\s]+)\s*(?:内容|content|with)?\s*[：:\s]*(.*)",
        r"(?:保存|save)\s*(?:到|to)\s*([^\s]+)\s*(?:内容|content)?\s*[：:\s]*(.*)",
    ]
    for pattern in write_patterns:
        match = re.search(pattern, text_stripped, re.IGNORECASE | re.DOTALL)
        if match:
            fpath = match.group(1).strip()
            content_val = match.group(2).strip() if match.group(2) else ""
            if ("\\" in fpath or "/" in fpath or "." in fpath) and len(fpath) < 500:
                return {"op": "write", "path": fpath, "content": content_val}

    return None


def _mentions_relative_file(text: str) -> bool:
    """True when text names a relative file path (not a drive-letter absolute path)."""
    for match in _RELATIVE_FILE_RE.finditer(text):
        start = match.start()
        if start >= 2 and text[start - 1] == ":" and text[start - 2].isalpha():
            continue
        prefix = text[max(0, start - 12):start].lower()
        if "://" in prefix or prefix.endswith("http") or prefix.endswith("https"):
            continue
        return True
    return False


def has_structured_pipeline_signal(text: str) -> bool:
    """Structured signals that require the full tool/LangGraph pipeline."""
    stripped = text.strip()
    if not stripped:
        return False
    if re.search(r"https?://", stripped):
        return True
    if re.search(r"[A-Za-z]:[\\\/][^\s]+", stripped):
        return True
    if has_creation_product_intent(stripped):
        return True
    if _mentions_relative_file(stripped) and _MODIFY_INTENT_RE.search(stripped):
        return True
    return False
