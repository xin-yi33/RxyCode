"""WEB-W8-C01. Cloud Full = sandboxed Full Auto; task-private development
environment; control-plane credentials and network boundaries; durable
approval pause/resume bound to the exact call.

Unit layer — pure argv builders, policy evaluators, config merge, the ctl
dispatch surface, the channel-bound broker, and the durable approval
service on a real Postgres. The module test drives the same chains inside
the deployed worker container (real bwrap spawn, real private netns, real
egress relay, real kill-tree cleanup).

Invariants under test:

* ``permission_mode = full_auto`` is an APPROVAL semantic — never an
  isolation level. Every accepted Web target runs inside the per-run
  userns sandbox: same mounts, same private network namespace, same
  egress filter, same writable domain. Local-CLI Full semantics in
  ``core/sandbox/policy.py`` are untouched.
* The confined turn holds no platform credentials: no
  ``RXYCODE_WEB_DATABASE_URL``, no ``RXYCODE_API_KEY``, no copied
  ``api_key*`` config fields — the parent injects real model auth on the
  gateway's upstream hop.
* The durable ask binds ``tenant/run/call/attempt`` plus the verbatim
  arguments; approve executes exactly that call once (journal
  at-most-once); reject/cancel never executes; a late decision on a
  moved-on run is stale, never a resurrection.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


# ---------------------------------------------------------------------------
# 1. _execution_gate — Full is an approval semantic, never an isolation level.
# ---------------------------------------------------------------------------


def test_w8_c01_execution_gate_full_is_permission_not_isolation() -> None:
    """The gate answers ONE question: which permission mode does this run
    execute under — inside the sandbox it always gets. Tenant binding is
    unchanged; malformed placements fail closed."""
    from rxycode_worker.drain import _execution_gate, _UnsupportedTarget

    # Tenant-owned cloud target: every profile resolves to a real mode —
    # full and full_auto both land on the existing no-approval mode.
    assert (
        _execution_gate(
            "cloud:t-1:w1", "full", execution_mode="cloud-only", tenant_id="t-1"
        )
        == "full_auto"
    )
    assert (
        _execution_gate(
            "cloud:t-1:w1", "full_auto", execution_mode="cloud-only", tenant_id="t-1"
        )
        == "full_auto"
    )
    assert (
        _execution_gate(
            "cloud:t-1:w1", "auto_edit", execution_mode="cloud-only", tenant_id="t-1"
        )
        == "auto_edit"
    )
    assert (
        _execution_gate(
            "cloud:t-1:w1", "confirm_all", execution_mode="cloud-only", tenant_id="t-1"
        )
        == "confirm_all"
    )
    # Unknown profile → None = configured default (never a free pass).
    assert (
        _execution_gate(
            "cloud:t-1:w1", "mystery", execution_mode="cloud-only", tenant_id="t-1"
        )
        is None
    )

    # Ownership still binds: a cloud target naming ANOTHER tenant fails
    # closed under EVERY profile — Full cannot launder a cross-tenant bind.
    for profile in ("full", "full_auto", "auto_edit", ""):
        with pytest.raises(_UnsupportedTarget):
            _execution_gate(
                "cloud:t-other:w1",
                profile,
                execution_mode="cloud-only",
                tenant_id="t-1",
            )
        with pytest.raises(_UnsupportedTarget):
            _execution_gate(
                "cloud::w1", profile, execution_mode="cloud-only", tenant_id="t-1"
            )

    # cloud-only still refuses local/sandbox/undeclared placements — Full
    # included.
    for target in ("local:*", "local:w1", "sandbox:x", "", "weird"):
        for profile in ("full", "full_auto", "auto_edit"):
            with pytest.raises(_UnsupportedTarget):
                _execution_gate(
                    target, profile, execution_mode="cloud-only", tenant_id="t-1"
                )

    # sandboxed-local accepts local:* AND tenant cloud — still confined,
    # Full still maps to the no-approval mode (isolation unchanged).
    assert (
        _execution_gate(
            "local:w1", "full", execution_mode="sandboxed-local", tenant_id="t-1"
        )
        == "full_auto"
    )
    assert (
        _execution_gate(
            "cloud:t-1:w1", "full", execution_mode="sandboxed-local", tenant_id="t-1"
        )
        == "full_auto"
    )
    with pytest.raises(_UnsupportedTarget):
        _execution_gate(
            "cloud:t-x:w1", "full", execution_mode="sandboxed-local", tenant_id="t-1"
        )
    with pytest.raises(_UnsupportedTarget):
        _execution_gate(
            "weird", "auto_edit", execution_mode="sandboxed-local", tenant_id="t-1"
        )

    # Unknown execution mode refuses regardless of target.
    with pytest.raises(_UnsupportedTarget):
        _execution_gate(
            "cloud:t-1:w1", "auto_edit", execution_mode="host", tenant_id="t-1"
        )


# ---------------------------------------------------------------------------
# 2. userns argv shape — Full gets identical mounts/network/env isolation.
# ---------------------------------------------------------------------------


def test_w8_c01_sandbox_argv_isolation_shape(tmp_path: Path) -> None:
    """The bwrap argv is a pure function — the isolation shape is asserted
    without a namespace-capable host: private userns/pid/ipc/uts/net,
    die-with-parent, clearenv, only setenv env, private tmpfs /tmp before
    binds, rw domain = workdir + named rw_binds + tmpfs overlays."""
    from rxycode_runner.sandbox.userns import build_sandbox_argv

    workdir = tmp_path / "ws"
    ctl_dir = tmp_path / "ctl"
    fake_usr = tmp_path / "usr-root"  # /usr on the deployed host
    workdir.mkdir()
    ctl_dir.mkdir()
    fake_usr.mkdir()
    argv = build_sandbox_argv(
        workdir=workdir,
        argv=["python", "-m", "rxycode_worker.drain"],
        env={"RXYCODE_CTL_SOCK": str(ctl_dir / "ctl.sock"), "HOME": str(workdir / ".home")},
        ro_binds=["/repo"],
        rw_binds=[str(ctl_dir)],
        overlay_roots=[str(fake_usr)],
    )
    text = " ".join(argv)

    for flag in (
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ):
        assert flag in argv, flag
    assert "--share-net" not in text

    # Only --setenv carries env — nothing else may leak through --clearenv.
    env_keys = [argv[i + 1] for i, part in enumerate(argv) if part == "--setenv"]
    assert "RXYCODE_CTL_SOCK" in env_keys and "HOME" in env_keys
    # Private /tmp precedes every bind (a workdir under /tmp must not be
    # shadowed by the tmpfs).
    assert argv.index("--tmpfs") < argv.index("--bind")
    # The ctl dir is rw-bound at the same path; the workspace binds rw.
    bind_pairs = [
        (argv[i + 1], argv[i + 2]) for i, part in enumerate(argv) if part == "--bind"
    ]
    assert (str(ctl_dir), str(ctl_dir)) in bind_pairs
    assert (str(workdir), str(workdir)) in bind_pairs
    # Overlay makes system-package installs task-private — the host /usr
    # stays ro underneath.
    assert "--overlay" in argv
    assert argv[argv.index("--overlay") + 1] == str(fake_usr)
    # cwd inside the workspace; the confined command runs after `--`.
    assert argv[argv.index("--chdir") + 1] == str(workdir)
    assert argv[-3:] == ["python", "-m", "rxycode_worker.drain"]


def test_w8_c01_sandbox_argv_env_allowlist(tmp_path: Path) -> None:
    """The drain's env contract: credentials never enter the passlist;
    the turn env carries only task-local identity + sockets + proxies."""
    import rxycode_worker.drain as drain

    workdir = tmp_path / "ws"
    workdir.mkdir()
    monkey_env = {
        "RXYCODE_WEB_DATABASE_URL": "postgresql+psycopg://secret@db/x",
        "RXYCODE_API_KEY": "sk-platform-secret",
        "HOME": "/home/root",
        "PATH": "/usr/bin:/bin",
        "RXYCODE_WORKER_MODEL": "deployed",
    }
    import os as _os

    saved = {k: _os.environ.get(k) for k in monkey_env}
    _os.environ.update(monkey_env)
    try:
        env = drain._child_env({"RXYCODE_TURN_RUN_ID": "r1", "RXYCODE_CTL_SOCK": "/s"})
    finally:
        for key, old in saved.items():
            if old is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = old
    assert env["RXYCODE_TURN_RUN_ID"] == "r1"
    assert env["RXYCODE_CTL_SOCK"] == "/s"
    assert "RXYCODE_WEB_DATABASE_URL" not in env
    assert "RXYCODE_API_KEY" not in env
    assert env.get("HOME") != "/home/root"  # HOME comes from _task_turn_env
    assert env.get("PATH") == "/usr/bin:/bin"
    assert env.get("RXYCODE_WORKER_MODEL") == "deployed"


def test_w8_c01_task_private_dev_environment(tmp_path: Path) -> None:
    """edit/bash/python share ONE write domain — the task-private project
    dir, HOME, caches and private /tmp — identical real paths inside the
    sandbox, never host rules."""
    import rxycode_worker.drain as drain

    workdir = tmp_path / "ws"
    env = drain._task_turn_env(workdir)
    home = workdir / ".home"
    assert env["HOME"] == str(home)
    assert env["PIP_CACHE_DIR"].startswith(str(home))
    assert env["npm_config_cache"].startswith(str(home))
    assert env["TMPDIR"] == "/tmp"
    domain = drain._writable_domain(workdir)
    assert domain[0] == str(workdir)
    assert str(home) in domain and "/tmp" in domain


# ---------------------------------------------------------------------------
# 3. Config merge — sandbox-real write domain + credential scrub.
# ---------------------------------------------------------------------------


def test_w8_c01_merge_turn_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The copied config is rewritten for the confined process: write
    domain = sandbox-real paths, os_sandbox forced off (this process IS
    the boundary), EVERY model entry's credential fields die, and the
    used model's base_url points at the loopback egress gateway."""
    import yaml

    import rxycode_worker.drain as drain

    workdir = tmp_path / "ws"
    workdir.mkdir()
    monkeypatch.setenv("RXYCODE_EGRESS_PORT", "18881")
    monkeypatch.setenv("RXYCODE_WORKER_MODEL", "deployed")
    dst = tmp_path / "config.yaml"
    dst.write_text(
        yaml.safe_dump(
            {
                "active_model": "deployed",
                "models": {
                    "deployed": {
                        "provider_id": "openai",
                        "base_url": "https://api.real.example/v1",
                        "model_name": "smoke",
                        "api_key_env": "RXYCODE_API_KEY",
                        "api_key_secret": "cred:abc",
                    },
                    "other": {
                        "base_url": "https://other.example/v1",
                        "api_key": "sk-literal-secret",
                    },
                },
                "safety": {"allowed_write_paths": ["/should-not-survive-alone"]},
                "execution": {"os_sandbox": {"enabled": True}},
            }
        ),
        encoding="utf-8",
    )
    drain._merge_turn_config(dst, workdir)
    data = yaml.safe_load(dst.read_text(encoding="utf-8"))

    domain = data["safety"]["allowed_write_paths"]
    assert str(workdir) in domain and "/tmp" in domain
    assert data["execution"]["workspace_root"] == str(workdir)
    assert data["execution"]["os_sandbox"]["enabled"] is False

    deployed = data["models"]["deployed"]
    assert deployed["base_url"] == "http://127.0.0.1:18881"
    assert "api_key_env" not in deployed
    assert "api_key_secret" not in deployed
    assert deployed["api_key"] == "confined"
    # Non-used entries keep their endpoint but lose every credential —
    # calls to them fail honestly at the egress filter anyway.
    other = data["models"]["other"]
    assert other["base_url"] == "https://other.example/v1"
    assert other["api_key"] == "confined"


