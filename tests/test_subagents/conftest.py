"""Shared fixtures for Phase B subagent tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def project_root():
    """Return the repository root as a Path."""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def fresh_test_dir(tmp_path):
    """An empty writable directory for workspace-scope tests."""
    return tmp_path
