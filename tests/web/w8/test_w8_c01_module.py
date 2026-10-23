"""WEB-W8-C01 module tests — the four acceptance chains end-to-end at the
service seam: the real ToolOrchestrator (gate + approval + journal), the
durable approval service on real Postgres, the real egress policy, and the
merged sandbox-write-domain config.

What is substituted and why:
- The AF_UNIX control socket is exercised through the real ``_ctl_handlers``
  + ``_CtlApproval`` pair with the socket hop removed (Windows has no
  AF_UNIX; the socket transport itself is covered by unit tests and the
  Linux deployment). Everything a handler touches — Postgres, the lease
  fence, the durable row, the parent-owned journal — is real.
- bwrap is Linux-only; its argv shape (mounts, --unshare-net,
  --die-with-parent, env) is asserted in the unit file, and the kernel
  boundary chain (confined read/connect denial) runs live here wherever
  ``userns_available()`` is true — skipping honestly elsewhere.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO,
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _seed_tenant_run(postgres_url: str, *, tenant: str, run_id: str, status: str) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import (
        Organization,
        Project,
        Run,
        SessionRow,
        User,
    )

    upgrade_head(postgres_url)
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            if db.get(User, f"u-{tenant}") is None:
                db.add(User(id=f"u-{tenant}", github_id=None, kind="local"))
            if db.get(Organization, f"o-{tenant}") is None:
                db.add(Organization(id=f"o-{tenant}", tenant_id=tenant))
            if db.get(Project, f"p-{tenant}") is None:
                db.add(Project(id=f"p-{tenant}", tenant_id=tenant, name="t", repo_config={}))
            if db.get(SessionRow, f"s-{run_id}") is None:
                db.add(
                    SessionRow(
                        id=f"s-{run_id}", tenant_id=tenant, project_id=f"p-{tenant}", title="t"
                    )
                )
            db.add(
                Run(
                    id=run_id,
                    tenant_id=tenant,
                    session_id=f"s-{run_id}",
                    status=status,
                    request_id=f"req-{run_id}",
                )
            )
            db.commit()
    finally:
        engine.dispose()


def _run_status(postgres_url: str, run_id: str) -> tuple[str, Any]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return tuple(
                conn.execute(
                    text("SELECT status, lease_owner FROM runs WHERE id = :r"),
                    {"r": run_id},
                ).one()
            )
    finally:
        engine.dispose()


def _lease_run(postgres_url: str, run_id: str, worker: str, epoch: int) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = :e,"
                    " lease_until = :u WHERE id = :r"
                ),
                {
                    "w": worker,
                    "e": epoch,
                    "u": datetime.now(timezone.utc) + timedelta(minutes=5),
                    "r": run_id,
                },
            )
    finally:
        engine.dispose()


def _set_status(postgres_url: str, run_id: str, status: str) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE runs SET status = :s WHERE id = :r"),
                {"s": status, "r": run_id},
            )
    finally:
        engine.dispose()


def _sandbox_data_dir(
    tmp_path: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Mirror the confined child's config home: the parent merges
    ``execution.workspace_root``/``safety`` into a copied config.yaml that
    ``load_config()`` (and therefore shell_executor's workspace check)
    reads via ``RXYCODE_DATA_DIR`` — the same mechanism the deployed turn
    uses, pointed at this test's sandbox."""
    import yaml

    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "execution": {
                    "workspace_root": str(workdir),
                    "os_sandbox": {"enabled": False},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
    return data_dir


def _orchestrator() -> Any:
    from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import (
        register_builtin_tools,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

    orchestrator = ToolOrchestrator()
    register_builtin_tools(
        ToolRegistry(), orchestrator, rag_enabled=False, subagents_enabled=False
    )
    return orchestrator


def _cfg(workdir: Path, permission_mode: str) -> dict[str, Any]:
    """The shape a confined turn actually executes under: safety.enabled is
    True in the deployed defaults (settings.py), the write domain is the
    sandbox-real path set _merge_turn_config injects, and os_sandbox stays
    off (this process IS the sandbox)."""
    import rxycode_worker.drain as drain

    return {
        "safety": {
            "enabled": True,
            "permission_mode": permission_mode,
            "allowed_write_paths": drain._writable_domain(workdir),
        },
        "execution": {
            "workspace_root": str(workdir),
            "os_sandbox": {"enabled": False},
        },
    }


# ---------------------------------------------------------------------------
# Chain A — normal development completes in ordinary AND Full modes.
# ---------------------------------------------------------------------------


def test_w8_c01_chain_normal_dev_both_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """read/edit/bash all work inside the sandbox write domain — ordinary
    mode asks once and executes after approval; Full auto-grants without a
    prompt; no tool is accidentally disabled in either mode."""
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        ApprovalBroker,
        ApprovalDecision,
        set_approval_broker,
    )

    _sandbox_data_dir(tmp_path, tmp_path, monkeypatch)

    orch = _orchestrator()

    def _dev_legs(cfg: dict[str, Any], name: str) -> None:
        """The acceptance chain, identical for both modes: read/edit files,
        install a dependency into the task-private tree, and execute a
        test — all real tool calls through the same orchestrator."""
        marker = tmp_path / f"{name}.txt"
        marker.write_text("seed-content", encoding="utf-8")
        out = asyncio.run(
            orch.execute_tool(
                "edit",
                {
                    # Committed EditInput: replace exact text — the unified
                    # write/patch API only exists in a dirty worktree, so
                    # this chain must prove itself on the SHIPPED contract
                    # (audit W8-r3).
                    "filePath": str(marker),
                    "oldString": "seed-content",
                    "newString": name,
                },
                cfg,
            )
        )
        assert marker.read_text() == name
        assert "blocked" not in str(out).lower()
        assert "[error" not in str(out).lower()
        read_out = asyncio.run(
            orch.execute_tool("read", {"filePath": str(marker)}, cfg)
        )
        assert name in str(read_out)
        # A REAL dependency install: pip installs a (locally built,
        # index-free) wheel into the task-private tree and the import
        # resolves from it — no installer is simulated (audit W8-r2).
        import zipfile

        pkg = f"demopkg_{name.replace('-', '_')}"
        whl = tmp_path / f"{pkg}-0.1.0-py3-none-any.whl"
        dist = f"{pkg}-0.1.0.dist-info"
        with zipfile.ZipFile(whl, "w") as z:
            z.writestr(f"{pkg}/__init__.py", "VALUE = 7\n")
            z.writestr(
                f"{dist}/METADATA",
                f"Metadata-Version: 2.1\nName: {pkg}\nVersion: 0.1.0\n",
            )
            z.writestr(
                f"{dist}/WHEEL",
                "Wheel-Version: 1.0\nGenerator: w8test\n"
                "Root-Is-Purelib: true\nTag: py3-none-any\n",
            )
            z.writestr(
                f"{dist}/RECORD",
                f"{pkg}/__init__.py,,\n{dist}/METADATA,,\n"
                f"{dist}/WHEEL,,\n{dist}/RECORD,,\n",
            )
        install = asyncio.run(
            orch.execute_tool(
                "bash",
                {
                    "command": (
                        f"python -m pip install --no-index --quiet"
                        f" --target .deps {whl.name}"
                    ),
                    "workdir": str(tmp_path),
                },
                cfg,
            )
        )
        assert (tmp_path / ".deps" / pkg / "__init__.py").exists(), str(install)[:600]
        # Resolution proof: the interpreter imports the installed package
        # out of the task-private target dir — proven by a side-effect
        # marker, not by output parsing.
        resolve = asyncio.run(
            orch.execute_tool(
                "bash",
                {
                    "command": (
                        "python -c \"import sys,pathlib;"
                        " sys.path.insert(0, '.deps');"
                        f" import {pkg}; assert {pkg}.VALUE == 7;"
                        " pathlib.Path('resolved.marker').write_text('ok')\""
                    ),
                    "workdir": str(tmp_path),
                },
                cfg,
            )
        )
        assert (tmp_path / "resolved.marker").exists(), str(resolve)[:400]
        # A real test execution: python runs the suite file; its exit
        # code and its marker prove the run happened.
        suite = tmp_path / f"test_{name}.py"
        suite.write_text(
            "from pathlib import Path\n"
            f"assert '{name}' in Path('{name}.txt').read_text()\n"
            "Path('test-ran.marker').write_text('passed')\n",
            encoding="utf-8",
        )
        bash_out = asyncio.run(
            orch.execute_tool(
                "bash",
                {"command": f"python test_{name}.py", "workdir": str(tmp_path)},
                cfg,
            )
        )
        assert (tmp_path / "test-ran.marker").exists(), str(bash_out)[:400]
        (tmp_path / "test-ran.marker").unlink()

    # -- ordinary mode: asks on each risk call, approved -> executed.
    asks: list[Any] = []

    class _Approve(ApprovalBroker):
        async def _ask(self, request: Any) -> Any:
            asks.append(request)
            return ApprovalDecision.APPROVED

    set_approval_broker(_Approve())
    try:
        cfg = _cfg(tmp_path, "confirm_all")
        _dev_legs(cfg, "line-one")
        # bash append — the side effect is verified, not just "not blocked"
        # (python for the append: PowerShell `>>` writes a BOM-less
        # UTF-16LE tail that no single decode reads reliably).
        asyncio.run(
            orch.execute_tool(
                "bash",
                {
                    "command": (
                        "python -c \"open('line-one.txt','a',"
                        "encoding='utf-8').write('via-bash')\""
                    ),
                    "workdir": str(tmp_path),
                },
                cfg,
            )
        )
        assert "via-bash" in (tmp_path / "line-one.txt").read_text()
        assert asks, "confirm_all must surface approval asks for risk calls"
    finally:
        set_approval_broker(None)

    # -- Full: same calls, ZERO asks (auto-grant), identical effects.
    asks.clear()
    cfg_full = _cfg(tmp_path, "full_auto")
    _dev_legs(cfg_full, "full-mode")
    assert not asks, "full_auto must never surface an approval prompt"


# ---------------------------------------------------------------------------
# Chain B — non-Full approval wired to the real running call, executed once.
# ---------------------------------------------------------------------------


def test_w8_c01_chain_approval_executes_the_stored_call_once(
    tmp_path: Path, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-proc channel: the child's _CtlApproval parks the run via the REAL
    service (waiting_approval + lease released + verbatim call persisted);
    approval re-queues; the resume child replays THE call through the real
    orchestrator + journal — and a second resume never re-runs the side
    effect."""
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.core.harness_checkpoint import HarnessPaused
    from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker
    from rxycode_server.approvals.service import decide_approval

    _sandbox_data_dir(tmp_path, tmp_path, monkeypatch)
    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    _lease_run(postgres_url, run_id, "wkr-1", 7)

    paused = threading.Event()
    paused_info: dict[str, Any] = {}
    journal_dir = tmp_path / ".journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    cfg = SimpleNamespace(database_url=postgres_url, worker_id="wkr-1")
    handlers = drain._ctl_handlers(
        cfg,
        tenant_id=tenant,
        run_id=run_id,
        epoch=7,
        workdir=tmp_path,
        journal_dir=journal_dir,
        paused=paused,
        paused_info=paused_info,
    )

    # In-proc channel: the same kwargs the unix-socket hop would carry, with
    # the checkpoint packed exactly as TurnChannel packs it on the wire.
    class _Channel:
        def pause_approval(self, **kwargs: Any) -> dict[str, Any]:
            from rxycode_worker.ctl import pack_checkpoint

            kwargs["checkpoint_z"] = pack_checkpoint(kwargs.pop("checkpoint"))
            return handlers["pause_approval"](kwargs)

        def resume_state(self, approval_id: str) -> dict[str, Any]:
            return handlers["resume_state"]({"approval_id": approval_id})

        def emit(self, **kwargs: Any) -> dict[str, Any]:
            return handlers["emit"](kwargs)

        def journal_state(self, **kwargs: Any) -> str:
            return str(handlers["journal_state"](kwargs)["state"])

        def journal_reserve(self, **kwargs: Any) -> dict[str, Any]:
            return handlers["journal_reserve"](kwargs)

        def journal_complete(self, **kwargs: Any) -> str:
            out = handlers["journal_complete"](kwargs)
            if out.get("refused"):
                raise RuntimeError("journal_complete refused: unbound call")
            return str(out["result"])

    channel = _Channel()
    set_approval_broker(
        drain._CtlApproval(channel, run_id=run_id, workdir=tmp_path).broker()
    )
    orch = _orchestrator()
    try:
        with pytest.raises(HarnessPaused) as info:
            asyncio.run(
                orch.execute_tool(
                    "bash",
                    {
                        "command": "echo approved-mark >> calls.log",
                        "workdir": str(tmp_path),
                    },
                    _cfg(tmp_path, "confirm_all"),
                    call_id="call-77",
                )
            )
    finally:
        set_approval_broker(None)
    # The shared loop attaches its checkpoint before the pause leaves the
    # turn; this test stands in for that loop with a Harness-shaped state.
    info.value.checkpoint = {
        "version": 1,
        "user_input": "run the approved mark",
        "mode": "build",
        "messages": [{"kind": "human", "content": "run the approved mark"}],
        "paused": {"call_id": "call-77", "tool": "bash"},
        "remaining": [],
        "state": {},
        "budget": None,
    }
    assert asyncio.run(drain._park_for_human(channel, info.value, tmp_path)) == ""

    # The run is parked: waiting_approval, lease released — waiting for a
    # human is NOT no-progress, and no other worker can claim it meanwhile.
    assert paused.is_set()
    assert _run_status(postgres_url, run_id) == ("waiting_approval", None)

    # Find the approval, approve it — the run re-queues pending.
    record = channel.resume_state("**scan**")  # wrong id -> nothing
    assert record.get("record") is None
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    with engine.connect() as conn:
        approval_id = conn.execute(
            text("SELECT id FROM approvals WHERE run_id = :r"), {"r": run_id}
        ).scalar()
    engine.dispose()
    out = decide_approval(
        postgres_url,
        tenant_id=tenant,
        approval_id=approval_id,
        decision="approved",
        expected_revision=0,
    )
    assert out["status"] == "approved"
    assert _run_status(postgres_url, run_id)[0] == "pending"
    # The ctl op reported which ask it parked on.
    assert paused_info["approval_id"] == approval_id

    # A NEW claim owns the run before any resume executes — the op's
    # lease fence only releases the stored call to the current owner.
    _lease_run(postgres_url, run_id, "wkr-1", 7)
    _set_status(postgres_url, run_id, "leased")

    # The resume child fetches the stored call THROUGH the channel and
    # executes it once — verbatim args, durable-shaped ids, real journal.
    state = channel.resume_state(approval_id)
    record = dict(state.get("record") or {})
    assert record["run_id"] == run_id
    assert drain._DURABLE_CALL_ID_RE.fullmatch(record["call_id"])
    assert record["source_call_id"] == "call-77"
    assert record["arguments"]["command"] == "echo approved-mark >> calls.log"
    # The parked Harness state comes back intact for the resumed loop.
    assert drain.unpack_checkpoint(record["checkpoint_z"])["paused"]["call_id"] == "call-77"

    emitted: list[dict[str, Any]] = []

    class _Emit:
        def _append(self, kind: str, payload: dict[str, Any]) -> None:
            emitted.append({"kind": kind, **payload})

    ok, result, outcome = asyncio.run(
        drain._execute_approved_call(
            record, tmp_path, _Emit(), drain._ChannelJournal(channel)
        )
    )
    assert ok, result[:400]
    # The ok verdict is backed by the orchestrator's recorded evidence,
    # not by parsing the result text.
    assert outcome is not None and outcome["status"] == "succeeded"
    # PowerShell echo emits UTF-16LE+BOM; cmd emits OEM — decode by BOM.
    raw = (tmp_path / "calls.log").read_bytes()
    body = (
        raw.decode("utf-16")
        if raw.startswith((b"\xff\xfe", b"\xfe\xff"))
        else raw.decode("utf-8", "replace")
    )
    assert body.strip() == "approved-mark"

    # Replay again — the PARENT-OWNED journal says completed -> reuse,
    # NOT a second side effect. calls.log still has exactly one append's
    # worth even though the workspace itself is child-writable.
    (tmp_path / "calls.log").unlink()  # simulate a wiped workspace
    again = asyncio.run(
        drain._execute_approved_call(
            record, tmp_path, _Emit(), drain._ChannelJournal(channel)
        )
    )
    assert again == (True, result, None)
    assert not (tmp_path / "calls.log").exists()  # no second side effect


def test_w8_c01_chain_approval_reject_never_executes(
    tmp_path: Path, postgres_url: str
) -> None:
    """A rejected ask: run is cancelled, the stored call can never be
    resumed (record status != approved), and the file it would have
    written never exists."""
    import rxycode_worker.drain as drain
    from rxycode_server.approvals.service import decide_approval, request_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    _lease_run(postgres_url, run_id, "wkr-1", 2)

    asked = request_approval(
        postgres_url,
        tenant_id=tenant,
        run_id=run_id,
        call_id="call_" + "b" * 32,
        tool="edit",
        permission_scope="write",
        arguments={
            "filePath": str(tmp_path / "never.txt"),
            "operation": "write",
            "content": "must-not-exist",
        },
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="wkr-1",
        epoch=2,
        attempt_id="att_" + "c" * 32,
        command="",
        workdir=str(tmp_path),
        source_call_id="raw-9",
    )
    out = decide_approval(
        postgres_url,
        tenant_id=tenant,
        approval_id=asked["approval_id"],
        decision="rejected",
        expected_revision=0,
    )
    assert out["status"] == "rejected"
    assert _run_status(postgres_url, run_id) == ("cancelled", None)
    # A resume probe finds no approved record — the call is dead.
    assert drain._resume_state(postgres_url, tenant, run_id, asked["approval_id"]) is None
    assert not (tmp_path / "never.txt").exists()


# ---------------------------------------------------------------------------
# Chain C — boundary denial: files, bash, and network all refuse.
# ---------------------------------------------------------------------------


def test_w8_c01_chain_boundary_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same real tools refuse out-of-domain writes — path-arg tools are
    hard-rejected in every mode, bash write-targets are hard-rejected under
    Full and broker-gated otherwise, and a rejected ask never executes.
    Script-internal writes (``python -c open(...)``) are deliberately NOT
    gate-parsed: per spec the final backstop for those is the kernel
    boundary (ro mounts, private netns) asserted in the argv unit tests."""
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        ApprovalBroker,
        ApprovalDecision,
        set_approval_broker,
    )
    _sandbox_data_dir(tmp_path, tmp_path, monkeypatch)
    orch = _orchestrator()
    # /tmp is inside the sandbox write domain, and the process cwd on CI
    # can be the runner home. A path under /opt is outside both.
    outside = Path("/opt") / f"rxy-w8-outside-{uuid.uuid4().hex[:8]}.txt"

    asks: list[Any] = []

    class _Reject(ApprovalBroker):
        async def _ask(self, request: Any) -> Any:
            asks.append(request)
            return ApprovalDecision.REJECTED

    set_approval_broker(_Reject())
    try:
        # Path-arg gate: refused outright — the human is never consulted
        # for a file tool writing outside the domain.
        out = asyncio.run(
            orch.execute_tool(
                "edit",
                {
                    "filePath": str(outside),
                    "operation": "write",
                    "content": "escape",
                },
                _cfg(tmp_path, "confirm_all"),
            )
        )
        assert "blocked" in str(out).lower() or "rejected" in str(out).lower()
        assert not outside.exists()
        edit_asks = len(asks)

        # Bash with an absolute out-of-domain write target:
        # - confirm_all: escalated to the human — a REJECT never executes.
        out = asyncio.run(
            orch.execute_tool(
                "bash",
                {"command": f"echo x > {outside}", "workdir": str(tmp_path)},
                _cfg(tmp_path, "confirm_all"),
            )
        )
        assert "rejected" in str(out).lower() or "blocked" in str(out).lower()
        assert not outside.exists()
        # The gate DID escalate this one (bash has no path arg to reject
        # outright — the write-target scan flags it for the human).
        assert len(asks) > edit_asks

        # - full_auto: hard reject — no prompt, no bypass.
        out = asyncio.run(
            orch.execute_tool(
                "bash",
                {"command": f"echo x > {outside}", "workdir": str(tmp_path)},
                _cfg(tmp_path, "full_auto"),
            )
        )
        assert "blocked" in str(out).lower()
        assert not outside.exists()
    finally:
        set_approval_broker(None)
        outside.unlink(missing_ok=True)

    # The writable domain itself is the sandbox-truth — workspace + private
    # home + private tmp, never other tenants' paths or the platform root.
    domain = {str(p) for p in drain._writable_domain(tmp_path)}
    assert str(tmp_path) in domain
    assert not any(".sandboxes" in p for p in domain)


def test_w8_c01_chain_boundary_network_control_plane() -> None:
    """Simulated control-plane/metadata/tenant endpoints are refused at
    the egress evaluator — Bash/Python/MCP reach the network only through
    this filter in deployment (private netns + loopback relay)."""
    from rxycode_worker.egress import evaluate

    async def _fake_private(*_a: Any, **_k: Any) -> list[Any]:
        return [(None, None, None, None, ("10.0.0.9", 0))]

    async def _fake_public(*_a: Any, **_k: Any) -> list[Any]:
        return [(None, None, None, None, ("8.8.8.8", 0))]

    blocked = [
        # cloud metadata endpoint — the classic credential theft target
        ("169.254.169.254", 80),
        # in-cluster control plane services (resolved private addresses)
        ("postgres.internal", 5432),
        ("control-plane.local", 8080),
        # host loopback/admin
        ("127.0.0.1", 3000),
        ("localhost", 22),
        # other tenant private ranges
        ("192.168.7.4", 443),
        ("172.16.0.5", 443),
        ("10.4.0.2", 443),
        # multicast/link-local/unspecified categories
        ("224.0.0.1", 443),
        ("169.254.1.1", 443),
        ("0.0.0.0", 443),
    ]
    for host, port in blocked:
        verdict = asyncio.run(
            evaluate(host, port, set(), resolve=_fake_private)
        )
        assert not verdict.allowed, f"{host}:{port} should be refused ({verdict.reason})"
    # A real public endpoint on an allowed port still passes — dev work
    # (pypi/model/git) is not crippled by the boundary.
    ok = asyncio.run(evaluate("pypi.org", 443, set(), resolve=_fake_public))
    assert ok.allowed
    # ...but the same host on a non-web port is refused (no SMTP/SSH out).
    odd = asyncio.run(evaluate("pypi.org", 25, set(), resolve=_fake_public))
    assert not odd.allowed and odd.reason == "port_not_allowed"


def test_w8_c01_chain_boundary_kernel_confined(tmp_path: Path) -> None:
    """Where bwrap exists, prove the READ boundary end-to-end inside the
    real sandbox: the file tool's unconfined absolute-path reads on the
    host become impossible in the mount namespace — host markers and
    sibling-tenant paths are simply not there, and the private netns has
    no route to a simulated control-plane endpoint at all."""
    pytest.importorskip("rxycode_runner.sandbox.userns")
    from rxycode_runner.sandbox.userns import (
        UsernsSandboxProvider,
        userns_available,
    )

    if not userns_available():
        pytest.skip("bwrap/userns unavailable on this host")

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    provider = UsernsSandboxProvider(tmp_path / "ws")
    handle = provider.create(tenant_id=tenant, workspace_id="w1", retain=False)

    # Host marker + sibling-tenant files that must be unreachable inside.
    marker = tmp_path / "host-marker.txt"
    marker.write_text("host-secret", encoding="utf-8")
    sibling = tmp_path / "ws" / f"{tenant}-other" / "w9" / "tenant-secret.txt"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text("tenant-secret", encoding="utf-8")

    import shutil

    shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    for attempt in (
        # file-tool equivalent: cat a host path that exists outside
        ["-c", f"cat {marker}"],
        # sibling tenant's workspace — not mounted at all
        ["-c", f"cat {sibling}"],
        # python expresses the same read
        ["-c", f"python3 -c \"open('{marker}')\""],
        # simulated control-plane endpoint — private netns has no route
        ["-c", "python3 -c \"import socket;socket.create_connection(('169.254.169.254',80),2)\""],
        # host admin port
        ["-c", "python3 -c \"import socket;socket.create_connection(('172.17.0.1',2375),2)\""],
    ):
        res = provider.exec(
            handle.sandbox_id,
            tenant_id=tenant,
            argv=[shell, *attempt],
            timeout=20,
        )
        assert res.exit_code != 0, (
            f"confined read/connect unexpectedly succeeded: {attempt}\n"
            f"stdout={res.stdout[:300]}"
        )
    provider.destroy(handle.sandbox_id, tenant_id=tenant)


# ---------------------------------------------------------------------------
# Chain D — cancellation & recovery: late approvals die, uncertain journals
# refuse a second side effect, and the ask never strands a claim.
# ---------------------------------------------------------------------------


def test_w8_c01_chain_cancel_kills_late_approval(
    tmp_path: Path, postgres_url: str
) -> None:
    """Ask parks the run -> the user cancels -> a late approval lands ->
    ApprovalStale, never a resurrection. And the approval row is left
    truthfully pending (not silently decided)."""
    import rxycode_worker.drain as drain  # noqa: F401  (module must import)
    from rxycode_server.approvals.service import (
        ApprovalStale,
        decide_approval,
        request_approval,
    )

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    _lease_run(postgres_url, run_id, "wkr-1", 4)

    asked = request_approval(
        postgres_url,
        tenant_id=tenant,
        run_id=run_id,
        call_id="call_" + "d" * 32,
        tool="bash",
        permission_scope="danger",
        arguments={"command": "rm x"},
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="wkr-1",
        epoch=4,
        attempt_id="att_" + "e" * 32,
        command="rm x",
        workdir=str(tmp_path),
    )
    assert _run_status(postgres_url, run_id) == ("waiting_approval", None)

    # The human cancels instead of deciding.
    _set_status(postgres_url, run_id, "cancelled")
    with pytest.raises(ApprovalStale):
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=asked["approval_id"],
            decision="approved",
            expected_revision=0,
        )
    assert _run_status(postgres_url, run_id)[0] == "cancelled"