# ---------------------------------------------------------------------------
# 4. Egress — execution-environment network boundary.
# ---------------------------------------------------------------------------


def test_w8_c01_egress_evaluate_policy() -> None:
    """The parent-side verdict: private/loopback/link-local/ULA/multicast
    and non-80/443 all refuse; public 80/443 passes; the explicit
    allowlist is the only way to a private address (the in-cluster model
    endpoint). Resolution happens in the parent — an injected resolver
    proves no sandbox DNS is consulted."""
    from rxycode_worker.egress import build_allowlist, evaluate

    async def resolver(host: str, port: int) -> list:
        table = {
            "api.example": [("af", "sock", "proto", "canon", ("93.184.216.34", port))],
            "evil.example": [("af", "sock", "proto", "canon", ("169.254.169.254", port))],
        }
        return table.get(host, [])

    async def drive() -> None:
        # Simulated control-plane + host targets — every one refused.
        for host, port in (
            ("127.0.0.1", 443),
            ("169.254.169.254", 80),  # cloud metadata
            ("10.0.0.9", 443),
            ("172.16.0.5", 443),
            ("192.168.1.1", 443),
            ("fd00::1", 443),
            ("224.0.0.1", 443),
            ("postgres", 5432),  # unresolvable under the fake resolver
            ("93.184.216.34", 5432),  # public IP, wrong port
            ("evil.example", 443),  # resolves to metadata IP → refused
        ):
            verdict = await evaluate(host, port, set(), resolve=resolver)
            assert not verdict.allowed, (host, port, verdict.reason)

        verdict = await evaluate("api.example", 443, set(), resolve=resolver)
        assert verdict.allowed and verdict.reason == "public"

        allowlist = build_allowlist("http://llm.internal:8317/v1", "cache.local:6379")
        assert ("llm.internal", 8317) in allowlist
        assert ("cache.local", 6379) in allowlist
        verdict = await evaluate("llm.internal", 8317, allowlist, resolve=resolver)
        assert verdict.allowed and verdict.reason == "allowlisted"

    asyncio.run(drive())


