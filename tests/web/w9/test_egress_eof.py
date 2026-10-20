"""WEB-W9. Egress tunnel half-close must survive TLS writers.

``asyncio`` TLS transports raise ``NotImplementedError`` from
``write_eof()`` — observed in the e2e stack as ``egress request failed``
tracebacks tearing CONNECT tunnels down mid-stream. ``_pipe`` must check
``can_write_eof()`` and swallow the unsupported half-close.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-worker", "rxycode-server", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_worker.egress import _pipe  # noqa: E402


class _Reader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _Writer:
    def __init__(self, *, tls: bool) -> None:
        self.written: list[bytes] = []
        self.eof_called = False
        self._tls = tls

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def can_write_eof(self) -> bool:
        return not self._tls

    def write_eof(self) -> None:
        self.eof_called = True
        if self._tls:
            raise NotImplementedError


def test_pipe_tls_writer_no_eof_no_crash():
    writer = _Writer(tls=True)
    asyncio.run(_pipe(_Reader([b"hello", b"world"]), writer))
    assert writer.written == [b"hello", b"world"]
    assert writer.eof_called is False


def test_pipe_plain_writer_gets_eof():
    writer = _Writer(tls=False)
    asyncio.run(_pipe(_Reader([b"x"]), writer))
    assert writer.written == [b"x"]
    assert writer.eof_called is True
