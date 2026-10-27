"""Normalize proxy bypass environment variables for httpx compatibility.

Why this exists (2026-10-23)
----------------------------
``httpx`` builds its no-proxy mount table by feeding every ``NO_PROXY`` entry
through ``httpx._utils.URLPattern``.  A *bare bracketed IPv6 literal* such as
``[::1]`` is not a valid URL pattern, so construction raises::

    httpx.InvalidURL: Invalid port: ':1]'

Because ``openai`` / ``langchain_openai`` build an ``httpx`` client during
``ChatOpenAI(...)`` construction, a single ``[::1]`` entry in the host
environment makes **every** model client fail before the first request —
``AgentV2()`` cannot even be constructed.

Many proxy managers (Clash, v2rayN, Proxifier, corporate MDM policies) write
``NO_PROXY`` containing ``[::1]``.  The value is semantically correct for
curl and browsers, so the environment is not "wrong"; only httpx rejects it.
The bare form ``::1`` is accepted, and ``[::1]:8080`` (with an explicit port)
is accepted too — only the port-less bracketed form breaks.

This module rewrites those entries once, early, so the rest of the process
sees an equivalent bypass list that every HTTP stack can parse.  It is
idempotent, never raises, and is a no-op on machines with clean settings.
"""

from __future__ import annotations

import logging
import os
import re

_logger = logging.getLogger(__name__)

#: ``[<ipv6>]`` with no ``:port`` suffix — the shape httpx rejects.
_BRACKETED_IPV6_ONLY = re.compile(r"^\[([0-9A-Fa-f:.]+)\]$")

_PROXY_BYPASS_VARS = ("NO_PROXY", "no_proxy")


def _normalize_entry(entry: str) -> str:
    """Return an httpx-safe equivalent for one bypass entry."""
    match = _BRACKETED_IPV6_ONLY.match(entry)
    if match:
        # "[::1]" -> "::1".  Same semantics for bypass matching, and it is
        # the form httpx/openai accept.
        return match.group(1)
    return entry


def normalize_no_proxy_value(value: str) -> tuple[str, list[str]]:
    """Normalize one ``NO_PROXY`` value.

    Returns the rewritten value plus the list of entries that were changed,
    so callers can log or assert on the transformation.  Empty entries and
    stray whitespace are dropped, which also keeps httpx from choking on
    ",," sequences.
    """
    if not value:
        return value, []

    changed: list[str] = []
    kept: list[str] = []
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        fixed = _normalize_entry(entry)
        if fixed != entry:
            changed.append(f"{entry}->{fixed}")
        kept.append(fixed)

    normalized = ",".join(kept)
    if normalized == value:
        return value, []
    return normalized, changed


def sanitize_no_proxy_env(*, environ: dict[str, str] | None = None) -> list[str]:
    """Rewrite ``NO_PROXY`` / ``no_proxy`` in place to httpx-safe forms.

    Returns a list of human-readable change descriptions (empty when the
    environment was already clean).  Never raises: a broken environment is
    exactly the situation this function is meant to survive.
    """
    env = os.environ if environ is None else environ
    applied: list[str] = []
    for name in _PROXY_BYPASS_VARS:
        try:
            current = env.get(name)
            if not current:
                continue
            normalized, changed = normalize_no_proxy_value(current)
            if not changed:
                continue
            env[name] = normalized
            applied.append(f"{name}: {', '.join(changed)}")
        except Exception as exc:  # pragma: no cover - defensive
            _logger.debug("NO_PROXY normalization skipped for %s: %s", name, exc)
    for line in applied:
        _logger.debug("normalized proxy bypass env: %s", line)
    return applied
