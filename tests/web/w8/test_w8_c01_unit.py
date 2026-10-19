"""WEB-W8-C01. Cloud Full = sandboxed Full Auto; task-private development
environment; control-plane credentials and network boundaries; durable
approval pause/resume bound to the exact call.

Unit layer — pure argv builders, policy evaluators, config merge, the ctl
dispatch surface, the channel-bound broker/journal, and the durable
approval service on a real Postgres. The module test drives the same
chains through the real ToolOrchestrator and durable store on the host;
the kernel boundary itself (private mounts/netns, egress relay,
kill-tree) is covered here at the argv/policy level — a bwrap-capable
host runs it live in compose.

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
    upper = tmp_path / "ovl" / "usr-upper"
    work = tmp_path / "ovl" / "usr-work"
    workdir.mkdir()
    ctl_dir.mkdir()
    upper.mkdir(parents=True)
    work.mkdir(parents=True)
    argv = build_sandbox_argv(
        workdir=workdir,
        argv=["python", "-m", "rxycode_worker.drain"],
        env={"RXYCODE_CTL_SOCK": str(ctl_dir / "ctl.sock"), "HOME": str(workdir / ".home")},
        ro_binds=["/repo"],
        rw_binds=[str(ctl_dir)],
        overlays=[(str(upper), str(work), "/usr")],
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
    # Overlay uses bwrap's three-operand form — upper+work bound writable
    # first (task-private persistent layer), then --overlay UPPER WORK
    # DEST so system-package installs never touch the host /usr. The
    # mandatory --overlay-src DEST names the ro lower layer and must
    # precede the overlay op (bwrap rejects overlay argv without one).
    idx = argv.index("--overlay")
    assert argv[idx + 1 : idx + 4] == [str(upper), str(work), "/usr"]
    src_idx = argv.index("--overlay-src")
    assert argv[src_idx + 1] == "/usr" and src_idx < idx
    upper_bind = argv.index(str(upper))
    assert argv[upper_bind - 1] == "--bind" and upper_bind < idx
    # cwd inside the workspace; the confined command runs after `--`.
    assert argv[argv.index("--chdir") + 1] == str(workdir)
    assert argv[-3:] == ["python", "-m", "rxycode_worker.drain"]


def test_w8_c01_sandbox_argv_seeded_overlay(tmp_path: Path) -> None:
    """A seed-verdict overlay (container /etc — Docker's injected file
    mounts make the kernel reject it as a lower) mounts a PLAIN COPY as
    the lower, not the system path: the seed is ro-bound at its own
    host path, --overlay-src names it, --overlay still lands on /etc
    (audit W8-r6)."""
    from rxycode_runner.sandbox.userns import build_sandbox_argv

    workdir = tmp_path / "ws"
    upper = tmp_path / "ovl" / "etc-upper"
    work = tmp_path / "ovl" / "etc-work"
    seed = tmp_path / "ovl" / "etc-seed"
    workdir.mkdir()
    upper.mkdir(parents=True)
    work.mkdir(parents=True)
    seed.mkdir()
    argv = build_sandbox_argv(
        workdir=workdir,
        argv=["/bin/true"],
        env={},
        ro_binds=[],
        rw_binds=[],
        overlays=[(str(upper), str(work), "/etc", str(seed))],
    )
    idx = argv.index("--overlay")
    assert argv[idx + 1 : idx + 4] == [str(upper), str(work), "/etc"]
    src_idx = argv.index("--overlay-src")
    assert argv[src_idx + 1] == str(seed) and src_idx < idx
    # The seed is ro-bound at its own path so --overlay-src resolves it.
    ro_pairs = [
        (argv[i + 1], argv[i + 2])
        for i, part in enumerate(argv)
        if part == "--ro-bind"
    ]
    assert (str(seed), str(seed)) in ro_pairs
    seed_idx = argv.index(str(seed))
    assert argv[seed_idx - 1] == "--ro-bind" and seed_idx < src_idx


def test_w8_c01_claim_dirs_removed_at_teardown(tmp_path: Path) -> None:
    """retain=False must retain nothing: the per-claim conf copy, ctl
    dir and overlay upper/work/seed layers are removed wholesale at
    teardown (audit W8-r6) — while the run-keyed journal survives for
    at-most-once replay and a vanished dir never escalates."""
    import rxycode_worker.drain as drain

    state_root = tmp_path / "sandboxes"
    conf = state_root / "sbx-1-conf" / ".data"
    conf.mkdir(parents=True)
    (conf / "config.yaml").write_text("model: x", encoding="utf-8")
    ctl = state_root / "sbx-1-ctl"
    ctl.mkdir()
    (ctl / "ctl.sock").write_text("", encoding="utf-8")
    ovl = state_root / "sbx-1-ovl" / "etc-upper"
    ovl.mkdir(parents=True)
    (ovl / "marker").write_text("x", encoding="utf-8")
    journal = state_root / "journals" / "ten" / "run-1"
    journal.mkdir(parents=True)
    (journal / "calls.log").write_text("reserved", encoding="utf-8")
    gone = state_root / "already-vanished"

    drain._remove_claim_dirs(
        [
            state_root / "sbx-1-conf",
            ctl,
            state_root / "sbx-1-ovl",
            gone,
        ]
    )

    assert not (state_root / "sbx-1-conf").exists()
    assert not ctl.exists()
    assert not (state_root / "sbx-1-ovl").exists()
    assert journal.joinpath("calls.log").read_text() == "reserved"


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
                # Non-model credential-bearing config (audit W8-r2):
                # supported fields outside ``models`` must also be
                # redacted before the file mounts — while non-credential
                # scalars like token budgets survive.
                "rag": {
                    "embedding": {
                        "provider": "openai",
                        "api_key": "sk-embed-secret",
                        "base_url": "https://api.real.example",
                    }
                },
                "mcp": {
                    "servers": {
                        "github": {
                            "command": "mcp-github",
                            "env": {
                                "GITHUB_TOKEN": "ghp_secret",
                                "OPENAI_API_KEY": "sk-mcp",
                                "LOG_LEVEL": "debug",
                            },
                        }
                    }
                },
                "agents": {"budget": {"max_tokens": 4096}},
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
    # Credential-shaped scalars die ANYWHERE in the tree; non-credential
    # keys with similar names (token budgets, log levels) survive.
    assert data["rag"]["embedding"]["api_key"] == "confined"
    assert data["rag"]["embedding"]["base_url"] == "https://api.real.example"
    mcp_env = data["mcp"]["servers"]["github"]["env"]
    assert mcp_env["GITHUB_TOKEN"] == "confined"
    assert mcp_env["OPENAI_API_KEY"] == "confined"
    assert mcp_env["LOG_LEVEL"] == "debug"
    assert data["agents"]["budget"]["max_tokens"] == 4096


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
    paused_info: dict[str, Any] = {}
    handlers = drain._ctl_handlers(
        cfg,
        tenant_id="t1",
        run_id="r1",
        epoch=3,
        workdir=tmp_path,
        journal_dir=tmp_path / "journal",
        paused=paused,
        paused_info=paused_info,
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
    assert paused_info["approval_id"] == "ap-1"

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
        paused_info={},
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


def _lease_run(postgres_url: str, run_id: str, worker: str, epoch: int) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner = :w, lease_epoch = :e,"
                    " lease_until = :u, status = 'leased' WHERE id = :r"
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


def _set_run_status(postgres_url: str, run_id: str, status: str) -> None:
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
        # The old drain's post-exit marker is what lets a new claimant
        # proceed immediately — the poll finds it instead of waiting out
        # the teardown budget.
        from rxycode_server.events.store import append_event

        append_event(
            postgres_url,
            tenant_id=tenant,
            run_id=run_id,
            event_type="turn.paused",
            payload={"approval_id": asked["approval_id"]},
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


# ---------------------------------------------------------------------------
# W8 audit r1 regression legs
# ---------------------------------------------------------------------------


def test_w8_c01_mounted_config_is_prescrubbed(tmp_path: Path) -> None:
    """The config the sandbox READS is sanitized before it is ever mounted —
    a literal api_key in the worker's config.yaml can never be recovered
    from the ro-bound source (audit W8-r1: ro stops writes, not reads)."""
    import yaml

    import rxycode_worker.drain as drain

    src = tmp_path / "src"
    src.mkdir()
    (src / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "active_model": "main",
                "models": {
                    "main": {
                        "api_key": "sk-literal-secret",
                        "api_key_env": "RXYCODE_API_KEY",
                        "base_url": "https://api.real-model.example/v1",
                    },
                    "other": {"api_key": "sk-second", "base_url": "https://x/v1"},
                },
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "conf"
    old = os.environ.get("RXYCODE_DATA_DIR")
    old_model = os.environ.get("RXYCODE_WORKER_MODEL")
    os.environ["RXYCODE_DATA_DIR"] = str(src)
    os.environ.pop("RXYCODE_WORKER_MODEL", None)
    try:
        drain._prepare_child_data_dir(out)
    finally:
        if old is None:
            os.environ.pop("RXYCODE_DATA_DIR", None)
        else:
            os.environ["RXYCODE_DATA_DIR"] = old
        if old_model is None:
            os.environ.pop("RXYCODE_WORKER_MODEL", None)
        else:
            os.environ["RXYCODE_WORKER_MODEL"] = old_model
    mounted = yaml.safe_load((out / "config.yaml").read_text(encoding="utf-8"))
    main = mounted["models"]["main"]
    assert main["api_key"] == "confined"
    assert "api_key_env" not in main
    assert main["base_url"] == f"http://127.0.0.1:{drain._EGRESS_PORT}"
    assert mounted["models"]["other"]["api_key"] == "confined"
    assert "sk-literal-secret" not in (out / "config.yaml").read_text()


def test_w8_c01_egress_connect_tunnels_end_to_end() -> None:
    """A permitted CONNECT actually proxies bytes — the round-1 audit found
    ``self._tunnel`` bound inside a module function so every successful
    forwarding path raised AttributeError. Exercise the real handler
    against a real loopback upstream."""
    import socket

    from rxycode_worker.egress import EgressProxy

    assert callable(getattr(EgressProxy, "_tunnel", None)), "_tunnel must be a method"

    async def drive() -> bytes:
        proxy = EgressProxy("unused.sock", allowlist=frozenset())
        # The CONNECT target is loopback — evaluate() would refuse it, so
        # call _connect's tunnel half via a verdict-free seam: drive
        # _tunnel directly with both stream pairs.
        client_a, client_b = socket.socketpair()
        up_a, up_b = socket.socketpair()
        r_client, w_client = await asyncio.open_connection(sock=client_a)
        r_up, w_up = await asyncio.open_connection(sock=up_a)
        tunnel = asyncio.ensure_future(proxy._tunnel(r_client, w_client, r_up, w_up))
        try:
            client_b.sendall(b"ping\n")
            # recv off the loop — a blocking recv inside the coroutine
            # would starve the tunnel task itself.
            echoed = await asyncio.to_thread(up_b.recv, 64)
            assert echoed == b"ping\n"
            up_b.sendall(b"pong\n")
            back = await asyncio.to_thread(client_b.recv, 64)
            assert back == b"pong\n"
        finally:
            for s in (client_b, up_b):
                s.close()
            client_a.close()
            up_a.close()
            try:
                await asyncio.wait_for(tunnel, timeout=5)
            except Exception:
                pass
        return b"ok"

    assert asyncio.run(drive()) == b"ok"


def test_w8_c01_ctl_journal_ops_roundtrip(
    tmp_path: Path, postgres_url: str
) -> None:
    """journal_* ops run the real RemoteJournalAdapter parent-side so the
    child never touches journal files — reserve/complete/state over the
    handler dict, in parent-owned storage. The reserve is gated on the
    run's live lease AND on (attempt,call,tool,args) being this run's
    stored approval — anything else is refused (audit W8-r2)."""
    from types import SimpleNamespace

    import rxycode_worker.drain as drain
    from rxycode_server.approvals.service import request_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    attempt = "att_" + "a" * 32
    call = "call_" + "b" * 32
    _lease_run(postgres_url, run_id, "w-1", 1)
    request_approval(
        postgres_url,
        tenant_id=tenant,
        run_id=run_id,
        call_id=call,
        tool="bash",
        permission_scope="danger",
        arguments={"command": "x"},
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="w-1",
        epoch=1,
        attempt_id=attempt,
        command="x",
        workdir=str(tmp_path),
    )
    # The ask parks the run; a NEW claim owns it for the journal ops.
    _lease_run(postgres_url, run_id, "w-1", 2)
    cfg = SimpleNamespace(database_url=postgres_url, worker_id="w-1")
    journal_dir = tmp_path / "journal"
    handlers = drain._ctl_handlers(
        cfg,
        tenant_id=tenant,
        run_id=run_id,
        epoch=2,
        workdir=tmp_path,
        journal_dir=journal_dir,
        paused=threading.Event(),
        paused_info={},
    )
    assert handlers["journal_state"](
        {"attempt_id": attempt, "call_id": call}
    ) == {"state": "not_started"}
    res = handlers["journal_reserve"](
        {
            "attempt_id": attempt,
            "call_id": call,
            "tool": "bash",
            "args": {"command": "x"},
        }
    )
    assert res["action"] == "execute"
    assert handlers["journal_state"](
        {"attempt_id": attempt, "call_id": call}
    ) == {"state": "unknown"}
    out = handlers["journal_complete"](
        {
            "attempt_id": attempt,
            "call_id": call,
            "tool": "bash",
            "args": {"command": "x"},
            "result": "done",
        }
    )
    assert out["result"] == "done"
    again = handlers["journal_reserve"](
        {
            "attempt_id": attempt,
            "call_id": call,
            "tool": "bash",
            "args": {"command": "x"},
        }
    )
    assert again["action"] == "reuse" and again["result"] == "done"
    # The files live ONLY in the parent-owned dir — nothing under workdir.
    assert journal_dir.is_dir()
    assert not (tmp_path / ".journal").exists()


def test_w8_c01_journal_ops_fences(tmp_path: Path, postgres_url: str) -> None:
    """The reserve fences (audit W8-r2): an unbound (attempt,call) pair,
    mismatched tool/args, or a lost/cancelled lease each refuse — no
    side-effect grant slips past the binding."""
    from types import SimpleNamespace

    import rxycode_worker.drain as drain
    from rxycode_server.approvals.service import request_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    attempt = "att_" + "c" * 32
    call = "call_" + "d" * 32
    _lease_run(postgres_url, run_id, "w-1", 1)
    request_approval(
        postgres_url,
        tenant_id=tenant,
        run_id=run_id,
        call_id=call,
        tool="bash",
        permission_scope="danger",
        arguments={"command": "real"},
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="w-1",
        epoch=1,
        attempt_id=attempt,
        command="real",
        workdir=str(tmp_path),
    )
    _lease_run(postgres_url, run_id, "w-1", 2)
    cfg = SimpleNamespace(database_url=postgres_url, worker_id="w-1")
    journal_dir = tmp_path / "journal"

    def ops(worker: str, epoch: int) -> Any:
        return drain._ctl_handlers(
            cfg,
            tenant_id=tenant,
            run_id=run_id,
            epoch=epoch,
            workdir=tmp_path,
            journal_dir=journal_dir,
            paused=threading.Event(),
            paused_info={},
        )

    # A pair the run never asked for: refused outright.
    unbound = ops("w-1", 2)["journal_reserve"](
        {"attempt_id": "att_" + "9" * 32, "call_id": "call_" + "9" * 32,
         "tool": "bash", "args": {"command": "real"}}
    )
    assert unbound["action"] == "refused"
    # The real pair with swapped args: not the approved call — refused.
    wrong_args = ops("w-1", 2)["journal_reserve"](
        {"attempt_id": attempt, "call_id": call,
         "tool": "bash", "args": {"command": "rm -rf /"}}
    )
    assert wrong_args["action"] == "refused"
    # The real pair under a foreign claim: refused.
    foreign = ops("w-other", 99)["journal_reserve"](
        {"attempt_id": attempt, "call_id": call,
         "tool": "bash", "args": {"command": "real"}}
    )
    assert foreign["action"] == "refused"
    # The real pair under THIS claim while live: granted.
    granted = ops("w-1", 2)["journal_reserve"](
        {"attempt_id": attempt, "call_id": call,
         "tool": "bash", "args": {"command": "real"}}
    )
    assert granted["action"] == "execute"
    # Cancel mid-flight: the SAME claim can no longer reserve — but
    # journal_complete still records the already-made side effect so the
    # next claimant reuses instead of re-running.
    _set_run_status(postgres_url, run_id, "cancel_requested")
    refused = ops("w-1", 2)["journal_reserve"](
        {"attempt_id": attempt, "call_id": call,
         "tool": "bash", "args": {"command": "real"}}
    )
    assert refused["action"] == "refused"
    completed = ops("w-1", 2)["journal_complete"](
        {"attempt_id": attempt, "call_id": call,
         "tool": "bash", "args": {"command": "real"}, "result": "ok"}
    )
    assert completed["result"] == "ok"
    # And completing an unbound pair never records anything.
    denied = ops("w-1", 2)["journal_complete"](
        {"attempt_id": "att_" + "9" * 32, "call_id": "call_" + "9" * 32,
         "tool": "bash", "args": {}, "result": "x"}
    )
    assert denied.get("refused") is True


def test_w8_c01_channel_journal_speaks_ops() -> None:
    """_ChannelJournal maps the adapter surface onto TurnChannel methods —
    the resume child reserves/completes through the parent, never files."""
    import rxycode_worker.drain as drain

    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeChannel:
        def journal_state(self, **kw: Any) -> str:
            calls.append(("journal_state", kw))
            return "not_started"

        def journal_reserve(self, **kw: Any) -> dict[str, Any]:
            calls.append(("journal_reserve", kw))
            return {"action": "execute", "result": None}

        def journal_complete(self, **kw: Any) -> str:
            calls.append(("journal_complete", kw))
            return "ok"

    journal = drain._ChannelJournal(FakeChannel())
    assert journal.state(attempt_id="a", call_id="c") == "not_started"
    res = journal.reserve(attempt_id="a", call_id="c", tool="bash", args={"x": 1})
    assert res.action == "execute"
    assert journal.complete(
        attempt_id="a", call_id="c", tool="bash", args={"x": 1}, result="r"
    ) == "ok"
    assert [name for name, _ in calls] == [
        "journal_state",
        "journal_reserve",
        "journal_complete",
    ]



def test_w8_c01_resume_state_lease_fence(postgres_url: str) -> None:
    """approve->claim->cancel must not let a late resume_state execute: the
    op only returns the stored call while THIS claim (worker+epoch, live
    status, unexpired lease) still owns the run (audit W8-r1)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.approvals.service import decide_approval, request_approval
    import rxycode_worker.drain as drain
    from types import SimpleNamespace

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET lease_owner='wkr-1', lease_epoch=9,"
                    " lease_until=:u WHERE id=:r"
                ),
                {"u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run_id},
            )
        asked = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run_id,
            call_id="call_fence",
            tool="bash",
            permission_scope="danger",
            arguments={"command": "touch /w/x"},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr-1",
            epoch=9,
            command="touch /w/x",
            workdir="/w",
        )
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=asked["approval_id"],
            decision="approved",
            expected_revision=0,
        )

        def ops_for(worker: str, epoch: int) -> Any:
            cfg = SimpleNamespace(database_url=postgres_url, worker_id=worker)
            return drain._ctl_handlers(
                cfg,
                tenant_id=tenant,
                run_id=run_id,
                epoch=epoch,
                workdir=Path("/w"),
                journal_dir=Path("/j"),
                paused=threading.Event(),
                paused_info={},
            )["resume_state"]

        # The approving claim finished and a new claim owns the run.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET status='leased', lease_owner='wkr-2',"
                    " lease_epoch=10, lease_until=:u WHERE id=:r"
                ),
                {"u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run_id},
            )
        ours = ops_for("wkr-2", 10)({"approval_id": asked["approval_id"]})
        assert ours["record"] is not None
        assert ours["record"]["call_id"] == "call_fence"

        # A stale/foreign claim gets nothing — the approved row is not a
        # pass for whoever happens to ask.
        foreign = ops_for("wkr-other", 11)({"approval_id": asked["approval_id"]})
        assert foreign["record"] is None

        # Cancel after claim: the stored call may never execute late.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE runs SET status='cancel_requested' WHERE id=:r"),
                {"r": run_id},
            )
        cancelled = ops_for("wkr-2", 10)({"approval_id": asked["approval_id"]})
        assert cancelled["record"] is None
    finally:
        engine.dispose()


