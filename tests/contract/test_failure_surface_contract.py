"""Contract: Card B failure surfaces stay on the three protocol paths."""

from __future__ import annotations

import inspect

from RxyCode.RxyCode1_1_0.core import agent_v2
from RxyCode.RxyCode1_1_0.core import session as session_mod
from RxyCode.RxyCode1_1_0.recovery import error_recovery


def test_session_gates_event_error_on_taxonomy():
    source = inspect.getsource(session_mod.Session.prompt)
    assert "should_emit_event_error" in source
    stream_src = inspect.getsource(agent_v2.AgentV2._raw_stream)
    assert "_is_transport_retryable(exc)" in stream_src


def test_taxonomy_exports_three_kinds_and_surfaces():
    assert error_recovery.ErrorKind.BUSINESS.value == "business"
    assert callable(error_recovery.failure_surface)
    assert callable(error_recovery.should_emit_event_error)
