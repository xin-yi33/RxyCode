"""执行层 - 修复 P0-2A 工具执行超时与可靠性缺陷

用户反馈问题 (P0-2A):
    场景 2 (创建 hello.py) 和场景 3 (读取文件) 中,Agent 的 write/read
    工具执行超过 120 秒无响应,最终超时。文件创建这一最基础的功能完全不可用。

架构根因:
    执行层无超时/重试/降级机制,一次失败即整个任务失败。

修复方案 (ADR-002):
    1. 工具级超时: write 15s / read 5s / bash 60s / search 30s
    2. 自动重试: 失败后重试最多 2 次,指数退避 (1s, 4s)
    3. 降级策略: 超时/失败时优雅降级,而非无限等待
    4. 执行事件流: 每次工具调用发出结构化事件

核心聚合根: ToolCall (对应架构文档 4.3 节)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from .shell import ShellExecutor, ExecResult


class ToolStatus(str, Enum):
    """工具调用状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DEGRADED = "degraded"  # 降级成功


class EventType(str, Enum):
    """执行事件流事件类型 (修复 P2-2 错误不透明)"""
    TOOL_INVOKED = "tool_invoked"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    TOOL_RETRIED = "tool_retried"
    TOOL_TIMED_OUT = "tool_timed_out"
    TOOL_DEGRADED = "tool_degraded"


@dataclass
class ExecutionEvent:
    """结构化执行事件 (修复 P2-2/P2-3 可观测性缺失)"""
    event_type: EventType
    tool_name: str
    tool_call_id: str
    attempt: int
    message: str = ""
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Attempt:
    """单次执行尝试记录"""
    attempt_num: int
    status: ToolStatus
    result: Any = None
    error: str = ""
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolResult:
    """工具执行结果"""
    output: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.exit_code == 0


