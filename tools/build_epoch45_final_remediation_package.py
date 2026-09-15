#!/usr/bin/env python3
"""Build the non-overwriting epoch45 final-remediation candidate v2.

The package is deterministic for a fixed evidence tree: generated metadata is
bound to the frozen platform snapshot time, paths are sorted, ZIP timestamps
and Unix modes are fixed, and final_manifest.json excludes itself and is last.
This builder never fetches Git objects or creates platform Artifact authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "run_bda13e93b2ea"
FAMILY_ID = "run_0886dd109c15"
ATTEMPT_ID = "attempt:run_bda13e93b2ea:remediation_rerun:epoch45:loop3:node1"
SNAPSHOT_ID = "attempt-ef6476c5bf4ad3e8"
BASELINE = "b7c338a32c53e181079b0c769561ce0aebf630be"
EVIDENCE = ROOT / "evidence" / "epoch45-final-remediation"
BROWSER = ROOT / "client" / "evidence" / "epoch45-final-remediation" / "e2e"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / SNAPSHOT_ID
PACKAGE = ROOT / "deliverables" / RUN_ID / "epoch45-final-remediation-candidate-v2"
ZIP_PATH = ROOT / "artifacts" / f"Claude_Runtime_epoch45_final_remediation_{RUN_ID}.zip"
RECEIPT = ROOT / "artifacts" / f"Claude_Runtime_epoch45_final_remediation_{RUN_ID}-receipt.json"
HISTORICAL_PACKAGE = ROOT / "deliverables" / RUN_ID / "epoch45-remediation-candidate-v1"
HISTORICAL_ZIP = ROOT / "artifacts" / f"Claude_Runtime_epoch45_remediation_{RUN_ID}.zip"


def io_path(path: Path) -> Path:
    """Return a Win32 extended-length spelling without changing path authority."""
    if os.name != "nt":
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    absolute = str(path.absolute())
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def read_json(path: Path) -> Any:
    return json.loads(io_path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def digest(path: Path) -> dict[str, Any]:
    value = hashlib.sha256()
    size = 0
    with io_path(path).open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": value.hexdigest()}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def current_hash(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    return {"path": relative, **digest(path)}


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    cases = list(root.findall(".//testcase"))
    if cases:
        return {
            "tests": len(cases),
            "failures": sum(case.find("failure") is not None for case in cases),
            "errors": sum(case.find("error") is not None for case in cases),
            "skipped": sum(case.find("skipped") is not None for case in cases),
        }
    suites = [root] if root.tag.endswith("testsuite") else list(root.findall(".//testsuite"))
    return {
        key: sum(int(float(suite.attrib.get(key, 0) or 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def preserve_historical_candidate() -> dict[str, Any]:
    files = []
    historical_io = io_path(HISTORICAL_PACKAGE)
    if historical_io.exists():
        for path in sorted(item for item in historical_io.rglob("*") if item.is_file()):
            files.append({"path": path.relative_to(historical_io).as_posix(), **digest(path)})
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "jianghu.epoch45.historical-candidate-preservation.v1",
        "historical_candidate_path": rel(HISTORICAL_PACKAGE),
        "historical_candidate_exists": HISTORICAL_PACKAGE.is_dir(),
        "historical_candidate_file_count": len(files),
        "historical_candidate_tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "historical_zip": ({"path": rel(HISTORICAL_ZIP), **digest(HISTORICAL_ZIP)} if HISTORICAL_ZIP.is_file() else None),
        "new_candidate_path": rel(PACKAGE),
        "new_candidate_version": 2,
        "policy": "The historical epoch45-remediation-candidate-v1 directory and ZIP are read-only inputs to this receipt and are never deleted or modified by this builder.",
    }


def generate_controls() -> None:
    snapshot = read_json(EVIDENCE / "snapshot-verification.json")
    platform = read_json(EVIDENCE / "platform-evidence-audit.json")
    runtime = read_json(EVIDENCE / "runtime-control-audit.json")
    source = read_json(EVIDENCE / "source-authority.json")
    e2e = read_json(EVIDENCE / "e2e-independent-verification.json")
    inspections = read_json(EVIDENCE / "inspection-summary.json")
    pre = read_json(EVIDENCE / "pre-judge-verification.json")
    post = read_json(EVIDENCE / "post-completion-verification.json")
    public_review = read_json(EVIDENCE / "public-submission-review.json")
    frozen_at = read_json(SNAPSHOT / "run-metadata.json")["generated_at"]

    server = junit_counts(EVIDENCE / "test-results" / "server-tests-junit-final.xml")
    bridge = junit_counts(EVIDENCE / "test-results" / "bridge-tests-junit.xml")
    browser = e2e["cases"]
    targeted = junit_counts(EVIDENCE / "test-results" / "memory-pause-recovery-junit.xml")
    total = server["tests"] + bridge["tests"] + int(browser["total"])
    failed = server["failures"] + server["errors"] + bridge["failures"] + bridge["errors"] + int(browser["failed"])
    skipped = server["skipped"] + bridge["skipped"]
    test_denominator = {
        "schema_version": "jianghu.epoch45.unique-test-denominator.v2",
        "denominator_id": "E45-FINAL-UNIQUE-259-v2",
        "frozen_at": frozen_at,
        "total": total,
        "passed": total - failed - skipped,
        "failed": failed,
        "errors": server["errors"] + bridge["errors"],
        "skipped": skipped,
        "outcome": "PASS" if failed == 0 and skipped == 0 and total == 259 else "FAIL",
        "components": [
            {"name": "full server/tests", "unique": True, "receipt": "commands/server-tests-full-final.receipt.json", **server},
            {"name": "Claude Agent SDK Bridge", "unique": True, "receipt": "commands/bridge-tests.receipt.json", **bridge},
            {"name": "real 5173+8003 Evidence Center E2E", "unique": True, "receipt": "commands/evidence-center-e2e-receipt.json", "tests": int(browser["total"]), "failures": int(browser["failed"]), "errors": 0, "skipped": 0},
        ],
        "overlap_exclusions": [
            {"name": "six Memory/pause/recovery targeted tests", "tests": targeted["tests"], "reason": "all are members of full server/tests"},
            {"name": "targeted convergence/Judge reruns", "reason": "members of full server/tests; retained as remediation evidence only"},
            {"name": "Bridge JUnit replay", "reason": "same ten Bridge cases as product command; format generation is not a second denominator"},
        ],
        "historical_failure_policy": "Earlier failed/rerun receipts and JUnit files remain preserved; only the named final receipts determine this current denominator.",
    }
    write_json(EVIDENCE / "unique-test-denominator.json", test_denominator)

    gaps = [
        {"id": "E45-FINAL-GAP-001", "priority": "P0", "status": "OPEN", "title": f"Required origin/master@{BASELINE} object/ref and tracked clean product checkout are absent."},
        {"id": "E45-FINAL-GAP-002", "priority": "P0", "status": "OPEN", "title": "Current epoch45 Attempt has no completed turn, member completion, five-role collaboration/synthesis, or quality closure at cutoff."},
        {"id": "E45-FINAL-GAP-003", "priority": "P0", "status": "OPEN", "title": "Current v2 package has no platform Artifact ID or created/collected/download-verified/authoritative/authority-frozen lifecycle."},
        {"id": "E45-FINAL-GAP-004", "priority": "P0", "status": "OPEN", "title": "Browser byte closure covers an existing current-Run checkpoint Artifact, not the current v2 package."},
        {"id": "E45-FINAL-GAP-005", "priority": "P0", "status": "OPEN", "title": "Current Attempt has no strict Memory candidate/review/commit/later-different-SDK retrieve/use/namespace/supersession/tombstone closure."},
        {"id": "E45-FINAL-GAP-006", "priority": "P0", "status": "OPEN", "title": "Historical strict Memory closures have distinct writer/reader SDK IDs, but no chain has both SDK identities independently corroborated by completed-turn events."},
        {"id": "E45-FINAL-GAP-007", "priority": "P0", "status": "OPEN", "title": "The only sdk.session.continued row repeats the same SDK Session ID on both sides; different-session continuation is absent."},
        {"id": "E45-FINAL-GAP-008", "priority": "P0", "status": "OPEN", "title": "Epoch45 fencing and terminal zero-duplicate scan are real, but current-Attempt object-bound reconciled-after-interruption exactly-once evidence is absent."},
        {"id": "E45-FINAL-GAP-009", "priority": "P0", "status": "OPEN", "title": "Current native Attempt supersedes artifact_af94838bcb60; corrected semantic supersession code can only govern a later persisted Attempt/Artifact lifecycle."},
        {"id": "E45-FINAL-GAP-010", "priority": "P0", "status": "OPEN", "title": "Post-rework independent quality sign-off and independent Judge ACCEPT are absent; starting a new Judge remains prohibited."},
        {"id": "E45-FINAL-GAP-011", "priority": "P0", "status": "OPEN", "title": "judge.verdict.accepted < gate.passed < run.converged < run.completed is absent and must not be fabricated pre-Judge."},
        {"id": "E45-FINAL-GAP-012", "priority": "P1", "status": "OPEN", "title": "OpenClaw residual scan and a short ten-entrypoint zero-traffic window pass, but source authority, sustained production evidence, package authority, quality and Judge approval are absent."},
    ]
    gap_denominator = {
        "schema_version": "jianghu.epoch45.unique-gap-denominator.v2",
        "denominator_id": "E45-FINAL-OPEN-GAPS-12-v2",
        "frozen_at": frozen_at,
        "total": len(gaps),
        "open": len(gaps),
        "closed": 0,
        "p0_open": sum(item["priority"] == "P0" for item in gaps),
        "p1_open": sum(item["priority"] == "P1" for item in gaps),
        "items": gaps,
    }
    write_json(EVIDENCE / "unique-gap-denominator.json", gap_denominator)

    cam_rows = [
        ("CAM-00", "authoritative source checkout", "FAIL", ["source-authority.json"]),
        ("CAM-01", "Claude Agent SDK bridge/runtime route", "PASS", ["commands/bridge-tests.receipt.json", "runtime-control-audit.json"]),
        ("CAM-02", "five-role current-Attempt execution closure", "BLOCKED", ["platform-evidence-audit.json"]),
        ("CAM-03", "Tool request/result/schema and object-bound exactly-once", "PARTIAL", ["commands/server-tests-full-final.receipt.json", "runtime-control-audit.json"]),
        ("CAM-04", "current package lifecycle and unique authority", "BLOCKED", ["artifact-authority.json"]),
        ("CAM-05", "current-Attempt public collaboration and role isolation", "BLOCKED", ["platform-evidence-audit.json"]),
        ("CAM-06", "Judge rejection causally linked to rework", "PASS", ["runtime-control-audit.json"]),
        ("CAM-07", "later independent Judge ACCEPT", "BLOCKED", ["pre-judge-verification.json"]),
        ("CAM-08", "Memory current-Attempt and different-SDK-session closure", "BLOCKED", ["runtime-control-audit.json"]),
        ("CAM-09", "pause/checkpoint/resume and continuation", "PARTIAL", ["runtime-control-audit.json"]),
        ("CAM-10", "worker recovery/fencing/object reconciliation", "PARTIAL", ["runtime-control-audit.json"]),
        ("CAM-11", "OpenClaw retirement approval", "BLOCKED", ["openclaw-production-scan.json", "runtime-control-audit.json"]),
        ("CAM-12", "post-ACCEPT ordered convergence", "BLOCKED", ["post-completion-verification.json"]),
    ]
    cam = {
        "schema_version": "jianghu.epoch45.cam-denominator.v2",
        "denominator_id": "E45-FINAL-CAM-00-12-v2",
        "total": 13,
        "pass": sum(status == "PASS" for _, _, status, _ in cam_rows),
        "fail": sum(status == "FAIL" for _, _, status, _ in cam_rows),
        "partial": sum(status == "PARTIAL" for _, _, status, _ in cam_rows),
        "blocked": sum(status == "BLOCKED" for _, _, status, _ in cam_rows),
        "release_pass": False,
        "items": [{"id": item_id, "name": name, "status": status, "evidence": evidence} for item_id, name, status, evidence in cam_rows],
        "decision_rule": "Only all 13 PASS may authorize release; PARTIAL/BLOCKED/FAIL never count as PASS.",
    }
    write_json(EVIDENCE / "cam-status.json", cam)

    mandatory = {
        "schema_version": "jianghu.epoch45.mandatory-command-summary.v2",
        "workdir": "delivery/",
        "credential_policy": "Provider-like environment variables and inherited Git override variables were removed where applicable; no environment value or credential was serialized.",
        "commands": [
            {"id": "server-tests", "command": "python -m pytest server/tests -p anyio.pytest_plugin (credential-isolated, plugin autoload disabled, delivery-scoped temp)", "exit_code": 0, "tests": 240, "passed": 240, "failed": 0, "receipt": "commands/server-tests-full-final.receipt.json"},
            {"id": "bridge-tests", "command": "npm --prefix server/claude_agent_runtime test", "exit_code": 0, "tests": 10, "passed": 10, "failed": 0, "receipt": "commands/bridge-tests.receipt.json"},
            {"id": "frontend-build", "command": "npm --prefix client run build", "exit_code": 0, "receipt": "commands/frontend-production-build.receipt.json"},
            {"id": "browser-e2e", "command": "bash tools/run_epoch45_e2e.sh (real 5173+8003)", "exit_code": 0, "tests": 9, "passed": 9, "failed": 0, "receipt": "commands/evidence-center-e2e-receipt.json"},
            {"id": "openclaw-and-credential-scans", "command": "python tools/run_epoch45_inspections.py", "exit_code": 0, "receipt": "commands/mandatory-inspections-final.receipt.json"},
            {"id": "git-diff-check", "command": "git -c core.longpaths=true diff --check", "exit_code": 0, "receipt": "commands/git-diff-check-final.receipt.json"},
            {"id": "source-authority", "command": "python tools/verify_epoch45_source_authority.py", "exit_code": 2, "expected_fail_closed": True, "receipt": "commands/source-authority.receipt.json"},
            {"id": "runtime-control-audit", "command": "python tools/audit_epoch45_runtime_controls.py", "exit_code": 0, "receipt": "commands/runtime-control-audit.receipt.json"},
            {"id": "pre-judge", "command": "python tools/verify_acceptance_phase.py --phase pre-judge ...", "exit_code": 3, "expected_fail_closed": True, "receipt": "commands/pre-judge-verification.receipt.json"},
            {"id": "post-completion", "command": "python tools/verify_acceptance_phase.py --phase post-completion ...", "exit_code": 4, "expected_fail_closed": True, "receipt": "commands/post-completion-verification.receipt.json"},
        ],
        "historical_failure_evidence_preserved": [
            "commands/server-tests-full.log", "commands/server-tests-full.receipt.json",
            "commands/server-tests-full-rerun.log", "commands/server-tests-full-rerun.receipt.json",
            "commands/evidence-center-e2e-independent-verification-attempt1-failed.log",
            "commands/evidence-center-e2e-independent-verification-attempt1-failed.receipt.json",
        ],
    }
    write_json(EVIDENCE / "mandatory-command-summary.json", mandatory)

    integration_before = {item["destination_path"]: item.get("before") for item in public_review["copied_files"]}
    changed_paths = [
        ("server/app/platform_store.py", "frozen same-connection event cursor; exact persisted event identity; same task/kind candidate supersession"),
        ("server/app/platform_executor.py", "frozen public projection accounting; persisted ACCEPT causation; semantic predecessor selection"),
        ("server/app/acceptance_verification.py", "pre-Judge/post-completion temporal split"),
        ("server/app/git_delivery.py", "per-invocation Git for Windows core.longpaths=true without SUBST"),
        ("scripts/capture-openclaw-runtime-baseline.py", "Win32 extended-path normalization for read-only SQLite URI"),
        ("client/e2e/evidence-center.mjs", "nine real browser cases, HAR, trace, request telemetry, UI download and independent hash"),
        ("server/tests/runtime_contract/test_acceptance_convergence.py", "seven deterministic convergence and supersession tests"),
        ("server/tests/runtime_contract/test_runtime_execution_safety.py", "complete frozen snapshot metadata assertions"),
        ("server/tests/test_api.py", "ACCEPT-before-terminal and exact causation assertions"),
        ("tools/audit_epoch45_runtime_controls.py", "durable public-snapshot Memory/recovery/pause/runtime audit"),
        ("tools/verify_epoch45_source_authority.py", "fail-closed b7 source authority verification"),
        ("tools/run_epoch45_e2e.sh", "final-remediation evidence root and real dual-server runner"),
        ("tools/verify_epoch45_e2e.py", "independent browser media/request/download/Manifest verification"),
    ]
    change_set = {
        "schema_version": "jianghu.epoch45.change-set.v2",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "required_source": f"origin/master@{BASELINE}",
        "source_authority_status": source["status"],
        "baseline_claimed": False,
        "files": [
            {**current_hash(path), "before": integration_before.get(path), "change": description}
            for path, description in changed_paths
        ],
        "public_submission_rows_reviewed": len(public_review["reviews"]),
        "public_submission_rows_copied": len(public_review["copied_files"]),
        "boundary": "Exact before bytes are reported only where the public integration audit retained them. Current hashes are recomputed from delivery/. Missing b7 authority is not replaced by a synthetic baseline diff.",
    }
    write_json(EVIDENCE / "change-set.json", change_set)

    issue_rows = [
        ("moving snapshot denominator", ["server/app/platform_store.py", "server/app/platform_executor.py"], "PASS_CODE_AND_TEST"),
        ("pre-Judge incorrectly depending on future terminal events", ["server/app/acceptance_verification.py"], "PASS_CODE_AND_TEST"),
        ("gate causation not bound to exact persisted ACCEPT", ["server/app/platform_store.py", "server/app/platform_executor.py", "server/tests/test_api.py"], "PASS_CODE_AND_TEST"),
        ("Artifact supersession crossing semantic kinds", ["server/app/platform_store.py", "server/app/platform_executor.py"], "PASS_CODE_AND_TEST; LATER_NATIVE_LIFECYCLE_REQUIRED"),
        ("Win32 SQLite and Git long-path failures", ["scripts/capture-openclaw-runtime-baseline.py", "server/app/git_delivery.py"], "PASS_240_OF_240"),
        ("browser evidence missing HAR/trace/download/request boundary", ["client/e2e/evidence-center.mjs", "tools/verify_epoch45_e2e.py"], "PASS_EXISTING_CURRENT_RUN_ARTIFACT; CURRENT_PACKAGE_PENDING"),
        ("Memory evidence conflated historical Run and current Attempt", ["tools/audit_epoch45_runtime_controls.py"], "DISTINCTION_ENFORCED; CURRENT_ATTEMPT_OPEN"),
        ("recovery generic scan conflated object-bound reconciliation", ["tools/audit_epoch45_runtime_controls.py"], "DISTINCTION_ENFORCED; OBJECT_RECONCILIATION_OPEN"),
        ("same-ID continuation labeled different-session", ["tools/audit_epoch45_runtime_controls.py"], "FAIL_CLOSED_GAP_RECORDED"),
        ("required b7 Git authority unavailable", ["tools/verify_epoch45_source_authority.py"], "BLOCKED_NOT_FABRICATED"),
    ]
    issue_map = {
        "schema_version": "jianghu.epoch45.issue-to-change-map.v2",
        "items": [{"issue": issue, "changes": changes, "result": result} for issue, changes, result in issue_rows],
    }
    write_json(EVIDENCE / "issue-to-change-map.json", issue_map)

    before_after = {
        "schema_version": "jianghu.epoch45.before-after.v2",
        "items": [
            {"control": "full backend", "before": "initial failures retained, including Win32 path/Git environment defects", "after": "240/240 PASS with credential/Git isolation and long-path fixes"},
            {"control": "snapshot", "before": "moving/ambiguous event denominator", "after": "174370 source = 174276 public + 94 omission receipts; exact 1..174370 domain"},
            {"control": "Judge temporal order", "before": "pre-Judge could be coupled to future terminals and ACCEPT identity was not guaranteed", "after": "pre-Judge marks terminals expected_after_accept; persisted ACCEPT ID causes gate; post verifier enforces order"},
            {"control": "Artifact supersession", "before": "task-wide candidate/predecessor selection", "after": "same run + same task + same artifact kind; current historical native supersedes remains openly unresolved"},
            {"control": "browser", "before": "missing complete current media/download/request telemetry", "after": "9/9, 9 screenshots, 91 HAR entries, 303 trace members, 87 browser requests, exact Artifact download hash"},
            {"control": "Memory", "before": "historical and current-Attempt closure could be conflated", "after": "40 historical strict event chains, 0 current-Attempt chains, 0 dual-completed-turn-attested chains"},
            {"control": "continuation", "before": "strict label could mask same SDK identity", "after": "same-ID continuation explicitly fails different-session control"},
            {"control": "recovery", "before": "generic terminal duplicate scan could be presented as object reconciliation", "after": "epoch45 fencing/scan passes; current object-bound reconciled-after-interruption count remains 0"},
            {"control": "source authority", "before": "latest b7 requirement not independently bound", "after": "explicit BLOCKED_SOURCE_AUTHORITY; no fetch/reset/invention"},
        ],
    }
    write_json(EVIDENCE / "before-after.json", before_after)

    artifact_authority = {
        "schema_version": "jianghu.epoch45.artifact-authority.v2",
        "candidate": "epoch45-final-remediation-candidate-v2",
        "platform_registry_artifact_id": None,
        "artifact_created": False,
        "artifact_collected": False,
        "artifact_download_verified": False,
        "artifact_authoritative": False,
        "artifact_authority_frozen": False,
        "current_package_browser_view_download_hash_closure": False,
        "native_current_attempt_supersedes": "artifact_af94838bcb60",
        "semantic_supersession_implementation_fixed": True,
        "native_current_attempt_semantic_supersession_reconciled": False,
        "status": "LOCAL_CANDIDATE_ONLY_PENDING_PLATFORM_POST_TURN_REGISTRATION",
    }
    write_json(EVIDENCE / "artifact-authority.json", artifact_authority)

    attempt = next(item for item in snapshot["tail_events"] if item["type"] == "attempt.created" and item["platform_attempt_id"] == ATTEMPT_ID)
    identity = {
        "schema_version": "jianghu.epoch45.run-attempt-identity.v2",
        "run_id": RUN_ID,
        "family_id": FAMILY_ID,
        "version": 9,
        "execution_epoch": 45,
        "platform_attempt_id": ATTEMPT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "cutoff_sequence": snapshot["counts"]["cutoff_sequence"],
        "snapshot_generated_at": frozen_at,
        "attempt_created": attempt,
        "frozen_state": snapshot["current_attempt_frozen_state"],
        "causal_rejection": runtime["rework_causation"]["causation_event"],
    }
    write_json(EVIDENCE / "run-attempt-identity.json", identity)

    command_files = []
    for path in sorted(item for item in (EVIDENCE / "commands").rglob("*") if item.is_file()):
        command_files.append({"path": rel(path), **digest(path)})
    command_index = {
        "schema_version": "jianghu.epoch45.command-index.v2",
        "workdir": "delivery/",
        "files": command_files,
        "file_count": len(command_files),
        "mandatory_summary": "evidence/epoch45-final-remediation/mandatory-command-summary.json",
        "preservation_rule": "Failed attempts are retained next to final passes and are never silently removed from the candidate.",
    }
    write_json(EVIDENCE / "command-index.json", command_index)
    write_json(EVIDENCE / "historical-candidate-preservation.json", preserve_historical_candidate())

    evidence_index = {
        "schema_version": "jianghu.epoch45.candidate-evidence-index.v2",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "candidate": rel(PACKAGE),
        "zip": rel(ZIP_PATH),
        "categories": {
            "formal_reports": ["Claude_Agent_SDK_全链路迁移验收报告_Epoch45_Final.md", "迁移缺口清单_Epoch45_Final.md"],
            "denominators": ["unique-test-denominator.json", "unique-gap-denominator.json", "cam-status.json"],
            "platform": ["snapshot-verification.json", "platform-evidence-audit.json", "artifact-byte-index.json", "runtime-control-audit.json"],
            "browser": ["e2e-independent-verification.json", "client/evidence/epoch45-final-remediation/e2e/"],
            "commands": ["mandatory-command-summary.json", "command-index.json", "commands/"],
            "source_and_change": ["source-authority.json", "change-set.json", "issue-to-change-map.json", "before-after.json", "public-submission-review.json"],
            "authority_and_acceptance": ["artifact-authority.json", "pre-judge-verification.json", "post-completion-verification.json"],
        },
        "authority_boundary": artifact_authority,
    }
    write_json(EVIDENCE / "candidate-evidence-index.json", evidence_index)

    report = f"""# Claude Agent SDK 全链路迁移验收报告｜Epoch 45 Final Remediation Candidate v2

