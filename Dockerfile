# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=24

FROM node:${NODE_VERSION}-bookworm-slim AS claude-agent-runtime
WORKDIR /runtime
COPY server/claude_agent_runtime/package.json server/claude_agent_runtime/package-lock.json ./
RUN npm ci --omit=dev \
    && node -e "import('@anthropic-ai/claude-agent-sdk').then(() => console.log('claude-agent-sdk ready'))"

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
    JIANGHU_AGENT_RUNTIME=claude_code \
    JIANGHU_CLAUDE_STATE_ROOT=/app/.data/claude-code \
    JIANGHU_CLAUDE_NODE_PATH=/usr/local/bin/node \
    JIANGHU_CLAUDE_BRIDGE_PATH=/app/server/claude_agent_runtime/bridge.mjs

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git procps tini unzip \
    && rm -rf /var/lib/apt/lists/*

# Keep Node/npm available because the Claude SDK bridge and engineering Agents
# both need a pinned JavaScript runtime.
COPY --from=claude-agent-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=claude-agent-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=claude-agent-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=claude-agent-runtime /usr/local/bin/corepack /usr/local/bin/corepack

WORKDIR /app
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ ./server/
COPY --from=claude-agent-runtime /runtime/node_modules ./server/claude_agent_runtime/node_modules
COPY --from=client-builder /app/client/dist ./client/dist

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.data/workspaces /app/.data/knowledge /app/.data/claude-code \
    && chown -R appuser:appuser /app \
    && python -m compileall -q server \
    && node --version \
    && node -e "import('/app/server/claude_agent_runtime/node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs').then(() => console.log('claude-agent-sdk ready'))"

USER root
EXPOSE 8000
VOLUME ["/app/.data"]

HEALTHCHECK --interval=30s --timeout=8s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
