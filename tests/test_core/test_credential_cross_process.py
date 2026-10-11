"""Two real processes must not drop each other's credential writes."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CHILD = textwrap.dedent(
    """
    import os
    import sys
    from pathlib import Path

    os.environ["RXYCODE_CREDENTIAL_RMW_PAUSE"] = "0.4"
    sys.path.insert(0, sys.argv[1])
    from config.credential_store import store_credentials

    print(store_credentials([sys.argv[3]], Path(sys.argv[2]))[0], flush=True)
    """
)


def test_two_processes_keep_both_credential_references(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("models: {}\n", encoding="utf-8")
    children = []
    for secret in ("isolated-secret-a", "isolated-secret-b"):
        children.append(
            subprocess.Popen(
                [sys.executable, "-c", CHILD, str(REPO), str(config_path), secret],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    refs: list[str] = []
    try:
        for child, secret in zip(children, ("isolated-secret-a", "isolated-secret-b")):
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            ref = stdout.strip().splitlines()[-1]
            refs.append(ref)
            assert ref
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()

    os.environ.pop("RXYCODE_CREDENTIAL_RMW_PAUSE", None)
    sys.path.insert(0, str(REPO))
    from config.credential_store import load_credential

    loaded = [load_credential(ref, config_path) for ref in refs]
    assert loaded == ["isolated-secret-a", "isolated-secret-b"]
