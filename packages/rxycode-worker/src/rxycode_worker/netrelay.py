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


async def start_relay(listen_port: int, egress_sock: str | Path) -> asyncio.AbstractServer | None:
    """Listen on loopback and bridge each connection to the egress socket.

    Returns the running server, or ``None`` when either side is unavailable
    (the turn then runs fully offline — still confined)."""

    async def _bridge(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            up_r, up_w = await asyncio.open_unix_connection(str(egress_sock))
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

    if not Path(egress_sock).exists():
        _LOG.warning("egress socket %s missing; turn runs offline", egress_sock)
        return None
    try:
        return await asyncio.start_server(_bridge, "127.0.0.1", int(listen_port))
    except OSError:
        _LOG.warning("egress relay bind failed on :%s", listen_port, exc_info=True)
        return None
