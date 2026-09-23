"""Deterministic tests for the public-benchmark harness. No live LLM."""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.evals.public.cases import bfcl_cases, chateval_cases, gaia_cases
from RxyCode.RxyCode1_1_0.evals.public.chateval import lexical_value_hit, parse_chateval_votes
from RxyCode.RxyCode1_1_0.evals.public.official_bfcl import EXPECTED_COUNTS, official_counts
from RxyCode.RxyCode1_1_0.evals.public.reports import render_matrix
from RxyCode.RxyCode1_1_0.evals.public.runner import is_retryable_text
from RxyCode.RxyCode1_1_0.evals.public.score import (
    parse_tool_calls,
    score_bfcl,
    score_bfcl_official,
    score_gaia,
)


def test_homemade_slice_still_eight():
    assert len(bfcl_cases(official=False)) == 8
    assert len(gaia_cases(official=False)) == 6
    assert len(chateval_cases(official=False)) == 3


def test_official_gaia_validation_is_165():
    from RxyCode.RxyCode1_1_0.evals.public.official_gaia import EXPECTED_COUNTS, EXPECTED_TOTAL, official_gaia_counts

    cases = gaia_cases(official=True)
    assert len(cases) == EXPECTED_TOTAL
    assert official_gaia_counts(cases) == EXPECTED_COUNTS
    first = cases[0]
    assert first["official"] is True
    assert first["expected"]


def test_official_chateval_is_mtbench_80():
    cases = chateval_cases(official=True)
    assert len(cases) == 80
    assert cases[0]["id"].startswith("mtbench-")
    assert cases[0]["official"] is True


def test_official_bfcl_is_full_ast_set():
    counts = official_counts()
    assert counts == EXPECTED_COUNTS
    assert sum(counts.values()) == 1240
    cases = bfcl_cases(official=True)
    assert len(cases) == 1240
    first = next(case for case in cases if case["id"] == "simple_python_0")
    assert first["functions"][0]["name"] == "calculate_triangle_area"
    assert first["ground_truth"][0]["calculate_triangle_area"]["base"] == [10]


def test_bfcl_simple_and_parallel_match():
    actual = [
        {"name": "get_weather", "arguments": {"city": "Paris", "unit": "celsius"}},
        {"name": "get_weather", "arguments": {"city": "Berlin", "unit": "Celsius"}},
    ]
    expected = [
        {"name": "get_weather", "arguments": {"city": "Berlin"}},
        {"name": "get_weather", "arguments": {"city": "Paris"}},
    ]
    assert score_bfcl(actual, expected_calls=expected, category="parallel")["passed"] is True


def test_official_scorer_optional_unit_and_dotted_name():
    assert score_bfcl_official(
        [{"name": "calculate_triangle_area", "arguments": {"base": 10, "height": 5}}],
        ground_truth=[{"calculate_triangle_area": {"base": [10], "height": [5], "unit": ["units", ""]}}],
        category="simple",
    )["passed"] is True
    assert score_bfcl_official(
        [{"name": "math_factorial", "arguments": {"number": 5}}],
        ground_truth=[{"math.factorial": {"number": [5]}}],
        category="simple",
    )["passed"] is True
    assert score_bfcl_official(
        [{"name": "calculate_triangle_area", "arguments": {"base": 10, "height": 5, "unit": "meters"}}],
        ground_truth=[{"calculate_triangle_area": {"base": [10], "height": [5], "unit": ["units", ""]}}],
        category="simple",
    )["passed"] is False


def test_bfcl_irrelevance_rejects_extra_call():
    verdict = score_bfcl(
        [{"name": "get_weather", "arguments": {"city": "Tokyo"}}],
        expected_calls=[],
        category="irrelevance",
    )
    assert verdict["passed"] is False


def test_bfcl_parses_langchain_shape():
    calls = parse_tool_calls(
        [{"name": "calculate", "args": {"expression": "17 * 23 + 8"}}]
    )
    assert calls[0]["name"] == "calculate"
    assert score_bfcl(
        calls,
        expected_calls=[{"name": "calculate", "arguments": {"expression": "17*23+8"}}],
    )["passed"]


def test_gaia_matches_last_line():
    answer = "I added the column.\nThe total is 42\n"
    assert score_gaia(answer, "42")["passed"] is True
    assert score_gaia("forty two", "42")["passed"] is False


def test_gaia_matches_bold_first_line():
    answer = "**Egalitarian**\n\nI fetched arXiv:2207.01510 and the axis label is egalitarian.\n"
    assert score_gaia(answer, "egalitarian")["passed"] is True


def test_chateval_majority_and_lexical():
    parsed = parse_chateval_votes(
        '{"votes": {"general": "pass", "critic": "fail", "specialist": "pass"}, "rationale": "ok"}'
    )
    assert parsed["ok"] is True
    assert parsed["passed"] is True
    lexical = lexical_value_hit(
        "Keep the approval gate; demo on a fork; residual risk is real.",
        ["approval", "demo", "risk"],
    )
    assert lexical["passed"] is True
    chinese = lexical_value_hit(
        "不会把密钥打到聊天里，调试改走本地配置。",
        [["secret", "密钥"], ["not", "不会"], ["debug", "调试"]],
    )
    assert chinese["passed"] is True


def test_429_is_retryable_not_auth():
    assert is_retryable_text("RateLimitError: Error code: 429 该模型当前访问量过大，请您稍后再试 1305")
    assert is_retryable_text("HTTP 429")
    assert not is_retryable_text("AuthenticationError: invalid_api_key")
    assert not is_retryable_text("missing call calculate_triangle_area")


def test_render_matrix_is_agent_only():
    text = render_matrix(
        {
            "date": "2026-09-08",
            "tag": "2026-09-08-public",
            "model": "zhipu/glm-5.3-flash",
            "note": "agent-only",
            "suites": {
                "bfcl": {
                    "agent": {"passed": 1000, "total": 1240, "pass_rate": 1000 / 1240},
                }
            },
            "cases": [],
        }
    )
    assert "1240" in text
    assert "RxyCode Agent" in text
    assert "OpenHands" in text
    assert "Magentic-One" in text
    assert "165" in text
    assert "80" in text
