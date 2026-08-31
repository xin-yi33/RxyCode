"""Opt-in OpenCode Go smoke matrix for the two user-requested model classes.

Credentials are read only from the environment.  This test deliberately fails
on provider/region errors once live mode is enabled; a skipped or blocked Muse
request is not release evidence.
"""

from __future__ import annotations

import os

import pytest
import yaml
from langchain_core.messages import HumanMessage
from openai import PermissionDeniedError


pytestmark = pytest.mark.live

_LIVE_ENABLED = (
    os.environ.get("RXYCODE_RUN_LIVE_TESTS") == "1"
    and bool(os.environ.get("RXYCODE_LIVE_API_KEY"))
)


@pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason=(
        "requires RXYCODE_RUN_LIVE_TESTS=1, RXYCODE_LIVE_API_KEY, "
        "and an isolated test budget"
    ),
)
@pytest.mark.parametrize(
    ("model_name", "provider_name"),
    [
        ("hy3", "hy3"),
        ("muse-spark-1.2-contributor", "muse_spark"),
    ],
)
async def test_opencode_go_model_class_smoke(
    isolated_runtime, model_name, provider_name
):
    from RxyCode.RxyCode1_1_0.config.settings import _default_config
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    config = _default_config()
    config["models"] = {
        "live-opencode-go": {
            "model_name": model_name,
            "api_key_env": "RXYCODE_LIVE_API_KEY",
            "base_url": "https://opencode.ai/zen/go/v1",
            "max_tokens": 1024,
        }
    }
    config["active_model"] = "live-opencode-go"
    isolated_runtime.config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )

    agent = AgentV2()
    assert agent._provider.name == provider_name

    text = []
    try:
        async for chunk in agent._raw_stream(
            [HumanMessage(content="Reply with exactly: OK")], max_tokens=1024
        ):
            choices = getattr(chunk, "choices", None) or []
            if choices:
                text.append(str(getattr(choices[0].delta, "content", "") or ""))
    except PermissionDeniedError as exc:
        if "DataPolicyError" in str(exc):
            pytest.fail(
                "OpenCode Go reached the Muse Contributor route, but this "
                "workspace has not opted in to Contributor data use. A workspace "
                "owner must review and accept that policy before release testing; "
                "do not treat this as a passing or skipped model test.",
                pytrace=False,
            )
        raise
    assert "OK" in "".join(text).upper()
