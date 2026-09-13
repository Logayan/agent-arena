from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from . import NODE_KEY, RUN_ID

REJECT_EXIT = 42


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(candidate_path: Path, blocker_path: Path) -> dict[str, Any]:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    blocker = json.loads(blocker_path.read_text(encoding="utf-8"))
    reasons: list[str] = []
    if candidate.get("run_id") != RUN_ID or candidate.get("node_key") != NODE_KEY:
        reasons.append("candidate_identity_mismatch")
    provenance = candidate.get("collector_provenance")
    if blocker.get("active") and (
        not isinstance(provenance, dict)
        or not provenance.get("snapshot_sha256")
        or not provenance.get("capture_receipt_sha256")
    ):
        reasons.append("RP-BLOCKER-001:collector_provenance_missing")
    if candidate.get("candidate_version", 0) > 1 and not candidate.get("rework_of_sha256"):
        reasons.append("immutable_rework_link_missing")
    return {
        "schema_version": "jianghu.local-pre-gate-receipt.v1",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "candidate_path": candidate_path.as_posix(),
        "candidate_sha256": digest(candidate_path),
        "blocker_path": blocker_path.as_posix(),
        "blocker_sha256": digest(blocker_path),
        "verdict": "REJECT" if reasons else "ACCEPT_LOCAL_PRE_GATE",
        "reasons": reasons,
        "exit_code": REJECT_EXIT if reasons else 0,
        "evidence_class": "deterministic_local_pre_gate",
        "acceptance_eligible": False,
        "not_a_platform_judge_event": True,
    }


def remediate(candidate_path: Path, output_path: Path, snapshot_path: Path, capture_receipt_path: Path) -> dict[str, Any]:
    original_bytes = candidate_path.read_bytes()
    original = json.loads(original_bytes.decode("utf-8"))
    result = dict(original)
    result["candidate_version"] = int(original.get("candidate_version", 1)) + 1
    result["status"] = "LOCAL_REMEDIATION_CANDIDATE_PLATFORM_REJUDGE_PENDING"
    result["rework_of_sha256"] = hashlib.sha256(original_bytes).hexdigest()
    result["collector_provenance"] = {
        "snapshot_path": snapshot_path.as_posix(),
        "snapshot_sha256": digest(snapshot_path),
        "capture_receipt_path": capture_receipt_path.as_posix(),
        "capture_receipt_sha256": digest(capture_receipt_path),
    }
    result["platform_attempt_id"] = None
    result["platform_rejudge_status"] = "PENDING_NOT_FABRICATED"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if candidate_path.read_bytes() != original_bytes:
        raise RuntimeError("candidate-v1 mutated during remediation")
    return result
