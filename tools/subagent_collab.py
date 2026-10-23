"""Model-facing collaboration tools. Dispatch stays in the child-session manager."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from RxyCode.RxyCode1_1_0.core.subagents.collab import (
    cancel_subagent,
    list_agents,
    send_message_to_subagent,
    spawn_subagent,
)


class SpawnSubagentInput(BaseModel):
    agent_id: str = Field(description="Child agent id, for example explore, general, reviewer, or scout.")
    prompt: str = Field(description="Task instruction. The child sees it as [FROM_MAIN_AGENT].")
    mode: str = Field(
        default="sync",
        description="sync waits; async returns a session id; stream returns a session id and keeps emitting events.",
    )


class CancelSubagentInput(BaseModel):
    session_id: str = Field(description="Child session id returned by spawn_subagent.")


class SendMessageInput(BaseModel):
    session_id: str = Field(description="Child session id, or main to report back to the parent session.")
    text: str = Field(description="Supplemental instruction, question, or progress report.")


class ListAgentsInput(BaseModel):
    pass


async def _spawn(agent_id: str, prompt: str, mode: str = "sync") -> str:
    return await spawn_subagent(agent_id, prompt, mode=mode)


async def _cancel(session_id: str) -> str:
    return await cancel_subagent(session_id)


async def _send(session_id: str, text: str) -> str:
    return await send_message_to_subagent(session_id, text)


def _list() -> str:
    return list_agents()


async def _list_async() -> str:
    return list_agents()


spawn_subagent_tool = StructuredTool(
    name="spawn_subagent",
    description=(
        "Create an isolated child agent with its own prompt, context, and tools. "
        "mode=sync waits for the result. mode=async returns a session id and later "
        "delivers the summary to the parent inbox. mode=stream does the same and also "
        "emits that child's tool and progress events. "
        "Do not use this for a greeting or a one-file change you can finish yourself."
    ),
    func=lambda agent_id, prompt, mode="sync": __import__("asyncio").run(
        _spawn(agent_id, prompt, mode)
    ),
    coroutine=_spawn,
    args_schema=SpawnSubagentInput,
)

cancel_subagent_tool = StructuredTool(
    name="cancel_subagent",
    description=(
        "Stop a running child agent when the user changed their mind or another child "
        "already answered. Pass the session id from spawn_subagent."
    ),
    func=lambda session_id: __import__("asyncio").run(_cancel(session_id)),
    coroutine=_cancel,
    args_schema=CancelSubagentInput,
)

send_message_to_subagent_tool = StructuredTool(
    name="send_message_to_subagent",
    description=(
        "Send a follow-up to a running child, or report progress to your parent session. "
        "session_id=main sends upward. The runtime chooses the source tag from who "
        "is actually calling; do not claim to be the user or the coordinator."
    ),
    func=lambda session_id, text: __import__("asyncio").run(
        _send(session_id, text)
    ),
    coroutine=_send,
    args_schema=SendMessageInput,
)

list_agents_tool = StructuredTool(
    name="list_agents",
    description=(
        "List available agents with their duties and the status of running child sessions. "
        "Use this to find a collaborator instead of guessing that only explore exists."
    ),
    func=_list,
    coroutine=_list_async,
    args_schema=ListAgentsInput,
)
