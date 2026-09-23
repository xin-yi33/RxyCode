"""The Muse adapter stress script must run from a source checkout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_stress_muse_script_runs_from_arbitrary_cwd(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    script = repo / "scripts" / "stress_muse_provider.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--requests",
            "1",
            "--chunks",
            "1",
            "--concurrency",
            "1",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "passed" in result.stdout
