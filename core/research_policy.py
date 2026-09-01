"""Deterministic policy for freshness-sensitive external facts."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from RxyCode.RxyCode1_1_0.log.log_helpers import redact_sensitive


@dataclass(frozen=True)
class ResearchPolicy:
    requires_web: bool
    cache_read_allowed: bool
    cache_write_allowed: bool
    citations_required: bool


_FRESH_ZH = (
    "最新", "当前", "现在", "今天", "今日", "实时", "近期", "最近",
    "现价", "价格", "新闻",
)
_FRESH_EN = re.compile(
    r"\b(latest|current|currently|today|tonight|real[- ]?time|recent|recently|"
    r"price|pricing|news)\b",
    re.IGNORECASE,
)

# ``status``, ``version``, ``release`` and ``updated`` are common local
# delivery words.  A task that asks the agent to build an offline artifact and
# report its runtime status must not be sent to the web path just because one
# of those words occurs in the acceptance checklist.  External freshness is
# still detected by explicit ``current/latest/today`` wording, price/news
# subjects, volatile domains, or explicit web intent below.
_FRESH_RELEASE_EN = re.compile(
    r"\b(?:status|version|release|updated?)\b[^.\n]{0,80}\b"
    r"(?:of|for|from|about|available|released|published)\b",
    re.IGNORECASE,
)

# Explicit web intent is deliberately narrower than a bare ``search`` token so
# programming questions such as "implement binary search" do not get routed to
# the network.  Chinese phrases similarly require an online/web qualifier.
_EXPLICIT_WEB_ZH = (
    "联网搜索", "网络搜索", "网上搜索", "搜索网页", "搜索网络", "搜索互联网",
    "上网查", "联网查", "网上查", "查阅网页", "浏览网页", "浏览网站",
    "使用 websearch", "用 websearch", "调用 websearch", "websearch 工具",
    "使用 webfetch", "调用 webfetch", "webfetch 工具",
)
_EXPLICIT_WEB_EN = re.compile(
    r"^\s*(?:please\s+)?(?:browse|search|look\s+up)\b|"
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"(?:browse|search|look\s+up)\b|"
    r"\b(?:browse|search|check|verify|look\s+up)\s+"
    r"(?:the\s+)?(?:web|internet|online|github)\b|"
    r"\b(?:web|internet|online|github)\s+(?:search|lookup)\b|"
    r"\b(?:call|use|invoke)\s+(?:the\s+)?(?:websearch|webfetch)\b|"
    r"\bwebsearch\s+and\s+webfetch\b",
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

# A request that names a local workspace *and* directs the agent to use local
# inspection tools is not a freshness/research request.  In particular, the
# word "current" in "current workspace" must not trigger _FRESH_EN: doing so
# used to send a Desktop code audit through the synchronous web-search path.
_LOCAL_WORKSPACE_EN = re.compile(
    r"\b(?:current|local)\s+(?:workspace|worktree|repository|repo|codebase|"
    r"project|directory|folder)\b",
    re.IGNORECASE,
)
_LOCAL_WORKSPACE_ZH = (
    "当前工作区", "本地工作区", "当前工作目录", "当前目录", "本地目录",
    "工作目录", "项目目录", "代码库", "仓库目录", "仓库",
)
_NON_WEB_CURRENT_ZH = (
    "当前时间", "当前日期", "今天日期", "现在时间", "现在几点", "当前时刻",
    "当前工作区", "本地工作区", "当前工作目录", "当前目录", "本地目录",
    "当前项目", "本地项目", "工作目录",
    # Local application state is not a request for an externally verified
    # current fact.  Without these bounded phrases, a game prompt such as
    # "检查当前范围" leaves the bare word "当前" behind and is routed into
    # the synchronous web-research path before local tools can run.
    "当前范围", "当前状态", "当前环境", "当前任务", "当前窗口", "当前输出",
)
_NON_WEB_CURRENT_EN = re.compile(
    r"\b(?:current|local)\s+(?:time|date|workspace|worktree|repository|repo|"
    r"codebase|project|directory|folder|range|state|environment|task|"
    r"window|output|score|level|attempts?)\b",
    re.IGNORECASE,
)
_LOCAL_TOOL_CALL = re.compile(
    r"\b(?:glob|grep|read|ls|cat|open)\b|调用\s*(?:glob|grep|read|ls|cat|open)",
    re.IGNORECASE,
)
# A bounded local inspection workflow often has a release/compatibility word
# in its requested answer.  When it explicitly prohibits network tools, that
# constraint must win over keyword freshness detection; otherwise a Desktop
# audit is diverted to websearch before it can run its requested glob/grep/read
# sequence.  This does not apply to a bare "do not use web" factual question:
# a local inspection tool must also be named.
_NEGATED_WEB_TOOL_CONSTRAINT = re.compile(
    r"\b(?:do\s+not|don't|never)\s+"
    r"(?:call|use|run|execute|invoke|browse|search)\b[^.\n]*\b"
    r"(?:websearch|web|internet|online)\b",
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
    local_workspace_task = (
        bool(_LOCAL_WORKSPACE_EN.search(text))
        or any(term in text for term in _LOCAL_WORKSPACE_ZH)
    ) and bool(_LOCAL_TOOL_CALL.search(text))
    constrained_local_inspection = bool(_LOCAL_TOOL_CALL.search(text)) and bool(
        _NEGATED_WEB_TOOL_CONSTRAINT.search(text)
    )
    explicit_no_web = bool(_NEGATED_WEB_TOOL_CONSTRAINT.search(text))
    explicit_web_request = (
        not explicit_no_web
        and (
            any(term in text for term in _EXPLICIT_WEB_ZH)
            or bool(_EXPLICIT_WEB_ZH_COMMAND.search(text))
            or bool(_EXPLICIT_WEB_EN.search(text))
        )
    )
    # Explicit websearch/webfetch instructions must win over generic local
    # acceptance boilerplate such as "current workspace", "open the page",
    # or "read the generated files". The old ordering silently removed the
    # network tools from real research builds before the fast path started.
    if (
        (local_workspace_task and not explicit_web_request)
        or (constrained_local_inspection and not explicit_web_request)
        or (explicit_no_web and not explicit_web_request)
        or (is_local_workspace_file_task(text) and not explicit_web_request)
    ):
        return ResearchPolicy(
            requires_web=False,
            cache_read_allowed=True,
            cache_write_allowed=True,
            citations_required=False,
        )

    # "当前工作区/当前时间" are local inspection instructions, not requests
    # for externally verified facts. Remove only those bounded phrases before
    # applying freshness detection, so "current price" and "current release"
    # still require web research.
    freshness_text = text
    for term in _NON_WEB_CURRENT_ZH:
        freshness_text = freshness_text.replace(term, " ")
    freshness_text = _NON_WEB_CURRENT_EN.sub(" ", freshness_text)
    requires_web = (
        any(term in freshness_text for term in _FRESH_ZH)
        or bool(_FRESH_EN.search(freshness_text))
        or bool(_FRESH_RELEASE_EN.search(freshness_text))
        or explicit_web_request
        or any(term in freshness_text for term in _VOLATILE_ZH)
        or bool(_VOLATILE_EN.search(freshness_text))
        or bool(_CURRENCY_PAIR_EN.search(text))
    )
    return ResearchPolicy(
        requires_web=requires_web,
        cache_read_allowed=not requires_web,
        cache_write_allowed=not requires_web,
        citations_required=requires_web,
    )


def research_failure_message(detail: str = "") -> str:
    safe = redact_sensitive(detail)[:300] if detail else ""
    suffix = f" Detail: {safe}" if safe else ""
    return (
        "I could not verify the requested current information from external sources, "
        "so I will not guess or present stale knowledge as current." + suffix
    )


def research_prefetch_failure_note(detail: str = "") -> str:
    safe = redact_sensitive(detail)[:300] if detail else ""
    suffix = f" Detail: {safe}" if safe else ""
    return (
        "External research prefetch failed. Do not invent live facts or cite "
        "unverified URLs. Record the unavailable research honestly, then continue "
        "the requested local artifact with write/edit tools." + suffix
    )


_LOCAL_FILE_TASK_ZH = (
    "当前工作目录", "当前目录", "本地目录", "工作目录", "仓库目录",
)
_LOCAL_FILE_VERBS_ZH = (
    "新建", "修复", "修改", "创建", "实现", "请修复", "写入", "创建/修改",
)
_LOCAL_FILE_VERBS_EN = re.compile(
    r"\b(fix|create|implement|write|edit|repair)\b",
    re.IGNORECASE,
)


def is_local_workspace_file_task(text: str) -> bool:
    """True when the user asks to create/fix files in the local workdir."""
    local = any(term in text for term in _LOCAL_FILE_TASK_ZH) or bool(
        _LOCAL_WORKSPACE_EN.search(text)
    )
    if not local:
        return False
    has_file = ".py" in text.lower() or "文件" in text or bool(
        re.search(r"\.[A-Za-z0-9]{1,5}\b", text)
    )
    has_verb = any(verb in text for verb in _LOCAL_FILE_VERBS_ZH) or bool(
        _LOCAL_FILE_VERBS_EN.search(text)
    )
    return has_file and has_verb


def should_abort_on_research_prefetch_failure(user_input: str) -> bool:
    """Pure Q&A must not guess. A create/build or local file task must still write files."""
    from RxyCode.RxyCode1_1_0.core.request_routing import has_creation_product_intent
    if has_creation_product_intent(user_input):
        return False
    if is_local_workspace_file_task(user_input):
        return False
    return True


def _is_usable_research_query(query: str) -> bool:
    text = str(query or "").strip()
    if len(text) < 8:
        return False
    if text[:1] in {"/", "\\"}:
        return False
    return True


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


_EN_RESEARCH_TOPIC_TERMS = re.compile(
    r"\b(?:travel|trip|tour|budget|transport|lodging|hotel|ticket|styling|"
    r"website|company|dashboard|market|gold|silver|nasdaq|stock|index|"
    r"vehicle|car|rental|rent|commute|coffee|inventory|order|spring|mysql|"
    r"price|pricing|cost|investment|suzhou|hangzhou|guangzhou)\b",
    re.IGNORECASE,
)
_EN_STRONG_RESEARCH_TERMS = re.compile(
    r"\b(?:gold|silver|nasdaq|s&p|spx|star\s*50|suzhou|hangzhou|"
    r"zhujiang|tco|vehicle|rental)\b",
    re.IGNORECASE,
)
_EN_UI_REQUIREMENT = re.compile(
    r"\b(?:the page must|must provide|date filter|asset filter|"
    r"metric switcher|tooltips?|detail table)\b",
    re.IGNORECASE,
)
_EN_RESEARCH_TOOL_WORDS = re.compile(
    r"\b(?:websearch|webfetch|datetime|bash|powershell|python|node|npm|"
    r"read|write|edit|open|browser|workspace|directory|folder|README|"
    r"test-report)\b",
    re.IGNORECASE,
)


def _english_research_topic(text: str) -> str:
    """Choose a topic sentence without treating tool names as search terms."""
    sentences = [
        part.strip(" \t\r\n-:;,.!?()[]{}")
        for part in re.split(r"(?:\r?\n+|(?<=[.!?])\s+)", text)
        if part.strip()
    ]
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        if len(sentence) < 12:
            continue
        topic_hits = len(_EN_RESEARCH_TOPIC_TERMS.findall(sentence))
        tool_hits = len(_EN_RESEARCH_TOOL_WORDS.findall(sentence))
        if topic_hits == 0:
            continue
        score = topic_hits * 10 - tool_hits * 4
        score += len(_EN_STRONG_RESEARCH_TERMS.findall(sentence)) * 20
        if _EN_UI_REQUIREMENT.search(sentence):
            # Page-control copy ("date filter", "tooltips") is the deliverable,
            # not the external fact to look up. T06-3 searched this sentence.
            score -= 50
        if re.search(r"\bweb(?:search|fetch)\b", sentence, re.IGNORECASE):
            # Tool names describe how to research, not what to research, unless
            # the same sentence already names the assets ("webfetch ... for gold").
            if len(_EN_STRONG_RESEARCH_TERMS.findall(sentence)) == 0:
                score -= 40
        if re.search(
            r"\b(?:plan|collect|research|create|build|develop|analy[sz]e)\b",
            sentence,
            re.IGNORECASE,
        ):
            score += 3
        scored.append((score, -index, sentence))
    if not scored:
        return ""
    candidate = max(scored)[2]
    for_clause = re.search(
        r"\b(?:websearch|webfetch)\b[\s\S]{0,160}?\bfor\b\s+(.+)",
        candidate,
        re.IGNORECASE,
    )
    if for_clause is not None:
        after = re.split(
            r";|\.\s+|Record |Do not |If a source",
            for_clause.group(1),
            maxsplit=1,
        )[0]
        after = after.strip().strip(",")
        if len(after) >= 8:
            candidate = after
    # Keep search requests topical and compact.  Long acceptance prose lowers
    # recall in public engines and makes the prefetch path wait for fallbacks.
    candidate = re.sub(
        r"^\s*(?:plan|collect|research|create|build|develop|analy[sz]e)\b[:,]?\s*",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\bfrom and back to\b", "from", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"\bwith a hard total budget of no more than\b",
        "budget",
        candidate,
        flags=re.IGNORECASE,
    )
    if len(candidate) > 120:
        candidate = candidate[:120].rsplit(" ", 1)[0]
    return candidate.strip()


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
        if marker == "search":
            idx = next(
                (
                    match.start()
                    for match in re.finditer(r"\bsearch\b", lowered)
                    if not lowered[match.end():].lstrip().startswith("/")
                ),
                -1,
            )
        else:
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
            if after and len(after) <= 120 and _is_usable_research_query(after):
                return after

    # 3. No explicit verb.  If we stripped a task-direction prefix, trim
    #    suffixes and command-direction filler; otherwise the input is already
    #    a searchable query and we leave it untouched (preserving punctuation
    #    such as the trailing "？" on "今天最新 Python 版本是什么？").
    if not prefix_stripped:
        # Long English acceptance prompts commonly contain ``websearch`` and
        # ``webfetch`` several times.  If no standalone search verb matched,
        # choose the domain sentence instead of sending a tool-name fragment
        # such as "and webfetch for transport" to the search engine.
        if len(text) > 120 and re.search(r"\bweb(?:search|fetch)\b", text, re.I):
            topic = _english_research_topic(text)
            if topic:
                return topic
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
