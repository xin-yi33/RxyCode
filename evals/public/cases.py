"""Load the public-benchmark fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"{name} must be an object with a cases list")
    return data


def bfcl_cases(*, official: bool = True) -> list[dict[str, Any]]:
    if official:
        from .official_bfcl import load_official_bfcl

        return load_official_bfcl()
    return list(load_json("bfcl_slice.json")["cases"])


def gaia_cases(*, official: bool = True) -> list[dict[str, Any]]:
    if official:
        from .official_gaia import load_official_gaia

        return load_official_gaia()
    return list(load_json("gaia_slice.json")["cases"])


def chateval_cases(*, official: bool = True) -> list[dict[str, Any]]:
    if official:
        from .official_chateval import load_official_chateval

        return load_official_chateval()
    return list(load_json("chateval_slice.json")["cases"])