def test_w8_c01_model_gateway_from_env() -> None:
    """The gateway resolves the platform endpoint parent-side: scheme,
    host, default ports, base path and the injected auth triple. No
    endpoint → no gateway → model calls refuse honestly."""
    from rxycode_worker.egress import model_gateway_from_env

    assert model_gateway_from_env({}) is None
    gw = model_gateway_from_env(
        {
            "RXYCODE_LLM_BASE_URL": "https://api.real.example/v1",
            "RXYCODE_API_KEY": "sk-real",
        }
    )
    assert gw is not None
    assert (gw.scheme, gw.host, gw.port, gw.base_path) == (
        "https",
        "api.real.example",
        443,
        "/v1",
    )
    assert gw.headers["authorization"] == "Bearer sk-real"
    assert gw.headers["x-api-key"] == "sk-real"
    gw2 = model_gateway_from_env({"RXYCODE_LLM_BASE_URL": "http://llm:8317"})
    assert gw2 is not None and (gw2.scheme, gw2.port) == ("http", 8317)
    assert gw2.headers == {}  # no key — upstream is trusted network


def test_w8_c01_gateway_head_injects_auth() -> None:
    """The child's own credential-shaped headers are stripped and the
    parent's real auth is injected; Host is rewritten; body framing
    headers survive verbatim."""
    from rxycode_worker.egress import ModelGateway, _gateway_head

    gw = ModelGateway(
        scheme="http",
        host="llm.internal",
        port=8317,
        base_path="/v1",
        headers={"authorization": "Bearer sk-real"},
    )
    head = _gateway_head(
        gw,
        "POST",
        "/chat/completions",
        [
            "Host: 127.0.0.1:18881",
            "Authorization: Bearer confined",
            "x-api-key: confined",
            "Content-Type: application/json",
            "Content-Length: 42",
            "Connection: keep-alive",
            "User-Agent: openai-python/1.x",
        ],
    ).decode("iso-8859-1")
    assert head.startswith("POST /v1/chat/completions HTTP/1.1\r\n")
    assert "Host: llm.internal:8317\r\n" in head
    assert "authorization: Bearer sk-real\r\n" in head
    assert "confined" not in head
    assert "Content-Length: 42" in head
    assert "Content-Type: application/json" in head
    assert "User-Agent: openai-python/1.x" in head
    assert "keep-alive" not in head
    assert head.endswith("Connection: close\r\n\r\n") or "\r\n\r\n" in head


