"""ALTCHA proof-of-work human verification (open-source, self-contained).

Wire shape per https://altcha.org — the server issues a signed challenge:

    salt      = <random hex>?expires=<unix>&
    number    = random in [0, maxnumber)
    challenge = SHA256(salt + str(number))            (hex)
    signature = HMAC_SHA256(secret, challenge)        (hex)

The widget brute-forces ``number`` until its hash matches ``challenge`` and
posts back the payload (base64 JSON). Verification here is pure crypto:
recompute the signature, recompute the hash, check the salt's ``expires``
param, and burn the challenge so it cannot be replayed. The replay registry
lives per-replica like the auth rate limiters — a solved challenge is at most
useful inside its 20-minute window anyway.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qsl, urlparse

_TTL_SECONDS = 20 * 60
_MAX_NUMBER = 100_000


def create_challenge(secret: str) -> dict[str, object]:
    salt = secrets.token_hex(12) + f"?expires={int(time.time()) + _TTL_SECONDS}&"
    number = secrets.randbelow(_MAX_NUMBER)
    challenge = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    signature = hmac.new(secret.encode(), challenge.encode(), "sha256").hexdigest()
    return {
        "algorithm": "SHA-256",
        "challenge": challenge,
        "maxnumber": _MAX_NUMBER,
        "salt": salt,
        "signature": signature,
    }


class _ReplayRegistry:
    """challenge → expiry; a solved challenge can never verify twice."""

    def __init__(self) -> None:
        self.seen: dict[str, float] = {}

    def burn(self, challenge: str, expires: float) -> bool:
        now = time.time()
        if len(self.seen) > 4096:
            self.seen = {k: v for k, v in self.seen.items() if v > now}
        if challenge in self.seen:
            return False
        self.seen[challenge] = expires
        return True


def _expiry(salt: str) -> float:
    _, _, query = salt.partition("?")
    params = dict(parse_qsl(query))
    try:
        return float(params.get("expires") or params.get("expire") or 0)
    except ValueError:
        return 0.0


def verify_payload(
    payload_b64: object, secret: str, registry: _ReplayRegistry
) -> bool:
    """True when the widget's solution is genuine, unexpired, and fresh."""
    if not isinstance(payload_b64, str) or not payload_b64:
        return False
    try:
        import json

        payload = json.loads(base64.b64decode(payload_b64, validate=True))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    challenge = str(payload.get("challenge") or "")
    signature = str(payload.get("signature") or "")
    salt = str(payload.get("salt") or "")
    number = payload.get("number")
    if payload.get("algorithm") != "SHA-256" or not challenge or not salt:
        return False
    try:
        number_int = int(number)
    except (TypeError, ValueError):
        return False
    expected_sig = hmac.new(secret.encode(), challenge.encode(), "sha256").hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        return False
    if hashlib.sha256(f"{salt}{number_int}".encode()).hexdigest() != challenge:
        return False
    expires = _expiry(salt)
    if not expires or expires <= time.time():
        return False
    return registry.burn(challenge, expires)
