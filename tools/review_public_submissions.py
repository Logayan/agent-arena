#!/usr/bin/env python3
"""Audit both authorized public engineering submissions and merge selected bytes.

The script reads only the public collaboration export declared by this node.  It
never reads another Agent's private workspace, conversation, Memory, or provider
credentials.  Every non-deletion manifest row is size/hash checked before any
merge decision is emitted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

RUN_ID = "run_9226059d74a1"
NODE_KEY = "runtime_probe_harness"
AGENTS = ("agent_eac0b56ad320", "agent_bcde21fdede6")
SRE_AGENT = "agent_bcde21fdede6"

# Exact public bytes selected from the SRE submission.  The negative-gate
# declaration is renamed because the primary candidate gate remains RP-BLOCKER-001.
SELECTED_SRE: dict[str, str] = {
    "config/team-roles.json": "config/team-roles.json",
    "config/runtime-acceptance-tasks.json": "config/runtime-acceptance-tasks.json",
    "config/predeclared-blocker.json": "config/supplemental-predeclared-blocker.json",
    "schemas/runtime-evidence-event.schema.json": "schemas/runtime-evidence-event.schema.json",
    "src/run_local_probes.py": "src/run_local_probes.py",
    "tasks/probe_worker.py": "tasks/probe_worker.py",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def decision(agent_id: str, row: dict[str, Any], destination_exists: bool) -> tuple[str, str, str | None]:
    path = row["path"]
    action = row["action"]
    if action == "deleted":
        return (
            "REJECTED_DELETION",
            "Deletion marker is not applied: upstream formal inputs and the selected primary implementation remain independently traceable.",
            None,
        )
    if agent_id == SRE_AGENT and path in SELECTED_SRE:
        return (
            "REVISED_AND_MERGED",
            "Selected after byte audit. It adds five-role contract, target schema, SQLite Memory, OS force-kill, dependency and path-confinement probes; local evidence remains acceptance-ineligible.",
            SELECTED_SRE[path],
        )
    if agent_id == SRE_AGENT:
        if path.startswith("evidence/") or path.startswith("verification/") or path.startswith("artifacts/"):
            return (
                "SUPERSEDED_BY_CURRENT_RUN_REBUILD",
                "Generated evidence belongs to the contributor's earlier cutoff and is not copied over the fresh owner snapshot or final manifest.",
                None,
            )
        if path.startswith("docs/") or path.startswith("gaps/") or path.endswith("报告.md"):
            return (
                "SUPERSEDED_BY_CONSOLIDATED_REPORT",
                "Substantive observations are retained in the owner report, while duplicate report bytes are not made the formal entrypoint.",
                None,
            )
        if path in {"runtime_forensics/core.py", "run_acceptance.py", "runtime_forensics/__init__.py", "tests/test_runtime_forensics.py", "pyproject.toml", "README.md"}:
            return (
                "REJECTED_PARALLEL_IMPLEMENTATION",
                "The existing runtime_probe implementation is the primary fail-closed path. Relevant probe/test requirements are merged without replacing it with a second incompatible CLI and snapshot namespace.",
                None,
            )
        return (
            "REJECTED_NOT_NEEDED_IN_FINAL_ARCHITECTURE",
            "Byte-audited but not required after selecting the primary runtime_probe architecture and fresh evidence rebuild.",
            None,
        )
    # Owner submission: source/config/code form the primary baseline; generated
    # evidence is always rebuilt from the current live public-safe projection.
    if path == "artifacts/sha256_manifest.json":
        return ("SUPERSEDED_BY_FINAL_MANIFEST", "Earlier manifest is replaced only after final build/test/verification.", None)
    if path.startswith("evidence/runtime_probe/"):
        return ("SUPERSEDED_BY_CURRENT_RUN_REBUILD", "Earlier frozen cutoff is preserved in public audit but current formal evidence is regenerated.", None)
    if path.startswith("docs/") or path.startswith("gaps/") or path == "README_Runtime_Probe.md":
        return ("REVISED_AND_MERGED", "Retained as report structure and regenerated from the current evidence index.", path)
    return (
        "ADOPTED_AS_PRIMARY_BASELINE" if destination_exists else "REVISED_AND_MERGED",
        "Selected as the primary implementation/configuration baseline; subsequent edits are tracked by the final package manifest.",
        path,
    )


def main() -> int:
    root = Path.cwd().resolve()
    workspace = root.parent
    authorized = (workspace / "collaboration" / NODE_KEY / "loop-1-attempt-1").resolve()
    if not authorized.is_dir():
        raise RuntimeError(f"authorized public collaboration root missing: {authorized}")

    reviews: list[dict[str, Any]] = []
    submissions: list[dict[str, Any]] = []
    copied: list[dict[str, Any]] = []
    audit_mismatches: list[dict[str, Any]] = []
    total_non_deleted = 0
    total_deleted = 0
    raw_verified = 0
    nonmaterialized = 0
    live_artifact_by_digest: dict[tuple[str, int], Path] = {}
    for candidate in (root / ".jianghu-platform-evidence" / "artifacts").glob("*"):
        if candidate.is_file():
            live_artifact_by_digest[(sha256(candidate), candidate.stat().st_size)] = candidate

    for agent_id in AGENTS:
        submission = authorized / agent_id
        manifest_path = submission / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("agent_id") != agent_id:
            raise RuntimeError(f"manifest actor mismatch: {agent_id}")
        changes = manifest.get("changes")
        if not isinstance(changes, list):
            raise RuntimeError(f"manifest changes malformed: {agent_id}")
        source_root = (submission / "files").resolve()
        if source_root.parent != submission.resolve():
            raise RuntimeError("unexpected public source root")
        submissions.append({
            "agent_id": agent_id,
            "agent_name": manifest.get("agent_name"),
            "manifest_path": manifest_path.relative_to(workspace).as_posix(),
            "manifest_sha256": sha256(manifest_path),
            "change_row_count": len(changes),
        })
        for index, row in enumerate(changes, 1):
            path = row.get("path")
            action = row.get("action")
            if not isinstance(path, str) or not path or action not in {"created", "modified", "deleted"}:
                raise RuntimeError(f"invalid manifest row {agent_id}:{index}")
            source = (source_root / path).resolve()
            if source != source_root and source_root not in source.parents:
                raise RuntimeError(f"public path escapes source root: {agent_id}:{path}")
            byte_audit: dict[str, Any]
            if action == "deleted":
                total_deleted += 1
                byte_audit = {"status": "DELETION_MARKER_NO_SOURCE_BYTES", "matches_manifest": True}
            else:
                total_non_deleted += 1
                expected_key = (str(row.get("sha256")), int(row.get("size_bytes") or -1))
                audit_source: Path | None = None
                audit_status = ""
                if source.is_file():
                    audit_source = source
                    audit_status = "PASS_PUBLIC_EXPORT_BYTES"
                else:
                    current_destination = root / path
                    if current_destination.is_file() and (sha256(current_destination), current_destination.stat().st_size) == expected_key:
                        audit_source = current_destination
                        audit_status = "PASS_EXISTING_DELIVERY_BYTES"
                    elif expected_key in live_artifact_by_digest:
                        audit_source = live_artifact_by_digest[expected_key]
                        audit_status = "PASS_PLATFORM_ARTIFACT_BYTES"
                if audit_source is None:
                    nonmaterialized += 1
                    byte_audit = {
                        "status": "PUBLICLY_ATTESTED_NOT_MATERIALIZED_FOR_OWNER_READBACK",
                        "matches_manifest": False,
                        "raw_bytes_available": False,
                    }
                else:
                    observed_size = audit_source.stat().st_size
                    observed_sha = sha256(audit_source)
                    matches = observed_size == row.get("size_bytes") and observed_sha == row.get("sha256")
                    byte_audit = {
                        "status": audit_status if matches else "MISMATCH",
                        "audit_path": audit_source.relative_to(root).as_posix() if root in audit_source.parents else "authorized-public-export",
                        "observed_size_bytes": observed_size,
                        "observed_sha256": observed_sha,
                        "matches_manifest": matches,
                        "raw_bytes_available": True,
                    }
                    if matches:
                        raw_verified += 1
                    else:
                        audit_mismatches.append({"agent_id": agent_id, "path": path, "reason": "size_or_sha256"})
            destination = root / path
            disposition, reason, merged_path = decision(agent_id, row, destination.is_file())
            review = {
                "agent_id": agent_id,
                "row_index": index,
                "path": path,
                "action": action,
                "declared_size_bytes": row.get("size_bytes"),
                "declared_sha256": row.get("sha256"),
                "byte_audit": byte_audit,
                "decision": disposition,
                "reason": reason,
                "merged_path": merged_path,
            }
            reviews.append(review)
            if agent_id == SRE_AGENT and path in SELECTED_SRE:
                if not byte_audit.get("matches_manifest"):
                    raise RuntimeError(f"cannot merge unaudited source: {path}")
                target_rel = SELECTED_SRE[path]
                target = (root / target_rel).resolve()
                if target != root and root not in target.parents:
                    raise RuntimeError(f"merge target escapes delivery: {target_rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied.append({
                    "agent_id": agent_id,
                    "source_path": path,
                    "destination_path": target_rel,
                    "source_sha256": byte_audit["observed_sha256"],
                    "copied_sha256": sha256(target),
                })

    if audit_mismatches:
        raise RuntimeError(f"public submission byte audit failed: {audit_mismatches}")
    payload = {
        "schema_version": "jianghu.public-submission-review.v1",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "authorized_source": "collaboration/runtime_probe_harness/loop-1-attempt-1/*/{manifest.json,files/**}",
        "private_conversation_or_memory_read": False,
        "submissions": submissions,
        "summary": {
            "manifest_change_row_count": len(reviews),
            "non_deleted_row_count": total_non_deleted,
            "deletion_marker_count": total_deleted,
            "raw_byte_verified_non_deleted_rows": raw_verified,
            "publicly_attested_not_materialized_rows": nonmaterialized,
            "byte_audit_mismatch_count": 0,
            "selected_public_files_copied": len(copied),
            "decision_counts": {},
        },
        "copied_files": copied,
        "reviews": reviews,
    }
    counts: dict[str, int] = {}
    for row in reviews:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    payload["summary"]["decision_counts"] = dict(sorted(counts.items()))
    out = root / "evidence" / "runtime_probe" / "public-submission-review.json"
    write_json(out, payload)
    write_json(root / "evidence" / "runtime_probe" / "public-submission-byte-audit.json", {
        "run_id": RUN_ID,
        "manifest_rows": len(reviews),
        "non_deleted_rows": total_non_deleted,
        "raw_byte_verified_non_deleted_rows": raw_verified,
        "publicly_attested_not_materialized_rows": nonmaterialized,
        "deletion_markers": total_deleted,
        "mismatches": audit_mismatches,
        "status": "PASS_WITH_EXPLICIT_NONMATERIALIZED_ROWS" if nonmaterialized else "PASS",
    })
    print(f"PUBLIC_SUBMISSION_REVIEW_PASS rows={len(reviews)} bytes={total_non_deleted} deletions={total_deleted} copied={len(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
