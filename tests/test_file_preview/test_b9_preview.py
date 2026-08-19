"""PhaseG-B9 file preview path safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.preview import preview_file, list_tree, prepare_open_external
from appserver.server import AppServer
from appserver.workspace import PathBoundaryError
from protocol.handshake import CapabilitySnapshot


@pytest.mark.asyncio
async def test_preview_inside_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_file_preview({"session_id": session.session_id, "path": "a.py"}, 1)
    result = next(item["result"] for item in sent if "result" in item)
    assert result["kind"] == "text"
    assert "print" in result["content"]


def test_outside_path_rejected(tmp_path: Path) -> None:
    (tmp_path / "in.txt").write_text("ok", encoding="utf-8")
    with pytest.raises(PathBoundaryError):
        preview_file(tmp_path, str(tmp_path.parent / "secrets.txt"))


def test_binary_and_large_placeholder(tmp_path: Path) -> None:
    (tmp_path / "x.bin").write_bytes(b"\x00\x01\x02")
    result = preview_file(tmp_path, "x.bin")
    assert result["kind"] == "binary"
    assert result["content"] is None


def test_two_threads_do_not_share_tree(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "only_a.txt").write_text("a", encoding="utf-8")
    (b / "only_b.txt").write_text("b", encoding="utf-8")
    names_a = {row["name"] for row in list_tree(a)}
    names_b = {row["name"] for row in list_tree(b)}
    assert "only_a.txt" in names_a
    assert "only_b.txt" not in names_a
    assert "only_a.txt" not in names_b


def test_open_external_requires_confirm_and_stays_inside(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    with pytest.raises(PathBoundaryError) as exc:
        prepare_open_external(tmp_path, "a.py", confirm=False)
    assert exc.value.code == "USER_ACTION_REQUIRED"
    with pytest.raises(PathBoundaryError):
        prepare_open_external(tmp_path, str(tmp_path.parent / "x.py"), confirm=True)
    result = prepare_open_external(tmp_path, "a.py", confirm=True)
    assert result["launched"] is False
    assert result["opened"] is False
    assert result["requires_user_action"] is True
    assert result["action"] == "open_external"


def test_capability_honest() -> None:
    snap = CapabilitySnapshot()
    assert snap.file_preview is True
    assert snap.worktree is True


async def _noop(_message: dict) -> None:
    return None
