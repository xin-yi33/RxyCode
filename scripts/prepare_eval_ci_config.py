"""Write a minimal RxyCode config.yaml for CI eval runs (no secrets logged)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml


def main() -> int:
    api_key = os.environ.get("RXYCODE_LIVE_API_KEY", "").strip()
    if not api_key:
        print(
            "RXYCODE_LIVE_API_KEY is not set; eval suite cannot run in CI.",
            file=sys.stderr,
        )
        return 2

    data_dir = Path(os.environ.get("RXYCODE_DATA_DIR", "")).expanduser()
    if not data_dir:
        print("RXYCODE_DATA_DIR is required", file=sys.stderr)
        return 2

    model = os.environ.get("RXYCODE_EVAL_MODEL", "deepseek-v4-flash").strip()
    base_url = os.environ.get(
        "RXYCODE_EVAL_BASE_URL", "https://api.deepseek.com"
    ).strip()

    data_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "active_model": model,
        "models": {
            model: {
                "model_name": model,
                "api_key": api_key,
                "base_url": base_url,
            }
        },
    }
    path = data_dir / "config.yaml"
    path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    print(f"Prepared eval config at {path} (credentials not printed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())