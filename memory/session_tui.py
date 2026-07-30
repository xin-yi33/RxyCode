"""TUI adapter that records complete, versioned native CLI sessions."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from .chat_storage import CHAT_MESSAGE_VERSION


class SessionRecordingTUI:
    """Delegate display calls while mirroring semantic events to history."""

    def __init__(
        self,
        delegate: Any,
        history: list[dict],
        *,
        run_id: str,
        user_message: str,
    ) -> None:
        self._delegate = delegate
        self._history = history
        self.run_id = run_id
        self.started_at = time.monotonic()
        self._thinking: dict | None = None
        self._tools: dict[str, dict] = {}
        self._terminal = False
        self._append("user", user_message)

    def _append(self, role: str, content: object, **metadata) -> dict:
        message = {
            "version": CHAT_MESSAGE_VERSION,
            "id": metadata.pop(
                "id", f"{self.run_id}-{role}-{uuid.uuid4().hex[:10]}"
            ),
            "role": role,
            "content": str(content),
            "timestamp": metadata.pop("timestamp", int(time.time() * 1000)),
            "run_id": self.run_id,
            **metadata,
        }
        self._history.append(message)
        return message

    def _record_thinking(self, text: object) -> None:
        value = str(text)
        if not value:
            return
        if self._thinking is None:
            self._thinking = self._append(
                "thinking", value, done=False, live=True
            )
        else:
            previous = self._thinking.get("content", "")
            separator = "\n" if previous else ""
            self._thinking["content"] = f"{previous}{separator}{value}"

    def write(self, text, color=""):
        self._record_thinking(text)
        return self._delegate.write(text, color)

    def write_progress(self, text):
        self._record_thinking(text)
        return self._delegate.write_progress(text)

    def write_reasoning(self, text):
        self._record_thinking(text)
        writer = getattr(self._delegate, "write_reasoning", None)
        if callable(writer):
            return writer(text)
        return self._delegate.write_progress(text)

    def write_thinking(self, text):
        self._record_thinking(text)
        return self._delegate.write_thinking(text)

    def write_thought(self, elapsed):
        self._record_thinking(f"Thought: {float(elapsed):.1f}s")
        return self._delegate.write_thought(elapsed)

    def write_plan(self, steps):
        values = list(steps)
        self._record_thinking(
            "Plan:\n" + "\n".join(
                f"{index}. {step}" for index, step in enumerate(values, 1)
            )
        )
        writer = getattr(self._delegate, "write_plan", None)
        if callable(writer):
            return writer(values)
        return None

    def write_step(self, num, total, desc):
        self._record_thinking(f"Step {num}/{total}: {desc}")
        return self._delegate.write_step(num, total, desc)

    def write_step_done(self, num, total, desc):
        self._record_thinking(f"Step {num}/{total} completed: {desc}")
        writer = getattr(self._delegate, "write_step_done", None)
        if callable(writer):
            return writer(num, total, desc)
        return None

    def write_info(self, text):
        self._record_thinking(text)
        return self._delegate.write_info(text)

    def write_warning(self, text):
        self._record_thinking(text)
        return self._delegate.write_warning(text)

    def write_error(self, text):
        self._append("system", f"Error: {text}")
        return self._delegate.write_error(text)

    def write_tool_call(self, name, args, call_id=None):
        call_id = str(call_id or uuid.uuid4().hex)
        message = self._append(
            "tool",
            "",
            id=call_id,
            toolName=str(name),
            toolArgs=str(args),
            toolStatus="running",
            toolStdout="",
            _started_at=time.monotonic(),
        )
        self._tools[call_id] = message
        self._delegate.write_tool_call(name, args, call_id=call_id)
        return call_id

    def write_tool_result(self, result, status="success", call_id=None):
        running = [
            message
            for message in self._tools.values()
            if message.get("toolStatus") == "running"
        ]
        message = self._tools.get(str(call_id)) if call_id is not None else None
        if message is None and call_id is None and len(running) == 1:
            message = running[0]
        if message is not None and message.get("toolStatus") == "running":
            output = str(result)
            normalized = {"failed": "error", "timed_out": "timeout"}.get(
                str(status), str(status)
            )
            started_at = float(message.pop("_started_at", time.monotonic()))
            message.update(
                {
                    "content": output,
                    "toolStdout": output,
                    "toolStatus": normalized,
                    "toolDuration": max(0.0, time.monotonic() - started_at),
                }
            )
            exit_match = re.search(
                r"\[?\s*exit(?:\s*code)?\s*:\s*(-?\d+)\s*\]?",
                output,
                re.I,
            )
            if exit_match:
                message["toolExitCode"] = int(exit_match.group(1))
            if normalized in {"error", "timeout", "cancelled"}:
                message["toolError"] = output
        return self._delegate.write_tool_result(
            result, status, call_id=call_id
        )

    def finish(self, answer: object, status: str) -> None:
        if self._terminal:
            return
        self._terminal = True
        for message in self._tools.values():
            if message.get("toolStatus") != "running":
                continue
            started_at = float(message.pop("_started_at", time.monotonic()))
            message["toolStatus"] = "cancelled" if status == "cancelled" else "error"
            message["toolDuration"] = max(0.0, time.monotonic() - started_at)
        if self._thinking is not None:
            self._thinking["done"] = True
            self._thinking["live"] = False
        if status == "succeeded":
            self._append(
                "assistant",
                answer,
                elapsed=max(0.0, time.monotonic() - self.started_at),
            )
        else:
            detail = str(answer)
            if not self._history or self._history[-1].get("content") != detail:
                self._append("system", detail)

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)
