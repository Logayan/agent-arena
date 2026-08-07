# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS client-builder
WORKDIR /app/client

COPY client/package.json client/package-lock.json ./
RUN npm ci

COPY client/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JIANGHU_DB_PATH=/app/.data/jianghu.db \
    JIANGHU_SECRET_KEY_FILE=/app/.data/.jianghu-secret.key \
    JIANGHU_WORKSPACE_ROOT=/app/.data/workspaces \
    JIANGHU_KNOWLEDGE_ROOT=/app/.data/knowledge \
    JIANGHU_OPENCLAW_STATE_ROOT=/app/.data/openclaw

WORKDIR /app

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ ./server/
COPY --from=client-builder /app/client/dist ./client/dist

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.data \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
VOLUME ["/app/.data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
