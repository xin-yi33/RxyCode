import pytest

from RxyCode.RxyCode1_1_0.core.research_policy import (
    extract_research_query,
    extract_research_urls,
    get_research_policy,
    is_successful_research_fetch,
    normalize_research_url,
    research_failure_message,
    research_prefetch_failure_note,
    should_abort_on_research_prefetch_failure,
)


def test_chinese_freshness_query_requires_web_and_bypasses_cache():
    policy = get_research_policy("今天 Python 最新版本是什么？")
    assert policy.requires_web is True
    assert policy.cache_read_allowed is False
    assert policy.cache_write_allowed is False
    assert policy.citations_required is True


def test_english_freshness_query_requires_web():
    policy = get_research_policy("What is the current stable Node.js release?")
    assert policy.requires_web is True
    assert policy.cache_read_allowed is False


@pytest.mark.parametrize(
    "query",
    [
        "Search the web for the Python documentation",
        "Search for the Python documentation",
        "Please look up online how this API works",
        "请联网搜索 Python 官方文档",
        "帮我搜索 Python 官方文档",
        "上海明天的天气怎么样？",
        "Who is the president of France?",
        "What regulations apply to this visa?",
        "What is the USD to CNY exchange rate?",
    ],
)
def test_explicit_web_intent_and_volatile_domains_require_web(query):
    assert get_research_policy(query).requires_web is True


def test_stable_knowledge_query_can_use_answer_cache():
    policy = get_research_policy("Explain what a Python decorator is")
    assert policy.requires_web is False
    assert policy.cache_read_allowed is True
    assert policy.cache_write_allowed is True


def test_bare_algorithm_search_does_not_force_web_research():
    assert get_research_policy("Implement binary search in Python").requires_web is False
    assert get_research_policy("Convert one to two fields").requires_web is False


@pytest.mark.parametrize(
    "query",
    [
        "请检查当前工作区和当前时间，然后创建一个离线 HTML 游戏。",
        "查询当前时间并使用 Java Swing 编写数字游戏。",
        "Check the current time, then build the local offline demo.",
    ],
)
def test_clock_or_workspace_context_does_not_force_web_research(query):
    """A time check is not an external-facts research request.

    The Desktop real-business harness adds a generic current-time check to
    every prompt. Treating that boilerplate as web research sends offline
    tasks through synchronous search/fetch and can starve the appserver.
    """
    assert get_research_policy(query).requires_web is False


def test_local_runtime_state_words_do_not_force_web_research():
    """Game/program state such as the current range is local, not web data."""
    query = (
        "\u8bf7\u8c03\u7528 datetime \u67e5\u8be2\u5f53\u524d\u65f6\u95f4\uff0c"
        "\u68c0\u67e5\u5f53\u524d\u5de5\u4f5c\u533a\u548c\u5f53\u524d\u8303\u56f4\uff0c"
        "\u7136\u540e\u8fd0\u884c\u672c\u5730 Java \u7a0b\u5e8f\u3002"
    )
    assert get_research_policy(query).requires_web is False


def test_current_workspace_audit_with_local_tools_does_not_force_web_research():
    """A local audit must not be misrouted merely because it says "current".

    This is the exact intent behind the Desktop regression where the agent
    fanned out to external search engines and the appserver watchdog expired
    before it could execute the requested local glob/grep/read calls.
    """
    query = (
        "Audit the current workspace. Call glob, grep, and read only; "
        "do not use web search."
    )

    assert get_research_policy(query).requires_web is False


def test_current_local_time_and_workspace_do_not_force_web_research():
    query = "Inspect the current workspace and current time before building the local offline demo."
    assert get_research_policy(query).requires_web is False


def test_local_runtime_state_phrases_do_not_force_web_research():
    query = "Build a Java game and verify the current range, current score, and current level."
    assert get_research_policy(query).requires_web is False


def test_local_artifact_repair_prompt_does_not_force_web_research():
    """A generated-artifact repair turn must stay local.

    The repair validator includes words such as ``currently``, ``source`` and
    ``status``. Before this guard, those words routed the repair turn through
    synchronous multi-engine search even though it only needed local files.
    """
    query = (
        "Artifact repair pass for T05. The previous turn was incomplete. "
        "Inspect every file currently present and fix the Java source. "
        "Do not call or use websearch, webfetch, browsing, internet, or "
        "external research. Use only the existing workspace and local tools. "
        "Report the current status after running javac."
    )
    assert get_research_policy(query).requires_web is False


