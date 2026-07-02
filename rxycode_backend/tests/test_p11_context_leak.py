"""P1-1 上下文泄露回归测试

用户反馈:
    从场景 4 开始,所有后续场景的 thinking 字段中都包含场景 2-3 的
    工具调用记录 (读取不存在的 hello.py、写入 fixed_divide.py 等),
    即使这些操作与当前场景完全无关。token 从 3K 累积到 95K。

回归测试: 确保请求级隔离和按需注入机制生效。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rxycode_backend.core.session import (
    ContextScope, RequestContext, SessionContext, SessionManager,
    ToolCallRecord, CONTEXT_COMPRESS_THRESHOLD,
)


class TestP11ContextLeak(unittest.TestCase):
    """P1-1: 上下文泄露回归测试"""

    def setUp(self):
        self.manager = SessionManager()
        self.session_id = "test-session-001"

    def test_new_request_isolates_thinking(self):
        """回归: 新请求的 thinking 不应继承上一个请求"""
        # 第一个请求
        ctx1 = self.manager.new_request(self.session_id)
        ctx1.add_thinking("场景 2: 正在创建 hello.py")
        ctx1.add_tool_call(ToolCallRecord(
            task_id=ctx1.task_id, tool_name="write",
            input_summary="hello.py", output_summary="success", status="success",
        ))

        # 第二个请求 (应隔离)
        ctx2 = self.manager.new_request(self.session_id)
        ctx2.add_thinking("场景 4: 正在修复 bug")

        # ctx2 的 thinking 不应包含 ctx1 的内容
        thinking_text = ctx2.get_thinking_text()
        self.assertNotIn("hello.py", thinking_text,
            "新请求 thinking 泄露了上一个请求的内容 (P1-1 未修复)")
        self.assertIn("场景 4", thinking_text)

    def test_tool_calls_isolated_by_task(self):
        """回归: 工具调用按任务 ID 分区,不跨任务泄露"""
        ctx1 = self.manager.new_request(self.session_id)
        ctx1.add_tool_call(ToolCallRecord(
            task_id=ctx1.task_id, tool_name="write",
            input_summary="fixed_divide.py", output_summary="ok", status="success",
        ))

        ctx2 = self.manager.new_request(self.session_id)
        # 尝试注入 ctx1 的工具调用到 ctx2 (应被拒绝)
        ctx2.add_tool_call(ToolCallRecord(
            task_id=ctx1.task_id,  # 不同任务 ID
            tool_name="write",
            input_summary="fixed_divide.py", output_summary="ok", status="success",
        ))

        # ctx2 不应包含 ctx1 的工具调用
        tool_summaries = ctx2.get_tool_calls_summary()
        self.assertEqual(len(tool_summaries), 0,
            "不同任务的工具调用不应注入当前上下文")

    def test_history_not_auto_injected(self):
        """回归: 历史摘要默认不注入,需显式引用 (ADR-003)"""
        ctx1 = self.manager.new_request(self.session_id)
        ctx1.add_thinking("正在创建 hello.py")
        ctx1.add_tool_call(ToolCallRecord(
            task_id=ctx1.task_id, tool_name="write",
            input_summary="hello.py", output_summary="ok", status="success",
        ))
        old_task_id = ctx1.task_id

        # 新请求
        ctx2 = self.manager.new_request(self.session_id)
        # 默认不注入历史
        history = self.manager.inject_history(self.session_id, task_ids=None)
        self.assertEqual(history, "",
            "历史应默认不注入,需显式引用 task_ids")

        # 显式注入才返回历史摘要
        history = self.manager.inject_history(self.session_id, task_ids=[old_task_id])
        self.assertIn("hello.py", history,
            "显式引用时应注入历史摘要")

    def test_token_count_does_not_accumulate_infinitely(self):
        """回归: token 不应无限累积 (从 3K 到 95K 的问题)"""
        session = self.manager._sessions[self.session_id]
        # 模拟多个请求
        for i in range(10):
            ctx = self.manager.new_request(self.session_id)
            ctx.add_thinking(f"场景 {i}: " + "x" * 1000)
            ctx.token_count = 5000

        # token 应有累积,但可通过压缩控制
        self.assertGreater(session.total_token_count, 0)
        # 触发压缩
        if session.should_compress():
            session.compress_global()
            # 压缩后 token 应受控
            self.assertLess(
                session.total_token_count, CONTEXT_COMPRESS_THRESHOLD * 2,
                "压缩后 token 应受控"
            )

    def test_request_context_scope(self):
        """请求上下文作用域应为 REQUEST (隔离)"""
        ctx = self.manager.new_request(self.session_id)
        self.assertEqual(ctx.scope, ContextScope.REQUEST)

    def test_clear_session_removes_history(self):
        """清除会话应移除所有历史"""
        ctx = self.manager.new_request(self.session_id)
        ctx.add_thinking("test")
        self.manager.clear_session(self.session_id)
        session = self.manager.get_session(self.session_id)
        self.assertIsNone(session, "会话应被清除")

    def test_independent_sessions_do_not_leak(self):
        """不同会话之间不应泄露上下文"""
        ctx_a = self.manager.new_request("session-A")
        ctx_a.add_thinking("会话 A 的内容")

        ctx_b = self.manager.new_request("session-B")
        ctx_b.add_thinking("会话 B 的内容")

        self.assertNotIn("会话 A", ctx_b.get_thinking_text(),
            "会话 B 泄露了会话 A 的内容")
        self.assertNotIn("会话 B", ctx_a.get_thinking_text(),
            "会话 A 泄露了会话 B 的内容")


if __name__ == "__main__":
    unittest.main(verbosity=2)
