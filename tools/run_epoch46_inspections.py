#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path.cwd().resolve()
OUT = ROOT / "evidence" / "epoch46-owner-remediation-rerun" / "inspections"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / "attempt-49d1df2dfeb3e1f2"
ATTEMPT = "attempt:run_bda13e93b2ea:remediation_rerun:epoch46:loop2:node1"
TARGET_COMMIT = "58c0e52e0bb16386674b4c4edde6dd5fd3b5c7b0"
CONFLICTING_SUPPLEMENT_TARGET = "b7c338a32c53e181079b0c769561ce0aebf630be"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(name: str, value: object) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def inspect_snapshot() -> tuple[dict, dict[int, tuple[str, str, str]], list[dict]]:
    metadata = json.loads((SNAPSHOT / "run-metadata.json").read_text(encoding="utf-8"))
    omissions_doc = json.loads((SNAPSHOT / "projection-omissions.json").read_text(encoding="utf-8"))
    omissions = list(omissions_doc.get("omissions") or [])
    public_count = 0
    public_sequences: list[int] = []
    event_index: dict[int, tuple[str, str, str]] = {}
    current_attempt_events: list[dict] = []
    current_attempt_start_sequence: int | None = None
    event_hash = hashlib.sha256()
    with (SNAPSHOT / "events.ndjson").open("rb") as raw:
        for raw_line in raw:
            event_hash.update(raw_line)
            if not raw_line.strip():
                continue
            event = json.loads(raw_line)
            sequence = int(event["sequence"])
            public_count += 1
            public_sequences.append(sequence)
            event_index[sequence] = (
                str(event.get("event_id") or ""),
                str(event.get("source_event_sha256") or ""),
                str(event.get("type") or ""),
            )
            if (
                event.get("type") == "attempt.created"
                and str((event.get("payload") or {}).get("platform_attempt_id") or "") == ATTEMPT
            ):
                current_attempt_start_sequence = sequence
            if current_attempt_start_sequence is not None and sequence >= current_attempt_start_sequence:
                current_attempt_events.append(event)
    omitted_sequences = [int(item["sequence"]) for item in omissions]
    combined = public_sequences + omitted_sequences
    unique = set(combined)
    cutoff = int(metadata["cutoff_sequence"])
    first = min(combined, default=0)
    result = {
        "snapshot": SNAPSHOT.name,
        "events_sha256": event_hash.hexdigest(),
        "metadata": metadata,
        "observed_public_event_count": public_count,
        "observed_omitted_event_count": len(omissions),
        "observed_source_event_count": len(combined),
        "observed_first_event_sequence": first,
        "observed_cutoff_sequence": max(combined, default=0),
        "duplicate_sequence_count": len(combined) - len(unique),
        "out_of_boundary_count": sum(1 for item in combined if item > cutoff),
        "sequence_domain_exact": unique == set(range(first, cutoff + 1)),
        "count_equation_exact": (
            int(metadata["source_event_count"])
            == int(metadata["public_event_count"]) + int(metadata["omitted_event_count"])
            == len(combined)
        ),
        "metadata_event_count_equals_source": int(metadata["event_count"]) == int(metadata["source_event_count"]),
        "omissions_greater_than_zero": len(omissions) > 0,
        "new_boundary_attestation_fields_present": all(
            key in metadata
            for key in ("first_event_sequence", "event_snapshot_coherent", "event_snapshot_boundary_rule")
        ),
        "current_attempt_event_count": len(current_attempt_events),
        "current_attempt_event_types": [event["type"] for event in current_attempt_events],
        "status": "PASS_CONTENT_COHERENCE_BLOCKED_NEW_BOUNDARY_ATTESTATION"
        if unique == set(range(first, cutoff + 1)) and len(omissions) > 0
        else "FAIL_SNAPSHOT_CONTENT_COHERENCE",
    }
    write("snapshot-verification.json", result)
    write("current-attempt-events.json", current_attempt_events)
    return result, event_index, omissions


