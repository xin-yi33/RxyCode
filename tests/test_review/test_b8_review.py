"""PhaseG-B8 review, checkpoint, and git hunk actions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from appserver.review import ReviewError, ReviewService
from appserver.server import AppServer
from protocol.handshake import CapabilitySnapshot


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
    _git(tmp_path, "config", "user.email", "b8@example.com")
    _git(tmp_path, "config", "user.name", "B8")
    (tmp_path / "a.txt").write_text("one\n" + "keep\n" * 20 + "two\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


@pytest.mark.asyncio
async def test_non_git_is_not_fake_diff(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_review_start(
        {"session_id": session.session_id, "request_id": "r1", "scope": "working_tree"},
        1,
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "REVIEW_DIFF_UNAVAILABLE"


@pytest.mark.asyncio
async def test_untracked_and_idempotent_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    root = _repo(tmp_path)
    (root / "new.txt").write_text("secret=not-really\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(root, title="p")
    await server._handle_review_start(
        {"session_id": session.session_id, "request_id": "same", "scope": "working_tree"},
        1,
    )
    first = server._reviews._by_request["same"]
    await server._handle_review_start(
        {"session_id": session.session_id, "request_id": "same", "scope": "working_tree"},
        2,
    )
    assert server._reviews._by_request["same"] == first
    review = server._reviews.read(first)
    assert "new.txt" in review["files"]
    assert any(item["severity"] == "P0" for item in review["findings"])


@pytest.mark.asyncio
async def test_review_read_after_disconnect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    root = _repo(tmp_path)
    (root / "a.txt").write_text("one\n" + "keep\n" * 20 + "changed\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(root, title="p")
    result, _events = server._reviews.start(
        request_id="req-read",
        session_id=session.session_id,
        workspace=root,
    )
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_review_read({"review_id": result["review_id"]}, 3)
    body = next(item["result"] for item in sent if "result" in item)
    assert body["review_id"] == result["review_id"]
    assert body["diff_hash"] == result["diff_hash"]


@pytest.mark.asyncio
async def test_finding_stale_after_agent_fix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    root = _repo(tmp_path)
    (root / "a.txt").write_text("one\nAPI_KEY=abcd\n" + "keep\n" * 20 + "two\n", encoding="utf-8")
    service = ReviewService()
    result, _ = service.start(request_id="s1", session_id="sid", workspace=root)
    review = service.read(result["review_id"])
    assert any(item["severity"] == "P0" for item in review["findings"])
    (root / "a.txt").write_text("one\n" + "keep\n" * 20 + "two\n", encoding="utf-8")
    stale = service.refresh_hashes(root)
    assert result["review_id"] in stale
    after = service.read(result["review_id"])
    assert after["status"] == "stale"
    assert any(item["status"] in {"fixed", "stale"} for item in after["findings"])


@pytest.mark.asyncio
async def test_single_hunk_revert_leaves_other_hunk(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    root = _repo(tmp_path)
    (root / "a.txt").write_text("ALPHA\n" + "keep\n" * 20 + "BETA\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    session = server._sessions.create(root, title="p")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_git_change(
        {"session_id": session.session_id, "paths": ["a.txt"], "hunk_index": 0},
        4,
        "revert",
    )
    text = (root / "a.txt").read_text(encoding="utf-8")
    assert "BETA" in text
    assert text.splitlines()[0] == "one"


@pytest.mark.asyncio
async def test_checkpoint_restore_new_hash_and_audit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    root = _repo(tmp_path)
    (root / "a.txt").write_text("snap\n" + "keep\n" * 20 + "two\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    session = server._sessions.create(root, title="p")
    started, _ = server._reviews.start(request_id="before", session_id=session.session_id, workspace=root)
    checkpoint = server._reviews.create_checkpoint(session_id=session.session_id, workspace=root, reason="write")
    (root / "a.txt").write_text("mutated\n", encoding="utf-8")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_checkpoint_restore(
        {"checkpoint_id": checkpoint["checkpoint_id"], "session_id": session.session_id},
        5,
    )
    result = next(item["result"] for item in sent if "result" in item)
    assert result["diff_hash"] != started["diff_hash"] or result["previous_diff_hash"]
    assert started["review_id"] in result["stale_reviews"]
    assert "a.txt" in result["file_list"]
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("snap")


@pytest.mark.asyncio
async def test_git_stage_requires_permission(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    root = _repo(tmp_path)
    (root / "a.txt").write_text("x\n", encoding="utf-8")
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(root, title="p")
    await server._handle_git_change(
        {"session_id": session.session_id, "paths": ["a.txt"]},
        6,
        "stage",
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "PERMISSION_DENIED"


def test_review_does_not_modify_tree(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    before = (root / "a.txt").read_text(encoding="utf-8")
    ReviewService().start(request_id="ro", session_id="s", workspace=root)
    assert (root / "a.txt").read_text(encoding="utf-8") == before


def test_comment_binds_review_finding_and_hash(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    service = ReviewService()
    result, _ = service.start(request_id="c1", session_id="s", workspace=root)
    review = service.read(result["review_id"])
    finding_id = review["findings"][0]["finding_id"]
    comment = service.comment(
        review_id=result["review_id"],
        finding_id=finding_id,
        file="a.txt",
        start_line=1,
        end_line=1,
        body="please fix",
    )
    assert comment["review_id"] == result["review_id"]
    assert comment["finding_id"] == finding_id
    assert comment["file_hash"].startswith("sha256:")


def test_capabilities_honest() -> None:
    snap = CapabilitySnapshot()
    assert snap.review is True
    assert snap.review_comments is True
    assert snap.checkpoint is True
    assert snap.git_hunk_actions is True


def test_invalid_scope() -> None:
    with pytest.raises(ReviewError) as exc:
        ReviewService().start(request_id="x", session_id="s", workspace=Path("."), scope="nope")
    assert exc.value.code == "REVIEW_SCOPE_INVALID"


def test_scope_aliases_accepted(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    service = ReviewService()
    for scope in ("working_tree", "base", "head", "paths"):
        result, _ = service.start(
            request_id=f"alias-{scope}",
            session_id="s",
            workspace=root,
            scope=scope,
            paths=["a.txt"] if scope == "paths" else None,
        )
        assert result["review_id"]


def test_deleted_file_finding_is_fixed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "gone.txt").write_text("API_KEY=abcd\n", encoding="utf-8")
    service = ReviewService()
    result, _ = service.start(request_id="del", session_id="s", workspace=root)
    (root / "gone.txt").unlink()
    after = service.read(result["review_id"])
    assert after["status"] == "stale"
    assert any(item["status"] == "fixed" for item in after["findings"])


@pytest.mark.asyncio
async def test_checkpoint_create_via_protocol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    root = _repo(tmp_path)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(root, title="p")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_checkpoint_create({"session_id": session.session_id, "reason": "write"}, 30)
    result = next(item["result"] for item in sent if "result" in item)
    assert result["checkpoint_id"].startswith("cp_")
    listed = server._reviews.list_checkpoints(session.session_id)
    assert listed[0]["checkpoint_id"] == result["checkpoint_id"]


def test_working_tree_paths_filter_untracked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "keep_me.txt").write_text("a\n", encoding="utf-8")
    (root / "skip_me.txt").write_text("b\n", encoding="utf-8")
    snap = __import__("appserver.review", fromlist=["current_diff"]).current_diff(
        root, scope="working_tree", base_ref=None, head_ref=None, paths=["keep_me.txt"]
    )
    assert "keep_me.txt" in snap["files"]
    assert "skip_me.txt" not in snap["files"]


def test_comment_rejects_foreign_finding(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    service = ReviewService()
    result, _ = service.start(request_id="cf", session_id="s", workspace=root)
    with pytest.raises(ReviewError) as exc:
        service.comment(
            review_id=result["review_id"],
            finding_id="nope",
            file="a.txt",
            start_line=1,
            end_line=1,
            body="x",
        )
    assert exc.value.code == "REVIEW_SCOPE_INVALID"


def test_generated_types_include_b8_fields() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "protocol-client"
        / "src"
        / "generated"
        / "types.ts"
    ).read_text(encoding="utf-8")
    for name in (
        "ReviewStartRequest",
        "ReviewReadRequest",
        "ReviewCommentRequest",
        "CheckpointCreateRequest",
        "CheckpointRestoreRequest",
        "GitRevertRequest",
    ):
        assert name in text


def test_b8_fixtures_exist() -> None:
    root = Path(__file__).resolve().parent / "fixtures"
    for name in ("b8-success.json", "b8-denied.json", "b8-timeout.json", "b8-reconnect.json"):
        assert (root / name).is_file()


async def _noop(_message: dict) -> None:
    return None
