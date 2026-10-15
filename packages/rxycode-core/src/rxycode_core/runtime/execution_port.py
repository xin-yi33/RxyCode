"""Capability port. ToolSpec does not grant permission. Native calls need the gate."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass

_PORT: ContextVar[ExecutionPort | None] = ContextVar("rxycode_execution_port", default=None)
_NATIVE: ContextVar[bool] = ContextVar("rxycode_native_dispatch", default=False)


@dataclass(frozen=True)
class Capabilities:
    """What one target can do. This is not a permission grant."""

    names: frozenset[str]

    def allows(self, capability: str) -> bool:
        return capability in self.names


@dataclass(frozen=True)
class ToolSpec:
    """Declared tool shape. Declaration never authorizes execution."""

    name: str
    version: int
    required_capability: str

    def allows_execute(self) -> bool:
        return False


@dataclass(frozen=True)
class ToolEvent:
    ok: bool
    status: str
    tool: str
    target_id: str
    text: str
    version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "tool": self.tool,
            "target_id": self.target_id,
            "text": self.text,
            "version": self.version,
        }


class NativeBackend:
    """OS-facing call. Refuses to run unless ToolOrchestrator authorized this task."""

    def invoke(self, call: object, runner: Callable[[], ToolEvent]) -> ToolEvent:
        if not _NATIVE.get():
            return ToolEvent(
                ok=False,
                status="BLOCKED",
                tool=str(getattr(call, "name", "")),
                target_id=str(getattr(call, "target_id", "")),
                text="[blocked: native backend requires ToolOrchestrator]",
                version=int(getattr(call, "version", 1) or 1),
            )
        return runner()


class ExecutionPort:
    def __init__(self) -> None:
        self.targets: dict[str, Capabilities] = {}
        self.specs: dict[str, ToolSpec] = {}
        self.backend = NativeBackend()

    def register_target(self, target_id: str, capabilities: Capabilities) -> None:
        self.targets[target_id] = capabilities

    def register_spec(self, spec: ToolSpec) -> None:
        self.specs[spec.name] = spec

    def capability_denial(self, name: str, args: object) -> str | None:
        spec = self.specs.get(name)
        if spec is None:
            return None
        target_id = ""
        if isinstance(args, dict):
            target_id = str(args.get("target") or args.get("target_id") or "")
        capabilities = self.targets.get(target_id)
        if capabilities is None or not capabilities.allows(spec.required_capability):
            shown = target_id or "(missing)"
            return (
                f"[blocked: target {shown} lacks capability "
                f"{spec.required_capability} for {name}]"
            )
        return None


def bind_execution_port(port: ExecutionPort) -> Token[ExecutionPort | None]:
    return _PORT.set(port)


def reset_execution_port(token: Token[ExecutionPort | None]) -> None:
    _PORT.reset(token)


def current_execution_port() -> ExecutionPort | None:
    return _PORT.get()


def authorize_native_dispatch() -> Token[bool]:
    """Called only by ToolOrchestrator after approval and journaling."""
    return _NATIVE.set(True)


def reset_native_dispatch(token: Token[bool]) -> None:
    _NATIVE.reset(token)
