"""Prompt registry package - single source of truth for all prompts.

Public API:
    get_system_prompt(tools=True)      -> str   # unified system prompt
    get_role_prompt("goal_planner")    -> str   # stage-specific role prompt
    build_user_message(role, content)  -> str   # formatted user message
    list_stages()                      -> list  # all stage keys
    get_prompt_version("decomposer")   -> str   # prompt version (for cache key)
    PromptSpec                         -> dataclass  # versioned prompt spec
    UNIFIED_SYSTEM_PROMPT              -> str   # backward-compatible constant
"""

from .registry import (
    PromptRegistry,
    PromptSpec,
    get_system_prompt,
    get_role_prompt,
    build_user_message,
    list_stages,
    get_prompt_version,
    UNIFIED_SYSTEM_PROMPT,
)

__all__ = [
    "PromptRegistry",
    "PromptSpec",
    "get_system_prompt",
    "get_role_prompt",
    "build_user_message",
    "list_stages",
    "get_prompt_version",
    "UNIFIED_SYSTEM_PROMPT",
]
