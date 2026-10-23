"""Contract tests for the generated command wrapper (both platforms).

Rewritten 2026-10-23 for the second protocol: the user command is base64-
encoded into a ScriptBlock (so multi-line blocks survive PowerShell's stdin
parser) and exit status travels through temp files rather than in-band text.

These assert the SHAPE of the generated script.  They do NOT prove POSIX
runtime behaviour -- that is called out separately below.
"""

from __future__ import annotations

import base64

import pytest

from RxyCode.RxyCode1_1_0.core.persistent_shell import (
    _build_wrapped_command,
    _is_powershell,
    _marker_protocol,
    default_shell_argv,
)


def _decoded_user_command(script: str) -> str:
    marker = "FromBase64String('"
    start = script.index(marker) + len(marker)
    end = script.index("'", start)
    return base64.b64decode(script[start:end]).decode("utf-8")


class TestPowerShellWrapper:
    def test_begin_marker_precedes_command(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command("Write-Output hi", protocol, powershell=True)
        # The user text is base64-encoded, so compare against the marker order.
        assert script.index(protocol.begin) < script.index("FromBase64String")

    def test_end_marker_present(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command("echo x", protocol, powershell=True)
        assert protocol.end in script

    def test_exit_code_comes_from_a_file(self):
        """In-band rc parsing was replaced by temp files (audit: stale rc)."""
        protocol = _marker_protocol()
        script = _build_wrapped_command("echo x", protocol, powershell=True)
        assert protocol.rc_file_path in script
        assert "Set-Content -LiteralPath" in script

    def test_user_command_is_base64_encoded(self):
        """A multi-line user command must not break the stdin parser."""
        protocol = _marker_protocol()
        user = "function f {\n  Write-Output a\n}\nf"
        script = _build_wrapped_command(user, protocol, powershell=True)
        assert "\n" not in script.split("FromBase64String", 1)[1].split(")", 1)[0]
        assert _decoded_user_command(script) == user

    def test_dot_sourced_for_state_persistence(self):
        """'&' made assignments local; dot-sourcing keeps them in the session."""
        protocol = _marker_protocol()
        script = _build_wrapped_command("$x = 1", protocol, powershell=True)
        assert ". $__rxy_sb" in script

    def test_information_stream_captured(self):
        """Write-Host output must be captured, so 6>&1 is required."""
        protocol = _marker_protocol()
        script = _build_wrapped_command("Write-Host x", protocol, powershell=True)
        assert "6>&1" in script

    def test_workdir_failure_prevents_execution(self):
        """A failed Set-Location must skip the command entirely."""
        protocol = _marker_protocol()
        script = _build_wrapped_command(
            "Write-Output $x", protocol, powershell=True, workdir="C:\\tmp"
        )
        assert "if ($__rxy_ok)" in script
        assert "126" in script

    def test_workdir_restores_previous_directory(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command(
            "echo", protocol, powershell=True, workdir="C:\\tmp"
        )
        assert "Set-Location -LiteralPath $__rxy_prev" in script

    def test_no_subshell_for_workdir(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command(
            "echo $x", protocol, powershell=True, workdir="C:\\tmp"
        )
        # A subshell operator would isolate variables as well.
        assert "& {\n" not in script


class TestPosixWrapper:
    """String contract only: this host cannot execute a POSIX shell."""

    def test_markers_present(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command("echo hi", protocol, powershell=False)
        assert protocol.begin in script
        assert protocol.end in script

    def test_exit_code_written_to_file(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command("false", protocol, powershell=False)
        assert "__rxy_rc=$?" in script
        assert protocol.rc_file_path in script

    def test_workdir_saves_and_restores_pwd(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command(
            "echo", protocol, powershell=False, workdir="/tmp"
        )
        assert "__rxy_prev=$PWD" in script
        assert 'cd "$__rxy_prev"' in script

    def test_workdir_failure_exits_before_command(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command(
            "echo SHOULD_NOT_RUN", protocol, powershell=False, workdir="/nope"
        )
        fail_at = script.index("workdir_failed")
        cmd_at = script.index("echo SHOULD_NOT_RUN")
        assert fail_at < cmd_at
        assert "exit 0" in script

    def test_no_subshell_for_workdir(self):
        protocol = _marker_protocol()
        script = _build_wrapped_command(
            "echo $x", protocol, powershell=False, workdir="/tmp"
        )
        assert "( echo $x" not in script


class TestDetection:
    @pytest.mark.parametrize(
        "argv,expected",
        [
            (["powershell.exe", "-Command", "-"], True),
            (["C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"], True),
            (["/bin/bash"], False),
            (["/bin/sh"], False),
            ([], False),
        ],
    )
    def test_is_powershell(self, argv, expected):
        assert _is_powershell(argv) is expected

    def test_default_argv_is_non_empty(self):
        argv = default_shell_argv()
        assert isinstance(argv, list) and argv
        assert all(isinstance(part, str) and part for part in argv)


class TestMarkerUniqueness:
    def test_each_command_gets_a_new_token(self):
        a = _marker_protocol()
        b = _marker_protocol()
        assert a.token != b.token
        assert a.rc_file_path != b.rc_file_path

    def test_token_is_long_enough_to_resist_spoofing(self):
        assert len(_marker_protocol().token) >= 24
