# tests/test_timeout/test_decision_engine.py（文件头）
"""layer=unit P2"""
from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.core.timeout_decision import (
    DecisionPolicy, ExtensionLedger, TimeoutDecisionEngine,
)
from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence


class _StubLLM:
    """义层 stub：queue 里逐条取要让 LLM 回的文本；调用次数如实记录。"""
    def __init__(self, replies=(), raises=None, hang=False):
        self._replies = list(replies)
        self._raises = raises
        self._hang = hang
        self.calls = 0

    async def ainvoke(self, prompt, **kw):
        self.calls += 1
        if self._hang:
            await asyncio.sleep(3600)
        if self._raises is not None:
            raise self._raises
        text = self._replies.pop(0)

        class _R:  # 模仿 AIMessage 最小面
            content = text
        return _R()


def _evidence(**over):
    base = dict(
        trigger_point="graph_task_max_time", session_id="s", run_id="r",
        subject_id="subj_t", task_hint="t",
        elapsed_seconds=7200.0, budget_seconds=7200.0, extension_index=0,
        progress="", last_error="",
    )
    base.update(over)
    return TimeoutEvidence(**base)


def _policy(enabled=True):
    return DecisionPolicy({
        "enabled": enabled,
        "max_extensions_per_point": 2,
        "extension_growth": 2,
        "decision_timeout_seconds": 1.0,
        "decision_model": None,
        "fail_closed": True,
        "absolute_cap_seconds": {
            "graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
            "watchdog_stall": 1800.0, "tool_timeout": 7200.0,
        },
    })

def test_u_p2_01_config_single_shape_and_no_double_section():
    """layer=unit U-P2-01 config 单一形状：timeout_decision_config(整 config)→节本体；
    行为负例：若实现二次取节（mc["timeout_decision"]），from_config 构造即 KeyError → 红"""
    from RxyCode.RxyCode1_1_0.core import timeout_decision as td

    cfg = {"timeout_decision": {
        "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
        "decision_timeout_seconds": 1.0, "decision_model": None, "fail_closed": True,
        "absolute_cap_seconds": {"graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
                                 "watchdog_stall": 1800.0, "tool_timeout": 7200.0}}}
    section = td.timeout_decision_config(cfg)
    assert "timeout_decision" not in section                    # 返回的就是节本体（没有二次包节）
    assert section["enabled"] is True and section["fail_closed"] is True
    # 行为断言（优先于源码门）：from_config 只按节判断 enabled、DecisionPolicy 直接吃节本体；
    # 内部若再做 mc["timeout_decision"] 二次取节，下一行构造当场 KeyError，本测试即红。
    engine = td.from_config(cfg, base_llm=_StubLLM())
    assert engine is not None
    assert engine._policy._cfg == section                       # 与节本体同值、无二次加工


async def test_u_p2_02_grant_truncates_at_cap_and_identity_holds():
    """layer=unit U-P2-02 grant 截断：granted=min(requested, cap - budget)；恒等式钉死"""
    policy = _policy()
    g = policy.grant(trigger_point="tool_timeout", budget=7150.0,
                     k=1, extend_seconds=2400.0)
    assert g.granted_seconds == 50.0                            # 7200.0 - 7150.0
    assert g.new_budget == 7200.0
    assert g.granted_seconds == g.new_budget - 7150.0           # granted == new_budget - budget 恒成立
    g2 = policy.grant(trigger_point="tool_timeout", budget=7150.0,
                      k=2, extend_seconds=600.0)
    assert g2.granted_seconds == 50.0                           # requested=600*2=1200 仍截断到 50
    assert g2.new_budget == 7200.0