## 1. 事实边界

- Run：`{RUN_ID}`；family：`{FAMILY_ID}`；version：`9`
- Attempt：`{ATTEMPT_ID}`
- Frozen snapshot：`{SNAPSHOT_ID}`；cutoff sequence：`174370`
- 最新强制源码：`origin/master@{BASELINE}`
- 工作目录：`delivery/`

源码权威校验实际返回 `BLOCKED_SOURCE_AUTHORITY`（命令 exit `2`）：目标 commit 对象与 `refs/remotes/origin/master` 均不可见，当前 `HEAD=e4d51a8c098d27f621079fead307396c5e6b0609`，产品文件虽物理存在但不在可见 Git ledger 的 tracked set 中。未 fetch、reset、伪造或改写历史。

冻结事件复算为：`source_event_count=174370`、`public_event_count=174276`、`omitted_event_count=94`，且两域合并精确覆盖 `1..174370`。Registry `6546/6546` Artifact、`9,167,814,665` 字节与来源 provenance 全部复算一致。仅读取 public-safe 对象和 omission metadata，未读取 omission 正文、环境值或 Provider 凭据。

## 2. 本轮真实整改

1. 同连接冻结事件游标，所有批次受 `sequence<=cutoff_sequence` 约束；强制 `source=public+omitted`。
2. `append_run_event` 返回真实持久化事件；Judge pass 时先写 `judge.verdict.accepted`，其真实 ID 再作为 `gate.passed` causation。
3. Artifact predecessor 与 candidate supersession 限制为 same run + same task + same artifact kind。
4. pre-Judge 与 post-completion 分相：Judge 前不要求未来 terminal；Judge 后独立验证 ACCEPT 严格先于 gate/converged/completed。
5. 修复 Win32 SQLite extended path 与 Git long path；未使用 SUBST。
6. 九用例真实 Evidence Center 流程产生 JUnit、HTML、JSON、9 张截图、91-entry HAR、303-member trace、87 条浏览器请求清单及真实下载字节复算。
7. 新增 Runtime control auditor，明确区分历史/当前 Attempt、same/different SDK Session、generic terminal scan/object reconciliation。

