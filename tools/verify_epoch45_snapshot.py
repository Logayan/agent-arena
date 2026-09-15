#!/usr/bin/env python3
"""Verify the platform-supplied epoch45 public snapshot without private payload access."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / "attempt-ef6476c5bf4ad3e8"
OUTPUT = ROOT / "evidence" / "epoch45-final-remediation" / "snapshot-verification.json"


def digest(path: Path) -> dict[str, Any]:
    value = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            value.update(chunk)
    return {"size_bytes": size, "sha256": value.hexdigest()}


def main() -> int:
    metadata = json.loads((SNAPSHOT / "run-metadata.json").read_text(encoding="utf-8"))
    omissions = json.loads((SNAPSHOT / "projection-omissions.json").read_text(encoding="utf-8"))
    cutoff = int(metadata["cutoff_sequence"])
    seen = bytearray(cutoff + 1)
    event_ids: set[str] = set()
    event_types: Counter[str] = Counter()
    public_count = 0
    duplicate_sequences: list[int] = []
    out_of_boundary: list[int] = []
    tail_events: list[dict[str, Any]] = []
    with (SNAPSHOT / "events.ndjson").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            event = json.loads(line)
            sequence = int(event["sequence"])
            event_id = str(event.get("id") or event.get("event_id") or "")
            public_count += 1
            event_types[str(event.get("type") or "")] += 1
            if sequence >= max(1, cutoff - 10):
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                tail_events.append({
                    "sequence": sequence,
                    "event_id": event_id,
                    "type": str(event.get("type") or ""),
                    "platform_attempt_id": payload.get("platform_attempt_id"),
                    "rework_of": payload.get("rework_of"),
                    "causation_event_id": payload.get("causation_event_id"),
                    "supersedes": payload.get("supersedes"),
                })
            if not (1 <= sequence <= cutoff):
                out_of_boundary.append(sequence)
            elif seen[sequence]:
                duplicate_sequences.append(sequence)
            else:
                seen[sequence] = 1
            if event_id in event_ids:
                raise RuntimeError(f"duplicate_event_id:{event_id}")
            event_ids.add(event_id)
    omission_rows = omissions.get("omissions", [])
    omission_sequences: list[int] = []
    for item in omission_rows:
        sequence = int(item["sequence"])
        omission_sequences.append(sequence)
        if not (1 <= sequence <= cutoff):
            out_of_boundary.append(sequence)
        elif seen[sequence]:
            duplicate_sequences.append(sequence)
        else:
            seen[sequence] = 1
    missing_sequences = [sequence for sequence in range(1, cutoff + 1) if not seen[sequence]]
    source_count = public_count + len(omission_rows)
    checks = {
        "metadata_event_count_equals_source": int(metadata["event_count"]) == source_count,
        "metadata_source_event_count_equals_source": int(metadata["source_event_count"]) == source_count,
        "metadata_public_event_count_equals_projection": int(metadata["public_event_count"]) == public_count,
        "metadata_omitted_event_count_equals_receipts": int(metadata["omitted_event_count"]) == len(omission_rows),
        "omission_document_count_equals_receipts": int(omissions["omission_count"]) == len(omission_rows),
        "source_count_equals_cutoff": source_count == cutoff,
        "sequence_domain_exact": not duplicate_sequences and not missing_sequences and not out_of_boundary,
        "omissions_positive": len(omission_rows) > 0,
        "pre_judge_accept_absent": event_types["judge.verdict.accepted"] == 0,
        "pre_judge_terminal_events_absent": all(event_types[name] == 0 for name in ("gate.passed", "run.converged", "run.completed")),
    }
    file_names = (
        "run-metadata.json", "run-lineage.json", "runtime-attestation.json",
        "runtime-source-attestation.json", "projection-omissions.json",
        "artifact-registry.json", "events.ndjson", "critical-events.json",
    )
    result = {
        "schema_version": "jianghu.epoch45.platform-snapshot-verification.v1",
        "snapshot": "attempt-ef6476c5bf4ad3e8",
        "run_id": metadata["id"],
        "platform_attempt_id": metadata["platform_attempt_id"],
        "execution_epoch": metadata["execution_epoch"],
        "status": "PASS_PUBLIC_SNAPSHOT_COHERENCE" if all(checks.values()) else "FAIL",
        "boundary_rule": "combined public projection and omission receipt sequence domain equals 1..cutoff_sequence",
        "counts": {
            "event_count": int(metadata["event_count"]),
            "source_event_count": source_count,
            "public_event_count": public_count,
            "omitted_event_count": len(omission_rows),
            "cutoff_sequence": cutoff,
        },
        "checks": checks,
        "duplicate_sequences": duplicate_sequences[:20],
        "missing_sequences": missing_sequences[:20],
        "out_of_boundary_sequences": out_of_boundary[:20],
        "tail_events": tail_events,
        "current_attempt_frozen_state": {
            "platform_attempt_id": metadata["platform_attempt_id"],
            "event_types_at_or_after_attempt_created": dict(Counter(
                item["type"] for item in tail_events
                if item["sequence"] >= next(
                    (candidate["sequence"] for candidate in tail_events if candidate["type"] == "attempt.created" and candidate["platform_attempt_id"] == metadata["platform_attempt_id"]),
                    cutoff + 1,
                )
            )),
        },
        "control_event_counts": {
            name: event_types[name]
            for name in (
                "judge.verdict.accepted", "gate.passed", "gate.rejected",
                "run.converged", "run.completed", "agent.memory.committed",
                "run.paused", "run.resumed", "run.interrupted", "run.recovered",
                "artifact.authoritative", "artifact.authority.frozen",
            )
        },
        "files": {name: digest(SNAPSHOT / name) for name in file_names},
        "privacy_boundary": "Only public_agent_safe rows and omission metadata receipts were read; omitted private payload content was neither available nor inferred.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "counts": result["counts"], "control_event_counts": result["control_event_counts"]}, ensure_ascii=False, indent=2))
    return 0 if result["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
