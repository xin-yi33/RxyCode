"""Real client IP for rate-limit keys.

Deployment runs uvicorn ``proxy_headers=True`` with private-range
``forwarded_allow_ips`` (see compose/serve_web.py), so ``scope["client"]``
is already the forwarded client once the request comes through the Caddy
gateway — a private/loopback peer. When a request reaches the app WITHOUT
that rewrite (direct socket, a test transport, a deployment that dropped
``--proxy-headers``) the peer is still the gateway and the client only
survives in headers. In that case we trust ``CF-Connecting-IP`` /
``X-Forwarded-For`` — but ONLY while the direct peer is a private/loopback
address: an attacker hitting the app directly can write those headers, so
a public peer falls back to the raw peer IP.

``CF-Connecting-IP`` wins over ``X-Forwarded-For`` because Cloudflare
overwrites it (a client cannot smuggle a prefix through it); XFF entries
are walked right-to-left past trusted private hops — the first public
entry is the caller every proxy forwarded for.
"""

from __future__ import annotations

import ipaddress


def _private_peer(host: str) -> bool:
    """Loopback/private/link-local — or a non-IP literal (unix socket,
    TestClient transport), which is local by definition."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return ip.is_loopback or ip.is_private or ip.is_link_local


def client_ip_from_scope(scope: dict) -> str:
    pair = scope.get("client")
    peer = str(pair[0]) if isinstance(pair, (list, tuple)) and pair else ""
    if not _private_peer(peer):
        return peer
    headers = {
        str(k.decode("latin1")).lower(): v.decode("latin1")
        for k, v in (scope.get("headers") or ())
    }
    cf = headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    forwarded = headers.get("x-forwarded-for", "")
    hosts = [h.strip() for h in forwarded.split(",") if h.strip()]
    for host in reversed(hosts):
        if not _private_peer(host):
            return host
    if hosts:
        return hosts[0]
    return peer or "-"


def client_ip(request) -> str:
    return client_ip_from_scope(request.scope)
