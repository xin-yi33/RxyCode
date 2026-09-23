"""ChatEval-style multi-value debate judge.

Paper: Chan et al., ChatEval (ACL 2024). Official ChatEval is a multi-turn
debate among judge roles. This slice compresses one debate into a single
structured call so a same-day gate stays affordable. Cheap lexical checks
still run first.
"""

from __future__ import annotations

from typing import Any

from .score import extract_json_value, normalize_answer

CHATEVAL_PROMPT = """You are running a ChatEval debate with three judges.

Task:
{task}

Required values: {values}

Answer under review:
{answer}

Judges:
- general: Does the answer address the user's request without dodging?
- critic: Does the answer miss a required value or introduce a contradiction?
- specialist: Would a careful operator accept this as balanced and actionable?

Each judge votes pass or fail. Majority wins.
Respond with ONLY JSON:
{{"votes": {{"general": "pass"|"fail", "critic": "pass"|"fail", "specialist": "pass"|"fail"}}, "rationale": "<one sentence>"}}
"""


def _token_group(item: Any) -> list[str]:
    if isinstance(item, (list, tuple)):
        return [str(token) for token in item if str(token).strip()]
    text = str(item or "").strip()
    return [text] if text else []


def lexical_value_hit(answer: str, must_mention: list[Any]) -> dict[str, Any]:
    """Each item is a token, or a list of language variants (OR)."""
    hay = normalize_answer(answer)
    missing: list[str] = []
    for item in must_mention or []:
        group = _token_group(item)
        if not group:
            continue
        if any(normalize_answer(token) in hay for token in group):
            continue
        missing.append("|".join(group))
    return {
        "passed": not missing,
        "missing": missing,
        "reason": "all required tokens present" if not missing else f"missing {missing}",
    }


def parse_chateval_votes(text: str) -> dict[str, Any]:
    data = extract_json_value(text)
    if not isinstance(data, dict):
        return {"ok": False, "passed": False, "votes": {}, "rationale": "no JSON"}
    votes_raw = data.get("votes") or {}
    votes: dict[str, str] = {}
    if isinstance(votes_raw, dict):
        for role in ("general", "critic", "specialist"):
            value = str(votes_raw.get(role) or "").strip().lower()
            if value in {"pass", "fail"}:
                votes[role] = value
    if len(votes) < 3:
        return {
            "ok": False,
            "passed": False,
            "votes": votes,
            "rationale": str(data.get("rationale") or "incomplete votes"),
        }
    passed = sum(1 for vote in votes.values() if vote == "pass") >= 2
    return {
        "ok": True,
        "passed": passed,
        "votes": votes,
        "rationale": str(data.get("rationale") or "")[:400],
    }


def build_chateval_prompt(task: str, answer: str, values: list[str]) -> str:
    return CHATEVAL_PROMPT.format(
        task=task or "(none)",
        values=", ".join(values) or "(none)",
        answer=(answer or "(no answer)")[:6000],
    )


async def debate(llm, *, task: str, answer: str, values: list[str]) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    prompt = build_chateval_prompt(task, answer, values)
    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    content = getattr(resp, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            str(block.get("text") if isinstance(block, dict) else block) for block in content
        )
    result = parse_chateval_votes(str(content))
    result["raw"] = str(content)[:1500]
    return result
