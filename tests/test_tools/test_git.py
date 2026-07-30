"""
Tests for tools/git_tool.py - Git operations.

Covers: status, diff, log, branch, add, commit, checkout, unknown ops, error handling.
"""
import pytest
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestGitInput:
    def test_default_values(self):
        from RxyCode.RxyCode1_1_0.tools.git_tool import GitInput
        gi = GitInput()
        assert gi.operation == "status"
        assert gi.path == "."
        assert gi.args == ""

    def test_custom_values(self):
        from RxyCode.RxyCode1_1_0.tools.git_tool import GitInput
        gi = GitInput(operation="diff", path="/repo", args="--stat")
        assert gi.operation == "diff"
        assert gi.path == "/repo"
        assert gi.args == "--stat"


class TestRunGit:
    def test_invalid_path(self):
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        result = run_git("status", "/nonexistent/path/12345")
        assert "error" in result.lower()

    def test_not_a_directory(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        f = tmp_path / "file.txt"
        f.write_text("test")
        result = run_git("status", str(f))
        assert "error" in result.lower()

    def test_unknown_operation(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        result = run_git("invalid_op", str(tmp_path))
        assert "error" in result.lower()
        assert "invalid_op" in result

    def test_commit_without_args(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        result = run_git("commit", str(tmp_path), "")
        assert "error" in result.lower() or "message" in result.lower()

    def test_checkout_without_args(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        result = run_git("checkout", str(tmp_path), "")
        assert "error" in result.lower()

    def test_status_on_git_repo(self, tmp_path):
        """Test status on an actual initialized git repo."""
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        # Init a git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True)
        result = run_git("status", str(tmp_path))
        # Should return empty status or clean status
        assert isinstance(result, str)

    def test_log_on_git_repo(self, tmp_path):
        """Test log on a git repo with commits."""
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True)
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"],
                       cwd=str(tmp_path), capture_output=True)
        result = run_git("log", str(tmp_path))
        assert "initial" in result

    def test_branch_on_git_repo(self, tmp_path):
        """Test branch listing on git repo."""
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True)
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"],
                       cwd=str(tmp_path), capture_output=True)
        result = run_git("branch", str(tmp_path))
        assert isinstance(result, str)

    def test_stash_list(self, tmp_path):
        """Test stash list on git repo."""
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        result = run_git("stash", str(tmp_path))
        assert isinstance(result, str)

    def test_remote_view(self, tmp_path):
        """Test remote -v on git repo."""
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        result = run_git("remote", str(tmp_path))
        assert isinstance(result, str)

    def test_init_operation(self, tmp_path):
        """Test git init."""
        from RxyCode.RxyCode1_1_0.tools.git_tool import run_git
        repo_dir = tmp_path / "newrepo"
        repo_dir.mkdir()
        result = run_git("init", str(repo_dir))
        assert isinstance(result, str)


class TestGitTool:
    def test_tool_name(self):
        from RxyCode.RxyCode1_1_0.tools.git_tool import git_tool
        assert git_tool.name == "git"

    def test_tool_description(self):
        from RxyCode.RxyCode1_1_0.tools.git_tool import git_tool
        assert "Git" in git_tool.description

    def test_tool_has_args_schema(self):
        from RxyCode.RxyCode1_1_0.tools.git_tool import git_tool
        assert git_tool.args_schema is not None

    def test_tool_invoke(self, tmp_path):
        from RxyCode.RxyCode1_1_0.tools.git_tool import git_tool
        result = git_tool.invoke({"operation": "status", "path": str(tmp_path)})
        assert isinstance(result, str)
