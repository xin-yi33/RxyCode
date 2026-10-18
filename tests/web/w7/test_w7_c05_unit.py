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
SECRET_ENV_KEY = re.compile(r"(?i)(password|secret|token)")
ENV_REFERENCE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::[-?][^}]*)?\}$")
LOOPBACK_BINDS = {"", "127.0.0.1", "::1", "localhost"}


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
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=900,
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
    up = _compose(project, env, "up", "-d", "--remove-orphans")
    try:
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
            if host_ip and host_ip not in LOOPBACK_BINDS:
                raise ComposeRefused(
                    f"{service_name}: published port must bind loopback, got {host_ip}"
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
