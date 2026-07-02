"""文件写入工具 - 修复 P0-2A write 工具 120s 超时

用户反馈问题 (P0-2A):
    场景 2 (创建 hello.py) 中,write 工具执行超过 120 秒无响应,
    最终超时。文件创建这一最基础的功能完全不可用。

修复方案 (ADR-002):
    1. 默认超时 15s (远低于 120s)
    2. 由执行层接管超时/重试,工具本身不阻塞
    3. 降级策略: 超时/失败时输出文件内容供用户手动保存
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..core.environment import get_environment
from ..core.execution import ToolResult
from .base import BaseTool


class WriteTool(BaseTool):
    """文件写入工具 - 可靠的文件创建"""

    name = "write"
    default_timeout = 15  # ADR-002: write 15s 超时

    def execute(self, input: dict, timeout: int = 0) -> ToolResult:
        """写入文件

        参数:
            input["path"]: 文件路径 (支持 ~ 和环境变量)
            input["content"]: 文件内容
        """
        start = time.time()
        env = get_environment()

        raw_path = input.get("path", "")
        content = input.get("content", "")

        if not raw_path:
            return ToolResult(
                output="",
                exit_code=1,
                duration_ms=int((time.time() - start) * 1000),
                extra={"error": "缺少 path 参数"},
            )

        # 修复 P0-3: 使用环境感知的路径解析,不拼接用户名
        resolved_path = env.resolve_path(raw_path)

        try:
            # 确保父目录存在
            parent = Path(resolved_path).parent
            parent.mkdir(parents=True, exist_ok=True)

            # 同步写入 (快操作,执行层负责超时控制)
            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(content)

            # 立即验证文件确实写入 (配合验证层)
            file_size = os.path.getsize(resolved_path)
            duration_ms = int((time.time() - start) * 1000)

            return ToolResult(
                output=f"文件已写入: {resolved_path} ({file_size} 字节)",
                exit_code=0,
                duration_ms=duration_ms,
                extra={
                    "path": resolved_path,
                    "size": file_size,
                    "verified": True,  # 写入后立即验证存在
                },
            )
        except OSError as e:
            duration_ms = int((time.time() - start) * 1000)
            return ToolResult(
                output="",
                exit_code=1,
                duration_ms=duration_ms,
                extra={"error": f"写入失败: {type(e).__name__}: {e}"},
            )

    def degrade(self, input: dict, error: str) -> ToolResult:
        """降级策略 (ADR-002): 超时/失败时输出内容供用户手动保存

        修复 P0-2A:
            旧代码: 超时后无响应,用户不知道发生了什么
            新代码: 降级输出文件内容,用户可手动保存,不丢失工作
        """
        content = input.get("content", "")
        path = input.get("path", "未知文件")
        return ToolResult(
            output=(
                f"[降级模式] 文件写入失败: {error}\n"
                f"目标路径: {path}\n"
                f"请手动将以下内容保存到该路径:\n"
                f"{'=' * 40}\n{content}\n{'=' * 40}"
            ),
            exit_code=0,  # 降级成功
            duration_ms=0,
            extra={"degraded": True, "original_error": error},
        )