# ---------------------------------------------------------------------------
# 5. Control channel — dispatch surface + round-trip binding.
# ---------------------------------------------------------------------------


def test_w8_c01_ctl_dispatch_surface() -> None:
    """The server's dispatch enforces the wire contract without a socket:
    oversized/garbage/non-dict requests refuse; unknown ops refuse; a
    handler exception is a typed error, never a wedge; a handler result
    returns ok."""
    from rxycode_worker.ctl import CtlServer, _MAX_REQUEST_BYTES

    async def drive() -> None:
        server = CtlServer(
            Path("unused.sock"),
            {
                "echo": lambda args: {"seen": args.get("x")},
                "boom": lambda args: 1 / 0,
            },
        )
        assert (await server._dispatch(b""))["ok"] is False
        assert (await server._dispatch(b"x" * (_MAX_REQUEST_BYTES + 1)))["ok"] is False
        assert (await server._dispatch(b"not json"))["ok"] is False
        assert (await server._dispatch(b'"s"'))["ok"] is False
        assert (
            await server._dispatch(json.dumps({"op": "unknown", "args": {}}).encode())
        )["ok"] is False
        bad = await server._dispatch(json.dumps({"op": "boom", "args": {}}).encode())
        assert bad["ok"] is False and bad["error"]["type"] == "ZeroDivisionError"
        good = await server._dispatch(
            json.dumps({"op": "echo", "args": {"x": 7}}).encode()
        )
        assert good == {"ok": True, "result": {"seen": 7}}
        # args must be a dict — a bare list is refused, not unpacked.
        bad2 = await server._dispatch(
            json.dumps({"op": "echo", "args": [1]}).encode()
        )
        assert bad2["ok"] is False

    asyncio.run(drive())


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_w8_c01_ctl_roundtrip(tmp_path: Path) -> None:
    """Real UNIX-socket round-trip: CtlServer serves handlers in worker
    threads; ctl_call raises CtlError on failure; oversized asks die."""
    from rxycode_worker.ctl import CtlError, CtlServer, ctl_call

    async def drive() -> None:
        server = CtlServer(tmp_path / "ctl.sock", {"echo": lambda a: dict(a)})
        await server.start()
        try:
            assert ctl_call(server.sock_path, "echo", x=5) == {"x": 5}
            with pytest.raises(CtlError):
                ctl_call(server.sock_path, "missing")
        finally:
            await server.stop()

    asyncio.run(drive())


