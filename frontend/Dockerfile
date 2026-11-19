# syntax=docker/dockerfile:1.7
# Waffle Bros POS screens (the `web` service): the built React app served by nginx, which also
# forwards /api and /docs to the `api` service. Build context: this folder.

# ---------- 1. Dependencies (Debian base: Rollup crashes on Alpine/musl) ----------
FROM node:22-bookworm-slim AS deps
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---------- 2. Dev server with hot reload (used by `make dev` only) ----------
FROM deps AS dev
COPY . ./
EXPOSE 5173
CMD ["npm", "run", "dev"]

# ---------- 3. Build the screens ----------
FROM deps AS build
COPY . ./
RUN npm run build

# ---------- 4. Runtime: unprivileged nginx (listens on 8080, runs as uid 101) ----------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
LABEL org.opencontainers.image.title="Waffle Bros POS screens" \
      org.opencontainers.image.source="https://github.com/SAGE-Rebirth/waffle-bros-pos"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.inc /etc/nginx/conf.d/security-headers.inc
COPY --from=build /frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
