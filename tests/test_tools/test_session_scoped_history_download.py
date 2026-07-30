from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_relative_download_path_uses_active_session_cwd(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.tools import file_download

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    session_cwd = tmp_path / "session-a"
    target_dir = session_cwd / "downloads"
    target_dir.mkdir(parents=True)
    response = httpx.Response(
        200,
        content=b"session-bound",
        request=httpx.Request("GET", "https://example.test/result.bin"),
    )

    async def fetch(*_args, **_kwargs):
        return response

    monkeypatch.setattr(file_download, "fetch_public_response", fetch)
    token = bind_session("download-session")
    try:
        set_working_directory(session_cwd)
        result = await file_download.download_file_async(
            "https://example.test/result.bin",
            save_path="downloads",
        )
    finally:
        reset_session_binding(token)

    from datetime import datetime

    target = tmp_path / "data" / "output" / datetime.now().strftime("%Y-%m-%d") / "downloads" / "result.bin"
    assert target.read_bytes() == b"session-bound"
    assert f"Saved to: {target}" in result
    assert not (target_dir / "result.bin").exists()
    assert not (Path.cwd() / "downloads" / "result.bin").exists()


def test_history_search_sees_global_and_current_session_only(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
    )
    from RxyCode.RxyCode1_1_0.tools.history_tool import search_history

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    global_dir = tmp_path / "memory" / "user"
    current_dir = tmp_path / "memory" / "sessions" / "session-a"
    other_dir = tmp_path / "memory" / "sessions" / "session-b"
    for directory in (global_dir, current_dir, other_dir):
        directory.mkdir(parents=True)
    (global_dir / "1.md").write_text("needle global-visible", encoding="utf-8")
    (current_dir / "auto_facts.md").write_text(
        "needle current-visible", encoding="utf-8"
    )
    (other_dir / "auto_facts.md").write_text(
        "needle other-session-secret", encoding="utf-8"
    )

    token = bind_session("session-a")
    try:
        result = search_history(query="needle", limit=10)
    finally:
        reset_session_binding(token)

    assert "global-visible" in result
    assert "current-visible" in result
    assert "other-session-secret" not in result
    assert "session-b" not in result