def test_w8_c01_paused_marker_poll_predicate() -> None:
    """_paused_marker_seen is the durable teardown proof — False until the
    old drain's post-exit event lands for THAT approval, True after."""
    import rxycode_worker.drain as drain

    seen: list[dict[str, Any]] = []

    class FakeResult:
        def __init__(self, row: Any) -> None:
            self._row = row

        def first(self) -> Any:
            return self._row

    class FakeConn:
        def execute(self, stmt: Any, params: dict[str, Any]) -> Any:
            seen.append(params)
            if params["aid"] == "ap-no":
                return FakeResult(None)
            return FakeResult((1,))

        def __enter__(self) -> "FakeConn":
            return self

        def __exit__(self, *a: Any) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

        def dispose(self) -> None:
            pass

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr("sqlalchemy.create_engine", lambda *a, **k: FakeEngine())
        assert drain._paused_marker_seen("db", "r1", "ap-yes") is True
        assert drain._paused_marker_seen("db", "r1", "ap-no") is False
    finally:
        monkey.undo()
    assert seen and all(p["rid"] == "r1" for p in seen)


def test_w8_c01_child_emit_reserved_namespaces(postgres_url: str) -> None:
    """The ctl emit surface writes agent/UI events but refuses every
    control-plane namespace a forged child could abuse (audit W8-r2):
    turn.paused (teardown proof), steer.accepted/child.cancel (command
    injection), approval.requested (resume lookup), run.*/worker.*
    (terminalization/lease)."""
    from types import SimpleNamespace

    import rxycode_worker.drain as drain

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    cfg = SimpleNamespace(database_url=postgres_url, worker_id="w-1")
    handlers = drain._ctl_handlers(
        cfg,
        tenant_id=tenant,
        run_id=run_id,
        epoch=1,
        workdir=Path("/w"),
        journal_dir=Path("/j"),
        paused=threading.Event(),
        paused_info={},
    )
    emit = handlers["emit"]
    for reserved in (
        "turn.paused",
        "turn.started",
        "run.error",
        "run.created",
        "approval.requested",
        "approval.resumed",
        "worker.lease",
        "usage.attribution",
        "steer.accepted",
        "child.cancel",
    ):
        out = emit({"type": reserved, "payload": {"approval_id": "x"}})
        assert out.get("denied") == "reserved-namespace", reserved
        assert out["seq"] == 0
    for allowed in (
        "tool.call",
        "tool.result",
        "assistant.delta",
        "assistant.final",
        "question.requested",
        "usage.delta",
        "telemetry.span",
        "notify.event/tool_begin",
    ):
        out = emit({"type": allowed, "payload": {"n": 1}})
        assert out["seq"] > 0, allowed
    # The denied writes really never landed: no forged turn.paused row
    # exists for _paused_marker_seen to find.
    assert drain._paused_marker_seen(postgres_url, run_id, "x") is False


