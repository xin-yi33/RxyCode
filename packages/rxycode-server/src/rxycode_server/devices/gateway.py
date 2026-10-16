"""Device handshake, online TTL, and the Devices API. The runner dials out."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket

from rxycode_server.devices.pairing import PairingBook, PairingRejected

logger = logging.getLogger(__name__)

_PROTOCOL = "1.1.0"
_SCOPE = "device"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class DeviceRecord:
    tenant_id: str
    os_name: str
    capabilities: list[str]
    scope: str
    token_hash: str
    session_id: str
    last_seen: float


class Registry:
    def __init__(self, *, clock: Callable[[], float], pairing_ttl: float, ttl: float) -> None:
        self.clock = clock
        self.ttl = ttl
        self.browsers: dict[str, str] = {}
        self.devices: dict[str, DeviceRecord] = {}
        self.sockets: dict[str, WebSocket] = {}
        self.pairings = PairingBook(clock=clock, ttl=pairing_ttl)

    def open_browser(self, tenant_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.browsers[token] = tenant_id
        return token

    def tenant_for_browser(self, token: str) -> str:
        tenant_id = self.browsers.get(token)
        if tenant_id is None:
            raise HTTPException(status_code=401, detail="UNAUTHORIZED")
        return tenant_id

    def issue(self, tenant_id: str) -> str:
        return self.pairings.issue(tenant_id)

    def tool_permission(self, device_id: str) -> bool:
        device = self.devices.get(device_id)
        if device is None or not self._online(device):
            return False
        return device.scope == _SCOPE

    def session_id(self, device_id: str) -> str:
        device = self.devices.get(device_id)
        if device is None or not self._online(device):
            return ""
        return device.session_id

    def scope(self, device_id: str) -> str:
        device = self.devices.get(device_id)
        if device is None:
            return ""
        return device.scope

    def token_accepted(self, token: str) -> bool:
        digest = _hash(token)
        return any(device.token_hash == digest for device in self.devices.values())

    def list_for(self, tenant_id: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for device_id, device in self.devices.items():
            if device.tenant_id != tenant_id:
                continue
            rows.append(
                {
                    "id": device_id,
                    "os": device.os_name,
                    "capabilities": list(device.capabilities),
                    "scope": device.scope,
                    "online": self._online(device),
                }
            )
        return rows

    def hello(self, payload: dict[str, object], socket: WebSocket) -> dict[str, object]:
        version = str(payload.get("protocol_version") or "")
        if version != _PROTOCOL:
            return {"type": "reject", "code": "BAD_VERSION", "tool_permission": False}
        device_id = str(payload.get("device_id") or "")
        if not device_id:
            return {"type": "reject", "code": "BAD_DEVICE", "tool_permission": False}
        presented = str(payload.get("token") or "")
        if presented:
            current = self.devices.get(device_id)
            if current is None or current.token_hash != _hash(presented):
                return {"type": "reject", "code": "BAD_TOKEN", "tool_permission": False}
            tenant_id = current.tenant_id
            os_name = current.os_name
            capabilities = list(current.capabilities)
        else:
            try:
                tenant_id = self.pairings.redeem(str(payload.get("pairing_code") or ""))
            except PairingRejected as exc:
                return {"type": "reject", "code": exc.code, "tool_permission": False}
            os_name = str(payload.get("os") or "")
            raw_caps = payload.get("capabilities") or []
            capabilities = [str(item) for item in raw_caps] if isinstance(raw_caps, list) else []
        token = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        self.devices[device_id] = DeviceRecord(
            tenant_id=tenant_id,
            os_name=os_name,
            capabilities=capabilities,
            scope=_SCOPE,
            token_hash=_hash(token),
            session_id=session_id,
            last_seen=self.clock(),
        )
        previous = self.sockets.get(device_id)
        self.sockets[device_id] = socket
        if previous is not None and previous is not socket:
            _close_later(previous)
        logger.info("device online", extra={"device_id": device_id})
        return {
            "type": "hello_ok",
            "session_id": session_id,
            "token": token,
            "scope": _SCOPE,
            "tool_permission": True,
        }

    def touch(self, device_id: str, session_id: str) -> None:
        device = self.devices.get(device_id)
        if device is None or device.session_id != session_id:
            return
        device.last_seen = self.clock()

    def detach(self, device_id: str, socket: WebSocket) -> None:
        if self.sockets.get(device_id) is socket:
            self.sockets.pop(device_id, None)

    def _online(self, device: DeviceRecord) -> bool:
        live = self.sockets.get(_device_id_for(self, device))
        if live is None:
            return False
        return (self.clock() - device.last_seen) <= self.ttl


def _device_id_for(registry: Registry, device: DeviceRecord) -> str:
    for device_id, current in registry.devices.items():
        if current is device:
            return device_id
    return ""


def _close_later(socket: WebSocket) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_close(socket))


async def _close(socket: WebSocket) -> None:
    try:
        await socket.close()
    except Exception:
        logger.info("previous device socket closed")


def create_device_app(
    *,
    clock: Callable[[], float] | None = None,
    pairing_ttl: float = 300.0,
    ttl: float = 30.0,
) -> FastAPI:
    app = FastAPI(title="RxyCode Devices")
    app.state.device_registry = Registry(
        clock=clock or time.time,
        pairing_ttl=pairing_ttl,
        ttl=ttl,
    )
    app.include_router(build_router())
    return app


def build_router() -> APIRouter:
    router = APIRouter()

    def registry(request: Request) -> Registry:
        return request.app.state.device_registry

    @router.post("/api/v1/devices/browser-sessions")
    def open_browser(body: dict[str, str], request: Request) -> dict[str, str]:
        tenant_id = str(body.get("tenant_id") or "")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="TENANT_REQUIRED")
        token = registry(request).open_browser(tenant_id)
        return {"token": token}

    @router.post("/api/v1/devices/pairings")
    def issue_pairing(request: Request) -> dict[str, str]:
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip()
        book = registry(request)
        tenant_id = book.tenant_for_browser(token)
        return {"code": book.issue(tenant_id)}

    @router.get("/api/v1/devices")
    def list_devices(request: Request) -> dict[str, object]:
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip()
        book = registry(request)
        tenant_id = book.tenant_for_browser(token)
        return {"devices": book.list_for(tenant_id)}

    @router.websocket("/api/v1/devices/socket")
    async def device_socket(socket: WebSocket) -> None:
        await socket.accept()
        book: Registry = socket.app.state.device_registry
        device_id = ""
        try:
            raw = await socket.receive_text()
            payload = json.loads(raw)
            device_id = str(payload.get("device_id") or "")
            reply = book.hello(payload, socket)
            await socket.send_text(json.dumps(reply))
            if reply["type"] != "hello_ok":
                return
            session_id = str(reply["session_id"])
            while True:
                incoming = json.loads(await socket.receive_text())
                if incoming.get("type") == "heartbeat":
                    book.touch(device_id, str(incoming.get("session_id") or session_id))
        except Exception:
            logger.info("device socket ended", extra={"device_id": device_id})
        finally:
            if device_id:
                book.detach(device_id, socket)

    return router


class RunningGateway:
    def __init__(self, app: FastAPI, server: uvicorn.Server, thread: threading.Thread, port: int) -> None:
        self.app = app
        self.server = server
        self.thread = thread
        self.port = port
        self.http = f"http://127.0.0.1:{port}"
        self.ws = f"ws://127.0.0.1:{port}/api/v1/devices/socket"

    def _registry(self) -> Registry:
        return self.app.state.device_registry

    def session_id(self, device_id: str) -> str:
        return self._registry().session_id(device_id)

    def scope(self, device_id: str) -> str:
        return self._registry().scope(device_id)

    def tool_permission(self, device_id: str) -> bool:
        return self._registry().tool_permission(device_id)

    def token_accepted(self, token: str) -> bool:
        return self._registry().token_accepted(token)

    def client_token(self, device_id: str) -> str:
        from rxycode_runner.remote.client import token_for

        return token_for(device_id)

    def writer_count(self, device_id: str) -> int:
        from rxycode_runner.remote.client import writer_count

        return writer_count(device_id)

    def drop(self) -> None:
        registry = self._registry()
        sockets = list(registry.sockets.values())

        async def _drop() -> None:
            for socket in sockets:
                try:
                    await socket.close()
                except Exception:
                    logger.info("dropped device socket")

        server_loop = getattr(self.server, "_rxy_loop", None)
        if server_loop is None:
            raise RuntimeError("device gateway loop is not running")
        asyncio.run_coroutine_threadsafe(_drop(), server_loop).result(timeout=5)
        for device_id, socket in list(registry.sockets.items()):
            if socket in sockets:
                registry.sockets.pop(device_id, None)

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def serve_in_thread(
    *,
    clock: Callable[[], float] | None = None,
    pairing_ttl: float = 300.0,
    ttl: float = 30.0,
) -> RunningGateway:
    app = create_device_app(clock=clock, pairing_ttl=pairing_ttl, ttl=ttl)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    ready = threading.Event()

    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server._rxy_loop = loop  # type: ignore[attr-defined]

        async def go() -> None:
            task = loop.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.01)
            ready.set()
            await task

        loop.run_until_complete(go())
        loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not ready.wait(timeout=10):
        raise RuntimeError("device gateway did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    return RunningGateway(app, server, thread, port)