变更集、问题映射和前后对比见 `controls/change-set.json`、`controls/issue-to-change-map.json`、`controls/before-after.json`。

## 3. 命令、测试与浏览器结果

| 命令 | Workdir | Exit | 结果 |
|---|---|---:|---|
| Full `server/tests` | `delivery/` | 0 | 240/240 PASS |
| Claude Agent SDK Bridge | `delivery/` | 0 | 10/10 PASS |
| `npm --prefix client run build` | `delivery/` | 0 | production build PASS |
| real `5173+8003` Evidence Center E2E | `delivery/` | 0 | 9/9 PASS |
| OpenClaw residual + credential scans | `delivery/` | 0 | prohibited=0; credential findings=0 |
| `git -c core.longpaths=true diff --check` | `delivery/` | 0 | formatting check PASS |
| source authority verifier | `delivery/` | 2 | expected fail-closed blocker |
| pre-Judge verifier | `delivery/` | 3 | `NOT_READY_FOR_INDEPENDENT_JUDGE` |
| post-completion verifier | `delivery/` | 4 | `FAIL_POST_COMPLETION_ACCEPT_MISSING` |

唯一测试分母：`E45-FINAL-UNIQUE-259-v2 = 240 backend + 10 bridge + 9 browser`；`259 PASS / 0 FAIL / 0 ERROR / 0 SKIPPED`。六项 Memory/pause/recovery 定向复验是 full server suite 的重叠子集，不重复计数。历史失败日志和 JUnit 均保留。

