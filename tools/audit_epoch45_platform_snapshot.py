#!/usr/bin/env python3
"""Independently audit the supplied frozen platform snapshot and Registry bytes."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ID = "attempt-ef6476c5bf4ad3e8"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / SNAPSHOT_ID
OUT = ROOT / "evidence" / "epoch45-final-remediation"
RUN_ID = "run_bda13e93b2ea"
ATTEMPT_ID = "attempt:run_bda13e93b2ea:remediation_rerun:epoch45:loop3:node1"
ARTIFACT_ROOT = (ROOT / ".jianghu-platform-evidence" / "artifacts").resolve()


def file_digest(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": h.hexdigest()}


def canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def event_attempt(event: dict[str, Any]) -> str | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return payload.get("platform_attempt_id") or event.get("platform_attempt_id")


def main() -> int:
    metadata = json.loads((SNAPSHOT / "run-metadata.json").read_text(encoding="utf-8"))
    omissions_doc = json.loads((SNAPSHOT / "projection-omissions.json").read_text(encoding="utf-8"))
    omissions = list(omissions_doc.get("omissions") or [])
    cutoff = int(metadata["cutoff_sequence"])
    seen = bytearray(cutoff + 1)
    events_by_sequence: dict[int, dict[str, Any]] = {}
    event_ids: set[str] = set()
    event_types: Counter[str] = Counter()
    current_attempt_events: list[dict[str, Any]] = []
    projected_count = 0
    duplicate_sequences: list[int] = []
    out_of_boundary: list[int] = []
    event_file = SNAPSHOT / "events.ndjson"
    with event_file.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            event = json.loads(line)
            projected_count += 1
            sequence = int(event["sequence"])
            event_id = str(event.get("event_id") or event.get("id") or "")
            if not event_id or event_id in event_ids:
                raise RuntimeError(f"duplicate_or_missing_event_id:{line_number}:{event_id}")
            event_ids.add(event_id)
            if 1 <= sequence <= cutoff:
                if seen[sequence]:
                    duplicate_sequences.append(sequence)
                seen[sequence] = 1
            else:
                out_of_boundary.append(sequence)
            events_by_sequence[sequence] = event
            event_types[str(event.get("type") or "")] += 1
            if event_attempt(event) == ATTEMPT_ID:
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                current_attempt_events.append(
                    {
                        "sequence": sequence,
                        "event_id": event_id,
                        "type": event.get("type"),
                        "actor_id": event.get("actor_id"),
                        "platform_attempt_id": event_attempt(event),
                        "rework_of": payload.get("rework_of"),
                        "supersedes": payload.get("supersedes"),
                        "causation_event_id": payload.get("causation_event_id"),
                        "source_event_sha256": event.get("source_event_sha256"),
                    }
                )
    for item in omissions:
        sequence = int(item["sequence"])
        if 1 <= sequence <= cutoff:
            if seen[sequence]:
                duplicate_sequences.append(sequence)
            seen[sequence] = 1
        else:
            out_of_boundary.append(sequence)
    missing_sequences = [index for index in range(1, cutoff + 1) if not seen[index]]

    registry = json.loads((SNAPSHOT / "artifact-registry.json").read_text(encoding="utf-8"))
    artifact_index: list[dict[str, Any]] = []
    artifact_ids: set[str] = set()
    byte_failures: list[dict[str, Any]] = []
    provenance_failures: list[dict[str, Any]] = []
    path_failures: list[dict[str, Any]] = []
    lifecycle: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events_by_sequence.values():
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        artifact_id = payload.get("artifact_id")
        if artifact_id:
            lifecycle[str(artifact_id)][str(event.get("type") or "")] += 1

    total_bytes = 0
    for item in registry:
        artifact_id = str(item.get("id") or "")
        if not artifact_id or artifact_id in artifact_ids:
            raise RuntimeError(f"duplicate_or_missing_artifact_id:{artifact_id}")
        artifact_ids.add(artifact_id)
        materialized = (SNAPSHOT / str(item.get("materialized_path") or "")).resolve()
        path_confined = materialized.is_file() and ARTIFACT_ROOT in materialized.parents
        if not path_confined:
            path_failures.append({"artifact_id": artifact_id, "materialized_path": item.get("materialized_path")})
            observed = {"size_bytes": None, "sha256": None}
        else:
            observed = file_digest(materialized)
            total_bytes += int(observed["size_bytes"])
        byte_exact = (
            observed["size_bytes"] == int(item.get("size_bytes") or 0)
            and observed["sha256"] == str(item.get("expected_sha256") or "")
            and observed["sha256"] == str(item.get("observed_sha256") or "")
        )
        if not byte_exact:
            byte_failures.append(
                {
                    "artifact_id": artifact_id,
                    "expected_size_bytes": item.get("size_bytes"),
                    "expected_sha256": item.get("expected_sha256"),
                    "registry_observed_sha256": item.get("observed_sha256"),
                    "actual": observed,
                }
            )
        source_sequence = int(item.get("source_event_sequence") or 0)
        source_event = events_by_sequence.get(source_sequence)
        source_event_id = str(item.get("source_event_id") or "")
        source_hash = str(item.get("source_event_sha256") or "")
        provenance_exact = bool(
            source_event
            and str(source_event.get("event_id") or source_event.get("id") or "") == source_event_id
            and str(source_event.get("source_event_sha256") or "") == source_hash
            and str(source_event.get("run_id") or "") == RUN_ID
        )
        if not provenance_exact:
            provenance_failures.append(
                {
                    "artifact_id": artifact_id,
                    "source_event_sequence": source_sequence,
                    "source_event_id": source_event_id,
                    "source_event_sha256": source_hash,
                }
            )
        counts = lifecycle.get(artifact_id, Counter())
        artifact_index.append(
            {
                "artifact_id": artifact_id,
                "kind": item.get("kind"),
                "status": item.get("status"),
                "source_node_key": item.get("source_node_key"),
                "source_relative_path": item.get("source_relative_path"),
                "materialized_path": item.get("materialized_path"),
                "source_event_sequence": source_sequence,
                "source_event_id": source_event_id,
                "source_event_sha256": source_hash,
                "expected_size_bytes": item.get("size_bytes"),
                "expected_sha256": item.get("expected_sha256"),
                "actual_size_bytes": observed["size_bytes"],
                "actual_sha256": observed["sha256"],
                "byte_exact": byte_exact,
                "provenance_exact": provenance_exact,
                "lifecycle": {
                    "artifact.created": counts["artifact.created"],
                    "artifact.collected": counts["artifact.collected"],
                    "artifact.download.verified": counts["artifact.download.verified"],
                    "artifact.authoritative": counts["artifact.authoritative"],
                    "artifact.authority.frozen": counts["artifact.authority.frozen"],
                },
            }
        )

    current_counts = Counter(item["type"] for item in current_attempt_events)
    source_count = projected_count + len(omissions)
    event_checks = {
        "run_id_exact": metadata.get("id") == RUN_ID,
        "attempt_id_exact": metadata.get("platform_attempt_id") == ATTEMPT_ID,
        "event_count_equals_source": int(metadata.get("event_count") or 0) == source_count,
        "source_event_count_equals_source": int(metadata.get("source_event_count") or 0) == source_count,
        "public_event_count_equals_projection": int(metadata.get("public_event_count") or 0) == projected_count,
        "omitted_event_count_equals_receipt": int(metadata.get("omitted_event_count") or 0) == len(omissions),
        "source_equals_public_plus_omitted": source_count == projected_count + len(omissions),
        "cutoff_equals_source_count": cutoff == source_count,
        "omissions_positive": len(omissions) > 0,
        "sequence_domain_exact": not duplicate_sequences and not missing_sequences and not out_of_boundary,
    }
    authority_events = [
        {
            "sequence": sequence,
            "event_id": event.get("event_id") or event.get("id"),
            "type": event.get("type"),
            "payload": {
                key: value
                for key, value in (event.get("payload") or {}).items()
                if key in {
                    "artifact_id", "authoritative_artifact_ids", "superseded_artifact_ids",
                    "authority_manifest_sha256", "platform_attempt_id", "causation_event_id", "supersedes",
                }
            },
        }
        for sequence, event in sorted(events_by_sequence.items())
        if event.get("type") in {"artifact.superseded", "artifact.authoritative", "artifact.authority.frozen"}
    ]
    result = {
        "schema_version": "jianghu.epoch45.platform-evidence-audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_files": {
            name: file_digest(SNAPSHOT / name)
            for name in (
                "events.ndjson", "critical-events.json", "artifact-registry.json", "run-metadata.json",
                "run-lineage.json", "runtime-attestation.json", "runtime-source-attestation.json",
                "projection-omissions.json",
            )
        },
        "event_counts": {
            "metadata_event_count": int(metadata.get("event_count") or 0),
            "source_event_count": source_count,
            "public_event_count": projected_count,
            "omitted_event_count": len(omissions),
            "cutoff_sequence": cutoff,
        },
        "event_checks": event_checks,
        "event_failures": {
            "duplicate_sequences": duplicate_sequences[:100],
            "missing_sequences": missing_sequences[:100],
            "out_of_boundary_sequences": out_of_boundary[:100],
        },
        "registry": {
            "artifact_count": len(registry),
            "raw_bytes_verified": len(registry) - len(byte_failures),
            "provenance_verified": len(registry) - len(provenance_failures),
            "total_raw_bytes_read": total_bytes,
            "byte_failure_count": len(byte_failures),
            "provenance_failure_count": len(provenance_failures),
            "path_failure_count": len(path_failures),
        },
        "current_attempt": {
            "events": current_attempt_events,
            "event_type_counts": dict(sorted(current_counts.items())),
            "completed_turn_count": current_counts["agent.turn.completed"],
            "team_member_completed_count": current_counts["team.member.completed"],
            "memory_commit_count": current_counts["agent.memory.committed"],
            "artifact_authoritative_count": current_counts["artifact.authoritative"],
            "artifact_authority_frozen_count": current_counts["artifact.authority.frozen"],
        },
        "run_control_event_counts": {
            key: event_types[key]
            for key in (
                "gate.rejected", "judge.verdict.accepted", "gate.passed", "run.converged", "run.completed",
                "agent.memory.committed", "run.paused", "run.resumed", "run.interrupted", "run.recovered",
                "artifact.superseded", "artifact.authoritative", "artifact.authority.frozen",
            )
        },
        "authority_events": authority_events,
        "privacy_boundary": "Only public_agent_safe event objects and omission metadata were read. Omitted private payload bodies were neither available nor inferred.",
        "status": "PASS" if all(event_checks.values()) and not byte_failures and not provenance_failures and not path_failures else "FAIL",
    }
    write_json(OUT / "artifact-byte-index.json", {"schema_version": "jianghu.artifact-byte-index.v1", "items": artifact_index})
    write_json(OUT / "platform-evidence-audit.json", result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "event_counts": result["event_counts"],
                "registry": result["registry"],
                "current_attempt": result["current_attempt"],
                "control_counts": result["run_control_event_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
