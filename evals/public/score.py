"""Deterministic scorers for the public-benchmark slice.

Cheap code checks first. ChatEval debate is a separate judge, not this file.
"""

from __future__ import annotations

import json
import re
from typing import Any


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_JSON_LIST = re.compile(r"\[.*\]", re.DOTALL)


def normalize_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 6)
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    compact = re.sub(r"\s+", "", lowered)
    if re.fullmatch(r"-?\d+", compact):
        return int(compact)
    if re.fullmatch(r"-?\d+\.\d+", compact):
        number = float(compact)
        return int(number) if number.is_integer() else round(number, 6)
    return compact if re.search(r"[\d+\-*/]", lowered) else lowered


def normalize_answer(text: str) -> str:
    raw = (text or "").strip()
    raw = raw.replace(",", "")
    raw = re.sub(r"\s+", " ", raw)
    return raw.lower().rstrip(".")


def extract_json_value(text: str) -> Any | None:
    raw = text or ""
    for pattern in (_JSON_LIST, _JSON_BLOCK):
        match = pattern.search(raw)
        if not match:
            continue
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            continue
    return None


def parse_tool_calls(payload: Any) -> list[dict[str, Any]]:
    """Accept LangChain tool_calls, BFCL-style dicts, or JSON text."""
    if payload is None:
        return []
    if isinstance(payload, str):
        parsed = extract_json_value(payload)
        return parse_tool_calls(parsed)
    if isinstance(payload, dict):
        if "name" in payload:
            args = payload.get("arguments", payload.get("args", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            return [{"name": str(payload.get("name") or ""), "arguments": dict(args or {})}]
        if "tool_calls" in payload:
            return parse_tool_calls(payload.get("tool_calls"))
        if "calls" in payload:
            return parse_tool_calls(payload.get("calls"))
    if isinstance(payload, list):
        calls: list[dict[str, Any]] = []
        for item in payload:
            calls.extend(parse_tool_calls(item))
        return calls
    return []


def call_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if str(actual.get("name") or "") != str(expected.get("name") or ""):
        return False
    exp_args = expected.get("arguments") or {}
    act_args = actual.get("arguments") or {}
    if not isinstance(exp_args, dict) or not isinstance(act_args, dict):
        return False
    for key, value in exp_args.items():
        if key not in act_args:
            return False
        actual_value = normalize_scalar(act_args[key])
        expected_value = normalize_scalar(value)
        if actual_value == expected_value:
            continue
        if isinstance(actual_value, str) and isinstance(expected_value, str):
            if expected_value in actual_value or actual_value in expected_value:
                continue
        return False
    return True


def canonicalize_func_name(name: str) -> str:
    """OpenAI-compatible FC forbids '.' in tool names; BFCL uses dots."""
    return str(name or "").replace(".", "_").lower()


def _standardize_string(value: str) -> str:
    return re.sub(r"[ ,./\-_*^]", "", str(value)).lower().replace("'", '"')


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
    if actual == expected:
        return True
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)
    if isinstance(actual, str) and isinstance(expected, str):
        return _standardize_string(actual) == _standardize_string(expected)
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return False
        return all(_values_equal(left, right) for left, right in zip(actual, expected))
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            return False
        return all(_values_equal(actual[key], expected[key]) for key in actual)
    return normalize_scalar(actual) == normalize_scalar(expected)


def _allowed_value(actual: Any, allowed: list[Any]) -> bool:
    for option in allowed:
        if option == "":
            continue
        if _values_equal(actual, option):
            return True
    return False


def official_call_matches(actual: dict[str, Any], expected_item: dict[str, Any]) -> bool:
    """Match one actual call against one BFCL possible_answer dict."""
    if not expected_item:
        return False
    expected_name = next(iter(expected_item))
    expected_args = expected_item.get(expected_name) or {}
    if canonicalize_func_name(actual.get("name") or "") != canonicalize_func_name(expected_name):
        return False
    actual_args = {
        key: value
        for key, value in dict(actual.get("arguments") or {}).items()
        if value is not None
    }
    if not isinstance(expected_args, dict):
        return False
    for key in actual_args:
        if key not in expected_args:
            return False
    for key, allowed in expected_args.items():
        options = list(allowed) if isinstance(allowed, list) else [allowed]
        if key not in actual_args:
            if "" in options:
                continue
            return False
        if not _allowed_value(actual_args[key], options):
            return False
    return True


def score_bfcl_official(
    actual_calls: list[dict[str, Any]],
    *,
    ground_truth: list[dict[str, Any]] | None = None,
    category: str = "simple",
) -> dict[str, Any]:
    """Python AST checker aligned with Gorilla possible_answer files."""
    actual = [
        {
            "name": str(item.get("name") or ""),
            "arguments": {
                key: value
                for key, value in dict(item.get("arguments") or {}).items()
                if value is not None
            },
        }
        for item in (actual_calls or [])
    ]
    expected = list(ground_truth or [])
    if category == "irrelevance":
        passed = len(actual) == 0
        return {
            "passed": passed,
            "reason": "no tool calls" if passed else f"unexpected calls: {[c.get('name') for c in actual]}",
            "actual": actual,
            "expected": [],
        }
    if len(actual) != len(expected):
        return {
            "passed": False,
            "reason": f"wrong call count {len(actual)} != {len(expected)}",
            "actual": actual,
            "expected": expected,
        }
    unused = list(actual)
    for item in expected:
        hit = next((index for index, call in enumerate(unused) if official_call_matches(call, item)), None)
        if hit is None:
            name = next(iter(item), "?")
            return {
                "passed": False,
                "reason": f"missing call {name}",
                "actual": actual,
                "expected": expected,
            }
        unused.pop(hit)
    return {
        "passed": True,
        "reason": f"matched {len(expected)}/{len(expected)}",
        "actual": actual,
        "expected": expected,
    }


def score_bfcl(
    actual_calls: list[dict[str, Any]],
    *,
    expected_calls: list[dict[str, Any]] | None = None,
    category: str = "simple",
    ground_truth: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """AST-style function-call match, order-independent for parallel."""
    if ground_truth is not None:
        return score_bfcl_official(
            actual_calls, ground_truth=ground_truth, category=category
        )
    actual = list(actual_calls or [])
    expected = list(expected_calls or [])
    if category == "irrelevance":
        passed = len(actual) == 0
        return {
            "passed": passed,
            "reason": "no tool calls" if passed else f"unexpected calls: {[c.get('name') for c in actual]}",
            "actual": actual,
            "expected": [],
        }

    unused = list(actual)
    matched = 0
    for exp in expected:
        hit = next((i for i, act in enumerate(unused) if call_matches(act, exp)), None)
        if hit is None:
            return {
                "passed": False,
                "reason": f"missing call {exp.get('name')}",
                "actual": actual,
                "expected": expected,
            }
        unused.pop(hit)
        matched += 1
    passed = matched == len(expected)
    return {
        "passed": passed,
        "reason": f"matched {matched}/{len(expected)}",
        "actual": actual,
        "expected": expected,
    }


def score_gaia(answer: str, expected: str, *, aliases: list[str] | None = None) -> dict[str, Any]:
    """GAIA-style match: first/last lines and whole-word hit after light cleanup."""
    cleaned = re.sub(r"[*`_#]+", " ", answer or "")
    got = normalize_answer(cleaned)
    targets = [normalize_answer(expected), *(normalize_answer(x) for x in (aliases or []))]
    lines = [normalize_answer(line) for line in cleaned.splitlines() if line.strip()]
    candidates = [got, *(lines[:3] if lines else []), *(lines[-3:] if lines else [])]
    for candidate in candidates:
        for target in targets:
            if not target:
                continue
            if candidate == target or candidate.endswith(target) or target in candidate.split():
                return {"passed": True, "reason": f"matched {target!r}", "answer": answer}
            if re.search(rf"(?:^|\s){re.escape(target)}(?:$|\s|[.,;:!?])", candidate):
                return {"passed": True, "reason": f"matched {target!r}", "answer": answer}
    return {"passed": False, "reason": f"expected {expected!r}", "answer": answer}