def test_w8_c01_old_namespace_alive_probe(tmp_path: Path) -> None:
    """The ctl-socket probe is the teardown discriminator (audit W8-r2):
    no ctl dir / no socket / refused listener -> provably dead; a live
    listener -> alive; a missing id or unprobeable path -> unknown."""
    import socket as _socket

    import rxycode_worker.drain as drain

    root = tmp_path / "state"
    root.mkdir()
    # No id / no root -> cannot tell.
    assert drain._old_namespace_alive(root, "") is None
    assert drain._old_namespace_alive(None, "s1") is None
    # No ctl dir at all -> supervisor gone.
    assert drain._old_namespace_alive(root, "gone") is False
    # ctl dir without a socket -> dead.
    (root / "dead-ctl").mkdir()
    assert drain._old_namespace_alive(root, "dead") is False
    # A real listening unix socket -> alive.
    if not hasattr(_socket, "AF_UNIX"):
        pytest.skip("AF_UNIX unavailable on this host")
    ctl = root / "live-ctl"
    ctl.mkdir()
    srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    srv.bind(str(ctl / "ctl.sock"))
    srv.listen(1)
    try:
        assert drain._old_namespace_alive(root, "live") is True
    finally:
        srv.close()
    # Stale socket file after close: listener refuses -> dead.
    if sys.platform != "win32":
        assert drain._old_namespace_alive(root, "live") is False


