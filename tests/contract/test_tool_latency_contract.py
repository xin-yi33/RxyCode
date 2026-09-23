"""Contract: Card C tool-latency seams."""

from __future__ import annotations

import inspect

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def test_execute_tools_snapshots_only_on_writes():
    source = inspect.getsource(AgentV2._execute_tools_parallel)
    assert "ensure_write_snapshot" in source
    synth_src = inspect.getsource(AgentV2._synthesis_with_tools)
    assert "_execute_tools_parallel" in synth_src
    assert "await self._execute_tool(" not in synth_src
    round_src = inspect.getsource(AgentV2._raw_stream)
    assert "load_config()" not in round_src
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    cfg_src = inspect.getsource(AgentV2._parallel_tool_config)
    assert 'get("tool_parallel_enabled", True)' in cfg_src
    assert 'exec_cfg.get("parallel_enabled"' not in cfg_src
    assert "load_config" not in inspect.getsource(AgentV2._resolve_request_max_tokens)
    assert "load_config" not in inspect.getsource(UsageTrackingLLM._ensure_cache_flag)
