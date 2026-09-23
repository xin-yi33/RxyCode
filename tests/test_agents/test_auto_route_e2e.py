"""Overall auto-route eval: typed user prompts, dispatch, /why-mode traces.

This is the agent-quality gate for solo / expert-team / explore. Unit
ModeRouter cases live in test_router.py; this file asserts the Session
execution record (path taken, builtin explore dispatch, why-mode).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.agents.router import ExecutionMode, ModeRouter
from RxyCode.RxyCode1_1_0.core.prefix_profile import digest_tools
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent, ProgressUpdate

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "auto-route-explore-team.json"
TRACE_OUT = REPO / "evals" / "results" / "auto-route-session-trace.json"

SIMPLE_TTFT_S = 1.0
SIMPLE_TOL_S = 0.5
COMPLEX_TTFT_S = 3.0
COMPLEX_TOL_S = 0.2


class _FakeAgent:
    def __init__(self) -> None:
        self.ran: list[str] = []
        self._cancelled = False
        self._thinking_history: list[str] = []
        self._last_thinking = ""
        self._session_subagents_opt_in = False

    async def run(self, text: str, mode: str = "build") -> str:
        self.ran.append(text)
        return f"solo:{text}"

    def cancel(self) -> bool:
        self._cancelled = True
        return True


class _Clock:
    def __init__(self) -> None:
        self.first_meaningful_s: float | None = None
        self._t0 = 0.0

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self.first_meaningful_s = None

    def mark(self) -> None:
        if self.first_meaningful_s is None:
            self.first_meaningful_s = time.perf_counter() - self._t0


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _session(workspace, emit=None) -> Session:
    return Session(
        session_id="auto-route-e2e",
        workspace_root=workspace,
        emit=emit or (lambda _n: None),
    )


def _enable_agents(workspace, monkeypatch, enabled: bool) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(workspace / "data-route"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config

    (workspace / "data-route").mkdir(exist_ok=True)
    save_config({"agents": {"enabled": enabled, "team": "software_dev", "route_mode": "auto"}})


def test_fixture_router_cases_still_match() -> None:
    payload = _load_fixture()
    router = ModeRouter(enabled=True)
    for case in payload["required_after"]["cases"]:
        decision = router.route(case["prompt"])
        assert decision.mode is ExecutionMode(case["mode"]), case
        if "decided_by" in case:
            assert decision.decided_by == case["decided_by"], case
        why = router.handle_slash("/why-mode")
        assert f"mode={case['mode']}" in why


@pytest.mark.asyncio
async def test_typed_prompts_dispatch_explore_team_solo(tmp_path, monkeypatch):
    """Simulated user: type prompts into Session (the appserver/OpenTUI façade)."""
    payload = _load_fixture()
    _enable_agents(tmp_path, monkeypatch, True)
    explore_calls: list[dict[str, str]] = []
    team_calls: list[str] = []
    traces: list[dict] = []

    async def fake_dispatch(*, agent_id: str, prompt: str, description: str = "", **_k) -> str:
        explore_calls.append({"agent_id": agent_id, "prompt": prompt, "description": description})
        return f"explore:{prompt}"

    class _Coord:
        def __init__(self, *_a, **_k):
            pass

        async def run_team(self, team, user_input, **_k):
            team_calls.append(f"{team.name}:{user_input}")
            return f"team:{user_input}"

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.subagent_task_tool.dispatch_subagent_task",
        fake_dispatch,
    )
    monkeypatch.setattr("core.session.Coordinator", _Coord)
    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.core.session.Coordinator",
        _Coord,
    )

    emitted: list[BaseModel] = []
    session = _session(tmp_path, emitted.append)
    agent = _FakeAgent()
    clock = _Clock()
    simple_ttft: list[float] = []
    complex_ttft: list[float] = []

    async def _turn(prompt: str) -> str:
        clock.start()

        def emit(n: BaseModel) -> None:
            emitted.append(n)
            if isinstance(n, (ProgressUpdate, AgentEvent)):
                clock.mark()

        session.emit = emit
        result = await session.prompt(agent, prompt, mode="build", run_id=f"run-{len(traces)}")
        clock.mark()
        return result.answer

    for spec in payload["required_after"]["session_dispatch"]:
        if spec.get("agents_enabled") is False:
            continue
        if spec.get("setup"):
            continue
        explore_calls.clear()
        team_calls.clear()
        agent.ran.clear()
        answer = await _turn(spec["prompt"])
        why = await session.prompt(agent, "/why-mode", mode="build", run_id="why")
        path = spec["path"]
        if path == "explore":
            assert explore_calls, spec
            assert explore_calls[0]["agent_id"] == "explore"
            assert explore_calls[0]["prompt"] == spec["prompt"]
            assert explore_calls[0]["description"] != "explore codebase"
            assert not agent.ran
            assert not team_calls
            assert answer.startswith("explore:")
            complex_ttft.append(clock.first_meaningful_s or 0.0)
        elif path == "team":
            assert team_calls == [f"software_dev:{spec['prompt']}"]
            assert not explore_calls
            assert not agent.ran
            assert answer.startswith("team:")
            complex_ttft.append(clock.first_meaningful_s or 0.0)
        else:
            assert agent.ran == [spec["prompt"]]
            assert not explore_calls
            assert not team_calls
            simple_ttft.append(clock.first_meaningful_s or 0.0)
        if spec.get("why_contains"):
            assert spec["why_contains"] in why.answer
        traces.append(
            {
                "prompt": spec["prompt"],
                "path": path,
                "why": why.answer,
                "ttft_s": clock.first_meaningful_s,
                "answer_prefix": answer[:40],
            }
        )

    TRACE_OUT.parent.mkdir(parents=True, exist_ok=True)
    TRACE_OUT.write_text(
        json.dumps(
            {
                "id": "auto-route-session-trace",
                "kind": "trace-fixture",
                "source": "tests/test_agents/test_auto_route_e2e.py",
                "turns": traces,
                "simple_ttft_s": simple_ttft,
                "complex_ttft_s": complex_ttft,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert simple_ttft
    assert complex_ttft
    assert max(simple_ttft) <= SIMPLE_TTFT_S + SIMPLE_TOL_S
    assert max(complex_ttft) <= COMPLEX_TTFT_S + COMPLEX_TOL_S


@pytest.mark.asyncio
async def test_product_default_explore_after_subagent_opt_in(tmp_path, monkeypatch):
    """DC7 off: 查代码 stays solo until 用子代理; then explore actually dispatches."""
    _enable_agents(tmp_path, monkeypatch, False)
    seen: list[str] = []

    async def fake_explore(prompt: str) -> str:
        seen.append(prompt)
        return "explore-ok"

    session = _session(tmp_path)
    monkeypatch.setattr(session, "_run_explore", fake_explore)
    agent = _FakeAgent()

    skipped = await session.prompt(
        agent, "查找认证模块在哪个文件", mode="build", run_id="skip"
    )
    assert skipped.answer.startswith("solo:")
    assert seen == []

    opted = await session.prompt(agent, "用子代理", mode="build", run_id="opt")
    assert "打开子代理" in opted.answer

    dispatched = await session.prompt(
        agent, "查找认证模块在哪个文件", mode="build", run_id="ex"
    )
    assert dispatched.answer == "explore-ok"
    assert seen == ["查找认证模块在哪个文件"]
    why = await session.prompt(agent, "/why-mode", mode="build", run_id="why")
    assert "mode=explore" in why.answer


@pytest.mark.asyncio
async def test_session_flag_opens_team_without_config(tmp_path, monkeypatch):
    _enable_agents(tmp_path, monkeypatch, False)
    called: list[str] = []

    class _Coord:
        def __init__(self, *_a, **_k):
            pass

        async def run_team(self, team, user_input, **_k):
            called.append(user_input)
            return "team-ok"

    monkeypatch.setattr("core.session.Coordinator", _Coord)
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.core.session.Coordinator", _Coord)
    session = _session(tmp_path)
    agent = _FakeAgent()
    persist = await session.prompt(agent, "开专家团", mode="build", run_id="flag")
    assert persist.answer != "team-ok"
    assert "专家团" in persist.answer
    assert called == []
    result = await session.prompt(
        agent,
        "实现一个完整的登录功能，前后端都要",
        mode="build",
        run_id="feat",
    )
    assert result.answer == "team-ok"
    assert called == ["实现一个完整的登录功能，前后端都要"]
    why = await session.prompt(agent, "/why-mode", mode="build", run_id="why")
    assert "mode=team" in why.answer
    assert not agent.ran[-1:] or agent.ran[-1] != "实现一个完整的登录功能，前后端都要"


@pytest.mark.asyncio
async def test_slash_explore_calls_builtin_dispatch(tmp_path, monkeypatch):
    _enable_agents(tmp_path, monkeypatch, False)
    seen: list[dict] = []

    async def fake_dispatch(*, agent_id: str, prompt: str, description: str = "", **_k) -> str:
        seen.append({"agent_id": agent_id, "prompt": prompt})
        return "ok"

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.subagent_task_tool.dispatch_subagent_task",
        fake_dispatch,
    )
    session = _session(tmp_path)
    result = await session.prompt(
        _FakeAgent(), "/explore 认证模块在哪", mode="build", run_id="slash-ex"
    )
    assert result.answer == "explore:认证模块在哪" or result.answer == "ok"
    assert seen == [{"agent_id": "explore", "prompt": "认证模块在哪"}]


@pytest.mark.asyncio
async def test_routing_ttft_within_r6_envelope(tmp_path, monkeypatch):
    _enable_agents(tmp_path, monkeypatch, True)
    session = _session(tmp_path)
    monkeypatch.setattr(session, "_run_explore", fake_async("ex"))
    agent = _FakeAgent()

    t0 = time.perf_counter()
    await session.prompt(agent, "你好", mode="build", run_id="simple")
    simple = time.perf_counter() - t0

    t1 = time.perf_counter()
    await session.prompt(agent, "查代码", mode="build", run_id="complex")
    complex_s = time.perf_counter() - t1

    assert simple <= SIMPLE_TTFT_S + SIMPLE_TOL_S
    assert complex_s <= COMPLEX_TTFT_S + COMPLEX_TOL_S
    assert simple < 0.5, f"routing+solo first path too slow: {simple:.3f}s"
    assert complex_s < 0.5, f"explore dispatch too slow: {complex_s:.3f}s"


def fake_async(value: str):
    async def _inner(prompt: str) -> str:
        return value

    return _inner


def _tool(name: str):
    return SimpleNamespace(name=name)


def _prefix_agent(*, subagents: bool, opt_in: bool, names: tuple[str, ...]) -> AgentV2:
    agent = object.__new__(AgentV2)
    agent._subagents_enabled = subagents
    agent._session_subagents_opt_in = opt_in
    agent._capabilities = None
    agent._memory = SimpleNamespace(_rag_enabled=False)
    tools = [_tool(n) for n in names]
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: {t.name: t for t in tools})
    return agent


def test_prefix_tools_digest_stable_across_solo_prompts() -> None:
    """R7: greeting vs single-file bugfix must not rotate AgentPrefix tools."""
    agent = _prefix_agent(
        subagents=True,
        opt_in=False,
        names=("write", "task", "read", "bash", "edit"),
    )
    greeting = agent._select_turn_tools(
        agent._get_core_tools(), "你好", requires_web=False, allowed_tool_names=None
    )
    bugfix = agent._select_turn_tools(
        agent._get_core_tools(),
        "修一下 foo.py 里的空指针",
        requires_web=False,
        allowed_tool_names=None,
    )
    names_g = [t.name for t in greeting]
    names_b = [t.name for t in bugfix]
    assert names_g == names_b
    assert names_g == sorted(names_g)
    assert "task" in names_g
    assert digest_tools(greeting) == digest_tools(bugfix)


def test_opt_in_does_not_reorder_tools() -> None:
    agent = _prefix_agent(
        subagents=False,
        opt_in=True,
        names=("write", "task", "read", "bash"),
    )
    selected = agent._select_turn_tools(
        agent._get_core_tools(), "修一下 foo.py", requires_web=False, allowed_tool_names=None
    )
    names = [t.name for t in selected]
    assert names == sorted(names)
    assert "task" in names


@pytest.mark.asyncio
async def test_simulated_user_thread_greeting_explore_team(tmp_path, monkeypatch):
    """Multi-turn simulated user. Checkpoint after every turn (agent-evals thread)."""
    _enable_agents(tmp_path, monkeypatch, True)
    explore_calls: list[str] = []
    team_calls: list[str] = []

    async def fake_dispatch(*, agent_id: str, prompt: str, description: str = "", **_k) -> str:
        explore_calls.append(agent_id)
        return f"explore:{prompt}"

    class _Coord:
        def __init__(self, *_a, **_k):
            pass

        async def run_team(self, team, user_input, **_k):
            team_calls.append(user_input)
            return f"team:{user_input}"

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.subagent_task_tool.dispatch_subagent_task",
        fake_dispatch,
    )
    monkeypatch.setattr("core.session.Coordinator", _Coord)
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.core.session.Coordinator", _Coord)

    emitted: list[BaseModel] = []
    session = _session(tmp_path, emitted.append)
    agent = _FakeAgent()
    clock = _Clock()

    async def _turn(prompt: str) -> str:
        clock.start()

        def emit(n: BaseModel) -> None:
            emitted.append(n)
            if isinstance(n, (ProgressUpdate, AgentEvent)):
                clock.mark()

        session.emit = emit
        result = await session.prompt(agent, prompt, mode="build", run_id=prompt[:12])
        clock.mark()
        return result.answer

    hello = await _turn("你好")
    assert hello.startswith("solo:")
    assert agent.ran == ["你好"]
    assert (clock.first_meaningful_s or 0.0) <= SIMPLE_TTFT_S + SIMPLE_TOL_S
    why = await session.prompt(agent, "/why-mode", mode="build", run_id="why1")
    assert "mode=solo" in why.answer
    assert "greeting" in why.answer

    agent.ran.clear()
    explore = await _turn("查找认证模块在哪个文件")
    assert explore.startswith("explore:")
    assert explore_calls == ["explore"]
    assert not agent.ran
    assert (clock.first_meaningful_s or 0.0) <= COMPLEX_TTFT_S + COMPLEX_TOL_S
    why = await session.prompt(agent, "/why-mode", mode="build", run_id="why2")
    assert "mode=explore" in why.answer

    team = await _turn("实现一个完整的登录功能，前后端都要")
    assert team.startswith("team:")
    assert team_calls == ["实现一个完整的登录功能，前后端都要"]
    assert (clock.first_meaningful_s or 0.0) <= COMPLEX_TTFT_S + COMPLEX_TOL_S
    why = await session.prompt(agent, "/why-mode", mode="build", run_id="why3")
    assert "mode=team" in why.answer
