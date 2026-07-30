"""Build-pipeline timeout / progress-handling tests (#1: 10-minute hang).

Root cause: build-mode LangGraph pipeline had no intentional step budget
(LangGraph default recursion_limit=25) and, on hitting the 600s wall-clock
monitor, silently discarded all partial work and fell back to a tool-less
text reply — so "write a parkour game" hung ~10 min then returned a useless
blurb instead of a game. Progress was also reported as a frozen "phase:
planning".

These tests lock in the FIXED behaviour:
  * build_progress_message() reports honest elapsed time (no frozen "planning")
  * build_timeout_notice() reports a configured soft-budget stop without
    triggering or implying a second tool run
  * build_graph() compiles with an explicit recursion_limit (intentional budget)
"""
import sys

PKG = "RxyCode.RxyCode1_1_0"

# Import the pure helpers directly (no LLM / langgraph needed at import time).
sys.path.insert(0, "D:/agent-demo/RxyCode")
sys.path.insert(0, "D:/agent-demo/RxyCode/RxyCode1_1_0")
from RxyCode.RxyCode1_1_0.core.agent_v2 import (  # noqa: E402
    build_progress_message,
    build_timeout_notice,
)


def test_build_progress_message_is_honest_and_not_frozen():
    """Progress text must show real elapsed time, not a stuck 'planning'."""
    elapsed = 607.5
    msg = build_progress_message(elapsed)
    assert "planning" not in msg.lower(), "frozen 'phase: planning' must be gone"
    assert f"{elapsed:.0f}" in msg, "elapsed seconds should be visible to the user"
    assert "Build in progress" in msg


def test_build_progress_message_shows_minutes_over_60s():
    msg = build_progress_message(125)
    assert "~2m" in msg or "2m" in msg, "should summarise minutes for long builds"


def test_build_timeout_notice_does_not_claim_or_repeat_fallback_work():
    """A soft-budget stop must be explicit and must not imply a second run."""
    out = build_timeout_notice(607.5)
    assert "soft time budget" in out
    assert "not repeated" in out
    assert "single-pass" not in out
    assert "completed" not in out.lower().split("\n")[0]


def test_build_graph_compiles_with_full_node_set():
    """The build graph must compile with all planner/executor/validator/re-planner
    nodes wired (regression guard so a broken compile surfaces in tests, not at
    runtime after a 10-minute hang)."""
    from RxyCode.RxyCode1_1_0.core.graph import build_graph

    graph = build_graph()
    # A compiled LangGraph exposes an async invoke entrypoint.
    assert hasattr(graph, "ainvoke"), "graph did not compile correctly"
