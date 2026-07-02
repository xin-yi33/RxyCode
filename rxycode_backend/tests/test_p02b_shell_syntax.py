"""P0-2B Shell 语法混淆回归测试

用户反馈:
    Agent 在 bash 工具中使用了 PowerShell 语法:
        $desktopPath = Join-Path $env:USERPROFILE "Desktop"
    导致命令执行失败:
        '$desktop' 不是内部或外部命令,也不是可运行的程序或批处理文件。
        [exit code: 1]

回归测试: 确保 Shell 抽象层能检测并转换不兼容语法。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rxycode_backend.core.environment import ShellType, get_environment
from rxycode_backend.core.shell import ShellExecutor, ShellSyntaxError


class TestP02BShellSyntax(unittest.TestCase):
    """P0-2B: Shell 语法混淆回归测试"""

    def setUp(self):
        self.env = get_environment()
        self.executor = ShellExecutor(self.env)

    def test_detect_powershell_syntax_in_cmd(self):
        """回归: 检测 PowerShell 语法在 CMD 中的误用 (P0-2B 原始场景)"""
        # 这正是用户反馈的失败命令
        bad_command = '$desktopPath = Join-Path $env:USERPROFILE "Desktop"'
        issues = self.executor.validate_syntax(bad_command, ShellType.CMD)
        self.assertTrue(len(issues) > 0,
            f"未检测到 PowerShell 语法在 CMD 中的误用: {bad_command}")
        # 应检测到 $env: 和 Join-Path
        issues_text = " ".join(issues)
        self.assertIn("env", issues_text.lower())

    def test_detect_powershell_cmdlet(self):
        """回归: 检测 PowerShell cmdlet (Get-/Set-/Join-Path)"""
        issues = self.executor.validate_syntax("Join-Path A B", ShellType.CMD)
        self.assertTrue(any("cmdlet" in i or "Join-Path" in i for i in issues))

    def test_detect_dollar_variable_in_cmd(self):
        """回归: 检测 $ 变量在 CMD 中的误用"""
        issues = self.executor.validate_syntax("echo $HOME", ShellType.CMD)
        self.assertTrue(len(issues) > 0, "未检测到 $ 变量误用")

    def test_detect_dotnet_call_in_cmd(self):
        """回归: 检测 .NET 调用语法在 CMD 中的误用"""
        issues = self.executor.validate_syntax(
            "[Environment]::GetFolderPath('Desktop')", ShellType.CMD)
        self.assertTrue(len(issues) > 0, "未检测到 .NET 调用误用")

    def test_translate_cmd_percent_var_to_powershell(self):
        """回归: CMD %VAR% 转换为 PowerShell $env:VAR"""
        translated = self.executor.translate_command("echo %PATH%", ShellType.POWERSHELL)
        self.assertIn("$env:PATH", translated)
        self.assertNotIn("%PATH%", translated)

    def test_translate_powershell_env_to_bash(self):
        """回归: PowerShell $env:VAR 转换为 Bash $VAR"""
        translated = self.executor.translate_command("echo $env:HOME", ShellType.BASH)
        self.assertIn("$HOME", translated)
        self.assertNotIn("$env:", translated)

    def test_translate_cmd_percent_to_bash(self):
        """回归: CMD %VAR% 转换为 Bash $VAR"""
        translated = self.executor.translate_command("echo %PATH%", ShellType.BASH)
        self.assertIn("$PATH", translated)
        self.assertNotIn("%PATH%", translated)

    def test_cmd_incompatible_powershell_raises(self):
        """回归: 无法转换的 PowerShell 语法应抛异常而非执行"""
        with self.assertRaises(ShellSyntaxError):
            self.executor.translate_command(
                '$desktopPath = Join-Path $env:USERPROFILE "Desktop"',
                ShellType.CMD,
            )

    def test_execute_powershell_syntax_uses_powershell(self):
        """回归: PowerShell 语法命令应切换到 PowerShell 执行,而非在 CMD 中失败

        这是 P0-2B 的完整修复验证:
            旧代码: 在 CMD 中执行 PowerShell 语法 -> '$desktop' 不是内部命令
            新代码: 自动切换到 PowerShell -> 正确执行
        """
        # 这条命令在旧代码中会失败
        ps_command = "Write-Output 'hello-from-powershell'"
        result = self.executor.execute(ps_command, timeout=10)
        # 应该成功执行 (在 PowerShell 中)
        self.assertEqual(result.exit_code, 0,
            f"PowerShell 语法命令执行失败: {result.stderr}")
        self.assertIn("hello-from-powershell", result.stdout)

    def test_execute_simple_echo(self):
        """基础命令执行测试"""
        if self.env.is_windows:
            result = self.executor.execute("echo test-rxycode", timeout=10)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("test-rxycode", result.stdout)
        else:
            result = self.executor.execute("echo test-rxycode", timeout=10)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("test-rxycode", result.stdout)

    def test_execute_timeout_returns_error(self):
        """超时命令应返回明确错误,而非无限等待"""
        if self.env.is_windows:
            # Windows: ping 多次制造超时
            result = self.executor.execute(
                "powershell -Command \"Start-Sleep -Seconds 10\"", timeout=2)
        else:
            result = self.executor.execute("sleep 10", timeout=2)
        self.assertNotEqual(result.exit_code, 0,
            "超时命令不应返回成功")
        self.assertIn("超时", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
