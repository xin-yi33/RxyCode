#!/bin/sh
# W10-D1: worker image entrypoint — the env-dependent bootstrap the compose
# command used to run inline, then `exec "$@"` so the drain loop is PID 1
# (the probe_worker.py healthcheck asserts /proc/1 is the drain's python).
#
# Writes the deployed model config only when the operator pointed the worker
# at an LLM endpoint. api_key stays an env reference — the key itself never
# lands in the config file.
set -eu

python - <<'PY'
import os
import sys

base_url = os.environ.get("RXYCODE_LLM_BASE_URL", "").strip()
if not base_url:
    sys.exit(0)
import yaml

data_dir = os.environ.get("RXYCODE_DATA_DIR", "/work/data")
os.makedirs(data_dir, exist_ok=True)
path = os.path.join(data_dir, "config.yaml")
cfg = {
    "active_model": "deployed",
    "models": {
        "deployed": {
            "provider_id": "openai",
            "provider_name": "Deployed endpoint",
            "base_url": base_url,
            "model_name": os.environ.get("RXYCODE_LLM_MODEL") or "deployed",
            "api_key_env": "RXYCODE_API_KEY",
            "max_tokens": 8192,
            "temperature": 0.7,
        }
    },
}
with open(path, "w", encoding="utf-8") as fh:
    yaml.safe_dump(cfg, fh)
PY

exec "$@"
