from typing import Any, Callable
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
        return result

    def get_names(self) -> list[str]:
        return list(self._tools.keys())

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
        for name, t in self._tools.items():
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


registry = ToolRegistry()
