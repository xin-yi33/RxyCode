"""GX9 persistent plan files under RXYCODE_DATA_DIR/plans.

Never writes ~/.rxycode directly. persist is an export view; implement starts a turn.
Never lives under appserver/handlers/.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any


class PlanFileError(Exception):
    def __init__(self, message: str, *, code: str = "plan_files") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _plans_dir() -> Path:
    root = Path(os.environ.get("RXYCODE_DATA_DIR") or ".")
    return root / "plans"


def _slug(title: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (title or "plan").strip()).strip("-").lower()
    return (text or "plan")[:40]


class PlanFileService:
    def __init__(self) -> None:
        self._plans: dict[str, dict[str, Any]] = {}

    def persist(
        self,
        *,
        thread_id: str,
        title: str,
        goal: str,
        steps: list[str],
        acceptance: list[str],
    ) -> dict[str, Any]:
        if not thread_id:
            raise PlanFileError("thread_id is required", code="invalid_thread")
        directory = _plans_dir()
        directory.mkdir(parents=True, exist_ok=True)
        plan_id = "plan_" + uuid.uuid4().hex[:12]
        slug = _slug(title)
        path = directory / f"{thread_id}-{slug}.md"
        body = (
            f"# Plan: {title}\n"
            f"## 目标\n{goal.strip()}\n"
            f"## 步骤\n"
            + "".join(f"- [ ] {item}\n" for item in steps)
            + "## 验收清单\n"
            + "".join(f"- [ ] {item}\n" for item in acceptance)
        )
        path.write_text(body, encoding="utf-8")
        record = {
            "plan_id": plan_id,
            "thread_id": thread_id,
            "title": title,
            "path": str(path),
            "status": "ready",
            "markdown": body,
        }
        self._plans[plan_id] = record
        return dict(record)

    def implement(self, *, plan_id: str, confirm: bool) -> dict[str, Any]:
        if confirm is not True:
            raise PlanFileError("implement requires explicit confirm=true", code="confirm_required")
        record = self._plans.get(plan_id)
        if record is None:
            raise PlanFileError(f"unknown plan: {plan_id}", code="unknown_plan")
        record["status"] = "implementing"
        prompt = "Implement the following plan as first-turn context:\n" + record["markdown"]
        return {
            "plan_id": plan_id,
            "thread_id": record["thread_id"],
            "status": "implementing",
            "turn_prompt": prompt,
        }
