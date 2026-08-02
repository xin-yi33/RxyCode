"""Entry point: ``python -m appserver``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from .server import AppServer


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    _configure_logging()
    stub = os.environ.get("RXYCODE_APPSERVER_STUB") == "1"
    server = AppServer(stub=stub)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()