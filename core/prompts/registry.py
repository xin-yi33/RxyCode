"""PromptRegistry: single source of truth for all pipeline stage prompts.

Design stitched from OpenHands:
- XML tag structured sections
- Tool descriptions injected dynamically from ToolRegistry
- Few-shot examples optionally attached
- Locale-aware rendering via i18n module
- PromptSpec versioning: version enters cache key & trace

Usage::

    from RxyCode.RxyCode1_1_0.core.prompts import get_role_prompt, get_system_prompt

    role = get_role_prompt("goal_planner")          # with few-shot
    role = get_role_prompt("goal_planner", include_few_shot=False)  # without
    sys_prompt = get_system_prompt(tools=True)       # with tool descriptions
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import Any

from .i18n import get_locale, t
from .few_shot import format_few_shot
from .templates import SYSTEM_PROMPT_TEMPLATE, STAGE_TEMPLATES
from .tool_list import get_tool_descriptions


# ---------------------------------------------------------------------------
# Safe formatter: leaves missing keys as-is instead of raising KeyError
# ---------------------------------------------------------------------------

class _SafeFormatter(string.Formatter):
    """Formatter that preserves unresolved placeholders.

    This allows partial formatting: if a template has ``{user_input}``
    but ``user_input`` is not in the format kwargs, the placeholder is
    left as ``{user_input}`` rather than raising ``KeyError``.
    """

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")
        return super().get_value(key, args, kwargs)


_safe_formatter = _SafeFormatter()


# ---------------------------------------------------------------------------
# PromptSpec: versioned prompt definition (plan requirement)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptSpec:
    """A versioned prompt specification.

    The version field enters cache keys and traces, ensuring prompt
    changes are detectable and cache-safe.
    """
    name: str            # e.g. "decomposer"
    version: str        # semantic version, e.g. "1.0.0"
    template: str       # str.format-style template
    few_shots: tuple[str, ...] = ()

    def render(self, language: str = "zh", **kwargs: Any) -> str:
        """Render the template with i18n text and few-shot examples."""
        few_shot_text = ""
        if self.few_shots:
            from .few_shot import format_few_shot
            few_shot_text = format_few_shot(self.name)

        fmt = {
            "few_shot_examples": few_shot_text,
            "language_requirement": t("language_requirement", language),
            **kwargs,
        }
        return _safe_formatter.format(self.template, **fmt)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Default versions for all stages (bumped on template changes)
_DEFAULT_VERSION = "1.0.0"


class PromptRegistry:
    """Registry for all pipeline stage prompts.

    All stage role prompts are registered at import time from
    ``templates.STAGE_TEMPLATES`` as ``PromptSpec`` objects with versions.
    The registry renders them with i18n-aware text and optional few-shot.
    """

    def __init__(self):
        self._specs: dict[str, PromptSpec] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all default stage templates from templates.py."""
        for name, template in STAGE_TEMPLATES.items():
            self._specs[name] = PromptSpec(
                name=name,
                version=_DEFAULT_VERSION,
                template=template,
            )

    def register(
        self,
        key: str,
        template: str,
        version: str = _DEFAULT_VERSION,
    ) -> None:
        """Register or override a stage prompt template."""
        self._specs[key] = PromptSpec(
            name=key,
            version=version,
            template=template,
        )

    def get_spec(self, key: str) -> PromptSpec:
        """Return the PromptSpec for the given key."""
        if key not in self._specs:
            raise KeyError(
                f"Unknown prompt key: {key!r}; available: {self.list_keys()}"
            )
        return self._specs[key]

    def list_keys(self) -> list[str]:
        """Return all registered stage keys."""
        return list(self._specs.keys())

    def get_version(self, key: str) -> str:
        """Return the version of a registered prompt."""
        return self.get_spec(key).version

    def get_role_prompt(
        self,
        key: str,
        locale: str | None = None,
        include_few_shot: bool = True,
        **format_kwargs,
    ) -> str:
        """Render a stage role prompt.

        Args:
            key: Stage key (e.g. "goal_planner").
            locale: Override locale; defaults to config locale.
            include_few_shot: Whether to inject few-shot examples.
            **format_kwargs: Additional format variables for the template.

        Returns:
            Rendered prompt string with XML tags.
        """
        spec = self.get_spec(key)

        if locale is None:
            locale = get_locale()

        few_shot_text = ""
        if include_few_shot:
            few_shot_text = format_few_shot(key)

        fmt = {
            "few_shot_examples": few_shot_text,
            "language_requirement": t("language_requirement", locale),
            **format_kwargs,
        }

        return _safe_formatter.format(spec.template, **fmt)

    def get_system_prompt(
        self,
        tools: bool = False,
        tool_names: list[str] | None = None,
        locale: str | None = None,
    ) -> str:
        """Render the unified system prompt.

        Args:
            tools: If True, inject tool descriptions from ToolRegistry.
                   Default False for cache consistency.
            tool_names: If provided, only include these tools.
            locale: Override locale; defaults to config locale.
        """
        if locale is None:
            locale = get_locale()

        tool_desc = get_tool_descriptions(tool_names) if tools else ""
        if not tool_desc:
            tool_desc = "(no tools registered)"

        return SYSTEM_PROMPT_TEMPLATE.format(
            language_requirement=t("language_requirement", locale),
            tool_descriptions=tool_desc,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry = PromptRegistry()


def get_role_prompt(
    key: str,
    locale: str | None = None,
    include_few_shot: bool = True,
    **format_kwargs,
) -> str:
    """Convenience: render a role prompt from the global registry."""
    return _registry.get_role_prompt(key, locale, include_few_shot, **format_kwargs)


def get_system_prompt(
    tools: bool = False,
    tool_names: list[str] | None = None,
    locale: str | None = None,
) -> str:
    """Convenience: render the system prompt from the global registry."""
    return _registry.get_system_prompt(tools, tool_names, locale)


def list_stages() -> list[str]:
    """Convenience: list all registered stage keys."""
    return _registry.list_keys()


def get_prompt_version(key: str) -> str:
    """Convenience: get the version of a registered prompt."""
    return _registry.get_version(key)


def build_user_message(
    role_instruction: str,
    user_content: str,
    memory_context: str = "",
    locale: str | None = None,
) -> str:
    """Build a user message with role instruction + content + optional context.

    Injects current system time so the model always knows the time.
    Uses i18n labels for the timestamp and context sections.
    """
    from datetime import datetime

    if locale is None:
        locale = get_locale()

    parts: list[str] = []
    if role_instruction:
        parts.append(f"[{t('role_label', locale)}: {role_instruction.strip()}]")
    parts.append(
        f"[{t('time_label', locale)}: "
        + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        + "]"
    )
    if memory_context:
        parts.append(f"[{t('context_label', locale)}]\n{memory_context}")
    parts.append(user_content)
    return "\n\n---\n\n".join(parts)


# Backward-compatible constant (rendered with default locale, no tools)
UNIFIED_SYSTEM_PROMPT = _registry.get_system_prompt(tools=False)
