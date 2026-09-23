"""layer=e2e FR-SS-C 卡 C：无用户对话的窗口不出现在 sessions/list。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.core.session_list import SESSION_DEFAULT_TITLE

pytestmark = pytest.mark.e2e


def test_e2e_card_c_empty_window_hidden_from_catalog(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    empty = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    used = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.note_user_prompt(used.session_id, "修登录页")
    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _rid, payload: responses.append(payload))
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 1))
    ids = [row["session_id"] for row in responses[-1]["sessions"]]
    assert used.session_id in ids
    assert empty.session_id not in ids
    assert responses[-1]["sessions"][0]["display_title"] == "修登录页"


def test_e2e_card_c_pinned_empty_still_listed(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    rec.pinned = True
    server._sessions._persist(rec)
    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _rid, payload: responses.append(payload))
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 1))
    ids = [row["session_id"] for row in responses[-1]["sessions"]]
    assert rec.session_id in ids