async def test_u_p2_03_sequence_derived_from_ledger_count_not_evidence():
    """layer=unit U-P2-03 序号唯一来源 ledger.count(scope)+1；evidence.extension_index 恒 0 也递增"""
    policy = _policy()
    ledger = ExtensionLedger()
    engine = TimeoutDecisionEngine(
        _StubLLM(replies=[
            '{"action": "continue", "extend_seconds": 600, "note": "k1", "confidence": 0.9}',
            '{"action": "continue", "extend_seconds": 600, "note": "k2", "confidence": 0.9}',
        ]),
        policy, ledger=ledger, sink=(events := []),
    )
    ev = _evidence()                                            # extension_index 恒 0，不作记账依据
    assert (await engine.decide(ev)).action == "continue"
    assert (await engine.decide(ev)).action == "continue"
    assert [e["extension_index"] for e in events] == [1, 2]      # 第 1/2 次皆由引擎推导
    assert events[1]["extend_seconds"] == 1200.0                 # growth=2：k=2 授予翻倍
    assert ledger.count(("s", "subj_t")) == 2
    assert ledger.total_extended(("s", "subj_t")) == 1800.0
    forced = await engine.decide(ev)                             # k 候选=3 > max=2：强制 stop 且不问 LLM
    assert forced.action == "stop" and forced.note.startswith("[policy] ")
    assert engine._llm.calls == 2                                # 第三次零决策成本


async def test_u_p2_04_scope_isolation_and_query_port_original_budget_only():
    """layer=unit U-P2-04 ledger scope=(session_id, subject_id) 隔离；查询口只对原始预算有定义"""
    policy = _policy()
    ledger = ExtensionLedger()
    engine = TimeoutDecisionEngine(
        _StubLLM(replies=[
            '{"action": "continue", "extend_seconds": 600, "note": "a1", "confidence": 0.9}',
            '{"action": "continue", "extend_seconds": 600, "note": "a2", "confidence": 0.9}',
            '{"action": "continue", "extend_seconds": 600, "note": "b1", "confidence": 0.9}',
            '{"action": "continue", "extend_seconds": 600, "note": "c1", "confidence": 0.9}',
        ]),
        policy, ledger=ledger,
    )
    await engine.decide(_evidence(subject_id="task_a"))          # k=1
    g1 = engine.last_grant(("s", "task_a"))
    assert (g1.granted_seconds, g1.new_budget) == (600.0, 7800.0)
    await engine.decide(_evidence(subject_id="task_a"))          # k=2：裁定 B 钉死规则——
    # decide() 预算基数 = last_grant(scope).new_budget or evidence.budget_seconds
    g2 = engine.last_grant(("s", "task_a"))
    assert (g2.granted_seconds, g2.new_budget) == (1200.0, 9000.0)   # 7200→7800→9000，不是 9600
    assert g2.granted_seconds == g2.new_budget - g1.new_budget
    await engine.decide(_evidence(subject_id="task_b"))          # 同 session 不同 task 独立计数/cap
    assert ledger.count(("s", "task_b")) == 1
    assert ledger.total_extended(("s", "task_b")) == 600.0
    await engine.decide(_evidence(session_id="other", subject_id="task_a"))
    assert ledger.count(("other", "task_a")) == 1                # 跨 session 互不影响
    assert ledger.count(("s", "task_a")) == 2
    # 查询口 granted_budget(scope, 原始预算)：传延长后的 budget 是调用方 bug（9600 永不许出现）
    assert engine.granted_budget(("s", "task_a"), 7200.0) == 9000.0


async def test_u_p2_05_fail_closed_three_paths():
    """layer=unit U-P2-05 LLM 异常 / 解析失败 / 决策超时 → 全 fail-closed stop"""
    for stub in (
        _StubLLM(raises=ConnectionError("no route")),
        _StubLLM(replies=["绝不是 JSON"]),
        _StubLLM(hang=True),
    ):
        engine = TimeoutDecisionEngine(stub, _policy(), ledger=ExtensionLedger())
        r = await engine.decide(_evidence())
        assert r.action == "stop" and r.extend_seconds == 0.0
        assert r.note.startswith("[fail-closed] ")
        assert r.confidence == 0.0
        engine_events = engine.drain_events()
        assert engine_events[0]["fail_closed"] is True        # 事件标记
