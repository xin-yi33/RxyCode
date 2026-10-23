"""In-sandbox loopback relay — runs INSIDE the confined net namespace.

``bwrap --unshare-net`` leaves the turn with a private network namespace
containing only ``lo`` (which starts down). This module, executed by the
confined turn itself:

1. brings ``lo`` up (the turn is mapped-root inside its own userns+netns,
   so ``SIOCSIFFLAGS`` needs no host privilege), and
2. relays ``127.0.0.1:<port>`` <-> the parent-owned egress UNIX socket, so
   ordinary ``HTTP_PROXY``/``HTTPS_PROXY``-aware clients (httpx, requests,
   pip, npm, curl, git, Playwright) get proxied connectivity.

The relay is deliberately dumb: every policy decision lives in the
parent-side ``egress.EgressProxy``. The worst a compromised turn can do is
kill its own connectivity — it cannot widen the filter.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import socket
import struct
import threading
from pathlib import Path

_LOG = logging.getLogger(__name__)

SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
IFF_UP = 0x1
IFF_RUNNING = 0x40


def bring_up_loopback() -> bool:
    """Raise ``lo`` inside this net namespace. False = no connectivity —
    callers treat that as honest failure, never as a reason to weaken the
    boundary."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return False
    try:
        ifreq = struct.pack("16sH22s", b"lo", 0, b"")
        flags = struct.unpack("16sH22s", fcntl.ioctl(sock, SIOCGIFFLAGS, ifreq))[1]
        if not (flags & IFF_UP):
            fcntl.ioctl(
                sock,
                SIOCSIFFLAGS,
                struct.pack("16sH22s", b"lo", flags | IFF_UP | IFF_RUNNING, b""),
            )
        return True
    except OSError:
        return False
    finally:
        sock.close()


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    try:
        writer.write_eof()
    except (OSError, AttributeError):
        pass


class EgressRelay:
    """Loopback->egress-socket relay on a dedicated thread and event loop.

    The relay is the confined turn's only network lifeline, so it must not
    share fate with the agent's event loop: synchronous blocking calls in
    agent code (e.g. a tokenizer downloading its vocab through
    ``HTTPS_PROXY``) would otherwise freeze the loop that is supposed to
    deliver their responses — a self-deadlock (audit W7 deploy stall)."""

    def __init__(self, listen_port: int, egress_sock: str | Path) -> None:
        self._port = int(listen_port)
        self._egress_sock = str(egress_sock)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._thread: threading.Thread | None = None

    async def _bridge(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            up_r, up_w = await asyncio.open_unix_connection(self._egress_sock)
        except OSError:
            writer.close()
            return
        try:
            await asyncio.gather(_pump(reader, up_w), _pump(up_r, writer))
        finally:
            for w in (up_w, writer):
                try:
                    w.close()
                except Exception:
                    pass

    async def _shutdown(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _thread_main(self, ready: threading.Event, failed: list[bool]) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._server = loop.run_until_complete(
                asyncio.start_server(self._bridge, "127.0.0.1", self._port)
            )
        except OSError:
            _LOG.warning(
                "egress relay bind failed on :%s", self._port, exc_info=True
            )
            failed.append(True)
            ready.set()
            loop.close()
            return
        ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            except Exception:
                pass
            loop.close()

    def start(self) -> bool:
        ready = threading.Event()
        failed: list[bool] = []
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(ready, failed),
            name="egress-relay",
            daemon=True,
        )
        self._thread.start()
        ready.wait(timeout=10)
        return not failed and self._server is not None

    def close(self) -> None:
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)


def start_relay(listen_port: int, egress_sock: str | Path) -> EgressRelay | None:
    """Start the loopback relay on its own thread.

    Returns the running relay, or ``None`` when either side is unavailable
    (the turn then runs fully offline — still confined)."""
    if not Path(egress_sock).exists():
        _LOG.warning("egress socket %s missing; turn runs offline", egress_sock)
        return None
    relay = EgressRelay(listen_port, egress_sock)
    return relay if relay.start() else None