浏览器实际下载并独立复算的是当前 Run 已登记 Artifact `artifact_ebc8d8c43bc2`：`190199` bytes，SHA-256 `7c8004bc438564ab44c4ca80c0d58a8ffa86b04691318b705bf0d4cbfa9c74f8`，API/Registry/下载字节完全一致。它不是当前 v2 package，故不建立 package browser closure。

## 4. Memory、暂停、恢复与 Runtime

同 Run 历史中有 `40` 条完整 strict Memory event chain；最新链 sequence `162544..162554` 使用不同 writer/reader SDK IDs，并包含 namespace denial、supersession、tombstone 与 old-value hiding。当前 Attempt strict chain 为 `0`；此外 reader SDK ID 未由独立 `agent.turn.completed` 行交叉佐证，因此 dual-completed-turn-attested chain 为 `0`。

暂停统计为 `run.paused=10`、`run.resumed=10`；`9/10` cycle 具有 request→checkpoint persist→paused→resumed→checkpoint load 的完整结构，`5/10` 在 public+omission sequence 域内严格静默。其余 cycle 不被覆盖或平均。

Epoch45 真实观察到 lease acquire、旧 lease revoke、stale-writer deny、fencing、checkpoint load 与 terminal duplicate scan `duplicate=0`。但 current-Attempt object-bound `reconciled_after_interruption=true` 为 `0`。唯一 `sdk.session.continued` 的 first/second SDK ID 完全相同，只证明 same-session telemetry，不能声称 different-session continuation。

