"""
Tests for utils/shell.py - Shell command execution and translation.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestShellExecutor:
    def _make_executor(self):
        from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor
        return ShellExecutor()

    def test_init(self):
        executor = self._make_executor()
        assert executor is not None

    def test_detect_shell(self):
        executor = self._make_executor()
        shell = executor._detect_shell()
        assert shell is not None

    def test_has_powershell(self):
        executor = self._make_executor()
        result = executor._has_powershell()
        assert isinstance(result, bool)

    def test_detect_desktop(self):
        executor = self._make_executor()
        executor._detect_desktop()  # should not crash

    def test_is_powershell_syntax(self):
        executor = self._make_executor()
        result = executor._is_powershell_syntax("Get-ChildItem")
        assert isinstance(result, bool)

    def test_translate_command(self):
        executor = self._make_executor()
        result = executor.translate_command("ls")
        assert result is not None

    def test_powershell_translates_cmd_chain_and_start(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command(
            r"cd /d D:\agent-demo\RxyCode\RxyCode1_1_0 && dir"
        )
        assert shell == "powershell"
        assert "&&" not in cmd
        assert "Set-Location" in cmd
        assert ";" in cmd

        started, shell2 = executor.translate_command("start cmd /k python hello_rxy.py")
        assert shell2 == "powershell"
        assert "Start-Process" in started
        assert "cmd.exe" in started
        assert "python hello_rxy.py" in started

    def test_translate_complex_command(self):
        executor = self._make_executor()
        result = executor.translate_command("pip install flask")
        assert result is not None

    def test_execute_simple(self):
        executor = self._make_executor()
        result = executor.execute("echo hello")
        assert isinstance(result, dict)
        assert "stdout" in result or "success" in result

    def test_execute_python_command(self):
        executor = self._make_executor()
        result = executor.execute("python --version")
        assert isinstance(result, dict)

    def test_execute_invalid_command(self):
        executor = self._make_executor()
        result = executor.execute("nonexistent_command_xyz_123")
        assert isinstance(result, dict)

    def test_execute_empty_command(self):
        executor = self._make_executor()
        result = executor.execute("")
        assert isinstance(result, dict)
