import pytest
from pathlib import Path
from pydantic import BaseModel

from core.session import (
    PromptResult,
    Session,
    notification_to_sse_event,
    thinking_cursor,
    thinking_since,
)
from protocol.notifications import ErrorNotification, FinalAnswer, TokenUsage
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats


@pytest.fixture
def session_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


class _FakeAgent:
    def __init__(self, answer: str = "ok", *, fail: bool = False):
        self._answer = answer
        self._fail = fail
        self._cancelled = False
        self._thinking_history: list[str] = []
        self._last_thinking = ""

    async def run(self, text: str, mode: str = "build") -> str:
        if self._fail:
            raise RuntimeError("boom")
        return self._answer

    def cancel(self) -> bool:
        self._cancelled = True
        return True


class _UsageAgent(_FakeAgent):
    async def run(self, text: str, mode: str = "build") -> str:
        token_stats.add_real_usage(100, 25, cache_read_tokens=40)
        return await super().run(text, mode)


class _MixedChildUsageAgent(_FakeAgent):
    async def run(self, text: str, mode: str = "build") -> str:
        token_stats.add_real_usage(1000, 0, cache_read_tokens=970)
        scope_token, _scoped = token_stats.begin_usage_scope()
        try:
            token_stats.add_real_usage(5000, 0, cache_read_tokens=100)
        finally:
            token_stats.end_usage_scope(scope_token)
        return await super().run(text, mode)


@pytest.mark.asyncio
async def test_session_prompt_why_mode_does_not_call_agent(session_workspace):
    emitted: list[BaseModel] = []
    session = Session(
        session_id="s-why",
        workspace_root=session_workspace,
        emit=emitted.append,
    )
    agent = _FakeAgent("should-not-run")
    result = await session.prompt(agent, "/why-mode", mode="build", run_id="run-why")
    assert result.status == "succeeded"
    assert "routing" in result.answer or "mode=" in result.answer or "no routing" in result.answer
    assert agent._answer == "should-not-run"


@pytest.mark.asyncio
async def test_session_prompt_team_slash_runs_coordinator_not_agent(session_workspace, monkeypatch):
    emitted: list[BaseModel] = []
    session = Session(
        session_id="s-team",
        workspace_root=session_workspace,
        emit=emitted.append,
    )
    called: list[str] = []

    class _Coord:
        def __init__(self, *_a, **_k):
            pass

        async def run_team(self, team, user_input, **_k):
            called.append(f"{team.name}:{user_input}")
            return "team-ok"

    monkeypatch.setattr("core.session.Coordinator", _Coord)
    agent = _FakeAgent("solo-should-not-run")
    result = await session.prompt(
        agent,
        "/team add a health endpoint in app.py",
        mode="build",
        run_id="run-team",
    )
    assert result.status == "succeeded"
    assert result.answer == "team-ok"
    assert called == ["software_dev:add a health endpoint in app.py"]


