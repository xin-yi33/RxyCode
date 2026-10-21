"""BYOK keyring + AES-256-GCM envelope (WEB BYOK §13.7).

Pure python — no database. Canary-shaped plaintext only, never a real key.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_pkg = REPO / "packages" / "rxycode-server" / "src"
if _pkg.is_dir() and str(_pkg) not in sys.path:
    sys.path.insert(0, str(_pkg))

from rxycode_server.byok.crypto import (  # noqa: E402
    BYOKDecryptError,
    BYOKUnavailable,
    connection_aad,
    decrypt,
    encrypt,
)
from rxycode_server.byok.keyring import generate  # noqa: E402

CANARY = "sk-canary-bb71f2e3a4c34d12"


def _keyring(tmp_path: Path, keys: dict[str, bytes] | None = None, active="k1") -> Path:
    import base64
    import os

    material = keys or {"k1": os.urandom(32)}
    path = tmp_path / "keyring.json"
    path.write_text(
        json.dumps(
            {
                "active": active,
                "keys": {
                    key_id: base64.b64encode(raw).decode()
                    for key_id, raw in material.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _aad(**overrides) -> bytes:
    fields = {
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "connection_id": "mc_abc",
        "credential_version": 1,
    }
    fields.update(overrides)
    return connection_aad(**fields)


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(_keyring(tmp_path)))
    ciphertext, nonce, key_id = encrypt(CANARY, aad=_aad())
    assert key_id == "k1"
    assert ciphertext != CANARY.encode()
    assert decrypt(ciphertext, nonce, key_id, aad=_aad()) == CANARY


def test_unique_nonces(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(_keyring(tmp_path)))
    _, nonce_a, _ = encrypt(CANARY, aad=_aad())
    _, nonce_b, _ = encrypt(CANARY, aad=_aad())
    assert nonce_a != nonce_b


def test_tampered_ciphertext_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(_keyring(tmp_path)))
    ciphertext, nonce, key_id = encrypt(CANARY, aad=_aad())
    tampered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    with pytest.raises(BYOKDecryptError):
        decrypt(tampered, nonce, key_id, aad=_aad())


def test_aad_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(_keyring(tmp_path)))
    ciphertext, nonce, key_id = encrypt(CANARY, aad=_aad())
    # Wrong tenant, wrong owner, wrong connection, wrong version — all fail.
    for override in (
        {"tenant_id": "tenant-b"},
        {"owner_user_id": "user-b"},
        {"connection_id": "mc_other"},
        {"credential_version": 2},
    ):
        with pytest.raises(BYOKDecryptError):
            decrypt(ciphertext, nonce, key_id, aad=_aad(**override))


def test_missing_keyring(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(tmp_path / "nope.json"))
    with pytest.raises(BYOKUnavailable):
        encrypt(CANARY, aad=_aad())
    monkeypatch.delenv("RXYCODE_BYOK_KEYRING_FILE")
    with pytest.raises(BYOKUnavailable):
        encrypt(CANARY, aad=_aad())


def test_unknown_key_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(_keyring(tmp_path)))
    ciphertext, nonce, _ = encrypt(CANARY, aad=_aad())
    with pytest.raises(BYOKDecryptError):
        decrypt(ciphertext, nonce, "k9", aad=_aad())


def test_malformed_keyring(tmp_path, monkeypatch):
    # Distinct paths: the loader caches on (path, mtime).
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(bad))
    with pytest.raises(BYOKUnavailable):
        encrypt(CANARY, aad=_aad())
    bad2 = tmp_path / "bad2.json"
    bad2.write_text(json.dumps({"active": "k9", "keys": {}}), encoding="utf-8")
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(bad2))
    with pytest.raises(BYOKUnavailable):
        encrypt(CANARY, aad=_aad())


def test_rotation_decrypts_old_keys(tmp_path, monkeypatch):
    import base64
    import os

    k1 = os.urandom(32)
    monkeypatch.setenv(
        "RXYCODE_BYOK_KEYRING_FILE", str(_keyring(tmp_path, {"k1": k1}))
    )
    ciphertext, nonce, key_id = encrypt(CANARY, aad=_aad())
    assert key_id == "k1"
    # Rotate: k2 becomes active, k1 stays for old ciphertext.
    rotated = tmp_path / "rotated.json"
    rotated.write_text(
        json.dumps(
            {
                "active": "k2",
                "keys": {
                    "k1": base64.b64encode(k1).decode(),
                    "k2": base64.b64encode(os.urandom(32)).decode(),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(rotated))
    assert decrypt(ciphertext, nonce, "k1", aad=_aad()) == CANARY
    _, _, new_id = encrypt("sk-canary-new", aad=_aad())
    assert new_id == "k2"


def test_generate_cli(tmp_path):
    target = tmp_path / "gen" / "keyring.json"
    generate(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["active"] == "k1"
    import base64

    assert len(base64.b64decode(data["keys"]["k1"])) == 32
    if sys.platform != "win32":
        assert (target.stat().st_mode & 0o777) == 0o600
    with pytest.raises(FileExistsError):
        generate(target)
    # The module CLI refuses overwrite too.
    outcome = subprocess.run(
        [
            sys.executable,
            "-m",
            "rxycode_server.byok.keyring",
            "generate",
            str(target),
        ],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(_pkg)},
    )
    assert outcome.returncode == 1
    assert "already exists" in outcome.stderr