def test_w8_c01_pending_resume_teardown_barrier(
    postgres_url: str, tmp_path: Path
) -> None:
    """The parent-authored turn.paused marker is the ONLY teardown proof
    (audit W8-r3): without it the claim returns teardown_unproven even
    when the recorded sandbox's ctl socket is absent — a live child can
    unlink its own rw-bound ctl dir, and a foreign claimant may lack the
    host-local path entirely. The socket probe only logs liveness."""
    import socket as _socket

    import rxycode_worker.drain as drain
    from rxycode_server.approvals.service import decide_approval, request_approval
    from rxycode_server.events.store import append_event

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    _lease_run(postgres_url, run_id, "wkr-1", 5)
    asked = request_approval(
        postgres_url,
        tenant_id=tenant,
        run_id=run_id,
        call_id="call_" + "f" * 32,
        tool="bash",
        permission_scope="danger",
        arguments={"command": "x"},
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="wkr-1",
        epoch=5,
        attempt_id="att_" + "f" * 32,
        command="x",
        workdir=str(tmp_path),
        sandbox_id="dead-sandbox",
    )
    decide_approval(
        postgres_url,
        tenant_id=tenant,
        approval_id=asked["approval_id"],
        decision="approved",
        expected_revision=0,
    )
    def _approved_run(suffix: str) -> tuple[str, str]:
        """Seed+lease+ask+approve a fresh run; returns (run_id, approval_id)."""
        rid = f"run-{suffix}-{uuid.uuid4().hex[:6]}"
        _seed_tenant_run(postgres_url, tenant=tenant, run_id=rid, status="leased")
        _lease_run(postgres_url, rid, "wkr-1", 5)
        a = request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=rid,
            call_id="call_" + uuid.uuid4().hex,
            tool="bash",
            permission_scope="danger",
            arguments={"command": "x"},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr-1",
            epoch=5,
            attempt_id="att_" + uuid.uuid4().hex,
            command="x",
            workdir=str(tmp_path),
            sandbox_id=f"sbx-{suffix}",
        )
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=a["approval_id"],
            decision="approved",
            expected_revision=0,
        )
        return rid, str(a["approval_id"])

    root = tmp_path / "state"
    root.mkdir()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(drain, "_LEASE_IO_BUDGET", 0.01)
    try:
        # No marker AND an absent ctl dir: inconclusive, NOT death — the
        # child owns its ctl dir and could have unlinked it while alive.
        unproven = drain._pending_resume(
            postgres_url, tenant, run_id, state_root=root
        )
        assert unproven is not None
        assert unproven.get("teardown_unproven") is True

        # The parent-authored marker is what lets the claim proceed.
        append_event(
            postgres_url,
            tenant_id=tenant,
            run_id=run_id,
            event_type="turn.paused",
            payload={"approval_id": str(asked["approval_id"])},
        )
        record = drain._pending_resume(
            postgres_url, tenant, run_id, state_root=root
        )
        assert record is not None
        assert not record.get("teardown_unproven")
        assert record["sandbox_id"] == "dead-sandbox"
        import rxycode_worker.drain as _d

        # An approval whose record names no sandbox cannot be probed at
        # all -> unprobeable -> unproven on every platform.
        run2, aid2 = _approved_run("noid")

        def fake_noid(*_a: Any, **_k: Any) -> dict[str, Any]:
            return {"sandbox_id": "", "run_id": run2,
                    "approval_id": aid2,
                    "call_id": "call_x", "attempt_id": "att_x",
                    "status": "approved"}

        monkey.setattr(_d, "_resume_state", fake_noid)
        unproven2 = drain._pending_resume(
            postgres_url, tenant, run2, state_root=root
        )
        assert unproven2 is not None
        assert unproven2.get("teardown_unproven") is True
        if hasattr(_socket, "AF_UNIX"):
            # A live listener on the recorded sandbox -> unproven.
            ctl = root / "live-ctl"
            ctl.mkdir()
            srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            srv.bind(str(ctl / "ctl.sock"))
            srv.listen(1)
            try:
                run3, aid3 = _approved_run("live")

                def fake_live(*_a: Any, **_k: Any) -> dict[str, Any]:
                    return {"sandbox_id": "live", "run_id": run3,
                            "approval_id": aid3,
                            "call_id": "call_x", "attempt_id": "att_x",
                            "status": "approved"}

                monkey.setattr(_d, "_resume_state", fake_live)
                blocked = drain._pending_resume(
                    postgres_url, tenant, run3, state_root=root
                )
                assert blocked is not None
                assert blocked.get("teardown_unproven") is True
            finally:
                srv.close()
    finally:
        monkey.undo()


def test_w8_c01_request_approval_never_parks_cancel_requested(
    postgres_url: str,
) -> None:
    """cancel_requested is a current lease for settling but must never
    be PARKED: an ask landing after the kill would otherwise overwrite
    the cancellation with waiting_approval and requeue the dead run on
    approve (audit W8-r2)."""
    from rxycode_server.approvals.service import ApprovalStale, request_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed_tenant_run(postgres_url, tenant=tenant, run_id=run_id, status="leased")
    _lease_run(postgres_url, run_id, "wkr-1", 3)
    _set_run_status(postgres_url, run_id, "cancel_requested")
    with pytest.raises(ApprovalStale):
        request_approval(
            postgres_url,
            tenant_id=tenant,
            run_id=run_id,
            call_id="call_" + "e" * 32,
            tool="bash",
            permission_scope="danger",
            arguments={},
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
            worker_id="wkr-1",
            epoch=3,
        )
    # The run was NOT reparked: still cancel_requested, lease intact for
    # the drain's own settle path.
    assert _run_status_check(postgres_url, run_id) == "cancel_requested"


def _run_status_check(postgres_url: str, run_id: str) -> str:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return str(
                conn.execute(
                    text("SELECT status FROM runs WHERE id=:r"), {"r": run_id}
                ).scalar()
            )
    finally:
        engine.dispose()


def test_w8_c01_run_journal_dir_is_run_keyed(tmp_path: Path) -> None:
    """The resume journal is keyed by RUN, never by the per-claim
    sandbox id — a reclaimed run must see the prior claimant's
    reservations or the same approved call executes twice (W8-r2)."""
    import rxycode_worker.drain as drain

    d = drain._run_journal_dir(tmp_path, "t1", "r1")
    assert d == tmp_path / "journals" / "t1" / "r1"
    assert drain._run_journal_dir(tmp_path, "t1", "r2") != d


