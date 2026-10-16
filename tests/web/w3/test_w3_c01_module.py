"""WEB-W3-C01. The web build reuses a pure desktop component and no Electron host."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_UNIT = Path(__file__).with_name("test_w3_c01_unit.py")
_spec = importlib.util.spec_from_file_location("w3c01_unit_build", _UNIT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_w3_c01_integration() -> None:
    """Building the web app pulls in sessionVisualState and not Electron or node builtins."""
    dist = _mod.build_web()
    text = _mod.bundle_text(dist)
    for needle in _mod._FORBIDDEN:
        assert needle not in text, needle
    sources: list[str] = []
    maps = list(dist.rglob("*.map"))
    assert maps, "vite build did not emit a sourcemap"
    for path in maps:
        sources.extend(json.loads(path.read_text(encoding="utf-8")).get("sources", []))
    assert any(str(source).endswith("sessionVisualState.ts") for source in sources), sources
    joined = "\n".join(str(source) for source in sources)
    assert "electron" not in joined.lower()
    assert "preload" not in joined.lower()
    assert "child_process" not in joined
    assert "node:fs" not in joined
