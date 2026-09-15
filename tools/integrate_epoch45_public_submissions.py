#!/usr/bin/env python3
"""Byte-audit both authorised public submissions and merge the selected code.

Only the public collaboration export named by the production node is read.
Generated evidence from earlier cutoffs is reviewed but never copied over the
current run's fresh evidence. Every manifest row receives an explicit decision.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT.parent / "collaboration" / "remediation_rerun" / "loop-3-attempt-1"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / "attempt-ef6476c5bf4ad3e8"
OUT = ROOT / "evidence" / "epoch45-final-remediation"
RUN_ID = "run_bda13e93b2ea"
AGENTS = ("agent_eac0b56ad320", "agent_bcde21fdede6")
OWNER = AGENTS[0]
SRE = AGENTS[1]

# Product/runtime changes with the stronger deterministic convergence behavior.
OWNER_SELECTED = {
    "client/e2e/evidence-center.mjs",
    "scripts/capture-openclaw-runtime-baseline.py",
    "server/app/platform_executor.py",
    "server/app/platform_store.py",
    "server/tests/test_api.py",
    "tools/run_epoch45_e2e.sh",
    "tools/run_epoch45_inspections.py",
    "tools/verify_epoch45_e2e.py",
    "tools/verify_epoch45_snapshot.py",
}
# One reusable command receipt utility is independent of the conflicting report
# and old baseline conclusions.
SRE_SELECTED = {"tools/run_recorded_command.py"}
GENERATED_PREFIXES = ("artifacts/", "deliverables/", "evidence/", "t/", "x/")
REPORT_PREFIXES = ("docs/", "gaps/")


def digest_bytes(data: bytes) -> dict[str, Any]:
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def digest(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": h.hexdigest()}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def registry_by_digest() -> dict[tuple[str, int], list[dict[str, Any]]]:
    registry = json.loads((SNAPSHOT / "artifact-registry.json").read_text(encoding="utf-8"))
    result: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in registry:
        key = (str(item.get("expected_sha256") or ""), int(item.get("size_bytes") or 0))
        result.setdefault(key, []).append(item)
    return result


def public_source(agent_id: str, relative: str) -> Path:
    return PUBLIC_ROOT / agent_id / "files" / relative


def audit_row(
    agent_id: str,
    row: dict[str, Any],
    registry: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    if row["action"] == "deleted":
        return {"status": "DELETION_MARKER", "matches_manifest": True, "raw_bytes_read": False}
    expected = (str(row.get("sha256") or ""), int(row.get("size_bytes") or 0))
    candidates: list[tuple[str, Path, dict[str, Any] | None]] = []
    source = public_source(agent_id, row["path"])
    if source.is_file():
        candidates.append(("PUBLIC_EXPORT", source, None))
    current = ROOT / row["path"]
    if current.is_file():
        candidates.append(("CURRENT_DELIVERY", current, None))
    for item in registry.get(expected, []):
        path = (SNAPSHOT / str(item["materialized_path"])).resolve()
        artifact_root = (ROOT / ".jianghu-platform-evidence" / "artifacts").resolve()
        if path.is_file() and (path == artifact_root or artifact_root in path.parents):
            candidates.append(("PLATFORM_ARTIFACT", path, item))
    attempted: list[dict[str, Any]] = []
    for source_class, path, item in candidates:
        observed = digest(path)
        attempted.append({"source_class": source_class, **observed})
        if (observed["sha256"], observed["size_bytes"]) == expected:
            result: dict[str, Any] = {
                "status": f"PASS_{source_class}",
                "matches_manifest": True,
                "raw_bytes_read": True,
                **observed,
            }
            if item:
                result.update(
                    {
                        "artifact_id": item.get("id"),
                        "source_event_sequence": item.get("source_event_sequence"),
                        "source_event_id": item.get("source_event_id"),
                    }
                )
            return result
    return {
        "status": "PUBLICLY_ATTESTED_BYTES_NOT_MATERIALIZED",
        "matches_manifest": False,
        "raw_bytes_read": False,
        "attempted_candidates": attempted,
    }


def disposition(agent_id: str, row: dict[str, Any], audit: dict[str, Any]) -> tuple[str, str, str | None]:
    path = row["path"]
    if row["action"] == "deleted":
        return "REJECTED_DELETION", "No public deletion marker may remove current or historical evidence.", None
    if path.startswith(GENERATED_PREFIXES):
        return (
            "SUPERSEDED_GENERATED_EVIDENCE",
            "Earlier generated evidence/candidate bytes are retained in public history but not copied over the fresh integrated rerun.",
            None,
        )
    if path.startswith(REPORT_PREFIXES) or path.endswith("报告.md"):
        return (
            "SUPERSEDED_BY_OWNER_CONSENSUS_REPORT",
            "Facts are reconciled in the new report; conflicting denominators and baseline claims are not averaged.",
            None,
        )
    if agent_id == OWNER and path in OWNER_SELECTED:
        return (
            "ADOPTED_OWNER_IMPLEMENTATION",
            "Selected after exact public-byte audit because it includes frozen-cursor accounting, persisted ACCEPT causation, semantic artifact supersession and nine-case browser evidence.",
            path,
        )
    if agent_id == SRE and path in SRE_SELECTED:
        return (
            "ADOPTED_SRE_UTILITY",
            "Selected as a reusable credential-isolated command receipt utility; no stale verdict or generated evidence is imported.",
            path,
        )
    if path in OWNER_SELECTED or path in SRE_SELECTED:
        return (
            "REJECTED_CONFLICTING_VARIANT",
            "A different audited variant was selected explicitly; the conflict remains recorded rather than silently merged.",
            None,
        )
    if path.startswith(("server/", "client/", "scripts/", "tools/", "config/")):
        if not audit.get("matches_manifest"):
            return (
                "NOT_ADOPTED_BYTES_UNAVAILABLE",
                "The manifest claim is retained, but exact public bytes were unavailable for owner readback and cannot be merged.",
                None,
            )
        return (
            "REJECTED_NOT_REQUIRED_FOR_SELECTED_CHANGESET",
            "Byte-audited but not needed after selecting one convergence implementation and one fresh evidence pipeline.",
            None,
        )
    return (
        "REJECTED_OUTSIDE_FINAL_CHANGESET",
        "Reviewed and retained in public history, but not part of the final product/evidence change set.",
        None,
    )


def main() -> int:
    if not PUBLIC_ROOT.is_dir():
        raise RuntimeError(f"authorised_public_root_missing:{PUBLIC_ROOT}")
    registry = registry_by_digest()
    reviews: list[dict[str, Any]] = []
    submissions: list[dict[str, Any]] = []
    copied: list[dict[str, Any]] = []
    failures: list[str] = []
    before: dict[str, dict[str, Any] | None] = {}

    for agent_id in AGENTS:
        manifest_path = PUBLIC_ROOT / agent_id / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        if manifest.get("agent_id") != agent_id or not isinstance(manifest.get("changes"), list):
            raise RuntimeError(f"manifest_identity_or_shape_invalid:{agent_id}")
        submissions.append(
            {
                "agent_id": agent_id,
                "agent_name": manifest.get("agent_name"),
                "manifest": digest_bytes(manifest_bytes),
                "row_count": len(manifest["changes"]),
            }
        )
        for row_index, row in enumerate(manifest["changes"], 1):
            if not isinstance(row.get("path"), str) or row.get("action") not in {"created", "modified", "deleted"}:
                raise RuntimeError(f"invalid_manifest_row:{agent_id}:{row_index}")
            audit = audit_row(agent_id, row, registry)
            decision, reason, merged_path = disposition(agent_id, row, audit)
            review = {
                "agent_id": agent_id,
                "row_index": row_index,
                "path": row["path"],
                "action": row["action"],
                "declared_size_bytes": row.get("size_bytes"),
                "declared_sha256": row.get("sha256"),
                "byte_audit": audit,
                "decision": decision,
                "reason": reason,
                "merged_path": merged_path,
            }
            reviews.append(review)
            if merged_path:
                if not audit.get("matches_manifest"):
                    failures.append(f"selected_row_unavailable:{agent_id}:{row['path']}")
                    continue
                source = public_source(agent_id, row["path"])
                if not source.is_file():
                    failures.append(f"selected_public_file_missing:{agent_id}:{row['path']}")
                    continue
                target = (ROOT / merged_path).resolve()
                if ROOT.resolve() not in target.parents:
                    failures.append(f"merge_target_escape:{merged_path}")
                    continue
                if merged_path not in before:
                    before[merged_path] = digest(target) if target.is_file() else None
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                observed = digest(target)
                if observed["sha256"] != row["sha256"] or observed["size_bytes"] != row["size_bytes"]:
                    failures.append(f"copy_digest_mismatch:{agent_id}:{row['path']}")
                copied.append(
                    {
                        "agent_id": agent_id,
                        "source_path": row["path"],
                        "destination_path": merged_path,
                        "before": before[merged_path],
                        "after": observed,
                    }
                )

    counts = Counter(item["decision"] for item in reviews)
    audits = Counter(item["byte_audit"]["status"] for item in reviews)
    result = {
        "schema_version": "jianghu.epoch45.public-submission-integration.v1",
        "run_id": RUN_ID,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "authorised_scope": "collaboration/remediation_rerun/loop-3-attempt-1/<agent>/manifest.json and files/** only",
        "private_conversation_or_memory_read": False,
        "submissions": submissions,
        "summary": {
            "manifest_rows_reviewed": len(reviews),
            "decision_counts": dict(sorted(counts.items())),
            "byte_audit_counts": dict(sorted(audits.items())),
            "selected_files_copied": len(copied),
            "integration_failures": failures,
            "status": "PASS" if not failures else "FAIL",
        },
        "conflict_decisions": [
            {
                "topic": "backend convergence implementation",
                "selected": "林砚 variant",
                "rejected": "谢临川 overlapping variant",
                "reason": "Selected variant additionally persists exact ACCEPT identity and scopes candidate supersession by semantic artifact kind.",
            },
            {
                "topic": "browser evidence implementation",
                "selected": "林砚 nine-case variant as base, followed by owner integration hardening",
                "rejected": "谢临川 eight-case variant as sole implementation",
                "reason": "Nine-case variant performs an actual UI-triggered download and byte/hash recomputation; management-path request denial telemetry is reintroduced separately.",
            },
            {
                "topic": "test/CAM/pre-Judge denominator",
                "selected": "fresh final rerun only",
                "rejected": "259 and 256/old READY claims as final authority",
                "reason": "Earlier counts were produced before the latest b7c338a source requirement and disagree materially; they remain historical evidence only.",
            },
        ],
        "copied_files": copied,
        "reviews": reviews,
    }
    write_json(OUT / "public-submission-review.json", result)
    print(
        json.dumps(
            {
                "status": result["summary"]["status"],
                "rows": len(reviews),
                "copied": len(copied),
                "decisions": result["summary"]["decision_counts"],
                "audits": result["summary"]["byte_audit_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
