"""Lightweight runtime probe for live debugging (2026-09-23).

Every call site is marked ``# PROBE-20260923:`` so all probes can be found
and removed with a single grep.  Sites are listed in
``D:\\tmp-cursor-probe\\PROBE-MANIFEST.md``.

Log file: ``D:\\tmp-cursor-probe\\rxycode-probe.log`` (C: has 0 GB free, so
never default to a C: path).  Override with ``RXYCODE_PROBE_LOG``.
Disable entirely with ``RXYCODE_PROBE=0``.

Fail-safe by contract: probe() must never raise, never block meaningfully,
and never change behavior — it is append-only observation.  Each line carries
the pid because appserver spawns one worker subprocess per session and all
of them share this log file.
"""

from __future__ import annotations

import os
import threading
import time

_LOCK = threading.Lock()
_DEFAULT_LOG = r"D:\tmp-cursor-probe\rxycode-probe.log"
_ENABLED = os.environ.get("RXYCODE_PROBE", "1").strip().casefold() not in {
    "0",
    "false",
    "off",
    "no",
}


def probe(event: str, **fields: object) -> None:
    """Append one probe line.  Never raises."""
    if not _ENABLED:
        return
    try:
        path = os.environ.get("RXYCODE_PROBE_LOG", _DEFAULT_LOG)
        now = time.time()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        ms = int((now % 1) * 1000)
        kv = " ".join(f"{key}={value!r}" for key, value in fields.items())
        line = f"{ts}.{ms:03d} pid={os.getpid()} {event} {kv}\n"
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        pass
