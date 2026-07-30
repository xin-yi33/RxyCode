"""W16/W18 product fixes: git-force skips web research; evidence maps to Chinese."""
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, GIT_ONLY_TOOL_NAMES, _GIT_FORCE_RE
from RxyCode.RxyCode1_1_0.core.research_policy import get_research_policy
from RxyCode.RxyCode1_1_0.utils.user_facing_errors import to_user_facing_error, MSG_TOOL_INTERRUPTED


def test_git_force_regex_and_allowlist():
    msg = "必须调用 git 工具，operation=status，不要用 websearch"
    assert _GIT_FORCE_RE.search(msg)
    agent = AgentV2.__new__(AgentV2)
    names = agent._resolve_fast_reply_tool_allowlist(msg, None)
    assert names == GIT_ONLY_TOOL_NAMES
    assert "websearch" not in names
    # status token would otherwise force web research
    assert get_research_policy(msg).requires_web is True


def test_evidence_failed_is_user_facing_chinese():
    out = to_user_facing_error(
        "[evidence failed: Tool read did not complete: failed]"
    )
    assert out == MSG_TOOL_INTERRUPTED
    assert "evidence" not in out.lower()