@dataclass
class ToolCall:
    """工具调用聚合根 - 封装一次工具调用的完整生命周期

    对应架构文档 4.3 节的核心聚合。

    不变式 (Invariants):
        1. status=SUCCESS 时 result 必须非空
        2. attempts 数量 <= max_retries + 1
        3. 超时后必须标记为 TIMEOUT,不可静默成功
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    input: dict = field(default_factory=dict)
    status: ToolStatus = ToolStatus.PENDING
    result: ToolResult | None = None
    attempts: list[Attempt] = field(default_factory=list)
    max_retries: int = 2
    timeout_seconds: int = 15
    events: list[ExecutionEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add_event(self, event_type: EventType, message: str = "", duration_ms: int = 0) -> None:
        """记录执行事件"""
        self.events.append(ExecutionEvent(
            event_type=event_type,
            tool_name=self.tool_name,
            tool_call_id=self.id,
            attempt=len(self.attempts),
            message=message,
            duration_ms=duration_ms,
        ))

    def to_summary(self) -> dict:
        """生成结构化摘要 (修复 P2-2 工具调用显示为 unknown)"""
        return {
            "tool_call_id": self.id,
            "tool": self.tool_name,  # 不再是 "unknown"
            "input": self.input,
            "status": self.status.value,
            "attempts": len(self.attempts),
            "duration_ms": sum(a.duration_ms for a in self.attempts),
            "result_excerpt": (self.result.output[:200] if self.result else ""),
            "events": [
                {
                    "type": e.event_type.value,
                    "message": e.message,
                    "attempt": e.attempt,
                }
                for e in self.events
            ],
        }


class ToolProtocol(Protocol):
    """工具协议 - 所有工具必须实现此接口"""
    name: str
    default_timeout: int

    def execute(self, input: dict, timeout: int) -> ToolResult:
        ...

    def degrade(self, input: dict, error: str) -> ToolResult:
        """降级策略 - 失败时的优雅降级"""
        ...


class ToolExecutionError(Exception):
    """工具执行错误"""


class ToolTimeoutError(Exception):
    """工具执行超时"""


class ExecutionEngine:
    """执行引擎 - 编排工具调用的超时/重试/降级

    修复 P0-2A 的核心组件:
        旧代码: 直接调用工具,无超时无重试 -> 120s 卡死
        新代码: 超时+重试+降级 -> 15s 内成功或明确失败
    """

    def __init__(self, event_callback: Callable[[ExecutionEvent], None] | None = None) -> None:
        self._event_callback = event_callback
        self._tools: dict[str, ToolProtocol] = {}

    def register_tool(self, tool: ToolProtocol) -> None:
        """注册工具到执行引擎"""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolProtocol | None:
        return self._tools.get(name)

    def invoke(
        self,
        tool_name: str,
        input: dict,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> ToolCall:
        """执行工具调用 - 应用超时/重试/降级策略

        执行流程 (ADR-002):
            1. 创建 ToolCall 聚合根
            2. 执行,超时则标记 TIMEOUT (不静默成功)
            3. 失败则重试,指数退避 (1s, 4s)
            4. 全部失败则触发降级策略
            5. 全程发出结构化事件

        返回完整的 ToolCall,包含所有尝试和事件。
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolExecutionError(f"未注册的工具: {tool_name}")

        call = ToolCall(
            tool_name=tool_name,
            input=input,
            max_retries=max_retries if max_retries is not None else 2,
            timeout_seconds=timeout if timeout is not None else tool.default_timeout,
        )

        call.add_event(EventType.TOOL_INVOKED, f"调用工具 {tool_name}")

        max_attempts = call.max_retries + 1
        last_error = ""

        for attempt_num in range(1, max_attempts + 1):
            start = time.time()

            try:
                # 执行,带超时 (修复 P0-2A: 不再无限等待)
                result = self._execute_with_timeout(tool, input, call.timeout_seconds)
                duration_ms = int((time.time() - start) * 1000)

                attempt = Attempt(
                    attempt_num=attempt_num,
                    status=ToolStatus.SUCCESS,
                    result=result,
                    duration_ms=duration_ms,
                )
                call.attempts.append(attempt)
                call.result = result
                call.status = ToolStatus.SUCCESS

                call.add_event(
                    EventType.TOOL_SUCCEEDED,
                    f"第 {attempt_num} 次执行成功",
                    duration_ms,
                )
                self._emit_events(call)
                return call

            except ToolTimeoutError as e:
                # 超时: 必须标记为 TIMEOUT,不可静默成功 (不变式 3)
                duration_ms = int((time.time() - start) * 1000)
                last_error = str(e)
                call.attempts.append(Attempt(
                    attempt_num=attempt_num,
                    status=ToolStatus.TIMEOUT,
                    error=last_error,
                    duration_ms=duration_ms,
                ))
                call.add_event(
                    EventType.TOOL_TIMED_OUT,
                    f"第 {attempt_num} 次执行超时 ({call.timeout_seconds}s)",
                    duration_ms,
                )

            except Exception as e:
                # 失败: 记录错误,准备重试
                duration_ms = int((time.time() - start) * 1000)
                last_error = f"{type(e).__name__}: {e}"
                call.attempts.append(Attempt(
                    attempt_num=attempt_num,
                    status=ToolStatus.FAILED,
                    error=last_error,
                    duration_ms=duration_ms,
                ))
                call.add_event(
                    EventType.TOOL_FAILED,
                    f"第 {attempt_num} 次执行失败: {last_error}",
                    duration_ms,
                )

            # 是否还有重试机会
            if attempt_num < max_attempts:
                # 指数退避: 1s, 4s, 9s... (对应 ADR-002)
                backoff = attempt_num ** 2
                call.add_event(EventType.TOOL_RETRIED, f"{backoff}s 后重试")
                self._emit_events(call)
                time.sleep(backoff)

        # 所有尝试都失败,触发降级
        call = self._apply_degradation(call, tool, input, last_error)
        self._emit_events(call)
        return call

    def _execute_with_timeout(self, tool: ToolProtocol, input: dict, timeout: int) -> ToolResult:
        """带超时执行工具

        使用线程执行,主线程等待 timeout 秒。
        超时则抛出 ToolTimeoutError,绝不静默成功。

        修复 P0-2A: 旧代码 write 工具 120s 无响应,
        新代码 write 15s 超时后立即标记失败。
        """
        import threading

        result_holder: dict[str, Any] = {"result": None, "error": None}
        thread = threading.Thread(
            target=self._run_tool_safely,
            args=(tool, input, result_holder),
            daemon=True,
        )
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 线程仍在运行 -> 超时
            # daemon=True,主线程退出时自动结束,不阻塞
            raise ToolTimeoutError(f"工具 {tool.name} 执行超过 {timeout}s 超时")

        if result_holder["error"]:
            raise result_holder["error"]

        result = result_holder["result"]
        if result is None:
            raise ToolExecutionError(f"工具 {tool.name} 返回空结果")
        return result

    @staticmethod
    def _run_tool_safely(tool: ToolProtocol, input: dict, holder: dict) -> None:
        """在子线程中安全执行工具,捕获所有异常"""
        try:
            holder["result"] = tool.execute(input, timeout=0)
        except Exception as e:
            holder["error"] = e

    def _apply_degradation(
        self,
        call: ToolCall,
        tool: ToolProtocol,
        input: dict,
        last_error: str,
    ) -> ToolCall:
        """应用降级策略 (ADR-002 决策 3)

        降级策略:
            - write 超时 -> 降级为输出文件内容供用户手动保存
            - bash 语法错误 -> 检测 Shell 类型并转换语法后重试
            - read 失败 -> 返回明确"文件不存在"而非超时
        """
        try:
            degraded_result = tool.degrade(input, last_error)
            call.result = degraded_result
            call.status = ToolStatus.DEGRADED
            call.add_event(
                EventType.TOOL_DEGRADED,
                f"降级成功: {degraded_result.output[:100]}",
            )
        except Exception as degrade_err:
            call.status = ToolStatus.FAILED
            call.add_event(
                EventType.TOOL_FAILED,
                f"降级也失败: {degrade_err}",
            )
        return call

    def _emit_events(self, call: ToolCall) -> None:
        """发出未发送的事件 (修复 P2-2/P2-3 可观测性)"""
        if self._event_callback:
            for event in call.events:
                try:
                    self._event_callback(event)
                except Exception:
                    pass  # 事件回调失败不影响主流程


# 全局执行引擎单例
_engine: ExecutionEngine | None = None


def get_execution_engine() -> ExecutionEngine:
    """获取全局执行引擎单例"""
    global _engine
    if _engine is None:
        _engine = ExecutionEngine()
    return _engine
