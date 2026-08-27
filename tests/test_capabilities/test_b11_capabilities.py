"""PhaseG-B11 capability / skill / MCP / browser projections."""

from __future__ import annotations

import pytest

from pathlib import Path

from appserver.capabilities import CapabilityError, CapabilityService
from appserver.permission import PermissionStore
from appserver.server import AppServer
from protocol.handshake import CapabilitySnapshot
from protocol.schema import export_schema


class _PassReview:
    def start(self, **_kwargs):
        return {"review_id": "rev_pass", "status": "passed"}, []


def _write_perms() -> PermissionStore:
    store = PermissionStore(persistent=False)
    store.set_profile("workspace_write")
    return store


def _skill_dir(root: Path, name: str = "demo-skill") -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    return path


def _service(tmp_path: Path | None = None) -> CapabilityService:
    skill_path = str(_skill_dir(tmp_path)) if tmp_path else "/tmp/demo-skill"
    skills = [{"name": "demo-skill", "path": skill_path, "has_skill_md": True}]
    mcp = {"files": {"command": "npx", "connected": False}}
    return CapabilityService(
        persistent=False,
        skill_lister=lambda: skills,
        mcp_lister=lambda: mcp,
        review_service=_PassReview(),
    )


def test_uninstalled_and_unauthorized_are_not_available(tmp_path: Path) -> None:
    missing = CapabilityService(
        persistent=False,
        skill_lister=lambda: [{"name": "ghost", "path": str(tmp_path / "ghost"), "has_skill_md": True}],
        mcp_lister=lambda: {"files": {"connected": False}},
        review_service=_PassReview(),
    )
    rows = {row["capability_id"]: row for row in missing.list()["capabilities"]}
    assert rows["skill:ghost"]["installed"] is False
    assert rows["skill:ghost"]["available"] is False
    service = _service(tmp_path)
    rows = {row["capability_id"]: row for row in service.list()["capabilities"]}
    assert rows["skill:demo-skill"]["installed"] is True
    assert rows["skill:demo-skill"]["available"] is False
    assert rows["mcp:files"]["available"] is False
    assert rows["browser"]["available"] is False
    assert rows["browser"]["bypass"] is False
    only = service.list(available_only=True)["capabilities"]
    assert only == []


def test_authorize_then_skill_invoke_is_auditable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    perms = _write_perms()
    service.set_enabled("skill:demo-skill", True, authorize=True, permission_store=perms)
    got = service.get("skill:demo-skill")
    assert got["available"] is True
    job = service.invoke("skill:demo-skill", permission_store=perms, session_id="s1")
    assert job["status"] == "completed"
    assert job["thread_stuck"] is False
    assert job["payload"]["copyable"] is True
    assert job["payload"]["collapsible"] is True
    assert job["payload"]["source"]["locator"] == "skill:demo-skill/SKILL.md"
    audit = service.audit("skill:demo-skill")
    assert audit
    assert any(row.get("status") == "completed" for row in audit)


def test_disconnected_mcp_fails_without_sticking(tmp_path: Path) -> None:
    service = _service(tmp_path)
    perms = _write_perms()
    service.set_enabled("mcp:files", True, authorize=True, permission_store=perms)
    job = service.invoke("mcp:files", permission_store=perms)
    assert job["status"] == "failed"
    assert job["error_code"] == "CAPABILITY_DISCONNECTED"
    assert job["thread_stuck"] is False
    assert job["payload"]["copyable"] is True
    assert job["payload"]["collapsible"] is True
    assert job["payload"]["source"]["locator"]


def test_missing_skill_fails_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    job = service.invoke("skill:ghost", permission_store=_write_perms())
    assert job["status"] == "failed"
    assert job["error_code"] == "CAPABILITY_NOT_FOUND"
    assert job["thread_stuck"] is False


def test_browser_is_not_a_bypass(tmp_path: Path) -> None:
    import subprocess

    from appserver.execution import ExecutionStore
    from appserver.review import ReviewService

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "b11@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "B11"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    service = CapabilityService(
        persistent=False,
        skill_lister=lambda: [],
        mcp_lister=lambda: {},
        execution_store=ExecutionStore(),
        review_service=ReviewService(),
    )
    perms = _write_perms()
    with pytest.raises(CapabilityError) as exc:
        service.set_enabled("browser", True, authorize=True, permission_store=perms)
    assert exc.value.code == "BROWSER_NOT_IMPLEMENTED"
    job = service.invoke("browser", permission_store=perms, session_id="s1", workspace=str(tmp_path))
    assert job["status"] == "failed"
    assert job["error_code"] == "BROWSER_NOT_IMPLEMENTED"
    steps = [row["step"] for row in job["payload"]["chain"]]
    assert steps == ["tool", "approval", "review"]
    assert job["payload"]["chain"][2]["bypass"] is False
    assert job["payload"]["chain"][2].get("review_id") or job["payload"]["chain"][2].get("status") == "passed"
    assert job["payload"]["copyable"] is True
    assert job["payload"]["source"]["locator"]
    snap = CapabilitySnapshot()
    assert snap.browser is False
    assert snap.mcp is True
    assert snap.skills is True
    assert snap.capability_panel is True


