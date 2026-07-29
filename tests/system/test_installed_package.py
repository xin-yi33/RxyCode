from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSIONED_ROOT = PurePosixPath("RxyCode/RxyCode1_1_0")
EXPECTED_ENTRYPOINT = "RxyCode.RxyCode1_1_0.entrypoint:main"


@dataclass(frozen=True)
class InstalledPackage:
    wheel: Path
    sdist: Path
    venv: Path
    python: Path
    console: Path
    env: dict[str, str]
    workdir: Path


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    input_text: str | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {command!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _venv_executable(venv: Path, name: str) -> Path:
    if os.name == "nt":
        suffix = ".exe" if name in {"python", "rxycode"} else ""
        return venv / "Scripts" / f"{name}{suffix}"
    return venv / "bin" / name


@pytest.fixture(scope="module")
def installed_package(tmp_path_factory: pytest.TempPathFactory) -> InstalledPackage:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the installed-package system test")

    root = tmp_path_factory.mktemp("installed-rxycode")
    wheel_dir = root / "wheel"
    wheel_dir.mkdir()
    build_env = os.environ.copy()
    build_env.pop("PYTHONPATH", None)
    build_env.update(
        {
            "UV_CACHE_DIR": str(root / "uv-cache"),
            "UV_NO_PROGRESS": "1",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )

    before_egg_info = set(PROJECT_ROOT.glob("*.egg-info"))
    build_dir = PROJECT_ROOT / "build"
    build_dir_existed = build_dir.exists()
    try:
        _run(
            [
                uv,
                "build",
                "--no-build-isolation",
                "--out-dir",
                str(wheel_dir),
                "--python",
                sys.executable,
                str(PROJECT_ROOT),
            ],
            cwd=root,
            env=build_env,
            timeout=180,
        )
    finally:
        for generated in set(PROJECT_ROOT.glob("*.egg-info")) - before_egg_info:
            shutil.rmtree(generated, ignore_errors=True)
        if not build_dir_existed and build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)

    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found: {wheels}"
    wheel = wheels[0]
    sdists = list(wheel_dir.glob("*.tar.gz"))
    assert len(sdists) == 1, f"expected one sdist, found: {sdists}"
    sdist = sdists[0]

    venv = root / "venv"
    _run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        cwd=root,
        env=build_env,
    )
    python = _venv_executable(venv, "python")
    install_env = build_env.copy()
    install_env.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ],
        cwd=root,
        env=install_env,
    )

    console = _venv_executable(venv, "rxycode")
    assert console.is_file(), f"console script was not installed: {console}"

    workdir = root / "workdir"
    home = root / "fresh-home"
    data_dir = home / ".rxycode"
    workdir.mkdir()
    home.mkdir()
    data_dir.mkdir()
    runtime_env = install_env.copy()
    runtime_env.pop("PYTHONPATH", None)
    runtime_env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "RXYCODE_DATA_DIR": str(data_dir),
            "RXYCODE_V2_CONFIG_DIR": str(data_dir),
            "PATH": os.pathsep.join(
                [str(console.parent), runtime_env.get("PATH", "")]
            ),
        }
    )
    return InstalledPackage(
        wheel=wheel,
        sdist=sdist,
        venv=venv,
        python=python,
        console=console,
        env=runtime_env,
        workdir=workdir,
    )


