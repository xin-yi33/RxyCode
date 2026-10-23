# W10-D1: production image for the durable queue worker.
#
# `python -m rxycode_worker.drain` — claims runs, then executes each turn
# INSIDE a per-run bubblewrap user/pid/ipc/uts namespace. The image preinstalls
# bubblewrap: absent it the drain refuses every run instead of executing
# unconfined (fail-closed; see compose worker comment + userns.py).
#
# The bwrap child sees this image's own filesystem: /usr|/usr/local|/bin|/lib|
# /etc|/opt are ro-bound plus /repo and every PYTHONPATH entry (drain.py
# ro_binds) — so the checkout at /repo and the /opt/pkg bridge are what the
# confined turn imports. Runtime still needs `security_opt: seccomp=unconfined`
# on the service (compose/D2 owns that): Docker's default profile forbids the
# unshare/mount syscalls userns isolation needs.
#
# Alembic ordering is the prod overlay's job (W10-D2), same as the api image.

# Base pinned to Debian 12 (bookworm): it ships bubblewrap 0.8, which uses the
# classic mount() API — the only flavour that runs on el7-class kernels
# (3.10.0-957). Debian 13's bwrap 0.12 calls the new mount API
# (open_tree/move_mount), absent before kernel 5.2 — its probe dies ENOSYS and
# the drain would refuse every run. bwrap 0.8 lacks --overlay (0.10+); the
# userns overlay probe degrades those mounts honestly, as designed.
FROM python:3.12-slim-bookworm

ARG RXYCODE_BUILD_COMMIT=unknown
ARG RXYCODE_BUILD_TIME=""

ENV RXYCODE_BUILD_COMMIT=${RXYCODE_BUILD_COMMIT} \
    RXYCODE_BUILD_TIME=${RXYCODE_BUILD_TIME} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PYTHONPATH=/opt/pkg:/repo:/repo/packages/rxycode-core/src:/repo/packages/rxycode-protocol/src:/repo/packages/rxycode-runner/src:/repo/packages/rxycode-server/src:/repo/packages/rxycode-worker/src \
    RXYCODE_WORKER_WORKSPACES=/work/runs \
    RXYCODE_DATA_DIR=/work/data \
    RXYCODE_UVLOOP=0

# bubblewrap is the turn's kernel boundary (userns provider).
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends bubblewrap \
    && rm -rf /var/lib/apt/lists/*

COPY infra/docker/requirements-web.txt /tmp/requirements-web.txt
# Optional mirror for slow networks: --build-arg PIP_INDEX_URL=https://…/simple
ARG PIP_INDEX_URL=""
RUN python -m pip install --quiet --no-cache-dir \
    ${PIP_INDEX_URL:+-i "$PIP_INDEX_URL"} -r /tmp/requirements-web.txt \
    && rm /tmp/requirements-web.txt

# --- release payload at /repo (same whitelist as api.Dockerfile) -------------
COPY __init__.py __main__.py main.py api_server.py api_server_models.py api_server_stream.py /repo/
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
COPY packages/rxycode-core /repo/packages/rxycode-core
COPY packages/rxycode-protocol /repo/packages/rxycode-protocol
COPY packages/rxycode-runner/src /repo/packages/rxycode-runner/src
COPY packages/rxycode-server/src /repo/packages/rxycode-server/src
COPY packages/rxycode-server/alembic /repo/packages/rxycode-server/alembic
COPY packages/rxycode-worker /repo/packages/rxycode-worker
COPY infra/compose/sandbox-policy.yaml /repo/infra/compose/sandbox-policy.yaml

# Bridge package + entrypoint/healthcheck helpers + workspace/data dirs.
COPY infra/docker/worker-entry.sh infra/docker/probe_worker.py /opt/
RUN chmod 0755 /opt/worker-entry.sh \
    && mkdir -p /opt/pkg/RxyCode /work/runs /work/data \
    && ln -sfn /repo /opt/pkg/RxyCode/RxyCode1_1_0 \
    && printf '"""Bridge package for the seeded checkout."""\n' > /opt/pkg/RxyCode/__init__.py

# Ship warm bytecode. PYTHONDONTWRITEBYTECODE=1 (ENV above) means no process
# can ever write .pyc at runtime — every confined turn is a FRESH
# `python -m rxycode_worker.drain` spawned under bwrap, so without baked
# bytecode each run re-parses the whole import surface (measured ~2.9s cold
# vs ~1.06s warm). compileall writes pyc regardless of that env flag, and
# timestamp-invalidation .pyc files stay valid because image layers keep
# COPY mtimes. `|| true`: one unparseable vendored file must not fail the
# image — it just stays uncompiled.
RUN python -m compileall -q /repo /opt /usr/local/lib/python3.12/site-packages || true

# worker-entry.sh writes the deployed model config when RXYCODE_LLM_BASE_URL
# is set (the bootstrap compose used to run inline), then execs the drain as
# PID 1 so probe_worker.py's /proc/1 check keeps working.
ENTRYPOINT ["/opt/worker-entry.sh"]
CMD ["python", "-m", "rxycode_worker.drain"]
