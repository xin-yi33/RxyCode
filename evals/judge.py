"""LLM-as-judge scoring for eval task outputs.

Prompt template stitched from the OpenAI evals scoring-template pattern:
a fixed rubric, per-dimension 1-5 anchors, and a strict JSON output
contract with an example. Only the pattern is ported; the rubric text is
written for RxyCode's coding-agent tasks.

The judge model is chosen by config ``evals.judge_model`` (falls back to
the active model). Judge calls go through UsageTrackingLLM so their
tokens/cost are billed into token_stats like every other LLM call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: Fixed judge prompt template (OpenAI-evals style: role + rubric +
#: output contract + few-shot output example). Placeholders:
#:   {task_prompt}   — the instruction given to the agent
#:   {agent_answer}  — the agent's final answer text
#:   {artifacts}     — concatenated contents of files in the workdir (may be "")
JUDGE_PROMPT_TEMPLATE = """You are an impartial senior software engineer acting as a judge for a coding-agent benchmark.

## Task given to the agent
{task_prompt}

## Agent's final answer
{agent_answer}

## Files in the agent's workspace after the run
{artifacts}

## Rubric
Score the agent's work on three dimensions, each from 1 (worst) to 5 (best):

- correctness (1-5): Does the solution actually solve the task? Would the
  code run and produce the right behavior? 5 = fully correct; 3 = partially
  correct with notable gaps; 1 = wrong or missing.
- style (1-5): Is the code/answer clear, idiomatic, and well organized?
  5 = clean and idiomatic; 3 = readable but clumsy; 1 = messy or confusing.
- efficiency (1-5): Is the approach reasonably efficient and direct, without
  pointless complexity or wasted work? 5 = direct and efficient;
  3 = workable but wasteful; 1 = grossly over-engineered or inefficient.

## Output contract
Respond with ONLY a JSON object, no prose, no markdown fences. Schema:
{{"correctness": <int 1-5>, "style": <int 1-5>, "efficiency": <int 1-5>, "rationale": "<one sentence>"}}

Example:
{{"correctness": 5, "style": 4, "efficiency": 4, "rationale": "Fixes the off-by-one cleanly; minor naming nit."}}
"""


@dataclass
class JudgeScore:
    """Parsed judge output. ``ok`` is False when parsing fell back."""

    correctness: int = 0
    style: int = 0
    efficiency: int = 0
    rationale: str = ""
    ok: bool = True
    raw: str = ""

    @property
    def mean(self) -> float:
        return (self.correctness + self.style + self.efficiency) / 3.0

    def to_dict(self) -> dict:
        return {
            "correctness": self.correctness,
            "style": self.style,
            "efficiency": self.efficiency,
            "mean": round(self.mean, 3),
            "rationale": self.rationale,
            "ok": self.ok,
        }


def _clamp_score(value: Any) -> int:
    """Coerce a score into the 1-5 range; 0 marks 'unusable'."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return max(1, min(5, v))


def parse_judge_output(text: str) -> JudgeScore:
    """Parse the judge LLM's reply into a JudgeScore.

    Tolerant extraction (same idea as validation/validator.py): find the
    first {...} JSON block. On any failure return a zero-score fallback
    with ok=False instead of raising — a judge hiccup must not kill a run.
    """
    raw = text or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return JudgeScore(ok=False, raw=raw, rationale="no JSON in judge output")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return JudgeScore(ok=False, raw=raw, rationale="judge output is not valid JSON")
    if not isinstance(data, dict):
        return JudgeScore(ok=False, raw=raw, rationale="judge JSON is not an object")

    correctness = _clamp_score(data.get("correctness"))
    style = _clamp_score(data.get("style"))
    efficiency = _clamp_score(data.get("efficiency"))
    if 0 in (correctness, style, efficiency):
        return JudgeScore(ok=False, raw=raw, rationale="judge scores missing or out of range")
    return JudgeScore(
        correctness=correctness,
        style=style,
        efficiency=efficiency,
        rationale=str(data.get("rationale", ""))[:500],
        ok=True,
        raw=raw,
    )


def build_judge_prompt(task_prompt: str, agent_answer: str, artifacts: str) -> str:
    """Render the fixed judge prompt template."""
    return JUDGE_PROMPT_TEMPLATE.format(
        task_prompt=task_prompt or "(none)",
        agent_answer=(agent_answer or "(no answer)")[:8000],
        artifacts=(artifacts or "(no files)")[:8000],
    )


def resolve_judge_model_name(cfg: dict) -> Optional[str]:
    """Config ``evals.judge_model`` wins; None means 'use the active model'."""
    evals_cfg = (cfg or {}).get("evals") or {}
    return evals_cfg.get("judge_model")


async def judge_task(
    llm,
    *,
    task_prompt: str,
    agent_answer: str,
    artifacts: str = "",
) -> JudgeScore:
    """Run one judge call through the (usage-tracked) LLM.

    ``llm`` is expected to be a UsageTrackingLLM (or anything with an
    async ``ainvoke(messages)`` returning an object with ``.content``).
    """
    from langchain_core.messages import HumanMessage

    prompt = build_judge_prompt(task_prompt, agent_answer, artifacts)
    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    return parse_judge_output(getattr(resp, "content", ""))
