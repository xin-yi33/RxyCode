"""WEB-W4-C01. Ask mode still uses the approval broker. Full does not."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
if str(_RUNNER) not in sys.path:
    sys.path.insert(0, str(_RUNNER))


def test_w4_c01_integration(tmp_path: Path) -> None:
    """The same command is rejected under ask and runs under full."""
    from core.safety.approval import (
        ApprovalBroker,
        ApprovalDecision,
        set_approval_broker,
    )
    from rxycode_runner.local.native_backend import LocalNativeBackend

    asked: list[str] = []

    class Reject(ApprovalBroker):
        async def _ask(self, request: object) -> ApprovalDecision:
            asked.append(str(getattr(request, "tool_name", "")))
            return ApprovalDecision.REJECTED

    set_approval_broker(Reject())
    try:
        argv = [sys.executable, "-c", "print('ran')"]
        ask = LocalNativeBackend(target="local", permission="ask")
        refused = asyncio.run(ask.shell(argv, tmp_path))
        assert refused.started is False
        assert refused.approval == "rejected"
        assert asked == ["shell"]
        marker = tmp_path / "ran.txt"
        full = LocalNativeBackend(target="local", permission="full")
        ran = asyncio.run(
            full.shell(
                [sys.executable, "-c", f"open(r'{marker}', 'w', encoding='utf-8').write('ok')"],
                tmp_path,
            )
        )
        assert ran.started is True
        assert ran.exit_code == 0
        assert marker.read_text(encoding="utf-8") == "ok"
        assert asked == ["shell"]
    finally:
        set_approval_broker(None)
