"""UPDATE-02 §4.4 / V17 todo wire contract.

FIX5 consumes this module. It is the only snapshot schema. Do not add a
second wire model under core/todo_snapshot.py.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

TodoStatus = Literal["pending", "in_progress", "completed", "blocked", "cancelled"]
TodoScope = Literal["turn", "goal", "compose", "child"]
TodoSource = Literal["model", "task_tree", "goal", "compose", "system"]


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    content: str
    status: TodoStatus
    priority: str | None = None
    owner_session_id: str | None = None
    owner_agent_id: str | None = None
    evidence_refs: list[str] | None = None


class TodoSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    root_session_id: str
    run_id: str | None = None
    list_id: str
    revision: int
    scope: TodoScope
    source: TodoSource
    explanation: str | None = None
    items: list[TodoItem]
    updated_at: str
