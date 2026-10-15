"""WEB-W0-C01 integration: real gitignore, real Web docs, secrets stay ignored."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w0_c01_integration():
    """Given the repo gitignore, Web docs are trackable and leftover secrets are not."""
    report = _scanner().tracking_status(REPO)
    assert report["web_doc_ignored"] is False
    assert report["plans_archive_ignored"] is True
    assert report["secret_ignored"] is True
    assert report["legacy_plan_tree_ignored"] is True
    assert report["web_local_env_ignored"] is True
    assert report["web_local_credentials_ignored"] is True
    assert report["web_local_archive_ignored"] is True
    assert report["web_local_secrets_ignored"] is True
