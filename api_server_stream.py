"""SSE transport classes for the RxyCode API server (extracted from api_server.py)."""

from __future__ import annotations

import re
import asyncio as _asyncio
import time as _time
import uuid as _uuid


class APIProxyTUI:
    """Proxy TUI that captures output for the API."""

    def __init__(self):
        self._mode = "build"
        self._model_name = ""
        self._last_output = []
        self._tool_calls = []
        self._stats = {}
        self._expand_thinking = False
        self._thinking_content = []

    def set_thinking_expanded(self, expanded):
        self._expand_thinking = expanded

    def get_thinking_expanded(self):
        return self._expand_thinking

    def set_mode(self, mode): self._mode = mode
    def set_model(self, name): self._model_name = name
    def set_process_fn(self, fn): pass
    def set_cancel_fn(self, fn): pass
    def set_session_list_fn(self, fn): pass
    def set_model_list_fn(self, fn): pass
    def set_new_session_fn(self, fn): pass
    def set_busy(self, busy): pass

    def update_stats(self, **kwargs):
        self._stats.update(kwargs)

    def write(self, text, color=""):
        self._last_output.append(text)

    def write_user_input(self, text):
        pass

    def write_thought(self, elapsed):
        self._last_output.append(f"  + Thought: {elapsed:.1f}s")

    def write_plan(self, steps):
        self._last_output.append(f"  + Plan: {len(steps)} Steps")

    def write_step(self, num, total, desc):
        self._last_output.append(f"  {num}/{total} {desc}")

    def write_tool_call(self, name, args, call_id=None):
        call_id = str(call_id or _uuid.uuid4().hex)
        self._tool_calls.append({
            "id": call_id,
            "name": name,
            "args": args,
            "result": "",
            "status": "running",
        })
        self._last_output.append(f"    {name}({args})")
        return call_id

    def write_tool_result(self, result, status="success", call_id=None):
        running = [
            call for call in self._tool_calls if call.get("status") == "running"
        ]
        target = next(
            (call for call in running if call.get("id") == call_id),
            running[0] if call_id is None and len(running) == 1 else None,
        )
        if target is not None:
            target["result"] = result
            target["status"] = status
        self._last_output.append(f"    -> {result[:200]}")

    def write_error(self, msg):
        self._last_output.append(f"  x {msg}")

    def write_success(self, msg):
        self._last_output.append(f"  v {msg}")

    def write_info(self, msg):
        self._last_output.append(f"  {msg}")

    def write_progress(self, text):
        self._last_output.append(f"  {text}")

    def stream_token(self, tok):
        pass

    def write_warning(self, msg):
        self._last_output.append(f"  ! {msg}")

    def write_model_indicator(self, mode, model):
        self._last_output.append(f"  {mode} . {model}")

    def write_capability_list(self):
        pass

    def write_command_list(self):
        pass

    def write_chat_list(self, chats):
        pass

    def run(self):
        pass

    def exit(self):
        pass

    def get_and_clear(self):
        output = "\n".join(self._last_output)
        tool_calls = self._tool_calls.copy()
        self._last_output.clear()
        self._tool_calls.clear()
        return output, tool_calls


