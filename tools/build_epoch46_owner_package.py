#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

ROOT = Path.cwd().resolve()
FORMAL = ROOT / "claude-runtime-migration/run_bda13e93b2ea/epoch46-owner-remediation-v1"
EVIDENCE = ROOT / "evidence/epoch46-owner-remediation-rerun"
SNAPSHOT = ROOT / ".jianghu-platform-evidence/snapshots/attempt-49d1df2dfeb3e1f2"
ZIP_PATH = ROOT / "artifacts/Claude_Agent_SDK_迁移整改证据包_run_bda13e93b2ea_epoch46_owner.zip"
MANIFEST = FORMAL / "final_manifest.json"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
POST_SEAL_NAMES = {
    "package-build-receipt.json",
    "package-verification-receipt.json",
    "package-secret-scan.json",
    "post-seal-verification.json",
}
SOURCE_FILES = [
    "server/app/platform_store.py",
    "server/app/platform_executor.py",
    "server/app/git_delivery.py",
    "server/app/frozen_evidence_verifier.py",
    "server/tests/runtime_contract/test_frozen_platform_evidence_verifier.py",
    "server/tests/runtime_contract/test_runtime_execution_safety.py",
    "server/tests/runtime_contract/test_git_delivery.py",
    "server/tests/test_api.py",
    "client/e2e/evidence-center.mjs",
    "tools/apply_owner_remediation_patch.py",
    "tools/run_epoch46_e2e.sh",
    "tools/run_epoch46_inspections.py",
    "tools/audit_epoch46_controls.py",
    "tools/scan_epoch46_evidence_secrets.py",
    "tools/verify_frozen_platform_evidence.py",
    "tools/verify_epoch46_owner_source_authority.py",
    "tools/verify_epoch46_playwright_exclusion.py",
    "tools/build_epoch46_owner_package.py",
    "tools/verify_epoch46_owner_package.py",
    "tools/scan_epoch46_owner_package_secrets.py",
]
SNAPSHOT_FILES = [
    "README.md",
    "run-metadata.json",
    "run-lineage.json",
    "projection-omissions.json",
    "runtime-attestation.json",
    "runtime-source-attestation.json",
]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": digest(path),
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def eligible(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    parts = set(relative.parts)
    if parts.intersection({".git", "node_modules", ".playwright-browsers", "__pycache__", ".pytest_cache", "dist"}):
        return False
    if path.name in POST_SEAL_NAMES or path == MANIFEST or path == ZIP_PATH:
        return False
    return path.is_file()


def create_indexes() -> None:
    command_paths = sorted(
        path for path in (EVIDENCE / "commands").rglob("*")
        if eligible(path)
    )
    write_json(FORMAL / "command-index.json", {
        "schema_version": "jianghu.command-index.v2",
        "workdir": "delivery/",
        "commands_and_receipts": [record(path) for path in command_paths],
    })
    evidence_paths = sorted(path for path in EVIDENCE.rglob("*") if eligible(path))
    write_json(FORMAL / "evidence-index.json", {
        "schema_version": "jianghu.evidence-index.v2",
        "run_id": "run_bda13e93b2ea",
        "attempt_id": "attempt:run_bda13e93b2ea:remediation_rerun:epoch46:loop2:node1",
        "supplied_snapshot_id": "attempt-49d1df2dfeb3e1f2",
        "supplied_cutoff_sequence": 182897,
        "post_remediation_platform_snapshot": None,
        "post_remediation_platform_snapshot_status": "PENDING_PLATFORM_POST_TURN",
        "files": [record(path) for path in evidence_paths],
    })
    write_json(FORMAL / "package-scope.json", {
        "schema_version": "jianghu.epoch46-owner-package-scope.v1",
        "included": [
            "epoch46-owner-remediation-v1 formal report, gap list, issue/change map and indexes",
            "epoch46-owner-remediation-rerun command/test/E2E/inspection evidence",
            "modified product source and regression tests",
            "owner verifier/scanner/package tools",
            "supplied frozen snapshot metadata, lineage, omission receipts and Runtime attestations",
        ],
        "excluded_by_design": [
            {"path": ".jianghu-platform-evidence/snapshots/attempt-49d1df2dfeb3e1f2/events.ndjson", "reason": "platform-owned 182897-row source; exact SHA-256/domain receipt is included"},
            {"path": ".jianghu-platform-evidence/snapshots/attempt-49d1df2dfeb3e1f2/artifact-registry.json", "reason": "platform-owned Registry; SHA-256 and 7278/7278 raw-byte receipt is included"},
            {"path": ".jianghu-platform-evidence/artifacts/**", "reason": "9.7 GB platform materialization is not duplicated"},
            {"path": ".git/**", "reason": "repository metadata excluded"},
            {"path": "**/node_modules/**", "reason": "dependencies excluded"},
            {"path": "**/.playwright-browsers/**", "reason": "browser cache explicitly excluded"},
            {"path": "client/dist/**", "reason": "generated build output excluded; build log retained"},
            {"path": "post-seal receipts", "reason": "package verifier and package secret scan necessarily execute after sealing and remain external receipts"},
            {"path": "evidence/epoch46-remediation/**", "reason": "stale predecessor evidence excluded"},
        ],
        "manifest_rule": "self-excluding manifest, stable member order, manifest last",
        "zip_timestamp": "1980-01-01T00:00:00",
        "zip_mode": "0100644",
    })


def payload_paths() -> list[Path]:
    paths: set[Path] = set()
    for path in FORMAL.rglob("*"):
        if eligible(path):
            paths.add(path)
    for path in EVIDENCE.rglob("*"):
        if eligible(path):
            paths.add(path)
    for relative in SOURCE_FILES:
        path = ROOT / relative
        if path.is_file() and eligible(path):
            paths.add(path)
    for name in SNAPSHOT_FILES:
        path = SNAPSHOT / name
        if path.is_file() and eligible(path):
            paths.add(path)
    selected = sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix())
    prohibited = [
        item.relative_to(ROOT).as_posix()
        for item in selected
        if ".playwright-browsers" in item.parts or "node_modules" in item.parts or ".git" in item.parts
    ]
    if prohibited:
        raise RuntimeError(f"prohibited package payload paths: {prohibited}")
    return selected


