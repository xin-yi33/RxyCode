"""Stub agent for appserver integration tests (no LLM)."""

from __future__ import annotations

import asyncio

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


class StubAgent:
    """Deterministic agent used when ``RXYCODE_APPSERVER_STUB=1``."""

    def __init__(self) -> None:
        self._thinking_history: list[str] = []
        self._last_thinking = ""
        self._cancelled = False
        self.model_config = {"model_name": "stub"}

    async def run(self, text: str, mode: str = "build") -> str:
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
            while not self._cancelled:
                await asyncio.sleep(0.05)
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
