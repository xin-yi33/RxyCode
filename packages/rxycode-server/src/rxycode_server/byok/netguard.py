"""Network guard for user-supplied model base URLs.

A BYOK base URL becomes an upstream the worker's egress gateway connects
to carrying a real credential — the URL must never resolve to a private,
loopback, link-local or otherwise non-global address, or BYOK turns into
an SSRF proxy. Same rules as the worker's egress ``_ip_blocked``.

``RXYCODE_BYOK_ALLOW_PRIVATE=1`` is the explicit dev/test escape hatch:
it permits http:// and private/loopback destinations.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit


def _allow_private() -> bool:
    return os.environ.get("RXYCODE_BYOK_ALLOW_PRIVATE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ip_blocked(addr: str) -> bool:
    """Same semantics as rxycode_worker.egress._ip_blocked."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return not bool(ip.is_global)


def vet_base_url(raw: str) -> str:
    """Validate + normalize a BYOK base URL. Raises ValueError on refusal."""
    allow_private = _allow_private()
    text = str(raw or "").strip()
    if not text or len(text) > 2048:
        raise ValueError("invalid base_url")
    if "://" not in text:
        text = f"https://{text}"
    try:
        split = urlsplit(text)
    except ValueError as exc:
        raise ValueError("invalid base_url") from exc
    scheme = split.scheme.lower()
    if scheme == "http" and not allow_private:
        raise ValueError("base_url must use https")
    if scheme not in {"http", "https"}:
        raise ValueError("invalid base_url scheme")
    if split.username or split.password:
        raise ValueError("base_url must not carry userinfo")
    host = (split.hostname or "").strip().lower()
    if not host:
        raise ValueError("base_url has no host")
    try:
        port = split.port
    except ValueError as exc:
        raise ValueError("invalid base_url port") from exc
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 0 < port < 65536:
        raise ValueError("invalid base_url port")
    if split.query or split.fragment:
        raise ValueError("base_url must not carry query or fragment")

    if allow_private:
        # Dev/test only: private + loopback destinations permitted.
        pass
    else:
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise ValueError("base_url host does not resolve") from exc
            addresses = {str(info[4][0]) for info in infos}
        if not addresses or any(_ip_blocked(addr) for addr in addresses):
            raise ValueError("base_url resolves to a non-public address")

    netloc = f"[{host}]" if ":" in host else host
    if split.port is not None or port != (443 if scheme == "https" else 80):
        netloc = f"{netloc}:{port}"
    path = (split.path or "").rstrip("/")
    return urlunsplit((scheme, netloc, path or "", "", ""))
