"""F10 · ModeRouter 三级路由。"""

from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.agents.router import (
    ExecutionMode,
    ModeRouter,
    get_default_router,
)
from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent


def test_slash_commands_force_mode() -> None:
    router = ModeRouter(enabled=False)
    assert router.handle_slash("/solo do it").startswith("forced solo")
    assert router.route("/team build both").mode is ExecutionMode.TEAM
    assert router.route("/team-multi x").mode is ExecutionMode.TEAM_MULTI_MODEL
    assert router.route("/explore 认证模块在哪").mode is ExecutionMode.EXPLORE
    why = router.handle_slash("/why-mode")
    assert "decided_by=user" in why
    assert "explore" in why or "mode=" in why


def test_disabled_skips_llm_and_heuristic() -> None:
    calls: list[str] = []

    def ask(prompt: str) -> str:
        calls.append(prompt)
        return "team"

    router = ModeRouter(enabled=False, llm_ask=ask, router_model="x")
    decision = router.route("重构前后端并迁移多个模块")
    assert decision.mode is ExecutionMode.SOLO
    assert decision.decided_by == "default"
    assert calls == []
    assert router._llm_calls == 0


def test_structured_split_goes_team() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("把前后端拆成两个独立改造再多人审计")
    assert decision.mode is ExecutionMode.TEAM
    assert decision.decided_by == "heuristic"
    assert "split" in decision.reason


def test_serial_dependency_goes_solo() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("只改这一个单文件，必须同步改完全量上下文")
    assert decision.mode is ExecutionMode.SOLO
    assert "serial" in decision.reason


def test_llm_failure_falls_back_to_level_two() -> None:
    def boom(_prompt: str) -> str:
        raise RuntimeError("timeout")

    router = ModeRouter(enabled=True, llm_ask=boom, router_model="judge")
    decision = router.route("把前后端拆成两个独立改造")
    assert decision.mode is ExecutionMode.TEAM
    assert decision.decided_by == "heuristic"
    assert "llm failed" in decision.reason


def test_route_emits_agent_event_with_experiment_tag() -> None:
    seen: list[AgentEvent] = []
    router = ModeRouter(enabled=True, emit=seen.append, experiment_tag="E1")
    router.route("hello?")
    assert seen
    assert seen[0].method == "event/agent_routed"
    assert seen[0].experiment_tag == "E1"
    assert seen[0].routing_reason


def test_efficiency_gate_updates_l2_thresholds() -> None:
    router = ModeRouter(enabled=True)
    before = router.thresholds.min_files_for_team
    router.apply_efficiency_gate(team_beats_solo=False)
    assert router.thresholds.min_files_for_team == before + 1
    router.apply_efficiency_gate(team_beats_solo=True, min_files_for_team=5)
    assert router.thresholds.min_files_for_team == 5


def test_default_router_why_mode_without_history() -> None:
    router = ModeRouter()
    assert router.handle_slash("/why-mode") == "no routing decision yet"
    get_default_router().route("/solo x")
    assert "solo" in get_default_router().handle_slash("/why-mode")


def test_legacy_parallel_method_is_gone() -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    assert not hasattr(AgentV2, "_should_request_parallel_execution")


def test_nl_open_team_is_user_force_even_when_disabled() -> None:
    router = ModeRouter(enabled=False)
    decision = router.route("开专家团 实现登录前后端")
    assert decision.mode is ExecutionMode.TEAM
    assert decision.decided_by == "user"
    assert "登录前后端" in decision.task


def test_nl_explore_is_user_force() -> None:
    router = ModeRouter(enabled=False)
    decision = router.route("用explore 查找认证模块")
    assert decision.mode is ExecutionMode.EXPLORE
    assert decision.decided_by == "user"
    assert "认证" in decision.task


def test_greeting_stays_solo() -> None:
    router = ModeRouter(enabled=True)
    assert router.route("你好").mode is ExecutionMode.SOLO
    assert router.route("hello").reason == "greeting"


def test_single_file_bugfix_stays_solo() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("修一下 foo.py 里的空指针")
    assert decision.mode is ExecutionMode.SOLO


def test_codebase_question_goes_explore() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("查找认证模块在哪个文件")
    assert decision.mode is ExecutionMode.EXPLORE
    assert "explore" in decision.reason


def test_why_it_works_without_write_goes_explore() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("这个登录流程为什么这样工作")
    assert decision.mode is ExecutionMode.EXPLORE


def test_full_feature_and_two_files_go_team() -> None:
    router = ModeRouter(enabled=True)
    assert router.route("实现一个完整的登录功能，前后端都要").mode is ExecutionMode.TEAM
    two = router.route("实现 auth.py 和 login.tsx 的接口对接")
    assert two.mode is ExecutionMode.TEAM
    assert "multiple files" in two.reason


def test_dont_modify_file_is_not_explore() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route(
        "当前目录已经有 notes.md。请用系统默认程序打开 notes.md 给我预览。"
        "成功后立刻最终回答，写明工具名和返回原文。不要等我关闭 Typora/记事本。"
        "不要改文件内容"
    )
    assert decision.mode is ExecutionMode.SOLO
    assert decision.reason == "host preview"


