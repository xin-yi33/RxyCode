"""Trusted exec wrapper: bind one Web command to the parent observer, then exec it."""

from __future__ import annotations

import json
import os
import socket
import sys


def _split(argv: list[str]) -> tuple[str, str, float, list[str]]:
    try:
        marker = argv.index("--")
    except ValueError:
        return "", "", 30.0, []
    options = argv[1:marker]
    try:
        sock_path = options[options.index("--socket") + 1]
        process_key = options[options.index("--process-key") + 1]
        timeout = float(options[options.index("--timeout") + 1])
    except (ValueError, IndexError):
        return "", "", 30.0, []
    return sock_path, process_key, max(0.1, timeout), argv[marker + 1 :]


def _register(sock_path: str, process_key: str, timeout: float) -> None:
    request = {
        "op": "process_register",
        "args": {"process_key": process_key},
    }
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(sock_path)
        sock.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        sock.shutdown(socket.SHUT_WR)
        while sock.recv(4096):
            pass
    finally:
        sock.close()


def main(argv: list[str]) -> int:
    sock_path, process_key, timeout, original = _split(argv)
    try:
        if sock_path and process_key and original:
            _register(sock_path, process_key, timeout)
    except Exception:
        pass
    if not original:
        return 127
    os.execvpe(original[0], original, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
