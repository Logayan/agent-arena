FROM node:22-bookworm-slim

WORKDIR /probe
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY src/static-probe.mjs ./src/static-probe.mjs

CMD ["node", "./src/static-probe.mjs"]