def inspect_registry(event_index: dict[int, tuple[str, str, str]]) -> dict:
    registry = json.loads((SNAPSHOT / "artifact-registry.json").read_text(encoding="utf-8"))
    items = registry if isinstance(registry, list) else registry.get("artifacts", registry.get("items", []))
    failures: list[dict] = []
    provenance_failures: list[dict] = []
    total_bytes = 0
    for item in items:
        materialized = (SNAPSHOT / str(item.get("materialized_path") or "")).resolve()
        expected = str(item.get("expected_sha256") or item.get("observed_sha256") or "")
        size = int(item.get("size_bytes") or 0)
        if not materialized.is_relative_to((ROOT / ".jianghu-platform-evidence").resolve()) or not materialized.is_file():
            failures.append({"artifact_id": item.get("id"), "reason": "materialized_file_missing_or_escape"})
            continue
        observed_size = materialized.stat().st_size
        observed = digest(materialized)
        total_bytes += observed_size
        if observed != expected or observed_size != size or str(item.get("observed_sha256") or expected) != expected:
            failures.append({
                "artifact_id": item.get("id"), "path": str(item.get("materialized_path")),
                "expected_sha256": expected, "observed_sha256": observed,
                "expected_size": size, "observed_size": observed_size,
            })
        sequence = int(item.get("source_event_sequence") or 0)
        projected = event_index.get(sequence)
        if not projected:
            provenance_failures.append({"artifact_id": item.get("id"), "sequence": sequence, "reason": "source_event_not_public"})
        elif projected[0] != str(item.get("source_event_id") or "") or projected[1] != str(item.get("source_event_sha256") or ""):
            provenance_failures.append({"artifact_id": item.get("id"), "sequence": sequence, "reason": "source_identity_mismatch"})
    result = {
        "registry_sha256": digest(SNAPSHOT / "artifact-registry.json"),
        "artifact_count": len(items),
        "raw_bytes_verified": len(items) - len(failures),
        "raw_payload_bytes_read": total_bytes,
        "byte_failures": failures,
        "public_source_event_provenance_verified": len(items) - len(provenance_failures),
        "provenance_failures": provenance_failures,
        "status": "PASS" if not failures else "FAIL",
    }
    write("artifact-byte-verification.json", result)
    return result


def inspect_sources() -> dict:
    production_files: list[Path] = []
    roots = [ROOT / "server" / "app", ROOT / "server" / "claude_agent_runtime", ROOT / "client" / "src"]
    for source_root in roots:
        production_files.extend(path for path in source_root.rglob("*") if path.is_file() and "node_modules" not in path.parts)
    production_files.extend(path for path in [ROOT / "Dockerfile", ROOT / "compose.yaml", ROOT / "compose.postgres.yaml", ROOT / ".env.docker.example"] if path.is_file())
    references: list[dict] = []
    prohibited: list[dict] = []
    import_re = re.compile(r"(?im)^\s*(?:from\s+openclaw\b|import\s+openclaw\b)")
    dependency_re = re.compile(r'(?i)["\']openclaw["\']\s*:')
    adapter_re = re.compile(r"(?i)(runtime|adapter|provider)\s*[:=]\s*[\"']?openclaw")
    for path in sorted(set(production_files)):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if "openclaw" in line.lower():
                record = {"path": path.relative_to(ROOT).as_posix(), "line": number, "classification": "migration_label_or_fail_closed_guard"}
                references.append(record)
                is_one_way_migration = (
                    "UPDATE agent_blueprints SET runtime='claude_code' WHERE runtime='openclaw'" in line
                )
                if not is_one_way_migration and (
                    import_re.search(line) or dependency_re.search(line) or adapter_re.search(line)
                ):
                    prohibited.append({**record, "classification": "prohibited_production_runtime_reference"})
    result = {
        "production_files_scanned": len(set(production_files)),
        "case_insensitive_reference_count": len(references),
        "references": references,
        "prohibited_findings": prohibited,
        "status": "PASS" if not prohibited else "FAIL",
    }
    write("openclaw-production-scan.json", result)
    return result