def test_w8_c01_tool_call_outcome_classification() -> None:
    """Journal completion is replay safety, not success — the stored
    string is classified so error markers settle failed (W8-r2)."""
    import rxycode_worker.drain as drain

    for bad in (
        "[error: tool 'x' not found]",
        "[error executing bash: ValueError]",
        "[blocked: write path not allowed: /etc]",
        "[evidence failed: no artifact]",
        "[rejected: no approval broker available]",
        "[rejected by user: bash]",
        "[cancelled: tool 'bash']",
        "[dry-run] not executed: bash(x)",
        "  [error: leading whitespace]",
        # Registered-tool formats the local table missed — the classifier
        # is now the canonical log.log_helpers one (audit W8-r3).
        "[workflow error: no name or script provided]",
        "[workflow timeout: exceeded 30s]",
        "[search error: backend unavailable]",
        "[agent error: recursion]",
        "[pipeline error: stage 2]",
        "Download failed: connection reset",  # real bare tool format
        "Failed to install requirements: x",
    ):
        assert drain._tool_call_failed(bad), bad
    for ok in (
        "wrote 3 files",
        "pytest: 5 passed",
        "",
        "all good [error] later",
        # A successful tool may literally PRINT classifier content —
        # only the prefix tables may classify tool output (audit W8-r4).
        "echo output: circuit breaker tripped in stage 3",
        "docs mention 模型调用已暂停 as a design note",
        # r5: a SUCCESSFUL command may print text starting with 'Error:' —
        # bash.py emits raw stdout for exit-0 runs; it must not settle
        # the replay as failed.
        "Error: fixture text\nmore output",
        "error: something failed",      # not a real registered-tool prefix
        "failed to download artifact",  # real format is 'Download failed:'
    ):
        assert not drain._tool_call_failed(ok), ok


def test_w8_c01_execute_approved_call_error_outcome(tmp_path: Path) -> None:
    """An approved call to a missing/unavailable tool completes the
    journal with an error outcome — ok=False, and a second resume reuses
    the same error instead of re-running (audit W8-r2's counterexample:
    'status: succeeded' for a not-found tool can never happen again)."""
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )

    record = {
        "tool": "no_such_tool_w8",
        "call_id": "call_" + "7" * 32,
        "attempt_id": "att_" + "7" * 32,
        "arguments": {},
    }

    class _Emit:
        def _append(self, *_a: Any, **_k: Any) -> None:
            return

    journal = RemoteJournalAdapter(ToolExecutionJournal(str(tmp_path / "j")))
    ok, text = asyncio.run(
        drain._execute_approved_call(record, tmp_path, _Emit(), journal)
    )
    assert ok is False
    assert "not found" in text
    # Second resume: journal completed -> reuse -> same error, no rerun.
    ok2, text2 = asyncio.run(
        drain._execute_approved_call(record, tmp_path, _Emit(), journal)
    )
    assert ok2 is False and text2 == text

def test_w8_c01_scrub_envlist_runtogether_and_dsn() -> None:
    """Whole-tree scrub must cover every SUPPORTED credential spelling
    (audit W8-r3): MCP env lists (``KEY=VALUE`` items), run-together
    names like ``PGPASSWORD``/``ACCESSTOKEN``, and URLs with embedded
    userinfo passwords under innocent names like ``database_url`` —
    while real budgets/identifiers survive."""
    import rxycode_worker.drain as drain

    cfg = {
        "mcpServers": {
            "gh": {
                "command": "srv",
                "env": [
                    "GITHUB_TOKEN=ghp_secret",
                    "PGPASSWORD=pw123",
                    "DATABASE_URL=postgres://u:p@db.internal:5432/app",
                    "PATH=/usr/bin",
                    "HOME=/data",
                ],
                # Positional args carry secrets too (audit W8-r4) — and
                # separated flag-value pairs (W8-r5) and credential URLs
                # whose query string contains "=" (W8-r6).
                "args": [
                    "--dsn",
                    "postgres://u:p@db.internal:5432/app",
                    "postgres://u:p@db.internal/app?sslmode=require",
                    "--api-key=flag_secret",
                    "--api-key",
                    "pair_secret",
                    "--verbose",
                ],
            },
            "dictform": {"env": {"API_KEY": "k-secret", "NORMAL": "ok"}},
        },
        "database": {"database_url": "postgres://u:p@db:5432/x", "dsn": "postgres://u:p@d/x"},
        "plain_url": "postgres://db:5432/no-creds",
        "embedding": {"rag": {"embedding": {"api_key": "emb-secret"}}},
        "budgets": {"max_tokens": 4096, "token_budget": 99, "sort_key": "name"},
        "identifiers": {"worker_id": "w1", "session_token_name": "field"},
    }
    drain._scrub_credential_values(cfg)

    env = cfg["mcpServers"]["gh"]["env"]
    assert "GITHUB_TOKEN=confined" in env
    assert "PGPASSWORD=confined" in env
    assert "DATABASE_URL=confined" in env
    assert "PATH=/usr/bin" in env and "HOME=/data" in env
    args = cfg["mcpServers"]["gh"]["args"]
    assert args[1] == "confined"                    # positional userinfo URL
    assert args[2] == "confined"  # userinfo URL whose query has '=' (W8-r6)
    assert args[3] == "--api-key=confined"          # --flag=value spelling
    assert args[4] == "--api-key"                   # flag kept…
    assert args[5] == "confined"                    # …its VALUE redacted (W8-r5)
    assert args[0] == "--dsn" and args[6] == "--verbose"  # non-secret args kept
    assert cfg["mcpServers"]["dictform"]["env"]["API_KEY"] == "confined"
    assert cfg["mcpServers"]["dictform"]["env"]["NORMAL"] == "ok"
    assert cfg["database"]["database_url"] == "confined"
    assert cfg["database"]["dsn"] == "confined"
    # No userinfo -> not a credential; stays.
    assert cfg["plain_url"] == "postgres://db:5432/no-creds"
    assert cfg["embedding"]["rag"]["embedding"]["api_key"] == "confined"
    # Budgets/identifiers survive — word-boundary anchored.
    assert cfg["budgets"]["max_tokens"] == 4096
    assert cfg["budgets"]["token_budget"] == 99
    assert cfg["budgets"]["sort_key"] == "name"
    assert cfg["identifiers"]["session_token_name"] == "field"


def test_w8_c01_wait_child_no_sweep_on_reused_pid(tmp_path: Path) -> None:
    """A captured proc_identity that is no longer running means the pid
    was reaped-and-reused: the descendant sweep must NOT fire, or the
    replacement process's children get killed (audit W8-r3)."""
    import rxycode_worker.drain as drain

    class _Proc:
        pid = 424242
        returncode = None
        stderr = None
        killed = False

        async def wait(self) -> None:
            raise asyncio.CancelledError()

        def kill(self) -> None:
            type(self).killed = True

    class _Identity:
        """psutil handle semantics: is_running False == pid reused."""

        def __init__(self, alive: bool) -> None:
            self._alive = alive
            self.children_called = False

        def is_running(self) -> bool:
            return self._alive

        def children(self, recursive: bool = True) -> list[Any]:
            self.children_called = True
            return []

    async def _go(identity: Any) -> _Proc:
        proc = _Proc()
        try:
            await drain._wait_child(proc, [], None, identity)
        except asyncio.CancelledError:
            pass
        return proc

    dead = _Identity(alive=False)
    proc = asyncio.run(_go(dead))
    assert proc.killed is True          # proc.kill() still fires
    assert dead.children_called is False  # ...but no reused-pid sweep
    live = _Identity(alive=True)
    asyncio.run(_go(live))
    assert live.children_called is True


def test_w8_c01_resume_settled_maps_to_terminal() -> None:
    """_ResumeSettled carries the verdict into the shared finalize path —
    a probe failure or teardown_unproven maps to recovery_required, a
    stored error maps to failed, a clean stored result to succeeded
    (audit W8-r3: no early settle_run return)."""
    import rxycode_worker.drain as drain

    err = drain._ResumeSettled("recovery_required", "unproven")
    assert err.status == "recovery_required" and "unproven" in err.detail
    ok = drain._ResumeSettled("succeeded")
    assert ok.status == "succeeded" and ok.detail == ""


