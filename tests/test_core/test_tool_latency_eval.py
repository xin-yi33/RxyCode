"""Eval/module fixture for Card C tool latency."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from RxyCode.RxyCode1_1_0.config.settings import _default_config
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, UsageTrackingLLM
from RxyCode.RxyCode1_1_0.tools.bash import BashInput

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "tool-latency.json"


def test_tool_latency_eval_fixture_matches_runtime():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = payload["required_after"]
    exec_cfg = _default_config()["execution"]
    assert exec_cfg["tool_parallel_enabled"] is required["tool_parallel_default"]
    assert exec_cfg["parallel_enabled"] is required["graph_task_parallel_default"]
    assert BashInput.model_fields["timeout"].default == required["bash_timeout_s"]
    assert ("load_config()" in inspect.getsource(AgentV2._raw_stream)) is required[
        "raw_stream_load_config"
    ]
    assert ("load_config" in inspect.getsource(AgentV2._resolve_request_max_tokens)) is required[
        "raw_stream_load_config"
    ]
    assert ("load_config" in inspect.getsource(UsageTrackingLLM._ensure_cache_flag)) is required[
        "raw_stream_load_config"
    ]
