from RxyCode.RxyCode1_1_0.core.progress_labels import (
    FIRST_TOKEN_WAIT,
    MODEL_STREAMING,
    preparing_tool,
    thinking_round,
    tool_wait_progress,
)


def test_tool_wait_labels_name_the_blocker():
    assert tool_wait_progress("bash") == "等待终端返回…"
    assert tool_wait_progress("shell") == "等待终端返回…"
    assert tool_wait_progress("vision") == "等待视觉识别返回…"
    assert tool_wait_progress("open_file") == "等待打开文件…"
    assert tool_wait_progress("open") == "等待打开文件…"
    assert tool_wait_progress("final_answer") == ""
    assert tool_wait_progress("final-answer") == ""
    assert tool_wait_progress("ls") == "等待工具 ls 返回…"
    assert tool_wait_progress("vision", 1) == "等待视觉识别返回（1s）…"
    assert tool_wait_progress("vision", 12) == "等待视觉识别返回（12s）…"


def test_model_wait_labels_are_ttft_not_decode():
    assert FIRST_TOKEN_WAIT == "等待模型返回…"
    assert MODEL_STREAMING == "模型输出中…"
    assert thinking_round(2) == "思考中（第 2 轮）…"
    assert "ls" in preparing_tool("ls", 3)
