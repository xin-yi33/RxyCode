from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL_INSTALLER = PROJECT_ROOT / "install.ps1"
SHELL_INSTALLER = PROJECT_ROOT / "install.sh"
DEFAULT_SOURCE = "git+https://github.com/xin-yi33/RxyCode.git@v1.2.0"


def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _posix_shell() -> str | None:
    discovered = shutil.which("sh")
    if discovered:
        return discovered
    if os.name == "nt":
        git_shell = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "sh.exe"
        if git_shell.is_file():
            return str(git_shell)
    return None


def _base_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    local_app_data = tmp_path / "local-app-data"
    roaming_app_data = tmp_path / "roaming-app-data"
    for directory in (home, local_app_data, roaming_app_data):
        directory.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(local_app_data),
            "APPDATA": str(roaming_app_data),
            "RXYCODE_NO_MODIFY_PATH": "1",
        }
    )
    for key in (
        "RXYCODE_SOURCE",
        "RXYCODE_VERSION",
        "RXYCODE_INSTALL_DRY_RUN",
        "UV_INSTALL_DIR",
        "XDG_BIN_HOME",
    ):
        env.pop(key, None)
    return env


def _write_fake_uv(bin_dir: Path, log_path: Path) -> Path:
    bin_dir.mkdir(parents=True)
    helper = bin_dir / "fake_uv.py"
    helper.write_text(
        "from __future__ import annotations\n"
        "import json, os, sys\n"
        "with open(os.environ['RXYCODE_UV_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(int(os.environ.get('RXYCODE_FAKE_UV_EXIT', '0')))\n",
        encoding="utf-8",
    )

    if os.name == "nt":
        launcher = bin_dir / "uv.cmd"
        launcher.write_text(
            f'@"{sys.executable}" "{helper}" %*\r\n', encoding="utf-8"
        )
        shell_launcher = bin_dir / "uv"
        shell_launcher.write_text(
            "#!/bin/sh\n"
            'exec "$RXYCODE_TEST_PYTHON" "$RXYCODE_FAKE_UV_HELPER" "$@"\n',
            encoding="utf-8",
        )
        shell_launcher.chmod(0o755)
    else:
        launcher = bin_dir / "uv"
        launcher.write_text(
            "#!/bin/sh\n"
            'exec "$RXYCODE_TEST_PYTHON" "$RXYCODE_FAKE_UV_HELPER" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return helper


def _read_uv_calls(log_path: Path) -> list[list[str]]:
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_installer_sources_are_pinned_and_do_not_pipe_remote_code():
    ps_text = POWERSHELL_INSTALLER.read_text(encoding="utf-8")
    sh_text = SHELL_INSTALLER.read_text(encoding="utf-8")

    assert 'https://github.com/xin-yi33/RxyCode.git' in ps_text
    assert 'https://github.com/xin-yi33/RxyCode.git' in sh_text
    assert 'https://astral.sh/uv/install.ps1' in ps_text
    assert 'https://astral.sh/uv/install.sh' in sh_text
    assert "Invoke-Expression" not in ps_text
    assert "| iex" not in ps_text.lower()
    assert "curl |" not in sh_text
    assert "curl -" not in sh_text or "--output" in sh_text
    assert "RXYCODE_INSTALL_DRY_RUN" in ps_text
    assert "RXYCODE_INSTALL_DRY_RUN" in sh_text
    assert 'Add("--from")' not in ps_text
    assert "tool install --force --from" not in sh_text


def test_shell_installer_has_valid_syntax():
    shell = _posix_shell()
    if shell is None:
        pytest.skip("POSIX sh is not installed")

    result = subprocess.run(
        [shell, "-n", str(SHELL_INSTALLER)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_powershell_installer_has_valid_syntax():
    powershell = _powershell()
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    parse_command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:RXYCODE_INSTALLER_PARSE_PATH, [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { "
        "[Console]::Error.WriteLine($_.Message) }; exit 1 }"
    )
    env = os.environ.copy()
    env["RXYCODE_INSTALLER_PARSE_PATH"] = str(POWERSHELL_INSTALLER)
    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", parse_command],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", ["1.2.0", "v1.2.0"])
def test_powershell_dry_run_uses_version_without_network(tmp_path: Path, version: str):
    powershell = _powershell()
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    env = _base_env(tmp_path)
    env.update(
        {
            "RXYCODE_VERSION": version,
            "RXYCODE_INSTALL_DRY_RUN": "1",
            "PATH": "",
        }
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(POWERSHELL_INSTALLER),
            "-Force",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert DEFAULT_SOURCE in result.stdout
    assert "--force" in result.stdout
    assert "install.ps1" in result.stdout
    assert "RxyCode is installed" not in result.stdout


def test_powershell_uses_fake_uv_and_quotes_local_source(tmp_path: Path):
    powershell = _powershell()
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    source = tmp_path / "source with spaces"
    source.mkdir()
    log_path = tmp_path / "uv.jsonl"
    fake_bin = tmp_path / "fake-bin"
    helper = _write_fake_uv(fake_bin, log_path)
    env = _base_env(tmp_path)
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "RXYCODE_SOURCE": str(source),
            "RXYCODE_UV_LOG": str(log_path),
            "RXYCODE_TEST_PYTHON": sys.executable,
            "RXYCODE_FAKE_UV_HELPER": str(helper),
        }
    )

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(POWERSHELL_INSTALLER),
            "-Force",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _read_uv_calls(log_path) == [
        ["tool", "install", "--force", str(source.resolve())]
    ]
    assert "Run 'rxycode'" in result.stdout


def test_powershell_propagates_uv_failure(tmp_path: Path):
    powershell = _powershell()
    if powershell is None:
        pytest.skip("PowerShell is not installed")

    log_path = tmp_path / "uv.jsonl"
    fake_bin = tmp_path / "fake-bin"
    helper = _write_fake_uv(fake_bin, log_path)
    env = _base_env(tmp_path)
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "RXYCODE_SOURCE": str(tmp_path),
            "RXYCODE_UV_LOG": str(log_path),
            "RXYCODE_FAKE_UV_EXIT": "23",
            "RXYCODE_TEST_PYTHON": sys.executable,
            "RXYCODE_FAKE_UV_HELPER": str(helper),
        }
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(POWERSHELL_INSTALLER),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1
    assert "uv failed with exit code 23" in result.stderr
    assert "RxyCode is installed" not in result.stdout


def test_shell_uses_fake_uv_with_force_and_no_path_update(tmp_path: Path):
    shell = _posix_shell()
    if shell is None:
        pytest.skip("POSIX sh is not installed")

    source = tmp_path / "source with spaces"
    source.mkdir()
    log_path = tmp_path / "uv.jsonl"
    fake_bin = tmp_path / "fake-bin"
    helper = _write_fake_uv(fake_bin, log_path)
    env = _base_env(tmp_path)
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "RXYCODE_SOURCE": str(source),
            "RXYCODE_UV_LOG": str(log_path),
            "RXYCODE_TEST_PYTHON": sys.executable,
            "RXYCODE_FAKE_UV_HELPER": str(helper),
        }
    )
    result = subprocess.run(
        [shell, str(SHELL_INSTALLER), "--force"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = _read_uv_calls(log_path)
    assert len(calls) == 1
    assert calls[0][:3] == ["tool", "install", "--force"]
    assert Path(calls[0][3]).name == source.name
    assert "Run 'rxycode'" in result.stdout


def test_shell_dry_run_does_not_execute_uv(tmp_path: Path):
    shell = _posix_shell()
    if shell is None:
        pytest.skip("POSIX sh is not installed")

    log_path = tmp_path / "uv.jsonl"
    fake_bin = tmp_path / "fake-bin"
    helper = _write_fake_uv(fake_bin, log_path)
    env = _base_env(tmp_path)
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "RXYCODE_INSTALL_DRY_RUN": "1",
            "RXYCODE_UV_LOG": str(log_path),
            "RXYCODE_TEST_PYTHON": sys.executable,
            "RXYCODE_FAKE_UV_HELPER": str(helper),
        }
    )
    result = subprocess.run(
        [shell, str(SHELL_INSTALLER), "--force"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert DEFAULT_SOURCE in result.stdout
    assert _read_uv_calls(log_path) == []
    assert "RxyCode is installed" not in result.stdout


def test_installers_reject_invalid_version_before_running_uv(tmp_path: Path):
    shell = _posix_shell()
    if shell is None:
        pytest.skip("POSIX sh is not installed")

    log_path = tmp_path / "uv.jsonl"
    fake_bin = tmp_path / "fake-bin"
    helper = _write_fake_uv(fake_bin, log_path)
    env = _base_env(tmp_path)
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "RXYCODE_VERSION": "../../unexpected",
            "RXYCODE_UV_LOG": str(log_path),
            "RXYCODE_TEST_PYTHON": sys.executable,
            "RXYCODE_FAKE_UV_HELPER": str(helper),
        }
    )
    result = subprocess.run(
        [shell, str(SHELL_INSTALLER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid characters" in result.stderr
    assert _read_uv_calls(log_path) == []
