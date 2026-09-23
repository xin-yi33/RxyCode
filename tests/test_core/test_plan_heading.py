"""Plan mode must hand the existing approval pane a markdown heading."""

from RxyCode.RxyCode1_1_0.core.agent_v2 import _ensure_plan_heading


def test_plan_without_heading_becomes_a_document() -> None:
    text = _ensure_plan_heading("1. 读取 CSV\n2. 给出步骤")
    assert text.startswith("# 计划\n")
    assert "1. 读取 CSV" in text


def test_plan_with_heading_is_unchanged() -> None:
    src = "# 导入计划\n\n## Steps\n1. 读文件"
    assert _ensure_plan_heading(src) == src
