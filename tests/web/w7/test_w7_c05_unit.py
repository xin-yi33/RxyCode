"""WEB-W7-C05. The compose stack really comes up; unsafe deploy shapes are refused.

Contract: ``infra/compose/compose.yaml`` is launched with a per-test project
name and per-test secrets (``docker compose -p <proj> up -d``). Postgres, the
api service and the worker service all reach ``healthy``; the one-shot
``migrate`` and ``webbuild`` services complete with exit code 0. The HTTPS
gateway then proves the whole path end to end: ``GET /`` returns the built
frontend, ``GET /api/v1/auth/csrf`` returns 200 through the TLS proxy, and the
durable Postgres on the published loopback port shows the Alembic head plus
the web schema. TLS is verified honestly: the same URL fails certificate
validation with the default CA bundle and succeeds with ``verify=False``
(Caddy internal CA — a real TLS listener, not a plaintext pass-through).

Negative: a ``docker compose -f base -f bad.yaml config`` overlay that adds
``privileged: true``, a docker.sock mount, ``network_mode: host``, and literal
secret values is REFUSED by the validator in this file — the same invariants
the compose file documents (validated against the real base file first). A
local-mode bind of the web gateway on ``0.0.0.0`` is refused by
``reject_as_public_web_gateway`` through ``rxycode_server.main.serve``.

Skip policy: only a missing docker CLI/engine skips. This environment has a
working docker engine, so the contract runs for real.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]

# The checkout is seeded into the `repo-src` volume through `reposync` — this
# Docker Desktop does not mount Windows bind paths (verified: any -v/--mount
# of a host path hangs container start), so the test streams a tar over the
# exec stdin instead. The include list is the real code the stack needs.
_REPO_INCLUDE = (
    "__init__.py",
    "__main__.py",
    "main.py",
    "api_server.py",
    "api_server_models.py",
    "api_server_stream.py",
    "common_elements.py",
    "entrypoint.py",
    "pyproject.toml",
    "requirements.txt",
    "appserver",
    "auth",
    "cache",
    "config",
    "core",
    "execution",
    "history",
    "log",
    "lsp",
    "mcp",
    "memory",
    "planning",
    "plugins",
    "protocol",
    "rag",
    "recovery",
    "scheduler",
    "synthesis",
    "tools",
    "utils",
    "validation",
    "packages",
    "apps",
    "infra",
)
_REPO_INCLUDE_FILES = ("frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts",)
_EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", "dist", "build", ".venv"}


def _repo_tar() -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()

    def _keep(info: Any) -> Any:
        if any(part in _EXCLUDE_DIRS for part in Path(info.name).parts):
            return None
        if info.name.endswith(".pyc"):
            return None
        return info

    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel in _REPO_INCLUDE:
            source = REPO / rel
            if source.is_dir():
                tar.add(source, arcname=rel, filter=_keep)
            elif source.is_file():
                tar.add(source, arcname=rel, filter=_keep)
        for rel in _REPO_INCLUDE_FILES:
            source = REPO / rel
            assert source.is_file(), f"missing seeded file {rel}"
            tar.add(source, arcname=rel, filter=_keep)
        marker = tarfile.TarInfo(".rxy-sync-done")
        marker.size = 0
        marker.mtime = int(time.time())
        tar.addfile(marker)
    return buffer.getvalue()


def _seed_repo(project: str, env: dict[str, str]) -> None:
    payload = _repo_tar()
    last = b""
    for _attempt in range(30):
        push = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "-p",
                project,
                "exec",
                "-T",
                "reposync",
                "sh",
                "-c",
                "tar -xf - -C /repo",
            ],
            input=payload,
            capture_output=True,
            check=False,
            env=env,
            timeout=300,
        )
        if push.returncode == 0:
            return
        last = push.stderr
        time.sleep(2)
    raise RuntimeError(f"repo seed failed:\n{last.decode(errors='replace')}")


for _entry in (
    REPO,
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

COMPOSE_FILE = REPO / "infra" / "compose" / "compose.yaml"
STACK_TIMEOUT = 1500.0
SERVICE_MISSING_GRACE = 120.0
SECRET_ENV_KEY = re.compile(r"(?i)(password|secret|token|api[_-]?key|credential)")
ENV_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::[-?][^}]*)?\}$")
LOOPBACK_BINDS = {"127.0.0.1", "::1", "localhost"}


class ComposeRefused(RuntimeError):
    """A merged compose document broke a deploy invariant."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _stack_env(pg_port: int, https_port: int, http_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "RXYCODE_POSTGRES_PASSWORD": f"pg-{secrets.token_urlsafe(24)}",
            "RXYCODE_MINIO_ROOT_USER": f"minio-{secrets.token_hex(8)}",
            "RXYCODE_MINIO_ROOT_PASSWORD": f"minio-{secrets.token_urlsafe(24)}",
            "RXYCODE_WEB_SECRET": secrets.token_urlsafe(40),
            "RXYCODE_WEB_ORIGINS": f"https://localhost:{https_port}",
            "RXYCODE_PG_PORT": str(pg_port),
            "RXYCODE_HTTPS_PORT": str(https_port),
            "RXYCODE_HTTP_PORT": str(http_port),
            "RXYCODE_GITHUB_CLIENT_ID": "",
            "RXYCODE_GITHUB_CLIENT_SECRET": "",
            "RXYCODE_GITHUB_REDIRECT_URI": "",
        }
    )
    return env


