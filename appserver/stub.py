"""Stub agent for appserver integration tests (no LLM)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# The top-level ``python -m appserver`` entrypoint binds the canonical project
# package in appserver.__init__.  Use that identity first so the deterministic
# stub and the protocol worker share the same approval broker singleton.  The
# relative/top-level fallbacks retain direct package and legacy-script support.
try:
    from RxyCode.RxyCode1_1_0.core.safety.approval import (
        ApprovalRequest,
        get_approval_broker,
    )
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
except ImportError:
    try:
        from ..core.safety.approval import ApprovalRequest, get_approval_broker
        from ..core.safety.policy import RiskLevel
    except ImportError:
        from core.safety.approval import ApprovalRequest, get_approval_broker
        from core.safety.policy import RiskLevel


_MARKER = "e2e-03-worker-marker"


def next_prompt_reply() -> str | None:
    """Consume one line of RXYCODE_STUB_PROMPT_REPLIES_FILE across processes."""
    raw = os.environ.get("RXYCODE_STUB_PROMPT_REPLIES_FILE")
    if not raw:
        return None
    file = Path(raw)
    if not file.is_file():
        return None
    lines = file.read_text(encoding="utf-8").splitlines()
    index = file.with_name(file.name + ".idx")
    current = 0
    if index.is_file():
        try:
            current = int(index.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            current = 0
    if current >= len(lines):
        return None
    index.write_text(str(current + 1), encoding="utf-8")
    return lines[current]


def peek_prompt_reply() -> str | None:
    raw = os.environ.get("RXYCODE_STUB_PROMPT_REPLIES_FILE")
    if not raw:
        return None
    file = Path(raw)
    if not file.is_file():
        return None
    lines = file.read_text(encoding="utf-8").splitlines()
    index = file.with_name(file.name + ".idx")
    current = 0
    if index.is_file():
        try:
            current = int(index.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            current = 0
    if current >= len(lines):
        return None
    return lines[current]


def _marker_visible(pid: int) -> bool:
    """True only when this child PID's own command line contains the marker.

    The query must not name the marker in the PowerShell process command line,
    or Windows CIM matches the query itself.
    """
    if sys.platform != "win32":
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False
        return _MARKER.encode() in raw
    import base64

    script = (
        f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\"; "
        "if ($null -eq $p) { '' } else { $p.CommandLine }"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    out = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    ).stdout
    return _MARKER in out


def spawn_stall_marker() -> subprocess.Popen:
    """Child of this worker. Its command line contains the e2e marker."""
    proc = subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep(300)  # {_MARKER}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return proc
        if _marker_visible(proc.pid):
            return proc
        time.sleep(0.25)
    return proc


class StubFileDecisionLLM:
    """One JSON decision per line of RXYCODE_TIMEOUT_DECISION_STUB_FILE."""

    def __init__(self, path: str) -> None:
        self._lines = [
            line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        self._index = 0
        self.calls = 0

    async def ainvoke(self, prompt, **kwargs):
        del prompt, kwargs
        self.calls += 1
        if self._index < len(self._lines):
            text = self._lines[self._index]
            self._index += 1
        else:
            text = '{"action": "stop", "extend_seconds": 0, "note": "empty stub", "confidence": 0}'
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and "action" not in payload:
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            if "hang_seconds" in payload:
                await asyncio.sleep(float(payload["hang_seconds"]))

        class _Reply:
            content = text

        return _Reply()


def stub_decision_llm():
    """Enabled only for the stub appserver when the decision file is set."""
    if os.environ.get("RXYCODE_APPSERVER_STUB") != "1":
        return None
    path = os.environ.get("RXYCODE_TIMEOUT_DECISION_STUB_FILE")
    if not path or not Path(path).is_file():
        return None
    return StubFileDecisionLLM(path)


class StubAgent:
    """Deterministic agent used when ``RXYCODE_APPSERVER_STUB=1``."""

    def __init__(self) -> None:
        self._thinking_history: list[str] = []
        self._last_thinking = ""
        self._cancelled = False
        self.model_config = {"model_name": "stub"}
        self.attempt_id = ""
        self._marker = None
        if os.environ.get("RXYCODE_APPSERVER_STUB") == "1":
            raw_attempt = os.environ.get("RXYCODE_STUB_ATTEMPT_ID") or ""
            if raw_attempt:
                from RxyCode.RxyCode1_1_0.execution.tool_journal import validate_attempt_id

                try:
                    self.attempt_id = validate_attempt_id(raw_attempt)
                except ValueError:
                    self.attempt_id = ""
            peeked = peek_prompt_reply()
            if (
                os.environ.get("RXYCODE_STUB_STALL_AFTER_PROMPT") == "1"
                and peeked == "(stalled-worker-silence)"
            ):
                self._marker = spawn_stall_marker()
                import atexit

                atexit.register(self._close_marker)

    def _close_marker(self) -> None:
        proc = self._marker
        if proc is not None and proc.poll() is None:
            proc.kill()

    async def run(self, text: str, mode: str = "build") -> str:
        if self.attempt_id:
            from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal

            # The run is bound to the pre-seeded attempt. A missing document
            # fails the prompt instead of looking like a successful bind.
            loaded = ToolExecutionJournal().load(self.attempt_id)
            if loaded is None:
                raise FileNotFoundError(
                    f"stub attempt {self.attempt_id} has no journal document"
                )
            self.bound_attempt = loaded
        if (
            os.environ.get("RXYCODE_APPSERVER_STUB") == "1"
            and os.environ.get("RXYCODE_STUB_PROMPT_REPLIES_FILE")
        ):
            reply = next_prompt_reply()
            if reply == "(stalled-worker-silence)" or (
                os.environ.get("RXYCODE_STUB_STALL_AFTER_PROMPT") == "1" and reply is None
            ):
                while not self._cancelled:
                    await asyncio.sleep(0.05)
                return "stub:cancelled"
            if reply is not None:
                return reply
        if text.startswith("think:"):
            thought = text[6:] or "stub-thought"
            self._last_thinking = thought
            self._thinking_history.append(thought)
            tui = None
            try:
                from .runtime import get_bound_tui
                tui = get_bound_tui()
            except ImportError:
                try:
                    from appserver.runtime import get_bound_tui
                    tui = get_bound_tui()
                except ImportError:
                    tui = None
            if tui is None:
                try:
                    from utils.tui import get_tui
                except ImportError:
                    from ..utils.tui import get_tui
                tui = get_tui()
            if tui is not None and hasattr(tui, "write_reasoning"):
                tui.write_reasoning(thought)
            return f"stub:{thought}"
        if text.startswith("barrier:"):
            label = text.split(":", 1)[1]
            barrier = os.environ.get("RXYCODE_APPSERVER_STUB_BARRIER_DIR")
            if barrier:
                root = Path(barrier)
                root.mkdir(parents=True, exist_ok=True)
                (root / f"{label}.ready").write_text("ready", encoding="utf-8")
                release = root / "release"
                for _ in range(400):
                    if release.exists():
                        break
                    await asyncio.sleep(0.05)
            return f"stub:{label}"
        if text.startswith("slow:"):
            await asyncio.sleep(0.5)
            return f"stub:{text[5:]}"
        if text.startswith("silent:"):
            try:
                seconds = max(0.0, float(text[7:]))
            except ValueError:
                seconds = 3.0
            await asyncio.sleep(seconds)
            return "stub:silent-complete"
        if text.startswith("hang:"):
            # Stall grace has to observe this job. task.cancel() would otherwise
            # end the turn in the same tick as interrupt, and both a 1s grace
            # and a long grace would be kept. Stay past one 1s grace poll, then
            # surface the cancel so a long grace still sees the job leave.
            try:
                while not self._cancelled:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    current.uncancel()
                await asyncio.sleep(1.25)
                raise
            await asyncio.sleep(1.25)
            raise asyncio.CancelledError
        if text.startswith("fail:"):
            return f"[agent error] {text[5:]}"
        if "trigger-approval" in text:
            broker = get_approval_broker()
            if broker is not None:
                decision = await broker.request_approval(
                    ApprovalRequest(
                        tool_name="write_file",
                        args_summary={"path": "demo.txt"},
                        risk=RiskLevel.WRITE,
                    )
                )
                return f"approval:{decision.value}"
        return f"stub:{text}"

    def cancel(self) -> bool:
        self._cancelled = True
        return True
