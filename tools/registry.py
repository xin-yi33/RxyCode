from langchain_core.tools import StructuredTool


class ToolRegistry:
    """Registry for tools with risk-level classification.

    Risk levels (stitched from OpenHands SecurityRisk):
    - ``read``: read-only tools (grep, glob, read, ls, view, datetime)
    - ``write``: file-writing tools (write, edit, patch) - default
    - ``danger``: dangerous tools (bash, git push --force, rm -rf)
    """

    def __init__(self):
        self._tools: dict[str, StructuredTool] = {}
        self._aliases: set[str] = set()
        self._risks: dict[str, str] = {}  # tool_name -> "read"|"write"|"danger"

    def register(self, tool: StructuredTool, risk: str = "write"):
        """Register a tool with an associated risk level.

        Args:
            tool: The StructuredTool to register.
            risk: Risk level - "read", "write", or "danger".
                  Defaults to "write" per OpenHands convention.
        """
        self._tools[tool.name] = tool
        self._risks[tool.name] = risk

    def register_alias(self, alias: str, target_name: str) -> bool:
        """Register an alias name pointing to an existing registered tool.
        Returns True if the target tool exists and alias was registered."""
        if target_name not in self._tools:
            return False
        self._tools[alias] = self._tools[target_name]
        self._risks[alias] = self._risks.get(target_name, "write")
        self._aliases.add(alias)
        return True

    def get(self, name: str) -> StructuredTool | None:
        return self._tools.get(name)

    def get_all(self) -> list[StructuredTool]:
        # Return only non-alias tools to avoid duplicates
        seen = set()
        result = []
        for name, tool in self._tools.items():
            if name in self._aliases:
                continue
            # Deduplicate by tool identity
            tid = id(tool)
            if tid not in seen:
                seen.add(tid)
                result.append(tool)
        # B2: 工具列表按名称排序固定，保证前缀字节稳定（缓存纪律）。
        return sorted(result, key=lambda t: getattr(t, "name", "") or "")

    def get_names(self) -> list[str]:
        # B2: 排序固定（含别名，保持原有语义：get_names 返回全部注册键），
        # 确定性顺序保证前缀字节稳定。
        return sorted(self._tools.keys())

    def get_risk(self, name: str) -> str:
        """Return the risk level of a tool (default 'write')."""
        return self._risks.get(name, "write")

    def get_tools_by_risk(self, risk: str) -> list[StructuredTool]:
        """Return all tools with the given risk level."""
        return [t for n, t in self._tools.items()
                if n not in self._aliases and self._risks.get(n, "write") == risk]

    def get_descriptions(self) -> str:
        parts = []
        seen = set()
        for name, t in sorted(self._tools.items(), key=lambda kv: kv[0]):
            if name in self._aliases:
                continue
            tid = id(t)
            if tid not in seen:
                seen.add(tid)
                parts.append(f"- {t.name}: {t.description}")
        return "\n".join(parts)

    def remove(self, name: str) -> bool:
        """Remove a tool by name (including alias). Returns True if found."""
        if name in self._tools:
            del self._tools[name]
            self._aliases.discard(name)
            return True
        return False


#: 进程级默认注册表。
#:
#: 历史上这是唯一的注册表，所有工具都注册到这里，因此无法给不同 Agent 配
#: 不同工具集。Phase F 引入 per-agent 注册表；本实例保留为默认值，供单
#: Agent 路径和未显式传注册表的调用方使用。
#:
#: 新代码请通过依赖注入接收 ToolRegistry，不要直接 import 这个全局。
default_registry = ToolRegistry()

#: 向后兼容别名。新代码不要用。
registry = default_registry
