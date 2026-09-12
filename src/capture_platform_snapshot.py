#!/usr/bin/env python3
"""Capture and verify an immutable, public-safe platform evidence snapshot.

The live .jianghu-platform-evidence directory can advance while a node runs. This
utility reads it without modifying it, retries if events change mid-capture,
materializes the exact bytes under evidence/platform_snapshot/, and emits a
compact index. It deliberately does not read environment variables or any
provider credential.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".jianghu-platform-evidence"
SNAPSHOT = ROOT / "evidence" / "platform_snapshot"
INDEX = ROOT / "evidence" / "platform_snapshot_index.json"
RUN_ID = "run_9226059d74a1"
REQUIRED = (
    "README.md",
    "artifact-registry.json",
    "critical-events.json",
    "events.ndjson",
    "run-lineage.json",
    "run-metadata.json",
    "runtime-attestation.json",
    "runtime-source-attestation.json",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SnapshotError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_json_bytes(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid JSON in {name}: {exc}") from exc


def parse_events(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SnapshotError(f"events.ndjson is not UTF-8: {exc}") from exc
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"invalid NDJSON at line {number}: {exc}") from exc
        if not isinstance(row, dict):
            raise SnapshotError(f"event line {number} is not an object")
        rows.append(row)
    if not rows:
        raise SnapshotError("event projection is empty")
    return rows


def safe_materialized_path(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = LIVE / candidate
    candidate = candidate.resolve()
    allowed = (LIVE / "artifacts").resolve()
    if candidate != allowed and allowed not in candidate.parents:
        raise SnapshotError(f"artifact path escapes platform artifacts/: {raw}")
    return candidate


def expected_digest(row: dict[str, Any]) -> str:
    for key in ("sha256", "expected_sha256", "registered_sha256", "registry_sha256", "content_sha256", "digest"):
        value = row.get(key)
        if isinstance(value, str) and HEX64.fullmatch(value.lower()):
            return value.lower()
    raise SnapshotError("artifact registry row lacks SHA-256")


def expected_size(row: dict[str, Any]) -> int | None:
    for key in ("size_bytes", "bytes", "expected_size_bytes"):
        value = row.get(key)
        if isinstance(value, int):
            return value
    return None


def ranges(values: list[int]) -> list[list[int]]:
    if not values:
        return []
    out: list[list[int]] = []
    start = previous = values[0]
    for value in values[1:]:
        if value != previous + 1:
            out.append([start, previous])
            start = value
        previous = value
    out.append([start, previous])
    return out


def lifecycle_coverage(types: Counter[str]) -> dict[str, Any]:
    names = set(types)
    def contains(*tokens: str) -> bool:
        return any(all(token in name for token in tokens) for name in names)
    return {
        "sdk_session_or_invocation_event_observed": contains("sdk", "session") or contains("sdk", "invocation"),
        "tool_lifecycle_event_observed": any("tool" in name for name in names),
        "artifact_event_observed": any("artifact" in name for name in names),
        "public_collaboration_event_observed": bool(names & {"agent.message.sent", "team.communication.round.started", "team.communication.round.completed"}) or any("collaboration" in name for name in names),
        "judge_event_observed": any("judge" in name or "verdict" in name for name in names),
        "rework_event_observed": any("rework" in name or "revision" in name or "gate.rejected" in name for name in names),
        "memory_retrieval_count": sum(count for name, count in types.items() if "memory" in name and "retriev" in name),
        "memory_write_event_observed": any("memory" in name and any(token in name for token in ("candidate", "review", "commit", "persist", "write", "tombstone", "supersed")) for name in names),
        "intentional_pause_resume_event_observed": bool(names & {"run.pause.requested", "run.paused", "run.resumed"}),
        "interruption_recovery_event_observed": bool(names & {"run.interrupted", "run.recovered", "agent.runtime.recovered", "worker.lease.acquired", "worker.fencing.verified", "run.checkpoint.loaded"}),
    }


def capture(max_attempts: int = 8, delay_seconds: float = 0.25) -> dict[str, Any]:
    for name in REQUIRED:
        if not (LIVE / name).is_file():
            raise SnapshotError(f"missing platform evidence: {name}")

    captured: dict[str, bytes] | None = None
    for _ in range(max_attempts):
        before = (LIVE / "events.ndjson").read_bytes()
        candidate = {name: (LIVE / name).read_bytes() for name in REQUIRED}
        after = (LIVE / "events.ndjson").read_bytes()
        if before == after == candidate["events.ndjson"]:
            captured = candidate
            break
        time.sleep(delay_seconds)
    if captured is None:
        raise SnapshotError("events.ndjson changed during every capture attempt")

    metadata = parse_json_bytes(captured["run-metadata.json"], "run-metadata.json")
    runtime = parse_json_bytes(captured["runtime-attestation.json"], "runtime-attestation.json")
    source = parse_json_bytes(captured["runtime-source-attestation.json"], "runtime-source-attestation.json")
    lineage = parse_json_bytes(captured["run-lineage.json"], "run-lineage.json")
    registry = parse_json_bytes(captured["artifact-registry.json"], "artifact-registry.json")
    critical = parse_json_bytes(captured["critical-events.json"], "critical-events.json")
    events = parse_events(captured["events.ndjson"])

    if metadata.get("id") != RUN_ID:
        raise SnapshotError("run-metadata belongs to another Run")
    if not isinstance(registry, list):
        raise SnapshotError("artifact-registry.json must be a list")
    if not isinstance(critical, list):
        raise SnapshotError("critical-events.json must be a list")

    sequences = [row.get("sequence") for row in events]
    if not all(isinstance(value, int) for value in sequences):
        raise SnapshotError("event sequence must be integer")
    if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
        raise SnapshotError("event sequence must be ordered and unique")
    ids = [row.get("event_id") for row in events]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise SnapshotError("event IDs must be present and unique")
    for row in events:
        if row.get("run_id") != RUN_ID:
            raise SnapshotError("foreign Run event in projection")
        if row.get("projection") != "public_agent_safe":
            raise SnapshotError("non-public event in public evidence projection")
        if not HEX64.fullmatch(str(row.get("source_event_sha256", ""))):
            raise SnapshotError("malformed source_event_sha256")

    by_id = {row["event_id"]: row for row in events}
    missing_critical: list[str] = []
    mismatched_critical: list[str] = []
    for row in critical:
        event_id = row.get("event_id")
        if event_id not in by_id:
            missing_critical.append(str(event_id))
        elif by_id[event_id] != row:
            mismatched_critical.append(str(event_id))
    if missing_critical or mismatched_critical:
        raise SnapshotError(f"critical projection mismatch: missing={missing_critical}, different={mismatched_critical}")

    artifact_bytes: list[tuple[str, bytes]] = []
    artifact_receipts: list[dict[str, Any]] = []
    for row in registry:
        if not isinstance(row, dict):
            raise SnapshotError("artifact registry row is not an object")
        raw = row.get("materialized_path") or row.get("snapshot_path") or row.get("path") or row.get("file_path")
        if not isinstance(raw, str) or not raw:
            raise SnapshotError("artifact registry row lacks materialized path")
        source_path = safe_materialized_path(raw)
        if not source_path.is_file():
            raise SnapshotError(f"registered artifact missing: {raw}")
        data = source_path.read_bytes()
        observed = sha256_bytes(data)
        expected = expected_digest(row)
        if observed != expected:
            raise SnapshotError(f"artifact digest mismatch: {raw}")
        size = expected_size(row)
        if size is not None and size != len(data):
            raise SnapshotError(f"artifact size mismatch: {raw}")
        artifact_id = str(row.get("artifact_id") or row.get("id") or "missing-id")
        target_name = f"{artifact_id}__{source_path.name}"
        artifact_bytes.append((target_name, data))
        artifact_receipts.append({
            "artifact_id": artifact_id,
            "source_registry_path": raw,
            "snapshot_path": f"evidence/platform_snapshot/artifacts/{target_name}",
            "expected_sha256": expected,
            "observed_sha256": observed,
            "size_bytes": len(data),
            "status": "MATCH",
        })

    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    SNAPSHOT.mkdir(parents=True)
    for name, data in captured.items():
        target = SNAPSHOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name, data in artifact_bytes:
        target = SNAPSHOT / "artifacts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    type_counts = Counter(str(row.get("type")) for row in events)
    key_types = {
        "run.retry_created", "run.started", "agent.runtime.ready",
        "runtime.route.attested", "runtime.fallback.denied", "attempt.created",
        "task.started", "agent.turn.started", "agent.turn.completed",
        "sdk.session.bound", "sdk.invocation.started", "sdk.invocation.completed",
        "collaboration.message.published", "collaboration.message.received",
        "judge.verdict", "gate.rejected", "attempt.rework_created",
        "memory.candidate.created", "memory.committed", "memory.used",
        "run.pause.requested", "run.paused", "run.resumed", "run.recovered",
        "artifact.registered", "artifact.materialized", "artifact.downloaded",
    }
    key_events = [
        {
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "type": row["type"],
            "agent_id": (row.get("payload") or {}).get("agent_id"),
            "node_key": (row.get("payload") or {}).get("node_key"),
            "source_event_sha256": row["source_event_sha256"],
        }
        for row in events if row.get("type") in key_types
    ]
    sequence_missing = sorted(set(range(sequences[0], sequences[-1] + 1)) - set(sequences))
    runtime_health = runtime.get("runtime_health", {})
    source_files = source.get("files", [])
    raw_source_available = any((SNAPSHOT / str(item.get("path", ""))).is_file() for item in source_files if isinstance(item, dict))

    evidence_files = []
    for path in sorted(SNAPSHOT.rglob("*")):
        if path.is_file():
            evidence_files.append({
                "path": path.relative_to(ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_bytes(path.read_bytes()),
            })

    result = {
        "schema_version": "jianghu.platform-snapshot-index.v2",
        "run_id": RUN_ID,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "platform_metadata_generated_at": metadata.get("generated_at"),
        "projection_boundary": "public_agent_safe; filtered projection, not source database export",
        "projection": {
            "event_count": len(events),
            "metadata_event_count": metadata.get("event_count"),
            "metadata_count_semantics": "platform metadata total may exceed public projection count when private events are filtered",
            "sequence_first": sequences[0],
            "sequence_last": sequences[-1],
            "sequence_ordered": True,
            "sequence_unique": True,
            "sequence_contiguous": not sequence_missing,
            "missing_sequences": sequence_missing,
            "contiguous_ranges": ranges(sequences),
            "event_ids_unique": True,
            "source_hash_format_valid": True,
            "events_ndjson_sha256": sha256_bytes(captured["events.ndjson"]),
            "event_type_counts": dict(sorted(type_counts.items())),
            "key_events": key_events,
            "critical_count": len(critical),
            "critical_correspondence": "PASS",
            "source_database_verified": False,
        },
        "runtime": {
            "available": runtime_health.get("available"),
            "runtime": runtime_health.get("runtime"),
            "mode": runtime_health.get("mode"),
            "version": runtime_health.get("version"),
            "claude_code_version": runtime_health.get("claude_code_version"),
            "config_ready": runtime_health.get("config_ready"),
            "session_binding_count": runtime.get("session_binding_count"),
            "distinct_agent_count": runtime.get("distinct_agent_count"),
            "distinct_sdk_session_count": runtime.get("distinct_sdk_session_count"),
            "source_attestation_status": source.get("status"),
            "source_checks": source.get("checks"),
            "source_file_count": len(source_files) if isinstance(source_files, list) else None,
            "source_file_raw_bytes_available_in_platform_snapshot": raw_source_available,
            "source_attestation_sha256": sha256_bytes(captured["runtime-source-attestation.json"]),
            "historical_exclusions": source.get("historical_exclusions"),
        },
        "artifacts": {
            "registry_count": len(registry),
            "registry_sha256": sha256_bytes(captured["artifact-registry.json"]),
            "materialized_count": len(artifact_receipts),
            "status": "MATCH" if registry else "NO_CURRENT_RUN_ARTIFACTS",
            "receipts": artifact_receipts,
        },
        "coverage": lifecycle_coverage(type_counts),
        "lineage": lineage,
        "evidence_files": evidence_files,
    }
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    result = capture()
    print(
        "SNAPSHOT_CAPTURED "
        f"events={result['projection']['event_count']} "
        f"sequence={result['projection']['sequence_first']}..{result['projection']['sequence_last']} "
        f"missing={len(result['projection']['missing_sequences'])} "
        f"artifacts={result['artifacts']['registry_count']} "
        f"sdk_bindings={result['runtime']['session_binding_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
