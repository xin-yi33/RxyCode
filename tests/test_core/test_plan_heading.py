"""Plan mode must hand the existing approval pane a markdown heading."""

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    _ensure_plan_heading,
    _novel_stream_text,
)


def test_plan_without_heading_becomes_a_document() -> None:
    text = _ensure_plan_heading("1. 读取 CSV\n2. 给出步骤")
    assert text.startswith("# 计划\n")
    assert "1. 读取 CSV" in text


def test_repeated_paragraph_and_snapshot_are_not_appended() -> None:
    paragraph = "工作区 rxyboard/ 下已存在一套同名文件，还带缓存。我需要先读这些已有内容，再决定覆盖还是复用。"
    assert _novel_stream_text(paragraph, paragraph) == ""
    assert _novel_stream_text(paragraph + "\n\n" + paragraph, paragraph) == ""
    accumulated = "重要发现：目录里已经有看板。"
    snapshot = accumulated + "下一步先读 README。"
    assert _novel_stream_text(accumulated, snapshot) == "下一步先读 README。"
    assert _novel_stream_text("你好", "世界") == "世界"


def test_plan_with_heading_is_unchanged() -> None:
    src = "# 导入计划\n\n## Steps\n1. 读文件"
    assert _ensure_plan_heading(src) == src