def test_current_price_still_requires_web_research():
    assert get_research_policy("Check the current price of gold before advising me.").requires_web is True


def test_explicit_web_tool_request_requires_web_research():
    assert get_research_policy(
        "First call websearch at least three times and webfetch at least twice."
    ).requires_web is True


def test_explicit_web_request_wins_over_workspace_boilerplate():
    """A build prompt may mention the local workspace and opening a page,
    while still explicitly requiring external research.

    The old local-tool heuristic saw ``current workspace`` plus a generic
    ``open``/``read`` word in the acceptance checklist and disabled web tools
    before the fast path could prefetch them.
    """
    query = (
        "Create T04-travel in the current workspace. First call datetime and "
        "record the current date. Use websearch and webfetch for transport, "
        "lodging, tickets, food, styling, and contingency costs. Deliver an "
        "interactive webpage, then open it and verify the budget filters."
    )
    policy = get_research_policy(query)
    assert policy.requires_web is True
    assert policy.cache_read_allowed is False


def test_local_offline_task_status_does_not_force_web_research():
    """Local delivery/status language is not a request for external facts.

    The real-business harness appends common completion rules mentioning task
    status.  A standalone ``status`` keyword must not send an offline game
    through synchronous websearch/webfetch before local tools can run.
    """
    query = (
        "Create an original offline HTML game with keyboard controls, score, "
        "collision and restart. Verify the local runtime status and write a "
        "README and TEST-REPORT. Do not use websearch or external assets."
    )

    assert get_research_policy(query).requires_web is False


def test_local_readonly_tool_sequence_overrides_release_freshness_keyword():
    """A Desktop code audit must honor its explicit no-web tool constraint."""
    query = (
        "Execute exactly these read-only tools: glob for appserver/runtime.py; "
        "grep for install_tui_context_hook; then read lines 1-45. "
        "Do not call bash, cd, ls, write, shell, web, or any other tool. "
        "Act as a release engineer and return delivery risk."
    )

    assert get_research_policy(query).requires_web is False


def test_research_urls_are_deduplicated_normalized_and_private_hosts_rejected():
    urls = extract_research_urls(
        "https://Example.com/source). https://example.com/source "
        "http://127.0.0.1/admin https://localhost/private"
    )
    assert urls == ["https://example.com/source"]
    assert normalize_research_url("https://user:secret@example.com/") is None


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("Fetched source body", True),
        ("", False),
        ("[error fetching https://example.com: timeout]", False),
        ("[blocked: policy]", False),
        ("[rejected: approval denied]", False),
        ("[tool timeout: webfetch exceeded 30s]", False),
        ("[search error: all engines timed out]", False),
        ("None", False),
    ],
)
def test_research_fetch_success_requires_real_content(result, expected):
    assert is_successful_research_fetch(result) is expected


def test_research_failure_message_refuses_to_guess():
    message = research_failure_message("all engines timed out")
    assert "could not verify" in message
    assert "will not guess" in message
    assert "timed out" in message


def test_research_failure_message_redacts_provider_keys():
    leaked = "sk-" + "A" * 32
    message = research_failure_message(
        f"Error code: 401 Incorrect API key provided: {leaked}"
    )
    assert leaked not in message
    assert "sk-" not in message
    assert "[REDACTED]" in message
    assert "401" in message


@pytest.mark.parametrize(
    ("user_input", "expected_query"),
    [
        # The mandatory-research path must not hand the whole instruction to a
        # search engine; the topic after the search verb is what matters.
        (
            "使用网页搜索（websearch 工具）搜索成都三日游攻略，整理一份简要的成都三日游行程并写入当前目录的 travel_guide.md",
            "成都三日游攻略",
        ),
        (
            "使用网页搜索工具搜索 2026 年 AI 编程助手领域最重要的趋势，总结出 3 条趋势",
            "2026 年 AI 编程助手领域最重要的趋势",
        ),
        (
            "帮我搜索 Python 的 rich 库最新用法，然后写一个脚本",
            "Python 的 rich 库最新用法",
        ),
        (
            "What is the current stable Node.js release?",
            "current stable Node.js release",
        ),
        (
            "搜索一下 Python 3.12 的新特性",
            "Python 3.12 的新特性",
        ),
        (
            "查一下 2026 年成都马拉松的报名时间",
            "2026 年成都马拉松的报名时间",
        ),
    ],
)
def test_extract_research_query_strips_task_direction(user_input, expected_query):
    query = extract_research_query(user_input)
    assert expected_query in query
    # The query must never contain the instruction boilerplate.
    assert "websearch" not in query
    assert "写入" not in query
    assert "整理一份" not in query
    assert len(query) <= 120


