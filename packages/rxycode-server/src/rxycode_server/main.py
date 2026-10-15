"""Web FastAPI gateway. The legacy Ink app in api_server stays a loopback fallback."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import router as auth_router
from rxycode_server.api.projects import router as projects_router

_PLACEHOLDERS = ("replace-with", "change-me", "changeme", "example-token", "example-secret")


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
) -> FastAPI:
    """Build the cloud or local gateway. It does not mount the legacy /chat app."""
    checked = _require_secret(secret)
    if mode not in {"local", "cloud"}:
        raise RuntimeError("mode must be local or cloud")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.engine.dispose()

    app = FastAPI(title="RxyCode Web", version="1.4.3", lifespan=lifespan)
    app.state.engine = create_engine(database_url, poolclass=NullPool)
    app.state.secret = checked
    app.state.mode = mode
    app.state.secure = mode == "cloud"
    app.state.allowed_origins = tuple(allowed_origins)
    app.state.sessions = {}
    app.state.oauth_states = {}
    app.state.github_client_id = github_client_id
    app.state.github_client_secret = github_client_secret
    app.state.github_redirect_uri = github_redirect_uri
    app.state.github_transport = github_transport
    app.include_router(auth_router)
    app.include_router(projects_router)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) else "FORBIDDEN"
        return JSONResponse(status_code=exc.status_code, content={"code": code})

    return app


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