def test_wheel_contains_runtime_contract_without_workspace_state(
    installed_package: InstalledPackage,
):
    with zipfile.ZipFile(installed_package.wheel) as archive:
        names = archive.namelist()
        paths = [PurePosixPath(name) for name in names if not name.endswith("/")]

        assert VERSIONED_ROOT / "entrypoint.py" in paths
        assert VERSIONED_ROOT / "__main__.py" in paths
        assert PurePosixPath("RxyCode/__main__.py") in paths
        assert VERSIONED_ROOT / "log/logger.py" in paths
        assert VERSIONED_ROOT / "frontend/package.json" in paths
        assert VERSIONED_ROOT / "frontend/dist/index.js" in paths
        assert any(
            path.parent == VERSIONED_ROOT / "evals/tasks"
            and path.suffix in {".yaml", ".yml"}
            for path in paths
        )

        forbidden_directories = {
            "tests",
            "data",
            "node_modules",
            "artifacts",
            "__pycache__",
            ".pytest_cache",
            "secret",
            "secrets",
        }
        leaked = [
            str(path)
            for path in paths
            if forbidden_directories.intersection(
                part.casefold() for part in path.parts
            )
            or path.suffix.casefold() in {".log", ".key", ".pem"}
            or path.name.casefold() in {".env", "credentials.yaml"}
        ]
        assert not leaked, f"wheel contains workspace state or credentials: {leaked}"

        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        assert metadata["Name"] == "rxycode"
        assert metadata["Version"] == "1.2.1"
        requirements = [
            value.casefold() for value in metadata.get_all("Requires-Dist", [])
        ]
        assert not any(requirement.startswith("textual") for requirement in requirements)

        entrypoints_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entrypoints = configparser.ConfigParser()
        entrypoints.read_string(archive.read(entrypoints_name).decode("utf-8"))
        assert entrypoints["console_scripts"]["rxycode"] == EXPECTED_ENTRYPOINT


def test_sdist_contains_bootstraps_without_runtime_state(
    installed_package: InstalledPackage,
):
    with tarfile.open(installed_package.sdist, mode="r:gz") as archive:
        paths = [PurePosixPath(member.name) for member in archive.getmembers()]

    roots = {path.parts[0] for path in paths if path.parts}
    assert len(roots) == 1
    root = next(iter(roots))
    relative = {
        PurePosixPath(*path.parts[1:])
        for path in paths
        if path.parts and path.parts[0] == root
    }
    for required in (
        PurePosixPath("pyproject.toml"),
        PurePosixPath("README.md"),
        PurePosixPath("install.ps1"),
        PurePosixPath("install.sh"),
        PurePosixPath("entrypoint.py"),
        PurePosixPath("frontend/package.json"),
        PurePosixPath("frontend/dist/index.js"),
        PurePosixPath("_package_root/RxyCode/__main__.py"),
    ):
        assert required in relative

    forbidden = {"artifacts", "data", "node_modules", "__pycache__"}
    leaked = [
        str(path)
        for path in relative
        if forbidden.intersection(part.casefold() for part in path.parts)
        or path.suffix.casefold() in {".log", ".key", ".pem"}
        or path.name.casefold() in {".env", "credentials.yaml"}
    ]
    assert not leaked, f"sdist contains runtime state or credentials: {leaked}"


def test_fresh_install_runs_console_and_module_entrypoints(
    installed_package: InstalledPackage,
):
    probe = _run(
        [
            str(installed_package.python),
            "-c",
            "import pathlib, RxyCode; print(pathlib.Path(RxyCode.__file__).resolve())",
        ],
        cwd=installed_package.workdir,
        env=installed_package.env,
    )
    assert str(installed_package.venv.resolve()).casefold() in probe.stdout.casefold()
    assert str(PROJECT_ROOT.resolve()).casefold() not in probe.stdout.casefold()

    version = _run(
        [str(installed_package.console), "--version"],
        cwd=installed_package.workdir,
        env=installed_package.env,
    )
    assert "1.2.1" in version.stdout + version.stderr

    help_result = _run(
        [str(installed_package.console), "--help"],
        cwd=installed_package.workdir,
        env=installed_package.env,
    )
    help_output = help_result.stdout + help_result.stderr
    assert "Usage:" in help_output
    assert "--version" in help_output

    for command in (
        [str(installed_package.python), "-m", "RxyCode"],
        [str(installed_package.console)],
    ):
        result = subprocess.run(
            command,
            cwd=installed_package.workdir,
            env=installed_package.env,
            input="/exit\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert "requires an interactive terminal (TTY)" in output
        assert "ERR_MODULE_NOT_FOUND" not in output
        assert "Cannot find module" not in output
        assert "Traceback (most recent call last)" not in output
