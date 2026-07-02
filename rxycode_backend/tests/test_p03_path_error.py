"""P0-3 路径错误回归测试

用户反馈:
    Agent 报告桌面路径为 C:\\Users\\RxyCode\\Desktop,但实际测试环境
    用户名为 Administrator,正确路径应为 C:\\Users\\Administrator\\Desktop。
    Agent 疑似使用了进程运行身份 (RxyCode) 而非当前登录用户的身份来推断路径。

回归测试: 确保环境探测使用登录用户身份,而非进程身份。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rxycode_backend.core.environment import (
    EnvironmentDetector, EnvironmentInfo, OSName, ShellType, get_environment,
)


class TestP03PathError(unittest.TestCase):
    """P0-3: 路径错误与用户身份混淆回归测试"""

    def setUp(self):
        self.env = get_environment()

    def test_username_is_not_process_identity(self):
        """回归: 用户名不应是进程身份 (RxyCode),应为登录用户"""
        # P0-3 核心: 旧代码返回 RxyCode,新代码应返回真实登录用户
        username = self.env.username
        self.assertNotEqual(username, "RxyCode",
            f"用户名仍为进程身份 RxyCode,P0-3 未修复。当前: {username}")
        self.assertTrue(len(username) > 0, "用户名不能为空")

    def test_desktop_path_uses_real_username(self):
        """回归: 桌面路径应使用真实用户名,不是 RxyCode"""
        desktop = self.env.desktop_path
        self.assertNotIn("RxyCode", desktop,
            f"桌面路径包含 RxyCode,P0-3 未修复。路径: {desktop}")
        # Windows 上应包含 Administrator 或真实用户名
        if self.env.is_windows:
            # 路径应包含当前用户名
            self.assertIn(self.env.username, desktop,
                f"桌面路径应包含用户名 {self.env.username}。路径: {desktop}")

    def test_desktop_path_directory_exists(self):
        """回归: 探测到的桌面路径必须真实存在"""
        # 旧代码拼接路径可能指向不存在的位置
        self.assertTrue(
            os.path.isdir(self.env.desktop_path),
            f"桌面路径不存在: {self.env.desktop_path}"
        )

    def test_path_resolution_does_not_concat_username(self):
        """回归: 路径解析不应拼接用户名,应用系统 API"""
        # 测试 ~ 展开
        resolved = self.env.resolve_path("~/test.py")
        self.assertTrue(resolved.startswith(self.env.home_path),
            f"~ 展开错误: {resolved}, 应以 {self.env.home_path} 开头")
        self.assertNotIn("RxyCode", resolved,
            f"路径解析仍包含 RxyCode: {resolved}")

    def test_desktop_keyword_resolution(self):
        """回归: Windows 上 'desktop' 关键词应解析到真实桌面"""
        if not self.env.is_windows:
            self.skipTest("仅 Windows 测试")
        resolved = self.env.resolve_path("desktop")
        self.assertEqual(resolved, self.env.desktop_path,
            f"desktop 关键词解析错误: {resolved}")

    def test_environment_info_is_immutable(self):
        """环境信息不可变,防止运行中被篡改"""
        with self.assertRaises((AttributeError, Exception)):
            try:
                self.env.username = "tampered"
            except AttributeError:
                pass
            else:
                # frozen dataclass 应抛 FrozenInstanceError (AttributeError 子类)
                self.fail("EnvironmentInfo 应为不可变对象")

    def test_environment_singleton_consistency(self):
        """全局环境信息单例一致性"""
        env2 = get_environment()
        self.assertEqual(self.env.username, env2.username)
        self.assertEqual(self.env.desktop_path, env2.desktop_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