def test_cancel_releases_inflight_job(tmp_path: Path) -> None:
    import time

    service = _service(tmp_path)
    service._invoke_timeout_s = 2.0
    perms = _write_perms()
    service.set_enabled("skill:demo-skill", True, authorize=True, permission_store=perms)
    job = service.invoke("skill:demo-skill", permission_store=perms, session_id="s", hang=True)
    assert job["status"] == "started"
    cancelled = service.cancel(job["job_id"], session_id="s")
    deadline = time.time() + 1.5
    while service._jobs[job["job_id"]]["status"] == "started" and time.time() < deadline:
        time.sleep(0.02)
    assert cancelled["status"] in {"cancelled", "started"}
    assert service._jobs[job["job_id"]]["status"] == "cancelled"
    assert service._jobs[job["job_id"]]["thread_stuck"] is False


def test_set_enabled_requires_permission(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(CapabilityError) as exc:
        service.set_enabled("skill:demo-skill", True, permission_store=None)
    assert exc.value.code == "CAPABILITY_PERMISSION_DENIED"
    assert service.audit()
    readonly = PermissionStore(persistent=False)
    readonly.set_profile("read_only")
    with pytest.raises(CapabilityError):
        service.set_enabled("skill:demo-skill", True, authorize=True, permission_store=readonly)
    assert any(row.get("status") == "denied" for row in service.audit())


def test_set_enabled_rejects_unknown() -> None:
    service = _service()
    with pytest.raises(CapabilityError) as exc:
        service.set_enabled("skill:ghost", True, permission_store=_write_perms())
    assert exc.value.code == "CAPABILITY_NOT_FOUND"


def test_skill_and_mcp_real_failure_are_terminal_and_cancellable(tmp_path: Path) -> None:
    broken = _skill_dir(tmp_path, "broken")
    skills = [{"name": "broken", "path": str(broken), "has_skill_md": True}]
    mcp = {"files": {"connected": True, "fail": True}}
    service = CapabilityService(
        persistent=False,
        skill_lister=lambda: skills,
        mcp_lister=lambda: mcp,
        review_service=_PassReview(),
    )
    perms = _write_perms()
    service.set_enabled("skill:broken", True, authorize=True, permission_store=perms)
    skill_job = service.invoke("skill:broken", permission_store=perms, force_fail=True)
    assert skill_job["status"] == "failed"
    assert skill_job["error_code"] == "CAPABILITY_INVOKE_FAILED"
    again = service.cancel(skill_job["job_id"])
    assert again["status"] == "failed"
    service.set_enabled("mcp:files", True, authorize=True, permission_store=perms)
    mcp_job = service.invoke("mcp:files", permission_store=perms)
    assert mcp_job["status"] == "failed"
    assert mcp_job["error_code"] == "CAPABILITY_INVOKE_FAILED"
    assert mcp_job["thread_stuck"] is False


def test_schema_has_capability_methods() -> None:
    defs = export_schema()["$defs"]
    for name in (
        "CapabilitiesListRequest",
        "CapabilitiesGetRequest",
        "CapabilitiesSetEnabledRequest",
        "CapabilitiesInvokeRequest",
        "CapabilitiesCancelRequest",
        "CapabilitiesAuditRequest",
    ):
        assert name in defs


@pytest.mark.asyncio
async def test_rpc_list_and_invoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_message: dict) -> None:
        return None

    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    skill_root = _skill_dir(tmp_path, "rpc-skill")
    server._capabilities = CapabilityService(
        persistent=False,
        skill_lister=lambda: [{"name": "rpc-skill", "path": str(skill_root), "has_skill_md": True}],
        mcp_lister=lambda: {},
        review_service=_PassReview(),
        execution_store=server._execution,
    )
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_capabilities_list({}, 1)
    listed = next(item["result"] for item in sent if "result" in item)
    assert listed["browser_implemented"] is False
    listed_skill = next(row for row in listed["capabilities"] if row["kind"] == "skill")
    assert listed_skill["available"] is False
    sent.clear()
    await server._handle_capabilities_set_enabled(
        {"capability_id": "skill:rpc-skill", "enabled": True, "authorize": True},
        2,
    )
    await server._handle_capabilities_invoke({"capability_id": "skill:rpc-skill"}, 3)
    results = [item["result"] for item in sent if "result" in item]
    assert results[-1]["status"] == "completed"
    assert results[-1]["payload"]["source"]["locator"]
    sent.clear()
    await server._handle_capabilities_invoke(
        {"capability_id": "skill:rpc-skill", "background": True},
        4,
    )
    started = next(item["result"] for item in sent if "result" in item)
    assert started["status"] == "started"
    sent.clear()
    await server._handle_capabilities_cancel({"job_id": started["job_id"]}, 5)
    cancelled = next(item["result"] for item in sent if "result" in item)
    assert cancelled["status"] in {"cancelled", "completed"}