def build_archive(target: Path, payload: list[Path], manifest_bytes: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in payload:
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), FIXED_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        info = zipfile.ZipInfo(MANIFEST.relative_to(ROOT).as_posix(), FIXED_TIME)
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, manifest_bytes, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    if ROOT.name != "delivery":
        raise SystemExit("must run from delivery root")
    create_indexes()
    payload = payload_paths()
    entries = [record(path) for path in payload]
    manifest = {
        "schema_version": "jianghu.deterministic-package-manifest.v2",
        "run_id": "run_bda13e93b2ea",
        "run_version": 9,
        "execution_epoch": 46,
        "attempt_id": "attempt:run_bda13e93b2ea:remediation_rerun:epoch46:loop2:node1",
        "supplied_snapshot_id": "attempt-49d1df2dfeb3e1f2",
        "supplied_cutoff_sequence": 182897,
        "post_remediation_platform_snapshot": None,
        "post_remediation_platform_snapshot_status": "PENDING_PLATFORM_POST_TURN",
        "payload_count": len(entries),
        "payload_bytes": sum(int(item["size_bytes"]) for item in entries),
        "files": entries,
        "self_excluding": True,
        "zip_timestamp": "1980-01-01T00:00:00",
        "zip_mode": "0100644",
        "unique_test_denominator": "E46-OWNER-UNIQUE-263-v1",
        "cam_denominator": "E46-CAM-13-v1",
        "gap_denominator": "E46-GAPS-11-v1",
        "verdict": "NO_GO_PENDING_SOURCE_SNAPSHOT_PACKAGE_AUTHORITY_AND_JUDGE",
    }
    write_json(MANIFEST, manifest)
    manifest_bytes = MANIFEST.read_bytes()
    build_archive(ZIP_PATH, payload, manifest_bytes)
    with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
        rebuilt = Path(temp_dir) / "rebuilt.zip"
        build_archive(rebuilt, payload, manifest_bytes)
        deterministic = ZIP_PATH.read_bytes() == rebuilt.read_bytes()
        rebuilt_sha = digest(rebuilt)
    receipt = {
        "command": "python tools/build_epoch46_owner_package.py",
        "workdir": "delivery/",
        "exit_code": 0 if deterministic else 1,
        "package_path": ZIP_PATH.relative_to(ROOT).as_posix(),
        "size_bytes": ZIP_PATH.stat().st_size,
        "sha256": digest(ZIP_PATH),
        "rebuilt_sha256": rebuilt_sha,
        "deterministic_rebuild_byte_identical": deterministic,
        "payload_count": len(entries),
        "zip_member_count": len(entries) + 1,
        "manifest_path": MANIFEST.relative_to(ROOT).as_posix(),
        "manifest_sha256": digest(MANIFEST),
        "platform_artifact_id": None,
        "authority": "PENDING_PLATFORM_POST_TURN_REGISTRATION",
    }
    write_json(FORMAL / "package-build-receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if deterministic else 1


if __name__ == "__main__":
    raise SystemExit(main())
