# =============================================================================
# RxyCode Dockerfile - Multi-stage build
# =============================================================================
# Stage 1: Build the frontend (TypeScript -> dist/)
# Stage 2: Python runtime with all deps + compiled frontend
#
# Usage:
#   docker build -t rxycode:latest .
#   docker compose up -d api
#   docker compose run --rm tui
# The default API is loopback-only inside the shared container namespace and
# is not published to the host. See docs/modules/api_server.md before enabling
# a non-loopback bind; remote access requires a strong token and TLS cert/key.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Frontend build
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# Copy package files first for better layer caching
COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci --production=false

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# The Ink frontend is a single JavaScript bundle but still requires Node.js.
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node

# Install system deps needed by some Python packages (psutil, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python backend
COPY . /app/RxyCode/

# Copy the self-contained frontend bundle from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/RxyCode/frontend/dist

# Set Python path so `from RxyCode.RxyCode1_1_0 import ...` works
ENV PYTHONPATH=/app
ENV RXYCODE_API_PORT=8765
ENV RXYCODE_DATA_DIR=/root/.rxycode

# Create data directory
RUN mkdir -p /root/.rxycode

# Expose the API port
EXPOSE 8765

# Default: start API server + TUI
# The TUI needs a TTY, so in Docker we default to API-only mode.
# For TUI mode, run: docker run -it rxycode:latest tui
CMD ["python", "-c", \
     "from RxyCode.RxyCode1_1_0.api_server import run_api_server; run_api_server(host='127.0.0.1', port=8765)"]
