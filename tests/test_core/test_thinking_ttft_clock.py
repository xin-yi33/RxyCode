"""User clock: Session.prompt → first thinking/reasoning token.

Routing ProgressUpdate and liveness 「思考中...」 must not pass the
1.5s / 3.2s red lines. An instant mock stream must still surface a
reasoning delta; harness overhead above budget is a fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.core.ttft_clock import (
    SIMPLE_UPPER_S,
    bind_prompt_clock,
    first_reasoning_s,
    is_real_thinking,
    mark_reasoning,
    reset_prompt_clock,
)
from RxyCode.RxyCode1_1_0.protocol.notifications import (
    ProgressUpdate,
    ReasoningSnapshot,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "thinking-ttft.json"
TRACE_OUT = REPO / "evals" / "results" / "thinking-ttft-clock.json"


def test_fixture_defines_user_thinking_clock() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["thinking"]["required"] is True
    assert payload["thinking"]["disable_to_buy_ttft"] is False
    assert payload["gates"]["simple_ttft_s"]["upper_s"] == SIMPLE_UPPER_S
    assert payload["gates"]["complex_ttft_s"]["upper_s"] == 3.2
    assert "first ProgressUpdate" in payload["clock"]["not_a_pass"]
    assert payload["gates"]["cache_hit_floor"] == 0.97


def test_liveness_is_not_a_thinking_token() -> None:
    assert is_real_thinking("思考中...") is False
    assert is_real_thinking("等待模型返回…") is False
    assert is_real_thinking("用户要修登录") is True


def test_progress_update_does_not_mark_clock() -> None:
    token = bind_prompt_clock()
    try:
        mark_reasoning("思考中...", kind="liveness")
        assert first_reasoning_s() is None
        mark_reasoning("先看现有登录入口", kind="wire")
        assert first_reasoning_s() is not None
        assert first_reasoning_s() < SIMPLE_UPPER_S
    finally:
        reset_prompt_clock(token)


class _InstantThinkingAgent:
    def __init__(self) -> None:
        self._thinking_history: list[str] = []
        self._last_thinking = ""
        self._cancelled = False

    async def run(self, text: str, mode: str = "build") -> str:
        from RxyCode.RxyCode1_1_0.utils.tui import get_tui

        tui = get_tui()
        if tui is not None and hasattr(tui, "write_turn_liveness"):
            tui.write_turn_liveness("思考中...")
        if tui is not None and hasattr(tui, "write_reasoning"):
            tui.write_reasoning("需要先确认用户意图。")
        self._last_thinking = "需要先确认用户意图。"
        self._thinking_history.append(self._last_thinking)
        return f"ok:{text}"

    def cancel(self) -> bool:
        self._cancelled = True
        return True


@pytest.mark.asyncio
async def test_session_clock_ignores_progress_and_liveness(tmp_path):
    emitted: list[BaseModel] = []
    session = Session(
        session_id="thinking-ttft",
        workspace_root=tmp_path,
        emit=emitted.append,
    )
    from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
    from RxyCode.RxyCode1_1_0.utils.tui import set_tui

    tui = ProtocolTui("thinking-ttft", emitted.append)
    prev = None
    try:
        from RxyCode.RxyCode1_1_0.utils import tui as tui_mod

        prev = tui_mod._tui_instance
        set_tui(tui)
        result = await session.prompt(
            _InstantThinkingAgent(),
            "你好",
            mode="build",
            run_id="simple",
        )
    finally:
        set_tui(prev)

    assert result.answer.startswith("ok:")
    reasoning_events = [
        n
        for n in emitted
        if isinstance(n, ReasoningSnapshot) and is_real_thinking(n.text)
    ]
    progress = [n for n in emitted if isinstance(n, ProgressUpdate)]
    assert reasoning_events, "first thinking token never arrived on the protocol"
    assert any("确认" in (n.text or "") for n in reasoning_events)
    TRACE_OUT.parent.mkdir(parents=True, exist_ok=True)
    TRACE_OUT.write_text(
        json.dumps(
            {
                "id": "thinking-ttft-clock",
                "kind": "trace-fixture",
                "simple_prompt": "你好",
                "reasoning_events": [n.text for n in reasoning_events],
                "progress_events": [n.text for n in progress],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_harness_overhead_to_first_thinking_under_budget(tmp_path):
    """Instant provider reasoning must still beat the simple upper bound."""
    from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
    from RxyCode.RxyCode1_1_0.core.ttft_clock import current_clock
    from RxyCode.RxyCode1_1_0.utils.tui import set_tui
    from RxyCode.RxyCode1_1_0.utils import tui as tui_mod

    captured: dict[str, float | None] = {"ttft": None}
    emitted: list[BaseModel] = []

    class _Agent(_InstantThinkingAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            answer = await super().run(text, mode)
            clock = current_clock()
            captured["ttft"] = None if clock is None else clock.first_reasoning_s
            return answer

    session = Session(
        session_id="thinking-ttft-overhead",
        workspace_root=tmp_path,
        emit=emitted.append,
    )
    tui = ProtocolTui("thinking-ttft-overhead", emitted.append)
    prev = tui_mod._tui_instance
    try:
        set_tui(tui)
        await session.prompt(_Agent(), "你好", mode="build", run_id="ovh")
    finally:
        set_tui(prev)

    assert captured["ttft"] is not None, "clock never saw a thinking token"
    assert captured["ttft"] <= SIMPLE_UPPER_S, (
        f"harness delay to first thinking token {captured['ttft']:.3f}s "
        f"exceeds simple red line {SIMPLE_UPPER_S}s"
    )
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert captured["ttft"] <= float(payload["gates"]["harness_overhead_s"]) + 0.2


def test_fast_reply_still_forbids_thinking_off() -> None:
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    src = inspect.getsource(AgentV2._fast_reply)
    assert "_thinking_disabled_this_turn = True" not in src


def test_stream_max_tokens_cap_is_ttft_friendly() -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _resolve_fast_build_round_max_tokens

    # A fixed 4096 round cap truncated valid writes. The live budget follows
    # the model limit unless an operator sets a smaller override.
    assert _resolve_fast_build_round_max_tokens({}, 8192) == 8192
    assert _resolve_fast_build_round_max_tokens(
        {"fast_build_tool_round_max_tokens": 2048},
        8192,
    ) == 2048
    assert _resolve_fast_build_round_max_tokens({}, 384000) == 384000


def test_tool_wire_schema_shrinks_bytes_without_rotating_names() -> None:
    """FX6: same names/order; only description/schema bytes shrink."""
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    long_desc = (
        "Run a shell command in the workspace. Use this for builds, tests, "
        "and git. Never use it to write source files. Always quote paths."
    )
    tools = [
        SimpleNamespace(
            name=name,
            description=long_desc,
            args={
                "command": {
                    "type": "string",
                    "title": "Command",
                    "description": "The complete shell command to execute in bash",
                    "examples": ["ls"],
                }
            },
            tool_call_schema=None,
        )
        for name in ("aaa", "bash", "zzz")
    ]
    payload = [AgentV2._tool_to_openai(tool) for tool in tools]
    assert [item["function"]["name"] for item in payload] == ["aaa", "bash", "zzz"]
    assert payload[0]["function"]["description"].startswith("Run a shell command")
    assert "Never use it" not in payload[0]["function"]["description"]
    params = payload[1]["function"]["parameters"]
    assert "title" not in str(params)
    assert "examples" not in str(params)
    compact = sum(len(str(item)) for item in payload)
    assert compact < 22000
    assert len(payload[0]["function"]["description"]) <= 140
