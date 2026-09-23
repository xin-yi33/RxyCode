"""Contract: daily stream path passes an explicit HTTP timeout and arms connect first."""

from __future__ import annotations

import inspect

from RxyCode.RxyCode1_1_0.core import agent_v2
from RxyCode.RxyCode1_1_0.appserver.watchdog import WatchdogState


def test_raw_stream_passes_http_timeout_into_create():
    source = inspect.getsource(agent_v2.AgentV2._raw_stream)
    assert "timeout=http_timeout" in source
    assert "_arm_hard_deadline(connect_timeout, \"connect\")" in source
    assert "client.create(**attempt_payload)" not in source.replace(
        "client.create(**attempt_payload, timeout=http_timeout)", ""
    )


def test_openai_client_disables_sdk_retries():
    source = inspect.getsource(agent_v2.AgentV2._openai_client)
    assert '"max_retries": 0' in source or "'max_retries': 0" in source
    assert "http_timeout" in source


def test_watchdog_stall_doc_is_worker_death():
    doc = inspect.getdoc(WatchdogState.stalled_jobs) or ""
    assert "heartbeat" in doc.lower()
    assert "silence is not a stall" in doc.lower() or "not a stall" in doc.lower()


def test_force_close_schedules_async_sdk_close():
    source = inspect.getsource(agent_v2._schedule_or_call_closer)
    assert "run_coroutine_threadsafe" in source
    assert "iscoroutinefunction" in source
    stream_src = inspect.getsource(agent_v2.AgentV2._raw_stream)
    assert "loop=stream_loop" in stream_src
    assert "chat.completions" in stream_src
