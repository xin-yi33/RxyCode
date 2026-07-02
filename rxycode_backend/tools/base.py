"""工具基类 - 定义工具协议与注册表

修复 P0-2A/P0-2B/P0-3 的工具基础设施:
    所有工具通过注册表管理,接入执行层的超时/重试/降级机制。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.execution import ToolResult, ToolProtocol


class BaseTool(ABC, ToolProtocol):
    """工具基类 - 所有具体工具继承此类

    子类需实现:
        - execute(): 正常执行逻辑
        - degrade(): 降级策略 (失败时的优雅降级)
    """

    name: str = "base"
    default_timeout: int = 30

    @abstractmethod
    def execute(self, input: dict, timeout: int = 0) -> ToolResult:
        """正常执行 - 由执行引擎调用,自动处理超时"""
        ...

    @abstractmethod
    def degrade(self, input: dict, error: str) -> ToolResult:
        """降级策略 - 正常执行失败时的备选方案

        对应 ADR-002 降级策略:
            - write 超时 -> 输出文件内容供用户手动保存
            - read 失败 -> 返回明确"文件不存在"
            - bash 失败 -> 返回错误信息而非卡死
        """
        ...


class ToolRegistry:
    """工具注册表 - 可扩展的工具管理 (对应 ADR-006 模块化单体)

    修复 P1-4 引导与能力不符:
        功能介绍基于实际注册的工具生成,而非泛化声明。
        新工具接入只需 register(),无需改核心代码。
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._capabilities: dict[str, dict] = {}  # 能力声明,与工具同步

    def register(self, tool: BaseTool, capability: dict | None = None) -> None:
        """注册工具 + 同步能力声明"""
        self._tools[tool.name] = tool
        self._capabilities[tool.name] = capability or {
            "name": tool.name,
            "timeout": tool.default_timeout,
        }

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_capabilities(self) -> list[dict]:
        """获取能力声明 - 用于生成新用户引导 (修复 P1-4)"""
        return list(self._capabilities.values())

    def generate_intro(self) -> str:
        """基于实际注册的工具生成功能介绍

        修复 P1-4:
            旧代码: 硬编码声称支持 Java/C++ 等未验证能力
            新代码: 基于实际注册工具动态生成,不虚报能力
        """
        if not self._tools:
            return "当前无可用工具。"
        lines = ["可用工具:"]
        for name, cap in self._capabilities.items():
            desc = cap.get("description", "未描述")
            timeout = cap.get("timeout", "N/A")
            lines.append(f"  - {name}: {desc} (超时 {timeout}s)")
        return "\n".join(lines)


# 全局工具注册表单例
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_tool_registry() -> None:
    """重置注册表 (测试用)"""
    global _registry
    _registry = ToolRegistry()
