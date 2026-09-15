#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path.cwd().resolve()
BASE = ROOT / "evidence/epoch46-owner-remediation-rerun/e2e/results"
OUT = ROOT / "evidence/epoch46-owner-remediation-rerun/inspections/evidence-secret-scan.json"

LITERAL_RULES = {
    "private_key_material": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "anthropic_key_literal": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key_literal": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "github_token_literal": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws_access_key_literal": re.compile(rb"AKIA[0-9A-Z]{16}"),
}
SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "x-api-key", "cookie", "set-cookie"}


def literal_findings(name: str, data: bytes) -> list[dict]:
    return [{"path": name, "rule": rule} for rule, pattern in LITERAL_RULES.items() if pattern.search(data)]


def main() -> int:
    findings: list[dict] = []
    har = json.loads((BASE / "network.har").read_text(encoding="utf-8"))
    sensitive_header_counts: dict[str, int] = {}
    for entry_index, entry in enumerate((har.get("log") or {}).get("entries") or []):
        for side in ("request", "response"):
            for header in (entry.get(side) or {}).get("headers") or []:
                name = str(header.get("name") or "").lower()
                if name in SENSITIVE_HEADERS and str(header.get("value") or ""):
                    sensitive_header_counts[name] = sensitive_header_counts.get(name, 0) + 1
                    findings.append({"path": "network.har", "rule": "sensitive_header_value_present", "header_name": name, "entry_index": entry_index, "side": side})
    findings.extend(literal_findings("network.har", (BASE / "network.har").read_bytes()))
    trace_scanned = 0
    with zipfile.ZipFile(BASE / "playwright-trace.zip") as archive:
        for info in archive.infolist():
            if info.file_size > 20_000_000:
                continue
            data = archive.read(info)
            trace_scanned += 1
            findings.extend(literal_findings(f"playwright-trace.zip!{info.filename}", data))
    result = {
        "scope": ["network.har headers and embedded content", "all trace members <=20MB"],
        "har_entry_count": len((har.get("log") or {}).get("entries") or []),
        "trace_members_scanned": trace_scanned,
        "sensitive_header_counts": sensitive_header_counts,
        "findings": findings,
        "values_redacted_by_design": True,
        "status": "PASS" if not findings else "FAIL",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "finding_count": len(findings)}, ensure_ascii=False))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
