"""layer=module FR-SS-A FR-SS-D 卡 A/D：首句占位，隐藏 LLM 命名，第三轮再总结。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.core.session_list import SESSION_DEFAULT_TITLE, display_title


def test_handle_prompt_sets_fallback_title_immediately(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._respond = AsyncMock()
    server._run_prompt = AsyncMock(return_value=None)

    asyncio.run(
        server._handle_prompt(
            {"session_id": rec.session_id, "text": "帮我改桌面 blog 的联系方式"},
            1,
        )
    )
    got = server._sessions.get(rec.session_id)
    assert got is not None
    assert got.last_user_prompt.startswith("帮我改桌面")
    assert got.title == "帮我改桌面 blog 的联系方式"
    assert got.title_is_manual is False
    assert display_title(got) == "帮我改桌面 blog 的联系方式"
    server._run_prompt.assert_awaited()


def test_hidden_llm_overwrites_fallback_title(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.note_user_prompt(rec.session_id, "hi")
    server._session_title_complete = lambda _system, _user: "Start conversation"
    asyncio.run(server._maybe_title_session(rec.session_id, 1))
    got = server._sessions.get(rec.session_id)
    assert got is not None
    assert got.generated_title == "Start conversation"
    assert got.title == "Start conversation"
    assert got.title_source == "llm"
    assert got.title_llm_pass == 1
    assert display_title(got) == "Start conversation"


def test_third_turn_refresh_uses_dialogue(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.apply_generated_title(
        rec.session_id, "hi", source="llm", title_llm_pass=1
    )
    for user, assistant in (
        ("hi", "hello"),
        ("修登录", "改了验证码"),
        ("再确认下", "已修好"),
    ):
        server._task_store.append_event(
            rec.session_id, {"method": "session/prompt", "params": {"text": user}}
        )
        server._task_store.append_event(
            rec.session_id, {"method": "event/final", "params": {"text": assistant}}
        )
    seen: list[str] = []

    def complete(_system: str, user: str) -> str:
        seen.append(user)
        return "登录验证码修复"

    server._session_title_complete = complete
    asyncio.run(server._maybe_title_session(rec.session_id, 3))
    got = server._sessions.get(rec.session_id)
    assert got is not None
    assert got.generated_title == "登录验证码修复"
    assert got.title_llm_pass == 3
    assert seen and "User: hi" in seen[0]
    assert "Assistant: 已修好" in seen[0]
    events, _, _ = server._task_store.events(rec.session_id, 0)
    methods = [item["method"] for item in events]
    assert "event/message_delta" not in methods
    assert all("You name a coding-agent session" not in str(item) for item in events)


def test_third_prompt_titles_in_parallel_with_running_job(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.apply_generated_title(
        rec.session_id, "hi", source="llm", title_llm_pass=1
    )
    for user in ("hi", "修登录"):
        server._task_store.append_event(
            rec.session_id, {"method": "session/prompt", "params": {"text": user}}
        )
        server._task_store.append_event(
            rec.session_id, {"method": "event/final", "params": {"text": "ok"}}
        )
    server._respond = AsyncMock()
    running = asyncio.Event()

    async def slow_prompt(**_kwargs):
        running.set()
        await asyncio.sleep(1.0)
        return None

    server._run_prompt = slow_prompt
    server._session_title_complete = lambda _system, user: (
        "登录验证码修复" if user.startswith("User:") else "Start conversation"
    )

    async def scenario():
        prompt = asyncio.create_task(
            server._handle_prompt(
                {"session_id": rec.session_id, "text": "再确认"},
                3,
            )
        )
        await running.wait()
        for _ in range(50):
            got = server._sessions.get(rec.session_id)
            if got is not None and got.generated_title == "登录验证码修复":
                break
            await asyncio.sleep(0.02)
        mid = server._sessions.get(rec.session_id)
        assert mid is not None
        assert mid.generated_title == "登录验证码修复"
        assert mid.title_llm_pass == 3
        assert prompt.done() is False
        await prompt

    asyncio.run(scenario())


def test_manual_rename_survives_prompt(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    rec = server._sessions.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    server._sessions.rename(rec.session_id, "手动会话名")
    server._respond = AsyncMock()
    server._run_prompt = AsyncMock(return_value=None)
    asyncio.run(
        server._handle_prompt(
            {"session_id": rec.session_id, "text": "第二句不该覆盖标题"},
            2,
        )
    )
    got = server._sessions.get(rec.session_id)
    assert got is not None
    assert got.title == "手动会话名"
    assert got.title_is_manual is True
