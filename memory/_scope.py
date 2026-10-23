"""Scoped memory root for web turns (FR-PROJECT-03).

The worker passes ``RXYCODE_MEMORY_ROOT`` (a durable, tenant-scoped dir
mounted into the confined turn) and ``RXYCODE_MEMORY_KEY`` (the
experience-record owner: ``users:<actor>`` or ``projects:<project>``).
Outside web turns both envs are unset and memory stays under
``<data>/memory`` exactly as before — CLI behaviour is unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir


def memory_root() -> Path:
    """Base dir for the persistent memory subtree (replaces <data>/memory)."""
    env = os.environ.get("RXYCODE_MEMORY_ROOT", "").strip()
    if env:
        root = Path(env)
        root.mkdir(parents=True, exist_ok=True)
        return root
    return get_data_dir() / "memory"


def memory_key(default: str) -> str:
    """Owner key for experience records — scope id, else the caller's default."""
    return os.environ.get("RXYCODE_MEMORY_KEY", "").strip() or default


def memory_mode() -> str:
    """default | project_only — informational; scoping is done via root/key."""
    return os.environ.get("RXYCODE_MEMORY_MODE", "").strip() or "default"
