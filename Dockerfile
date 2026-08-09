# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=24
ARG OPENCLAW_VERSION=2026.7.1-2

FROM node:${NODE_VERSION}-bookworm-slim AS openclaw-runtime
ARG OPENCLAW_VERSION
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates git python3 \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global --omit=dev "openclaw@${OPENCLAW_VERSION}" \
    && openclaw --version

FROM node:${NODE_VERSION}-bookworm-slim AS client-builder
WORKDIR /app/client
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JIANGHU_DATA_ROOT=/app/.data \
    JIANGHU_DB_PATH=/app/.data/jianghu.db \
    JIANGHU_SECRET_KEY_FILE=/app/.data/.jianghu-secret.key \
    JIANGHU_WORKSPACE_ROOT=/app/.data/workspaces \
    JIANGHU_KNOWLEDGE_ROOT=/app/.data/knowledge \
    JIANGHU_OPENCLAW_STATE_ROOT=/app/.data/openclaw \
    JIANGHU_OPENCLAW_NODE_PATH=/usr/local/bin/node \
    JIANGHU_OPENCLAW_ENTRY_PATH=/usr/local/lib/node_modules/openclaw/openclaw.mjs

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git procps tini unzip \
    && rm -rf /var/lib/apt/lists/*

# Keep Node/npm available because engineering Agents must be able to build and
# test generated JavaScript projects. OpenClaw itself is pinned and copied from
# the dedicated stage so runtime behavior does not depend on a host install.
COPY --from=openclaw-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=openclaw-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=openclaw-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=openclaw-runtime /usr/local/bin/corepack /usr/local/bin/corepack
COPY --from=openclaw-runtime /usr/local/bin/openclaw /usr/local/bin/openclaw
COPY --from=openclaw-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

WORKDIR /app
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ ./server/
COPY --from=client-builder /app/client/dist ./client/dist

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.data/workspaces /app/.data/knowledge /app/.data/openclaw \
    && chown -R appuser:appuser /app \
    && python -m compileall -q server \
    && node --version \
    && openclaw --version

USER root
EXPOSE 8000
VOLUME ["/app/.data"]

HEALTHCHECK --interval=30s --timeout=8s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
