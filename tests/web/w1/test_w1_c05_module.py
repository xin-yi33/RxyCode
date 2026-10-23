"""WEB-W1-C05. Existing CLI help stays, and web help says it is not delivered."""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import venv
from pathlib import Path

from click.testing import CliRunner

from RxyCode.RxyCode1_1_0.main import cli

REPO = Path(__file__).resolve().parents[3]


def test_w1_c05_integration():
    """rxycode --help keeps gui/config, and web --help states the reserved command."""
    runner = CliRunner()
    top = runner.invoke(cli, ["--help"])
    assert top.exit_code == 0, top.output
    assert "gui" in top.output
    assert "config" in top.output
    assert "--model" in top.output
    web = runner.invoke(cli, ["web", "--help"])
    assert web.exit_code == 0, web.output
    assert "connect" in web.output
    assert "not delivered" in web.output.casefold()
    connect = runner.invoke(cli, ["web", "connect", "--help"])
    assert connect.exit_code == 0, connect.output
    assert "not implemented" in connect.output.casefold()


def test_w1_c05_installed_core(tmp_path: Path):
    """An installed wheel exposes one core facade and the reserved web help."""
    archive = tmp_path / "head.tar"
    archived = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
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
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), str(checkout)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("rxycode-*.whl"))
    assert len(wheels) == 1
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True, system_site_packages=True)
    python = env_dir / "Scripts" / "python.exe" if os.name == "nt" else env_dir / "bin" / "python"
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert install.returncode == 0, install.stderr
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "from RxyCode.RxyCode1_1_0.main import core_for_surface\n"
            "left = core_for_surface('cli')\n"
            "right = core_for_surface('web')\n"
            "assert left['agent_runtime'] is right['agent_runtime']\n"
            "assert left['session'] is right['session']\n"
            "print('installed-core-ok')\n",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert probe.returncode == 0, probe.stderr
    assert "installed-core-ok" in probe.stdout
    console = env_dir / "Scripts" / "rxycode.exe" if os.name == "nt" else env_dir / "bin" / "rxycode"
    help_run = subprocess.run(
        [str(console), "web", "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert help_run.returncode == 0, help_run.stderr
    assert "not delivered" in (help_run.stdout + help_run.stderr).casefold()
