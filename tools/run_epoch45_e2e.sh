#!/usr/bin/env bash
set +e
mkdir -p evidence/epoch45-final-remediation/commands client/evidence/epoch45-final-remediation
if [ -d client/evidence/epoch45-final-remediation/e2e ]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  mv client/evidence/epoch45-final-remediation/e2e "client/evidence/epoch45-final-remediation/e2e-$stamp"
fi
api_log=evidence/epoch45-final-remediation/commands/e2e-api.log
ui_log=evidence/epoch45-final-remediation/commands/e2e-ui.log
e2e_log=evidence/epoch45-final-remediation/commands/evidence-center-e2e.log
start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
python -m uvicorn server.app.main:app --host 127.0.0.1 --port 8003 > "$api_log" 2>&1 & api_pid=$!
npm --prefix client run dev -- --host 127.0.0.1 --port 5173 --strictPort > "$ui_log" 2>&1 & ui_pid=$!
cleanup(){ kill "$ui_pid" "$api_pid" 2>/dev/null; wait "$ui_pid" "$api_pid" 2>/dev/null; }
trap cleanup EXIT
ready=0
for _ in $(seq 1 120); do
  if curl -fsS 'http://127.0.0.1:8003/api/platform/runs?organization_id=org_jianghu' >/dev/null 2>&1 && curl -fsS 'http://127.0.0.1:5173/' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -eq 1 ]; then
  EVIDENCE_E2E_FRONTEND=http://127.0.0.1:5173 \
  EVIDENCE_E2E_BACKEND=http://127.0.0.1:8003 \
  EVIDENCE_E2E_OUTPUT=evidence/epoch45-final-remediation/e2e \
    npm --prefix client run test:e2e:evidence > "$e2e_log" 2>&1
  rc=$?
else
  echo services_not_ready > "$e2e_log"
  rc=70
fi
end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cleanup
trap - EXIT
python - "$start" "$end" "$rc" "$api_pid" "$ui_pid" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
start, end, rc, api_pid, ui_pid = sys.argv[1:]
paths = [
    'evidence/epoch45-final-remediation/commands/evidence-center-e2e.log',
    'evidence/epoch45-final-remediation/commands/e2e-api.log',
    'evidence/epoch45-final-remediation/commands/e2e-ui.log',
]
paths += [
    f'client/evidence/epoch45-final-remediation/e2e/{name}'
    for name in (
        'test-cases.json', 'test-results.json', 'screenshot-index.json',
        'junit.xml', 'playwright-report.html', 'network.har', 'trace.zip',
        'browser-download-receipts.json', 'sha256-manifest.json',
    )
]
files = []
for name in paths:
    path = Path(name)
    if path.is_file():
        data = path.read_bytes()
        files.append({
            'path': name,
            'size_bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        })
receipt = {
    'name': 'evidence-center-e2e',
    'command': 'ports 5173+8003; npm --prefix client run test:e2e:evidence',
    'workdir': 'delivery/',
    'started_at': start,
    'finished_at': end,
    'exit_code': int(rc),
    'backend_pid': int(api_pid),
    'frontend_pid': int(ui_pid),
    'files': files,
}
Path('evidence/epoch45-final-remediation/commands/evidence-center-e2e-receipt.json').write_text(
    json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n'
)
PY
cat "$e2e_log"
exit "$rc"
