"""Deterministic policy for freshness-sensitive external facts."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class ResearchPolicy:
    requires_web: bool
    cache_read_allowed: bool
    cache_write_allowed: bool
    citations_required: bool


_FRESH_ZH = (
    "最新", "当前", "现在", "今天", "今日", "实时", "近期", "最近",
    "现价", "价格", "新闻", "状态", "版本", "发布", "更新",
)
_FRESH_EN = re.compile(
    r"\b(latest|current|currently|today|tonight|real[- ]?time|recent|recently|"
    r"price|pricing|news|status|version|release|updated?)\b",
    re.IGNORECASE,
)

# Explicit web intent is deliberately narrower than a bare ``search`` token so
# programming questions such as "implement binary search" do not get routed to
# the network.  Chinese phrases similarly require an online/web qualifier.
_EXPLICIT_WEB_ZH = (
    "联网搜索", "网络搜索", "网上搜索", "搜索网页", "搜索网络", "搜索互联网",
    "上网查", "联网查", "网上查", "查阅网页", "浏览网页", "浏览网站",
)
_EXPLICIT_WEB_EN = re.compile(
    r"^\s*(?:please\s+)?(?:browse|search|look\s+up)\b|"
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"(?:browse|search|look\s+up)\b|"
    r"\b(?:browse|search|check|verify|look\s+up)\s+"
    r"(?:the\s+)?(?:web|internet|online|github)\b|"
    r"\b(?:web|internet|online|github)\s+(?:search|lookup)\b",
    re.IGNORECASE,
)
_EXPLICIT_WEB_ZH_COMMAND = re.compile(
    r"^\s*(?:(?:请|帮我|麻烦)(?:你)?\s*)?(?:搜一下|搜索|查一下|查找|浏览)"
)

# These subjects can change without the wording containing "latest".  A
# deterministic policy is safer than relying on a model to remember when its
# own training data may be stale.
_VOLATILE_ZH = (
    "天气", "天气预报", "气温", "汇率", "兑换率", "外汇",
    "现任总统", "现任总理", "现任首相", "现任市长", "现任州长",
    "总统是谁", "总理是谁", "首相是谁", "首席执行官是谁", "CEO是谁",
    "法律", "法规", "监管规定", "合规要求", "签证要求", "税率",
)
_VOLATILE_EN = re.compile(
    r"\b(?:weather|weather\s+forecast|forecast|temperature|exchange\s+rate|"
    r"currency\s+rate|forex|laws|legislation|regulations?|statutes?|"
    r"legal\s+requirements?|visa\s+requirements?|tax\s+rates?)\b|"
    r"\b(?:who\s+(?:is|are)\s+(?:the\s+)?|incumbent\s+|sitting\s+)"
    r"(?:president|prime\s+minister|governor|mayor|ceo|chair(?:person|man|woman)?)\b|"
    r"\b(?:president|prime\s+minister|governor|mayor|ceo)\s+of\b",
    re.IGNORECASE,
)
_CURRENCY_PAIR_EN = re.compile(
    r"\b(?:USD|EUR|GBP|JPY|CNY|RMB|CAD|AUD|CHF|HKD|SGD|INR|KRW)\s*"
    r"(?:to|/)\s*"
    r"(?:USD|EUR|GBP|JPY|CNY|RMB|CAD|AUD|CHF|HKD|SGD|INR|KRW)\b",
    re.IGNORECASE,
)

_HTTP_URL = re.compile(r"https?://[^\s<>\[\]{}\"'`]+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"


def normalize_research_url(url: str) -> str | None:
    """Return a stable, public HTTP(S) URL or ``None`` for unsafe input."""
    candidate = str(url or "").strip().rstrip(_TRAILING_URL_PUNCTUATION)
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return None
    address = None
    try:
        address = ipaddress.ip_address(hostname)
        if not address.is_global:
            return None
    except ValueError:
        if "." not in hostname:
            return None

    try:
        port = parsed.port
    except ValueError:
        return None
    netloc = f"[{hostname}]" if address and address.version == 6 else hostname
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    return urlunsplit((
        parsed.scheme.lower(),
        netloc,
        parsed.path or "",
        parsed.query,
        "",
    ))


def extract_research_urls(text: str) -> list[str]:
    """Extract unique public HTTP(S) URLs in their first-seen order."""
    urls: list[str] = []
    for match in _HTTP_URL.findall(str(text or "")):
        normalized = normalize_research_url(match)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls


def is_successful_research_fetch(result: str) -> bool:
    """Reject empty, blocked, cancelled, timed-out, or tool-error fetches."""
    text = str(result or "").strip()
    if not text:
        return False
    lowered = text.lower()
    failure_prefixes = (
        "[error", "[search error", "[blocked", "[rejected", "[cancelled",
        "[timeout", "[timed out", "[tool", "[approval", "download failed",
        "error fetching",
    )
    return lowered not in {"none", "null"} and not lowered.startswith(failure_prefixes)


def get_research_policy(query: str) -> ResearchPolicy:
    text = query.strip()
    requires_web = (
        any(term in text for term in _FRESH_ZH)
        or bool(_FRESH_EN.search(text))
        or any(term in text for term in _EXPLICIT_WEB_ZH)
        or bool(_EXPLICIT_WEB_ZH_COMMAND.search(text))
        or bool(_EXPLICIT_WEB_EN.search(text))
        or any(term in text for term in _VOLATILE_ZH)
        or bool(_VOLATILE_EN.search(text))
        or bool(_CURRENCY_PAIR_EN.search(text))
    )
    return ResearchPolicy(
        requires_web=requires_web,
        cache_read_allowed=not requires_web,
        cache_write_allowed=not requires_web,
        citations_required=requires_web,
    )


def research_failure_message(detail: str = "") -> str:
    suffix = f" Detail: {detail[:300]}" if detail else ""
    return (
        "I could not verify the requested current information from external sources, "
        "so I will not guess or present stale knowledge as current." + suffix
    )


# Instruction prefixes / boilerplate that should not be sent to a search engine.
# They describe the *task*, not the *topic* being searched.
_ZH_TASK_PREFIXES = (
    "使用网页搜索（websearch 工具）",
    "使用网页搜索(websearch 工具)",
    "使用网页搜索工具",
    "使用 websearch 工具",
    "使用网页搜索",
    "用网页搜索",
    "联网搜索",
    "网络搜索",
    "网上搜索",
    "搜索网页",
    "搜索网络",
    "搜索互联网",
    "上网查",
    "联网查",
    "网上查",
    "请你搜索",
    "请搜索",
    "帮我搜索",
    "搜索一下",
    "查一下",
    "查找",
    "浏览网页",
    "浏览网站",
    "帮我查",
    "请查",
)
_ZH_TASK_SUFFIXES = (
    "的内容",
    "的相关信息",
    "的信息",
    "的资料",
    "最新情况",
    "最新动态",
    "现状",
)


def extract_research_query(user_input: str) -> str:
    """Derive a concise search query from free-form task language.

    The deterministic research path must not hand the whole instruction to a
    search engine ("使用网页搜索（websearch 工具）搜索成都三日游攻略，整理一份…")
    — engines return junk for such prompts.  Strip task-direction boilerplate and
    take the first searchable phrase instead.  When the input carries no
    task-direction boilerplate it is already a usable query and is returned
    unchanged.
    """
    text = str(user_input or "").strip()
    if not text:
        return ""

    # 1. Strip known task-direction prefixes first so "使用网页搜索（websearch
    #    工具）搜索成都三日游攻略…" becomes "搜索成都三日游攻略…" instead of
    #    splitting inside the compound verb "网页搜索".
    candidate = text
    prefix_stripped = False
    for prefix in _ZH_TASK_PREFIXES:
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):].lstrip("（( ：:，,。")
            prefix_stripped = True
            break

    # 2. Take the clause after an explicit search verb.
    lowered = candidate.lower()
    for marker in ("搜索", "search", "查一下", "查找", "浏览"):
        idx = lowered.find(marker)
        if idx == -1:
            continue
        after = candidate[idx + len(marker):].lstrip("（( ：:，,。")
        # Drop leading filler words.
        for filler in ("一下", "最新", "的", "有关", "关于"):
            if after.startswith(filler):
                after = after[len(filler):].lstrip()
                break
        if after:
            # Stop at sentence punctuation or imperative filler that signals
            # the topic ended.
            stop = re.search(
                r"[\n，,。；;！!？?：:]|，然后|然后|并|并写入|写入|总结|整理|列出|"
                r"介绍|是啥|是什么|然后写|并写|写出",
                after,
            )
            if stop:
                after = after[: stop.start()].rstrip("（( ")
            after = after.strip().strip("，,。")
            if after and len(after) <= 120:
                return after

    # 3. No explicit verb.  If we stripped a task-direction prefix, trim
    #    suffixes and command-direction filler; otherwise the input is already
    #    a searchable query and we leave it untouched (preserving punctuation
    #    such as the trailing "？" on "今天最新 Python 版本是什么？").
    if not prefix_stripped:
        return text
    for suffix in _ZH_TASK_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)].rstrip()
            break
    if len(candidate) > 120:
        candidate = candidate[:120].rsplit("，", 1)[0]
    fallback_stop = re.search(
        r"[\n。；;！!？?]|，然后|然后|，并|并写入|，整理|，总结|，列出|，介绍",
        candidate,
    )
    if fallback_stop:
        candidate = candidate[: fallback_stop.start()].rstrip("，, ")
    return candidate.strip() or text
