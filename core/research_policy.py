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
