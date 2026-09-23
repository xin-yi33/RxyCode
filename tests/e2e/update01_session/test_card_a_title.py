"""layer=e2e FR-SS-A 卡 A：session/prompt 立刻命名，sessions/list 显示 fallback。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.core.session_list import SESSION_DEFAULT_TITLE, display_title

pytestmark = pytest.mark.e2e
REPO = Path(__file__).resolve().parents[3]


def test_e2e_card_a_prompt_names_session_in_catalog(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    assert rec.title == SESSION_DEFAULT_TITLE
    server._respond = AsyncMock()
    server._run_prompt = AsyncMock(return_value=None)
    asyncio.run(
        server._handle_prompt(
            {"session_id": rec.session_id, "text": "修登录页的验证码"},
            1,
        )
    )

    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _rid, payload: responses.append(payload))
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 2))
    rows = responses[-1]["sessions"]
    assert rows[0]["session_id"] == rec.session_id
    assert rows[0]["display_title"] == "修登录页的验证码"
    assert rows[0]["display_title"] != SESSION_DEFAULT_TITLE
    src = (REPO / "appserver/server.py").read_text(encoding="utf-8")
    assert "maybe_generate_session_title" in src
    assert "note_user_prompt" in src
    assert "complete_session_title" in src
    assert "TITLE_REFRESH_TURN" in src


def test_e2e_card_a_old_prompt_event_backfills_title(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._task_store.append_event(
        rec.session_id,
        {
            "method": "session/prompt",
            "params": {"session_id": rec.session_id, "text": "帮我做鹅鹅骑自行车页面", "role": "user"},
        },
    )
    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _rid, payload: responses.append(payload))
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 1))
    rows = [row for row in responses[-1]["sessions"] if row["session_id"] == rec.session_id]
    assert rows
    assert rows[0]["display_title"] == "帮我做鹅鹅骑自行车页面"


def test_e2e_hidden_llm_title_then_third_turn_refresh(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.note_user_prompt(rec.session_id, "hi")
    for user, assistant in (
        ("hi", "hello"),
        ("修登录", "改了验证码"),
        ("再确认", "已修好"),
    ):
        server._task_store.append_event(
            rec.session_id, {"method": "session/prompt", "params": {"text": user}}
        )
        server._task_store.append_event(
            rec.session_id, {"method": "event/final", "params": {"text": assistant}}
        )
    server._session_title_complete = lambda _system, user: (
        "登录验证码修复" if user.startswith("User:") else "Start conversation"
    )
    asyncio.run(server._maybe_title_session(rec.session_id, 1))
    got = server._sessions.get(rec.session_id)
    assert got is not None
    assert display_title(got) == "Start conversation"
    asyncio.run(server._maybe_title_session(rec.session_id, 3))
    got = server._sessions.get(rec.session_id)
    assert got is not None
    assert got.generated_title == "登录验证码修复"
    assert got.title_source == "llm"
    events, _, _ = server._task_store.events(rec.session_id, 0)
    assert all("You name a coding-agent session" not in str(item) for item in events)
    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _rid, payload: responses.append(payload))
    asyncio.run(server._handle_sessions_list({"include_trashed": False}, 9))
    rows = [row for row in responses[-1]["sessions"] if row["session_id"] == rec.session_id]
    assert rows[0]["display_title"] == "登录验证码修复"
