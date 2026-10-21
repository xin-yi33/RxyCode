"""Keyring bootstrap CLI::

    python -m rxycode_server.byok.keyring generate <path>

Writes ``{"active": "k1", "keys": {"k1": "<base64 32 bytes>"}}`` with mode
0600 (best effort on Windows). Never overwrites an existing file — losing
the active key orphans every stored credential.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path


def generate(path: Path) -> None:
    """Write a fresh single-key keyring. Refuses to overwrite."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"keyring already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    keyring = {
        "active": "k1",
        "keys": {"k1": base64.b64encode(os.urandom(32)).decode()},
    }
    # 'x' mode: a racing generator cannot clobber the file we just checked.
    with path.open("x", encoding="utf-8") as fh:
        json.dump(keyring, fh, indent=2)
        fh.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows ACLs ignore POSIX modes; the file is still private per-ACL.


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "generate":
        print(
            "usage: python -m rxycode_server.byok.keyring generate <path>",
            file=sys.stderr,
        )
        return 2
    try:
        generate(Path(args[1]))
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"cannot write keyring: {exc}", file=sys.stderr)
        return 1
    print(f"keyring written: {args[1]} (active key k1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
