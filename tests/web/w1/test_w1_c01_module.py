"""WEB-W1-C01. An installed wheel exposes one Session and the CLI entry."""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def test_w1_c01_integration(tmp_path: Path):
    """A wheel of HEAD, installed without the checkout on the path, is one Session."""
    archive = tmp_path / "head.tar"
    archived = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert archived.returncode == 0, archived.stderr
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with tarfile.open(archive) as bundle:
        if sys.version_info >= (3, 12):
            bundle.extractall(checkout, filter="data")
        else:
            bundle.extractall(checkout)
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
            str(checkout),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("rxycode-*.whl"))
    assert len(wheels) == 1
    env_dir = tmp_path / "venv"
    # Third-party deps stay on the base interpreter. The origin check below
    # rejects a checkout or editable install that shadows this wheel.
    venv.create(env_dir, with_pip=True, system_site_packages=True)
    python = _python(env_dir)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert install.returncode == 0, install.stderr
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import RxyCode.RxyCode1_1_0.appserver.server as server\n"
            "import RxyCode.RxyCode1_1_0.core.session as legacy\n"
            "import rxycode_core\n"
            "from pathlib import Path\n"
            "assert rxycode_core.Session is legacy.Session\n"
            "for mod in (rxycode_core, legacy, server):\n"
            "    print(Path(mod.__file__).resolve())\n"
            "print('wheel-session-ok')\n",
        ],
        cwd=run_dir,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert probe.returncode == 0, probe.stderr
    assert "wheel-session-ok" in probe.stdout
    venv_root = str(env_dir.resolve()).casefold()
    repo_root = str(REPO.resolve()).casefold()
    origins = [
        line.strip()
        for line in probe.stdout.splitlines()
        if line.strip() and line.strip() != "wheel-session-ok"
    ]
    assert len(origins) == 3
    for origin in origins:
        folded = origin.casefold()
        assert venv_root in folded
        assert repo_root not in folded
    console = env_dir / "Scripts" / "rxycode.exe" if os.name == "nt" else env_dir / "bin" / "rxycode"
    help_run = subprocess.run(
        [str(console), "--help"],
        cwd=run_dir,
        text=True,
        capture_output=True,
        check=False,
        env=_clean_env(),
    )
    assert help_run.returncode == 0, help_run.stderr
    assert "Usage:" in help_run.stdout + help_run.stderr
