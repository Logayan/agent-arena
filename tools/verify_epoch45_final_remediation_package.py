#!/usr/bin/env python3
"""Independently verify epoch45 final-remediation candidate v2 bytes and controls."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "run_bda13e93b2ea"
PACKAGE = ROOT / "deliverables" / RUN_ID / "epoch45-final-remediation-candidate-v2"
ZIP_PATH = ROOT / "artifacts" / f"Claude_Runtime_epoch45_final_remediation_{RUN_ID}.zip"
OUTPUT = ROOT / "artifacts" / f"Claude_Runtime_epoch45_final_remediation_{RUN_ID}-independent-verification.json"
HISTORICAL_PACKAGE = ROOT / "deliverables" / RUN_ID / "epoch45-remediation-candidate-v1"
HISTORICAL_ZIP = ROOT / "artifacts" / f"Claude_Runtime_epoch45_remediation_{RUN_ID}.zip"


def io_path(path: Path) -> Path:
    """Return a Win32 extended-length spelling without changing authority."""
    if os.name != "nt":
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    absolute = str(path.absolute())
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def digest_bytes(data: bytes) -> dict[str, Any]:
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def digest(path: Path) -> dict[str, Any]:
    value = hashlib.sha256()
    size = 0
    with io_path(path).open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": value.hexdigest()}


def read_json(path: Path) -> Any:
    return json.loads(io_path(path).read_text(encoding="utf-8"))


def tree_receipt(path: Path) -> dict[str, Any]:
    root = io_path(path)
    files = [
        {"path": item.relative_to(root).as_posix(), **digest(item)}
        for item in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    ]
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"file_count": len(files), "tree_sha256": hashlib.sha256(canonical).hexdigest()}


def zip_one(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for relative in names:
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, io_path(PACKAGE / relative).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    manifest_path = PACKAGE / "final_manifest.json"
    manifest_bytes = io_path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = list(manifest["files"])
    payload_names = [item["path"] for item in expected]
    expected_names = payload_names + ["final_manifest.json"]
    package_io = io_path(PACKAGE)
    actual_directory_names = sorted(
        item.relative_to(package_io).as_posix()
        for item in package_io.rglob("*")
        if item.is_file() and item.name != "final_manifest.json"
    )

    directory_checks = []
    for item in expected:
        observed = digest(PACKAGE / item["path"])
        declared = {"size_bytes": int(item["size_bytes"]), "sha256": str(item["sha256"])}
        directory_checks.append({"path": item["path"], "exact": observed == declared, **observed})

    with zipfile.ZipFile(io_path(ZIP_PATH), "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        crc_error = archive.testzip()
        zip_checks = []
        directory_zip_equality = []
        for item in expected:
            archived = archive.read(item["path"])
            observed = digest_bytes(archived)
            declared = {"size_bytes": int(item["size_bytes"]), "sha256": str(item["sha256"])}
            zip_checks.append({"path": item["path"], "exact": observed == declared, **observed})
            directory_zip_equality.append(archived == io_path(PACKAGE / item["path"]).read_bytes())
        manifest_in_zip_exact = archive.read("final_manifest.json") == manifest_bytes
        metadata_exact = all(
            info.date_time == (1980, 1, 1, 0, 0, 0)
            and info.create_system == 3
            and ((info.external_attr >> 16) & 0o170000) == 0o100000
            and ((info.external_attr >> 16) & 0o777) == 0o644
            for info in infos
        )

    temp_parent = ROOT / "t"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_parent) as temporary:
        temp = Path(temporary)
        rebuilt_one = temp / "rebuilt-one.zip"
        rebuilt_two = temp / "rebuilt-two.zip"
        zip_one(rebuilt_one, expected_names)
        zip_one(rebuilt_two, expected_names)
        deterministic_rebuild = rebuilt_one.read_bytes() == ZIP_PATH.read_bytes()
        two_rebuilds_identical = rebuilt_one.read_bytes() == rebuilt_two.read_bytes()

    source = read_json(PACKAGE / "evidence" / "source-authority.json")
    tests = read_json(PACKAGE / "controls" / "unique-test-denominator.json")
    gaps = read_json(PACKAGE / "controls" / "unique-gap-denominator.json")
    cam = read_json(PACKAGE / "controls" / "cam-status.json")
    authority = read_json(PACKAGE / "controls" / "artifact-authority.json")
    pre = read_json(PACKAGE / "evidence" / "pre-judge-verification.json")
    post = read_json(PACKAGE / "evidence" / "post-completion-verification.json")
    runtime = read_json(PACKAGE / "evidence" / "runtime-control-audit.json")
    e2e = read_json(PACKAGE / "evidence" / "e2e-independent-verification.json")
    preservation = read_json(PACKAGE / "controls" / "historical-candidate-preservation.json")

    required = {
        "README.md",
        "reports/Claude_Agent_SDK_全链路迁移验收报告_Epoch45_Final.md",
        "reports/迁移缺口清单_Epoch45_Final.md",
        "controls/unique-test-denominator.json",
        "controls/unique-gap-denominator.json",
        "controls/cam-status.json",
        "controls/artifact-authority.json",
        "controls/change-set.json",
        "controls/issue-to-change-map.json",
        "controls/before-after.json",
        "controls/mandatory-command-summary.json",
        "evidence/platform-evidence-audit.json",
        "evidence/artifact-byte-index.json",
        "evidence/runtime-control-audit.json",
        "evidence/source-authority.json",
        "evidence/public-submission-review.json",
        "browser/network.har",
        "browser/trace.zip",
        "browser/junit.xml",
        "browser/playwright-report.html",
        "browser/browser-download-receipts.json",
        "browser/browser-requests.json",
        "commands/server-tests-full-final.receipt.json",
        "commands/server-tests-full.log",
        "commands/evidence-center-e2e-independent-verification-attempt1-failed.receipt.json",
        "test-results/server-tests-junit-final.xml",
        "source/server/claude_agent_runtime/bridge.mjs",
        "platform-snapshot/artifact-registry.json",
        "platform-snapshot/projection-omissions.json",
        "platform-snapshot/external-large-file-receipt.json",
    }
    control_checks = {
        "required_members_present": required.issubset(set(payload_names)),
        "manifest_payload_count_exact": int(manifest["payload_count"]) == len(expected),
        "manifest_payload_bytes_exact": int(manifest["payload_bytes"]) == sum(int(item["size_bytes"]) for item in expected),
        "source_authority_blocked": source["status"] == "BLOCKED_SOURCE_AUTHORITY",
        "test_denominator_exact": tests["total"] == 259 and tests["passed"] == 259 and tests["failed"] == 0 and tests["errors"] == 0 and tests["skipped"] == 0,
        "gap_denominator_exact": gaps["total"] == 12 and gaps["open"] == 12 and len(gaps["items"]) == 12,
        "cam_denominator_exact": cam["total"] == 13 and len(cam["items"]) == 13 and cam["release_pass"] is False,
        "platform_authority_pending": authority["platform_registry_artifact_id"] is None and not any(authority[key] for key in ("artifact_created", "artifact_collected", "artifact_download_verified", "artifact_authoritative", "artifact_authority_frozen")),
        "pre_judge_fail_closed": pre["status"] == "NOT_READY_FOR_INDEPENDENT_JUDGE" and pre["ready"] is False,
        "post_completion_fail_closed": post["status"] == "FAIL_POST_COMPLETION_ACCEPT_MISSING" and post["passed"] is False,
        "same_sdk_continuation_rejected": runtime["sdk_continuation"]["status"] == "FAIL_SAME_SDK_SESSION_ID" and runtime["sdk_continuation"]["distinct_sdk_sessions"] is False,
        "current_attempt_memory_open": runtime["memory"]["current_attempt_strict_event_chain_count"] == 0,
        "object_reconciliation_open": runtime["recovery"]["object_reconciled_after_interruption"] == 0,
        "e2e_exact": e2e["status"] == "PASS" and e2e["cases"]["passed"] == 9 and e2e["har"]["entries"] == 91 and e2e["trace"]["members"] == 303,
        "historical_candidate_declared_preserved": preservation["historical_candidate_exists"] is True and preservation["historical_zip"] is not None,
        "historical_candidate_still_exists": io_path(HISTORICAL_PACKAGE).is_dir() and io_path(HISTORICAL_ZIP).is_file(),
    }

    current_historical_tree = tree_receipt(HISTORICAL_PACKAGE)
    historical_tree_exact = current_historical_tree["file_count"] == preservation["historical_candidate_file_count"] and current_historical_tree["tree_sha256"] == preservation["historical_candidate_tree_sha256"]
    historical_zip_exact = digest(HISTORICAL_ZIP) == {"size_bytes": preservation["historical_zip"]["size_bytes"], "sha256": preservation["historical_zip"]["sha256"]}
    control_checks["historical_candidate_tree_exact"] = historical_tree_exact
    control_checks["historical_zip_exact"] = historical_zip_exact

    structural_checks = {
        "directory_payload_names_exact": actual_directory_names == sorted(payload_names),
        "directory_payload_hashes_exact": all(item["exact"] for item in directory_checks),
        "zip_names_exact_and_manifest_last": names == expected_names,
        "duplicate_members_zero": len(names) == len(set(names)),
        "zip_payload_hashes_exact": all(item["exact"] for item in zip_checks),
        "directory_zip_payload_equality": all(directory_zip_equality),
        "manifest_in_zip_exact": manifest_in_zip_exact,
        "crc_pass": crc_error is None,
        "fixed_timestamp_and_mode": metadata_exact,
        "deterministic_rebuild_byte_identical": deterministic_rebuild,
        "two_independent_rebuilds_identical": two_rebuilds_identical,
    }
    passed = all(structural_checks.values()) and all(control_checks.values())
    result = {
        "schema_version": "jianghu.epoch45.independent-package-verification.v2",
        "status": "PASS_LOCAL_PACKAGE_INTEGRITY_ONLY" if passed else "FAIL",
        "package_file_count_verified": len(directory_checks),
        "zip_payload_count_verified": len(zip_checks),
        "zip_member_count": len(names),
        "structural_checks": structural_checks,
        "control_checks": control_checks,
        "manifest": {"path": manifest_path.relative_to(ROOT).as_posix(), **digest(manifest_path)},
        "zip": {"path": ZIP_PATH.relative_to(ROOT).as_posix(), **digest(ZIP_PATH)},
        "historical_candidate_observed_after_verification": {**current_historical_tree, "zip": digest(HISTORICAL_ZIP)},
        "authority_boundary": "Verification establishes local deterministic directory/Manifest/ZIP integrity only. Platform Registry authority, required b7 source authority, current-package browser closure, quality sign-off, Judge ACCEPT and terminal Run events remain absent.",
    }
    io_path(OUTPUT.parent).mkdir(parents=True, exist_ok=True)
    io_path(OUTPUT).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