def test_extract_research_query_empty_and_fallback():
    assert extract_research_query("") == ""
    # No explicit search marker: falls back to the input, stripping prefixes.
    query = extract_research_query("今天 Python 最新版本是什么？")
    assert query  # non-empty


def test_extract_research_query_does_not_use_webfetch_as_english_topic():
    prompt = (
        "Create T04-travel in the current workspace. First call datetime and record the current date. "
        "Plan a five-day four-night Suzhou plus Hangzhou trip from and back to Guangzhou with a hard "
        "total budget of no more than CNY 3000 and one makeup styling session. "
        "Use websearch and webfetch for transport, lodging, tickets, food, local transport, styling, "
        "and contingency costs; record source URL and access date. Deliver an interactive webpage."
    )

    query = extract_research_query(prompt)

    assert "webfetch" not in query.lower()
    assert "transport" in query.lower() or "suzhou" in query.lower()
    assert "websearch" not in query.lower()
    assert len(query) <= 120
    assert "今天 Python 最新版本是什么" in query or query


def test_extract_research_query_ignores_search_filter_ui_feature():
    prompt = (
        "Create T03-company in the current workspace. First call websearch at least three "
        "times and webfetch at least twice to research company website competitors. "
        "Build a static HTML company website. A successful demo login must open an admin "
        "console; support validation, search/filter, CRUD, persistence after refresh, and logout."
    )
    query = extract_research_query(prompt)
    assert query != "/filter"
    assert "filter" not in query.lower()
    assert "website" in query.lower() or "company" in query.lower() or "competitors" in query.lower()


def test_extract_research_query_prefers_market_assets_over_page_controls():
    prompt = (
        "Create T06-market-bi in the current workspace. Call datetime first. "
        "Then call websearch at least three times and webfetch at least twice for gold, silver, "
        "an A-share technology index or STAR 50, Nasdaq Composite, and S&P 500. "
        "The page must provide date filter, asset filter, normalized benchmark, metric switcher, "
        "tooltips, detail table, data-gap warnings, and a risk disclaimer."
    )
    query = extract_research_query(prompt)
    lowered = query.lower()
    assert "date filter" not in lowered
    assert "tooltip" not in lowered
    assert "gold" in lowered or "silver" in lowered or "nasdaq" in lowered
    assert "webfetch" not in lowered
    assert len(query) <= 120


def test_current_working_directory_boilerplate_does_not_force_web():
    """Eval/harness boilerplate says 当前工作目录; the leftover 当前 must not force web.

    ``当前目录`` is stripped, but ``当前工作目录`` is not a substring of that
    phrase, so a bare ``当前`` used to keep requires_web True and prefetch
    websearch before any local write/edit.
    """
    query = (
        "修复 cart.py 的可变默认参数。"
        "所有文件必须创建/修改在【当前工作目录】内；禁止把文件写入仓库目录。"
    )
    assert get_research_policy(query).requires_web is False
    assert should_abort_on_research_prefetch_failure(query) is False


def test_eval_local_file_prompts_do_not_force_web_or_abort():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2] / "evals" / "tasks"
    for name in (
        "bugfix-mutable-default.yaml",
        "bugfix-off-by-one.yaml",
        "bugfix-string-reverse.yaml",
        "feature-fizzbuzz.yaml",
        "feature-cli-parser.yaml",
        "refactor-replace-magic-numbers.yaml",
        "refactor-extract-function.yaml",
    ):
        prompt = yaml.safe_load((root / name).read_text(encoding="utf-8"))["prompt"]
        assert get_research_policy(prompt).requires_web is False, name
        assert should_abort_on_research_prefetch_failure(prompt) is False, name
    web = yaml.safe_load((root / "websearch-summary.yaml").read_text(encoding="utf-8"))["prompt"]
    assert get_research_policy(web).requires_web is True


def test_creation_task_does_not_abort_when_research_prefetch_fails():
    create = (
        "Create T03-company in the current workspace. First call websearch and webfetch "
        "to research company website competitors, then build a static website."
    )
    assert should_abort_on_research_prefetch_failure(create) is False
    assert should_abort_on_research_prefetch_failure("今天最新 Python 版本是什么？") is True
    assert "continue the requested local artifact" in research_prefetch_failure_note("timeout")
