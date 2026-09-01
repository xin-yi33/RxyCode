"""Docs-check: shipped module catalog + development-order (no hardcoded prose)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "docs" / "modules" / "catalog.yaml"
ORDER_PATH = REPO_ROOT / "docs" / "development-order.yaml"


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path.name} must be a mapping"
    return payload


def _tracked_root_packages(exclude: set[str]) -> set[str]:
    """First-party packages = tracked `<name>/__init__.py` at repo root."""
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT)
    names: set[str] = set()
    for rel in raw.split(b"\0"):
        if not rel:
            continue
        parts = Path(rel.decode("utf-8", "replace")).parts
        if len(parts) == 2 and parts[1] == "__init__.py" and parts[0] not in exclude:
            names.add(parts[0])
    return names


def test_inventory_lists_every_root_package_with_required_fields() -> None:
    catalog = _load_yaml(CATALOG_PATH)
    modules = catalog.get("modules")
    assert isinstance(modules, dict) and modules, "catalog.yaml must define modules"
    scan = catalog.get("scan") or {}
    exclude = {str(name) for name in (scan.get("exclude") or [])}
    on_disk = _tracked_root_packages(exclude)
    listed = set(modules)
    missing = sorted(on_disk - listed)
    extra_init = sorted(listed - on_disk)
    assert missing == [], f"catalog.yaml missing tracked packages: {missing}"
    assert extra_init == [], f"catalog.yaml lists packages with no tracked __init__.py: {extra_init}"
    required = ("purpose", "public_surface", "dependencies", "how_to_test")
    for name, entry in modules.items():
        assert isinstance(entry, dict), f"{name} entry must be a mapping"
        for field in required:
            value = entry.get(field)
            assert value, f"{name} is missing {field}"
        deps = entry["dependencies"]
        if isinstance(deps, dict):
            assert "inbound" in deps and "outbound" in deps, f"{name}.dependencies needs inbound/outbound"
        else:
            assert str(deps).strip() != ""


def test_development_order_marks_parallel_and_must_wait() -> None:
    order = _load_yaml(ORDER_PATH)
    must_wait = order.get("must_wait")
    parallel = order.get("parallel")
    assert isinstance(must_wait, list) and must_wait, "development-order.yaml needs must_wait"
    assert isinstance(parallel, list) and parallel, "development-order.yaml needs parallel groups"
    wait_blob = yaml.safe_dump(must_wait).lower()
    assert "adapter" in wait_blob or "architecture" in wait_blob
    oauth_after_adapter = False
    for row in must_wait:
        assert isinstance(row, dict)
        assert row.get("track") and row.get("predecessor"), row
        track = str(row["track"]).lower()
        pred = str(row["predecessor"]).lower()
        if "oauth" in track and "adapter" in pred:
            oauth_after_adapter = True
    assert oauth_after_adapter, "plugin OAuth must wait for the adapter contract"
    parallel_ok = False
    for group in parallel:
        assert isinstance(group, dict)
        tracks = group.get("tracks") or []
        if isinstance(tracks, list) and len(tracks) >= 2:
            parallel_ok = True
    assert parallel_ok, "order doc must mark at least one parallelizable set of tracks"
