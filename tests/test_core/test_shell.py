"""
Tests for utils/shell.py - Shell command execution and translation.
"""
import sys
import pytest
from unittest.mock import patch, MagicMock

# These tests verify Windows command translation (powershell/cmd mapping).
# ShellExecutor reads sys.platform at construction time, and the module-level
# import caches the reference, making standard unittest.mock.patch unreliable
# across process boundaries (pytest-xdist workers).  Skip the entire class
# on non-Windows runners rather than fighting the patching mechanics.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-only shell translation tests",
)


class TestShellExecutor:
    def _make_executor(self, platform: str = "win32"):
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

    def test_version_probe_uses_cmd_native_exit_code_on_windows(self):
        executor = self._make_executor()
        translated, shell = executor.translate_command("java -version 2>&1")

        assert shell == "powershell"
        assert 'cmd.exe /d /c "java -version 2>&1"' in translated

    def test_translates_recursive_ls_and_cmd_ver(self):
        executor = self._make_executor()
        translated, shell = executor.translate_command("ls -laR . && ver")

        assert shell == "powershell"
        assert "Get-ChildItem -Force -Recurse ." in translated
        assert "cmd.exe /d /c ver" in translated

    def test_translates_compound_find_directory_and_batch_directory_variable(self):
        executor = self._make_executor()
        translated, shell = executor.translate_command(
            'cd /d "%~dp0" 2>nul & ls -la; find . -type d'
        )

        assert shell == "powershell"
        assert "%~dp0" not in translated
        assert "Get-ChildItem -Force" in translated
        assert "Get-ChildItem -Path . -Recurse -Directory" in translated

    def test_translates_maxdepth_find_and_rm_rf(self):
        executor = self._make_executor()
        translated, shell = executor.translate_command(
            "find . -maxdepth 3 -type d 2>/dev/null; rm -rf bin"
        )

        assert shell == "powershell"
        assert "Get-ChildItem -Path . -Recurse -Directory" in translated
        assert "Remove-Item -Recurse -Force -LiteralPath bin" in translated

    def test_translates_windows_environment_probes(self):
        executor = self._make_executor()
        translated, shell = executor.translate_command(
            "where java; uname -a; find . -maxdepth 3 -type d -iname 'bin'"
        )

        assert shell == "powershell"
        assert "Get-Command java" in translated
        assert "Get-Command chrome,2" not in executor.translate_command("where chrome 2>&1")[0]
        assert "Get-Command chrome" in executor.translate_command("where chrome 2>&1")[0]
        assert "2>&1" in executor.translate_command("where chrome 2>&1")[0]
        assert "[Environment]::OSVersion.VersionString" in translated
        assert "Get-ChildItem -Path . -Recurse -Directory -Filter 'bin'" in translated

    def test_keeps_native_version_stderr_inside_cmd(self):
        executor = self._make_executor()
        translated, shell = executor.translate_command(
            'java -version 2>&1; cmd /c "javac -version" 2>&1'
        )

        assert shell == "powershell"
        assert 'cmd.exe /d /c "java -version 2>&1"' in translated
        assert 'cmd.exe /d /c "javac -version 2>&1"' in translated
        assert translated.count("2>&1") == 2

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

    def test_powershell_translates_posix_ls_flags(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("ls -la")
        assert shell == "powershell"
        assert "Get-ChildItem -Force" in cmd

        cmd2, _ = executor.translate_command("pwd && ls -l")
        assert "Get-ChildItem" in cmd2
        assert "ls -l" not in cmd2

        one_col, _ = executor.translate_command("pwd && ls -1 | head -20")
        assert "Get-ChildItem" in one_col
        assert "ls -1" not in one_col
        assert "Select-Object -First 20" in one_col

    def test_powershell_translates_posix_grep(self):
        """POSIX grep → Select-String（B7：模型高频输出 grep 语法）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command('grep -n "add_node" core/graph.py')
        assert shell == "powershell"
        assert "Select-String" in cmd
        assert "grep" not in cmd
        assert "core/graph.py" in cmd

    def test_powershell_translates_posix_cat(self):
        """POSIX cat → Get-Content（B7）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("cat counter.py")
        assert shell == "powershell"
        assert "Get-Content" in cmd
        assert "cat " not in cmd

    def test_powershell_translates_dev_null_redirect(self):
        """POSIX 2>/dev/null → 2>$null（B7，现有只覆盖 2>nul）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("ls test.py 2>/dev/null")
        assert shell == "powershell"
        assert "2>/dev/null" not in cmd
        assert "2>$null" in cmd

    def test_powershell_translates_pwd(self):
        """POSIX pwd → Get-Location（B7）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("pwd")
        assert shell == "powershell"
        assert "Get-Location" in cmd

    def test_powershell_translates_or_fallback(self):
        """POSIX || → 失败分支（B7：cmd1 || cmd2 语义）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("cat x.py || echo missing")
        assert shell == "powershell"
        assert "||" not in cmd
        assert "echo missing" in cmd

        chained, _ = executor.translate_command(
            'cmd.exe /d /c "mvn -version 2>&1" || echo mvn-missing || echo still-missing'
        )
        assert "||" not in chained
        assert chained.count("if (-not $?)") == 2

    def test_powershell_translates_posix_find(self):
        """POSIX find -name → Get-ChildItem -Recurse -Filter（B7）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command('find . -name "graph.py"')
        assert shell == "powershell"
        assert "Get-ChildItem" in cmd
        assert "-Recurse" in cmd
        assert "graph.py" in cmd

    def test_powershell_translates_find_type_file(self):
        """POSIX ``find . -type f`` must not invoke Windows ``find.exe``."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("find . -type f")
        assert shell == "powershell"
        assert "find" not in cmd.lower()
        assert "Get-ChildItem" in cmd
        assert "-Recurse" in cmd
        assert "-File" in cmd

    def test_powershell_translates_posix_mkdir_p(self):
        """Agent-created directories must work on Windows PowerShell."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command('mkdir -p "src/main" tests')
        assert shell == "powershell"
        assert "mkdir -p" not in cmd.lower()
        assert "New-Item" in cmd
        assert "-ItemType Directory" in cmd
        assert "-Force" in cmd
        assert "src/main" in cmd
        assert "tests" in cmd

        mixed_flags, _ = executor.translate_command(
            "mkdir -p -Force T05-number-bomb\\src"
        )
        assert "-Force, T05" not in mixed_flags
        assert "T05-number-bomb\\src" in mixed_flags

        chained, _ = executor.translate_command("mkdir -p build && echo ready")
        assert "echo ready" in chained
        assert "&&" not in chained
        assert "New-Item" in chained

        plain, _ = executor.translate_command(
            r"mkdir T05-number-bomb\src T05-number-bomb\bin"
        )
        assert "mkdir" not in plain.lower()
        assert "New-Item -ItemType Directory -Force -Path" in plain
        assert r"T05-number-bomb\src" in plain
        assert r"T05-number-bomb\bin" in plain

    def test_powershell_translates_posix_which(self):
        """POSIX ``which`` must resolve tools through PowerShell."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("which java javac")
        assert shell == "powershell"
        assert "which" not in cmd.lower()
        assert "Get-Command" in cmd
        assert "java,javac" in cmd

    def test_powershell_translates_recursive_cmd_dir_listing(self):
        """Compile scripts using ``dir /s /b`` must work in PowerShell."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command(r"dir /s /b out\classes\*.class")
        assert shell == "powershell"
        assert "dir" not in cmd.lower()
        assert "Get-ChildItem -Path out\\classes\\*.class -Recurse -Name" in cmd

        flat, _ = executor.translate_command(r"dir /b out\classes\*.class")
        assert "Get-ChildItem -Path out\\classes\\*.class -Name" in flat

        trailing, _ = executor.translate_command(r"dir out\classes\*.class /b")
        assert "Get-ChildItem -Path out\\classes\\*.class -Name" in trailing

    def test_powershell_translates_posix_wc_line_count(self):
        """POSIX ``wc -l`` must remain a scalar line-count check on Windows."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command(r"wc -l T05-number-bomb\src\NumberBomb.java")
        assert shell == "powershell"
        assert "wc" not in cmd.lower()
        assert "Measure-Object -Line" in cmd
        assert "Select-Object -ExpandProperty Lines" in cmd

    def test_powershell_mkdir_does_not_consume_stderr_redirection(self):
        """mkdir followed by ``2>&1`` must remain valid PowerShell syntax."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command("mkdir T05-number-bomb 2>&1; echo done")
        assert "-Path T05-number-bomb" in cmd
        assert "-Path T05-number-bomb, 2" not in cmd
        assert "2>&1" not in cmd

    def test_powershell_translates_find_directory_iname(self):
        """find directory probes must not invoke the Windows find.exe."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command('find . -type d -iname "*T05*" 2>/dev/null')
        assert shell == "powershell"
        assert "find" not in cmd.lower()
        assert "-Directory" in cmd
        assert "-Filter '*T05*'" in cmd

    def test_powershell_maps_container_workspace_to_current_workspace(self):
        """The synthetic /workspace path is the session cwd on the host."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command("cd /workspace && pwd")
        assert shell == "powershell"
        assert "C:\\workspace" not in cmd
        assert "Set-Location ." in cmd
        assert "Get-Location" in cmd

    def test_powershell_translates_grep_rl(self):
        """POSIX grep -rl → Select-String 递归（B7）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command('grep -rl "goal_planner" core/')
        assert shell == "powershell"
        assert "Select-String" in cmd
        assert "-Recurse" in cmd
        assert "goal_planner" in cmd

    def test_powershell_translate_does_not_touch_quoted_text(self):
        """引号内的普通文本（echo 输出等）不被转换误改（luna R1）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command('echo "pwd && cat readme"')
        assert shell == "powershell"
        # 引号内的 pwd/cat 不应被转换为 Get-Location/Get-Content
        assert "Get-Location" not in cmd
        assert "Get-Content" not in cmd

    def test_powershell_translate_quoted_redirect_and_or(self):
        """引号内的 2>/dev/null 与 || 不被转换（luna R2）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command('echo "2>/dev/null"')
        assert '"2>/dev/null"' in cmd

        cmd2, _ = executor.translate_command('echo "a || b"')
        assert '"a || b"' in cmd2
        assert "if (-not" not in cmd2

        cmd3, _ = executor.translate_command('echo "x; pwd"')
        assert '"x; pwd"' in cmd3
        assert "Get-Location" not in cmd3

    def test_powershell_translate_unclosed_quote_protected(self):
        """未闭合引号后的文本不受转换（luna R3-1）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command('echo "2>/dev/null')
        assert '"2>/dev/null' in cmd
        assert "2>$null" not in cmd

    def test_powershell_translate_escaped_quote_protected(self):
        """转义引号不结束保护范围（luna R3-2）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command(r'echo "a \" 2>/dev/null"')
        assert "2>/dev/null" in cmd
        assert "2>$null" not in cmd

    def test_powershell_translate_grep_multiple_files(self):
        """grep 多文件参数不丢失（luna R3-4）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command('grep -n "pat" file1 file2')
        assert "file1" in cmd
        assert "file2" in cmd

    def test_powershell_translate_or_then_pwd(self):
        """|| 分支内的 pwd 也转换（luna R3-5）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command("echo x || pwd")
        assert "if (-not $?)" in cmd
        assert "Get-Location" in cmd

    def test_powershell_translate_grep_after_cd_chain(self):
        """cd && grep 链中 grep 也转换（B8：; 后位置）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command(
            r'cd "D:\x" && grep -n "class UsageTrackingLLM" core/agent_v2.py'
        )
        assert "Select-String" in cmd
        assert "grep" not in cmd

    def test_powershell_translate_grep_after_semicolon(self):
        """echo x; grep 链中 grep 也转换（B8）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command('echo hi; grep -n "x" f.py')
        assert "Select-String" in cmd

    def test_powershell_translate_grep_pattern_safe_quoting(self):
        """grep pattern 用 PS 单引号包裹，$ 不展开、引号/反引号保留（luna R4-1）。"""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, _ = executor.translate_command("grep '$HOME' file")
        assert "Select-String -Pattern '$HOME'" in cmd

        cmd2, _ = executor.translate_command("grep 'a\"b' file")
        assert "'a\"b'" in cmd2

        cmd3, _ = executor.translate_command("grep 'a`nb' file")
        assert "'a`nb'" in cmd3

    def test_powershell_translates_ampersand_separators(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command(
            "python a.py X & echo --- & python a.py Y"
        )
        assert shell == "powershell"
        assert cmd == "python a.py X; echo ---; python a.py Y"

        # Call-operator `& 'path'` must be preserved.
        call_op, _ = executor.translate_command("& 'C:\\Program Files\\app.exe' --help")
        assert call_op.startswith("& '")
        assert "; " not in call_op

    def test_powershell_translates_cmd_dir_and_redirects(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"

        bare, _ = executor.translate_command('dir /b "C:\\Users\\Administrator\\.rxycode\\skills"')
        assert bare == 'Get-ChildItem -Path "C:\\Users\\Administrator\\.rxycode\\skills" -Name'

        bare_short, _ = executor.translate_command("dir /b")
        assert bare_short == "Get-ChildItem -Name"

        flag_after, _ = executor.translate_command('dir "C:\\tools" /b')
        assert flag_after == 'Get-ChildItem -Path "C:\\tools" -Name'

        nul, _ = executor.translate_command("python run.py 2>nul")
        assert nul == "python run.py 2>$null"

    def test_powershell_runs_mysql_through_cmd(self):
        """mysql stderr warnings and SQL semicolons must not fail the bash tool."""
        executor = self._make_executor()
        executor.shell_type = "powershell"
        cmd, shell = executor.translate_command(
            r'"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u rxycode_t09 --password=secret -e "SELECT CURRENT_USER(); SHOW DATABASES;"'
        )
        assert shell == "powershell"
        assert "cmd.exe /d /c" in cmd
        assert "ErrorActionPreference" in cmd
        assert "SELECT CURRENT_USER(); SHOW DATABASES;" in cmd
        assert "mysql.exe" in cmd

    def test_powershell_does_not_wrap_mysql_env_or_get_command(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"
        env_probe, _ = executor.translate_command(
            'Get-ChildItem Env: | Where-Object { $_.Name -like "MYSQL*" -or $_.Name -like "SPRING*" }'
        )
        assert "cmd.exe" not in env_probe
        assert "Get-ChildItem Env:" in env_probe

        which, _ = executor.translate_command(
            "Get-Command mysql,mysqld,mvn -ErrorAction SilentlyContinue"
        )
        assert "cmd.exe" not in which
        assert "Get-Command mysql" in which

        echo_env, _ = executor.translate_command('echo "URL=$MYSQL_URL"')
        assert "cmd.exe" not in echo_env

    def test_powershell_translates_head_tail_pipes(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"

        head_n, _ = executor.translate_command("curl -s https://x.test | head -50")
        assert head_n == "curl -s https://x.test | Select-Object -First 50"

        head_short, _ = executor.translate_command("python -c \"print(1)\" | head -3")
        assert head_short == "python -c \"print(1)\" | Select-Object -First 3"

        tail_n, _ = executor.translate_command("Get-Content out.txt | tail -n 4")
        assert tail_n == "Get-Content out.txt | Select-Object -Last 4"

    def test_powershell_heredoc_translates_head_with_cmd_chain(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"
        heredoc = (
            "cd /d D:\\repo && python - <<'PY'\n"
            "import os\n"
            "print('ok')\n"
            "PY"
        )
        cmd, shell = executor.translate_command(heredoc)
        assert shell == "powershell"
        assert "Set-Location" in cmd
        assert "python -c" in cmd
        assert "@'" in cmd
        assert "&&" not in cmd

    def test_powershell_translates_posix_heredoc(self):
        executor = self._make_executor()
        executor.shell_type = "powershell"
        heredoc = (
            "python - <<'PY'\n"
            "import os\n"
            "print('hello', os.name)\n"
            "PY"
        )
        cmd, shell = executor.translate_command(heredoc)
        assert shell == "powershell"
        assert "python -c" in cmd
        assert "@'" in cmd
        assert "import os" in cmd
        assert "<<" not in cmd
        assert "'PY'" not in cmd

        # A plain command without heredoc must not be altered.
        plain, shell2 = executor.translate_command("python --version")
        assert shell2 == "powershell"
        assert "python --version" in plain

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
