"""W10-D1: worker healthcheck — same probe the compose service runs inline."""

import os
import sys
from pathlib import Path

# The worker is the drain loop; prove it is alive as PID 1. `comm` must be
# python — the startup script's cmdline already contains "rxycode_worker"
# while pip/apt still install (a false healthy).
if Path("/proc/1/comm").read_text().strip() != "python":
    sys.exit(1)
cmdline = Path("/proc/1/cmdline").read_bytes()
if b"rxycode_worker" not in cmdline:
    sys.exit(1)
# Its durable spine is the same Postgres the api uses.
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

engine = create_engine(os.environ["RXYCODE_WEB_DATABASE_URL"], poolclass=NullPool)
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
finally:
    engine.dispose()
