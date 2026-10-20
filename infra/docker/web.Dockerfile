# W10-D1: production image for the web frontend + gateway.
#
# Multi-stage (compose `webbuild` + `gateway` services folded into one image):
#   stage 1 (node:22-slim) — npm ci + npm run build for apps/web, the same
#     tree layout the webbuild service assembles (/build/apps/web plus the
#     desktop sessionVisualState.ts that vite.config aliases in).
#   stage 2 (caddy:2.11, same tag as compose gateway) — built SPA at /srv/www
#     and the repo's Caddyfile baked at /etc/caddy/Caddyfile. W10-D2 swaps in
#     Caddyfile.prod for the real deployment; the current Caddyfile still
#     reverse-proxies /api/* to the `api` service name with SSE unbuffered.
#
# Build context is the repo root; .dockerignore keeps node_modules/dist out.

FROM node:22-slim AS webbuild
WORKDIR /build

# Lockfile first for layer caching; npm ci fails loudly without it.
COPY apps/web/package.json apps/web/package-lock.json /build/apps/web/
WORKDIR /build/apps/web
RUN npm ci --no-audit --no-fund

COPY apps/web /build/apps/web
# vite.config.ts aliases @desktop/sessionVisualState to this repo-root file —
# the compose webbuild copies it into the build tree the same way.
COPY frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts \
    /build/frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts
RUN npm run build

FROM caddy:2.11
COPY --from=webbuild /build/apps/web/dist /srv/www
COPY infra/compose/Caddyfile /etc/caddy/Caddyfile
EXPOSE 80 443
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
