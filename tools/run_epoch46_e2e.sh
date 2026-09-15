#!/usr/bin/env bash
set -u
ROOT="$(pwd)"
OUT="$ROOT/evidence/epoch46-owner-remediation-rerun/e2e"
mkdir -p "$OUT"
if [ "$ROOT" != "$(pwd)" ]; then
  echo "workdir mismatch" >&2
  exit 90
fi
npm --prefix client run dev -- --host 127.0.0.1 --port 5173 > "$OUT/frontend.log" 2>&1 &
frontend_pid=$!
cleanup() {
  kill "$frontend_pid" >/dev/null 2>&1 || true
  wait "$frontend_pid" >/dev/null 2>&1 || true
}
trap cleanup EXIT
ready=0
for _ in $(seq 1 60); do
  node -e "fetch('http://127.0.0.1:5173').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" >/dev/null 2>&1 && ready=1 && break
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "frontend did not become ready" >&2
  exit 91
fi
node -e "fetch('http://127.0.0.1:8003/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" || exit 92
EVIDENCE_E2E_FRONTEND=http://127.0.0.1:5173 \
EVIDENCE_E2E_BACKEND=http://127.0.0.1:8003 \
EVIDENCE_E2E_RUN=run_bda13e93b2ea \
EVIDENCE_E2E_OUTPUT="$OUT/results" \
EVIDENCE_E2E_ALLOW_COMPAT=0 \
npm --prefix client run test:e2e:evidence > "$OUT/output.log" 2>&1
code=$?
printf '{"command":"bash tools/run_epoch46_e2e.sh","workdir":".","frontend":"127.0.0.1:5173","backend":"127.0.0.1:8003","exit_code":%s,"subst_used":false}\n' "$code" > "$OUT/command.json"
cat "$OUT/output.log"
exit "$code"
