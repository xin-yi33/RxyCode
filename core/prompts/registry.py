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
from dataclasses import dataclass
from datetime import datetime
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
        self._specs: dict[str, dict[str, PromptSpec]] = {}
        self._system_templates: dict[str, str] = {"default": SYSTEM_PROMPT_TEMPLATE}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all default stage templates from templates.py."""
        for name, template in STAGE_TEMPLATES.items():
            self._specs[name] = {
                "default": PromptSpec(
                    name=name,
                    version=_DEFAULT_VERSION,
                    template=template,
                )
            }
        # F4-8：system 模板也入 PromptSpec。precise cache 的 prompt_version 从这里取。
        # 改正文必须同步 bump 日期版本（同日多次加 -rN）。
        self._specs["system"] = {
            "default": PromptSpec(
                name="system",
                version="2026-10-01",
                template=SYSTEM_PROMPT_TEMPLATE,
            )
        }

    def register(
        self,
        key: str,
        template: str,
        version: str = _DEFAULT_VERSION,
        variant: str = "default",
    ) -> None:
        """Register or override a stage prompt template for a variant."""
        self._specs.setdefault(key, {})[variant] = PromptSpec(
            name=key,
            version=version,
            template=template,
        )

    def register_system_template(self, variant: str, template: str) -> None:
        """Register a system-prompt template for a variant (mechanism only)."""
        self._system_templates[variant] = template

    def _resolve_spec(self, key: str, variant: str) -> PromptSpec:
        """Resolve (stage, locale, variant) with fallback to "default" (A9)."""
        variants = self._specs.get(key)
        if not variants:
            raise KeyError(
                f"Unknown prompt key: {key!r}; available: {self.list_keys()}"
            )
        spec = variants.get(variant) or variants.get("default")
        if spec is None:
            raise KeyError(
                f"No prompt spec for key {key!r} variant {variant!r} (no default)"
            )
        return spec

    def get_spec(self, key: str) -> PromptSpec:
        """Return the default-variant PromptSpec for the given key."""
        return self._resolve_spec(key, "default")

    def list_keys(self) -> list[str]:
        """Return pipeline stage keys.

        ``system`` is the S1 version knob for the precise cache. It stays
        queryable through get_spec / get_prompt_version and is not a stage.
        """
        return [key for key in self._specs if key != "system"]

    def get_version(self, key: str) -> str:
        """Return the version of a registered prompt."""
        return self.get_spec(key).version

    def get_role_prompt(
        self,
        key: str,
        locale: str | None = None,
        include_few_shot: bool = True,
        variant: str = "default",
        few_shot_limit: int | None = None,
        **format_kwargs,
    ) -> str:
        """Render a stage role prompt.

        Args:
            key: Stage key (e.g. "goal_planner").
            locale: Override locale; defaults to config locale.
            include_few_shot: Whether to inject few-shot examples.
            variant: Model-specific variant key; falls back to "default".
            few_shot_limit: A20 few_shot_policy="first2" → 只注入前 N 条；None=全量。
            **format_kwargs: Additional format variables for the template.

        Returns:
            Rendered prompt string with XML tags.
        """
        spec = self._resolve_spec(key, variant)

        if locale is None:
            locale = get_locale()

        few_shot_text = ""
        if include_few_shot:
            few_shot_text = format_few_shot(key, limit=few_shot_limit)

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
        variant: str = "default",
    ) -> str:
        """Render the unified system prompt.

        Args:
            tools: If True, inject tool descriptions from ToolRegistry.
                   Default False for cache consistency.
            tool_names: If provided, only include these tools.
            locale: Override locale; defaults to config locale.
            variant: Model-specific variant key; falls back to "default".
        """
        if locale is None:
            locale = get_locale()

        tool_desc = get_tool_descriptions(tool_names) if tools else ""
        if not tool_desc:
            tool_desc = "(no tools registered)"

        template = self._system_templates.get(variant) or self._system_templates["default"]
        return template.format(
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
    variant: str = "default",
    few_shot_limit: int | None = None,
    **format_kwargs,
) -> str:
    """Convenience: render a role prompt from the global registry."""
    return _registry.get_role_prompt(
        key, locale, include_few_shot, variant, few_shot_limit=few_shot_limit, **format_kwargs
    )


def get_system_s1(
    tools: bool = False,
    tool_names: list[str] | None = None,
    locale: str | None = None,
    variant: str = "default",
) -> str:
    """Frozen S1: identity, rules, tool descriptions. No date/cwd/research."""
    return _registry.get_system_prompt(tools, tool_names, locale, variant)


def get_system_s2(
    *,
    cwd: str = "",
    research_contract: str = "",
    memory_excerpt: str = "",
    session_created_at: str | None = None,
    locale: str | None = None,
) -> str:
    """Dynamic turn snapshot for the user lane (never a second system)."""
    if locale is None:
        locale = get_locale()
    parts: list[str] = []
    if session_created_at:
        parts.append(f"[session_created: {session_created_at}]")
    if cwd:
        parts.append(f"[cwd: {cwd}]")
    if memory_excerpt:
        parts.append(f"[{t('context_label', locale)}]\n{memory_excerpt}")
    if research_contract:
        parts.append(research_contract)
    return "\n\n".join(parts)


def get_system_prompt(
    tools: bool = False,
    tool_names: list[str] | None = None,
    locale: str | None = None,
    variant: str = "default",
) -> str:
    """Convenience: render the frozen S1 system prompt from the global registry."""
    return get_system_s1(tools, tool_names, locale, variant)


def list_stages() -> list[str]:
    """Convenience: list all registered stage keys."""
    return _registry.list_keys()


def get_prompt_version(key: str) -> str:
    """Convenience: get the version of a registered prompt."""
    return _registry.get_version(key)


def get_spec(key: str) -> PromptSpec:
    """Convenience: return the default-variant PromptSpec. Unknown keys raise KeyError."""
    return _registry.get_spec(key)


def build_user_message(
    role_instruction: str,
    user_content: str,
    memory_context: str = "",
    locale: str | None = None,
) -> str:
    """Build a user message with role instruction + content + optional context.

    Injects current system time so the model always knows the time.
    Uses i18n labels for the timestamp and context sections.
    Timestamp stays on the user suffix (FXC3: never move into S1).
    """
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
