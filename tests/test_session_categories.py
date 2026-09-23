"""GX20-B path A: consume B5 pin/deleted_at and GX8 thread/pin. No new methods."""

from __future__ import annotations

from pathlib import Path

from appserver.server import AppServer
from appserver.sessions import (
    AppSessionRecord,
    is_placeholder_title,
    title_from_first_prompt,
)


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


def test_placeholder_title_becomes_first_sentence() -> None:
    assert is_placeholder_title("新任务") is True
    assert is_placeholder_title("New task") is True
    assert is_placeholder_title("会话 abcdef12") is True
    assert is_placeholder_title("修复登录") is False
    assert title_from_first_prompt("没什么，只是打个招呼。后面还有一句") == "没什么，只是打个招呼"
