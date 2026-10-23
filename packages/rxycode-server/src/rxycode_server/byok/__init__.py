"""Web BYOK: tenant-owned model credentials, encrypted at rest.

The API key a user pastes is AES-256-GCM encrypted under a master key from
a file keyring (``RXYCODE_BYOK_KEYRING_FILE``) before it ever touches the
database. The worker decrypts it parent-side at claim time and injects it
on the upstream hop of the per-run egress gateway — the sandboxed child
only ever sees the loopback gateway address and a placeholder key.
"""

from rxycode_server.byok.crypto import (
    BYOKDecryptError,
    BYOKUnavailable,
    connection_aad,
    decrypt,
    encrypt,
)

__all__ = [
    "BYOKDecryptError",
    "BYOKUnavailable",
    "connection_aad",
    "decrypt",
    "encrypt",
]
