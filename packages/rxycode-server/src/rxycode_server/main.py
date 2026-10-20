"""Web FastAPI gateway. The legacy Ink app in api_server stays a loopback fallback."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from rxycode_server.api.approvals import router as approvals_router
from rxycode_server.api.artifacts import router as artifacts_router
from rxycode_server.api.auth import AuthRateLimit, router as auth_router
from rxycode_server.api.projects import router as projects_router
from rxycode_server.api.runs import router as runs_router
from rxycode_server.api.sse import router as sse_router
from rxycode_server.api.terminal_ws import router as terminal_router
from rxycode_server.api.version import router as version_router
from rxycode_server.api.workspace import router as workspace_router
from rxycode_server.devices.gateway import Registry, build_router
from rxycode_server.notifications.service import router as product_router
from rxycode_server.previews.proxy import PreviewProxy
from rxycode_server.previews.proxy import build_router as preview_router

_PLACEHOLDERS = ("replace-with", "change-me", "changeme", "example-token", "example-secret")


async def _fire_due_schedules(app: FastAPI, stop: asyncio.Event) -> None:
    """Fire due web schedules from the database. This process is not appserver."""
    from rxycode_server.notifications.service import fire_due_schedules

    while not stop.is_set():
        try:
            fire_due_schedules(app.state.database_url, now=datetime.now(timezone.utc))
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass


def _require_secret(secret: str) -> str:
    value = (secret or "").strip()
    folded = value.casefold()
    if len(value) < 32 or len(set(value)) < 10 or any(marker in folded for marker in _PLACEHOLDERS):
        raise RuntimeError("web gateway requires a local random secret")
    return value


def create_app(
    database_url: str,
    *,
    mode: str,
    secret: str,
    allowed_origins: list[str],
    github_client_id: str = "",
    github_client_secret: str = "",
    github_redirect_uri: str = "",
    github_transport: object | None = None,
    s3_endpoint: str = "",
    s3_bucket: str = "",
    s3_access_key: str = "",
    s3_secret_key: str = "",
    rate_limit_rpm: int = 0,
) -> FastAPI:
    """Build the cloud or local gateway. It does not mount the legacy /chat app.

    ``rate_limit_rpm`` installs the per-client-IP fixed-window limiter
    (``api.ratelimit.RateLimitMiddleware``); 0 disables it. The deployed
    compose stack enables it via ``RXYCODE_WEB_RATE_LIMIT_RPM`` so the public
    demo is throttled at the app layer (stock Caddy has no limiter plugin).
    """
    checked = _require_secret(secret)
    if mode not in {"local", "cloud"}:
        raise RuntimeError("mode must be local or cloud")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        ticker = asyncio.create_task(_fire_due_schedules(app, stop))
        try:
            yield
        finally:
            stop.set()
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
            app.state.engine.dispose()

    app = FastAPI(title="RxyCode Web", version="1.4.3", lifespan=lifespan)
    app.state.engine = create_engine(database_url, poolclass=NullPool)
    app.state.database_url = database_url
    try:
        from rxycode_worker.agent_events import publish_database_url
    except ImportError:
        publish_database_url = None
    if publish_database_url is not None:
        publish_database_url(database_url)
    app.state.secret = checked
    app.state.mode = mode
    app.state.secure = mode == "cloud"
    # W10-D1: /api/v1/version falls back to process start when the image
    # build did not stamp RXYCODE_BUILD_TIME.
    app.state.built_at = datetime.now(timezone.utc).isoformat()
    app.state.allowed_origins = tuple(allowed_origins)
    # WEB-W9-B1: browser sessions live in the auth_sessions table — no
    # per-process dicts, so restarts and replicas keep cookies valid.
    registration = os.environ.get("RXYCODE_WEB_REGISTRATION", "invite").strip().lower()
    app.state.registration = (
        registration if registration in ("invite", "open", "closed") else "invite"
    )
    app.state.auth_rate = AuthRateLimit()
    app.state.github_client_id = github_client_id
    app.state.github_client_secret = github_client_secret
    app.state.github_redirect_uri = github_redirect_uri
    app.state.github_transport = github_transport
    app.state.s3_endpoint = s3_endpoint or None
    app.state.s3_bucket = s3_bucket or None
    app.state.s3_access_key = s3_access_key or None
    app.state.s3_secret_key = s3_secret_key or None
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(runs_router)
    app.include_router(workspace_router)
    app.include_router(terminal_router)
    app.include_router(sse_router)
    app.include_router(approvals_router)
    app.include_router(artifacts_router)
    app.include_router(version_router)
    app.include_router(product_router)
    app.state.device_registry = Registry(clock=time.time, pairing_ttl=300.0, ttl=30.0)
    app.include_router(build_router())
    app.state.preview_proxy = PreviewProxy()
    app.include_router(preview_router())
    app.state.rate_limit_rpm = int(rate_limit_rpm or 0)
    if app.state.rate_limit_rpm > 0:
        from rxycode_server.api.ratelimit import RateLimitMiddleware

        app.add_middleware(RateLimitMiddleware, rpm=app.state.rate_limit_rpm)

    # WEB-W9-B4: env-gated admission gate. When none of the knobs is set the
    # package default (no installed gate, DEFAULT_LIMITS) is untouched.
    _install_quota_gate_from_env()

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) else "FORBIDDEN"
        return JSONResponse(status_code=exc.status_code, content={"code": code})

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"code": "INVALID_INPUT"})

    return app


def _install_quota_gate_from_env() -> None:
    """WEB-W9-B4: install the admission gate iff any quota env var exists."""
    concurrency = os.environ.get("RXYCODE_QUOTA_CONCURRENCY", "").strip()
    tasks = os.environ.get("RXYCODE_QUOTA_TASKS_PER_DAY", "").strip()
    tokens = os.environ.get("RXYCODE_QUOTA_TOKENS_PER_DAY", "").strip()
    queue = os.environ.get("RXYCODE_QUEUE_MAX", "").strip()
    if not (concurrency or tasks or tokens or queue):
        return
    from rxycode_server.quotas.service import (
        DEFAULT_LIMITS,
        Limits,
        QuotaGate,
        RunWorkers,
        install_gate,
    )

    limits = Limits(
        tasks=int(tasks) if tasks else DEFAULT_LIMITS.tasks,
        tokens=int(tokens) if tokens else DEFAULT_LIMITS.tokens,
        concurrency=int(concurrency) if concurrency else DEFAULT_LIMITS.concurrency,
        preview_fee=DEFAULT_LIMITS.preview_fee,
        sandbox_fee=DEFAULT_LIMITS.sandbox_fee,
        window_seconds=86400,
        queue_max=int(queue) if queue else None,
    )
    install_gate(QuotaGate(limits=limits, capacity=RunWorkers()))


def serve(
    *,
    mode: str,
    host: str,
    database_url: str,
    secret: str,
    allowed_origins: list[str],
    port: int = 8766,
    **kwargs: object,
) -> FastAPI:
    """Return the web app. Local mode refuses any non-loopback bind of this gateway."""
    del port
    if mode == "local":
        from RxyCode.RxyCode1_1_0.api_server import reject_as_public_web_gateway

        reject_as_public_web_gateway(host)
    return create_app(
        database_url,
        mode=mode,
        secret=secret,
        allowed_origins=allowed_origins,
        **kwargs,
    )
