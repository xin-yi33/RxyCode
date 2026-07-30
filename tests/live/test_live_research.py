from __future__ import annotations

import os

import pytest
import yaml


pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("RXYCODE_RUN_LIVE_TESTS") != "1"
    or not os.environ.get("RXYCODE_LIVE_API_KEY"),
    reason=(
        "live provider test requires RXYCODE_RUN_LIVE_TESTS=1, "
        "RXYCODE_LIVE_API_KEY, and an isolated budget"
    ),
)
async def test_current_fact_research_returns_a_source(isolated_runtime):
    from RxyCode.RxyCode1_1_0.config.settings import _default_config
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    config = _default_config()
    config["models"] = {
        "live-test": {
            "model_name": os.environ.get("RXYCODE_LIVE_MODEL", "gpt-4o-mini"),
            "api_key": os.environ["RXYCODE_LIVE_API_KEY"],
            "base_url": os.environ.get("RXYCODE_LIVE_BASE_URL") or None,
            "temperature": 0,
            "max_tokens": 2048,
        }
    }
    config["active_model"] = "live-test"
    config["execution"].update(
        {
            "pipeline_soft_budget_seconds": 90,
            "tool_timeout_seconds": 30,
            "heartbeat_interval_seconds": 5,
        }
    )
    config["safety"]["auto_approve"] = ["read"]
    isolated_runtime.config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )

    agent = AgentV2()
    answer = await agent.run(
        "What is the latest stable Python release? Cite the official source.",
        mode="build",
    )

    assert "https://" in answer
    assert "python.org" in answer.lower()
