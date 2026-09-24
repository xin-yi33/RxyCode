"""Official MT-Bench questions used as the ChatEval set (80 items)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path(__file__).parent / "official" / "mt_bench_question.jsonl"


def load_official_chateval() -> list[dict[str, Any]]:
    if not PATH.is_file():
        raise FileNotFoundError(f"MT-Bench questions missing: {PATH}")
    cases: list[dict[str, Any]] = []
    for line in PATH.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        row = json.loads(text)
        question_id = row.get("question_id")
        turns = list(row.get("turns") or [])
        cases.append(
            {
                "id": f"mtbench-{question_id}",
                "category": str(row.get("category") or ""),
                "prompt": str(turns[0]) if turns else "",
                "turns": turns,
                "official": True,
            }
        )
    return cases
