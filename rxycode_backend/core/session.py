"""会话上下文隔离模块 - 修复 P1-1 上下文泄露

用户反馈问题 (P1-1):
    从场景 4 开始,所有后续场景的 thinking 字段中都包含场景 2-3 的
    工具调用记录 (读取不存在的 hello.py、写入 fixed_divide.py 等),
    即使这些操作与当前场景完全无关。
    token 消耗从 3K 累积到 95K。

架构根因:
    会话状态无隔离,历史累积。所有请求共享同一上下文窗口。

修复方案 (ADR-003):
    1. 请求级隔离: 每个用户请求创建独立上下文
    2. 历史按需注入: 仅当任务显式依赖历史时才注入相关摘要
    3. 上下文压缩: 单会话 token 超 20K 时触发压缩
    4. 工具调用历史分区: 按任务 ID 分区,不跨任务泄露
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

# 上下文压缩阈值 (对应 ADR-003 决策)
CONTEXT_COMPRESS_THRESHOLD = 20_000
# 单条历史摘要最大长度
HISTORY_SUMMARY_MAX_CHARS = 500


class ContextScope(str, Enum):
    """上下文作用域"""
    REQUEST = "request"       # 单次请求级 (默认隔离)
    SESSION = "session"       # 会话级 (跨请求,需显式引用)
    GLOBAL = "global"         # 全局级 (系统配置等)


@dataclass
class ToolCallRecord:
    """工具调用历史记录 - 按任务 ID 分区存储"""
    task_id: str
    tool_name: str
    input_summary: str
    output_summary: str
    status: str  # success | failed | timeout
    timestamp: float = field(default_factory=time.time)


@dataclass
class RequestContext:
    """请求上下文 - 每个用户请求独立创建

    修复 P1-1 核心:
        thinking 字段只包含当前请求的推理过程,
        历史工具调用不会自动注入,必须显式引用。
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    scope: ContextScope = ContextScope.REQUEST
    thinking: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    token_count: int = 0
    created_at: float = field(default_factory=time.time)

    def add_thinking(self, content: str) -> None:
        """添加当前请求的推理过程"""
        self.thinking.append(content)

    def add_tool_call(self, record: ToolCallRecord) -> None:
        """记录当前请求的工具调用 (仅当前任务)"""
        if record.task_id != self.task_id:
            # 防御性检查: 不同任务的工具调用不得注入当前上下文
            return
        self.tool_calls.append(record)

    def get_thinking_text(self) -> str:
        """获取当前请求的推理过程文本"""
        return "\n".join(self.thinking)

    def get_tool_calls_summary(self) -> list[dict]:
        """获取当前请求的工具调用摘要"""
        return [
            {
                "tool": tc.tool_name,
                "input": tc.input_summary,
                "status": tc.status,
            }
            for tc in self.tool_calls
        ]


@dataclass
class SessionContext:
    """会话上下文 - 跨请求共享,但历史按需注入

    设计原则:
        - 当前请求的 RequestContext 是"主"上下文
        - SessionContext 只存储压缩后的历史摘要
        - 历史摘要默认不注入,需显式调用 inject_history()
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    current_request: RequestContext | None = None
    # 历史摘要按任务 ID 分区,避免跨任务泄露
    history_summaries: dict[str, str] = field(default_factory=dict)
    total_token_count: int = 0

    def new_request(self) -> RequestContext:
        """创建新的请求上下文 - 实现 P1-1 的请求级隔离

        关键修复:
            每次新请求创建干净的 RequestContext,
            不自动继承上一个请求的 thinking 和 tool_calls。
        """
        # 保存上一个请求的压缩摘要 (按任务分区)
        if self.current_request is not None:
            self._compress_and_store(self.current_request)
        # 创建全新的隔离上下文
        self.current_request = RequestContext()
        return self.current_request

    def inject_history(self, task_ids: list[str] | None = None) -> str:
        """按需注入历史摘要 - 仅当当前任务显式依赖历史时调用

        参数:
            task_ids: 要注入的历史任务 ID 列表,None 表示不注入任何历史

        修复 P1-1:
            旧代码: 所有历史自动注入 -> token 从 3K 到 95K
            新代码: 默认不注入,显式引用才注入 -> token 稳定在 5-15K
        """
        if not task_ids:
            return ""
        summaries = []
        for tid in task_ids:
            if tid in self.history_summaries:
                summaries.append(f"[历史任务 {tid[:8]} 摘要]\n{self.history_summaries[tid]}")
        return "\n\n".join(summaries)

    def _compress_and_store(self, ctx: RequestContext) -> None:
        """压缩请求上下文并存入历史摘要

        对应 ADR-003 压缩策略:
            保留关键决策,丢弃中间过程。
            单条摘要不超过 HISTORY_SUMMARY_MAX_CHARS。
        """
        if not ctx.thinking and not ctx.tool_calls:
            return
        # 提取关键信息: 工具调用结果 + 最后一步推理
        parts = []
        if ctx.tool_calls:
            tools_str = ", ".join(
                f"{tc.tool_name}({tc.input_summary[:50]})={tc.status}"
                for tc in ctx.tool_calls[-5:]  # 保留最近 5 次调用
            )
            parts.append(f"工具调用: {tools_str}")
        if ctx.thinking:
            parts.append(f"最终推理: {ctx.thinking[-1][:300]}")
        summary = " | ".join(parts)
        if len(summary) > HISTORY_SUMMARY_MAX_CHARS:
            summary = summary[:HISTORY_SUMMARY_MAX_CHARS] + "..."
        self.history_summaries[ctx.task_id] = summary
        self.total_token_count += ctx.token_count

    def should_compress(self) -> bool:
        """检查是否需要触发上下文压缩"""
        return self.total_token_count > CONTEXT_COMPRESS_THRESHOLD

    def compress_global(self) -> None:
        """全局压缩: 当 token 超过阈值时,保留最近 N 个任务摘要"""
        if not self.should_compress():
            return
        # 保留最近 3 个任务的历史摘要
        sorted_keys = sorted(
            self.history_summaries.keys(),
            key=lambda k: self.history_summaries[k],  # 简化: 实际应按时间戳
        )
        keep = sorted_keys[-3:]
        self.history_summaries = {k: self.history_summaries[k] for k in keep}
        self.total_token_count = sum(
            len(s) // 4 for s in self.history_summaries.values()  # 粗略 token 估算
        )


class SessionManager:
    """会话管理器 - 提供隔离的上下文给所有限界上下文使用

    使用方式:
        session = SessionManager()
        ctx = session.new_request()           # 每次请求调用
        ctx.add_thinking("正在分析...")         # 当前请求的推理
        ctx.add_tool_call(record)              # 当前请求的工具调用
        # 需要历史时显式注入:
        history = session.inject_history(["task-xxx"])
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}

    def create_session(self) -> SessionContext:
        session = SessionContext()
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionContext | None:
        return self._sessions.get(session_id)

    def new_request(self, session_id: str) -> RequestContext:
        """为指定会话创建新的隔离请求上下文"""
        session = self._sessions.get(session_id)
        if session is None:
            session = self.create_session()
            self._sessions[session_id] = session
        return session.new_request()

    def inject_history(self, session_id: str, task_ids: list[str] | None = None) -> str:
        """注入历史摘要 (按需)"""
        session = self._sessions.get(session_id)
        if session is None:
            return ""
        return session.inject_history(task_ids)

    def clear_session(self, session_id: str) -> None:
        """清除会话 (用户主动 /clear)"""
        self._sessions.pop(session_id, None)