def _compose(
    project: str,
    env: dict[str, str],
    *args: str,
    extra_files: tuple[Path, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    for override in extra_files:
        command += ["-f", str(override)]
    command += ["-p", project, *args]
    done = subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=env,
        timeout=900,
    )
    # text=True would decode with the locale codec (GBK here); docker output
    # is UTF-8, so decode it ourselves — a decode crash leaves stdout=None.
    return subprocess.CompletedProcess(
        command,
        done.returncode,
        (done.stdout or b"").decode("utf-8", errors="replace"),
        (done.stderr or b"").decode("utf-8", errors="replace"),
    )


def _service_states(project: str, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    done = _compose(project, env, "ps", "-a", "--format", "json")
    states: dict[str, dict[str, Any]] = {}
    for line in done.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        row = json.loads(line)
        name = str(row.get("Service") or row.get("Name") or "")
        if name:
            states[name] = row
    return states


_WANTED = {
    "postgres": "healthy",
    "redis": "healthy",
    "minio": "healthy",
    "api": "healthy",
    "worker": "healthy",
    "gateway": "healthy",
    "reposync": "exited",
    "migrate": "exited",
    "webbuild": "exited",
}


def _row_ok(row: dict[str, Any], want: str) -> bool:
    state = str(row.get("State") or "").lower()
    health = str(row.get("Health") or "").lower()
    exit_code = str(row.get("ExitCode") if row.get("ExitCode") is not None else "")
    if want == "healthy":
        return health == "healthy"
    if want == "running":
        return state == "running"
    return state == "exited" and exit_code == "0"


def _wait_stack(project: str, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Poll until every service is healthy or a one-shot exited cleanly."""
    deadline = time.time() + STACK_TIMEOUT
    missing_deadline = time.time() + SERVICE_MISSING_GRACE
    last: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        last = _service_states(project, env)
        missing = [name for name in _WANTED if name not in last]
        if missing and time.time() > missing_deadline:
            raise RuntimeError(f"services never appeared: {missing}; states={last}")
        if not missing and all(_row_ok(last[name], want) for name, want in _WANTED.items()):
            return last
        time.sleep(3)
    logs = _compose(project, env, "logs", "--no-color", "--tail", "80")
    raise RuntimeError(f"stack did not become healthy; states={last}\n{logs.stdout}\n{logs.stderr}")


def _https_get(url: str, *, verify: bool, timeout: float = 15.0) -> Any:
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={"Accept": "application/json,text/html"})
    return urllib.request.urlopen(request, context=context, timeout=timeout)


@pytest.fixture()
def compose_stack() -> Any:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is required for the real compose contract")
    engine = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if engine.returncode != 0:
        pytest.skip("docker engine is not reachable")
    project = f"rxyw7c05-{uuid.uuid4().hex[:8]}"
    pg_port = _free_port()
    https_port = _free_port()
    http_port = _free_port()
    env = _stack_env(pg_port, https_port, http_port)
    try:
        # `up` itself lives inside try/finally: a startup timeout or a failed
        # `up` must still `down -v` the partially created project.
        up = _compose(project, env, "up", "-d", "--remove-orphans")
        assert up.returncode == 0, f"compose up failed:\n{up.stdout}\n{up.stderr}"
        _seed_repo(project, env)
        states = _wait_stack(project, env)
        yield {
            "project": project,
            "env": env,
            "states": states,
            "pg_dsn": (
                "postgresql+psycopg://rxycode:"
                f"{env['RXYCODE_POSTGRES_PASSWORD']}@127.0.0.1:{pg_port}/rxycode"
            ),
            "https_base": f"https://localhost:{https_port}",
            "http_base": f"http://localhost:{http_port}",
        }
    finally:
        _compose(project, env, "down", "-v", "--remove-orphans")


# ---------------------------------------------------------------------------
# Negative validator — mirrors the invariants compose.yaml documents.
# ---------------------------------------------------------------------------


def validate_compose_config(config: dict[str, Any]) -> None:
    """Refuse privilege escalation, host access, and literal secrets."""
    for service_name, service in (config.get("services") or {}).items():
        if service.get("privileged"):
            raise ComposeRefused(f"{service_name}: privileged mode refused")
        if service.get("cap_add"):
            raise ComposeRefused(f"{service_name}: cap_add refused")
        security_opt = [str(item) for item in (service.get("security_opt") or [])]
        if service_name == "worker":
            # The worker's per-run userns sandbox needs unshare/mount, which
            # Docker's default seccomp profile forbids — `seccomp=unconfined`
            # on THIS service is the documented trade. Anything beyond that
            # one entry is refused.
            if any(item != "seccomp=unconfined" for item in security_opt):
                raise ComposeRefused(
                    f"{service_name}: only seccomp=unconfined is allowed, got {security_opt!r}"
                )
        elif security_opt:
            raise ComposeRefused(f"{service_name}: security_opt refused")
        network_mode = str(service.get("network_mode") or "")
        if network_mode.split(":")[0] == "host":
            raise ComposeRefused(f"{service_name}: host networking refused")
        for volume in service.get("volumes") or []:
            if isinstance(volume, dict):
                source = str(volume.get("source") or "")
            else:
                source = str(volume).split(":", 1)[0]
            if source.endswith("docker.sock") or "/docker.sock" in source:
                raise ComposeRefused(f"{service_name}: docker.sock mount refused")
        environment = service.get("environment") or {}
        if isinstance(environment, dict):
            items = environment.items()
        else:
            items = (entry.split("=", 1) for entry in environment if "=" in str(entry))
        for key, value in items:
            if not SECRET_ENV_KEY.search(str(key)):
                continue
            value = "" if value is None else str(value)
            if value and not ENV_REFERENCE.match(value):
                raise ComposeRefused(f"{service_name}: {key} must come from env, not a literal")
        for port in service.get("ports") or []:
            if isinstance(port, dict):
                host_ip = str(port.get("host_ip") or "")
            else:
                parts = str(port).split(":")
                host_ip = parts[0] if len(parts) >= 3 else ""
            # A published port without an explicit loopback host_ip listens
            # on every interface ("8000:8000" => 0.0.0.0). That is refused:
            # the demo must say 127.0.0.1 out loud.
            if host_ip not in LOOPBACK_BINDS:
                raise ComposeRefused(
                    f"{service_name}: published port must bind loopback, got {host_ip!r}"
                )


def _config_no_interpolate(
    project: str, env: dict[str, str], extra_files: tuple[Path, ...] = ()
) -> dict[str, Any]:
    done = _compose(project, env, "config", "--no-interpolate", extra_files=extra_files)
    assert done.returncode == 0, done.stderr
    return yaml.safe_load(done.stdout)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


@pytest.mark.timeout(1800)
def test_w7_c05_contract(compose_stack: dict[str, Any]) -> None:
    """Real ``compose up``: deps + migrate + api + worker + HTTPS gateway all pass."""
    stack = compose_stack
    states = stack["states"]
    for service in ("postgres", "api", "worker"):
        assert str(states[service].get("Health")).lower() == "healthy", states[service]
    for service in ("reposync", "migrate", "webbuild"):
        assert str(states[service].get("State")).lower() == "exited"
        assert states[service].get("ExitCode") == 0, states[service]

    # The TLS listener is real: the default trust store refuses the internal CA.
    with pytest.raises((ssl.SSLError, urllib.error.URLError, OSError)):
        _https_get(f"{stack['https_base']}/api/v1/auth/csrf", verify=True)

    # Through the proxy: the built frontend and an unauthenticated API 200.
    page = _https_get(f"{stack['https_base']}/", verify=False)
    html = page.read().decode("utf-8", "replace")
    assert page.status == 200
    assert "<html" in html.lower()
    headers = {key.lower(): value for key, value in page.headers.items()}
    assert headers.get("strict-transport-security", ""), headers
    assert headers.get("x-content-type-options") == "nosniff"

    csrf = _https_get(f"{stack['https_base']}/api/v1/auth/csrf", verify=False)
    body = json.loads(csrf.read().decode("utf-8"))
    assert csrf.status == 200
    assert body["csrf_token"]
    # An authenticated surface proves the app is past boot: 401, not 502/404.
    try:
        _https_get(f"{stack['https_base']}/api/v1/me", verify=False)
    except urllib.error.HTTPError as exc:
        denied = exc
    else:
        raise AssertionError("/api/v1/me must refuse anonymous callers")
    assert denied.code == 401
    assert json.loads(denied.read().decode("utf-8"))["code"] == "UNAUTHORIZED"

    # The compose Postgres ran the real Alembic head (migrate service).
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(stack["pg_dsn"], poolclass=NullPool)
    try:
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert revision == "004_waiting_approval", revision
            for table in ("runs", "run_events", "outbox", "users", "projects"):
                found = conn.execute(
                    text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}
                ).scalar()
                assert found and str(found).split(".")[-1] == table, table
    finally:
        engine.dispose()


def test_w7_c05_negative(tmp_path: Path) -> None:
    """Unsafe deploy shapes are refused; local mode stays a loopback fallback."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is required to render compose config")
    project = f"rxyw7c05neg-{uuid.uuid4().hex[:8]}"
    env = _stack_env(_free_port(), _free_port(), _free_port())

    # (a1) The shipped file itself passes every invariant the validator enforces.
    base = _config_no_interpolate(project, env)
    validate_compose_config(base)

    # (a2) A privilege-escalating / host-reaching / literal-secret overlay is refused.
    bad_override = tmp_path / "bad.override.yaml"
    bad_override.write_text(
        "services:\n"
        "  api:\n"
        "    privileged: true\n"
        "    network_mode: host\n"
        "    environment:\n"
        "      RXYCODE_WEB_SECRET: hardcoded-literal-secret\n"
        "    volumes:\n"
        "      - /var/run/docker.sock:/var/run/docker.sock\n",
        encoding="utf-8",
        newline="\n",
    )
    merged = _config_no_interpolate(project, env, extra_files=(bad_override,))
    assert "api" in (merged.get("services") or {})
    assert merged["services"]["api"].get("privileged") is True
    with pytest.raises(ComposeRefused):
        validate_compose_config(merged)

    # A literal secret alone (no privileged/host bits) is refused too.
    mild_override = tmp_path / "literal.override.yaml"
    mild_override.write_text(
        "services:\n  api:\n    environment:\n      RXYCODE_WEB_SECRET: hardcoded-literal-secret\n",
        encoding="utf-8",
        newline="\n",
    )
    merged_literal = _config_no_interpolate(project, env, extra_files=(mild_override,))
    assert merged_literal["services"]["api"].get("privileged") is not True
    with pytest.raises(ComposeRefused):
        validate_compose_config(merged_literal)

    # A literal PROVIDER credential is refused the same way — names like
    # RXYCODE_API_KEY carry secrets and must interpolate, never literal.
    apikey_override = tmp_path / "apikey.override.yaml"
    apikey_override.write_text(
        "services:\n  worker:\n    environment:\n"
        "      RXYCODE_API_KEY: sk-literal-private-credential\n",
        encoding="utf-8",
        newline="\n",
    )
    merged_key = _config_no_interpolate(project, env, extra_files=(apikey_override,))
    with pytest.raises(ComposeRefused):
        validate_compose_config(merged_key)

    # (a3) A published port without an explicit loopback host_ip listens on
    # every interface — `8000:8000` means 0.0.0.0 and must be refused, not
    # skipped.
    wild_override = tmp_path / "wildcard.override.yaml"
    wild_override.write_text(
        "services:\n  api:\n    ports:\n      - '8000:8000'\n",
        encoding="utf-8",
        newline="\n",
    )
    merged_wild = _config_no_interpolate(project, env, extra_files=(wild_override,))
    with pytest.raises(ComposeRefused):
        validate_compose_config(merged_wild)

    # (a3b) Kernel relaxations are scoped: `cap_add` is refused everywhere and
    # `security_opt` is refused everywhere except the worker's one allowed
    # `seccomp=unconfined` (needed for the per-run userns sandbox).
    secopt_override = tmp_path / "secopt.override.yaml"
    secopt_override.write_text(
        "services:\n  api:\n    security_opt:\n      - seccomp=unconfined\n",
        encoding="utf-8",
        newline="\n",
    )
    merged_secopt = _config_no_interpolate(project, env, extra_files=(secopt_override,))
    with pytest.raises(ComposeRefused):
        validate_compose_config(merged_secopt)

    capadd_override = tmp_path / "capadd.override.yaml"
    capadd_override.write_text(
        "services:\n  worker:\n    cap_add:\n      - SYS_ADMIN\n",
        encoding="utf-8",
        newline="\n",
    )
    merged_capadd = _config_no_interpolate(project, env, extra_files=(capadd_override,))
    with pytest.raises(ComposeRefused):
        validate_compose_config(merged_capadd)

    # (a4) Deployment wiring: the api command goes through the real serve()
    # guard (mode=local + non-loopback can never boot), the rate-limit env
    # is wired, and the worker service runs the drain — not an idle stdio
    # appserver.
    api_service = base["services"]["api"]
    api_command = " ".join(str(part) for part in api_service.get("command") or [])
    assert "from rxycode_server.main import serve" in api_command
    assert "serve(" in api_command
    api_env = api_service.get("environment") or {}
    assert "RXYCODE_WEB_RATE_LIMIT_RPM" in api_env
    worker_service = base["services"]["worker"]
    worker_command = " ".join(str(part) for part in worker_service.get("command") or [])
    assert "rxycode_worker.drain" in worker_command

    # (a5) The app-layer limiter itself refuses past the window — a real
    # ASGI drive of the shipped middleware, not a config-shape check.
    import asyncio

    from rxycode_server.api.ratelimit import RateLimitMiddleware

    async def _ok_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def _drive():
        limiter = RateLimitMiddleware(_ok_app, rpm=2)
        statuses = []
        for _ in range(3):
            sent: list[dict[str, Any]] = []

            async def _send(message, _sink=sent):
                _sink.append(message)

            scope = {"type": "http", "client": ("203.0.113.7", 5000)}
            await limiter(scope, None, _send)
            statuses.append(sent[0]["status"])
        return statuses

    statuses = asyncio.run(_drive())
    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429

    # (b) A local-mode public bind is refused by the shipped gateway itself.
    from rxycode_server.main import serve

    with pytest.raises(RuntimeError, match="loopback"):
        serve(
            mode="local",
            host="0.0.0.0",
            database_url="sqlite+pysqlite:///:memory:",
            secret=secrets.token_urlsafe(40),
            allowed_origins=["http://localhost"],
        )

    # The same serve() call on loopback is accepted (the app builds).
    app = serve(
        mode="local",
        host="127.0.0.1",
        database_url="sqlite+pysqlite:///:memory:",
        secret=secrets.token_urlsafe(40),
        allowed_origins=["http://localhost"],
    )
    assert app.state.mode == "local"


# ---------------------------------------------------------------------------
# Drain internals — the deployed worker's honest-failure semantics.
# ---------------------------------------------------------------------------


def test_w7_c05_lease_watchdog_semantics(monkeypatch) -> None:
    """A store outage must not silently kill the watchdog while the turn
    keeps running: one failed renewal retries, renewals broken past the TTL
    cancel the turn and report the lost lease, and LeaseRejected /
    cancel_requested are the intentional exits."""
    import asyncio

    import rxycode_worker.drain as drain
    from rxycode_worker import supervisor

    async def _drive() -> None:
        # (a) One transient failure, then recovery — the turn survives; the
        # watchdog must keep living instead of dying on the first error.
        calls = {"n": 0}

        def flaky(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db blip")
            return None

        monkeypatch.setattr(supervisor, "renew_lease", flaky)
        monkeypatch.setattr(drain, "run_status", lambda *_a, **_k: "running")
        turn = asyncio.ensure_future(asyncio.sleep(5.0))
        watcher = asyncio.ensure_future(
            drain._lease_watchdog(
                "db", "r1", "w1", 1, lease_ttl=4, claimed_at=time.monotonic(), turn=turn
            )
        )
        await asyncio.wait_for(watcher, timeout=15)
        assert calls["n"] >= 2
        assert not turn.cancelled()

        # (b) Renewals broken past the TTL: the lease has expired — the turn
        # is cancelled instead of running unowned, and _LeaseRenewalLost
        # (not a silent return) reports it.
        def broken(*_args, **_kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(supervisor, "renew_lease", broken)
        turn2 = asyncio.ensure_future(asyncio.sleep(60))
        with pytest.raises(drain._LeaseRenewalLost):
            await drain._lease_watchdog(
                "db", "r2", "w1", 1, lease_ttl=2, claimed_at=time.monotonic(), turn=turn2
            )
        with pytest.raises(asyncio.CancelledError):
            await turn2

        # (c) The fence itself refusing (a newer owner claimed the row) is
        # an intentional exit — LeaseRejected propagates, turn cancelled.
        def rejected(*_args, **_kwargs):
            raise supervisor.LeaseRejected("epoch moved")

        monkeypatch.setattr(supervisor, "renew_lease", rejected)
        turn3 = asyncio.ensure_future(asyncio.sleep(60))
        with pytest.raises(supervisor.LeaseRejected):
            await drain._lease_watchdog(
                "db", "r3", "w1", 1, lease_ttl=2, claimed_at=time.monotonic(), turn=turn3
            )
        with pytest.raises(asyncio.CancelledError):
            await turn3

        # (d) An explicit cancel request cancels the turn too.
        monkeypatch.setattr(supervisor, "renew_lease", lambda *_a, **_k: None)
        monkeypatch.setattr(drain, "run_status", lambda *_a, **_k: "cancel_requested")
        turn4 = asyncio.ensure_future(asyncio.sleep(60))
        with pytest.raises(drain._RunCancelled):
            await drain._lease_watchdog(
                "db", "r4", "w1", 1, lease_ttl=2, claimed_at=time.monotonic(), turn=turn4
            )
        with pytest.raises(asyncio.CancelledError):
            await turn4

        # (e) The deadline is independent: renewal broken AND the status probe
        # stalling past the TTL still cancels the turn at expiry — the audit
        # r4 probe shape (failed renewal + slow status read).
        def down(*_args, **_kwargs):
            raise RuntimeError("db down")

        def slow_status(*_args, **_kwargs):
            time.sleep(4.2)
            return "running"

        monkeypatch.setattr(supervisor, "renew_lease", down)
        monkeypatch.setattr(drain, "run_status", slow_status)
        turn5 = asyncio.ensure_future(asyncio.sleep(60))
        t0 = time.monotonic()
        with pytest.raises(drain._LeaseRenewalLost):
            await drain._lease_watchdog("db", "r5", "w1", 1, lease_ttl=5, claimed_at=t0, turn=turn5)
        elapsed = time.monotonic() - t0
        assert elapsed < 12, f"turn ran unowned for {elapsed:.1f}s past a 5s lease"
        with pytest.raises(asyncio.CancelledError):
            await turn5

    asyncio.run(_drive())


def test_w7_c05_projection_vocabulary() -> None:
    """Drained runs project protocol notifications into the reducer's
    vocabulary — assistant.final/delta with text, tool.* rows keyed by
    call_id, and waiting-for-input reaching both question and approval
    buckets. The ``notify.*`` audit rows alone never reached the UI."""
    from rxycode_worker import drain

    tool_names: dict[str, str] = {}

    rows = drain._projection_rows(
        "event/final",
        {
            "text": "the answer",
            "run_id": "r9",
            "input_tokens": 11,
            "output_tokens": 7,
        },
        tool_names,
        run_id="r9",
    )
    assert rows == [
        (
            "assistant.final",
            {
                "text": "the answer",
                "run_id": "r9",
                "input_tokens": 11,
                "output_tokens": 7,
            },
        )
    ]

    rows = drain._projection_rows("event/message_delta", {"text": "chunk"}, tool_names, run_id="r9")
    assert rows == [("assistant.delta", {"text": "chunk", "intermediate": False})]

    drain._projection_rows(
        "event/tool_begin",
        {"call_id": "c1", "tool_name": "shell"},
        tool_names,
        run_id="r9",
    )
    rows = drain._projection_rows(
        "event/tool_end",
        {"call_id": "c1", "ok": False, "summary": "exit 1"},
        tool_names,
        run_id="r9",
    )
    assert rows[0][0] == "tool.failed"
    assert rows[0][1]["call_id"] == "c1"
    assert rows[0][1]["tool"] == "shell"

    rows = drain._projection_rows(
        "event/agent_needs_input",
        {"request_id": "ap1", "preview": "approve rm -rf?"},
        tool_names,
        run_id="r9",
    )
    kinds = {kind for kind, _payload in rows}
    assert kinds == {"question.requested", "approval.requested"}
    approval = dict(rows)["approval.requested"]
    assert approval["approval_id"] == "ap1"

    rows = drain._projection_rows(
        "event/todo_updated",
        {"snapshot": {"items": [{"id": "t1", "content": "build it", "status": "in_progress"}]}},
        tool_names,
        run_id="r9",
    )
    assert rows == [
        (
            "todo.updated",
            {"todo_id": "t1", "title": "build it", "status": "in_progress"},
        )
    ]

    rows = drain._projection_rows(
        "event/plan", {"steps": ["scan", "patch"]}, tool_names, run_id="r9"
    )
    assert [kind for kind, _payload in rows] == ["plan.updated", "plan.updated"]


def test_w7_c05_projection_terminal_survives_cap() -> None:
    """Audit r3-F4: a flooded run may drop intermediate projections at the
    cap, but the terminal assistant.final row is always persisted."""
    from rxycode_worker import drain

    emitter = drain._RunEmit("sqlite+pysqlite:///:memory:", "t1", "r-cap")
    emitter.projected = drain._JOURNAL_CAP  # cap already exhausted
    import rxycode_server.events.store as store

    captured: list[tuple[str, dict[str, Any]]] = []
    original = store.append_event
    try:
        store.append_event = (
            lambda _url, **kw: captured.append(  # type: ignore[assignment]
                (str(kw.get("event_type")), dict(kw.get("payload") or {}))
            )
            or 0
        )
        emitter.project("assistant.delta", {"text": "intermediate"})
        emitter.project("assistant.final", {"text": "the answer", "run_id": "r-cap"})
    finally:
        store.append_event = original  # type: ignore[assignment]
    assert captured == [("assistant.final", {"text": "the answer", "run_id": "r-cap"})]


def test_w7_c05_execution_gate() -> None:
    """Audit r3-F1: the placement gate IS the public rule in code — the
    shipped cloud-only mode executes only tenant-bound cloud:* targets and
    refuses local:*, sandbox:*, cross-tenant and full* placements; the
    dev opt-in keeps local:* confined rather than host-free."""
    from rxycode_worker import drain

    refuse = drain._UnsupportedTarget

    # cloud-only (the shipped mode): tenant-bound cloud:* + non-full -> runs.
    assert (
        drain._execution_gate(
            "cloud:t1:w1",
            "auto_edit",
            execution_mode="cloud-only",
            tenant_id="t1",
        )
        == "auto_edit"
    )
    assert (
        drain._execution_gate(
            "cloud:t1:w1",
            "confirm_all",
            execution_mode="cloud-only",
            tenant_id="t1",
        )
        == "confirm_all"
    )
    # An unknown profile falls back to the configured default, never widened.
    assert (
        drain._execution_gate(
            "cloud:t1:w1",
            "unlisted-profile",
            execution_mode="cloud-only",
            tenant_id="t1",
        )
        is None
    )
    # Refused on the public stack: local:*, empty, sandbox:*, cross-tenant.
    for target in ("local:c05", "", "sandbox:ws", "cloud::w1", "cloud:other:w1"):
        with pytest.raises(refuse):
            drain._execution_gate(target, "auto_edit", execution_mode="cloud-only", tenant_id="t1")
    # Full authority implies unsandboxed host execution — refused even on a
    # well-formed tenant-bound cloud target.
    for profile in ("full", "full_auto"):
        with pytest.raises(refuse):
            drain._execution_gate(
                "cloud:t1:w1",
                profile,
                execution_mode="cloud-only",
                tenant_id="t1",
            )

    # sandboxed-local (dev opt-in): local:* runs CONFINED, cloud:* tenant-bound
    # runs too; cross-tenant and undeclared placements still refuse.
    assert (
        drain._execution_gate(
            "local:c05",
            "full_auto",
            execution_mode="sandboxed-local",
            tenant_id="t1",
        )
        == "full_auto"
    )
    with pytest.raises(refuse):
        drain._execution_gate(
            "cloud:other:w1",
            "auto_edit",
            execution_mode="sandboxed-local",
            tenant_id="t1",
        )
    with pytest.raises(refuse):
        drain._execution_gate(
            "bogus:x",
            "auto_edit",
            execution_mode="sandboxed-local",
            tenant_id="t1",
        )
    with pytest.raises(refuse):
        drain._execution_gate("local:x", "auto_edit", execution_mode="bogus-mode", tenant_id="t1")


def test_w7_c05_sandbox_argv_shape(tmp_path: Path) -> None:
    """The bwrap argv really confines the turn: clearenv + userns/pidns +
    die-with-parent + minimal ro root + only the run workspace writable."""
    from rxycode_runner.sandbox.userns import build_sandbox_argv

    ro_src = tmp_path / "ro-src"
    ro_src.mkdir()
    workdir = tmp_path / "run-ws"
    argv = build_sandbox_argv(
        workdir=workdir,
        argv=["python", "-m", "rxycode_worker.drain"],
        env={"RXYCODE_TURN_RUN_ID": "r9", "PYTHONPATH": "/repo"},
        ro_binds=[str(ro_src)],
    )
    joined = " ".join(argv)
    for flag in (
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ):
        assert flag in argv, flag
    sep = argv.index("--")
    assert argv[sep + 1 :] == ["python", "-m", "rxycode_worker.drain"]
    # Only the run workspace is writable; the extra ro bind is mounted ro.
    workdir_resolved = str(workdir.resolve())
    assert f"--bind {workdir_resolved} {workdir_resolved}" in joined
    ro_resolved = str(ro_src.resolve())
    assert f"--ro-bind {ro_resolved} {ro_resolved}" in joined
    assert "--tmpfs /tmp" in joined
    assert f"--chdir {workdir_resolved}" in joined
    # The env passlist is explicit — two setenv entries, nothing else.
    assert argv.count("--setenv") == 2
    # A nonexistent bind path is skipped, not mounted blindly.
    argv2 = build_sandbox_argv(
        workdir=tmp_path, argv=["true"], env={}, ro_binds=["/definitely-absent-xyz"]
    )
    assert "/definitely-absent-xyz" not in " ".join(argv2)


def test_w7_c05_tmpfs_before_workspace_bind(tmp_path: Path) -> None:
    """Audit r4-F5: the private /tmp tmpfs must mount BEFORE the workspace
    bind — otherwise a workdir under /tmp (the drain default root) is
    shadowed and --chdir fails."""
    from rxycode_runner.sandbox.userns import build_sandbox_argv

    workdir = tmp_path / "tmp" / "rxycode-runs" / "t1" / "s1"
    argv = build_sandbox_argv(workdir=workdir, argv=["true"], env={})
    tmpfs_at = argv.index("/tmp")  # operand right after --tmpfs
    assert argv[tmpfs_at - 1] == "--tmpfs"
    # tmpfs must precede EVERY bind — ro binds (the .sandboxes config source
    # lives under the same workspaces root) and the workspace bind alike.
    first_bind = min(i for i, t in enumerate(argv) if t in {"--bind", "--ro-bind"})
    assert tmpfs_at < first_bind, "tmpfs /tmp must mount before all binds"


def test_w7_c05_stale_result_rejected(tmp_path: Path) -> None:
    """Audit r4-F3: a result file names its run; a reused workspace's
    leftover result can never become this run's outcome."""
    import json as _json

    import rxycode_worker.drain as drain

    workdir = tmp_path / "ws"
    workdir.mkdir()
    (workdir / drain._TURN_RESULT).write_text(
        _json.dumps({"status": "succeeded", "tokens": 73, "error": "", "run_id": "old-run"}) + "\n",
        encoding="utf-8",
    )
    row = drain._read_turn_result(workdir)
    assert str(row.get("run_id") or "") == "old-run"
    # The parent's acceptance gate compares run_id — simulate it:
    assert str(row.get("run_id") or "") != "new-run"


def test_w7_c05_child_config_outside_workspace(tmp_path: Path, monkeypatch) -> None:
    """Audit r4-F2: the child's config home lives under the drain state
    root, NOT inside the child-writable workspace — a confined turn cannot
    plant a symlinked config.yaml for the parent to overwrite next run."""
    import rxycode_worker.drain as drain

    monkeypatch.setenv("RXYCODE_DATA_DIR", "")
    state = tmp_path / ".sandboxes"
    conf = drain._prepare_child_data_dir(state / "sb1-conf")
    assert conf.parent == state
    assert conf.name == "sb1-conf"


def test_w7_c05_usage_delta_reader(monkeypatch) -> None:
    """Audit r5-F4: killed turns keep spend via cumulative usage.delta rows,
    summed PER ATTEMPT — a retried run's fresh baseline must not discard the
    earlier attempt's recorded usage."""
    import rxycode_worker.drain as drain

    seen = {}

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _stmt, params):
            seen["run_id"] = params["id"]

            class _R:
                def all(self):
                    # seq-ordered heartbeats: attempt "1" peaked at 100,
                    # retry "2" only measured 5 — the durable total is 105.
                    return [
                        (1, {"input_tokens": 60, "output_tokens": 40, "attempt": "1"}),
                        (2, {"input_tokens": 70, "output_tokens": 30, "attempt": "1"}),
                        (3, {"input_tokens": 3, "output_tokens": 2, "attempt": "2"}),
                    ]

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    deltas = drain._usage_deltas_by_attempt("db", "run-42")
    assert deltas == {"1": 100, "2": 5}
    assert seen["run_id"] == "run-42"


def test_w7_c05_agent_done_grouped_by_attempt(monkeypatch) -> None:
    """Audit r7: a prior attempt's agent_done meter is tagged with its epoch
    and grouped per attempt — it can never be re-charged inside a retry's
    bucket."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _stmt, params):
            class _R:
                def all(self):
                    return [
                        (1, {"tokens": 100, "attempt": "1"}),
                        (2, {"tokens": 5, "attempt": "2"}),
                    ]

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    dones, _amb = drain._agent_done_by_attempt("db", "run-42")
    assert dones == {"1": 100, "2": 5}


def test_w7_c05_untagged_rows_anchor_to_lease_epoch(monkeypatch) -> None:
    """Audit r8: rows journaled before attempt-tagging carry no ``attempt``
    key — they must be attributed to the lease epoch active at their seq,
    not an empty bucket that would double-charge a tagged heartbeat."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)

            class _R:
                def all(self):
                    if "worker.lease" in sql:
                        return [
                            (1, {"worker_id": "w", "epoch": 1}),
                            (20, {"worker_id": "w", "epoch": 2}),
                        ]
                    if "event/agent_done" in sql:
                        # Untagged legacy done from epoch 1; tagged done in 2.
                        return [(10, {"tokens": 100}), (25, {"tokens": 5, "attempt": "2"})]
                    if "usage.delta" in sql:
                        return [(5, {"input_tokens": 100, "output_tokens": 0, "attempt": "1"})]
                    return []

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    dones, _amb = drain._agent_done_by_attempt("db", "run-42")
    # The untagged 100-token done anchors to epoch 1 (seq 10 > lease seq 1,
    # < lease seq 20); the tagged 5-token done stays in epoch 2.
    assert dones == {"1": 100, "2": 5}
    deltas = drain._usage_deltas_by_attempt("db", "run-42")
    assert deltas == {"1": 100}
    # max within attempt, sum across: (max(100,100)=100) + 5 = 105.
    per_attempt = {a: max(deltas.get(a, 0), dones.get(a, 0)) for a in set(deltas) | set(dones)}
    assert sum(per_attempt.values()) == 105


def test_w7_c05_interleaved_untagged_done_binds_earliest_open_epoch(
    monkeypatch,
) -> None:
    """Audit r9 counterexample: epoch-1 writes a TAGGED 100-token delta,
    epoch 2 is claimed, THEN epoch 1's delayed untagged agent_done(100)
    commits. Anchoring by seq would charge it to epoch 2 (200 total); the
    earliest-open-epoch rule keeps it in epoch 1 → 105."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)

            class _R:
                def all(self):
                    if "worker.lease" in sql:
                        return [
                            (1, {"worker_id": "w", "epoch": 1}),
                            (20, {"worker_id": "w", "epoch": 2}),
                        ]
                    if "event/agent_done" in sql:
                        # Untagged done committed AFTER epoch 2's claim.
                        return [(25, {"tokens": 100})]
                    if "usage.delta" in sql:
                        return [
                            (5, {"input_tokens": 100, "output_tokens": 0, "attempt": "1"}),
                            (30, {"input_tokens": 5, "output_tokens": 0, "attempt": "2"}),
                        ]
                    return []

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    dones, _amb = drain._agent_done_by_attempt("db", "run-42")
    assert dones == {"1": 100}  # epoch 2 stays open — no misattributed done
    deltas = drain._usage_deltas_by_attempt("db", "run-42")
    per_attempt = {a: max(deltas.get(a, 0), dones.get(a, 0)) for a in set(deltas) | set(dones)}
    assert sum(per_attempt.values()) == 105


def test_w7_c05_untagged_delta_prefers_value_compatible_epoch(monkeypatch) -> None:
    """Audit r9: an untagged cumulative delta committing after a newer
    claim joins the attempt it continues (largest bucket <= value), not the
    newest epoch — biased to under-count, never double-charge."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)

            class _R:
                def all(self):
                    if "worker.lease" in sql:
                        return [
                            (1, {"worker_id": "w", "epoch": 1}),
                            (20, {"worker_id": "w", "epoch": 2}),
                        ]
                    if "usage.delta" in sql:
                        return [
                            (5, {"input_tokens": 100, "output_tokens": 0, "attempt": "1"}),
                            (30, {"input_tokens": 5, "output_tokens": 0, "attempt": "2"}),
                            # delayed untagged epoch-1 snapshot == its tagged value
                            (35, {"input_tokens": 100, "output_tokens": 0}),
                        ]
                    return []

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    deltas = drain._usage_deltas_by_attempt("db", "run-42")
    assert deltas == {"1": 100, "2": 5}


def test_w7_c05_streamed_flush_spools_on_outage(tmp_path, monkeypatch) -> None:
    """Audit r8: a flush that cannot reach the DB retries, then spools the
    metering to parent-owned disk; the next drain pass replays it."""
    import rxycode_worker.drain as drain
    import rxycode_server.events.store as store

    calls = []

    def fail_append(*_a, **_k):
        calls.append(1)
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "append_event", fail_append)
    streamed = {"tokens": 73, "input_tokens": 40, "output_tokens": 33}
    assert not drain._flush_streamed_usage("db", "t1", "r7", 3, streamed, deltas={})

    spool_dir = drain._usage_spool_dir(str(tmp_path))
    drain._spool_streamed_usage(
        spool_dir,
        tenant_id="t1",
        run_id="r7",
        epoch=3,
        input_tokens=40,
        output_tokens=33,
    )
    files = list(spool_dir.glob("*.usage.json"))
    assert len(files) == 1

    # Replay still fails while the DB is down — the file is retained.
    drain._replay_usage_spool("db", str(tmp_path))
    assert files[0].exists()

    # DB recovers: replay journals the row, reconciles the (absent) ledger,
    # and removes the spool file.
    written = []

    def ok_append(_dsn, *, tenant_id, run_id, event_type, payload):
        written.append((tenant_id, run_id, event_type, dict(payload)))
        return 1

    monkeypatch.setattr(store, "append_event", ok_append)
    monkeypatch.setattr(drain, "_usage_deltas_by_attempt", lambda *_a: {"3": 73})
    monkeypatch.setattr(drain, "_agent_done_by_attempt", lambda *_a: ({}, []))
    import rxycode_server.usage.service as usage_service

    adjusted = []
    monkeypatch.setattr(
        usage_service,
        "adjust_terminal_usage",
        lambda _dsn, *, tenant_id, run_id, tokens, event_id, attribution=None: adjusted.append(
            (tenant_id, run_id, tokens)
        )
        or {"tokens": tokens},
    )
    drain._replay_usage_spool("db", str(tmp_path))
    assert not files[0].exists()
    assert written == [
        (
            "t1",
            "r7",
            "usage.delta",
            {
                "input_tokens": 40,
                "output_tokens": 33,
                "cumulative": True,
                "attempt": "3",
                "final": True,
                "spooled": True,
            },
        )
    ]
    # Audit r9: a committed-but-short ledger is reconciled to the recovered
    # total instead of staying at the retry's partial amount.
    assert adjusted == [("t1", "r7", 73)]

    # A failed reconcile keeps the spool so the next pass retries.
    drain._spool_streamed_usage(
        spool_dir,
        tenant_id="t1",
        run_id="r7",
        epoch=3,
        input_tokens=40,
        output_tokens=33,
    )
    files = list(spool_dir.glob("*.usage.json"))

    def fail_adjust(*_a, **_k):
        raise RuntimeError("ledger locked")

    monkeypatch.setattr(usage_service, "adjust_terminal_usage", fail_adjust)
    drain._replay_usage_spool("db", str(tmp_path))
    assert files[0].exists()  # durable-spend file survives a failed reconcile


def test_w7_c05_streamed_flush_writes_delta(monkeypatch) -> None:
    """Audit r7: stderr-delivered spend that never reached a heartbeat is
    flushed as a final usage.delta row for THIS attempt — even when the
    worker lost the lease and must not write terminal state."""
    import rxycode_worker.drain as drain

    written = []

    def fake_append(_dsn, *, tenant_id, run_id, event_type, payload):
        written.append((event_type, dict(payload)))
        return 1

    import rxycode_server.events.store as store

    monkeypatch.setattr(store, "append_event", fake_append)
    streamed = {"tokens": 73, "input_tokens": 40, "output_tokens": 33}
    drain._flush_streamed_usage("db", "t1", "r7", 3, streamed, deltas={"3": 20})
    assert written == [
        (
            "usage.delta",
            {
                "input_tokens": 40,
                "output_tokens": 33,
                "cumulative": True,
                "attempt": "3",
                "final": True,
            },
        )
    ]
    # Nothing beyond the attempt's recorded cumulative => no duplicate row.
    written.clear()
    drain._flush_streamed_usage("db", "t1", "r7", 3, {"tokens": 73}, deltas={"3": 80})
    assert written == []


def test_w7_c05_untagged_done_exact_metered_match(monkeypatch) -> None:
    """Audit r10 counterexample: epoch 1 spends 5 and crashes WITHOUT a
    done; epoch 2 spends 100 and emits the run's only (untagged, legacy)
    done. Earliest-open-epoch attribution would charge it to epoch 1 →
    200; exact metered-bucket matching binds it to epoch 2 → 105."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)

            class _R:
                def all(self):
                    if "worker.lease" in sql:
                        return [
                            (1, {"worker_id": "w", "epoch": 1}),
                            (20, {"worker_id": "w", "epoch": 2}),
                        ]
                    if "event/agent_done" in sql:
                        # Untagged — epoch 2's own legacy completion.
                        return [(25, {"tokens": 100})]
                    if "usage.delta" in sql:
                        return [
                            (5, {"input_tokens": 5, "output_tokens": 0, "attempt": "1"}),
                            (22, {"input_tokens": 100, "output_tokens": 0, "attempt": "2"}),
                        ]
                    return []

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    dones, _amb = drain._agent_done_by_attempt("db", "run-42")
    assert dones == {"2": 100}  # NOT {"1": 100} — value pins it to epoch 2
    deltas = drain._usage_deltas_by_attempt("db", "run-42")
    per_attempt = {
        a: max(deltas.get(a, 0), dones.get(a, 0))
        for a in set(deltas) | set(dones)
    }
    assert sum(per_attempt.values()) == 105


def test_w7_c05_adjust_terminal_usage_multi_row(postgres_url: str) -> None:
    """Audit r10: a run may hold several (model, price) UsageRecord rows —
    reconciliation must raise the total across rows, not overwrite one row
    with the whole-run total (60+60 → 130 becomes 70+60, never 130+60)."""
    import rxycode_worker.drain as drain  # noqa: F401  (sys.path bootstrap)
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import (
        Organization,
        Project,
        Run,
        SessionRow,
        UsageRecord,
        User,
    )
    from rxycode_server.usage.service import adjust_terminal_usage

    upgrade_head(postgres_url)
    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(User(id=f"u-{tenant}", github_id=None, kind="local"))
            db.add(Organization(id=f"o-{tenant}", tenant_id=tenant))
            db.add(Project(id=f"p-{tenant}", tenant_id=tenant, name="t", repo_config={}))
            db.add(SessionRow(id=f"s-{tenant}", tenant_id=tenant, project_id=f"p-{tenant}", title="t"))
            db.add(Run(id="run-multi", tenant_id=tenant, session_id=f"s-{tenant}", status="succeeded", request_id="r1"))
            db.add(Run(id="run-single", tenant_id=tenant, session_id=f"s-{tenant}", status="succeeded", request_id="r2"))
            db.add(UsageRecord(id="ur-a", run_id="run-multi", model_id="m-a", price_version="2026-10", tokens=60))
            db.add(UsageRecord(id="ur-b", run_id="run-multi", model_id="m-b", price_version="2026-10", tokens=60))
            db.add(UsageRecord(id="ur-c", run_id="run-single", model_id="m-a", price_version="2026-10", tokens=5))
            db.commit()

        # Multi-row: recovered total 130 → largest row absorbs 130-60=70.
        out = adjust_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-multi",
            tokens=130, event_id="evt-adj-1",
        )
        assert out is not None
        with Session(engine) as db:
            rows = db.scalars(
                select(UsageRecord).where(UsageRecord.run_id == "run-multi")
            ).all()
            total = sum(int(r.tokens) for r in rows)
        assert total == 130
        # Single-row short ledger → raised to recovered total.
        out2 = adjust_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-single",
            tokens=78, event_id="evt-adj-2",
        )
        assert out2 is not None and int(out2["tokens"]) == 78
        # No ledger at all → None (caller's spool file stays for next pass).
        with Session(engine) as db:
            db.add(Run(id="run-none", tenant_id=tenant, session_id=f"s-{tenant}", status="failed", request_id="r3"))
            db.commit()
        assert adjust_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-none",
            tokens=50, event_id="evt-adj-3",
        ) is None
    finally:
        engine.dispose()


def test_w7_c05_untagged_done_lagging_heartbeat_match(monkeypatch) -> None:
    """Audit r11 counterexample: heartbeats lag the true total. e1 spends
    5 and dies silently; e2's last heartbeat reports 90 but its real total
    is 100, delivered as the run's only untagged done. No bucket EQUALS
    100 — the min-surplus rule must still bind e2 (->105), not the
    done-less e1 (->190)."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)

            class _R:
                def all(self):
                    if "worker.lease" in sql:
                        return [
                            (1, {"worker_id": "w", "epoch": 1}),
                            (20, {"worker_id": "w", "epoch": 2}),
                        ]
                    if "event/agent_done" in sql:
                        return [(25, {"tokens": 100})]
                    if "usage.delta" in sql:
                        return [
                            (5, {"input_tokens": 5, "output_tokens": 0, "attempt": "1"}),
                            (22, {"input_tokens": 90, "output_tokens": 0, "attempt": "2"}),
                        ]
                    return []

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    dones, _amb = drain._agent_done_by_attempt("db", "run-43")
    assert dones == {"2": 100}  # lagged meter still pins e2 — not e1
    deltas = drain._usage_deltas_by_attempt("db", "run-43")
    per_attempt = {
        a: max(deltas.get(a, 0), dones.get(a, 0))
        for a in set(deltas) | set(dones)
    }
    assert sum(per_attempt.values()) == 105


def test_w7_c05_ambiguous_done_journaled_as_uncertain(monkeypatch) -> None:
    """Audit r12: when two epochs are both feasible owners of an untagged
    done (e1 metered 5 dead, e2 metered 90, done 100), the binding is a
    heuristic — the ambiguity must be journaled explicitly, not hidden
    behind an inferred confirmed total."""
    import rxycode_worker.drain as drain

    written: list[dict] = []

    class _FakeEngine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            sql = str(stmt)

            class _R:
                def all(self):
                    if "worker.lease" in sql:
                        return [
                            (1, {"worker_id": "w", "epoch": 1}),
                            (20, {"worker_id": "w", "epoch": 2}),
                        ]
                    if "event/agent_done" in sql:
                        return [(25, {"tokens": 100})]
                    if "usage.delta" in sql:
                        return [
                            (5, {"input_tokens": 5, "output_tokens": 0, "attempt": "1"}),
                            (22, {"input_tokens": 90, "output_tokens": 0, "attempt": "2"}),
                        ]
                    if "usage.attribution" in sql:
                        return [
                            (w["payload"],)
                            for w in written
                            if w["event_type"] == "usage.attribution"
                        ]
                    return []

            return _R()

        def dispose(self):
            pass

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_a, **_k: _FakeEngine())
    dones, ambiguities = drain._agent_done_by_attempt("db", "run-44")
    assert dones == {"2": 100}
    assert len(ambiguities) == 1
    note = ambiguities[0]
    assert note["seq"] == 25 and note["chosen"] == "2"
    assert note["candidates"] == {"1": 5, "2": 90}

    # The ambiguity note is journaled exactly once across replays.
    monkeypatch.setattr(
        "rxycode_server.events.store.append_event",
        lambda _db, **kw: written.append(kw) or 1,
    )
    drain._emit_attribution_events("db", "t1", "run-44", ambiguities)
    assert [w["event_type"] for w in written] == ["usage.attribution"]
    assert written[0]["payload"]["ambiguous"] is True
    assert written[0]["payload"]["attribution_seq"] == 25
    drain._emit_attribution_events("db", "t1", "run-44", ambiguities)
    assert len(written) == 1  # dedupe — the note is not re-journaled


def test_w7_c05_short_existing_ledger_reconciled_on_finalize(
    monkeypatch, postgres_url: str
) -> None:
    """Audit r12 F1: attempt A's ledger (100) committed before its crash;
    retry B recomputes 105 and record_terminal_usage returns the existing
    row unchanged (insert-once is the W2-C07 contract). The finalize path
    must then adjust_terminal_usage up to 105."""
    import rxycode_worker.drain as drain  # noqa: F401
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import (
        Organization,
        Project,
        Run,
        SessionRow,
        UsageRecord,
        User,
    )
    from rxycode_server.usage.service import (
        record_terminal_usage,
        upsert_terminal_usage,
    )

    upgrade_head(postgres_url)
    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(User(id=f"u-{tenant}", github_id=None, kind="local"))
            db.add(Organization(id=f"o-{tenant}", tenant_id=tenant))
            db.add(Project(id=f"p-{tenant}", tenant_id=tenant, name="t", repo_config={}))
            db.add(SessionRow(id=f"s2-{tenant}", tenant_id=tenant, project_id=f"p-{tenant}", title="t"))
            db.add(SessionRow(id=f"s3-{tenant}", tenant_id=tenant, project_id=f"p-{tenant}", title="t"))
            db.add(Run(id="run-short", tenant_id=tenant, session_id=f"s2-{tenant}", status="running", request_id="r9"))
            db.commit()

        # Attempt A's committed ledger (then it crashed before terminal).
        record_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-short",
            model_id="model-a", price_version="2026-10",
            tokens=100, event_id="evt-a",
        )
        # API replay semantics stay insert-once (W2-C07 contract).
        inflated = record_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-short",
            model_id="model-a", price_version="2026-10",
            tokens=99999, event_id="evt-b",
        )
        assert int(inflated["tokens"]) == 100
        # The drain finalize path uses upsert_terminal_usage: retry B
        # recomputes 105 and the aggregate lifts to it.
        out = upsert_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-short",
            model_id="model-a", price_version="2026-10",
            tokens=105, event_id="evt-reconcile",
        )
        assert int(out["tokens"]) == 105
        with Session(engine) as db:
            total = db.scalar(
                select(func.sum(UsageRecord.tokens)).where(
                    UsageRecord.run_id == "run-short"
                )
            )
        assert int(total) == 105
        # A different-model prior row can't inflate the run total either —
        # the upsert reconciles the aggregate, it does not add a second row.
        with Session(engine) as db:
            db.add(Run(id="run-mixed", tenant_id=tenant, session_id=f"s3-{tenant}", status="running", request_id="r10"))
            db.add(UsageRecord(id="ur-x", run_id="run-mixed", model_id="model-x", price_version="2026-10", tokens=100))
            db.commit()
        out2 = upsert_terminal_usage(
            postgres_url, tenant_id=tenant, run_id="run-mixed",
            model_id="model-a", price_version="2026-10",
            tokens=105, event_id="evt-mixed",
        )
        assert int(out2["tokens"]) == 105
        with Session(engine) as db:
            rows = db.scalars(
                select(UsageRecord).where(UsageRecord.run_id == "run-mixed")
            ).all()
        assert len(rows) == 1 and int(rows[0].tokens) == 105
    finally:
        engine.dispose()


