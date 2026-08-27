"""PhaseG-B7 permission and approval audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.permission import PermissionStore
from appserver.server import AppServer
from protocol.handshake import CapabilitySnapshot


def test_full_access_not_selectable(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path / "p.json", persistent=True)
    with pytest.raises(PermissionError):
        store.set_profile("full_access")


def test_no_ui_still_rejects_risky() -> None:
    store = PermissionStore(persistent=False)
    assert store.evaluate(action="bash", actor="system") == "reject"
    assert store.evaluate(action="read", actor="system") == "allow"


def test_one_allow_does_not_reuse(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path / "p.json", persistent=True)
    first = store.decide(session_id="s", action="bash", decision="allow")
    second = store.decide(session_id="s", action="bash", decision="allow")
    assert first["approval_id"] != second["approval_id"]


def test_revoke_and_restart_only_keeps_persisted(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    first = PermissionStore(path, persistent=True)
    first.set_profile("workspace_write")
    rec = first.decide(session_id="s", action="write", decision="allow")
    first.revoke(rec["approval_id"])
    second = PermissionStore(path, persistent=True)
    snap = second.snapshot()
    assert snap["profile_id"] == "workspace_write"
    audit = second.audit("s")
    assert audit[0]["revoked"] is True
    assert "reject_streak" not in path.read_text(encoding="utf-8")
    assert second.evaluate(action="write", approval_id=rec["approval_id"], scope=rec["scope"]) == "reject"


def test_auto_review_does_not_expand() -> None:
    store = PermissionStore(persistent=False)
    cap = store.auto_review_capability()
    assert cap["read_only"] is True
    assert cap["expands_sandbox"] is False
    assert store.evaluate(action="write", actor="auto_review") == "reject"
    assert store.evaluate(action="read", actor="auto_review") == "allow"
    assert store.evaluate(action="read", actor="auto_review", expand_sandbox=True) == "reject"
    assert store.evaluate(action="read", actor="auto_review", expand_network=True) == "reject"
    assert store.evaluate(action="read", actor="auto_review", writable_roots=["/tmp/extra"]) == "reject"
    denied = store.decide(
        session_id="s",
        action="write",
        actor="auto_review",
        decision="allow",
        reviewer_id="reviewer-1",
        reason="unsafe write",
        expand_sandbox=True,
    )
    assert denied["decision"] == "reject"
    assert denied["reviewer_id"] == "reviewer-1"
    assert denied["reason"] == "unsafe write"


def test_reject_streak_interrupts_turn() -> None:
    store = PermissionStore(persistent=False)
    store.decide(session_id="s", action="bash", decision="reject")
    store.decide(session_id="s", action="bash", decision="reject")
    third = store.decide(session_id="s", action="bash", decision="reject")
    assert third["interrupt_turn"] is True


@pytest.mark.asyncio
async def test_appserver_permission_rpc(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    await server._dispatch({"jsonrpc": "2.0", "id": 1, "method": "permission/get", "params": {}})
    result = next(item["result"] for item in sent if "result" in item)
    assert "profiles" in result
    assert any(row["profile_id"] == "full_access" and row["selectable"] is False for row in result["profiles"])
    names = {row["profile_id"] for row in result["profiles"]}
    assert names == {
        "read_only",
        "workspace_write",
        "ask_for_each_risky_action",
        "allow_scoped_actions",
        "full_access",
    }


def test_approval_id_is_single_use() -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(session_id="s", action="bash", decision="allow", scope="/ws")
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s",
        )
        == "allow"
    )
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s",
        )
        == "reject"
    )


def test_capability_auto_review_honest() -> None:
    assert CapabilitySnapshot().approval_auto_review is True


def test_project_boundary_blocks_cross_project_approval(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(
        session_id="s",
        action="write",
        decision="allow",
        scope=str(tmp_path / "a"),
        project_id="proj-a",
    )
    assert (
        store.evaluate(
            action="write",
            actor="user",
            approval_id=rec["approval_id"],
            scope=str(tmp_path / "a"),
            project_id="proj-b",
            session_id="s",
        )
        == "reject"
    )
    assert store.audit("s")[0]["consumed"] is False
    assert (
        store.evaluate(
            action="write",
            actor="user",
            approval_id=rec["approval_id"],
            scope=str(tmp_path / "a"),
            project_id="proj-a",
            session_id="s",
        )
        == "allow"
    )


def test_auto_review_cannot_consume_user_approval(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(
        session_id="s",
        action="write",
        actor="user",
        decision="allow",
        scope=str(tmp_path),
        project_id="p1",
    )
    assert (
        store.evaluate(
            action="write",
            actor="auto_review",
            approval_id=rec["approval_id"],
            scope=str(tmp_path),
            project_id="p1",
            session_id="s",
        )
        == "reject"
    )
    assert (
        store.evaluate(
            action="write",
            actor="user",
            approval_id=rec["approval_id"],
            scope=str(tmp_path),
            project_id="p1",
            session_id="s",
        )
        == "allow"
    )


def test_allow_scoped_requires_matching_scope(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    store.set_profile("allow_scoped_actions")
    assert store.evaluate(action="command", scope=str(tmp_path), project_id="p1") == "reject"
    store.grant_scope(action="command", scope=str(tmp_path), project_id="p1")
    assert store.evaluate(action="command", scope=str(tmp_path), project_id="p1") == "allow"
    assert store.evaluate(action="command", scope=str(tmp_path), project_id="p2") == "reject"
    assert store.evaluate(action="bash", scope=str(tmp_path), project_id="p1") == "reject"


def test_workspace_write_stays_inside_workspace(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    store.set_profile("workspace_write")
    inside = tmp_path / "src"
    inside.mkdir()
    assert store.evaluate(action="command", scope=str(inside), workspace=str(tmp_path)) == "allow"
    assert store.evaluate(action="command", scope=str(tmp_path.parent), workspace=str(tmp_path)) == "reject"


@pytest.mark.asyncio
async def test_command_start_denied_without_ui(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    await server._handle_command_start(
        {"session_id": session.session_id, "command": "python -c pass", "cwd": str(tmp_path)},
        9,
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "PERMISSION_DENIED"
    assert err["data"]["approval"]["decision"] == "reject"


@pytest.mark.asyncio
async def test_command_start_scoped_grant_and_mismatch(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    project = server._projects.add(str(tmp_path), display_name="demo")
    server._permissions.set_profile("allow_scoped_actions")
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": "python -c pass",
            "cwd": str(tmp_path),
            "project_id": project["project_id"],
        },
        10,
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "PERMISSION_DENIED"
    sent.clear()
    server._permissions.grant_scope(
        action="command",
        scope=str(tmp_path),
        project_id=project["project_id"],
    )
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": 'python -c "print(1)"',
            "cwd": str(tmp_path),
            "project_id": project["project_id"],
        },
        11,
    )
    result = next(item["result"] for item in sent if "result" in item)
    assert result["status"] in {"succeeded", "running"}
    sent.clear()
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": 'python -c "print(1)"',
            "cwd": str(tmp_path),
            "project_id": "other-project",
        },
        12,
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "PERMISSION_DENIED"


def test_expired_approval_does_not_allow() -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(
        session_id="s",
        action="bash",
        decision="allow",
        scope="/ws",
        expires_at="2000-01-01T00:00:00Z",
    )
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s",
        )
        == "reject"
    )


def test_audit_returns_trace_fields() -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(
        session_id="s",
        action="bash",
        decision="reject",
        actor="user",
        turn_id="t1",
        project_id="p1",
        reason="risky",
    )
    rows = store.audit("s")
    assert rows[0]["approval_id"] == rec["approval_id"]
    assert rows[0]["trace_id"]
    assert rows[0]["turn_id"] == "t1"
    assert rows[0]["project_id"] == "p1"


def test_approval_bound_to_session_turn_and_actor() -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(session_id="s1", action="bash", decision="allow", scope="/ws", turn_id="t1")
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s2",
            turn_id="t1",
        )
        == "reject"
    )
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s1",
            turn_id="t2",
        )
        == "reject"
    )
    assert (
        store.evaluate(
            action="bash",
            actor="system",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s1",
            turn_id="t1",
        )
        == "reject"
    )
    assert store.audit("s1")[0]["consumed"] is False
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s1",
            turn_id="t1",
        )
        == "allow"
    )


def test_policy_decision_writes_audit() -> None:
    store = PermissionStore(persistent=False)
    assert store.evaluate(action="bash", actor="system", session_id="s") == "reject"
    rows = store.audit("s")
    assert rows
    assert rows[0]["decision"] == "reject"
    assert rows[0]["trace_id"]
    assert rows[0]["reason"] == "ask_required"
    assert rows[0]["consumed"] is True


def test_grant_scope_bumps_policy_version(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    rec = store.decide(session_id="s", action="command", decision="allow", scope=str(tmp_path), project_id="p1")
    before = store.snapshot()["policy_version"]
    store.grant_scope(action="command", scope=str(tmp_path), project_id="p1")
    assert store.snapshot()["policy_version"] == before + 1
    assert (
        store.evaluate(
            action="command",
            actor="user",
            approval_id=rec["approval_id"],
            scope=str(tmp_path),
            project_id="p1",
            session_id="s",
        )
        == "reject"
    )


def test_approval_scope_must_stay_in_workspace(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    other = tmp_path.parent / "other-ws"
    rec = store.decide(session_id="s", action="write", decision="allow", scope=str(other), project_id="p1")
    assert (
        store.evaluate(
            action="write",
            actor="user",
            approval_id=rec["approval_id"],
            scope=str(other),
            project_id="p1",
            session_id="s",
            workspace=str(tmp_path),
        )
        == "reject"
    )


def test_restart_does_not_restore_live_approval(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    first = PermissionStore(path, persistent=True)
    rec = first.decide(session_id="s", action="bash", decision="allow", scope=str(tmp_path))
    assert rec["consumed"] is False
    second = PermissionStore(path, persistent=True)
    assert (
        second.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope=str(tmp_path),
            session_id="s",
        )
        == "reject"
    )
    assert '"consumed": false' not in path.read_text(encoding="utf-8").lower()


def test_read_outside_workspace_is_rejected(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    outside = tmp_path.parent
    assert (
        store.evaluate(
            action="read",
            actor="system",
            scope=str(outside),
            workspace=str(tmp_path),
            session_id="s",
        )
        == "reject"
    )
    assert (
        store.evaluate(
            action="read",
            actor="system",
            scope=str(tmp_path / "a.txt"),
            workspace=str(tmp_path),
            session_id="s",
        )
        == "allow"
    )


def test_generated_types_include_b7_fields() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "protocol-client"
        / "src"
        / "generated"
        / "types.ts"
    ).read_text(encoding="utf-8")
    assert "PermissionGetRequest" in text
    assert "PermissionSetRequest" in text
    assert "PermissionScopeGrant" in text
    assert "ApprovalDecideRequest" in text
    assert "expand_sandbox" in text
    assert "original_approval_id" in text


def test_successful_allow_resets_reject_streak() -> None:
    store = PermissionStore(persistent=False)
    store.decide(session_id="s", action="bash", decision="reject")
    store.decide(session_id="s", action="bash", decision="reject")
    rec = store.decide(session_id="s", action="bash", decision="allow", scope="/ws")
    assert (
        store.evaluate(
            action="bash",
            actor="user",
            approval_id=rec["approval_id"],
            scope="/ws",
            session_id="s",
        )
        == "allow"
    )
    fourth = store.decide(session_id="s", action="bash", decision="reject")
    assert fourth["interrupt_turn"] is False


def test_read_without_scope_in_workspace_rejected(tmp_path: Path) -> None:
    store = PermissionStore(persistent=False)
    assert store.evaluate(action="read", workspace=str(tmp_path), session_id="s") == "reject"


@pytest.mark.asyncio
async def test_command_start_rejects_unknown_project(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    session = server._sessions.create(tmp_path, title="p")
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": "python -c pass",
            "cwd": str(tmp_path),
            "project_id": "ghost",
        },
        20,
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "PERMISSION_DENIED"
    assert err["data"]["reason"] == "unknown_project"


def test_b7_fixtures_exist() -> None:
    root = Path(__file__).resolve().parent / "fixtures"
    for name in ("b7-success.json", "b7-denied.json", "b7-timeout.json", "b7-reconnect.json"):
        assert (root / name).is_file()
