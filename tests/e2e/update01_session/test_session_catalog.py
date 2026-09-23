"""layer=e2e FR-SS-E2E"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from RxyCode.RxyCode1_1_0.appserver.sessions import SessionStore
from RxyCode.RxyCode1_1_0.core.session_list import (
    SESSION_DEFAULT_TITLE,
    format_session_age,
    session_date_group,
)
from RxyCode.RxyCode1_1_0.core.session_title import maybe_generate_session_title

pytestmark = pytest.mark.e2e
REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def test_e2e_ss_01_new_session_listed_without_save_chat(tmp_path):
    store = SessionStore()
    rec = store.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    ids = [item.session_id for item in store.list()]
    assert rec.session_id in ids
    assert rec.title == SESSION_DEFAULT_TITLE
    src = Path(SessionStore.create.__code__.co_filename).read_text(encoding="utf-8")
    assert "ChatStorage" not in src.split("def create", 1)[1].split("def ", 1)[0]


def test_e2e_ss_02_llm_title_after_first_prompt():
    complete = MagicMock(return_value="鹅鹅骑自行车 SVG")
    got = maybe_generate_session_title(
        title_is_manual=False,
        generated_title=None,
        first_user="帮我做鹅鹅骑自行车页面",
        complete=complete,
    )
    assert got == "鹅鹅骑自行车 SVG"
    complete.assert_called_once()


def test_e2e_ss_03_manual_rename_not_overwritten(tmp_path):
    store = SessionStore()
    rec = store.create(tmp_path)
    rec = store.rename(rec.session_id, "手动会话名")
    complete = MagicMock(return_value="LLM不该出现")
    got = maybe_generate_session_title(
        title_is_manual=rec.title_is_manual,
        generated_title=rec.generated_title,
        first_user="hello",
        complete=complete,
    )
    assert rec.title == "手动会话名"
    assert rec.title_is_manual is True
    assert got is None
    complete.assert_not_called()


def test_e2e_ss_04_date_group_and_age():
    past = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    assert session_date_group(past, now=NOW) == "Sat Sep 12 2026"
    assert format_session_age(NOW - timedelta(days=6), now=NOW) == "6d"
    assert format_session_age(NOW, now=NOW) == "now"


def test_e2e_ss_05_list_keybinds_dispatch_rpc():
    key_ts = REPO / "frontend/opentui-app/src/dialog/sessionListKeybind.ts"
    assert key_ts.is_file(), "STOP: U50 sessionListKeybind.ts 未合入"
    body = key_ts.read_text(encoding="utf-8")
    assert "delete-pending" in body
    assert "delete-confirm" in body
    assert "pendingDelete" in body or body.find("delete-pending") < body.find("delete-confirm")
    assert "rename" in body and "pin" in body and "fork" in body
    assert "ctrl+shift" in body or "shift: true" in body or "shift === true" in body
    phase = (REPO / "docs/plans/opus5-plan/rxycode/PHASE-UPDATE-01.md").read_text(encoding="utf-8")
    for needle in ("SESSION_LIST_KEY_RENAME", "ctrl+r", "ctrl+d", "ctrl+f", "ctrl+shift+f"):
        assert needle in phase, needle


def test_e2e_ss_06_esc_closes():
    key_ts = REPO / "frontend/opentui-app/src/dialog/sessionListKeybind.ts"
    assert key_ts.is_file(), "STOP: U50 sessionListKeybind.ts 未合入"
    body = key_ts.read_text(encoding="utf-8")
    assert "close" in body
    assert "escape" in body.lower()


def test_e2e_ss_07_fork_parent_title_unchanged(tmp_path):
    store = SessionStore()
    parent = store.create(tmp_path, title="父会话")
    parent_title = parent.title
    child = store.fork(parent.session_id)
    parent_after = store.get(parent.session_id)
    assert parent_after is not None
    assert parent_after.title == parent_title
    ids = [item.session_id for item in store.list()]
    assert child.session_id in ids
    assert parent.session_id in ids


def test_e2e_ss_08_empty_window_hidden_from_catalog(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock
    from RxyCode.RxyCode1_1_0.appserver.server import AppServer

    server = AppServer(stub=True)
    server._initialized = True
    empty = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    used = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.note_user_prompt(used.session_id, "修登录页")
    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _request_id, payload: responses.append(payload))
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 1))
    ids = [row["session_id"] for row in responses[-1]["sessions"]]
    assert used.session_id in ids
    assert empty.session_id not in ids
    assert responses[-1]["sessions"][0]["display_title"] == "修登录页"
