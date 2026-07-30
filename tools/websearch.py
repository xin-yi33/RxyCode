"""Web search tool with retry and multi-engine fallback."""
import html
import os
import re
import time
import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _get_proxy() -> str | None:
    """Read proxy from environment variables."""
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or os.environ.get("all_proxy")
    )


def _client(**kwargs) -> httpx.Client:
    """Create httpx.Client with system proxy support."""
    proxy = _get_proxy()
    if proxy:
        kwargs.setdefault("proxy", proxy)
    # Lower per-engine timeout so a single slow/unreachable engine cannot stall
    # the whole search. The parallel race (search_web) adds a global budget on
    # top of this.
    kwargs.setdefault("timeout", 8)
    kwargs.setdefault("follow_redirects", True)
    return httpx.Client(**kwargs)


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")
    numResults: int = Field(default=5, description="Number of results to return")


def _clean_text(s: str) -> str:
    """Strip HTML tags and decode entities (fixes &amp; / &#39; garble)."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _clean_url(u: str) -> str:
    """Drop pseudo-links and normalise to an absolute http(s) URL."""
    if not u:
        return ""
    u = html.unescape(u).strip()
    if not u or u.startswith(("javascript:", "#", "mailto:", "about:")):
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if " " in u:
        return ""
    return u


def _search_github_api(query: str, numResults: int = 5) -> list[str]:
    """Search via GitHub REST API (no auth needed, 60 req/hour limit)."""
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RxyCode-WebSearch/1.1",
    }
    with _client() as client:
        resp = client.get(
            url,
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": min(numResults, 30),
            },
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("items", []):
        full_name = item.get("full_name", "")
        html_url = _clean_url(item.get("html_url", ""))
        if not html_url:
            continue
        description = _clean_text(item.get("description") or "")
        stars = item.get("stargazers_count", 0)
        language = item.get("language") or ""
        results.append(
            f"\u2b50 {full_name} ({stars:,} stars)\n  {html_url}\n  {description}"
            + (f" [{language}]" if language else "")
        )
    return results


def _search_duckduckgo(query: str, numResults: int = 5) -> list[str]:
    """Search via DuckDuckGo HTML endpoint."""
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": _BROWSER_UA}
    with _client() as client:
        resp = client.post(url, data={"q": query}, headers=headers)
        resp.raise_for_status()
        html = resp.text
    results = []
    pattern = r'<a rel="nofollow" class="result__a" href="([^"]+)".*?>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</span>'
    for match in re.finditer(pattern, html, re.DOTALL):
        if len(results) >= numResults:
            break
        link = _clean_url(match.group(1))
        title = _clean_text(match.group(2))
        snippet = _clean_text(match.group(3))
        if not link or not title:
            continue
        results.append(f"{title}\n  {link}\n  {snippet}")
    return results


def _search_google(query: str, numResults: int = 5) -> list[str]:
    """Search via Google (scrape)."""
    url = "https://www.google.com/search"
    headers = {"User-Agent": _BROWSER_UA}
    with _client() as client:
        resp = client.get(url, params={"q": query, "num": numResults}, headers=headers)
        resp.raise_for_status()
        html_text = resp.text
    results = []
    for m in re.finditer(r'<a href="/url\?q=([^&"]+)&[^"]*"[^>]*>(.*?)</a>', html_text, re.DOTALL):
        if len(results) >= numResults:
            break
        link = _clean_url(m.group(1))
        title = _clean_text(m.group(2))
        if not link or not title or "google.com" in link:
            continue
        # Best-effort snippet from a sibling result block right after the link.
        snippet = ""
        after = html_text[m.end(): m.end() + 600]
        sm = re.search(r'class="[^"]*(?:BNeawe|s3v9rd|AP7Wnd|yXK7lf)[^"]*"[^>]*>(.*?)</div>', after, re.DOTALL)
        if sm:
            snippet = _clean_text(sm.group(1))
        results.append(f"{title}\n  {link}\n  {snippet}")
    return results


def _search_bing(query: str, numResults: int = 5) -> list[str]:
    """Search via Bing (scrape)."""
    url = "https://www.bing.com/search"
    headers = {"User-Agent": _BROWSER_UA}
    with _client() as client:
        resp = client.get(url, params={"q": query}, headers=headers)
        resp.raise_for_status()
        html = resp.text
    results = []
    pattern = r'<li class="b_algo"[^>]*>.*?<a href="([^"]+)"[^>]*>(.*?)</a>.*?<p[^>]*>(.*?)</p>'
    for m in re.finditer(pattern, html, re.DOTALL):
        if len(results) >= numResults:
            break
        link = _clean_url(m.group(1))
        title = _clean_text(m.group(2))
        snippet = _clean_text(m.group(3))
        if not link or not title:
            continue
        results.append(f"{title}\n  {link}\n  {snippet}")
    return results


def _search_via_redirect(query, numResults=5):
    """Fallback: use DuckDuckGo lite (simpler HTML, less likely blocked)."""
    results = []
    try:
        url = "https://lite.duckduckgo.com/lite/"
        headers = {"User-Agent": _BROWSER_UA}
        with _client() as client:
            resp = client.post(url, data={"q": query}, headers=headers)
            resp.raise_for_status()
            html = resp.text
        pattern = r'rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        for m in re.finditer(pattern, html, re.DOTALL):
            if len(results) >= numResults:
                break
            link = _clean_url(m.group(1))
            title = _clean_text(m.group(2))
            if title and link.startswith("http"):
                results.append(f"{title}\n  {link}")
    except Exception:
        pass
    return results


def _search_baidu(query, numResults=5):
    """Search via Baidu (works well in China)."""
    import urllib.parse
    url = "https://www.baidu.com/s?" + urllib.parse.urlencode({"wd": query, "rn": numResults})
    headers = {"User-Agent": _BROWSER_UA}
    with _client() as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text
    results = []
    for m in re.finditer(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
        if len(results) >= numResults:
            break
        link = _clean_url(m.group(1))
        title = _clean_text(m.group(2))
        if title and link.startswith("http"):
            results.append(f"{title}\n  {link}")
    return results


def _is_github_query(query: str) -> bool:
    """Check if the query is related to GitHub."""
    q = query.lower()
    return any(kw in q for kw in ["github", "git hub", "open source", "repo", "repository"])


# Bug 3 fix: global time budget for the whole search. Engines are raced in
# parallel threads; the highest-quality non-empty result wins. This replaces the
# old sequential 6-engines × 2-attempts × 15s scan that could take ~190s on a
# hard-to-find query and looked like a hang/timeout.
TOTAL_BUDGET = 25.0


def _engine_list(query: str):
    """Ordered engine list — reliable engines first so the race wins fast."""
    engines = []
    if _is_github_query(query):
        engines.append(("GitHub API", _search_github_api))
    engines.extend([
        ("Baidu", _search_baidu),
        ("DuckDuckGo Lite", _search_via_redirect),
        ("DuckDuckGo", _search_duckduckgo),
        ("Bing", _search_bing),
        ("Google", _search_google),
    ])
    return engines


def _result_quality(results: list[str]) -> int:
    """Score a result set: entries with title+url+snippet rank highest.

    This lets us prefer a structured, snippet-rich engine result over a bare
    link-only result (e.g. the old Google parser) when racing in parallel,
    mirroring how gemini-cli / goose pick the most complete web result.
    """
    score = 0
    for entry in results:
        lines = [l.strip() for l in entry.split("\n") if l.strip()]
        if len(lines) >= 3:
            score += 3
        elif len(lines) >= 2:
            score += 1
    return score


def search_web(query: str, numResults: int = 5) -> str:
    """Search the web with a bounded parallel race across engines.

    Instead of trying engines one-by-one (which could take minutes on a query
    no single engine handles well), we fire every engine concurrently and
    return the highest-quality non-empty result, bounded by ``TOTAL_BUDGET``
    seconds. Results are HTML-unescaped and structured (title / url / snippet)
    so the agent receives clean, parseable text instead of garbled markup, and
    even hard-to-find queries never hang the agent loop.
    """
    import concurrent.futures

    engines = _engine_list(query)
    deadline = time.time() + TOTAL_BUDGET
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(len(engines), 6))
    fut_map = {ex.submit(fn, query, numResults): name for name, fn in engines}
    collected: list[tuple[str, list[str]]] = []
    try:
        for fut in concurrent.futures.as_completed(fut_map):
            if time.time() > deadline:
                break
            try:
                res = fut.result(timeout=0)
            except Exception:
                res = None
            if res:
                collected.append((fut_map[fut], res))
    finally:
        # Don't block on still-running engine threads; let them finish silently.
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)

    if not collected:
        return "[search error: All engines failed or timed out]"

    # Prefer the engine whose results are most complete (title+snippet+url).
    collected.sort(key=lambda kv: _result_quality(kv[1]), reverse=True)
    return "\n\n".join(collected[0][1])


websearch_tool = StructuredTool(
    name="websearch",
    description="Search the web using GitHub API, Baidu, DuckDuckGo, Google, Bing.",
    func=search_web,
    args_schema=WebSearchInput,
)