def test_w8_c01_ctl_fragmented_request_dispatches(tmp_path: Path) -> None:
    """A valid request split across socket fragments must still dispatch —
    reader.read() returned the first chunk and partial JSON was rejected
    as 'not JSON'; any ask/journal frame >64KB died silently (W8-r5)."""
    from rxycode_worker.ctl import CtlServer

    async def go() -> dict[str, Any]:
        server = CtlServer(
            tmp_path / "unused.sock",
            {"echo": lambda a: {"n": len(a["t"])}},
        )
        listener = await asyncio.start_server(server._handle, "127.0.0.1", 0)
        port = listener.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        payload = (
            json.dumps({"op": "echo", "args": {"t": "a" * 300000}}).encode()
            + b"\n"
        )
        writer.write(payload[:128])          # fragment 1 — partial JSON
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.write(payload[128:])          # fragment 2 — the rest
        try:
            writer.write_eof()
        except (ConnectionError, OSError):
            pass
        response = await asyncio.wait_for(reader.readline(), 10)
        writer.close()
        listener.close()
        await listener.wait_closed()
        return json.loads(response)

    resp = asyncio.run(go())
    assert resp["ok"] is True and resp["result"]["n"] == 300000


def test_w8_c01_safe_unlink_inside_symlinked_dir(tmp_path: Path) -> None:
    """``.data`` planted as a symlink to a host dir must NEVER let the
    parent's cleanup delete a host file (audit W8-r5): POSIX refuses via
    O_NOFOLLOW, the realpath guard refuses elsewhere."""
    import rxycode_worker.drain as drain

    host_dir = tmp_path / "host"
    host_dir.mkdir()
    victim = host_dir / "config.yaml"
    victim.write_text("secret", encoding="utf-8")
    link = tmp_path / "ws" / ".data"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(host_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation needs privilege on this host")
    drain._safe_unlink_inside(link, "config.yaml")
    assert victim.read_text() == "secret"


def test_w8_c01_safe_unlink_inside_real_dir(tmp_path: Path) -> None:
    """The normal case still works — a stale config inside a REAL .data
    directory is removed."""
    import rxycode_worker.drain as drain

    data = tmp_path / ".data"
    data.mkdir()
    stale = data / "config.yaml"
    stale.write_text("old", encoding="utf-8")
    drain._safe_unlink_inside(data, "config.yaml")
    assert not stale.exists()
    # Missing file is not an error.
    drain._safe_unlink_inside(data, "config.yaml")


def test_w8_c01_scrub_inline_launcher_strings() -> None:
    """Opaque strings carry credential material the whole-item grammar
    never sees — ``args: ["-c", "exec srv --api-key K"]`` is ONE item,
    and the mounted config is readable whether or not MCP ever runs
    (audit W8-r7). The surgical pass removes only the secret span:
    ``--flag VALUE``, ``--flag=VALUE``, ``KEY=VALUE`` for credential
    names, and URL userinfo — while syntax survives."""
    import rxycode_worker.drain as drain

    cfg = {
        "mcpServers": {
            "sh": {
                "command": "sh",
                "args": [
                    "-c",
                    "exec server --api-key EXAMPLE_PLATFORM_KEY --verbose",
                    "run --token=tok123 now",
                    "export API_KEY=sk-live; srv --dsn postgres://u:p@h/x",
                    "x == y --normal flag",
                    # Quoted values with spaces (audit W8-r8): the
                    # quote-wrapped secret dies with its quotes.
                    "srv --api-key 'AUDIT KEY WITH SPACES' -v",
                    'env API_KEY="AUDIT_QUOTED_KEY" run',
                    # Shell-expression values glued to a credential
                    # flag (audit W8-r9): $(...) and ""X are ONE word —
                    # the flag consumes the whole word, leaving no
                    # secret remainder.
                    "srv --api-key $(printf %s AUDIT_SUB_KEY) -v",
                    'srv --api-key ""AUDIT_CONCAT_KEY -v',
                    'curl --header "Authorization: Bearer AUDIT_H" u',
                    'curl -H "X-Api-Key: RAWTOKEN123" u',
                    "--api-key",  # flag at END of item list — no value
                ],
            }
        },
        "launcher": "sh -c 'srv postgres://u:p@db --password pw1'",
        "doc": "the token = abc and mode == fast",  # prose, not creds
        "news": "the bearer of bad news",           # scheme prose lives
        "bare_url": "postgres://u:p@db:5432/app",
    }
    drain._scrub_credential_values(cfg)

    args = cfg["mcpServers"]["sh"]["args"]
    assert args[1] == "exec server --api-key confined --verbose"
    assert args[2] == "run --token=confined now"
    # A credential URL as a flag's VALUE dies whole — fail-closed.
    assert args[3] == "export API_KEY=confined; srv --dsn confined"
    assert args[4] == "x == y --normal flag"          # == and --flag kept
    assert args[5] == "srv --api-key confined -v"     # quoted secret dies
    assert args[6] == 'env API_KEY=confined run'      # quoted KEY=V dies
    assert args[7] == "srv --api-key confined -v"     # $(...) word dies
    assert args[8] == "srv --api-key confined -v"     # glued ""X dies
    assert args[9] == 'curl --header "Authorization: Bearer confined" u'
    assert args[10] == 'curl -H "X-Api-Key: confined" u'
    assert args[11] == "--api-key"                    # nothing follows it
    # dict scalar composite strings — surgical, not whole-redaction.
    assert cfg["launcher"] == (
        "sh -c 'srv postgres://confined:confined@db --password confined'"
    )
    assert cfg["news"] == "the bearer of bad news"
    # A bare credential URL value is still a secret whole.
    assert cfg["bare_url"] == "confined"


def test_w8_c01_child_spawn_chdir_and_safepath(tmp_path: Path) -> None:
    """python -m resolves sys.path[0] from the SPAWN cwd: a writable
    project containing ``rxycode_worker/`` would shadow the trusted
    drain and bypass approval/journal machinery (audit W8-r7). The
    drain therefore spawns with chdir=/tmp — the private tmpfs mounted
    before every bind, nothing pre-plantable — plus ``-s`` so a ``.pth``
    hook planted under the writable task HOME never runs before the
    trusted module (audit W8-r8). The workspace is still bound; the
    child sets its real cwd via set_working_directory. The hardening
    lives ONLY on the spawn argv — no PYTHONSAFEPATH/PYTHONNOUSERSITE
    env: task python keeps ordinary cwd-import semantics."""
    import rxycode_worker.drain as drain
    from rxycode_runner.sandbox.userns import build_sandbox_argv

    env = drain._child_env({"RXYCODE_TURN_RUN_ID": "r1"})
    # Bootstrap hardening must NOT leak into descendants (audit W8-r8):
    # a task's own ``python -c 'import solution'`` resolves the
    # workspace normally.
    assert "PYTHONSAFEPATH" not in env
    assert "PYTHONNOUSERSITE" not in env

    child = drain._trusted_child_argv()
    assert child[-2:] == ["-m", "rxycode_worker.drain"]
    assert "-s" in child                       # user-site .pth closed
    if sys.version_info >= (3, 11):
        assert "-P" in child                 # cwd off sys.path

    workdir = tmp_path / "ws"
    workdir.mkdir()
    argv = build_sandbox_argv(
        workdir=workdir,
        argv=child,
        env={},
        ro_binds=[],
        rw_binds=[],
        chdir="/tmp",
    )
    assert argv[argv.index("--chdir") + 1] == "/tmp"
    # The workspace remains mounted — only the spawn cwd moved.
    bind_pairs = [
        (argv[i + 1], argv[i + 2])
        for i, part in enumerate(argv)
        if part == "--bind"
    ]
    assert (str(workdir), str(workdir)) in bind_pairs
    tail = argv[argv.index("--") + 1 :]
    assert tail == child


def test_w8_c01_scrub_nested_shell_substitution() -> None:
    """Audit W8-r10: nested ``$(...)`` cannot strand a secret — a
    regex word matcher stops at the first ``)`` and left the tail
    ``AUDIT_NESTED_KEY)`` mounted in the child config."""
    import rxycode_worker.drain as drain

    s = "exec server --api-key $(printf %s $(printf ignored) AUDIT_NESTED_KEY) -v"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_NESTED_KEY" not in out
    assert out.startswith("exec server --api-key confined")
    assert out.endswith(" -v")


def test_w8_c01_scrub_backtick_substitution() -> None:
    """Audit W8-r10: a backtick substitution `` `cmd` `` is shell
    syntax too — its interior secret must not survive."""
    import rxycode_worker.drain as drain

    s = "exec server --api-key `printf %s AUDIT_BACKTICK_KEY` -v"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_BACKTICK_KEY" not in out
    assert out == "exec server --api-key confined -v"


def test_w8_c01_scrub_azure_api_key_header() -> None:
    """Audit W8-r10: ``api-key: TOKEN`` is the Azure-style header the
    egress gateway understands — it was missing from the header-name
    table."""
    import rxycode_worker.drain as drain

    s = 'curl --header "api-key: AUDIT_AZURE_KEY" example'
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_AZURE_KEY" not in out
    assert "api-key: confined" in out


def test_w8_c01_scrub_consumed_word_no_tail_artifact() -> None:
    """A flag-token inside an already-consumed quoted value must not
    be reprocessed and re-appended out of place (regression guard for
    the scanner overlap guard)."""
    import rxycode_worker.drain as drain

    s = "sh -c 'srv postgres://u:p@db --password pw1'"
    out = drain._scrub_inline_secrets(s)
    assert out == "sh -c 'srv postgres://confined:confined@db --password confined'"
    assert not out.endswith("' confined")


def test_w8_c01_scrub_dollar_brace_word() -> None:
    """``${VAR}/path`` glued to a credential flag is one shell word —
    the whole word must die, not just ``${VAR}``."""
    import rxycode_worker.drain as drain

    out = drain._scrub_inline_secrets("exec srv --token ${HOME}/x now")
    assert out == "exec srv --token confined now"


def test_w8_c01_scrub_line_continuation() -> None:
    r"""Audit W8-r11: ``\<newline>`` is a shell line continuation —
    the real value word sits on the next line and still belongs to
    the credential flag."""
    import rxycode_worker.drain as drain

    s = "exec server --api-key \\nAUDIT_CONTINUED_KEY"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_CONTINUED_KEY" not in out
    assert out == "exec server --api-key confined"


def test_w8_c01_scrub_process_substitution() -> None:
    """Audit W8-r11: ``<(cmd)``/``>(cmd)`` are WORDS, not redirects —
    ``--api-key-file <(printf %s KEY)`` kept its whole secret."""
    import rxycode_worker.drain as drain

    s = "srv --api-key-file <(printf %s AUDIT_FILE_KEY) -v"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_FILE_KEY" not in out
    assert out == "srv --api-key-file confined -v"


def test_w8_c01_scrub_digest_auth_header() -> None:
    """Audit W8-r11: ``Digest`` auth is a k=v list whose ENTIRE value
    is credential material — single-fragment redaction left the full
    ``response=`` mounted."""
    import rxycode_worker.drain as drain

    s = (
        'curl -H "Authorization: Digest username=\\"u\\", realm=\\"r\\",'
        ' nonce=\\"n\\", response=\\"AUDIT_DIGEST_RESP\\"" x'
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_DIGEST_RESP" not in out
    assert "Authorization: Digest confined" in out


def test_w8_c01_scrub_nested_parameter_expansion() -> None:
    """Audit W8-r12: ``${...}`` nests — ``${_A:-${_B:-} KEY}`` must be
    consumed to the balanced close; a first-``}`` match stranded
    ``KEY}`` mounted."""
    import rxycode_worker.drain as drain

    s = "exec server --api-key ${_RXY_A:-${_RXY_B:-} AUDIT_PARAM_KEY} -v"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_PARAM_KEY" not in out
    assert out == "exec server --api-key confined -v"


def test_w8_c01_scrub_ansi_c_quoted_value() -> None:
    """Audit W8-r12: ``$'a\' KEY'`` is ONE argument — ANSI-C quoting
    honors ``\'``; treating it as a POSIX single quote strands the
    secret tail."""
    import rxycode_worker.drain as drain

    s = "exec server --password $'a\\' AUDIT_ANSI_KEY'"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_ANSI_KEY" not in out
    assert out == "exec server --password confined"


def test_w8_c01_scrub_digest_escaped_quote_pair() -> None:
    """Audit W8-r12: a Digest pair value may itself contain ``\\"`` —
    ``username="a\\"b"`` — closing the pair at the escaped quote
    stranded the trailing ``response=`` pair."""
    import rxycode_worker.drain as drain

    s = (
        'curl -H "Authorization: Digest username=\\"a\\\\\\"b\\",'
        ' response=\\"AUDIT_RESP3\\"" x'
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_RESP3" not in out
    assert "Digest confined" in out


def test_w8_c01_scrub_inner_quotes_in_substitution() -> None:
    """Audit W8-r13: ``"$(printf "%s " K | tr -d ' ')"`` is ONE word —
    the ``"`` inside ``$(`` does not close the outer quote; a naive
    quote-find stranded ``K | tr -d ' ')"`` mounted."""
    import rxycode_worker.drain as drain

    s = (
        "exec server --api-key " + chr(34) + "$(printf "
        + chr(34) + "%s " + chr(34) + " AUDIT_QUOTED_KEY | tr -d "
        + chr(39) + " " + chr(39) + ")" + chr(34)
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_QUOTED_KEY" not in out
    assert out == "exec server --api-key confined"


def test_w8_c01_scrub_heredoc_body() -> None:
    """Audit W8-r13: a heredoc body is data — ``3<<'TAG'`` redacts the
    fd path but the body text must die too; the marker and terminator
    survive."""
    import rxycode_worker.drain as drain

    s = (
        "exec server --api-key-file /dev/fd/3 3<<" + chr(39)
        + "RXY_KEY" + chr(39) + chr(10) + "AUDIT_HEREDOC_KEY"
        + chr(10) + "RXY_KEY"
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_HEREDOC_KEY" not in out
    assert "RXY_KEY" in out  # terminator survives
    assert "confined" in out


def test_w8_c01_scrub_digest_ext_value_params() -> None:
    """Audit W8-r13: RFC 7616 ``username*`` ext parameters —
    ``username*=UTF-8''J%C3%A4…`` — must not break the pair grammar
    and leave ``response=`` mounted."""
    import rxycode_worker.drain as drain

    s = (
        "curl -H " + chr(34) + "Authorization: Digest username*=UTF-8"
        + chr(39) + chr(39) + "J%C3%A4s%C3%B8n%20Doe" + chr(39)
        + ", realm=" + chr(34) + "r" + chr(34) + ", response="
        + chr(34) + "AUDIT_RESP5" + chr(34) + chr(34) + " x"
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_RESP5" not in out
    assert "Digest confined" in out


def test_w8_c01_scrub_case_pattern_in_substitution() -> None:
    """Audit W8-r14: ``$(case x in x) K;; esac)`` — a case pattern's
    ``)`` is not the substitution closer; ``case``/``esac`` are
    tracked as keyword contexts."""
    import rxycode_worker.drain as drain

    s = "exec server --api-key $(case x in x) printf %s AUDIT_CASE_KEY;; esac) -v"
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_CASE_KEY" not in out
    assert out == "exec server --api-key confined -v"


def test_w8_c01_scrub_heredoc_hyphen_delimiter() -> None:
    """Audit W8-r14: ``<<'RXY-KEY'`` — delimiters are arbitrary words,
    not identifiers; a hyphenated tag must still redact its body."""
    import rxycode_worker.drain as drain

    s = (
        "exec server --api-key-file /dev/fd/3 3<<" + chr(39) + "RXY-KEY" + chr(39)
        + chr(10) + "AUDIT_DELIMITER_KEY" + chr(10) + "RXY-KEY"
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_DELIMITER_KEY" not in out
    assert "RXY-KEY" in out  # terminator survives


def test_w8_c01_scrub_multiple_heredocs_one_line() -> None:
    """Audit W8-r14: ``3<<A 4<<B`` queues two bodies on one command
    line — both must die, read in order."""
    import rxycode_worker.drain as drain

    s = (
        "exec server --api-key-file /dev/fd/4 3<<" + chr(39) + "RXY_CFG" + chr(39)
        + " 4<<" + chr(39) + "RXY_KEY" + chr(39) + chr(10) + "{}" + chr(10) + "RXY_CFG"
        + chr(10) + "AUDIT_MULTI_KEY" + chr(10) + "RXY_KEY"
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_MULTI_KEY" not in out
    assert "RXY_CFG" in out and "RXY_KEY" in out


def test_w8_c01_scrub_unterminated_heredoc() -> None:
    """Audit W8-r14: an unterminated heredoc body runs to EOF in bash
    — the whole tail is body and must die."""
    import rxycode_worker.drain as drain

    s = (
        "exec --api-key-file /dev/fd/3 3<<" + chr(39) + "E" + chr(39) + chr(10)
        + "AUDIT_UNTERM_KEY" + chr(10) + "still body"
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_UNTERM_KEY" not in out
    assert "still body" not in out


def test_w8_c01_scrub_auth_scheme_substitution_value() -> None:
    """Audit W8-r15: a scheme value that IS a shell word —
    Bearer $(printf %s K) — must die as ONE word; a charset
    regex strands the command text mounted."""
    import rxycode_worker.drain as drain

    for s in (
        'curl -H "Authorization: Bearer $(printf %s AUDIT_HKEY)" u',
        'curl -H "Authorization: Bearer ${TOKEN:-AUDIT_HKEY}" u',
        'X-Api-Key: $(printf %s AUDIT_HKEY)',
    ):
        out = drain._scrub_inline_secrets(s)
        assert "AUDIT_HKEY" not in out, out
    out = drain._scrub_inline_secrets(
        'curl -H "Authorization: Bearer AUDIT_PLAIN" u'
    )
    assert out == 'curl -H "Authorization: Bearer confined" u'
    # Header name + scheme + quoting survive.
    assert '"Authorization: Bearer confined"' in out


def test_w8_c01_scrub_long_url_password() -> None:
    """Audit W8-r15: a userinfo password longer than 256 chars is
    still a password — the charset bound must not be a bypass."""
    import rxycode_worker.drain as drain

    url = "https://user:" + "p" * 300 + "@example.org/api"
    assert drain._has_url_secret(url)
    cfg = {"endpoint": url}
    drain._scrub_credential_values(cfg)
    assert "p" * 300 not in cfg["endpoint"]


def test_w8_c01_scrub_url_port_path_not_userinfo() -> None:
    """Audit W8-r15: https://host:443/@scope/pkg has NO userinfo —
    the @ belongs to the path. A / in the password charset let
    the authority bleed into the path and redacted an innocent URL."""
    import rxycode_worker.drain as drain

    cfg = {"endpoint": "https://registry.npmjs.org:443/@scope/pkg"}
    drain._scrub_credential_values(cfg)
    assert cfg["endpoint"] == "https://registry.npmjs.org:443/@scope/pkg"


def test_w8_c01_scrub_bare_scheme_prose_survives() -> None:
    """Audit W8-r15: Basic configuration is prose — a bare scheme
    word only redacts a value that LOOKS credential-shaped (digit,
    symbol, or serious length)."""
    import rxycode_worker.drain as drain

    cfg = {"description": "Basic configuration for this server"}
    drain._scrub_credential_values(cfg)
    assert cfg["description"] == "Basic configuration for this server"
    cfg = {"note": "the bearer of bad news"}
    drain._scrub_credential_values(cfg)
    assert cfg["note"] == "the bearer of bad news"
    # Real token-shaped bare-scheme values still die.
    out = drain._scrub_inline_secrets("Bearer eyJhbGciOiJIUzI1NiJ9.x.y")
    assert out == "Bearer confined"


def test_w8_c01_scrub_cyclic_yaml_alias() -> None:
    """Audit W8-r15: yaml.safe_load turns &x [*x] into a real
    object cycle — traversal must dedup by id, not RecursionError."""
    import rxycode_worker.drain as drain

    node = {"x": []}
    node["x"].append(node)
    drain._scrub_credential_values(node)  # no RecursionError
    shared = ["token=K"]
    node2 = {"a": shared, "b": shared}
    drain._scrub_credential_values(node2)
    assert node2["a"] is node2["b"]


def test_w8_c01_scrub_rescan_work_budget() -> None:
    """Audit W8-r15: nested compound values fan rescan calls out
    exponentially — a 292-char input caused ~200k calls. The work
    budget fails closed instead of amplifying."""
    import rxycode_worker.drain as drain

    s = "safe"
    for _ in range(12):
        s = '--normal "$(X=$(echo ' + s + '))"'
    out = drain._scrub_inline_secrets(s)
    assert "confined" in out


def test_w8_c01_scrub_header_prefixed_substitution() -> None:
    """Audit W8-r16: Bearer prefix$(printf %s K) is ONE shell
    word — a leading plain segment must not bound the redaction and
    leave the substitution text mounted."""
    import rxycode_worker.drain as drain

    out = drain._scrub_inline_secrets(
        'curl -H "Authorization: Bearer prefix$(printf %s AUDIT_PK)" u'
    )
    assert "AUDIT_PK" not in out
    assert out == 'curl -H "Authorization: Bearer confined" u'
    out = drain._scrub_inline_secrets(
        'curl -H "Authorization: Bearer pre${TOKEN:-AUDIT_PK}" u'
    )
    assert "AUDIT_PK" not in out
    # Glued quote segments also stay one word.
    out = drain._scrub_inline_secrets('Bearer pre' + chr(39) + 'AUDIT_PK' + chr(39) + 'x')
    assert out == 'Bearer confined'


def test_w8_c01_scrub_empty_username_url() -> None:
    """Audit W8-r16: https://:SECRET@host has an EMPTY user — the
    password is live either way and must still die."""
    import rxycode_worker.drain as drain

    cfg = {"endpoint": "https://:AUDIT_EUP@example.org/api"}
    drain._scrub_credential_values(cfg)
    assert "AUDIT_EUP" not in cfg["endpoint"]


def test_w8_c01_scrub_url_query_fragment_not_userinfo() -> None:
    """Audit W8-r16: ? and # end the authority — a query or
    fragment @ is not a userinfo separator."""
    import rxycode_worker.drain as drain

    for url in (
        "https://example.org:443?email=user@example.org",
        "https://example.org:443#contact@example.org",
    ):
        cfg = {"endpoint": url}
        drain._scrub_credential_values(cfg)
        assert cfg["endpoint"] == url


def test_w8_c01_scrub_heredoc_line_continuation() -> None:
    r"""Audit W8-r16: inside an UNQUOTED heredoc, \<newline>
    joins lines before the terminator compare — a physical EOF
    that continues prefix\ is body content, and the real body
    extends to the NEXT terminator."""
    import rxycode_worker.drain as drain

    s = (
        "cat <<EOF" + chr(10) + "prefix" + chr(92) + chr(10) + "EOF"
        + chr(10) + "AUDIT_HDKEY" + chr(10) + "EOF"
    )
    out = drain._scrub_inline_secrets(s)
    assert "AUDIT_HDKEY" not in out
    assert out.endswith("EOF")


def test_w8_c01_scrub_deep_alias_chain() -> None:
    """Audit W8-r16: an acyclic alias chain a thousand links deep is
    a DAG, not a cycle — id-dedup alone cannot stop a RecursionError;
    traversal is iterative."""
    import rxycode_worker.drain as drain

    node = cur = {"k": []}
    for _ in range(1200):
        nxt = []
        cur["k"].append(nxt)
        cur = {"k": nxt}
    drain._scrub_credential_values(node)  # no RecursionError