十入口 route 在约 `8.465717s` 窗口内 `sample_count=10`、`openclaw_traffic=0`、`dual_write=0`、`silent_fallback=0`，且 source registry `13/13`。这是短窗事实，不是生产退役批准。

## 5. Rejection、Authority 与 Judge

Current Attempt sequence `174365` 的 `causation_event_id=evt_50cd240320a4` 精确解析到 sequence `162555 gate.rejected`，证明真实 rejection→rework 因果。冻结点内当前 Attempt 仅有 `attempt.created=1`、`task.started=1`、`team.member.started=2`，无 completed turn、Memory closure、Artifact authority 或质量签署。

本 v2 候选只建立本地确定性字节完整性。平台 authority 明确保持：

```text
platform_registry_artifact_id=null
artifact.created=false
artifact.collected=false
artifact.download.verified=false
artifact.authoritative=false
artifact.authority.frozen=false
```

pre-Judge 仍为 `{pre['status']}`。`gate.passed/run.converged/run.completed` 正确分类为 `expected_after_accept`。post-completion 为 `{post['status']}`，没有 ACCEPT 或 terminal chain 被补造。

## 6. 统一分母与裁决

- Test denominator：`E45-FINAL-UNIQUE-259-v2`：259/259 PASS。
- Gap denominator：`E45-FINAL-OPEN-GAPS-12-v2`：OPEN 12（P0 11，P1 1）。
- CAM denominator：`E45-FINAL-CAM-00-12-v2`：PASS {cam['pass']}/13；FAIL {cam['fail']}；PARTIAL {cam['partial']}；BLOCKED {cam['blocked']}。

