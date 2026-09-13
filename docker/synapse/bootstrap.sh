#!/bin/sh
set -eu

if [ ! -s /secrets/postgres-password ] || [ ! -s /secrets/as-token ] || [ ! -s /secrets/hs-token ]; then
  echo "Matrix secrets have not been generated" >&2
  exit 1
fi

if [ ! -s /data/homeserver.yaml ]; then
  SYNAPSE_SERVER_NAME="${SYNAPSE_SERVER_NAME:-localhost}" \
  SYNAPSE_REPORT_STATS=no \
  /start.py generate
fi

python3 /config/configure.py
chown -R 991:991 /data
