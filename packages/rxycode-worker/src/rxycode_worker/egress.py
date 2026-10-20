"""Filtered egress proxy for confined turns — the network boundary.

The sandbox runs with ``--unshare-net``: the turn's network namespace has
only loopback. A tiny in-turn relay bridges ``127.0.0.1:<port>`` to this
UNIX socket, so every byte of network the turn can produce must come
through here — Bash, Python, MCP and browser subprocesses alike (they all
inherit ``HTTP_PROXY``/``HTTPS_PROXY`` pointing at the loopback relay).
``webfetch``-level checks could never be the boundary; this is.

Policy (decided by the PARENT, outside the execution environment; Full
mode and user approvals cannot touch it):

* ``CONNECT host:port`` — allowed only when every resolved address is a
  public/global IP and ``port`` is 80/443, or ``host:port`` is explicitly
  allowlisted (the configured model endpoint plus
  ``RXYCODE_WORKER_EGRESS_ALLOW`` entries — that is how an in-cluster model
  relay stays reachable while the rest of the private range stays shut).
* Absolute-URI plain-HTTP requests (``GET http://h/p``) — same filter on
  the origin host; the request line is rewritten to origin form.
* Everything else — refused. Link-local metadata (169.254.169.254),
  loopback, private/ULA ranges, multicast and non-standard ports die here
  before a single TCP SYN leaves the worker.

DNS is resolved by the parent and the connection is opened to the resolved
address, so the turn can neither exfiltrate via DNS nor re-resolve to a
private address between check and connect.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

_LOG = logging.getLogger(__name__)

_MAX_HEAD = 16384
_ALLOWED_PORTS = {80, 443}


def _ip_blocked(addr: str) -> bool:
    """True for any address a confined turn must never reach."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # unparseable — refuse closed
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return not bool(ip.is_global)


