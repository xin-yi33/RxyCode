"""GX3-B: review/comment/add + resolve; B8 review/comment unchanged."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from appserver.review import GX3_SCOPES, ReviewService, current_diff
from appserver.review_comments import ReviewCommentService
from appserver.server import AppServer
from protocol.requests import ReviewCommentAddRequest, ReviewCommentRequest, ReviewCommentResolveRequest


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "gx3@example.com")
    _git(tmp_path, "config", "user.name", "GX3")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def test_b8_comment_method_still_exists() -> None:
    assert ReviewCommentRequest.model_fields["method"].default == "review/comment"
    add = ReviewCommentAddRequest(
        review_id="r", file="a.txt", line=1, hunk_hash="h1", body="fix"
    )
    assert add.method == "review/comment/add"
    assert ReviewCommentResolveRequest(comment_id="c").method == "review/comment/resolve"


def test_gx3_scope_probe_reuses_commit_and_branch() -> None:
    assert "commit" in GX3_SCOPES
    assert "branch" in GX3_SCOPES


def test_new_scopes_unstaged_staged_last_turn(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("one\nchanged\n", encoding="utf-8")
    unstaged = current_diff(root, scope="unstaged", base_ref=None, head_ref=None, paths=None)
    assert "a.txt" in "".join(unstaged["files"]) or "changed" in unstaged["diff"]
    _git(root, "add", "a.txt")
    staged = current_diff(root, scope="staged", base_ref=None, head_ref=None, paths=None)
    assert staged["diff"]
    last = current_diff(root, scope="last_turn", base_ref=None, head_ref=None, paths=None)
    assert last["diff"] == ""
    assert last["empty_reason"] == "no_turn_diff"


def test_add_resolve_stale_state_machine(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("one\nedit\n", encoding="utf-8")
    reviews = ReviewService()
    rec, _ = reviews.start(
        request_id="r1",
        session_id="s1",
        workspace=root,
        scope="working_tree",
    )
    svc = ReviewCommentService(reviews)
    added = svc.add(
        review_id=rec["review_id"],
        file="a.txt",
        line=2,
        hunk_hash="oldhash",
        body="please fix",
    )
    assert added["status"] == "open"
    svc.refresh_stale(rec["review_id"], {"a.txt:2": "newhash"})
    listed = svc.list_for_review(rec["review_id"])
    assert listed[0]["status"] == "stale"
    resolved = svc.resolve(added["comment_id"])
    assert resolved["status"] == "resolved"
    again = svc.resolve(added["comment_id"])
    assert again["status"] == "resolved"


@pytest.mark.asyncio
async def test_appserver_comment_add_resolve_rpc(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("one\nedit\n", encoding="utf-8")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(root, title="p")
    await server._handle_review_start(
        {"session_id": session.session_id, "request_id": "gx3", "scope": "working_tree"},
        1,
    )
    start = next(item["result"] for item in sent if item.get("id") == 1)
    review_id = start["review_id"]
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "review/comment/add",
            "params": {
                "review_id": review_id,
                "file": "a.txt",
                "line": 2,
                "hunk_hash": "hh",
                "body": "nits",
            },
        }
    )
    added = next(item["result"] for item in sent if item.get("id") == 2)
    assert added["body"] == "nits"
    assert added["status"] == "open"
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "review/comment/resolve",
            "params": {"comment_id": added["comment_id"]},
        }
    )
    resolved = next(item["result"] for item in sent if item.get("id") == 3)
    assert resolved["status"] == "resolved"


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