```text
ENGINEERING_REMEDIATION=PASS
LOCAL_DETERMINISTIC_CANDIDATE=BUILT_PENDING_INDEPENDENT_VERIFICATION
SOURCE_AUTHORITY=BLOCKED_SOURCE_AUTHORITY
QUALITY_SIGN_OFF=WITHHELD
PRE_JUDGE=NOT_READY_FOR_INDEPENDENT_JUDGE
CLAUDE_AGENT_SDK_FULL_RUNTIME_MIGRATION=NO_GO
OPENCLAW_RETIREMENT=REJECTED
NEW_INDEPENDENT_JUDGE=PROHIBITED
```

产品测试全绿不能覆盖源码权威、当前 Attempt、Memory、object-bound exactly-once、当前包 authority、当前包前端下载、质量签署和 Judge terminal chain 的缺口。
"""
    (EVIDENCE / "Claude_Agent_SDK_全链路迁移验收报告_Epoch45_Final.md").write_text(report, encoding="utf-8", newline="\n")
    lines = [
        "# Epoch 45 Final Remediation 迁移缺口清单", "",
        f"唯一缺口分母：`{gap_denominator['denominator_id']}`；OPEN={gap_denominator['open']}，P0={gap_denominator['p0_open']}，P1={gap_denominator['p1_open']}。", "",
        "| ID | Priority | Status | Gap |", "|---|---|---|---|",
    ]
    lines.extend(f"| {item['id']} | {item['priority']} | {item['status']} | {item['title']} |" for item in gaps)
    lines.extend(["", "关闭规则：必须由本 Run 后续真实平台事件、Artifact 与独立复算关闭；本地测试、历史 Attempt 或短窗扫描不能自动关闭当前缺口。"])
    (EVIDENCE / "迁移缺口清单_Epoch45_Final.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def copy_file(source: Path, destination: str) -> None:
    if not io_path(source).is_file():
        raise FileNotFoundError(source)
    target = PACKAGE / destination
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(io_path(source), io_path(target))


def build_package() -> None:
    if not io_path(HISTORICAL_PACKAGE).is_dir() or not io_path(HISTORICAL_ZIP).is_file():
        raise RuntimeError("historical_epoch45_v1_candidate_missing")
    package_io = io_path(PACKAGE)
    if package_io.exists():
        shutil.rmtree(package_io)
    package_io.mkdir(parents=True)

    control_names = [
        "artifact-authority.json", "before-after.json", "cam-status.json", "candidate-evidence-index.json",
        "change-set.json", "command-index.json", "historical-candidate-preservation.json",
        "issue-to-change-map.json", "mandatory-command-summary.json", "run-attempt-identity.json",
        "unique-gap-denominator.json", "unique-test-denominator.json",
    ]
    for name in control_names:
        copy_file(EVIDENCE / name, f"controls/{name}")

    evidence_names = [
        "artifact-byte-index.json", "credential-scan.json", "e2e-denominator-reconciliation.json",
        "e2e-independent-verification.json", "inspection-summary.json", "openclaw-production-scan.json",
        "platform-evidence-audit.json", "post-completion-verification.json", "pre-judge-preconditions.json",
        "pre-judge-verification.json", "public-submission-review.json", "runtime-control-audit.json",
        "snapshot-verification.json", "source-authority.json",
    ]
    for name in evidence_names:
        copy_file(EVIDENCE / name, f"evidence/{name}")
    copy_file(EVIDENCE / "frontend-build" / "output-inventory.json", "evidence/frontend-build/output-inventory.json")
    copy_file(EVIDENCE / "Claude_Agent_SDK_全链路迁移验收报告_Epoch45_Final.md", "reports/Claude_Agent_SDK_全链路迁移验收报告_Epoch45_Final.md")
    copy_file(EVIDENCE / "迁移缺口清单_Epoch45_Final.md", "reports/迁移缺口清单_Epoch45_Final.md")

    for path in sorted(item for item in (EVIDENCE / "commands").rglob("*") if item.is_file()):
        copy_file(path, f"commands/{path.relative_to(EVIDENCE / 'commands').as_posix()}")
    for path in sorted(item for item in (EVIDENCE / "test-results").rglob("*") if item.is_file()):
        copy_file(path, f"test-results/{path.relative_to(EVIDENCE / 'test-results').as_posix()}")
    for path in sorted(item for item in BROWSER.rglob("*") if item.is_file()):
        copy_file(path, f"browser/{path.relative_to(BROWSER).as_posix()}")

    source_paths = [
        "client/e2e/evidence-center.mjs", "scripts/capture-openclaw-runtime-baseline.py",
        "server/app/acceptance_verification.py", "server/app/git_delivery.py",
        "server/app/platform_executor.py", "server/app/platform_store.py",
        "server/claude_agent_runtime/bridge.mjs", "server/claude_agent_runtime/bridge.test.mjs",
        "server/tests/runtime_contract/test_acceptance_convergence.py",
        "server/tests/runtime_contract/test_runtime_execution_safety.py", "server/tests/test_api.py",
        "tools/audit_epoch45_platform_snapshot.py", "tools/audit_epoch45_runtime_controls.py",
        "tools/build_epoch45_final_remediation_package.py", "tools/integrate_epoch45_public_submissions.py",
        "tools/run_epoch45_e2e.sh", "tools/run_epoch45_inspections.py", "tools/run_recorded_command.py",
        "tools/verify_acceptance_phase.py", "tools/verify_epoch45_e2e.py",
        "tools/verify_epoch45_snapshot.py", "tools/verify_epoch45_source_authority.py",
        "tools/verify_epoch45_final_remediation_package.py",
    ]
    for path in source_paths:
        copy_file(ROOT / path, f"source/{path}")

    for name in [
        "artifact-registry.json", "projection-omissions.json", "run-lineage.json", "run-metadata.json",
        "runtime-attestation.json", "runtime-source-attestation.json",
    ]:
        copy_file(SNAPSHOT / name, f"platform-snapshot/{name}")
    snapshot_verification = read_json(EVIDENCE / "snapshot-verification.json")
    external = {
        "schema_version": "jianghu.epoch45.external-snapshot-dependency.v2",
        "snapshot_id": SNAPSHOT_ID,
        "excluded_large_files": {
            name: snapshot_verification["files"][name]
            for name in ("events.ndjson", "critical-events.json")
        },
        "reason": "The 406 MiB public event projection and 265 MiB critical projection remain at the platform-supplied snapshot path; their exact byte receipts and independent domain audit are packaged without duplicating those bytes.",
        "privacy_boundary": "Omitted private payload bodies are not packaged or inferred.",
    }
    write_json(PACKAGE / "platform-snapshot" / "external-large-file-receipt.json", external)

    readme = f"""# Epoch45 Final Remediation Candidate v2