# ---------------------------------------------------------------------------
# 6. Channel-bound approval broker + emitter — no DB in the confined child.
# ---------------------------------------------------------------------------


def test_w8_c01_ctl_approval_broker(tmp_path: Path) -> None:
    """The confined broker asks ONCE through the channel with the exact
    call identity + raw arguments: asked -> _RunPaused unwinds (the run
    is parked, lease released — nothing executes); refused -> REJECTED;
    already_authorized -> APPROVED. The broker never touches a database."""
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        ApprovalDecision,
        ApprovalRequest,
    )
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

    sent: list[dict[str, Any]] = []

    class _Channel:
        def pause_approval(self, **kwargs: Any) -> dict[str, Any]:
            sent.append(kwargs)
            return {"asked": True, "approval_id": "ap-1", "attempt_id": "att-1"}

    broker = drain._CtlApproval(
        _Channel(), run_id="r1", workdir=tmp_path
    ).broker()

    async def drive() -> None:
        request = ApprovalRequest(
            tool_name="bash",
            args_summary={"command": "rm -rf /tmp/x"},
            risk=RiskLevel.DANGER,
            call_id="call-42",
            arguments={"command": "rm -rf /tmp/x", "workdir": "/w"},
        )
        with pytest.raises(drain._RunPaused):
            await broker.request_approval(request)

    asyncio.run(drive())
    ask = sent[0]
    # The ask carries the raw source call id; the trusted parent derives the
    # journal-keyed durable call_id (tested separately below).
    assert ask["source_call_id"] == "call-42"
    assert ask["tool"] == "bash"
    assert ask["arguments"] == {"command": "rm -rf /tmp/x", "workdir": "/w"}
    assert ask["command"] == "rm -rf /tmp/x"
    assert ask["workdir"] == str(tmp_path)
    assert "danger" in ask["permission_scope"]

    class _Refused:
        def pause_approval(self, **kwargs: Any) -> dict[str, Any]:
            return {"asked": False, "reason": "refused:ApprovalStale"}

    refused = drain._CtlApproval(_Refused(), run_id="r1", workdir=tmp_path).broker()

    async def drive2() -> ApprovalDecision:
        return await refused.request_approval(
            ApprovalRequest(
                tool_name="bash",
                args_summary={},
                risk=RiskLevel.DANGER,
                call_id="c",
                arguments={},
            )
        )

    assert asyncio.run(drive2()) is ApprovalDecision.REJECTED

    class _Authorized:
        def pause_approval(self, **kwargs: Any) -> dict[str, Any]:
            return {"asked": False, "reason": "already_authorized"}

    granted = drain._CtlApproval(_Authorized(), run_id="r1", workdir=tmp_path).broker()

    async def drive3() -> ApprovalDecision:
        from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalRequest
        from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel

        return await granted.request_approval(
            ApprovalRequest(
                tool_name="bash",
                args_summary={},
                risk=RiskLevel.DANGER,
                call_id="c",
                arguments={},
            )
        )

    assert asyncio.run(drive3()) is ApprovalDecision.APPROVED


