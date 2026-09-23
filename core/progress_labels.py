"""User-visible wait labels. Status lines must name what is actually blocking."""

from __future__ import annotations

FIRST_TOKEN_WAIT = "等待模型返回…"
MODEL_STREAMING = "模型输出中…"


def thinking_round(n: int) -> str:
    return f"思考中（第 {int(n)} 轮）…"


def preparing_tool(label: str, chunks: int) -> str:
    name = str(label or "tool").strip() or "tool"
    return f"正在组装 {name} 工具参数…（{int(chunks)} 片）"


def tool_wait_progress(name: str, elapsed_s: int | None = None) -> str:
    key = str(name or "tool").strip() or "tool"
    lowered = key.lower()
    if lowered in {"bash", "shell"}:
        label = "等待终端返回…"
    elif lowered in {"open_file", "open", "browser"}:
        label = "等待打开文件…"
    elif lowered in {"final_answer", "final-answer"}:
        # 废弃代码（2026-09-22）：label = "正在提交最终结果…"
        # final_answer 只是结束本轮的内部信号，回答正文已经显示。禁止再当作工具等待。
        return ""
    elif lowered == "vision":
        label = "等待视觉识别返回…"
    else:
        label = f"等待工具 {key} 返回…"
    if elapsed_s is not None and int(elapsed_s) >= 1:
        return f"{label.rstrip('…')}（{int(elapsed_s)}s）…"
    return label
