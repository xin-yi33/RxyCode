"""Stub agent for appserver integration tests (no LLM)."""

from __future__ import annotations

import asyncio

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
        if text.startswith("hang:"):
            await asyncio.sleep(3600.0)
            return f"stub:{text[5:]}"
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