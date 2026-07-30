"""Dynamic tool description generation from ToolRegistry.

This replaces the hardcoded tool list in the system prompt.
Tool descriptions are injected at runtime from the ToolRegistry,
ensuring the prompt always reflects the actual registered tools.

Single source of truth: delegates to ``ToolRegistry.get_descriptions()``.
"""

from __future__ import annotations


def get_tool_descriptions(tool_names: list[str] | None = None) -> str:
    """Generate tool description text from the ToolRegistry.

    Delegates to ``registry.get_descriptions()`` as the single source,
    ensuring the prompt always reflects the actual registered tools.

    Args:
        tool_names: If provided, only include these tools.
                    If None, include all registered tools.

    Returns:
        Formatted tool descriptions string, or empty string if no tools
        are registered (e.g., during unit tests without tool registration).
    """
    try:
        from RxyCode.RxyCode1_1_0.tools.registry import registry
    except ImportError:
        return ""

    if tool_names:
        # Filter: only include requested tool names
        name_set = set(tool_names)
        all_tools = registry.get_all()
        filtered = [t for t in all_tools if t.name in name_set]
        if not filtered:
            return ""
        parts = [f"- {t.name}: {t.description}" for t in filtered]
        return "\n".join(parts)

    # Single source: use registry.get_descriptions() directly
    return registry.get_descriptions()


def get_tool_names(tool_names: list[str] | None = None) -> list[str]:
    """Return the list of registered tool names."""
    try:
        from RxyCode.RxyCode1_1_0.tools.registry import registry
    except ImportError:
        return []

    all_tools = registry.get_all()
    if tool_names:
        name_set = set(tool_names)
        all_tools = [t for t in all_tools if t.name in name_set]

    return [t.name for t in all_tools]
