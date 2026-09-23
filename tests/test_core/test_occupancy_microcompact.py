from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.compaction import (
    TOOL_RESULT_TOMBSTONE,
    microcompact_messages,
    occupancy_tokens,
)


def test_occupancy_counts_tool_call_args():
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="do it"),
        AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [
                    {"id": "1", "name": "write", "args": {"content": "x" * 90}},
                ]
            },
        ),
        ToolMessage(content="ok", tool_call_id="1"),
    ]
    body_only = occupancy_tokens(
        [SystemMessage(content="sys"), HumanMessage(content="do it")]
    )
    full = occupancy_tokens(messages)
    assert full > body_only


def test_microcompact_keeps_humans_and_recent_tool_results():
    messages = [
        HumanMessage(content="build mario"),
        AIMessage(content="", additional_kwargs={"tool_calls": [{"id": "a"}]}),
        ToolMessage(content="old ls output " * 20, tool_call_id="a"),
        HumanMessage(content="continue"),
        AIMessage(content="", additional_kwargs={"tool_calls": [{"id": "b"}]}),
        ToolMessage(content="new write output", tool_call_id="b"),
        ToolMessage(content="newest view output", tool_call_id="c"),
    ]
    out, telemetry = microcompact_messages(messages, keep_recent=2)
    assert telemetry["tombstoned"] == 1
    humans = [m.content for m in out if getattr(m, "type", None) == "human"]
    assert humans == ["build mario", "continue"]
    tools = [m for m in out if getattr(m, "type", None) == "tool"]
    assert tools[0].content == TOOL_RESULT_TOMBSTONE
    assert tools[1].content == "new write output"
    assert tools[2].content == "newest view output"
    assert any(getattr(m, "additional_kwargs", {}).get("tool_calls") for m in out)


def test_run_compaction_ladder_skips_below_window_minus_reserved():
    from RxyCode.RxyCode1_1_0.core.compaction import run_compaction_ladder

    messages = [HumanMessage(content="hello"), AIMessage(content="ok")]
    out, tel = run_compaction_ladder(
        messages,
        occupancy=12_000,
        context_window=100_000,
        reserved=20_000,
    )
    assert tel["did_compact"] is False
    assert tel["usable"] == 80_000
    assert tel["rung"] == "none"
    assert out[0].content == "hello"


def test_run_compaction_ladder_force_runs_when_small():
    from RxyCode.RxyCode1_1_0.core.compaction import run_compaction_ladder

    messages = [
        HumanMessage(content="build it"),
        AIMessage(content="", additional_kwargs={"tool_calls": [{"id": "a"}]}),
        ToolMessage(content="old ls output " * 20, tool_call_id="a"),
        HumanMessage(content="continue"),
        AIMessage(content="", additional_kwargs={"tool_calls": [{"id": "b"}]}),
        ToolMessage(content="new write output", tool_call_id="b"),
    ]
    out, tel = run_compaction_ladder(
        messages,
        force=True,
        occupancy=100,
        context_window=100_000,
        reserved=20_000,
    )
    assert tel["force"] is True
    assert tel["rung"] in {"microcompact", "fold"}
    assert any(
        getattr(m, "content", "") == TOOL_RESULT_TOMBSTONE
        or "old ls output" not in str(getattr(m, "content", ""))
        for m in out
    )
