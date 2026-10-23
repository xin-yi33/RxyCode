"""One-time pairing codes. A code expires and cannot be redeemed twice."""

from __future__ import annotations

import secrets
from collections.abc import Callable


class PairingRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PairingBook:
    def __init__(self, *, clock: Callable[[], float], ttl: float) -> None:
        self._clock = clock
        self._ttl = ttl
        self._codes: dict[str, tuple[str, float, bool]] = {}

    def issue(self, tenant_id: str) -> str:
        # token_urlsafe can emit a leading '-', which argparse would reject when
        # the code is passed as `--code <value>` on the runner CLI.
        code = secrets.token_urlsafe(18)
        while code.startswith("-"):
            code = secrets.token_urlsafe(18)
        self._codes[code] = (tenant_id, self._clock() + self._ttl, False)
        return code

    def redeem(self, code: str) -> str:
        row = self._codes.get(code)
        if row is None:
            raise PairingRejected("PAIRING_INVALID")
        tenant_id, expires_at, used = row
        if self._clock() > expires_at:
            raise PairingRejected("PAIRING_EXPIRED")
        if used:
            raise PairingRejected("PAIRING_USED")
        self._codes[code] = (tenant_id, expires_at, True)
        return tenant_id