def test_disabled_allow_explore_open_notes_uses_remainder_not_trigger() -> None:
    router = ModeRouter(enabled=False)
    decision = router.route(
        "用子代理打开 notes.md 给我预览。不要改文件内容",
        allow_explore=True,
    )
    assert decision.mode is ExecutionMode.SOLO
    assert decision.reason == "host preview"
    assert "notes.md" in decision.task
    assert not (decision.task or "").startswith("用子代理")


def test_missing_docx_open_is_host_preview_not_explore() -> None:
    from RxyCode.RxyCode1_1_0.core.agents.router import is_open_only_preview_task

    router = ModeRouter(enabled=True)
    prompt = (
        "请打开当前目录下这个不存在的文件：open_e2e_missing_no_such_file.docx。"
        "如果打不开，把工具返回的错误原文告诉我，然后给出最终结果。"
        "不要静默重试超过两次，不要一直等到某个窗口出现。"
    )
    decision = router.route(prompt)
    assert decision.mode is ExecutionMode.SOLO
    assert decision.reason == "host preview"
    assert is_open_only_preview_task(prompt) is True
    assert is_open_only_preview_task(
        "在当前工作目录新建 open_e2e_demo.html，写完后立刻用系统默认程序打开"
    ) is False


def test_readonly_without_codebase_question_stays_solo() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("不要改任何文件，用三句话介绍这个项目")
    assert decision.mode is ExecutionMode.SOLO
    assert "explore" not in decision.reason


def test_readonly_codebase_question_still_goes_explore() -> None:
    router = ModeRouter(enabled=True)
    decision = router.route("不要改任何文件，查找认证模块在哪个文件")
    assert decision.mode is ExecutionMode.EXPLORE


def test_allow_explore_when_agents_disabled() -> None:
    router = ModeRouter(enabled=False)
    skipped = router.route("查找认证模块在哪个文件")
    assert skipped.mode is ExecutionMode.SOLO
    allowed = router.route("查找认证模块在哪个文件", allow_explore=True)
    assert allowed.mode is ExecutionMode.EXPLORE


def test_session_enabled_runs_heuristics() -> None:
    router = ModeRouter(enabled=False)
    decision = router.route("实现一个完整的登录功能，前后端都要", session_enabled=True)
    assert decision.mode is ExecutionMode.TEAM


def test_min_files_for_team_default_is_two() -> None:
    assert ModeRouter().thresholds.min_files_for_team == 2


def test_route_decision_stays_off_the_llm_clock() -> None:
    """Copied from harness practice: route-before-LLM must be microseconds-cheap."""
    import time

    router = ModeRouter(enabled=True)
    prompts = (
        "你好",
        "查找认证模块在哪个文件",
        "实现一个完整的登录功能，前后端都要",
    )
    t0 = time.perf_counter()
    for _ in range(50):
        for prompt in prompts:
            router.route(prompt)
    elapsed = (time.perf_counter() - t0) / 150
    assert elapsed < 0.01, f"route() {elapsed*1000:.3f}ms is no longer a cheap L2"


def test_settings_agents_cache_follows_config_mtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data-cache"))
    from RxyCode.RxyCode1_1_0.config.settings import save_config
    from RxyCode.RxyCode1_1_0.core.agents import router as route_mod

    (tmp_path / "data-cache").mkdir()
    route_mod._AGENTS_CACHE = None
    save_config({"agents": {"enabled": False, "route_mode": "auto"}})
    router = ModeRouter()
    assert router.route("实现一个完整的登录功能，前后端都要").mode is ExecutionMode.SOLO
    save_config({"agents": {"enabled": True, "route_mode": "auto"}})
    assert router.route("实现一个完整的登录功能，前后端都要").mode is ExecutionMode.TEAM


def test_named_test_file_plus_impl_is_solo_not_team() -> None:
    """2026-09-23 P1a 回归：实现文件 + tests/ 下点名测试 = 单件小活，走 solo。

    现场：E26「写 eh26_lru.py + tests/test_eh26_lru.py」被 min_files_for_team=2
    判成 TEAM（multiple files），走了完整七阶段 SOP，用户反馈呈现奇怪。
    闸门规则：tests/ 外点名 ≥2 个产品文件才算真正的多文件。
    """
    router = ModeRouter(enabled=True)
    e26 = router.route(
        "必须按原样落地这两个路径（不准改名、不准挪到 backend/）："
        "eh26_lru.py 实现函数 lru_get(cache, key)，cache 是 dict，key 不存在返回 None；"
        "tests/test_eh26_lru.py 至少一条 pytest（空 cache 取 key 得 None）。"
        "最终回答之前这两个文件都必须已经在磁盘上。"
    )
    assert e26.mode is ExecutionMode.SOLO, f"E26 应走 solo，实际 {e26.mode} ({e26.reason})"

    # tests/ 外两个产品文件仍然进团队（闸门不误伤真多文件）
    two = router.route("实现 models/user.py 和 models/order.py 两个模型类")
    assert two.mode is ExecutionMode.TEAM
    assert "multiple files" in two.reason