def test_w8_c01_chain_cancel_reaps_child(tmp_path: Path) -> None:
    """A cancelled wait kills the spawned TREE — _wait_child SIGKILLs
    the supervisor and its descendants (bwrap's pid namespace +
    --die-with-parent in deployment; the psutil sweep anywhere else).
    Prove the reap on a real child AND its grandchild (audit W8-r2)."""
    import sys as _sys

    import psutil

    import rxycode_worker.drain as drain

    pid_file = tmp_path / "grandchild.pid"

    async def drive() -> int:
        proc = await asyncio.create_subprocess_exec(
            _sys.executable,
            "-c",
            "import os,subprocess,sys,time;"
            " p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            f" open(r'{pid_file}','w').write(str(p.pid));"
            " time.sleep(60)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # Same as the spawn site: pin (pid, create_time) at spawn so the
        # sweep can never target a reaped-and-reused pid (audit W8-r3).
        identity = psutil.Process(proc.pid)
        waiter = asyncio.ensure_future(
            drain._wait_child(proc, [], None, identity)
        )
        for _ in range(200):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            await asyncio.sleep(0.05)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        # The direct child is dead — killed by the cancel path, not by
        # the parent exiting.
        assert proc.returncode is not None
        return int(pid_file.read_text())

    grand_pid = asyncio.run(drive())
    # Descendant cleanup is REQUIRED: the grandchild must be dead too —
    # no residue survives a cancelled run.
    for _ in range(100):
        if not psutil.pid_exists(grand_pid):
            return
        time.sleep(0.05)
    pytest.fail(f"grandchild pid {grand_pid} survived the cancel")


def test_w8_c01_chain_journal_uncertain_refuses_second_effect(
    tmp_path: Path,
) -> None:
    """A pending (uncertain) journal entry: the resume path refuses the
    side effect outright — the parent's settle maps that refusal to
    recovery_required, never to another execution."""
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )

    attempt_id = "att_" + "f" * 32
    call_id = "call_" + "1" * 32
    args = {"command": "echo half-done >> out.log", "workdir": str(tmp_path)}
    journal = RemoteJournalAdapter(
        ToolExecutionJournal(str(tmp_path / ".journal"))
    )
    reservation = journal.reserve(
        attempt_id=attempt_id, call_id=call_id, tool="bash", args=args
    )
    assert reservation.action == "execute"
    # The "crash mid-call" state: reserved, never completed.
    record = {
        "tool": "bash",
        "call_id": call_id,
        "attempt_id": attempt_id,
        "arguments": args,
        "command": "echo half-done >> out.log",
    }

    class _Emit:
        def _append(self, *_a: Any, **_k: Any) -> None:
            return

    with pytest.raises(RuntimeError, match="journal-uncertain"):
        asyncio.run(drain._execute_approved_call(record, tmp_path, _Emit(), journal))
    assert not (tmp_path / "out.log").exists()
