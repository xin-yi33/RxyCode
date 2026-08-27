"""GX20-B path A: consume B5 pin/deleted_at and GX8 thread/pin. No new methods."""

from __future__ import annotations

from pathlib import Path

from appserver.server import AppServer
from appserver.sessions import AppSessionRecord


def categorize(record: AppSessionRecord, *, has_project: bool) -> str:
    if record.pinned:
        return "pinned"
    if has_project:
        return "project"
    return "recent"


def test_pin_deleted_and_three_categories(tmp_path: Path) -> None:
    server = AppServer(stub=True)
    record = server._sessions.create(tmp_path, title="s")
    assert record.deleted_at is None
    assert record.pinned is False
    assert categorize(record, has_project=False) == "recent"
    assert categorize(record, has_project=True) == "project"
    server._thread_fork.pin(record.session_id, pinned=True)
    assert record.pinned is True
    assert categorize(record, has_project=True) == "pinned"


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
