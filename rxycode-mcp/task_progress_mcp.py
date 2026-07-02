#!/usr/bin/env python
"""
任务进度追踪 MCP 服务器 (task-progress)
=======================================
实现可观测层 —— 结构化执行事件流，消除"黑盒执行"。

解决：
  P2-2 错误信息不透明（工具调用显示为 "unknown"，超时无错误信息）
  P2-3 缺乏执行进度反馈（36.6s 思考期间无进度指示）

核心机制：
  1. 结构化事件流 —— 每个执行步骤发出 ToolInvoked/StepCompleted/TaskFailed 事件
  2. 实时进度反馈 —— 用户可随时查询当前任务状态和进度
  3. 可追溯执行日志 —— 完整记录每次工具调用的输入、输出、耗时
  4. 透明错误传播 —— 失败时附带明确错误码和原因
"""

import json
import uuid
import time
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "task-progress",
    instructions="任务进度追踪 —— 结构化执行事件流，透明可观测",
)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventType(str, Enum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TOOL_INVOKED = "tool_invoked"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    TOOL_TIMED_OUT = "tool_timed_out"
    TOOL_RETRIED = "tool_retried"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Step:
    index: int
    description: str
    status: StepStatus = StepStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    duration_s: float | None = None
    detail: str = ""
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class ExecutionEvent:
    id: str
    timestamp: str
    event_type: str
    task_id: str
    step_index: int | None
    data: dict
    message: str = ""


@dataclass
class Task:
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    steps: list[Step] = field(default_factory=list)
    events: list[ExecutionEvent] = field(default_factory=list)
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    total_duration_s: float | None = None
    current_step: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "progress_percent": self._progress_percent(),
            "steps": [asdict(s) for s in self.steps],
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_s": self.total_duration_s,
            "event_count": len(self.events),
            "metadata": self.metadata,
        }

    def _progress_percent(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps
                        if s.status in (StepStatus.SUCCESS, StepStatus.FAILED,
                                        StepStatus.SKIPPED))
        return round(completed / len(self.steps) * 100, 1)


# ---------------------------------------------------------------------------
# 内存存储（单进程生命周期）
# ---------------------------------------------------------------------------

_tasks: dict[str, Task] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_ts() -> float:
    return time.time()


def _emit_event(task: Task, event_type: EventType, step_index: int | None,
                data: dict, message: str = ""):
    """发出结构化执行事件。"""
    event = ExecutionEvent(
        id=str(uuid.uuid4())[:8],
        timestamp=_now(),
        event_type=event_type.value,
        task_id=task.id,
        step_index=step_index,
        data=data,
        message=message,
    )
    task.events.append(event)
    return event


# ---------------------------------------------------------------------------
# MCP 工具
# ---------------------------------------------------------------------------

