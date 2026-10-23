"""Local kill switch. It runs before any cloud acknowledgement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rxycode_runner.local.audit import AuditLog
from rxycode_runner.local.supervisor import ProcessSupervisor

_BOUND: dict[str, "EmergencyStop"] = {}


@dataclass
class StopResult:
    ok: bool
    waited_for_cloud: bool


class EmergencyStop:
    def __init__(
        self,
        supervisor: ProcessSupervisor,
        *,
        audit: AuditLog | None = None,
        cloud_ack: Callable[[], None] | None = None,
    ) -> None:
        self.supervisor = supervisor
        self.audit = audit
        self.cloud_ack = cloud_ack

    def press(self) -> StopResult:
        self.supervisor.kill_tree()
        from rxycode_runner.local.grant_store import installed_stores

        for store in installed_stores():
            store.revoke_all()
        cloud = ""
        if self.cloud_ack is not None:
            try:
                self.cloud_ack()
            except OSError as exc:
                cloud = str(exc)
        if self.audit is not None:
            self.audit.write(
                {
                    "event": "emergency_stop",
                    "cloud": cloud or "not_sent",
                }
            )
        return StopResult(ok=True, waited_for_cloud=False)


def bind_local_hotkey(stop: EmergencyStop) -> None:
    """Remember the local switch. A tray click and a hotkey both call press."""
    _BOUND["local"] = stop


def press_local_hotkey() -> StopResult:
    stop = _BOUND.get("local")
    if stop is None:
        raise RuntimeError("no local emergency stop")
    return stop.press()
