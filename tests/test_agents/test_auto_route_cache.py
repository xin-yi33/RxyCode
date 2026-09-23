"""R7: auto-route must not bust the Primary 97% prefix cache.

Clock: this file does not measure provider TTFT. It asserts PrefixProfile
identity (thinking ON) and the warm-turn hit-rate model:
  hit = prefix_tokens, input = prefix_tokens + suffix
  rate = hit / input
after prewarm / turn 2+ of a matching identity.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.prefix_profile import PrefixProfile, digest_tools, profiles_compatible
from RxyCode.RxyCode1_1_0.core.prompts.templates import SYSTEM_PROMPT_TEMPLATE
from RxyCode.RxyCode1_1_0.evals.runner import _run_single_check
from RxyCode.RxyCode1_1_0.evals.tasks import Check

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "auto-route-cache-hit.json"
ROUTE_FIXTURE = REPO / "evals" / "baselines" / "auto-route-explore-team.json"
CACHE_FLOOR = 0.97

USER_PROMPTS = (
    "你好",
    "修一下 foo.py 里的空指针",
    "查找认证模块在哪个文件",
    "实现一个完整的登录功能，前后端都要",
)


def _tool(name: str):
    return SimpleNamespace(name=name, args_schema={"type": "object", "properties": {}})


def _agent(*, subagents: bool, opt_in: bool = False) -> AgentV2:
    agent = object.__new__(AgentV2)
    agent._subagents_enabled = subagents
    agent._session_subagents_opt_in = opt_in
    agent._capabilities = None
    agent._memory = SimpleNamespace(_rag_enabled=False)
    names = (
        "write",
        "task",
        "read",
        "bash",
        "edit",
        "grep",
        "glob",
        "ls",
        "git",
        "skill",
        "patch",
        "format",
        "datetime",
        "open_file",
    )
    tools = [_tool(n) for n in names]
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: {t.name: t for t in tools})
    return agent


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8")) // 4)


def _prefix_tokens(tools: list) -> int:
    schema = digest_tools(tools)
    return _estimate_tokens(SYSTEM_PROMPT_TEMPLATE) + _estimate_tokens(schema) + 8000


def _profile(tools_digest: str) -> PrefixProfile:
    return PrefixProfile(
        kind="agent",
        session_id="auto-route-cache",
        provider="stub",
        model="stub",
        thinking_enabled=True,
        thinking_effort="balanced",
        tools_digest=tools_digest,
        s1_digest="s1-frozen",
        system_template_version="v1",
        prompt_variant="default",
    )


def _warm_hit_rate(prefix_tokens: int, suffix_tokens: int) -> float:
    return prefix_tokens / max(prefix_tokens + suffix_tokens, 1)


def test_cache_fixture_floor_is_97() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["gates"]["warm_prefix_hit_floor"] == CACHE_FLOOR
    assert payload["gates"]["thinking_enabled"] is True
    assert payload["product_ttft_conflict"]["cannot_meet_simple_1s_with_thinking"] is True
    route = json.loads(ROUTE_FIXTURE.read_text(encoding="utf-8"))
    assert route["gates"]["cache_hit_floor"] == CACHE_FLOOR


def test_eval_check_cache_hit_floor_97() -> None:
    ok, msg = _run_single_check(
        Check(type="cache_hit_floor", floor=CACHE_FLOOR),
        workdir=None,
        agent_answer="",
        extras={"cache_hit_rate": 0.97},
    )
    assert ok, msg
    fail, _ = _run_single_check(
        Check(type="cache_hit_floor", floor=CACHE_FLOOR),
        workdir=None,
        agent_answer="",
        extras={"cache_hit_rate": 0.91},
    )
    assert not fail


def test_thinking_stays_on_in_prefix_identity() -> None:
    agent = _agent(subagents=True)
    tools = agent._select_turn_tools(
        agent._get_core_tools(), "你好", requires_web=False, allowed_tool_names=None
    )
    profile = _profile(digest_tools(tools))
    assert profile.thinking_enabled is True
    assert "|on|" in profile.identity()


def test_user_prompts_share_frozen_tools_digest() -> None:
    agent = _agent(subagents=True)
    digests: list[str] = []
    identities: list[str] = []
    for prompt in USER_PROMPTS:
        tools = agent._select_turn_tools(
            agent._get_core_tools(), prompt, requires_web=False, allowed_tool_names=None
        )
        names = [t.name for t in tools]
        assert names == sorted(names), prompt
        assert "task" in names
        digest = digest_tools(tools)
        digests.append(digest)
        identities.append(_profile(digest).identity())
    assert len(set(digests)) == 1
    assert len(set(identities)) == 1
    left = _profile(digests[0])
    right = _profile(digests[-1])
    assert profiles_compatible(left, right)


def test_explore_word_does_not_rotate_tools_when_subagents_off() -> None:
    agent = _agent(subagents=False, opt_in=False)
    greeting = agent._select_turn_tools(
        agent._get_core_tools(), "你好", requires_web=False, allowed_tool_names=None
    )
    explore_word = agent._select_turn_tools(
        agent._get_core_tools(),
        "用explore 找认证",
        requires_web=False,
        allowed_tool_names=None,
    )
    names_g = [t.name for t in greeting]
    names_e = [t.name for t in explore_word]
    assert "task" not in names_g
    assert names_g == names_e
    assert digest_tools(greeting) == digest_tools(explore_word)


def test_opt_in_then_next_turn_keeps_task() -> None:
    agent = _agent(subagents=False, opt_in=True)
    first = agent._select_turn_tools(
        agent._get_core_tools(), "查找认证模块在哪个文件", requires_web=False, allowed_tool_names=None
    )
    second = agent._select_turn_tools(
        agent._get_core_tools(), "修一下 foo.py 里的空指针", requires_web=False, allowed_tool_names=None
    )
    assert [t.name for t in first] == [t.name for t in second]
    assert "task" in [t.name for t in first]
    assert digest_tools(first) == digest_tools(second)


def test_warm_prefix_hit_rate_meets_97() -> None:
    agent = _agent(subagents=True)
    tools = agent._select_turn_tools(
        agent._get_core_tools(), "你好", requires_web=False, allowed_tool_names=None
    )
    prefix = _prefix_tokens(tools)
    rates: dict[str, float] = {}
    for prompt in USER_PROMPTS:
        suffix = _estimate_tokens(prompt)
        rate = _warm_hit_rate(prefix, suffix)
        rates[prompt] = rate
        assert rate >= CACHE_FLOOR, f"{prompt}: warm hit {rate:.4f} < 0.97 (prefix={prefix} suffix={suffix})"
    ok, msg = _run_single_check(
        Check(type="cache_hit_floor", floor=CACHE_FLOOR),
        workdir=None,
        agent_answer="",
        extras={"cache_hit_rate": min(rates.values())},
    )
    assert ok, msg
    assert min(rates.values()) >= CACHE_FLOOR


def test_identity_mismatch_is_a_full_miss() -> None:
    agent = _agent(subagents=True)
    tools = agent._select_turn_tools(
        agent._get_core_tools(), "你好", requires_web=False, allowed_tool_names=None
    )
    prefix = _prefix_tokens(tools)
    rotated = _profile("deadbeef")
    stable = _profile(digest_tools(tools))
    assert not profiles_compatible(left=stable, right=rotated)
    miss = 0.0
    assert miss < CACHE_FLOOR
    assert _warm_hit_rate(prefix, 8) >= CACHE_FLOOR
