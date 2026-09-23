"""Entry point: ``python -m appserver``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from .server import AppServer


def _configure_logging() -> None:
    import warnings

    # Keep langchain-openai from painting the TUI via stderr UserWarning.
    os.environ.setdefault("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")
    warnings.filterwarnings(
        "ignore",
        message=r"langchain-openai injected a custom httpx transport.*",
    )
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _configure_event_loop() -> None:
    """C5: prefer uvloop on non-Windows when RXYCODE_UVLOOP=1 (default).

    Windows is not supported by uvloop; a missing uvloop falls back to the
    default asyncio loop.  Must run before ``asyncio.run`` so the loop
    policy is installed before the loop is created.
    """
    if os.environ.get("RXYCODE_UVLOOP", "1") != "1":
        return
    if sys.platform == "win32":
        return
    try:
        import uvloop  # noqa: PLC0415

        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass  # fall back to the default loop; unit-tested


def main() -> None:
    _configure_logging()
    _configure_event_loop()
    stub = os.environ.get("RXYCODE_APPSERVER_STUB") == "1"
    try:
        server = AppServer(stub=stub)
    except Exception:
        raise
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        pass
    except Exception:
        raise


if __name__ == "__main__":
    main()