def _normalize_host(host: str) -> str:
    host = str(host or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def build_allowlist(*sources: str) -> set[tuple[str, int]]:
    """Parse ``host[:port]`` entries (default port 443) into an allowlist.

    Sources: the worker's model base URL and ``RXYCODE_WORKER_EGRESS_ALLOW``
    (comma-separated). Public endpoints pass the ordinary filter anyway —
    the allowlist exists for private/in-cluster ones the operator chose.
    """
    allowed: set[tuple[str, int]] = set()
    for source in sources:
        for part in str(source or "").split(","):
            part = part.strip()
            if not part:
                continue
            if "://" in part:
                part = urlsplit(part).netloc
            host = part
            port = 443
            if part.startswith("[") and "]" in part:
                host, _, rest = part[1:].partition("]")
                if rest.startswith(":"):
                    try:
                        port = int(rest[1:])
                    except ValueError:
                        port = 443
            elif part.count(":") == 1:
                host, _, tail = part.rpartition(":")
                try:
                    port = int(tail)
                except ValueError:
                    host, port = part, 443
            host = _normalize_host(host)
            if host and 0 < port < 65536:
                allowed.add((host, port))
    return allowed


def egress_allowlist_from_env(env: dict[str, str] | None = None) -> set[tuple[str, int]]:
    env = env if env is not None else dict(os.environ)
    return build_allowlist(
        env.get("RXYCODE_LLM_BASE_URL", ""),
        env.get("RXYCODE_WORKER_EGRESS_ALLOW", ""),
    )


class ModelGateway:
    """Credential-carrying loopback gateway for the platform model endpoint.

    The confined turn's model client talks plain HTTP to
    ``127.0.0.1:<egress_port>``; the relay lands those origin-form requests
    here and the PARENT forwards them to the real configured upstream —
    injecting the real auth headers and stripping whatever the child sent.
    The platform model key therefore never exists inside the sandbox at
    all: not in env, not in the copied config, not in mounts.
    """

    __slots__ = ("scheme", "host", "port", "base_path", "headers")

    def __init__(
        self,
        *,
        scheme: str,
        host: str,
        port: int,
        base_path: str,
        headers: dict[str, str],
    ) -> None:
        self.scheme = scheme
        self.host = host
        self.port = port
        self.base_path = base_path
        self.headers = headers


def model_gateway_from_env(env: dict[str, str] | None = None) -> ModelGateway | None:
    """Resolve the deployed model endpoint into a gateway, or None.

    Parent-side only: reads the real ``RXYCODE_LLM_BASE_URL`` /
    ``RXYCODE_API_KEY``. No configured endpoint → no gateway → in-turn
    model calls refuse honestly instead of leaking a key."""
    env = env if env is not None else dict(os.environ)
    base = str(env.get("RXYCODE_LLM_BASE_URL", "") or "").strip()
    key = str(env.get("RXYCODE_API_KEY", "") or "").strip()
    if not base:
        return None
    split = urlsplit(base if "://" in base else f"http://{base}")
    scheme = (split.scheme or "http").lower()
    if scheme not in {"http", "https"}:
        return None
    host = _normalize_host(split.hostname or "")
    if not host:
        return None
    try:
        port = int(split.port or (443 if scheme == "https" else 80))
    except ValueError:
        return None
    headers: dict[str, str] = {}
    if key:
        # Bearer covers OpenAI-compatible endpoints (and is also accepted by
        # Anthropic); x-api-key / api-key cover the anthropic/azure shapes.
        headers["authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
        headers["api-key"] = key
    return ModelGateway(
        scheme=scheme,
        host=host,
        port=port,
        base_path=(split.path or "").rstrip("/"),
        headers=headers,
    )


class EgressVerdict:
    __slots__ = ("allowed", "reason", "addresses")

    def __init__(self, allowed: bool, reason: str, addresses: list[str]) -> None:
        self.allowed = allowed
        self.reason = reason
        self.addresses = addresses


async def evaluate(
    host: str,
    port: int,
    allowlist: set[tuple[str, int]],
    *,
    resolve=None,
) -> EgressVerdict:
    """Decide one egress target. Resolution runs through ``getaddrinfo`` on
    the loop (or the injected resolver for tests) — never inside the
    sandbox."""
    host = _normalize_host(host)
    if not host or not (0 < int(port) < 65536):
        return EgressVerdict(False, "bad_target", [])
    if (host, int(port)) in allowlist:
        return EgressVerdict(True, "allowlisted", [host])
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            if resolve is not None:
                infos = await resolve(host, port)
            else:
                infos = await asyncio.get_running_loop().getaddrinfo(
                    host, int(port), type=socket.SOCK_STREAM
                )
            addresses = sorted({str(item[4][0]) for item in infos})
        except Exception:
            return EgressVerdict(False, "resolve_failed", [])
    if not addresses:
        return EgressVerdict(False, "resolve_empty", [])
    if any(_ip_blocked(addr) for addr in addresses):
        return EgressVerdict(False, "private_or_reserved", addresses)
    if int(port) not in _ALLOWED_PORTS:
        return EgressVerdict(False, "port_not_allowed", addresses)
    return EgressVerdict(True, "public", addresses)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.TimeoutError):
        pass
    try:
        # TLS transports cannot half-close: write_eof() raises
        # NotImplementedError there, which used to tear the tunnel down.
        if writer.can_write_eof():
            writer.write_eof()
    except (OSError, AttributeError, NotImplementedError):
        pass


class EgressProxy:
    """UNIX-socket CONNECT/forward proxy owned by the drain for one run."""

    def __init__(
        self,
        sock_path: Path,
        allowlist: set[tuple[str, int]],
        *,
        gateway: ModelGateway | None = None,
    ) -> None:
        self.sock_path = Path(sock_path)
        self.allowlist = set(allowlist)
        self.gateway = gateway
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self.sock_path)
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        try:
            self.sock_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._serve(reader, writer)
        except Exception:
            _LOG.warning("egress request failed", exc_info=True)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15.0)
        if len(head) > _MAX_HEAD:
            return
        try:
            text = head.decode("iso-8859-1")
        except UnicodeDecodeError:
            return
        lines = text.split("\r\n")
        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            return
        method = parts[0].upper()
        if method == "CONNECT":
            host, port = _split_authority(parts[1])
            await self._connect(reader, writer, host, port)
            return
        # Model gateway: origin-form requests only reach the relay when the
        # child's model client pointed its base_url at 127.0.0.1 — forward
        # them to the configured upstream with the parent's credentials.
        target = parts[1]
        if target.startswith("/") and self.gateway is not None:
            await self._gateway_serve(reader, writer, method, target, lines[1:])
            return
        # Forward-proxy origin handling: absolute-URI only.
        if target.lower().startswith("http://"):
            split = urlsplit(target)
            host, port = split.hostname or "", split.port or 80
            await self._forward(reader, writer, method, split, host, port, lines[1:])
            return
        writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()

    def _refuse(self, writer: asyncio.StreamWriter, code: int, label: str) -> None:
        body = f"egress blocked: {label}\n".encode("utf-8")
        writer.write(
            f"HTTP/1.1 {code} {label}\r\nContent-Length: {len(body)}\r\n\r\n".encode(
                "ascii", "replace"
            )
            + body
        )

    async def _connect(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
    ) -> None:
        verdict = await evaluate(host, port, self.allowlist)
        if not verdict.allowed:
            _LOG.info("egress CONNECT refused %s:%s (%s)", host, port, verdict.reason)
            self._refuse(writer, 403, f"Forbidden_{verdict.reason}")
            await writer.drain()
            return
        address = verdict.addresses[0] if verdict.addresses else host
        try:
            upstream_r, upstream_w = await asyncio.open_connection(address, int(port))
        except OSError:
            self._refuse(writer, 502, "Bad_Gateway")
            await writer.drain()
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await self._tunnel(reader, writer, upstream_r, upstream_w)

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        method: str,
        split,
        host: str,
        port: int,
        header_lines: list[str],
    ) -> None:
        verdict = await evaluate(host, port, self.allowlist)
        if not verdict.allowed:
            _LOG.info("egress %s refused %s:%s (%s)", method, host, port, verdict.reason)
            self._refuse(writer, 403, f"Forbidden_{verdict.reason}")
            await writer.drain()
            return
        address = verdict.addresses[0] if verdict.addresses else host
        try:
            upstream_r, upstream_w = await asyncio.open_connection(address, int(port))
        except OSError:
            self._refuse(writer, 502, "Bad_Gateway")
            await writer.drain()
            return
        path = split.path or "/"
        if split.query:
            path += "?" + split.query
        kept = [
            line
            for line in header_lines
            if line and not line.lower().startswith("proxy-")
        ]
        upstream_w.write(
            f"{method} {path} HTTP/1.1\r\n".encode("ascii", "replace")
            + "\r\n".join(kept).encode("iso-8859-1")
            + b"\r\n\r\n"
        )
        await upstream_w.drain()
        await self._tunnel(reader, writer, upstream_r, upstream_w)

    async def _gateway_serve(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        method: str,
        path: str,
        header_lines: list[str],
    ) -> None:
        """Plain-HTTP reverse proxy to the configured model upstream.

        Runs entirely in the parent: resolves+connects to the real endpoint,
        injects the real auth, drops every credential-shaped header the
        child sent. The child's ``Bearer confined`` placeholder is removed,
        never trusted."""
        gateway = self.gateway
        assert gateway is not None
        ssl_ctx = None
        if gateway.scheme == "https":
            import ssl as _ssl

            ssl_ctx = _ssl.create_default_context()
        try:
            upstream_r, upstream_w = await asyncio.open_connection(
                gateway.host,
                gateway.port,
                ssl=ssl_ctx,
                server_hostname=gateway.host if ssl_ctx else None,
            )
        except OSError:
            self._refuse(writer, 502, "Bad_Gateway")
            await writer.drain()
            return
        upstream_w.write(_gateway_head(gateway, method, path, header_lines))
        await upstream_w.drain()
        await self._tunnel(reader, writer, upstream_r, upstream_w)

    async def _tunnel(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        upstream_r: asyncio.StreamReader,
        upstream_w: asyncio.StreamWriter,
    ) -> None:
        try:
            await asyncio.gather(
                _pipe(reader, upstream_w),
                _pipe(upstream_r, writer),
            )
        finally:
            try:
                upstream_w.close()
            except Exception:
                pass


