"""P0-2A 工具执行超时回归测试

用户反馈:
    场景 2 (创建 hello.py) 中,write 工具执行超过 120 秒无响应,
    最终超时。文件创建这一最基础的功能完全不可用。

回归测试: 确保执行层有超时/重试/降级机制,工具不再无限等待。
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rxycode_backend.core.execution import (
    ExecutionEngine, EventType, ToolCall, ToolStatus, ToolResult,
)
from rxycode_backend.tools.base import reset_tool_registry, get_tool_registry
from rxycode_backend.tools.bash_tool import register_default_tools
from rxycode_backend.tools.write_tool import WriteTool
from rxycode_backend.tools.read_tool import ReadTool


class TestP02AToolTimeout(unittest.TestCase):
    """P0-2A: 工具执行超时与可靠性回归测试"""

    def setUp(self):
        reset_tool_registry()
        register_default_tools()
        self.engine = ExecutionEngine()
        # 重新注册到新引擎
        registry = get_tool_registry()
        for name in registry.list_tools():
            self.engine.register_tool(registry.get(name))
        self.tmpdir = tempfile.mkdtemp(prefix="rxycode_test_")

    def test_write_tool_default_timeout_is_15s(self):
        """回归: write 工具默认超时 15s (ADR-002),不再是 120s+"""
        tool = WriteTool()
        self.assertEqual(tool.default_timeout, 15,
            f"write 超时应为 15s,当前: {tool.default_timeout}")

    def test_read_tool_default_timeout_is_5s(self):
        """回归: read 工具默认超时 5s"""
        tool = ReadTool()
        self.assertEqual(tool.default_timeout, 5)

    def test_write_file_succeeds_within_timeout(self):
        """回归: 文件创建应在超时内成功完成 (修复 P0-2A 场景 2)"""
        test_file = os.path.join(self.tmpdir, "hello.py")
        content = "print('Hello World')\n\ndef add(a, b):\n    return a + b\n"

        call = self.engine.invoke("write", {
            "path": test_file,
            "content": content,
        }, timeout=15)

        # 验证: 应该成功,而不是超时
        self.assertEqual(call.status, ToolStatus.SUCCESS,
            f"文件创建失败: {call.status}, 事件: {[e.event_type.value for e in call.events]}")
        self.assertTrue(os.path.isfile(test_file),
            "文件实际未创建 - 执行层报告成功但文件不存在")
        with open(test_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), content)

    def test_write_completes_quickly(self):
        """回归: 简单文件写入应在 5s 内完成 (远低于 120s)"""
        test_file = os.path.join(self.tmpdir, "quick.py")
        start = time.time()
        call = self.engine.invoke("write", {
            "path": test_file,
            "content": "# quick test",
        }, timeout=15)
        elapsed = time.time() - start
        self.assertEqual(call.status, ToolStatus.SUCCESS)
        self.assertLess(elapsed, 5.0,
            f"写入耗时 {elapsed:.2f}s,应 <5s (旧代码 120s+ 超时)")

    def test_tool_call_has_event_stream(self):
        """回归: 工具调用应产生结构化事件流 (修复 P2-2/P2-3)"""
        test_file = os.path.join(self.tmpdir, "event_test.py")
        call = self.engine.invoke("write", {
            "path": test_file,
            "content": "# test",
        }, timeout=15)
        # 应有 TOOL_INVOKED 和 TOOL_SUCCEEDED 事件
        event_types = [e.event_type for e in call.events]
        self.assertIn(EventType.TOOL_INVOKED, event_types,
            "缺少 TOOL_INVOKED 事件")
        self.assertIn(EventType.TOOL_SUCCEEDED, event_types,
            "缺少 TOOL_SUCCEEDED 事件")

    def test_tool_summary_has_tool_name(self):
        """回归: 工具调用摘要应包含工具名 (修复 P2-2 'unknown')"""
        test_file = os.path.join(self.tmpdir, "summary_test.py")
        call = self.engine.invoke("write", {
            "path": test_file,
            "content": "# test",
        }, timeout=15)
        summary = call.to_summary()
        self.assertEqual(summary["tool"], "write",
            f"工具名应为 'write',当前: {summary['tool']}")

    def test_read_nonexistent_file_returns_immediately(self):
        """回归: 读取不存在文件应立即返回明确错误,而非超时 (修复 P0-2A 场景 3)"""
        nonexistent = os.path.join(self.tmpdir, "does_not_exist.py")
        call = self.engine.invoke("read", {"path": nonexistent}, timeout=5)
        # 应该快速失败,而不是超时
        self.assertNotEqual(call.status, ToolStatus.TIMEOUT,
            "读取不存在文件不应超时,应立即返回文件不存在错误")
        # 结果应包含 not_found 标记
        if call.result:
            self.assertTrue(
                call.result.extra.get("not_found") or "不存在" in call.result.output,
                "应明确返回文件不存在错误"
            )

    def test_write_degradation_outputs_content(self):
        """回归: 写入失败时应降级输出内容 (ADR-002 降级策略)"""
        # 用一个无效路径触发降级
        invalid_path = "/nonexistent_root_dir/cannot_write_here/file.py"
        call = self.engine.invoke("write", {
            "path": invalid_path,
            "content": "print('hello')",
        }, timeout=15, max_retries=0)  # 不重试,快速触发降级
        # 最终状态应为 DEGRADED 或 FAILED
        self.assertIn(call.status, [ToolStatus.DEGRADED, ToolStatus.FAILED])
        if call.status == ToolStatus.DEGRADED:
            # 降级输出应包含原始内容
            self.assertIn("print('hello')", call.result.output)

    def test_retry_mechanism_records_attempts(self):
        """回归: 重试机制应记录每次尝试"""
        tool = WriteTool()
        # 注册一个会失败的工具来测试重试
        class FailingTool:
            name = "failing"
            default_timeout = 2
            def execute(self, input, timeout=0):
                raise RuntimeError("模拟失败")
            def degrade(self, input, error):
                return ToolResult(output="降级输出", exit_code=0)

        self.engine.register_tool(FailingTool())
        call = self.engine.invoke("failing", {}, timeout=2, max_retries=2)
        # 应有 3 次尝试 (1 + 2 重试)
        self.assertEqual(len(call.attempts), 3,
            f"应有 3 次尝试,实际: {len(call.attempts)}")
        # 应有重试事件
        retry_events = [e for e in call.events if e.event_type == EventType.TOOL_RETRIED]
        self.assertEqual(len(retry_events), 2, "应有 2 次重试事件")

    def test_timeout_does_not_silently_succeed(self):
        """回归: 超时必须标记为 TIMEOUT,不可静默成功 (不变式 3)"""
        class SlowTool:
            name = "slow"
            default_timeout = 1
            def execute(self, input, timeout=0):
                time.sleep(10)  # 远超超时
                return ToolResult(output="不应到达这里", exit_code=0)
            def degrade(self, input, error):
                return ToolResult(output="降级", exit_code=0)

        self.engine.register_tool(SlowTool())
        call = self.engine.invoke("slow", {}, timeout=1, max_retries=0)
        # 必须有 TIMEOUT 状态的尝试,不能静默成功
        statuses = [a.status for a in call.attempts]
        self.assertIn(ToolStatus.TIMEOUT, statuses,
            f"超时必须标记为 TIMEOUT,当前状态: {statuses}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
