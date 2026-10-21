"""AES-256-GCM envelope for user model credentials.

Keyring file (``RXYCODE_BYOK_KEYRING_FILE``) is JSON::

    {"active": "k1", "keys": {"k1": "<base64 of 32 random bytes>"}}

Old key ids stay in ``keys`` after rotation so existing ciphertext keeps
decrypting. The keyring is loaded lazily per call with an mtime cache —
there is no global key swap and no plaintext/base64/random-key fallback.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class BYOKUnavailable(RuntimeError):
    """The keyring is missing, unreadable, or malformed. Never degrade."""


class BYOKDecryptError(RuntimeError):
    """Ciphertext, nonce, key id, or AAD do not verify."""


_AAD_PREFIX = "rxycode-byok:v1"
_KEYRING_ENV = "RXYCODE_BYOK_KEYRING_FILE"
_NONCE_BYTES = 12


def connection_aad(
    *,
    tenant_id: str,
    owner_user_id: str,
    connection_id: str,
    credential_version: int,
) -> bytes:
    """The exact AAD a connection credential is sealed to.

    Changing tenant, owner, connection, or credential_version makes the
    stored ciphertext undecryptable — a rotated key can never be replayed
    against the old snapshot.
    """
    return (
        f"{_AAD_PREFIX}:{tenant_id}:{owner_user_id}:{connection_id}:"
        f"{int(credential_version)}"
    ).encode()


@dataclass(frozen=True)
class _Keyring:
    active: str
    keys: dict[str, bytes]


# (path, mtime_ns) -> keyring; reloaded when the file changes on disk.
_CACHE: dict[tuple[str, int], _Keyring] = {}
_CACHE_KEY: tuple[str, int] | None = None


def _keyring_path() -> Path:
    raw = os.environ.get(_KEYRING_ENV, "").strip()
    if not raw:
        raise BYOKUnavailable(f"{_KEYRING_ENV} is not set")
    return Path(raw)


def _parse_keyring(raw: str) -> _Keyring:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise BYOKUnavailable("keyring is not valid JSON") from exc
    if not isinstance(data, dict):
        raise BYOKUnavailable("keyring must be a JSON object")
    active = str(data.get("active") or "")
    raw_keys = data.get("keys")
    if not active or not isinstance(raw_keys, dict) or active not in raw_keys:
        raise BYOKUnavailable("keyring is missing its active key")
    keys: dict[str, bytes] = {}
    for key_id, encoded in raw_keys.items():
        try:
            material = base64.b64decode(str(encoded), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise BYOKUnavailable("keyring key material is not base64") from exc
        if len(material) != 32:
            raise BYOKUnavailable("keyring keys must be 32 bytes")
        keys[str(key_id)] = material
    return _Keyring(active=active, keys=keys)


def load_keyring() -> _Keyring:
    """Read + parse the keyring, cached on (path, mtime). Any failure is
    ``BYOKUnavailable`` — there is no weaker source to fall back to."""
    global _CACHE_KEY
    path = _keyring_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as exc:
        raise BYOKUnavailable("keyring file is not readable") from exc
    cache_key = (str(path), mtime)
    if _CACHE_KEY == cache_key and cache_key in _CACHE:
        return _CACHE[cache_key]
    try:
        parsed = _parse_keyring(path.read_text(encoding="utf-8"))
    except BYOKUnavailable:
        raise
    except OSError as exc:
        raise BYOKUnavailable("keyring file is not readable") from exc
    _CACHE.clear()
    _CACHE[cache_key] = parsed
    _CACHE_KEY = cache_key
    return parsed


def encrypt(plaintext: str, *, aad: bytes) -> tuple[bytes, bytes, str]:
    """Seal a credential under the active key. Fresh 96-bit nonce per call."""
    keyring = load_keyring()
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(keyring.keys[keyring.active]).encrypt(
        nonce, plaintext.encode("utf-8"), aad
    )
    return ciphertext, nonce, keyring.active


def decrypt(
    ciphertext: bytes,
    nonce: bytes,
    key_id: str,
    *,
    aad: bytes,
) -> str:
    """Open a credential with its recorded key id + AAD. Old key ids keep
    working after rotation while they remain in the keyring."""
    keyring = load_keyring()
    material = keyring.keys.get(str(key_id or ""))
    if material is None:
        raise BYOKDecryptError(f"unknown key id {key_id!r}")
    try:
        plain = AESGCM(material).decrypt(bytes(nonce), bytes(ciphertext), aad)
    except Exception as exc:  # InvalidTag and friends — never disambiguate
        raise BYOKDecryptError("credential does not verify") from exc
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BYOKDecryptError("credential is not utf-8") from exc