@pytest.mark.asyncio
async def test_approved_plan_implement_skips_expert_team(session_workspace, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-ap"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-ap").mkdir()
    save_config({"agents": {"enabled": True, "team": "software_dev", "route_mode": "team"}})

    class _Coord:
        def __init__(self, *_a, **_k):
            raise AssertionError("approved plan must not start expert team")

        async def run_team(self, *_a, **_k):
            raise AssertionError("run_team")

    monkeypatch.setattr("core.session.Coordinator", _Coord)
    ran: list[tuple[str, str]] = []

    class _Tracking(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            ran.append((text.startswith("按已批准的计划开始实施"), mode))
            return "building"

    session = Session(
        session_id="s-ap",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    text = "按已批准的计划开始实施，不要重新规划。\n\n# Todo\n实现 frontend 与 backend"
    result = await session.prompt(_Tracking(), text, mode="build", run_id="run-ap")
    assert result.answer == "building"
    assert ran == [(True, "build")]


@pytest.mark.asyncio
async def test_session_prompt_disabled_keeps_split_prompt_on_solo_agent(
    session_workspace, monkeypatch
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-off"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-off").mkdir()
    save_config({"agents": {"enabled": False, "team": "software_dev", "route_mode": "auto"}})
    ran: list[str] = []

    class _Tracking(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            ran.append(text)
            return "solo"

    session = Session(
        session_id="s-off",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    result = await session.prompt(
        _Tracking(),
        "把前后端拆成两个独立改造再多人审计",
        mode="build",
        run_id="run-off",
    )
    assert result.answer == "solo"
    assert ran == ["把前后端拆成两个独立改造再多人审计"]


@pytest.mark.asyncio
async def test_session_prompt_disabled_skips_router_and_coordinator(
    session_workspace, monkeypatch
):
    """CI stub prompts (hang:/slow:) must not pay ModeRouter/Coordinator cost."""
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-skip"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-skip").mkdir()
    save_config({"agents": {"enabled": False}})

    def _boom(*_a, **_k):
        raise AssertionError("ModeRouter must not run when agents.enabled=false")

    monkeypatch.setattr("core.session.get_default_router", _boom)
    monkeypatch.setattr("core.session.Coordinator", _boom)
    ran: list[str] = []

    class _Tracking(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            ran.append(text)
            return "hung-ok"

    session = Session(
        session_id="s-skip",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    result = await session.prompt(
        _Tracking(),
        "hang:forever",
        mode="build",
        run_id="run-skip",
    )
    assert result.answer == "hung-ok"
    assert ran == ["hang:forever"]


@pytest.mark.asyncio
async def test_session_nl_open_team_runs_coordinator_when_disabled(
    session_workspace, monkeypatch
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-nl-team"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-nl-team").mkdir()
    save_config({"agents": {"enabled": False, "team": "software_dev", "route_mode": "auto"}})
    called: list[str] = []

    class _Coord:
        def __init__(self, *_a, **_k):
            pass

        async def run_team(self, team, user_input, **_k):
            called.append(user_input)
            return "team-nl-ok"

    monkeypatch.setattr("core.session.Coordinator", _Coord)
    session = Session(
        session_id="s-nl-team",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    result = await session.prompt(
        _FakeAgent("solo-should-not-run"),
        "开专家团 实现登录前后端",
        mode="build",
        run_id="run-nl-team",
    )
    assert result.answer == "team-nl-ok"
    assert called == ["实现登录前后端"]


@pytest.mark.asyncio
async def test_session_nl_explore_dispatches_explore(session_workspace, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-nl-ex"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-nl-ex").mkdir()
    save_config({"agents": {"enabled": True, "route_mode": "auto"}})
    seen: list[str] = []

    async def _fake_explore(prompt: str) -> str:
        seen.append(prompt)
        return "explore-ok"

    session = Session(
        session_id="s-nl-ex",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    monkeypatch.setattr(session, "_run_explore", _fake_explore)
    result = await session.prompt(
        _FakeAgent("solo-should-not-run"),
        "查找认证模块在哪个文件",
        mode="build",
        run_id="run-nl-ex",
    )
    assert result.answer == "explore-ok"
    assert seen == ["查找认证模块在哪个文件"]


@pytest.mark.asyncio
async def test_session_open_notes_preview_stays_solo(session_workspace, monkeypatch):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-open-notes"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-open-notes").mkdir()
    save_config({"agents": {"enabled": True, "route_mode": "auto"}})
    explore_calls: list[str] = []

    async def _fake_explore(prompt: str) -> str:
        explore_calls.append(prompt)
        return "explore-should-not-run"

    session = Session(
        session_id="s-open-notes",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    monkeypatch.setattr(session, "_run_explore", _fake_explore)
    agent = _FakeAgent("opened-notes")
    result = await session.prompt(
        agent,
        "当前目录已经有 notes.md。请用系统默认程序打开 notes.md 给我预览。"
        "成功后立刻最终回答，写明工具名和返回原文。不要等我关闭 Typora/记事本。"
        "不要改文件内容",
        mode="build",
        run_id="run-open-notes",
    )
    assert result.answer == "opened-notes"
    assert explore_calls == []


@pytest.mark.asyncio
async def test_session_opt_in_subagents_persists_and_unhides_task(
    session_workspace, monkeypatch
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(session_workspace / "data-opt"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (session_workspace / "data-opt").mkdir()
    save_config({"agents": {"enabled": False}})
    ran: list[str] = []

    class _Tracking(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            ran.append(text)
            return "solo"

    agent = _Tracking()
    session = Session(
        session_id="s-opt",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    first = await session.prompt(agent, "用子代理", mode="build", run_id="run-opt-1")
    assert "打开子代理" in first.answer
    assert session._session_subagents_opt_in is True
    second = await session.prompt(agent, "修一下 foo.py", mode="build", run_id="run-opt-2")
    assert second.answer == "solo"
    assert ran == ["修一下 foo.py"]
    assert getattr(agent, "_session_subagents_opt_in", False) is True


@pytest.mark.asyncio
async def test_session_prompt_emits_final_answer(session_workspace):
    emitted: list[BaseModel] = []
    session = Session(
        session_id="s1",
        workspace_root=session_workspace,
        emit=emitted.append,
        session_schema_version=3,
    )
    result = await session.prompt(
        _FakeAgent("hello"),
        "hi",
        mode="build",
        run_id="run-1",
    )
    assert result.status == "succeeded"
    assert result.answer == "hello"
    assert any(isinstance(item, FinalAnswer) for item in emitted)
    final = next(item for item in emitted if isinstance(item, FinalAnswer))
    assert final.text == "hello"
    assert final.run_id == "run-1"
    assert final.input_tokens is None
    assert final.output_tokens is None
    assert final.reporting_status == "not_reported"


@pytest.mark.asyncio
async def test_session_prompt_forwards_provider_cache_usage_for_this_turn(
    session_workspace,
):
    """Desktop reports require a per-turn provider-cache metric, not globals."""
    token_stats.reset()
    try:
        emitted: list[BaseModel] = []
        session = Session(
            session_id="s-cache",
            workspace_root=session_workspace,
            emit=emitted.append,
        )

        result = await session.prompt(_UsageAgent("cached"), "hi", mode="build", run_id="run-cache")

        usage = next(item for item in emitted if isinstance(item, TokenUsage))
        assert result.cache_hit_tokens == 40
        assert result.cache_hit_rate == 40.0
        assert usage.cache_hit_tokens == 40
        assert usage.cache_hit_rate == 40.0
    finally:
        token_stats.reset()


@pytest.mark.asyncio
async def test_session_prompt_excludes_child_cache_from_primary(session_workspace):
    """event/final P6 is Primary-only; mixing Child 68% must not be reported."""
    token_stats.reset()
    try:
        emitted: list[BaseModel] = []
        session = Session(
            session_id="s-p6",
            workspace_root=session_workspace,
            emit=emitted.append,
        )
        result = await session.prompt(
            _MixedChildUsageAgent("ok"),
            "hi",
            mode="build",
            run_id="run-p6",
        )
        usage = next(item for item in emitted if isinstance(item, TokenUsage))
        assert result.input_tokens == 1000
        assert result.cache_hit_tokens == 970
        assert result.cache_hit_rate == pytest.approx(97.0)
        assert usage.input_tokens == 1000
        assert usage.cache_hit_tokens == 970
        assert usage.cache_hit_rate == pytest.approx(97.0)
    finally:
        token_stats.reset()


@pytest.mark.asyncio
async def test_session_prompt_emits_error_on_exception(session_workspace):
    emitted: list[BaseModel] = []
    session = Session(session_id="s1", workspace_root=session_workspace, emit=emitted.append)
    result = await session.prompt(
        _FakeAgent(fail=True),
        "hi",
        mode="build",
        run_id="run-2",
    )
    assert result.status == "failed"
    assert any(isinstance(item, ErrorNotification) for item in emitted)


class _StreamedTui:
    _streamed_answer_chars = 400

    def resolve_active_recovery(self) -> None:
        return None

    def exhaust_active_recovery(self, detail: str) -> None:
        return None


@pytest.mark.asyncio
async def test_session_prompt_occupancy_ignores_cached_prompt_tokens(session_workspace):
    token_stats.reset()
    try:
        emitted: list[BaseModel] = []
        session = Session(
            session_id="s-occ",
            workspace_root=session_workspace,
            emit=emitted.append,
        )

        class _OccAgent(_FakeAgent):
            async def run(self, text: str, mode: str = "build") -> str:
                token_stats.add_real_usage(208248, 1729, cache_read_tokens=205696)
                token_stats._latest_prompt_tokens = 2_284_300
                token_stats.update_context(23418, 1048576)
                return "ok"

        result = await session.prompt(
            _OccAgent("ok"),
            "hi",
            mode="build",
            run_id="run-occ",
        )
        usage = next(item for item in emitted if isinstance(item, TokenUsage))
        assert result.status == "succeeded"
        assert usage.context_used == 23418
        assert result.context_used == 23418
        assert result.input_tokens == 208248
        assert usage.input_tokens == 208248
        assert usage.input_tokens != usage.context_used
    finally:
        token_stats.reset()


@pytest.mark.asyncio
async def test_session_prompt_skips_default_error_after_streamed_answer(session_workspace):
    emitted: list[BaseModel] = []
    session = Session(
        session_id="s-stream",
        workspace_root=session_workspace,
        emit=emitted.append,
    )
    tui = _StreamedTui()

    class _StreamAgent(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            tui._streamed_answer_chars = 400
            return self._answer

    result = await session.prompt(
        _StreamAgent(
            "[error: execution stopped after a side-effecting tool was attempted. Detail: boom]"
        ),
        "hi",
        mode="build",
        run_id="run-stream",
        tui=tui,
    )
    assert result.status == "succeeded"
    assert not any(isinstance(item, ErrorNotification) for item in emitted)


@pytest.mark.asyncio
async def test_session_prompt_timeout_emits_event_error(session_workspace):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import FirstTokenTimeoutError
    from RxyCode.RxyCode1_1_0.utils.user_facing_errors import MSG_TIMEOUT

    class _TimeoutAgent(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            raise FirstTokenTimeoutError("provider produced no first response")

    emitted: list[BaseModel] = []
    session = Session(
        session_id="s-timeout",
        workspace_root=session_workspace,
        emit=emitted.append,
    )
    result = await session.prompt(_TimeoutAgent(), "hi", mode="build", run_id="run-t")
    assert result.status == "failed"
    errors = [item for item in emitted if isinstance(item, ErrorNotification)]
    assert errors
    assert errors[0].message == MSG_TIMEOUT


@pytest.mark.asyncio
async def test_session_prompt_429_emits_error_only_when_exhausted(session_workspace):
    emitted: list[BaseModel] = []
    session = Session(
        session_id="s-429",
        workspace_root=session_workspace,
        emit=emitted.append,
    )

    class _RateAgent(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            resp = __import__("httpx").Response(
                429, request=__import__("httpx").Request("POST", "http://x")
            )
            raise __import__("httpx").HTTPStatusError(
                "rate", request=resp.request, response=resp
            )

    result = await session.prompt(_RateAgent(), "hi", mode="build", run_id="run-429")
    assert result.status == "failed"
    assert any(isinstance(item, ErrorNotification) for item in emitted)


def test_notification_to_sse_event_maps_final():
    event = notification_to_sse_event(
        FinalAnswer(
            session_id="s1",
            run_id="run-1",
            text="answer",
            thinking="thought",
            input_tokens=1,
            output_tokens=2,
            session_schema_version=3,
        )
    )
    assert event == {
        "type": "final",
        "run_id": "run-1",
        "text": "answer",
        "thinking": "thought",
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_hit_tokens": None,
        "cache_hit_rate": None,
        "session_schema_version": 3,
    }


def test_notification_to_sse_event_preserves_unreported_usage_as_null():
    event = notification_to_sse_event(
        FinalAnswer(
            session_id="s1",
            run_id="run-unreported",
            text="answer",
            input_tokens=None,
            output_tokens=None,
            cache_hit_tokens=None,
            cache_hit_rate=None,
            reporting_status="not_reported",
        )
    )

    assert event is not None
    assert event["input_tokens"] is None
    assert event["output_tokens"] is None
    assert event["cache_hit_tokens"] is None
    assert event["cache_hit_rate"] is None


def test_session_interrupt_delegates_to_agent():
    agent = _FakeAgent()
    session = Session(session_id="s1", workspace_root=Path("."), emit=lambda _: None)
    assert session.interrupt(agent) is True
    assert agent._cancelled is True


def test_reuse_or_create_session_keeps_agent_runtimes(session_workspace):
    """F14: warmup then H3 must not drop per-role AgentRuntime / AgentPrefix."""
    from core.session import reuse_or_create_session

    first_emit: list = []
    first = reuse_or_create_session(
        None,
        session_id="ses-h3",
        workspace_root=session_workspace,
        emit=first_emit.append,
    )
    marker = object()
    first.agent_runtimes["backend_coder"] = marker
    second_emit: list = []
    second = reuse_or_create_session(
        first,
        session_id="ses-h3",
        workspace_root=session_workspace,
        emit=second_emit.append,
    )
    assert second is first
    assert second.agent_runtimes["backend_coder"] is marker
    second.emit("keep")
    assert second_emit == ["keep"]


def test_reuse_or_create_session_new_id_is_fresh(session_workspace):
    from core.session import reuse_or_create_session

    first = reuse_or_create_session(
        None,
        session_id="ses-a",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    first.agent_runtimes["architect"] = object()
    second = reuse_or_create_session(
        first,
        session_id="ses-b",
        workspace_root=session_workspace,
        emit=lambda _n: None,
    )
    assert second is not first
    assert second.agent_runtimes == {}


@pytest.mark.asyncio
async def test_session_prompt_binds_workspace_for_tools(session_workspace):
    """HTTP /chat must not write into the installed package tree."""
    from RxyCode.RxyCode1_1_0.core.session_runtime import current_working_directory

    seen: dict[str, Path] = {}

    class _CwdAgent(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            seen["cwd"] = current_working_directory()
            return await super().run(text, mode)

    session = Session(session_id="ws-bind", workspace_root=session_workspace, emit=lambda _: None)
    result = await session.prompt(_CwdAgent("ok"), "write hello", mode="build", run_id="run-ws")
    assert result.status == "succeeded"
    assert seen["cwd"] == session_workspace.resolve()


def test_thinking_since_returns_delta():
    agent = _FakeAgent()
    agent._thinking_history = ["a"]
    cursor = thinking_cursor(agent)
    agent._thinking_history = ["a", "b"]
    assert thinking_since(agent, cursor) == "b"
