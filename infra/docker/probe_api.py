"""W10-D1: api healthcheck — same probe the compose service runs inline."""

import os
import sys
import urllib.request

# App layer: the unauthenticated CSRF endpoint must answer 200.
with urllib.request.urlopen(
    "http://127.0.0.1:8000/api/v1/auth/csrf", timeout=5
) as response:
    if response.status != 200:
        sys.exit(1)
# Durable layer: the API's own database handle must still reach PG.
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

engine = create_engine(os.environ["RXYCODE_WEB_DATABASE_URL"], poolclass=NullPool)
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
finally:
    engine.dispose()
