"""final_answer is the ReAct finish action (exit condition 2)."""

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, canonical_tool_name, get_tool_risk
from RxyCode.RxyCode1_1_0.tools.final_answer import final_answer_tool, submit_final_answer


def test_echoes_result() -> None:
    assert submit_final_answer("done") == "done"
    assert final_answer_tool.name == "final_answer"


def test_alias_and_risk() -> None:
    assert canonical_tool_name("final-answer") == "final_answer"
    assert get_tool_risk("final_answer") == RiskLevel.READ
