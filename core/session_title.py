"""Hidden session title: first-prompt placeholder, then LLM name, refresh at turn 3."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Iterable

SESSION_TITLE_MAX_CHARS = 40  # 与 §5.11 同一数字
TITLE_REFRESH_TURN = 3
TITLE_DIALOGUE_MAX_CHARS = 2000
TITLE_COMPLETE_TIMEOUT = 8.0

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "session_title.md"
SESSION_TITLE_SYSTEM = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_LOG = logging.getLogger("rxycode.session_title")


def fallback_title(first_user: str) -> str:
    blob = " ".join((first_user or "").split())
    if not blob:
        return ""
    return blob[:SESSION_TITLE_MAX_CHARS]


def sanitize_title(raw: str) -> str:
    text = (raw or "").strip().strip("\"'“”`")
    if not text:
        return ""
    text = " ".join(text.splitlines()[0].split())
    lowered = text.casefold()
    for prefix in ("title:", "标题:", "标题："):
        if lowered.startswith(prefix.casefold()):
            text = text[len(prefix) :].strip()
            break
    text = text.strip(" .。;；")
    return text[:SESSION_TITLE_MAX_CHARS]


def user_turn_count(events: Iterable[dict[str, Any]]) -> int:
    n = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("method") not in {"session/prompt", "event/user_message"}:
            continue
        params = ev.get("params") if isinstance(ev.get("params"), dict) else {}
        if str(params.get("text") or params.get("content") or "").strip():
            n += 1
    return n


def format_title_dialogue(
    events: Iterable[dict[str, Any]],
    *,
    max_rounds: int = TITLE_REFRESH_TURN,
    max_chars: int = TITLE_DIALOGUE_MAX_CHARS,
) -> str:
    """User + assistant finals only. Tools and token deltas stay out."""
    rounds: list[tuple[str, str]] = []
    pending_user = ""
    for ev in events:
        if not isinstance(ev, dict):
            continue
        method = str(ev.get("method") or "")
        params = ev.get("params") if isinstance(ev.get("params"), dict) else {}
        if method in {"session/prompt", "event/user_message"}:
            text = str(params.get("text") or params.get("content") or "").strip()
            if text:
                pending_user = text
            continue
        if method == "event/final" and pending_user:
            assistant = str(params.get("text") or "").strip()
            rounds.append((pending_user, assistant))
            pending_user = ""
    if pending_user:
        rounds.append((pending_user, ""))
    chosen = rounds[-max_rounds:]
    lines: list[str] = []
    for user, assistant in chosen:
        lines.append(f"User: {user}")
        if assistant:
            lines.append(f"Assistant: {assistant}")
    blob = "\n".join(lines)
    return blob[:max_chars]


def maybe_generate_session_title(
    *,
    title_is_manual: bool,
    generated_title: str | None,
    first_user: str,
    complete: Callable[[str, str], str],
    force: bool = False,
) -> str | None:
    if title_is_manual:
        return None
    if not force and (generated_title or "").strip():
        return None
    try:
        raw = (complete(SESSION_TITLE_SYSTEM, first_user) or "").strip()
    except Exception:
        raw = ""
    title = sanitize_title(raw)
    return title or None


def _active_model_config() -> dict:
    try:
        from config.settings import get_active_model_config
    except ImportError:
        from RxyCode.RxyCode1_1_0.config.settings import get_active_model_config

    return get_active_model_config()


def complete_session_title(system: str, user: str) -> str:
    """One-shot chat completion. Not a turn, not streamed, not persisted."""
    import httpx

    try:
        from config.model_endpoint import llm_endpoint_url
    except ImportError:
        from RxyCode.RxyCode1_1_0.config.model_endpoint import llm_endpoint_url

    cfg = _active_model_config()
    api_key = str(cfg.get("api_key") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    model = str(cfg.get("model_name") or "").strip()
    if not api_key or not base_url or not model:
        return ""
    url = llm_endpoint_url(
        base_url,
        "openai_chat",
        require_https=False,
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 64,
        "temperature": 0.2,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=TITLE_COMPLETE_TIMEOUT) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        _LOG.warning("hidden session title complete failed: %s", type(exc).__name__)
        return ""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()