class StreamSessionRecorder:
    """Mirror one real SSE turn into the durable session message protocol."""

    def __init__(self, history: list[dict], *, run_id: str, user_message: str) -> None:
        self._history = history
        self.run_id = run_id
        self.started_at = _time.monotonic()
        self._thinking_parts: list[str] = []
        self._has_thinking_content = False
        self._pending_tools: list[dict] = []
        self._terminal = False
        self._append("user", user_message)
        self._thinking = self._append(
            "thinking", "Analyzing request...", done=False, live=True
        )

    @property
    def messages(self) -> list[dict]:
        return [message for message in self._history if message.get("run_id") == self.run_id]

    @property
    def thinking_content(self) -> str:
        if not self._has_thinking_content:
            return ""
        return str(self._thinking.get("content", "") or "")

    def _append(self, role: str, content: str, **metadata) -> dict:
        message = _session_message(role, content, run_id=self.run_id, **metadata)
        self._history.append(message)
        return message

    def add_thinking(self, text: str) -> None:
        if text:
            self._has_thinking_content = True
            self._thinking_parts.append(str(text))
            self._thinking["content"] = "".join(self._thinking_parts)

    def set_plan(self, steps: list) -> None:
        self._has_thinking_content = True
        content = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
        self._thinking["content"] = f"Plan ({len(steps)} steps):\n{content}"

    def set_step(self, index: int, total: int, text: str) -> None:
        self.add_thinking(f"Step {index}/{total}: {text}")
        self._thinking["stepIndex"] = index
        self._thinking["stepTotal"] = total

    def start_tool(self, name: str, args, call_id: str | None = None) -> dict:
        message = self._append(
            "tool",
            "",
            id=call_id or f"{self.run_id}-tool-{_uuid.uuid4().hex[:10]}",
            toolName=str(name),
            toolArgs=str(args),
            toolStatus="running",
            toolStdout="",
            _started_at=_time.monotonic(),
        )
        self._pending_tools.append(message)
        return message

    def finish_tool(
        self, result, status: str, call_id: str | None = None
    ) -> dict | None:
        running = [
            candidate
            for candidate in self._pending_tools
            if candidate.get("toolStatus") == "running"
        ]
        message = next(
            (candidate for candidate in running if candidate.get("id") == call_id),
            running[0] if call_id is None and len(running) == 1 else None,
        )
        if message is None:
            return None
        output = str(result)
        normalized_status = {
            "failed": "error",
            "timed_out": "timeout",
        }.get(str(status), str(status))
        started_at = float(message.pop("_started_at", _time.monotonic()))
        message.update({
            "content": output,
            "toolStdout": output,
            "toolStatus": normalized_status,
            "toolDuration": max(0.0, _time.monotonic() - started_at),
        })
        exit_match = re.search(r"\[?\s*exit(?:\s*code)?\s*:\s*(-?\d+)\s*\]?", output, re.I)
        if exit_match:
            message["toolExitCode"] = int(exit_match.group(1))
        if normalized_status in {"error", "timeout", "cancelled"}:
            message["toolError"] = output
        return message

    def add_system_error(self, detail: str) -> dict:
        return self._append("system", f"Error: {detail}")

    def finish_success(self, answer: str, thinking: str) -> None:
        if self._terminal:
            return
        self._terminal = True
        if thinking:
            self._thinking["content"] = thinking
        elif not self._thinking_parts:
            self._thinking["content"] = "Done"
        self._finish_pending_tools("error")
        self._finish_thinking()
        self._append(
            "assistant",
            answer,
            elapsed=max(0.0, _time.monotonic() - self.started_at),
        )

    def finish_error(self, detail: str) -> None:
        if self._terminal:
            return
        self._terminal = True
        self._finish_pending_tools("error")
        self._finish_thinking()
        self.add_system_error(detail)

    def finish_cancelled(self) -> None:
        if self._terminal:
            return
        self._terminal = True
        self._thinking["content"] = self._thinking.get("content") or "Cancelled"
        self._finish_pending_tools("cancelled")
        self._finish_thinking()
        self._append("system", "Cancelled")

    def _finish_pending_tools(self, status: str) -> None:
        for message in self._pending_tools:
            if message.get("toolStatus") != "running":
                continue
            started_at = float(message.pop("_started_at", _time.monotonic()))
            message["toolStatus"] = status
            message["toolDuration"] = max(0.0, _time.monotonic() - started_at)

    def _finish_thinking(self) -> None:
        self._thinking.update({
            "done": True,
            "live": False,
            "elapsed": max(0.0, _time.monotonic() - self.started_at),
        })


