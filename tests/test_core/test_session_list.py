"""layer=unit FR-SS-1 FR-SS-3"""
from datetime import datetime, timedelta, timezone
from RxyCode.RxyCode1_1_0.core.session_list import (
    DATE_GROUP_PINNED,
    DATE_GROUP_TODAY,
    DATE_GROUP_YESTERDAY,
    SESSION_DEFAULT_TITLE,
    display_title,
    format_session_age,
    session_date_group,
    session_list_visible,
)


def test_age_labels():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    assert format_session_age(now, now=now) == "now"
    assert format_session_age(now - timedelta(seconds=59), now=now) == "now"
    assert format_session_age(now - timedelta(minutes=7), now=now) == "7m"
    assert format_session_age(now - timedelta(hours=4), now=now) == "4h"
    assert format_session_age(now - timedelta(days=6), now=now) == "6d"
    assert format_session_age(now - timedelta(days=60), now=now) == "2mo"


def test_date_groups_english_tables():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    assert session_date_group(now, now=now) == DATE_GROUP_TODAY
    assert session_date_group(now - timedelta(days=1), now=now) == DATE_GROUP_YESTERDAY
    assert session_date_group(datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc), now=now) == "Sat Sep 12 2026"
    assert session_date_group(now, now=now, pinned=True) == DATE_GROUP_PINNED


def test_display_title_manual_wins():
    rec = type("R", (), {
        "title": "手动名",
        "generated_title": "LLM名",
        "title_is_manual": True,
    })()
    assert display_title(rec) == "手动名"
    rec.title_is_manual = False
    assert display_title(rec) == "LLM名"
    rec.generated_title = ""
    rec.title = SESSION_DEFAULT_TITLE
    rec.last_user_prompt = "帮我改桌面 blog 的联系方式"
    assert display_title(rec) == "帮我改桌面 blog 的联系方式"
    rec.last_user_prompt = ""
    assert display_title(rec) == SESSION_DEFAULT_TITLE
    assert SESSION_DEFAULT_TITLE == "新任务"


def test_hidden_child_and_trashed():
    ok = type("R", (), {"trashed_at": None, "parent_session_id": None, "forked_from": "abc"})()
    child = type("R", (), {"trashed_at": None, "parent_session_id": "p1", "forked_from": None})()
    trash = type("R", (), {"trashed_at": "2026-09-15T00:00:00Z", "parent_session_id": None, "forked_from": None})()
    assert session_list_visible(ok) is True
    assert session_list_visible(child) is False
    assert session_list_visible(trash) is False


def test_empty_without_user_turn_hidden():
    empty = type("R", (), {
        "trashed_at": None,
        "parent_session_id": None,
        "title_is_manual": False,
        "pinned": False,
        "forked_from": None,
    })()
    assert session_list_visible(empty, has_user_turn=False) is False
    assert session_list_visible(empty, has_user_turn=True) is True
    pinned = type("R", (), {
        "trashed_at": None,
        "parent_session_id": None,
        "title_is_manual": False,
        "pinned": True,
        "forked_from": None,
    })()
    assert session_list_visible(pinned, has_user_turn=False) is True


"""layer=module FR-SS-1"""
import inspect
from RxyCode.RxyCode1_1_0.appserver.sessions import SessionStore
from RxyCode.RxyCode1_1_0.appserver.server import AppServer


def test_create_appears_in_list_without_save_chat(tmp_path):
    store = SessionStore()
    rec = store.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    ids = [r.session_id for r in store.list()]
    assert rec.session_id in ids
    src = inspect.getsource(SessionStore.create)
    assert "ChatStorage" not in src
    assert "save-chat" not in src.lower()


def test_session_summary_additive_keys():
    src = inspect.getsource(AppServer._session_summary)
    for key in ("display_title", "age_label", "date_group", "title_is_manual", "generated_title"):
        assert key in src, key
    assert "session_list_row" in src or "format_session_age" in src


def test_rename_marks_manual(tmp_path):
    store = SessionStore()
    rec = store.create(tmp_path)
    rec = store.rename(rec.session_id, "鹅鹅骑自行车")
    assert rec.title == "鹅鹅骑自行车"
    assert rec.title_is_manual is True
    assert rec.updated_at


def test_note_user_prompt_sets_fallback_title(tmp_path):
    store = SessionStore()
    rec = store.create(tmp_path, title=SESSION_DEFAULT_TITLE)
    rec = store.note_user_prompt(rec.session_id, "帮我改桌面 blog 的联系方式")
    assert rec is not None
    assert rec.last_user_prompt.startswith("帮我改桌面")
    assert rec.title == "帮我改桌面 blog 的联系方式"
    assert rec.title_is_manual is False
    rec = store.rename(rec.session_id, "手动名")
    store.note_user_prompt(rec.session_id, "第二句不该覆盖")
    assert store.get(rec.session_id).title == "手动名"
