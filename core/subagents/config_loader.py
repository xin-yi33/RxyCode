"""Agent definition config loaders (JSON, Markdown, YAML).

All loaders produce a raw dict that is then normalized by ``normalize_raw_config``
before being validated by ``validate_agent_definition``.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Raw config dict type (before validation)
# ---------------------------------------------------------------------------

AgentDefDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ConfigLoadError(ValueError):
    """Raised when a config file cannot be parsed."""

    def __init__(self, message: str, *, path: str = ""):
        super().__init__(message)
        self.path = path


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def load_agent_from_json(text: str) -> AgentDefDict:
    """Parse a JSON agent definition.

    Raises ConfigLoadError on invalid JSON or non-object root.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigLoadError("JSON agent definition must be a JSON object")

    return data


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_agent_from_yaml(text: str) -> AgentDefDict:
    """Parse a YAML agent definition.

    Raises ConfigLoadError on invalid YAML or non-mapping root.
    """
    try:
        import yaml
    except ImportError:
        raise ConfigLoadError(
            "PyYAML is required for YAML agent definitions. "
            "Install with: pip install pyyaml"
        ) from None

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigLoadError("YAML agent definition must be a mapping")

    return data


# ---------------------------------------------------------------------------
# Markdown (frontmatter) loader
# ---------------------------------------------------------------------------

_YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def load_agent_from_markdown(text: str) -> AgentDefDict:
    """Parse a Markdown agent definition with YAML frontmatter.

    The frontmatter (between ``---`` delimiters) contains the agent config.
    The Markdown body becomes the ``prompt`` field if not already set.

    Raises ConfigLoadError on missing/invalid frontmatter.
    """
    match = _YAML_FRONTMATTER_RE.match(text)
    if not match:
        raise ConfigLoadError(
            "Markdown agent definition must have YAML frontmatter delimited by '---'"
        )

    frontmatter_text = match.group(1)
    body = text[match.end():].strip()

    data = load_agent_from_yaml(frontmatter_text)

    # Use Markdown body as prompt unless frontmatter already specifies one
    if "prompt" not in data and body:
        data["prompt"] = body

    return data


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_raw_config(raw: AgentDefDict) -> AgentDefDict:
    """Normalize a raw agent definition dict to canonical form.

    This is the single choke-point where format-specific quirks are resolved
    before validation. All loaders (JSON, Markdown, YAML) must pass through here.
    """

    normalized: dict[str, Any] = {}

    # -- simple passthrough fields --------------------------------------------

    for field in ("id", "description", "mode", "model", "steps", "prompt"):
        if field in raw:
            normalized[field] = raw[field]

    # -- hidden (bool) --------------------------------------------------------

    if "hidden" in raw:
        normalized["hidden"] = bool(raw["hidden"])

    # -- subagent_depth (int) -------------------------------------------------

    if "subagent_depth" in raw:
        try:
            normalized["subagent_depth"] = int(raw["subagent_depth"])
        except (TypeError, ValueError):
            normalized["subagent_depth"] = raw["subagent_depth"]  # let validation catch it

    # -- workspace_scope ------------------------------------------------------

    if "workspace_scope" in raw:
        normalized["workspace_scope"] = str(raw["workspace_scope"])

    # -- permission -----------------------------------------------------------

    if "permission" in raw:
        perm = raw["permission"]
        if isinstance(perm, str):
            # Shorthand: "allow" / "deny" / "ask" → all tools same verdict
            normalized["permission"] = {
                "read": perm,
                "edit": perm,
                "bash": perm,
                "task": perm,
            }
        elif isinstance(perm, dict):
            normalized["permission"] = dict(perm)
        else:
            normalized["permission"] = perm

    # -- EXPLICITLY reject top-level task_permission --------------------------

    # Pass through raw so validate_agent_definition can detect and reject it.
    # normalize_raw_config must NOT silently drop or merge this field.
    if "task_permission" in raw:
        normalized["task_permission"] = raw["task_permission"]

    # -- extra unknown fields -------------------------------------------------

    known = {
        "id", "description", "mode", "model", "steps", "prompt", "permission",
        "hidden", "subagent_depth", "workspace_scope", "task_permission",
    }
    for key, value in raw.items():
        if key not in known:
            normalized[key] = value

    return normalized


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(file_path: str) -> str:
    """Detect the config format from a file extension.

    Returns: 'json', 'yaml', or 'markdown'.
    """
    suffix = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if suffix in ("yaml", "yml"):
        return "yaml"
    if suffix == "md":
        return "markdown"
    return "json"
