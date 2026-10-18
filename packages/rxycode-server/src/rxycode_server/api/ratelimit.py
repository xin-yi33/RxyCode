"""Per-client-IP fixed-window rate limiter for the public demo gateway.

The frozen public-demo requirement includes request rate limiting. The stock
``caddy:2`` image has no rate-limit plugin, so the gate lives at the app
layer: a pure-ASGI middleware keyed by the client address uvicorn reports
(``proxy_headers=True`` + ``forwarded_allow_ips`` maps the gateway's
X-Forwarded-For into ``scope["client"]``).

The window is per-process memory — honest for the single-replica demo stack.
A request that exceeds ``rpm`` gets ``429 {"code": "RATE_LIMITED"}`` plus a
``Retry-After`` of the seconds until the next window. ``rpm <= 0`` disables
the gate entirely (the default; local and test modes stay unthrottled).
"""

from __future__ import annotations

import json
import time
from typing import Any


class RateLimitMiddleware:
    """Refuse a client once it exceeds ``rpm`` requests in a 60s window."""

    def __init__(self, app: Any, *, rpm: int) -> None:
        self.app = app
        self.rpm = max(0, int(rpm))
        self._hits: dict[tuple[str, int], int] = {}
        self._last_prune = 0.0

    def _bucket(self, client: str) -> tuple[tuple[str, int], int, int]:
        """(key, hits so far this window, seconds until the window resets)."""
        now = time.monotonic()
        window = int(now // 60)
        if now - self._last_prune > 60:
            self._hits = {key: n for key, n in self._hits.items() if key[1] >= window}
            self._last_prune = now
        key = (client, window)
        hits = self._hits.get(key, 0) + 1
        self._hits[key] = hits
        return key, hits, max(1, int(60 - now % 60))

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self.rpm <= 0 or scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        client = "unknown"
        pair = scope.get("client")
        if isinstance(pair, (list, tuple)) and pair:
            client = str(pair[0])
        _key, hits, reset_in = self._bucket(client)
        if hits <= self.rpm:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"code": "RATE_LIMITED"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(reset_in).encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