def test_w7_c05_prior_activity_detected_on_cancel_claim(monkeypatch) -> None:
    """Audit r13 F1: a re-claimed run cancelled before this worker ran still
    had a prior attempt spend tokens — 'nothing ran' must not erase that.
    `_has_prior_attempt_activity` sees prior metering/lease rows."""
    import rxycode_worker.drain as drain

    class _FakeEngine:
        def __init__(self, n):
            self.n = n

        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, params):
            n = self.n

            class _R:
                def scalar(self):
                    return n

            return _R()

        def dispose(self):
            pass

    import sqlalchemy

    monkeypatch.setattr(
        sqlalchemy, "create_engine", lambda *_a, **_k: _FakeEngine(2)
    )
    assert drain._has_prior_attempt_activity("db", "r1", 2) is True
    monkeypatch.setattr(
        sqlalchemy, "create_engine", lambda *_a, **_k: _FakeEngine(0)
    )
    assert drain._has_prior_attempt_activity("db", "r1", 2) is False


def test_w7_c05_lost_lease_reconciles_committed_ledger(monkeypatch) -> None:
    """Audit r13 F3: our flush journaled a usage.delta successfully (no
    spool), but a retry already committed a smaller ledger — the lost-lease
    handoff must reconcile the committed row up to the recovered total."""
    import rxycode_worker.drain as drain

    monkeypatch.setattr(
        drain, "_usage_deltas_by_attempt", lambda *_a: {"1": 100, "2": 5}
    )
    monkeypatch.setattr(drain, "_agent_done_by_attempt", lambda *_a: ({}, []))
    seen = []
    monkeypatch.setattr(
        "rxycode_server.usage.service.adjust_terminal_usage",
        lambda _d, *, tenant_id, run_id, tokens, event_id, attribution=None: seen.append(
            tokens
        )
        or {"tokens": tokens},
    )
    drain._reconcile_lost_lease_ledger(
        "db", "t1", "r9", "2", {"tokens": 5}, {"1": 100, "2": 5}
    )
    assert seen == [105]
    # Zero total -> no reconcile call at all.
    seen.clear()
    monkeypatch.setattr(drain, "_usage_deltas_by_attempt", lambda *_a: {})
    drain._reconcile_lost_lease_ledger("db", "t1", "r9", "2", {"tokens": 0}, {})
    assert seen == []
