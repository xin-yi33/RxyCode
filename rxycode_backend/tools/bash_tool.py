"""Shell 命令执行工具 - 修复 P0-2B Shell 语法混淆

用户反馈问题 (P0-2B):
    Agent 在 bash 工具中使用了 PowerShell 语法:
        $desktopPath = Join-Path $env:USERPROFILE "Desktop"
    导致: '$desktop' 不是内部或外部命令 [exit code: 1]

修复方案 (ADR-004):
    通过 Shell 抽象层统一执行,自动校验/转换语法。
    工具本身只负责调用 ShellExecutor,语法处理由抽象层完成。
"""

from __future__ import annotations

import time

from ..core.execution import ToolResult
from ..core.shell import ShellExecutor, ShellSyntaxError, safe_execute
from .base import BaseTool


class BashTool(BaseTool):
    """Shell 命令执行工具 - 跨平台统一接口

    注意: 工具名为 bash 是历史遗留,实际通过 Shell 抽象层
    在 Windows 上使用 PowerShell/CMD,在 Unix 上使用 bash/zsh。
    """

    name = "bash"
    default_timeout = 60  # ADR-002: bash 60s 超时

    def execute(self, input: dict, timeout: int = 0) -> ToolResult:
        """执行 Shell 命令

        参数:
            input["command"]: 命令字符串
            input["cwd"]: 工作目录 (可选)
            input["timeout"]: 自定义超时 (可选)
        """
        start = time.time()
        command = input.get("command", "")
        cwd = input.get("cwd")
        custom_timeout = input.get("timeout") or self.default_timeout

        if not command:
            return ToolResult(
                output="",
                exit_code=1,
                duration_ms=int((time.time() - start) * 1000),
                extra={"error": "缺少 command 参数"},
            )

        try:
            # 修复 P0-2B: 通过 Shell 抽象层执行,自动处理语法
            result = safe_execute(command, timeout=custom_timeout, cwd=cwd)
            duration_ms = int((time.time() - start) * 1000)

            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}" if result.stdout else result.stderr

            return ToolResult(
                output=output,
                exit_code=result.exit_code,
                duration_ms=duration_ms,
                extra={
                    "shell_used": result.shell_used.value,
                    "translated": result.translated,
                    "command": result.command_executed,
                },
            )
        except ShellSyntaxError as e:
            # 语法不兼容且无法转换 - 明确报错而非执行失败
            duration_ms = int((time.time() - start) * 1000)
            return ToolResult(
                output=f"命令语法错误: {e}",
                exit_code=1,
                duration_ms=duration_ms,
                extra={"error": str(e), "syntax_error": True},
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return ToolResult(
                output=f"命令执行异常: {type(e).__name__}: {e}",
                exit_code=1,
                duration_ms=duration_ms,
                extra={"error": str(e)},
            )

    def degrade(self, input: dict, error: str) -> ToolResult:
        """降级策略: 返回错误信息而非卡死"""
        command = input.get("command", "")
        return ToolResult(
            output=(
                f"[降级模式] 命令执行失败: {error}\n"
                f"原始命令: {command}\n"
                f"建议: 检查命令语法或手动在终端执行。"
            ),
            exit_code=0,
            duration_ms=0,
            extra={"degraded": True, "original_error": error},
        )


def register_default_tools() -> None:
    """注册默认工具集到全局注册表和执行引擎

    在应用启动时调用一次,完成工具注册。
    """
    from .base import get_tool_registry, reset_tool_registry
    from ..core.execution import get_execution_engine

    # 重置 (测试可重复)
    reset_tool_registry()
    registry = get_tool_registry()
    engine = get_execution_engine()

    # 实例化工具
    write_tool = WriteTool()
    read_tool = ReadTool()
    bash_tool = BashTool()

    # 注册到注册表 (带能力声明,修复 P1-4)
    registry.register(write_tool, {
        "name": "write",
        "description": "写入文件 (支持 ~ 和环境变量路径)",
        "timeout": write_tool.default_timeout,
    })
    registry.register(read_tool, {
        "name": "read",
        "description": "读取文件内容",
        "timeout": read_tool.default_timeout,
    })
    registry.register(bash_tool, {
        "name": "bash",
        "description": "执行 Shell 命令 (自动适配 PowerShell/CMD/Bash)",
        "timeout": bash_tool.default_timeout,
    })

    # 注册到执行引擎 (接入超时/重试/降级)
    engine.register_tool(write_tool)
    engine.register_tool(read_tool)
    engine.register_tool(bash_tool)


# 延迟导入避免循环
from .write_tool import WriteTool
from .read_tool import ReadTool