def test_w8_c01_pause_approval_durable_call_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parent derives the journal-keyed ``call_<32hex>`` from the raw
    source id — deterministic per (run, call), pattern-valid for
    ``remote_call_key``, and never minted by the confined child."""
    import threading
    from types import SimpleNamespace

    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.execution.tool_journal import remote_call_key

    captured: list[dict[str, Any]] = []

    def fake_request_approval(database_url: str, **kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs)
        return {"approval_id": "ap-1"}

    monkeypatch.setattr(
        "rxycode_server.approvals.service.request_approval", fake_request_approval
    )

    cfg = SimpleNamespace(database_url="sqlite://", worker_id="w-1")
    paused = threading.Event()
    handlers = drain._ctl_handlers(
        cfg,
        tenant_id="t1",
        run_id="r1",
        epoch=3,
        workdir=tmp_path,
        journal_dir=tmp_path / "journal",
        paused=paused,
    )
    pause = handlers["pause_approval"]

    raw = "call_OpenAIStyleXyz9"  # provider id — not durable-shaped
    res = pause(
        {
            "source_call_id": raw,
            "tool": "bash",
            "scope": "danger",
            "arguments": {"command": "rm x"},
            "deadline": "2030-01-01T00:00:00+00:00",
            "command": "rm x",
        }
    )
    assert res == {"asked": True, "approval_id": "ap-1", "attempt_id": res["attempt_id"]}
    assert paused.is_set()

    kw = captured[0]
    durable = kw["call_id"]
    assert drain._DURABLE_CALL_ID_RE.fullmatch(durable)
    remote_call_key(durable)  # must not raise — the journal accepts it
    assert kw["source_call_id"] == raw
    assert kw["attempt_id"].startswith("att_")

    # Deterministic: the same underlying call always maps to the same key —
    # duplicate asks for one call dedupe at the journal instead of forking.
    res2 = pause(
        {
            "source_call_id": raw,
            "tool": "bash",
            "scope": "danger",
            "arguments": {"command": "rm x"},
            "deadline": "2030-01-01T00:00:00+00:00",
            "command": "rm x",
        }
    )
    assert captured[1]["call_id"] == durable
    assert res2["asked"] is True

    # A source already in durable shape passes through untouched; a different
    # run binds a different key for the same raw id.
    already = "call_" + "a" * 32
    pause({"source_call_id": already, "deadline": "2030-01-01T00:00:00+00:00"})
    assert captured[2]["call_id"] == already

    handlers2 = drain._ctl_handlers(
        cfg,
        tenant_id="t1",
        run_id="r2",
        epoch=3,
        workdir=tmp_path,
        journal_dir=tmp_path / "journal",
        paused=threading.Event(),
    )
    handlers2["pause_approval"](
        {"source_call_id": raw, "deadline": "2030-01-01T00:00:00+00:00"}
    )
    assert captured[3]["call_id"] != durable


def test_w8_c01_runemit_channel_mode(tmp_path: Path) -> None:
    """In channel mode _RunEmit writes through the parent transport and
    NEVER imports the platform store — a fake emitter captures every row,
    and sqlalchemy.create_engine is monkeypatched to explode on contact."""
    import sqlalchemy

    import rxycode_worker.drain as drain

    captured: list[tuple[str, dict[str, Any]]] = []
    monkey_fail = pytest.MonkeyPatch()
    try:
        monkey_fail.setattr(
            sqlalchemy,
            "create_engine",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("confined emit touched the database")
            ),
        )
        emit = drain._RunEmit(
            "",
            "t1",
            "r1",
            emitter=lambda etype, payload: captured.append((etype, payload)) or 1,
        )
        emit.project("assistant.delta", {"text": "hi"})
        emit.project("assistant.final", {"text": "done", "run_id": "r1"})
    finally:
        monkey_fail.undo()
    assert ("assistant.delta", {"text": "hi"}) in captured
    assert ("assistant.final", {"text": "done", "run_id": "r1"}) in captured


def test_w8_c01_commands_via_channel() -> None:
    """consume_commands_via runs the SAME delivery loop on a channel
    fetch — steer reaches the bound worker; seq cursors dedupe."""
    from rxycode_worker import agent_events

    delivered: list[str] = []

    class _Worker:
        async def deliver(self, text: str) -> dict[str, Any]:
            delivered.append(text)
            return {"accepted": True}

    async def _accept_steer(run_id: str, text: str, worker: Any) -> dict[str, Any]:
        return await worker.deliver(text)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(agent_events, "accept_steer", _accept_steer)
    try:
        agent_events.bind_run("r1", worker=_Worker())
        events = [
            {"seq": 5, "type": "steer.accepted", "payload": {"text": "steer me"}},
            {"seq": 6, "type": "child.cancel", "payload": {"session_id": "s1"}},
        ]
        applied = asyncio.run(
            agent_events.consume_commands_via(lambda after: events, "r1")
        )
        # child.cancel has no bound manager → undelivered → cursor stops at 5.
        assert len(applied) == 1
        assert delivered == ["steer me"]
        # A second pass after seq 5 returns nothing new to apply.
        applied2 = asyncio.run(
            agent_events.consume_commands_via(
                lambda after: [e for e in events if e["seq"] > after], "r1"
            )
        )
        assert applied2 == []
    finally:
        monkey.undo()
        agent_events._BOUND.pop("r1", None)
        agent_events._APPLIED.pop("r1", None)


# ---------------------------------------------------------------------------
# 7. Durable approval service — real Postgres, real lock/CAS semantics.
# ---------------------------------------------------------------------------


def _seed_tenant_run(
    postgres_url: str,
    *,
    tenant: str,
    run_id: str,
    status: str,
    session: str | None = None,
) -> None:
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
    session_id = session or f"s-{run_id}"
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            if db.get(User, f"u-{tenant}") is None:
                db.add(User(id=f"u-{tenant}", github_id=None, kind="local"))
            if db.get(Organization, f"o-{tenant}") is None:
                db.add(Organization(id=f"o-{tenant}", tenant_id=tenant))
            if db.get(Project, f"p-{tenant}") is None:
                db.add(Project(id=f"p-{tenant}", tenant_id=tenant, name="t", repo_config={}))
            if db.get(SessionRow, session_id) is None:
                db.add(
                    SessionRow(
                        id=session_id, tenant_id=tenant, project_id=f"p-{tenant}", title="t"
                    )
                )
            db.add(
                Run(
                    id=run_id,
                    tenant_id=tenant,
                    session_id=session_id,
                    status=status,
                    request_id=f"req-{run_id}",
                )
            )
            db.commit()
    finally:
        engine.dispose()


def test_w8_c01_approval_pause_decide_resume(postgres_url: str) -> None:
    """The full service chain on real Postgres: a leased run's ask parks
    it (waiting_approval + lease released + exact args journaled) —
    approve re-queues pending; decide twice is stale; reject cancels the
    run; and a decision on a run that already moved on is stale, never a
    resurrection (the cancel-then-approve race)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.approvals.service import (
        ApprovalStale,
        cancel_approval,
        decide_approval,
        get_approval,
        request_approval,
    )

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = 3,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": "wkr-1", "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run_id},
            )

        asked = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run_id,
            call_id="call-9",
            tool="bash",
            permission_scope="danger",
            arguments={"command": "rm -rf /tmp/x", "extra": [1, {"a": 2}]},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr-1",
            epoch=3,
            attempt_id="att-9",
            command="rm -rf /tmp/x",
            workdir="/w",
        )
        with engine.connect() as conn:
            status, owner = conn.execute(
                text("SELECT status, lease_owner FROM runs WHERE id = :r"),
                {"r": run_id},
            ).one()
            seq_rows = conn.execute(
                text("SELECT type, payload FROM run_events WHERE run_id = :r ORDER BY seq"),
                {"r": run_id},
            ).all()
        assert status == "waiting_approval" and owner is None
        assert asked["attempt_id"] == "att-9"
        recorded = get_approval(
            postgres_url, tenant_id=tenant, approval_id=asked["approval_id"]
        )
        assert recorded is not None
        # The stored call is verbatim — resume executes THIS, not a summary.
        assert recorded["call_id"] == "call-9"
        assert recorded["attempt_id"] == "att-9"
        assert recorded["arguments"] == {"command": "rm -rf /tmp/x", "extra": [1, {"a": 2}]}
        assert recorded["command"] == "rm -rf /tmp/x"
        assert recorded["status"] == "pending"
        kinds = [str(r.type) for r in seq_rows]
        assert "approval.requested" in kinds

        # Approve → run re-queues pending; the SAME approval can't be
        # decided twice.
        out = decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=asked["approval_id"],
            decision="approved",
            expected_revision=0,
        )
        assert out["status"] == "approved"
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM runs WHERE id = :r"), {"r": run_id}
            ).scalar()
        assert status == "pending"
        with pytest.raises(ApprovalStale):
            decide_approval(
                postgres_url,
                tenant_id=tenant,
                approval_id=asked["approval_id"],
                decision="rejected",
                expected_revision=1,
            )

        # Reject path on a fresh run → cancelled, never re-queued.
        run2 = f"run-{uuid.uuid4().hex[:8]}"
        _seed_tenant_run(postgres_url, tenant=tenant, run_id=run2, status="leased")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = 1,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": "wkr-1", "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run2},
            )
        asked2 = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run2,
            call_id="c2",
            tool="bash",
            permission_scope="danger",
            arguments={},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr-1",
            epoch=1,
        )
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=asked2["approval_id"],
            decision="rejected",
            expected_revision=0,
        )
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM runs WHERE id = :r"), {"r": run2}
            ).scalar()
        assert status == "cancelled"

        # Cancel-then-approve: the run moved on — the late decision is
        # stale, NEVER a resurrection.
        run3 = f"run-{uuid.uuid4().hex[:8]}"
        _seed_tenant_run(postgres_url, tenant=tenant, run_id=run3, status="leased")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = 2,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": "wkr-1", "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run3},
            )
        asked3 = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run3,
            call_id="c3",
            tool="bash",
            permission_scope="danger",
            arguments={},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr-1",
            epoch=2,
        )
        # The user cancels the RUN while the ask is pending (run-level
        # cancel lands the same way a run cancel API would).
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE runs SET status = 'cancelled' WHERE id = :r"),
                {"r": run3},
            )
        with pytest.raises(ApprovalStale):
            decide_approval(
                postgres_url,
                tenant_id=tenant,
                approval_id=asked3["approval_id"],
                decision="approved",
                expected_revision=0,
            )
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM runs WHERE id = :r"), {"r": run3}
            ).scalar()
        assert status == "cancelled"  # not resurrected to pending

        # Explicit ask cancel → same stale verdict; expired deadline
        # settles BOTH sides (approval expired + run cancelled).
        run4 = f"run-{uuid.uuid4().hex[:8]}"
        _seed_tenant_run(postgres_url, tenant=tenant, run_id=run4, status="leased")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = 1,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": "wkr-1", "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run4},
            )
        asked4 = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run4,
            call_id="c4",
            tool="bash",
            permission_scope="danger",
            arguments={},
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
            worker_id="wkr-1",
            epoch=1,
        )
        with pytest.raises(ApprovalStale):
            decide_approval(
                postgres_url,
                tenant_id=tenant,
                approval_id=asked4["approval_id"],
                decision="approved",
                expected_revision=0,
            )
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM runs WHERE id = :r"), {"r": run4}
            ).scalar()
        assert status == "cancelled"  # expiry settled the parked run too
    finally:
        engine.dispose()


