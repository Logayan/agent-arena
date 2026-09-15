#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path.cwd().resolve()
PACKAGE = ROOT / "artifacts/Claude_Agent_SDK_迁移整改证据包_run_bda13e93b2ea_epoch46_owner.zip"
OUT = ROOT / "claude-runtime-migration/run_bda13e93b2ea/epoch46-owner-remediation-v1/package-secret-scan.json"
RULES = {
    "private_key_material": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "anthropic_key_literal": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key_literal": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "github_token_literal": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws_access_key_literal": re.compile(rb"AKIA[0-9A-Z]{16}"),
}
SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "x-api-key", "cookie", "set-cookie"}


def main() -> int:
    if ROOT.name != "delivery":
        raise SystemExit("must run from delivery root")
    findings: list[dict[str, object]] = []
    members_scanned = 0
    bytes_scanned = 0
    har_sensitive_header_counts: dict[str, int] = {}
    with zipfile.ZipFile(PACKAGE) as archive:
        for info in archive.infolist():
            data = archive.read(info)
            members_scanned += 1
            bytes_scanned += len(data)
            for rule, pattern in RULES.items():
                if pattern.search(data):
                    findings.append({"member": info.filename, "rule": rule})
            if info.filename.endswith("/network.har"):
                har = json.loads(data)
                for entry in (har.get("log") or {}).get("entries") or []:
                    for side in ("request", "response"):
                        for header in (entry.get(side) or {}).get("headers") or []:
                            name = str(header.get("name") or "").lower()
                            if name in SENSITIVE_HEADERS and str(header.get("value") or ""):
                                har_sensitive_header_counts[name] = har_sensitive_header_counts.get(name, 0) + 1
                                findings.append({"member": info.filename, "rule": "sensitive_header_value_present", "header_name": name, "side": side})
    result = {
        "schema_version": "jianghu.package-secret-scan.v1",
        "package": PACKAGE.relative_to(ROOT).as_posix(),
        "members_scanned": members_scanned,
        "uncompressed_bytes_scanned": bytes_scanned,
        "har_sensitive_header_counts": har_sensitive_header_counts,
        "finding_count": len(findings),
        "findings": findings,
        "secret_values_emitted": False,
        "status": "PASS" if not findings else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "members_scanned": members_scanned, "finding_count": len(findings)}, ensure_ascii=False))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
