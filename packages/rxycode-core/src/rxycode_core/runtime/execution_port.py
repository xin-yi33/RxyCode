"""Capability port. ToolSpec does not grant permission. Native calls need the gate."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass

class DispatchGrant:
    """Mutable so a child task that copied the context sees the close."""

    __slots__ = ("open",)

    def __init__(self) -> None:
        self.open = True


_PORT: ContextVar[ExecutionPort | None] = ContextVar("rxycode_execution_port", default=None)
_NATIVE: ContextVar[DispatchGrant | None] = ContextVar("rxycode_native_dispatch", default=None)
_DEFAULT: ExecutionPort | None = None


@dataclass(frozen=True)
class Capabilities:
    """What one target can do. This is not a permission grant."""

    names: frozenset[str]

    def __post_init__(self) -> None:
        if any(not isinstance(name, str) or not name for name in self.names):
            raise ValueError("capability names must be non-empty strings")

    def allows(self, capability: str) -> bool:
        return capability in self.names

    def to_dict(self) -> dict[str, list[str]]:
        return {"names": sorted(self.names)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Capabilities:
        names = data.get("names")
        if not isinstance(names, list):
            raise ValueError("capabilities.names must be a list")
        return cls(frozenset(str(name) for name in names))


@dataclass(frozen=True)
class ToolSpec:
    """Declared tool shape. Declaration never authorizes execution."""

    name: str
    version: int
    required_capability: str

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("tool spec version must be >= 1")
        if not self.name or not self.required_capability:
            raise ValueError("tool spec name and capability are required")

    def allows_execute(self) -> bool:
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "required_capability": self.required_capability,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ToolSpec:
        return cls(
            name=str(data["name"]),
            version=int(data["version"]),
            required_capability=str(data["required_capability"]),
        )


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
        if not native_dispatch_open():
            return _blocked_event(call)
        return runner()

    async def ainvoke(self, call: object, runner: Callable[[], object]) -> ToolEvent:
        """Run the OS operation. The runner is the terminal tool body."""
        if not native_dispatch_open():
            return _blocked_event(call)
        result = runner()
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, ToolEvent):
            return result
        return ToolEvent(
            ok=True,
            status="OK",
            tool=str(getattr(call, "name", "")),
            target_id=str(getattr(call, "target_id", "")),
            text=str(result),
            version=int(getattr(call, "version", 1) or 1),
        )


class ExecutionPort:
    def __init__(self) -> None:
        self.targets: dict[str, Capabilities] = {}
        self.specs: dict[str, ToolSpec] = {}
        self.backend = NativeBackend()
        self.local_full: object | None = None

    def register_local_full(self, backend: object) -> None:
        self.local_full = backend

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


def native_dispatch_open() -> bool:
    grant = _NATIVE.get()
    return grant is not None and grant.open


def authorize_native_dispatch() -> Token[DispatchGrant | None]:
    """Called only by ToolOrchestrator after approval and journaling."""
    return _NATIVE.set(DispatchGrant())


def reset_native_dispatch(token: Token[DispatchGrant | None]) -> None:
    grant = _NATIVE.get()
    if grant is not None:
        grant.open = False
    _NATIVE.reset(token)


def default_execution_port() -> ExecutionPort:
    """Process port used when a caller did not bind one. It grants no capability."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ExecutionPort()
    return _DEFAULT


def _blocked_event(call: object) -> ToolEvent:
    return ToolEvent(
        ok=False,
        status="BLOCKED",
        tool=str(getattr(call, "name", "")),
        target_id=str(getattr(call, "target_id", "")),
        text="[blocked: native backend requires ToolOrchestrator]",
        version=int(getattr(call, "version", 1) or 1),
    )