def test_w8_c01_pending_resume_binding(postgres_url: str) -> None:
    """_pending_resume returns the stored call ONLY for the latest
    approval.requested of THIS run, and only when that ask is approved —
    anything else (rejected/cross-run) is not a resume."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.approvals.service import decide_approval, request_approval
    from rxycode_worker.drain import _pending_resume

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = 7,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": "wkr", "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run_id},
            )
        asked = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run_id,
            call_id="resume-call",
            tool="bash",
            permission_scope="danger",
            arguments={"command": "touch /w/yes", "workdir": "/w"},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr",
            epoch=7,
            attempt_id="att-resume",
            command="touch /w/yes",
            workdir="/w",
        )
        # Pending (not yet decided) → no resume.
        assert _pending_resume(postgres_url, tenant, run_id) is None
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=asked["approval_id"],
            decision="approved",
            expected_revision=0,
        )
        record = _pending_resume(postgres_url, tenant, run_id)
        assert record is not None
        assert record["call_id"] == "resume-call"
        assert record["attempt_id"] == "att-resume"
        assert record["arguments"]["command"] == "touch /w/yes"
        assert record["status"] == "approved"

        # A different run's approval never resolves for this run.
        other = f"run-{uuid.uuid4().hex[:8]}"
        _seed_tenant_run(postgres_url, tenant=tenant, run_id=other, status="leased")
        assert _pending_resume(postgres_url, tenant, other) is None
        # And a rejected ask is not a resume — run4-style.
        run_rej = f"run-{uuid.uuid4().hex[:8]}"
        _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_rej, status="leased")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = 1,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": "wkr", "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run_rej},
            )
        asked_rej = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run_rej,
            call_id="rej",
            tool="bash",
            permission_scope="danger",
            arguments={},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr",
            epoch=1,
        )
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=asked_rej["approval_id"],
            decision="rejected",
            expected_revision=0,
        )
        assert _pending_resume(postgres_url, tenant, run_rej) is None
    finally:
        engine.dispose()


def test_w8_c01_resume_journal_at_most_once(tmp_path: Path) -> None:
    """The journal decides the second-time question: a completed call is
    never re-executed; an uncertain one refuses a second side effect —
    the at-most-once contract the resume child relies on."""
    from rxycode_worker.interrupt_resume import _journal_state

    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )

    journal_dir = str(tmp_path / ".journal")
    adapter = RemoteJournalAdapter(ToolExecutionJournal(journal_dir))
    call_id = "call_" + "1" * 32  # durable-shaped id (as the parent derives)
    attempt_id = "att_" + "2" * 32  # att_[0-9a-f]{32} journal contract
    assert _journal_state(journal_dir, attempt_id, call_id) == "not_started"

    reservation = adapter.reserve(
        attempt_id=attempt_id, call_id=call_id, tool="bash", args={"command": "x"}
    )
    assert reservation.action == "execute"
    assert _journal_state(journal_dir, attempt_id, call_id) == "unknown"  # pending
    adapter.complete(
        attempt_id=attempt_id,
        call_id=call_id,
        tool="bash",
        args={"command": "x"},
        result="done",
    )
    assert _journal_state(journal_dir, attempt_id, call_id) == "completed"
    # A second reserve on the same (attempt, call) returns the stored
    # result — the duplicate resume path never re-runs the side effect.
    again = adapter.reserve(
        attempt_id=attempt_id, call_id=call_id, tool="bash", args={"command": "x"}
    )
    assert again.action == "reuse" and again.result == "done"
