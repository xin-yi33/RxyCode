"""Shared PostgreSQL test container helpers.

``--dist loadscope`` keeps one module per pytest-xdist worker, so sibling
workers that share one ``public`` schema drop it out from under each other.
``worker_url`` gives every worker its own ``<db>_<worker>`` database in the
shared container; ``ensure_container`` reuses the container when healthy and
starts it when missing.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

from sqlalchemy import create_engine, text


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def external_url() -> str | None:
    """``RXYCODE_PGURL`` points tests at a postgres the harness doesn't own
    (e.g. a disposable container on a LAN host when Docker is unavailable).
    Unset in CI — docker path is unchanged there."""
    url = os.environ.get("RXYCODE_PGURL", "").strip()
    return url or None


def ensure_container(container: str, port: int) -> None:
    if external_url():
        return
    ready = docker("exec", container, "pg_isready", "-U", "postgres", "-d", "rxycode")
    if ready.returncode == 0:
        return
    exists = docker("inspect", container)
    if exists.returncode == 0:
        started = docker("start", container)
        assert started.returncode == 0, started.stderr
    else:
        started = docker(
            "run",
            "-d",
            "--name",
            container,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=rxycode",
            "-p",
            f"127.0.0.1:{port}:5432",
            "postgres:16",
        )
        assert started.returncode == 0, started.stderr
    deadline = time.time() + 60
    while time.time() < deadline:
        probe = docker("exec", container, "pg_isready", "-U", "postgres", "-d", "rxycode")
        if probe.returncode == 0:
            # pg_isready clears while the postmaster can still die in its
            # init window (observed on loaded CI runners: isready passed,
            # then the connection was refused seconds later). Require a
            # REAL connection before declaring ready.
            try:
                engine = create_engine(
                    f"postgresql+psycopg://postgres@127.0.0.1:{port}/rxycode",
                    pool_pre_ping=True,
                )
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                engine.dispose()
                return
            except Exception:
                pass
        time.sleep(1)
    logs = docker("logs", container)
    raise RuntimeError(logs.stderr or logs.stdout or "postgres did not become ready")


def worker_dbname() -> str:
    worker = re.sub(
        r"[^A-Za-z0-9_]", "_", os.environ.get("PYTEST_XDIST_WORKER") or "main"
    )
    return "rxycode" if worker == "main" else f"rxycode_{worker}"


def worker_url(server_url: str) -> str:
    """Return ``server_url`` with the per-worker database created and swapped in."""
    external = external_url()
    if external:
        server_url = external
    dbname = worker_dbname()
    base, sep, _ = server_url.rpartition("/")
    if not sep:
        return server_url
    if dbname == "rxycode":
        return server_url
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": dbname},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()
    return f"{base}/{dbname}"


def bun_path() -> str | None:
    """Locate Bun on PATH or the default install dir — mirrors main._bun_executable."""
    import shutil
    from pathlib import Path

    found = shutil.which("bun")
    if found:
        return found
    home = Path.home()
    bun_install = (os.environ.get("BUN_INSTALL") or "").strip()
    candidates: list[Path] = []
    if bun_install:
        candidates += [
            Path(bun_install) / "bin" / "bun",
            Path(bun_install) / "bin" / "bun.exe",
        ]
    candidates += [home / ".bun" / "bin" / "bun", home / ".bun" / "bin" / "bun.exe"]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None