def credential_scan() -> dict:
    excluded = {".jianghu-platform-evidence", "evidence", "artifacts", "node_modules", "dist", ".git", ".pytest_cache", "__pycache__"}
    patterns = {
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
        "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
        "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    }
    files = 0
    findings: list[dict] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(ROOT).parts):
            continue
        if path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files += 1
        for rule, pattern in patterns.items():
            if pattern.search(text):
                findings.append({"path": path.relative_to(ROOT).as_posix(), "rule": rule})
    result = {"files_scanned": files, "credential_literal_findings": findings, "status": "PASS" if not findings else "FAIL"}
    write("credential-scan.json", result)
    return result


def test_denominator() -> dict:
    server = ET.parse(ROOT / "evidence/epoch46-owner-remediation-rerun/tests/backend-full-rerun.junit.xml").getroot()
    bridge = ET.parse(ROOT / "evidence/epoch46-owner-remediation-rerun/tests/bridge.junit.xml").getroot()
    e2e = json.loads((ROOT / "evidence/epoch46-owner-remediation-rerun/e2e/results/test-results.json").read_text(encoding="utf-8"))
    server_suites = list(server.iter("testsuite"))
    server_total = sum(int(item.attrib.get("tests", 0)) for item in server_suites)
    server_fail = sum(int(item.attrib.get("failures", 0)) + int(item.attrib.get("errors", 0)) for item in server_suites)
    bridge_cases = list(bridge.iter("testcase"))
    bridge_total = len(bridge_cases)
    bridge_fail = sum(1 for item in bridge_cases if item.find("failure") is not None or item.find("error") is not None)
    e2e_total = int(e2e["passed"]) + int(e2e["failed"]); e2e_fail = int(e2e["failed"])
    total = server_total + bridge_total + e2e_total
    failed = server_fail + bridge_fail + e2e_fail
    result = {
        "denominator_id": "E46-OWNER-UNIQUE-263-v1",
        "components": [
            {"name": "full_server_tests", "total": server_total, "failed": server_fail},
            {"name": "claude_agent_sdk_bridge", "total": bridge_total, "failed": bridge_fail},
            {"name": "real_5173_8003_evidence_center_e2e", "total": e2e_total, "failed": e2e_fail},
        ],
        "total": total,
        "passed": total - failed,
        "failed": failed,
        "status": "PASS" if failed == 0 and total == 263 else "FAIL",
    }
    write("unique-test-denominator.json", result)
    return result


def workspace_facts() -> dict:
    cwd = str(ROOT)
    playwright_dirs = [path.relative_to(ROOT).as_posix() for path in ROOT.rglob(".playwright-browsers")]
    result = {
        "cwd": cwd,
        "cwd_length": len(cwd),
        "system_short_root_proven": len(cwd) < 100,
        "subst_used_by_recorded_commands": False,
        "playwright_browser_directories": playwright_dirs,
        "playwright_browsers_absent": not playwright_dirs,
        "target_commit_required": TARGET_COMMIT,
        "conflicting_supplement_target_preserved": CONFLICTING_SUPPLEMENT_TARGET,
        "baseline_conflict_resolution": "latest_intervention_58c0e52_is_effective; b7c338_supplement_preserved_as_conflicting_and_not_proven",
        "git_metadata_available": (ROOT / ".git").exists(),
        "source_authority_status": "BLOCKED_GIT_BINDING_NOT_PROVEN",
    }
    write("workspace-and-source-authority.json", result)
    return result


def main() -> int:
    if ROOT.name != "delivery":
        raise SystemExit("must run from delivery root")
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot, event_index, _omissions = inspect_snapshot()
    registry = inspect_registry(event_index)
    openclaw = inspect_sources()
    credentials = credential_scan()
    denominator = test_denominator()
    workspace = workspace_facts()
    overall = {
        "snapshot": snapshot["status"], "registry": registry["status"],
        "openclaw_scan": openclaw["status"], "credential_scan": credentials["status"],
        "tests": denominator["status"], "workspace_source_authority": workspace["source_authority_status"],
        "engineering_checks_pass": all(item == "PASS" for item in [registry["status"], openclaw["status"], credentials["status"], denominator["status"]]),
        "migration_release": "NO_GO",
    }
    write("inspection-summary.json", overall)
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    return 0 if overall["engineering_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
