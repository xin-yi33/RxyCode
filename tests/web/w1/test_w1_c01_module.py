"""WEB-W1-C01. An installed wheel exposes one Session and the CLI entry."""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def test_w1_c01_integration(tmp_path: Path):
    """A fresh venv install keeps Session identity and can start the console."""
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-w",
            str(wheel_dir),
            str(REPO),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("rxycode-*.whl"))
    assert len(wheels) == 1
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True, system_site_packages=True)
    python = _python(env_dir)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        text=True,
        capture_output=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import RxyCode.RxyCode1_1_0.appserver.server as server\n"
            "import RxyCode.RxyCode1_1_0.core.session as legacy\n"
            "import rxycode_core\n"
            "assert rxycode_core.Session is legacy.Session\n"
            "print('wheel-session-ok')\n",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert "wheel-session-ok" in probe.stdout
    console = env_dir / "Scripts" / "rxycode.exe" if os.name == "nt" else env_dir / "bin" / "rxycode"
    help_run = subprocess.run(
        [str(console), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_run.returncode == 0, help_run.stderr
    assert "Usage:" in help_run.stdout + help_run.stderr
