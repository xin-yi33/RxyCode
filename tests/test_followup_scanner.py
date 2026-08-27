"""GX18-B: rule-based follow-up scanner, zero LLM, max 3, once per turn."""

from __future__ import annotations

from pathlib import Path

from appserver.followup_scanner import FollowupScanner
from appserver.server import AppServer


def test_rules_cap_dedupe_and_once_per_turn(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("TODO: later\nprint(1)\n", encoding="utf-8")
    scanner = FollowupScanner()
    first = scanner.scan(tmp_path, turn_id="t1")
    assert len(first) <= 3
    rules = [item["rule"] for item in first]
    assert "missing_tests" in rules
    assert "leftover_todo" in rules
    assert len(rules) == len(set(rules))
    again = scanner.scan(tmp_path, turn_id="t1")
    assert again == []
    second_turn = scanner.scan(tmp_path, turn_id="t2")
    assert second_turn


def test_appserver_has_scanner() -> None:
    server = AppServer(stub=True)
    assert isinstance(server._followup, FollowupScanner)


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
