# W10-D1: production image for the web API.
#
# Replaces the compose stack's `python:3.12-slim` + startup `pip install`:
# every dependency is baked in at build time from requirements-web.txt
# (D-11 — `docker compose up` must not touch PyPI). Build context is the repo
# root; .dockerignore there strips secrets/tests/docs from the context, and
# the COPY whitelist below keeps only the release payload.
#
# Layout mirrors the compose service:
#   /repo                         the checkout (canonical RxyCode1_1_0 package)
#   /opt/pkg/RxyCode              bridge package -> RxyCode.RxyCode1_1_0 = /repo
#   PYTHONPATH                    /opt/pkg + /repo + packages/*/src
#
# Alembic `upgrade head` is intentionally NOT in this entrypoint — the prod
# overlay (W10-D2) owns migration ordering.

FROM python:3.12-slim

# Build stamp for /api/v1/version — passed by infra/scripts/build-images.ps1.
ARG RXYCODE_BUILD_COMMIT=unknown
ARG RXYCODE_BUILD_TIME=""

ENV RXYCODE_BUILD_COMMIT=${RXYCODE_BUILD_COMMIT} \
    RXYCODE_BUILD_TIME=${RXYCODE_BUILD_TIME} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PYTHONPATH=/opt/pkg:/repo:/repo/packages/rxycode-server/src:/repo/packages/rxycode-worker/src:/repo/packages/rxycode-runner/src:/repo/packages/rxycode-protocol/src

COPY infra/docker/requirements-web.txt /tmp/requirements-web.txt
RUN python -m pip install --quiet --no-cache-dir -r /tmp/requirements-web.txt \
    && rm /tmp/requirements-web.txt

# --- release payload at /repo ------------------------------------------------
# Root package modules the web surface imports (api_server* for the local-mode
# loopback guard in serve(), main.py for the shared surface dispatch).
COPY __init__.py __main__.py main.py api_server.py api_server_models.py api_server_stream.py /repo/
# Root subpackages (the bare-alias set in __init__.py plus the rest of the
# runtime tree; tests/evals stay out per the card's exclusion list).
COPY appserver /repo/appserver
COPY cache /repo/cache
COPY config /repo/config
COPY core /repo/core
COPY execution /repo/execution
COPY history /repo/history
COPY log /repo/log
COPY lsp /repo/lsp
COPY mcp /repo/mcp
COPY memory /repo/memory
COPY planning /repo/planning
COPY plugins /repo/plugins
COPY protocol /repo/protocol
COPY rag /repo/rag
COPY recovery /repo/recovery
COPY scheduler /repo/scheduler
COPY synthesis /repo/synthesis
COPY tools /repo/tools
COPY utils /repo/utils
COPY validation /repo/validation
# Web packages: src/ trees are on PYTHONPATH; rxycode-server/alembic must sit
# next to the package so persistence.migrate._alembic_dir() finds it, and
# infra/compose/sandbox-policy.yaml is found by sandbox.policy's parent walk.
COPY packages/rxycode-core /repo/packages/rxycode-core
COPY packages/rxycode-protocol /repo/packages/rxycode-protocol
COPY packages/rxycode-runner/src /repo/packages/rxycode-runner/src
COPY packages/rxycode-server/src /repo/packages/rxycode-server/src
COPY packages/rxycode-server/alembic /repo/packages/rxycode-server/alembic
COPY packages/rxycode-worker /repo/packages/rxycode-worker
COPY infra/compose/sandbox-policy.yaml /repo/infra/compose/sandbox-policy.yaml

# Runtime helpers + the RxyCode.RxyCode1_1_0 bridge package (identical to the
# compose bootstrap: __init__.py marker + a symlink to /repo).
COPY infra/docker/serve_web.py infra/docker/probe_api.py /opt/
RUN mkdir -p /opt/pkg/RxyCode \
    && ln -sfn /repo /opt/pkg/RxyCode/RxyCode1_1_0 \
    && printf '"""Bridge package for the seeded checkout."""\n' > /opt/pkg/RxyCode/__init__.py

# Ship warm bytecode: PYTHONDONTWRITEBYTECODE=1 (ENV above) means .pyc can
# never be written at runtime, so without baked bytecode every cold start
# re-parses the whole import surface. compileall writes pyc regardless of
# that env flag; `|| true` keeps one unparseable vendored file from failing
# the image — it just stays uncompiled.
RUN python -m compileall -q /repo /opt /usr/local/lib/python3.12/site-packages || true

EXPOSE 8000
CMD ["python", "/opt/serve_web.py"]
