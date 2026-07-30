"""Evidence-grounded reflection for failed plan-and-execute tasks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from RxyCode.RxyCode1_1_0.core.prompts import (
    build_user_message,
    get_role_prompt,
    get_system_prompt,
)
from RxyCode.RxyCode1_1_0.core.state import TaskNode
from RxyCode.RxyCode1_1_0.planning.structured_output import (
    StructuredOutputError,
    invoke_structured_output,
)


FailureType = Literal[
    "planning_error",
    "reasoning_error",
    "tool_error",
    "verification_error",
    "unknown",
]
ReflectionAction = Literal["retry", "replan", "terminate"]


class ReflectionResult(BaseModel):
    failure_type: FailureType = "unknown"
    reason: str = "Insufficient evidence to classify the failure"
    action: ReflectionAction = "replan"
    corrective_action: str = "Revise the failed task using the available evidence"
    verification_steps: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)


def _deterministic_reflection(task: TaskNode) -> ReflectionResult | None:
    evidence_failed = any(
        isinstance(item, dict)
        and (item.get("status") != "succeeded" or item.get("executed") is not True)
        for item in task.evidence
    )
    validation = task.validation_result or {}
    issues = " ".join(str(item) for item in validation.get("issues", []))
    haystack = " ".join(
        [issues, task.result or "", *task.error_history[-5:]]
    ).lower()

    tool_markers = (
        "tool", "timeout", "permission", "approval", "not found", "network",
        "执行", "工具", "超时", "权限",
    )
    if evidence_failed or any(marker in haystack for marker in tool_markers):
        exhausted = task.retry_count >= task.max_retries
        return ReflectionResult(
            failure_type="tool_error",
            reason=issues or "Tool evidence reports an unsuccessful execution",
            action="terminate" if exhausted else "retry",
            corrective_action="Retry the failed tool through the governed tool boundary",
            verification_steps=["Require successful tool and artifact evidence"],
            lessons=["Do not treat optimistic model prose as execution evidence"],
        )

    planning_markers = (
        "dependency", "plan", "acceptance criteria", "requirement", "scope",
        "依赖", "计划", "验收", "需求",
    )
    if any(marker in haystack for marker in planning_markers):
        return ReflectionResult(
            failure_type="planning_error",
            reason=issues or "The plan did not express a valid executable task",
            action="replan",
            corrective_action="Revise the task boundaries, dependencies, and acceptance criteria",
            verification_steps=["Validate the revised dependency DAG before execution"],
        )

    verification_markers = ("evidence", "verify", "validation", "artifact", "校验", "证据")
    if any(marker in haystack for marker in verification_markers):
        exhausted = task.retry_count >= task.max_retries
        return ReflectionResult(
            failure_type="verification_error",
            reason=issues or "The result lacks sufficient verification evidence",
            action="terminate" if exhausted else "retry",
            corrective_action="Run the required verification and capture evidence",
            verification_steps=["Re-run deterministic acceptance checks"],
        )
    return None


class Reflector:
    """Classify a failure and choose retry/replan/terminate from evidence."""

    def __init__(self, llm):
        self._llm = llm

    async def reflect(self, task: TaskNode) -> ReflectionResult:
        deterministic = _deterministic_reflection(task)
        if deterministic is not None:
            return deterministic

        validation = task.validation_result or {}
        role = get_role_prompt(
            "reflection",
            task=f"{task.title}\n{task.description}\n{task.requirement}",
            result=(task.result or "")[:2000],
            validation_issues=validation.get("issues", []),
            error_history=task.error_history[-5:],
        )
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=build_user_message(role, "")),
        ]
        try:
            return await invoke_structured_output(
                self._llm,
                messages,
                ReflectionResult,
                repair_attempts=1,
            )
        except (StructuredOutputError, TypeError, ValueError):
            return ReflectionResult(
                reason="Reflection output could not be validated",
                action=(
                    "terminate"
                    if task.retry_count >= task.max_retries
                    else "replan"
                ),
                verification_steps=["Inspect the bounded failure history manually"],
            )
