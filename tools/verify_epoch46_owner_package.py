#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path.cwd().resolve()
DEFAULT_ZIP = ROOT / "artifacts/Claude_Agent_SDK_迁移整改证据包_run_bda13e93b2ea_epoch46_owner.zip"
FORMAL = ROOT / "claude-runtime-migration/run_bda13e93b2ea/epoch46-owner-remediation-v1"
MANIFEST_NAME = "claude-runtime-migration/run_bda13e93b2ea/epoch46-owner-remediation-v1/final_manifest.json"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    if ROOT.name != "delivery":
        raise SystemExit("must run from delivery root")
    package = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_ZIP
    failures: list[dict[str, object]] = []
    with zipfile.ZipFile(package) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        duplicate_free = len(names) == len(set(names))
        if not duplicate_free:
            failures.append({"check": "duplicate_members"})
        manifest_last = bool(names and names[-1] == MANIFEST_NAME)
        if not manifest_last:
            failures.append({"check": "manifest_last", "observed": names[-1] if names else None})
        bad_crc = archive.testzip()
        if bad_crc is not None:
            failures.append({"check": "zip_crc", "member": bad_crc})
        manifest_bytes = archive.read(MANIFEST_NAME)
        manifest = json.loads(manifest_bytes)
        expected_names = [item["path"] for item in manifest["files"]] + [MANIFEST_NAME]
        stable_domain = names == expected_names
        if not stable_domain:
            failures.append({"check": "stable_member_order_or_domain"})
        fixed_timestamps = all(info.date_time == FIXED_TIME for info in members)
        if not fixed_timestamps:
            failures.append({"check": "fixed_timestamp"})
        fixed_modes = True
        for info in members:
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) != stat.S_IFREG or stat.S_IMODE(mode) != 0o644:
                fixed_modes = False
                failures.append({"check": "fixed_mode", "member": info.filename, "mode": oct(mode)})
        payload_digests = True
        for item in manifest["files"]:
            data = archive.read(item["path"])
            if len(data) != int(item["size_bytes"]) or sha256_bytes(data) != item["sha256"]:
                payload_digests = False
                failures.append({"check": "payload_digest", "member": item["path"]})
        prohibited_members = [
            name for name in names
            if ".playwright-browsers" in name.replace("\\", "/").split("/")
            or "node_modules" in name.replace("\\", "/").split("/")
            or ".git" in name.replace("\\", "/").split("/")
            or name.startswith("evidence/epoch46-remediation/")
        ]
        if prohibited_members:
            failures.append({"check": "prohibited_members", "members": prohibited_members})
        manifest_self_excluding = not any(item["path"] == MANIFEST_NAME for item in manifest["files"])
        if not manifest_self_excluding:
            failures.append({"check": "manifest_self_excluding"})
    result = {
        "command": "python tools/verify_epoch46_owner_package.py",
        "workdir": "delivery/",
        "package_path": package.relative_to(ROOT).as_posix(),
        "package_size_bytes": package.stat().st_size,
        "package_sha256": sha256_bytes(package.read_bytes()),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "payload_count": manifest["payload_count"],
        "zip_member_count": len(members),
        "checks": {
            "duplicate_members": duplicate_free,
            "manifest_last": manifest_last,
            "crc": bad_crc is None,
            "stable_member_domain": stable_domain,
            "fixed_timestamp": fixed_timestamps,
            "fixed_mode_0100644": fixed_modes,
            "payload_size_sha256": payload_digests,
            "manifest_self_excluding": manifest_self_excluding,
            "playwright_browsers_excluded": not any(".playwright-browsers" in name for name in names),
            "node_modules_excluded": not any("node_modules" in name.replace("\\", "/").split("/") for name in names),
            "git_metadata_excluded": not any(".git" in name.replace("\\", "/").split("/") for name in names),
            "stale_epoch46_remediation_evidence_excluded": not any(name.startswith("evidence/epoch46-remediation/") for name in names),
        },
        "prohibited_members": prohibited_members,
        "failures": failures,
        "status": "PASS_LOCAL_PACKAGE_INTEGRITY_ONLY" if not failures else "FAIL_PACKAGE_INTEGRITY",
        "platform_artifact_id": None,
        "platform_authority": "NOT_ESTABLISHED",
    }
    FORMAL.mkdir(parents=True, exist_ok=True)
    (FORMAL / "package-verification-receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
