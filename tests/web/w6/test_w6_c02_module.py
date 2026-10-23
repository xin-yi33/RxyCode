"""WEB-W6-C02. A missing language server does not invent references."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_CORE = REPO / "packages" / "rxycode-core" / "src"
for _entry in (REPO, _CORE):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def test_w6_c02_integration() -> None:
    """cobol has no language server, so references stay empty."""
    from rxycode_core.tools.coding_workflow import references

    result = references(language="cobol", workspace=str(REPO), file_path="sample.cbl")
    assert result["status"] == "unavailable"
    assert result["locations"] == []
    assert "cobol" in result["reason"].lower()
    assert "unavailable" in result["reason"].lower()
    blob = str(result)
    assert "sample.cbl:" not in blob
    assert "line" not in result["reason"].lower()
