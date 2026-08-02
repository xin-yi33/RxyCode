"""In-process session registry for appserver."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppSessionRecord:
    session_id: str
    workspace_root: Path


class SessionStore:
    """Track multiple concurrent sessions in one appserver process."""

    def __init__(self) -> None:
        self._sessions: dict[str, AppSessionRecord] = {}

    def create(self, workspace_root: Path | str) -> AppSessionRecord:
        session_id = uuid.uuid4().hex[:12]
        record = AppSessionRecord(
            session_id=session_id,
            workspace_root=Path(workspace_root),
        )
        self._sessions[session_id] = record
        return record

    def get(self, session_id: str) -> AppSessionRecord | None:
        return self._sessions.get(session_id)

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())