def _gateway_head(
    gateway: ModelGateway,
    method: str,
    path: str,
    header_lines: list[str],
) -> bytes:
    """Build the upstream request head for one gateway hop.

    Rewrites the path under the configured base, rewrites Host, injects the
    real auth headers and drops every credential-shaped header the child
    sent. Content-Length/Transfer-Encoding pass through: the raw body is
    piped verbatim, so the upstream must see the same framing the client
    sent or the request body is lost."""
    upstream_path = f"{gateway.base_path}{path}" or "/"
    kept: list[str] = []
    for line in header_lines:
        if not line:
            continue
        name = line.split(":", 1)[0].strip().lower()
        if name in {
            "host",
            "proxy-connection",
            "connection",
            "keep-alive",
            "authorization",
            "x-api-key",
            "api-key",
            "proxy-authorization",
        }:
            continue
        kept.append(line)
    head_lines = [f"{method} {upstream_path} HTTP/1.1"]
    head_lines.append(f"Host: {gateway.host}:{gateway.port}")
    for name, value in gateway.headers.items():
        head_lines.append(f"{name}: {value}")
    head_lines.append("Connection: close")
    head_lines.extend(kept)
    return ("\r\n".join(head_lines) + "\r\n\r\n").encode("iso-8859-1")


def _split_authority(authority: str) -> tuple[str, int]:
    authority = str(authority or "").strip()
    if authority.startswith("["):
        host, _, rest = authority[1:].partition("]")
        tail = rest.lstrip(":")
    else:
        host, _, tail = authority.rpartition(":")
    try:
        return _normalize_host(host), int(tail)
    except ValueError:
        return _normalize_host(host), 0
