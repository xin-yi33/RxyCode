"""Signing / notarization entry. Does not invent a signature."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def sign(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"SIGN_ENTRY path={path} digest={digest} signed=false notary=false")
    return {"path": str(path), "digest": digest, "signed": False, "notary": False}


if __name__ == "__main__":
    sign(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
