"""Owner-authenticated preview proxy. It only reads a registered sandbox port."""

from __future__ import annotations

import ipaddress
import subprocess
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from rxycode_runner.sandbox.gvisor import GVisorSandbox, docker_executable
from rxycode_runner.sandbox.provider import AttachRefused

_CSP = "default-src 'none'; frame-ancestors 'none'"
_METADATA = {"169.254.169.254", "metadata.google.internal"}


class PreviewRefused(PermissionError):
    """The caller, tenant, port, or URL is not allowed to preview."""


class TargetUnavailable(RuntimeError):
    def __init__(self, target: str) -> None:
        self.target = target
        super().__init__(f"target unavailable: {target}")


@dataclass(frozen=True)
class PreviewGrant:
    grant_id: str
    proxy_path: str
    sandbox_id: str
    port: int
    tenant_id: str
    owner_id: str


@dataclass(frozen=True)
class PreviewPage:
    body: str
    content_type: str
    csp: str
    proxy_path: str


class PreviewProxy:
    def __init__(self) -> None:
        self._grants: dict[str, dict[str, object]] = {}

    def expose_port(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        sandbox_id: str,
        port: int,
        ttl_seconds: int,
    ) -> PreviewGrant:
        _require_port(port)
        if ttl_seconds < 1:
            raise PreviewRefused("preview ttl refused")
        _owned(sandbox_id, tenant_id)
        grant_id = "prv-" + uuid.uuid4().hex[:12]
        proxy_path = f"/api/v1/previews/{sandbox_id}/{port}"
        self._grants[grant_id] = {
            "grant_id": grant_id,
            "proxy_path": proxy_path,
            "sandbox_id": sandbox_id,
            "port": port,
            "tenant_id": tenant_id,
            "owner_id": owner_id,
            "expires": time.monotonic() + ttl_seconds,
        }
        return PreviewGrant(
            grant_id=grant_id,
            proxy_path=proxy_path,
            sandbox_id=sandbox_id,
            port=port,
            tenant_id=tenant_id,
            owner_id=owner_id,
        )

    def fetch(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        sandbox_id: str,
        port: int,
        requested_url: str | None = None,
        grant_id: str | None = None,
    ) -> PreviewPage:
        _require_port(port)
        if requested_url is not None and _blocked(requested_url, port):
            raise PreviewRefused("preview url refused")
        _owned(sandbox_id, tenant_id)
        grant = self._grant(
            tenant_id=tenant_id,
            owner_id=owner_id,
            sandbox_id=sandbox_id,
            port=port,
            grant_id=grant_id,
        )
        if time.monotonic() >= float(grant["expires"]):
            raise PreviewRefused("preview expired")
        body = _read_loopback(sandbox_id, port)
        if body is None:
            raise TargetUnavailable(f"sandbox:{sandbox_id}:{port}")
        return PreviewPage(
            body=body,
            content_type="text/html; charset=utf-8",
            csp=_CSP,
            proxy_path=str(grant["proxy_path"]),
        )

    def _grant(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        sandbox_id: str,
        port: int,
        grant_id: str | None,
    ) -> dict[str, object]:
        if grant_id is not None:
            row = self._grants.get(grant_id)
            if row is None or not _same_caller(row, tenant_id, owner_id, sandbox_id, port):
                raise PreviewRefused("preview refused")
            return row
        rows = [
            row
            for row in self._grants.values()
            if _same_caller(row, tenant_id, owner_id, sandbox_id, port)
            and time.monotonic() < float(row["expires"])
        ]
        if not rows:
            raise PreviewRefused("preview refused")
        return max(rows, key=lambda row: float(row["expires"]))

    def build_router(self) -> APIRouter:
        proxy = self
        router = APIRouter()

        @router.get("/api/v1/previews/{sandbox_id}/{port}")
        def get_preview(sandbox_id: str, port: int, request: Request) -> Response:
            owner = request.headers.get("x-owner-id", "")
            tenant = request.headers.get("x-tenant-id", "")
            try:
                page = proxy.fetch(
                    tenant_id=tenant,
                    owner_id=owner,
                    sandbox_id=sandbox_id,
                    port=port,
                )
            except PreviewRefused as exc:
                raise HTTPException(status_code=403, detail="preview refused") from exc
            except TargetUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return Response(
                page.body,
                media_type="text/html",
                headers={"Content-Security-Policy": page.csp},
            )

        return router


def _same_caller(
    row: dict[str, object],
    tenant_id: str,
    owner_id: str,
    sandbox_id: str,
    port: int,
) -> bool:
    return (
        row["tenant_id"] == tenant_id
        and row["owner_id"] == owner_id
        and row["sandbox_id"] == sandbox_id
        and row["port"] == port
    )


def _owned(sandbox_id: str, tenant_id: str) -> None:
    try:
        GVisorSandbox().attach(sandbox_id, tenant_id=tenant_id)
    except AttachRefused as exc:
        raise PreviewRefused("preview refused") from exc


def _require_port(port: int) -> None:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise PreviewRefused("preview port refused")


def _blocked(url: str, port: int) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if host in _METADATA or parts.scheme != "http":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host != "localhost":
            return True
        return parts.port not in {None, port}
    if address.is_link_local or address.is_multicast or address.is_unspecified:
        return True
    if address.is_loopback:
        return parts.port not in {None, port}
    return True


def _read_loopback(sandbox_id: str, port: int) -> str | None:
    script = (
        "import http.client, sys\n"
        f"conn = http.client.HTTPConnection('127.0.0.1', {int(port)}, timeout=3)\n"
        "try:\n"
        "    conn.request('GET', '/')\n"
        "    resp = conn.getresponse()\n"
        "    if resp.status != 200:\n"
        "        raise SystemExit(1)\n"
        "    sys.stdout.write(resp.read().decode('utf-8', 'replace'))\n"
        "except Exception:\n"
        "    raise SystemExit(1)\n"
    )
    done = subprocess.run(
        [docker_executable(), "exec", sandbox_id, "python", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if done.returncode != 0:
        return None
    return done.stdout
