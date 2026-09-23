"""layer=unit FR-SS-2 FR-SS-D"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from RxyCode.RxyCode1_1_0.core.session_title import (
    SESSION_TITLE_MAX_CHARS,
    complete_session_title,
    fallback_title,
    format_title_dialogue,
    maybe_generate_session_title,
    sanitize_title,
    user_turn_count,
)


def test_fallback_truncates():
    assert fallback_title("a" * 80) == "a" * SESSION_TITLE_MAX_CHARS
    assert fallback_title("  你好  世界  ") == "你好 世界"


def test_sanitize_title_strips_wrappers():
    assert sanitize_title('  "修登录验证码"  ') == "修登录验证码"
    assert sanitize_title("Title: Fix login\nmore") == "Fix login"


def test_manual_never_calls_llm():
    complete = MagicMock(return_value="SHOULD_NOT")
    assert maybe_generate_session_title(
        title_is_manual=True, generated_title=None, first_user="修登录", complete=complete,
    ) is None
    complete.assert_not_called()


def test_existing_generated_skips():
    complete = MagicMock(return_value="new")
    assert maybe_generate_session_title(
        title_is_manual=False, generated_title="旧标题", first_user="修登录", complete=complete,
    ) is None
    complete.assert_not_called()


def test_force_refresh_calls_even_with_generated():
    complete = MagicMock(return_value="登录页验证码")
    got = maybe_generate_session_title(
        title_is_manual=False,
        generated_title="hi",
        first_user="User: hi\nAssistant: hello\nUser: 修登录\nAssistant: 改完了",
        complete=complete,
        force=True,
    )
    assert got == "登录页验证码"
    complete.assert_called_once()


def test_llm_failure_returns_none_keeps_placeholder():
    def boom(*_a, **_k):
        raise RuntimeError("no key")
    got = maybe_generate_session_title(
        title_is_manual=False, generated_title=None, first_user="鹅鹅骑自行车 SVG 动画页面开发", complete=boom,
    )
    assert got is None


def test_dialogue_is_three_user_assistant_rounds():
    events = [
        {"method": "session/prompt", "params": {"text": "hi"}},
        {"method": "event/tool_begin", "params": {"call_id": "c1"}},
        {"method": "event/final", "params": {"text": "hello", "thinking": "secret"}},
        {"method": "session/prompt", "params": {"text": "修登录"}},
        {"method": "event/final", "params": {"text": "改验证码"}},
        {"method": "session/prompt", "params": {"text": "再看看"}},
        {"method": "event/final", "params": {"text": "好了"}},
    ]
    assert user_turn_count(events) == 3
    blob = format_title_dialogue(events)
    assert "User: hi" in blob
    assert "Assistant: hello" in blob
    assert "User: 修登录" in blob
    assert "Assistant: 改验证码" in blob
    assert "User: 再看看" in blob
    assert "thinking" not in blob
    assert "tool_begin" not in blob
    assert "secret" not in blob


def test_prompt_file_locked():
    repo = Path(__file__).resolve().parents[2]
    body = (repo / "core/prompts/session_title.md").read_text(encoding="utf-8")
    assert body.startswith("You name a coding-agent session.")
    assert "Never mention tools" in body
    assert "multi-turn transcript" in body


def test_prompt_success_calls_title_helper():
    import inspect
    from RxyCode.RxyCode1_1_0.appserver import server as server_mod
    from RxyCode.RxyCode1_1_0.core.session_title import maybe_generate_session_title

    src = inspect.getsource(server_mod)
    assert "maybe_generate_session_title" in src
    assert "complete_session_title" in src
    assert "_title_tasks" in src
    assert "compact_summarizer" not in inspect.getsource(maybe_generate_session_title)
    assert "compact_summarizer" not in inspect.getsource(complete_session_title)


def test_complete_session_title_posts_hidden_chat_completion():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "修登录验证码"}}]}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def post(self, url, headers, json):
            assert "/chat/completions" in url
            assert json["stream"] is False
            assert json["messages"][0]["role"] == "system"
            assert "Authorization" in headers
            self.payload = json
            return _Resp()

    cfg = {
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "model_name": "demo-model",
    }
    with patch(
        "RxyCode.RxyCode1_1_0.core.session_title._active_model_config",
        return_value=cfg,
    ), patch("httpx.Client", _Client):
        got = complete_session_title("sys", "hi")
    assert got == "修登录验证码"