@mcp.tool()
def start_task(description: str, steps: list[str],
               metadata: dict | None = None) -> str:
    """注册一个新任务及其执行步骤。

    在开始执行复杂多步骤任务前调用此工具，预先声明所有步骤。
    这让用户能看到任务的全貌和预期进度。

    解决 P2-3：用户不知道 Agent 在做什么、要做什么。

    Args:
        description: 任务描述
        steps: 任务步骤列表（按执行顺序）
        metadata: 可选的附加元数据

    Returns:
        JSON 包含任务 ID 和初始状态。
    """
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task = Task(
        id=task_id,
        description=description,
        created_at=_now(),
        metadata=metadata or {},
    )

    for i, step_desc in enumerate(steps):
        task.steps.append(Step(index=i, description=step_desc))

    _tasks[task_id] = task
    _emit_event(task, EventType.TASK_STARTED, None,
                {"step_count": len(steps)},
                f"任务已注册：{description}（{len(steps)} 个步骤）")

    return json.dumps({
        "task_id": task_id,
        "description": description,
        "total_steps": len(steps),
        "steps": [{"index": i, "description": s} for i, s in enumerate(steps)],
        "status": "pending",
        "message": "任务已注册。使用 update_progress 开始执行步骤。",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def update_progress(task_id: str, step_index: int, status: str,
                    detail: str = "", tool_calls: list[dict] | None = None) -> str:
    """更新任务步骤的进度。

    在每个步骤开始、完成或失败时调用此工具。
    这让用户能实时看到执行进度。

    解决 P2-3：长时间运行的任务无实时反馈。

    Args:
        task_id: 任务 ID（由 start_task 返回）
        step_index: 步骤索引（从 0 开始）
        status: 步骤状态（running/success/failed/skipped）
        detail: 步骤详情或说明
        tool_calls: 该步骤的工具调用记录列表

    Returns:
        JSON 包含更新后的任务状态和进度百分比。
    """
    task = _tasks.get(task_id)
    if task is None:
        return json.dumps({
            "error": f"任务不存在：{task_id}",
            "suggestion": "请先使用 start_task 注册任务。",
        }, ensure_ascii=False, indent=2)

    if step_index < 0 or step_index >= len(task.steps):
        return json.dumps({
            "error": f"步骤索引 {step_index} 超出范围（0-{len(task.steps) - 1}）",
        }, ensure_ascii=False, indent=2)

    step = task.steps[step_index]
    try:
        step.status = StepStatus(status)
    except ValueError:
        return json.dumps({
            "error": f"无效状态 '{status}'，可选：running/success/failed/skipped",
        }, ensure_ascii=False, indent=2)

    step.detail = detail
    if tool_calls:
        step.tool_calls.extend(tool_calls)

    now = _now()
    ts = _now_ts()

    if step.status == StepStatus.RUNNING:
        step.started_at = now
        task.status = TaskStatus.RUNNING
        task.current_step = step_index
        if task.started_at is None:
            task.started_at = now
        _emit_event(task, EventType.STEP_STARTED, step_index,
                    {"description": step.description},
                    f"开始执行步骤 {step_index + 1}：{step.description}")

    elif step.status == StepStatus.SUCCESS:
        step.completed_at = now
        if step.started_at:
            # 简化：用时间戳差值
            step.duration_s = round(ts - _parse_ts(step.started_at), 2)
        _emit_event(task, EventType.STEP_COMPLETED, step_index,
                    {"duration_s": step.duration_s, "detail": detail},
                    f"步骤 {step_index + 1} 完成：{step.description}")

    elif step.status == StepStatus.FAILED:
        step.completed_at = now
        _emit_event(task, EventType.STEP_FAILED, step_index,
                    {"detail": detail},
                    f"步骤 {step_index + 1} 失败：{detail}")
        task.status = TaskStatus.FAILED

    elif step.status == StepStatus.SKIPPED:
        step.completed_at = now
        _emit_event(task, EventType.INFO, step_index,
                    {"detail": detail}, f"步骤 {step_index + 1} 已跳过")

    # 检查任务是否全部完成
    if task.status != TaskStatus.FAILED:
        all_done = all(s.status in (StepStatus.SUCCESS, StepStatus.FAILED,
                                     StepStatus.SKIPPED) for s in task.steps)
        if all_done:
            task.status = TaskStatus.COMPLETED
            task.completed_at = now
            if task.started_at:
                task.total_duration_s = round(ts - _parse_ts(task.started_at), 2)
            _emit_event(task, EventType.TASK_COMPLETED, None,
                        {"total_duration_s": task.total_duration_s},
                        f"任务完成：{task.description}")

    return json.dumps({
        "task_id": task_id,
        "step_index": step_index,
        "step_status": step.status.value,
        "task_status": task.status.value,
        "progress_percent": task._progress_percent(),
        "current_step": task.current_step,
        "total_steps": len(task.steps),
    }, ensure_ascii=False, indent=2)


def _parse_ts(iso_str: str) -> float:
    """将 ISO 时间字符串转回时间戳（简化处理）。"""
    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except (ValueError, TypeError):
        return _now_ts()


@mcp.tool()
def log_tool_call(task_id: str, step_index: int, tool_name: str,
                  input_data: dict, output_data: dict | None = None,
                  status: str = "success", duration_s: float = 0,
                  error: str = "") -> str:
    """记录一次工具调用的详细信息。

    解决 P2-2：工具调用显示为 "unknown"，信息不透明。
    此工具记录完整的工具调用信息：名称、输入、输出、耗时、状态。

    Args:
        task_id: 任务 ID
        step_index: 所属步骤索引
        tool_name: 工具名称（如 write/read/bash）
        input_data: 工具输入参数
        output_data: 工具输出结果
        status: 调用状态（success/failed/timeout）
        duration_s: 执行耗时（秒）
        error: 错误信息（如果有）

    Returns:
        JSON 确认记录已保存。
    """
    task = _tasks.get(task_id)
    if task is None:
        return json.dumps({"error": f"任务不存在：{task_id}"}, ensure_ascii=False)

    call_record = {
        "tool": tool_name,
        "input": input_data,
        "output": output_data,
        "status": status,
        "duration_s": duration_s,
        "error": error,
        "timestamp": _now(),
    }

    if step_index < len(task.steps):
        task.steps[step_index].tool_calls.append(call_record)

    # 发出对应事件
    event_map = {
        "success": EventType.TOOL_SUCCEEDED,
        "failed": EventType.TOOL_FAILED,
        "timeout": EventType.TOOL_TIMED_OUT,
    }
    event_type = event_map.get(status, EventType.TOOL_INVOKED)
    _emit_event(task, event_type, step_index,
                {"tool": tool_name, "duration_s": duration_s},
                f"工具 {tool_name} {'成功' if status == 'success' else '失败'}"
                f"（{duration_s}s）")

    return json.dumps({
        "logged": True,
        "task_id": task_id,
        "tool": tool_name,
        "status": status,
        "duration_s": duration_s,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_task_status(task_id: str) -> str:
    """查询任务的当前状态和进度。

    用户可随时调用此工具查看任务进度。
    解决 P2-3：用户不知道任务执行到哪一步了。

    Args:
        task_id: 任务 ID

    Returns:
        JSON 包含任务状态、进度百分比、各步骤状态。
    """
    task = _tasks.get(task_id)
    if task is None:
        return json.dumps({
            "error": f"任务不存在：{task_id}",
            "available_tasks": list(_tasks.keys()),
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "task": task.to_dict(),
        "recent_events": [asdict(e) for e in task.events[-5:]],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_execution_log(task_id: str, event_type: str | None = None,
                      limit: int = 50) -> str:
    """获取任务的完整执行日志。

    返回结构化的事件流，可用于调试和审计。
    解决 P2-2：错误信息不透明，无法诊断。

    Args:
        task_id: 任务 ID
        event_type: 可选，按事件类型过滤（如 tool_failed）
        limit: 最大返回事件数（默认 50）

    Returns:
        JSON 包含结构化执行事件流。
    """
    task = _tasks.get(task_id)
    if task is None:
        return json.dumps({"error": f"任务不存在：{task_id}"}, ensure_ascii=False)

    events = task.events
    if event_type:
        events = [e for e in events if e.event_type == event_type]

    events = events[-limit:]

    return json.dumps({
        "task_id": task_id,
        "description": task.description,
        "total_events": len(task.events),
        "showing": len(events),
        "events": [asdict(e) for e in events],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_all_tool_calls(task_id: str) -> str:
    """获取任务中所有工具调用的汇总。

    透明展示每次工具调用的名称、输入、输出、耗时。
    解决 P2-2：工具调用显示为 "unknown"。

    Args:
        task_id: 任务 ID

    Returns:
        JSON 包含所有工具调用记录。
    """
    task = _tasks.get(task_id)
    if task is None:
        return json.dumps({"error": f"任务不存在：{task_id}"}, ensure_ascii=False)

    all_calls = []
    for step in task.steps:
        for call in step.tool_calls:
            call_entry = dict(call)
            call_entry["step_index"] = step.index
            call_entry["step_description"] = step.description
            all_calls.append(call_entry)

    # 统计
    stats = {
        "total_calls": len(all_calls),
        "by_tool": {},
        "by_status": {},
        "total_duration_s": 0,
    }
    for c in all_calls:
        tool = c.get("tool", "unknown")
        stats["by_tool"][tool] = stats["by_tool"].get(tool, 0) + 1
        status = c.get("status", "unknown")
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        stats["total_duration_s"] += c.get("duration_s", 0)

    stats["total_duration_s"] = round(stats["total_duration_s"], 2)

    return json.dumps({
        "task_id": task_id,
        "stats": stats,
        "tool_calls": all_calls,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_active_tasks() -> str:
    """列出所有活跃（未完成）的任务。

    Returns:
        JSON 包含活跃任务列表。
    """
    active = []
    for task in _tasks.values():
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            active.append({
                "task_id": task.id,
                "description": task.description,
                "status": task.status.value,
                "progress_percent": task._progress_percent(),
                "current_step": task.current_step,
                "total_steps": len(task.steps),
            })

    return json.dumps({
        "active_count": len(active),
        "tasks": active,
        "total_tracked": len(_tasks),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
