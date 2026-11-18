# syntax=docker/dockerfile:1.7
# Waffle Bros POS: one image with the FastAPI backend and the built React screens.

# ---------- 1. Build the screens (Debian base: Rollup crashes on Alpine/musl) ----------
FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Python dependencies ----------
FROM python:3.12-slim-bookworm AS backend
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so code changes don't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY README.md alembic.ini ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---------- 3. Runtime ----------
FROM python:3.12-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="Waffle Bros POS" \
      org.opencontainers.image.source="https://github.com/SAGE-Rebirth/waffle-bros-pos"
RUN groupadd --system pos && useradd --system --gid pos --home /app pos \
    && mkdir -p /data && chown pos:pos /data
WORKDIR /app
COPY --from=backend --chown=pos:pos /app/.venv /app/.venv
COPY --from=frontend --chown=pos:pos /frontend/dist /app/frontend/dist
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WB_DATA_DIR=/data \
    WB_FRONTEND_DIST=/app/frontend/dist \
    WB_HOST=0.0.0.0 \
    WB_PORT=4000 \
    WB_TIMEZONE=Asia/Kolkata
USER pos
VOLUME ["/data"]
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4000/api/health', timeout=4).status == 200 else 1)"
CMD ["waffle-pos"]