class StreamTUI:
    """TUI implementation that pushes structured events onto a queue so the
    agent's progress can be streamed to the client as Server-Sent Events.

    This is what powers the mainstream-style "think -> tell the user what I'm
    doing -> keep working -> stream the final answer" experience."""

    # Stream coalescing paradigm ported from google-gemini/gemini-cli
    # (Apache-2.0, https://github.com/google-gemini/gemini-cli):
    # high-frequency stream chunks are accumulated per type and flushed on a
    # fixed time tick instead of emitting one SSE event per chunk, so the
    # frontend renders in a single tick and never floods/flickers.
    FLUSH_INTERVAL_S = 0.07
    TOOL_RESULT_MAX_CHARS = 4096
    TOOL_RESULT_MAX_LINES = 60

    def __init__(
        self,
        queue: "_asyncio.Queue",
        recorder: StreamSessionRecorder | None = None,
    ):
        self.q = queue
        self.recorder = recorder
        self._expand_thinking = False
        # per-type accumulation buffers (dict order defines flush order)
        self._buffers: dict[str, list[str]] = {"reasoning": [], "progress": [], "token": []}
        self._last_flush = 0.0  # monotonic; 0 -> first chunk flushes at once

    def _put(self, ev: dict):
        try:
            self.q.put_nowait(ev)
        except Exception:
            pass

    # -- coalescing core (B1) -------------------------------------------
    def flush_stream_buffers(self):
        """Emit all buffered chunk types as single merged events."""
        for kind, buf in self._buffers.items():
            if buf:
                text = "".join(buf)
                buf.clear()
                self._put({"type": kind, "text": text})
        self._last_flush = _time.monotonic()

    def _buffer(self, kind: str, text: str):
        self._buffers[kind].append(text)
        if _time.monotonic() - self._last_flush >= self.FLUSH_INTERVAL_S:
            self.flush_stream_buffers()

    # Internal-monologue patterns that must never reach the client while
    # thinking is off (B2/B5): raw reasoning rounds, code dumps, char counters.
    _NOISY_PROGRESS = re.compile(
        r"^(Thinking\.\.\.|Analyzing|Synthesizing|\[Code block:|Generating\.\.\.)"
    )

    # progress / plan / steps / tools / streamed tokens
    def write_progress(self, text):
        text = str(text)
        if self.recorder: self.recorder.add_thinking(text)
        # Gating (B2, 问题5/6): with thinking off, only short single-line
        # status updates pass (frontend loading phrase); internal monologue,
        # multi-line or long content is suppressed from SSE.
        if not self._expand_thinking:
            if "\n" in text or len(text) >= 150 or self._NOISY_PROGRESS.match(text):
                return
        self._buffer("progress", text + "\n")
    def write_reasoning(self, text):
        if self.recorder: self.recorder.add_thinking(str(text))
        if self._expand_thinking:
            self._buffer("reasoning", str(text))
    def write(self, text, color=""): self.write_progress(text)
    def write_info(self, text): self.write_progress(text)
    def write_success(self, text): self.write_progress(text)
    def write_warning(self, text): self.write_progress(text)
    def write_error(self, text):
        self.flush_stream_buffers()
        message = self.recorder.add_system_error(str(text)) if self.recorder else None
        self._put({"type": "error", "message": str(text), "message_id": message.get("id") if message else None})
    def write_plan(self, steps):
        self.flush_stream_buffers()
        values = list(steps)
        if self.recorder: self.recorder.set_plan(values)
        self._put({"type": "plan", "steps": values})
    def write_step(self, num, total, desc):
        self.flush_stream_buffers()
        if self.recorder: self.recorder.set_step(num, total, str(desc))
        self._put({"type": "step", "index": num, "total": total, "text": str(desc)})
    def write_tool_call(self, name, args, call_id=None):
        self.flush_stream_buffers()
        message = (
            self.recorder.start_tool(name, args, call_id=call_id)
            if self.recorder
            else None
        )
        call_id = message["id"] if message else str(call_id or _uuid.uuid4().hex)
        self._put({
            "type": "tool_call", "name": name, "args": str(args),
            "message_id": call_id,
            "timestamp": message.get("timestamp") if message else None,
        })
        return call_id
    def _truncate_for_sse(self, text: str) -> tuple[str, bool]:
        """Cap tool output on the SSE channel (B3); full output stays in recorder."""
        truncated = False
        lines = text.splitlines()
        if len(lines) > self.TOOL_RESULT_MAX_LINES:
            text = "\n".join(lines[: self.TOOL_RESULT_MAX_LINES])
            truncated = True
        if len(text) > self.TOOL_RESULT_MAX_CHARS:
            text = text[: self.TOOL_RESULT_MAX_CHARS]
            truncated = True
        if truncated:
            text += "\n… [输出已截断，完整结果见会话历史]"
        return text, truncated
    def write_tool_result(self, result, status="success", call_id=None):
        self.flush_stream_buffers()
        message = (
            self.recorder.finish_tool(result, status, call_id=call_id)
            if self.recorder
            else None
        )
        normalized_status = message.get("toolStatus") if message else status
        sse_result, was_truncated = self._truncate_for_sse(str(result))
        event = {"type": "tool_result", "result": sse_result, "status": normalized_status}
        if was_truncated:
            event["truncated"] = True
        if message:
            event.update({
                "message_id": message["id"],
                "duration": message.get("toolDuration"),
                "error": message.get("toolError"),
                "exitCode": message.get("toolExitCode"),
            })
        elif call_id is not None:
            event["message_id"] = str(call_id)
        self._put(event)
    def stream_token(self, tok):
        # Answer tokens always pass (thinking gating never hides the answer).
        self._buffer("token", str(tok))

    # no-ops for the rest of the TUI interface
    def set_thinking_expanded(self, expanded):
        was = bool(getattr(self, "_expand_thinking", False))
        self._expand_thinking = bool(expanded)
        # Mid-run expand: push already-accumulated thinking so the client can
        # show it immediately (U3). Collapse must not replay.
        if self._expand_thinking and not was:
            self._emit_thinking_snapshot()

    def _emit_thinking_snapshot(self) -> None:
        self.flush_stream_buffers()
        snapshot = ""
        if self.recorder is not None:
            snapshot = str(self.recorder.thinking_content or "")
        if not snapshot:
            return
        self._put({"type": "reasoning", "text": snapshot, "snapshot": True})

    def get_thinking_expanded(self):
        """Get thinking panel expanded state (always False in stream mode unless set)."""
        return getattr(self, '_expand_thinking', False)
    def set_mode(self, *a): pass
    def set_model(self, *a): pass
    def set_busy(self, *a): pass
    def write_user_input(self, *a): pass
    def write_model_indicator(self, *a): pass
    def write_capability_list(self, *a): pass
    def write_command_list(self, *a): pass
    def write_chat_list(self, *a): pass
    def update_stats(self, *a, **k): pass
    def __getattr__(self, name):
        def _f(*a, **k): return None
        return _f

# ``_session_message`` is defined in api_server.py and referenced by
# StreamSessionRecorder._append.  Resolve it at module level here.  The
# back-import lives at the bottom so both import orders work: api_server.py
# imports this module only after defining ``_session_message``, and a direct
# ``import api_server_stream`` completes the class bodies before this line
# triggers the (circular, but by then fully defined) api_server import.
from .api_server import _session_message  # noqa: E402
