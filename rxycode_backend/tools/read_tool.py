"""文件读取工具 - 修复 P0-2A read 工具超时

修复方案 (ADR-002):
    1. 默认超时 5s
    2. 文件不存在时立即返回明确错误,而非超时
    3. 降级策略: 返回"文件不存在"而非卡死
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..core.environment import get_environment
from ..core.execution import ToolResult
from .base import BaseTool


class ReadTool(BaseTool):
    """文件读取工具"""

    name = "read"
    default_timeout = 5  # ADR-002: read 5s 超时

    def execute(self, input: dict, timeout: int = 0) -> ToolResult:
        """读取文件

        参数:
            input["path"]: 文件路径
        """
        start = time.time()
        env = get_environment()

        raw_path = input.get("path", "")
        if not raw_path:
            return ToolResult(
                output="",
                exit_code=1,
                duration_ms=int((time.time() - start) * 1000),
                extra={"error": "缺少 path 参数"},
            )

        resolved_path = env.resolve_path(raw_path)

        # 立即检查存在性,避免超时 (修复 P0-2A)
        if not os.path.exists(resolved_path):
            return ToolResult(
                output="",
                exit_code=2,  # 文件不存在专用退出码
                duration_ms=int((time.time() - start) * 1000),
                extra={"error": f"文件不存在: {resolved_path}", "not_found": True},
            )

        try:
            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            duration_ms = int((time.time() - start) * 1000)
            return ToolResult(
                output=content,
                exit_code=0,
                duration_ms=duration_ms,
                extra={"path": resolved_path, "size": len(content)},
            )
        except OSError as e:
            duration_ms = int((time.time() - start) * 1000)
            return ToolResult(
                output="",
                exit_code=1,
                duration_ms=duration_ms,
                extra={"error": f"读取失败: {type(e).__name__}: {e}"},
            )

    def degrade(self, input: dict, error: str) -> ToolResult:
        """降级策略: 返回明确的"文件不存在"错误"""
        path = input.get("path", "未知文件")
        env = get_environment()
        resolved = env.resolve_path(path)
        return ToolResult(
            output=f"文件不存在: {resolved}",
            exit_code=2,
            duration_ms=0,
            extra={"degraded": True, "not_found": True},
        )
