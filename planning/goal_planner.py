"""GoalPlanner: top-level goal extraction from user input."""

from __future__ import annotations
from uuid import uuid4
from pydantic import BaseModel, Field
from RxyCode.RxyCode1_1_0.core.state import TaskEffect, TaskNode, TaskTree
from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt, build_user_message, get_role_prompt
from RxyCode.RxyCode1_1_0.planning.structured_output import (
    StructuredOutputError,
    invoke_structured_output,
)


class GoalResult(BaseModel):
    """Structured output from the GoalPlanner LLM call."""
    goal: str = Field(description="One-sentence description of the final objective")
    constraints: list[str] = Field(default_factory=list, description="Constraints, tech stack, style requirements")
    output_format: str = Field(default="markdown", description="Desired output format")
    effect: TaskEffect = Field(
        default=TaskEffect.AUTO,
        description="Expected task effect: read, write, or danger",
    )


class GoalPlanner:
    """Extracts the top-level goal from user input."""

    def __init__(self, llm):
        self._llm = llm

    async def plan(self, user_input: str, memory_context: str = "") -> tuple[GoalResult, TaskTree]:
        from langchain_core.messages import HumanMessage, SystemMessage
        user_msg = build_user_message(get_role_prompt("goal_planner"), f"User input:\n{user_input}", memory_context)
        messages = [SystemMessage(content=get_system_prompt()), HumanMessage(content=user_msg)]
        try:
            result = await invoke_structured_output(self._llm, messages, GoalResult)
        except StructuredOutputError as exc:
            # Preserve the previous best-effort behavior after the bounded retry.
            result = GoalResult(goal=exc.response_text.strip() or user_input.strip())
        root = TaskNode(
            id=str(uuid4()),
            title=result.goal,
            description=user_input,
            requirement=result.goal,
            depth=0,
            effect=result.effect,
        )
        tree = TaskTree(goal_id=root.id, nodes={root.id: root}, constraints=result.constraints, output_format=result.output_format)
        tree.assert_valid_plan()
        return result, tree
