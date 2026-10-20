"""W10-D1: api image entrypoint — the same serve() path compose runs today.

Deployed startup MUST go through serve(): mode="local" on a non-loopback
bind is refused by reject_as_public_web_gateway — the same guard the
negative test exercises. create_app alone would let RXYCODE_WEB_MODE=local
boot a secure-cookies-off app on 0.0.0.0.

RXYCODE_WEB_BIND selects the listen address (default 0.0.0.0 for compose
networking); local mode still refuses anything non-loopback via serve().
"""

import os

import uvicorn

# Deployed startup MUST go through serve() — see module docstring.
from rxycode_server.main import serve

host = os.environ.get("RXYCODE_WEB_BIND", "0.0.0.0").strip() or "0.0.0.0"

app = serve(
    mode=os.environ.get("RXYCODE_WEB_MODE", "cloud"),
    host=host,
    database_url=os.environ["RXYCODE_WEB_DATABASE_URL"],
    secret=os.environ["RXYCODE_WEB_SECRET"],
    allowed_origins=[
        origin.strip()
        for origin in os.environ.get("RXYCODE_WEB_ORIGINS", "").split(",")
        if origin.strip()
    ],
    github_client_id=os.environ.get("RXYCODE_GITHUB_CLIENT_ID", ""),
    github_client_secret=os.environ.get("RXYCODE_GITHUB_CLIENT_SECRET", ""),
    github_redirect_uri=os.environ.get("RXYCODE_GITHUB_REDIRECT_URI", ""),
    s3_endpoint=os.environ.get("RXYCODE_S3_ENDPOINT", ""),
    s3_bucket=os.environ.get("RXYCODE_S3_BUCKET", ""),
    s3_access_key=os.environ.get("RXYCODE_S3_ACCESS_KEY", ""),
    s3_secret_key=os.environ.get("RXYCODE_S3_SECRET_KEY", ""),
    rate_limit_rpm=int(os.environ.get("RXYCODE_WEB_RATE_LIMIT_RPM", "0")),
)
uvicorn.run(
    app,
    host=host,
    port=int(os.environ.get("RXYCODE_WEB_PORT", "8000")),
    proxy_headers=True,
    forwarded_allow_ips="*",
)
