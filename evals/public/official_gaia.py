"""Official GAIA 2023 validation (165 items).

Source: ModelScope mirror of gaia-benchmark/GAIA (same parquet as HuggingFace).
Validation answers are public; the 301-item test split is not scored here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

OFFICIAL_DIR = Path(__file__).parent / "official" / "gaia"
PARQUET_PATH = OFFICIAL_DIR / "metadata.parquet"
FILES_DIR = OFFICIAL_DIR / "files"

EXPECTED_COUNTS = {"1": 53, "2": 86, "3": 26}
EXPECTED_TOTAL = 165


def load_official_gaia() -> list[dict[str, Any]]:
    if not PARQUET_PATH.is_file():
        raise FileNotFoundError(
            f"Official GAIA parquet missing: {PARQUET_PATH}. "
            "Download 2023/validation/metadata.parquet from ModelScope AI-ModelScope/GAIA."
        )
    frame = pd.read_parquet(PARQUET_PATH)
    cases: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        task_id = str(row.get("task_id") or "")
        file_name = str(row.get("file_name") or "").strip()
        question = str(row.get("Question") or "").strip()
        if file_name:
            question = (
                f"{question}\n\nA file named `{file_name}` is in your workspace. "
                "Use it if the question depends on it. Reply with the final answer only."
            )
        else:
            question = f"{question}\n\nReply with the final answer only."
        attachment = None
        if file_name:
            path = FILES_DIR / file_name
            if path.is_file():
                attachment = path
        cases.append(
            {
                "id": task_id,
                "level": int(str(row.get("Level") or "1")),
                "prompt": question,
                "expected": str(row.get("Final answer") or ""),
                "aliases": [],
                "attachment": str(attachment) if attachment is not None else "",
                "file_name": file_name,
                "official": True,
            }
        )
    return cases


def official_gaia_counts(cases: list[dict[str, Any]] | None = None) -> dict[str, int]:
    rows = cases if cases is not None else load_official_gaia()
    counts = {"1": 0, "2": 0, "3": 0}
    for row in rows:
        key = str(row.get("level") or "")
        if key in counts:
            counts[key] += 1
    return counts
