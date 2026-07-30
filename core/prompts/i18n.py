"""Multi-language text packs for prompt rendering.

Locale is read from config (``config.yaml`` -> ``language`` field).
Default locale is ``"zh"``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Language packs
# ---------------------------------------------------------------------------

I18N_TEXTS: dict[str, dict[str, str]] = {
    "zh": {
        "language_requirement": (
            "语言要求: 始终使用中文回复用户。即使用户使用英文提问，也使用中文回答。"
            "代码注释使用中文。"
        ),
        "time_label": "当前时间",
        "context_label": "对话上下文",
        "role_label": "角色",
        "tool_usage_intro": (
            "工具使用: 你可以使用以下工具完成任务。需要时主动调用工具。"
        ),
    },
    "en": {
        "language_requirement": (
            "Language requirement: Always respond in English. "
            "Use English for code comments."
        ),
        "time_label": "Current time",
        "context_label": "Conversation Context",
        "role_label": "Role",
        "tool_usage_intro": (
            "Tool usage: You can use the following tools to complete tasks. "
            "Call tools proactively when needed."
        ),
    },
}

SUPPORTED_LOCALES = tuple(I18N_TEXTS.keys())


def get_locale() -> str:
    """Read locale from config, defaulting to ``"zh"``.

    The config key is ``language`` (set in ``config.yaml``).
    """
    try:
        from RxyCode.RxyCode1_1_0.config.settings import load_config
        cfg = load_config() or {}
        locale = cfg.get("language", "zh")
        if locale not in I18N_TEXTS:
            locale = "zh"
        return locale
    except Exception:
        return "zh"


def t(key: str, locale: str | None = None) -> str:
    """Translate a key for the given locale (or the config default)."""
    if locale is None:
        locale = get_locale()
    pack = I18N_TEXTS.get(locale, I18N_TEXTS["zh"])
    return pack.get(key, key)
