"""Load official Gorilla BFCL v4 AST (Python) categories.

Source: https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard
This is the public JSONL dump, not a homemade 8-item slice.

Categories used here are the Python AST set:

- simple_python (400)
- multiple (200)
- parallel (200)
- parallel_multiple (200)
- irrelevance (240)  — no possible_answer file; success = no tool call
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OFFICIAL_DIR = Path(__file__).parent / "official"

CATEGORIES: tuple[tuple[str, str, bool], ...] = (
    ("simple", "BFCL_v4_simple_python.json", True),
    ("multiple", "BFCL_v4_multiple.json", True),
    ("parallel", "BFCL_v4_parallel.json", True),
    ("parallel_multiple", "BFCL_v4_parallel_multiple.json", True),
    ("irrelevance", "BFCL_v4_irrelevance.json", False),
)

EXPECTED_COUNTS = {
    "simple": 400,
    "multiple": 200,
    "parallel": 200,
    "parallel_multiple": 200,
    "irrelevance": 240,
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        item = json.loads(text)
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _prompt_of(row: dict[str, Any]) -> str:
    question = row.get("question")
    if isinstance(question, list) and question:
        first = question[0]
        if isinstance(first, list) and first and isinstance(first[0], dict):
            return str(first[0].get("content") or "")
        if isinstance(first, dict):
            return str(first.get("content") or "")
    return str(row.get("prompt") or "")


def load_official_bfcl() -> list[dict[str, Any]]:
    answers_dir = OFFICIAL_DIR / "possible_answer"
    cases: list[dict[str, Any]] = []
    for category, filename, has_gt in CATEGORIES:
        path = OFFICIAL_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Official BFCL file missing: {path}. "
                "Download from gorilla berkeley-function-call-leaderboard/bfcl_eval/data/"
            )
        gt_by_id: dict[str, list[dict[str, Any]]] = {}
        if has_gt:
            gt_path = answers_dir / filename
            if not gt_path.is_file():
                raise FileNotFoundError(f"Official BFCL ground truth missing: {gt_path}")
            for item in _read_jsonl(gt_path):
                gt_by_id[str(item.get("id") or "")] = list(item.get("ground_truth") or [])
        for row in _read_jsonl(path):
            case_id = str(row.get("id") or "")
            functions = list(row.get("function") or [])
            cases.append(
                {
                    "id": case_id,
                    "category": category,
                    "prompt": _prompt_of(row),
                    "functions": functions,
                    "ground_truth": gt_by_id.get(case_id, []),
                    "official": True,
                }
            )
    return cases


def official_counts(cases: list[dict[str, Any]] | None = None) -> dict[str, int]:
    rows = cases if cases is not None else load_official_bfcl()
    counts = {name: 0 for name in EXPECTED_COUNTS}
    for row in rows:
        category = str(row.get("category") or "")
        if category in counts:
            counts[category] += 1
    return counts