Run `{RUN_ID}`; Attempt `{ATTEMPT_ID}`; frozen cutoff `174370`.

This directory and its ZIP are local deterministic candidate bytes only. Required source authority `origin/master@{BASELINE}` is blocked, platform package Artifact ID is null, pre-Judge is NOT_READY, and no independent Judge is started. Historical `epoch45-remediation-candidate-v1` bytes are not modified.
"""
    io_path(PACKAGE / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    payload = []
    package_io = io_path(PACKAGE)
    for path in sorted(item for item in package_io.rglob("*") if item.is_file() and item.name != "final_manifest.json"):
        payload.append({"path": path.relative_to(package_io).as_posix(), **digest(path)})
    frozen_at = read_json(SNAPSHOT / "run-metadata.json")["generated_at"]
    manifest = {
        "schema_version": "jianghu.epoch45.self-excluding-manifest.v2",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "candidate_version": 2,
        "frozen_at": frozen_at,
        "payload_count": len(payload),
        "payload_bytes": sum(item["size_bytes"] for item in payload),
        "files": payload,
        "exclusion_rule": "final_manifest.json excludes itself and is written last in the ZIP",
        "zip_policy": {"timestamp": "1980-01-01T00:00:00", "unix_mode": "0100644", "path_order": "UTF-8 relative path lexical order; manifest last"},
        "platform_registry_artifact_id": None,
    }
    write_json(PACKAGE / "final_manifest.json", manifest)

    io_path(ZIP_PATH.parent).mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io_path(ZIP_PATH), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for relative in [item["path"] for item in payload] + ["final_manifest.json"]:
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, io_path(PACKAGE / relative).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    receipt = {
        "schema_version": "jianghu.epoch45.package-receipt.v2",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "candidate_version": 2,
        "package_directory": rel(PACKAGE),
        "manifest": {"path": rel(PACKAGE / "final_manifest.json"), **digest(PACKAGE / "final_manifest.json")},
        "zip": {"path": rel(ZIP_PATH), **digest(ZIP_PATH)},
        "zip_member_count": len(payload) + 1,
        "historical_v1_preserved": preserve_historical_candidate(),
        "platform_registry_artifact_id": None,
        "authority_status": "LOCAL_CANDIDATE_PENDING_PLATFORM_REGISTRATION",
    }
    write_json(RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def main() -> int:
    generate_controls()
    build_package()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
