from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import shutil
import time

from . import NODE_KEY, RUN_ID

HEX64 = re.compile(r"^[0-9a-f]{64}$")
CORE_FILES = (
    "README.md",
    "artifact-registry.json",
    "critical-events.json",
    "events.ndjson",
    "run-lineage.json",
    "run-metadata.json",
    "runtime-attestation.json",
    "runtime-source-attestation.json",
)
TOOL_PHASES = (
    "agent.tool.authorization.decided",
    "agent.tool.started",
    "agent.tool.completed",
    "agent.side_effect.verified",
)
PAUSE_TYPES = {"run.pause_requested", "run.pause.requested", "run.paused", "run.resumed"}
JUDGE_TYPES = {
    "judge.verdict", "judge.verdict.submitted", "gate.rejected", "gate.accepted",
    "revision_request", "revision.requested", "rework.requested", "rejudge.completed",
}
RECOVERY_TYPES = {
    "run.interrupted", "run.recovered", "agent.runtime.recovered",
    "runtime.route.attested", "runtime.fallback.denied", "worker.lease.acquired",
    "worker.fencing.verified", "run.checkpoint.loaded", "worker.duplicate_side_effect.scan",
}


class EvidenceError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON {name}: {exc}") from exc


def load_events(data: bytes) -> list[dict[str, Any]]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"events.ndjson is not UTF-8: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"invalid NDJSON line {number}: {exc}") from exc
        if not isinstance(row, dict):
            raise EvidenceError(f"event line {number} is not an object")
        rows.append(row)
    if not rows:
        raise EvidenceError("platform event projection is empty")
    return rows


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _stable_read(live: Path, attempts: int = 8) -> dict[str, bytes]:
    for name in CORE_FILES:
        _assert((live / name).is_file(), f"missing platform evidence file: {name}")
    for _ in range(attempts):
        first = {name: (live / name).read_bytes() for name in CORE_FILES}
        second = {name: (live / name).read_bytes() for name in CORE_FILES}
        if first == second:
            return first
        time.sleep(0.2)
    raise EvidenceError("platform evidence changed during all capture attempts")


def _safe_artifact(live: Path, raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = live / candidate
    candidate = candidate.resolve()
    allowed = (live / "artifacts").resolve()
    _assert(candidate == allowed or allowed in candidate.parents, f"artifact path escapes platform evidence: {raw}")
    return candidate


def _event_projection_check(events: list[dict[str, Any]], metadata: dict[str, Any], critical: list[Any]) -> dict[str, Any]:
    sequences = [row.get("sequence") for row in events]
    ids = [row.get("event_id") for row in events]
    source_hashes = [row.get("source_event_sha256") for row in events]
    _assert(all(isinstance(value, int) for value in sequences), "event sequence is not integer")
    _assert(sequences == sorted(sequences), "event sequence is not ordered")
    _assert(len(sequences) == len(set(sequences)), "event sequence is not unique")
    _assert(all(isinstance(value, str) and value for value in ids), "event ID missing")
    _assert(len(ids) == len(set(ids)), "event ID is not unique")
    _assert(all(isinstance(value, str) and HEX64.fullmatch(value) for value in source_hashes), "invalid source event SHA-256")
    _assert(len(source_hashes) == len(set(source_hashes)), "source event SHA-256 is not unique")
    _assert(all(row.get("run_id") == RUN_ID for row in events), "foreign Run event in projection")
    _assert(all(row.get("projection") == "public_agent_safe" for row in events), "non-public projection row")
    _assert(metadata.get("id") == RUN_ID, "run metadata belongs to another Run")
    by_id = {row["event_id"]: row for row in events}
    _assert(isinstance(critical, list), "critical-events.json must be a list")
    for row in critical:
        _assert(isinstance(row, dict), "critical event row is not an object")
        _assert(row.get("event_id") in by_id, f"critical event absent from projection: {row.get('event_id')}")
        _assert(by_id[row["event_id"]] == row, f"critical event bytes differ: {row.get('event_id')}")
    missing = sorted(set(range(sequences[0], sequences[-1] + 1)) - set(sequences))
    return {
        "event_count": len(events),
        "metadata_event_count": metadata.get("event_count"),
        "sequence_first": sequences[0],
        "sequence_last": sequences[-1],
        "missing_sequences": missing,
        "event_ids_unique": True,
        "source_event_hashes_unique_and_well_formed": True,
        "critical_count": len(critical),
        "critical_correspondence": "PASS",
        "projection": "public_agent_safe",
        "source_database_verified": False,
    }


def _artifact_check(live: Path, snapshot: Path, registry: list[Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["event_id"]: row for row in events}
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in registry:
        _assert(isinstance(item, dict), "artifact registry row is not an object")
        artifact_id = item.get("id") or item.get("artifact_id")
        _assert(isinstance(artifact_id, str) and artifact_id and artifact_id not in seen, "artifact ID missing or duplicated")
        seen.add(artifact_id)
        raw = item.get("materialized_path")
        _assert(isinstance(raw, str) and raw, f"artifact materialized path missing: {artifact_id}")
        path = _safe_artifact(live, raw)
        _assert(path.is_file(), f"registered artifact bytes missing: {artifact_id}")
        data = path.read_bytes()
        digest = sha256(data)
        _assert(digest == item.get("expected_sha256") == item.get("observed_sha256"), f"artifact digest mismatch: {artifact_id}")
        _assert(len(data) == item.get("size_bytes"), f"artifact size mismatch: {artifact_id}")
        source_id = item.get("source_event_id")
        source_seq = item.get("source_event_sequence")
        source = by_id.get(source_id)
        _assert(source is not None, f"artifact source event absent: {artifact_id}")
        _assert(source.get("sequence") == source_seq, f"artifact source sequence mismatch: {artifact_id}")
        _assert(source.get("source_event_sha256") == item.get("source_event_sha256"), f"artifact source hash mismatch: {artifact_id}")
        _assert((source.get("payload") or {}).get("artifact_id") == artifact_id, f"artifact source payload mismatch: {artifact_id}")
        payload = source.get("payload") or {}
        if payload.get("sha256") is not None:
            _assert(payload.get("sha256") == digest, f"artifact event digest mismatch: {artifact_id}")
            _assert(payload.get("size_bytes") == len(data), f"artifact event size mismatch: {artifact_id}")
        suffix = path.suffix or ".bin"
        target = snapshot / "artifacts" / f"{artifact_id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        receipts.append({
            "artifact_id": artifact_id,
            "registry_path": raw,
            "snapshot_path": target.relative_to(snapshot.parent.parent.parent).as_posix(),
            "source_event_sequence": source_seq,
            "source_event_id": source_id,
            "source_event_sha256": item.get("source_event_sha256"),
            "expected_sha256": item.get("expected_sha256"),
            "observed_sha256": digest,
            "size_bytes": len(data),
            "node_key": item.get("source_node_key"),
            "status": "PASS_BYTES_AND_SOURCE_EVENT",
        })
    return receipts


def _tool_analysis(events: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in events:
        if row.get("type") in TOOL_PHASES:
            call_id = (row.get("payload") or {}).get("tool_call_id")
            _assert(isinstance(call_id, str) and call_id, f"tool event lacks tool_call_id at sequence {row.get('sequence')}")
            groups[call_id][row["type"]].append(row)
    complete = 0
    incomplete: list[str] = []
    completion_statuses: Counter[str] = Counter()
    side_effect_statuses: Counter[str] = Counter()
    authorization: Counter[str] = Counter()
    tool_names: Counter[str] = Counter()
    node_groups = 0
    linkage = Counter({"sdk_session_id": 0, "invocation_id": 0, "result_digest": 0, "output_sha256": 0})
    failed_receipts: list[dict[str, Any]] = []
    for call_id, phases in groups.items():
        if all(len(phases.get(name, [])) == 1 for name in TOOL_PHASES):
            complete += 1
        else:
            incomplete.append(call_id)
        auth = phases.get(TOOL_PHASES[0], [{}])[0].get("payload", {})
        done = phases.get(TOOL_PHASES[2], [{}])[0].get("payload", {})
        side = phases.get(TOOL_PHASES[3], [{}])[0].get("payload", {})
        authorization[str(auth.get("authorization_decision"))] += 1
        completion_statuses[str(done.get("status"))] += 1
        side_effect_statuses[str(side.get("side_effect_status"))] += 1
        name = done.get("tool_name") or auth.get("tool_name")
        tool_names[str(name)] += 1
        if done.get("node_key") == NODE_KEY:
            node_groups += 1
        for field in linkage:
            if any((candidate.get("payload") or {}).get(field) is not None for rows in phases.values() for candidate in rows):
                linkage[field] += 1
        if done.get("status") != "completed":
            failed_receipts.append({
                "tool_call_id": call_id,
                "tool_name": name,
                "completion_sequence": phases.get(TOOL_PHASES[2], [{}])[0].get("sequence"),
                "completion_event_id": phases.get(TOOL_PHASES[2], [{}])[0].get("event_id"),
                "status": done.get("status"),
                "exit_code": done.get("exit_code"),
                "summary": phases.get(TOOL_PHASES[2], [{}])[0].get("summary"),
                "side_effect_status": side.get("side_effect_status"),
            })
    return {
        "group_count": len(groups),
        "complete_four_phase_groups": complete,
        "incomplete_group_count": len(incomplete),
        "incomplete_tool_call_ids": incomplete,
        "node_group_count": node_groups,
        "authorization_decisions": dict(sorted(authorization.items())),
        "completion_statuses": dict(sorted(completion_statuses.items())),
        "side_effect_statuses": dict(sorted(side_effect_statuses.items())),
        "tool_names": dict(sorted(tool_names.items())),
        "native_result_linkage_group_coverage": dict(linkage),
        "failed_receipts": failed_receipts,
        "raw_tool_request_or_result_bytes_available": False,
    }


def _runtime_analysis(events: list[dict[str, Any]], runtime: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    by_id = {row["event_id"]: row for row in events}
    valid = 0
    bindings = runtime.get("session_bindings") or []
    for binding in bindings:
        row = by_id.get(binding.get("event_id"))
        _assert(row is not None, f"runtime binding event absent: {binding.get('event_id')}")
        _assert(row.get("sequence") == binding.get("event_sequence"), "runtime binding sequence mismatch")
        _assert(row.get("source_event_sha256") == binding.get("source_event_sha256"), "runtime binding source hash mismatch")
        _assert(row.get("type") == "agent.turn.completed", "runtime binding is not a completed turn")
        payload = row.get("payload") or {}
        observed_runtime = payload.get("runtime") or {}
        _assert(observed_runtime.get("session_id") == binding.get("claude_sdk_session_id"), "SDK session ID mismatch")
        _assert(observed_runtime.get("session_key") == binding.get("platform_session_id"), "platform session mismatch")
        valid += 1
    route = [row for row in events if row.get("type") == "runtime.route.attested"]
    fallback = [row for row in events if row.get("type") == "runtime.fallback.denied"]
    started = [row for row in events if row.get("type") == "agent.turn.started"]
    completed = [row for row in events if row.get("type") == "agent.turn.completed"]
    return {
        "health": runtime.get("runtime_health"),
        "source_attestation_status": source.get("status"),
        "source_checks": source.get("checks"),
        "source_file_fingerprint_count": len(source.get("files") or []),
        "route_events": [{"sequence": r["sequence"], "event_id": r["event_id"], "payload": r.get("payload")} for r in route],
        "fallback_denial_events": [{"sequence": r["sequence"], "event_id": r["event_id"], "payload": r.get("payload")} for r in fallback],
        "turn_started_count": len(started),
        "turn_completed_count": len(completed),
        "binding_count": len(bindings),
        "binding_verified_count": valid,
        "distinct_bound_agents": len({b.get("agent_id") for b in bindings}),
        "distinct_sdk_sessions": len({b.get("claude_sdk_session_id") for b in bindings}),
        "bindings": bindings,
        "explicit_sdk_session_started_event_count": sum(1 for r in events if r.get("type") == "sdk.session.started"),
        "sdk_session_continued_event_count": sum(1 for r in events if r.get("type") == "sdk.session.continued"),
        "boundary": "attested binding to agent.turn.completed; model field is not treated as proof of model-provider identity",
    }


def _memory_analysis(events: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(row.get("type") for row in events)
    committed = [row for row in events if row.get("type") == "agent.memory.committed"]
    retrieved = [row for row in events if row.get("type") == "agent.memory.retrieved"]
    used = [row for row in events if row.get("type") == "agent.memory.used"]
    roundtrips: list[dict[str, Any]] = []
    for commit in committed:
        cp = commit.get("payload") or {}
        later_reads = [r for r in retrieved if r["sequence"] > commit["sequence"] and (r.get("payload") or {}).get("memory_id") == cp.get("memory_id") and (r.get("payload") or {}).get("value_sha256") == cp.get("value_sha256")]
        for read in later_reads:
            rp = read.get("payload") or {}
            later_uses = [u for u in used if u["sequence"] > read["sequence"] and (u.get("payload") or {}).get("memory_id") == cp.get("memory_id") and (u.get("payload") or {}).get("reader_session_id") == rp.get("reader_session_id")]
            if later_uses:
                roundtrips.append({
                    "memory_id": cp.get("memory_id"),
                    "commit_sequence": commit["sequence"],
                    "retrieve_sequence": read["sequence"],
                    "use_sequence": later_uses[0]["sequence"],
                    "writer_platform_session_id": cp.get("writer_session_id") or cp.get("platform_session_id"),
                    "reader_platform_session_id": rp.get("reader_session_id"),
                })
    return {
        "candidate_count": types["agent.memory.candidate"],
        "reviewed_count": types["agent.memory.reviewed"],
        "committed_count": types["agent.memory.committed"],
        "persisted_count": types["agent.memory.persisted"],
        "retrieved_count": len(retrieved),
        "used_count": len(used),
        "commit_anchors": [{"sequence": r["sequence"], "event_id": r["event_id"], "memory_id": (r.get("payload") or {}).get("memory_id")} for r in committed],
        "later_commit_retrieve_use_roundtrips": roundtrips,
        "cross_session_roundtrip_proven": any(x["writer_platform_session_id"] and x["reader_platform_session_id"] and x["writer_platform_session_id"] != x["reader_platform_session_id"] for x in roundtrips),
    }


def _controls(index: dict[str, Any]) -> list[dict[str, Any]]:
    a = index["analysis"]
    checks = [
        ("CAM-00", "OpenClaw capability baseline and retirement evidence", "NOT_PASS", "Mapping artifact exists, but parity, zero traffic, no bypass, single writer and rollback are not proven."),
        ("CAM-01", "Claude Agent SDK runtime identity and session lifecycle", "PARTIAL", f"{a['runtime']['binding_verified_count']} completed-turn bindings verified; explicit SDK session start/continue lifecycle is incomplete."),
        ("CAM-02", "Five distinct production roles", "NOT_PASS", f"{a['runtime']['distinct_bound_agents']} distinct bound agents are visible, but they are not bound to the five required named roles; role-to-session proof is absent."),
        ("CAM-03", "Tool request, authorization, result and side effect", "PARTIAL", f"{a['tools']['complete_four_phase_groups']}/{a['tools']['group_count']} projected groups have four platform phases; raw request/result bytes, independent schema denial and result digests are absent."),
        ("CAM-04", "File delivery and Artifact Registry", "PARTIAL", f"{a['artifacts']['byte_verified_count']}/{a['artifacts']['registry_count']} registered bytes verify; full collect/download lifecycle covers {a['artifacts']['download_verified_count']} artifacts, not every artifact."),
        ("CAM-05", "Typed public collaboration", "PARTIAL", f"{a['collaboration']['message_count']} public messages across {a['collaboration']['distinct_actor_count']} actors are visible, not a five-role production flow."),
        ("CAM-06", "Independent Judge rejection and re-judgment", "NOT_PASS", f"Projected Judge/gate event count is {a['judge']['event_count']}."),
        ("CAM-07", "Immutable rework attempt causality", "PARTIAL", f"{a['rework']['linked_attempt_count']} attempt.created event has rework_of, but no independent Judge causation is visible."),
        ("CAM-08", "Memory write, commit, new-session read and use", "PARTIAL", f"Committed={a['memory']['committed_count']}; later cross-session commit→retrieve→use proven={a['memory']['cross_session_roundtrip_proven']}."),
        ("CAM-09", "Intentional platform pause and resume", "NOT_PASS", f"Intentional pause/resume event count is {a['pause']['event_count']}."),
        ("CAM-10", "Failure recovery and exactly-once reconciliation", "PARTIAL", "Platform interruption/recovery chain exists, but terminal duplicate-side-effect reconciliation and convergence are absent."),
        ("CAM-11", "Terminal Run reconciliation", "NOT_PASS", f"Frozen Run status is {index['snapshot']['run_metadata']['status']}."),
        ("CAM-12", "OpenClaw retirement", "NOT_PASS", "No complete entrypoint inventory, zero-traffic window, no silent fallback and retirement rollback evidence."),
    ]
    return [{"control_id": cid, "name": name, "status": status, "basis": basis} for cid, name, status, basis in checks]


def analyze(snapshot: Path) -> dict[str, Any]:
    core = {name: (snapshot / name).read_bytes() for name in CORE_FILES}
    events = load_events(core["events.ndjson"])
    metadata = load_json(core["run-metadata.json"], "run-metadata.json")
    runtime = load_json(core["runtime-attestation.json"], "runtime-attestation.json")
    source = load_json(core["runtime-source-attestation.json"], "runtime-source-attestation.json")
    registry = load_json(core["artifact-registry.json"], "artifact-registry.json")
    critical = load_json(core["critical-events.json"], "critical-events.json")
    _assert(isinstance(registry, list), "artifact registry is not a list")
    projection = _event_projection_check(events, metadata, critical)
    tool = _tool_analysis(events)
    runtime_result = _runtime_analysis(events, runtime, source)
    counts = Counter(row.get("type") for row in events)
    messages = [row for row in events if row.get("type") == "agent.message.sent"]
    attempts = [row for row in events if row.get("type") == "attempt.created"]
    judge = [row for row in events if row.get("type") in JUDGE_TYPES or "judge" in str(row.get("type"))]
    pauses = [row for row in events if row.get("type") in PAUSE_TYPES]
    recovery = [row for row in events if row.get("type") in RECOVERY_TYPES and 2519 <= row.get("sequence", 0) <= 2527]
    artifact_created = [row for row in events if row.get("type") == "artifact.created"]
    collected = [row for row in events if row.get("type") == "artifact.collected"]
    downloaded = [row for row in events if row.get("type") == "artifact.download.verified"]
    index = {
        "schema_version": "jianghu.runtime-probe-evidence-index.v1",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_boundary": "Frozen public_agent_safe projection and registered raw artifact bytes; not source DB or initiator-private audit data.",
        "snapshot": {
            "core_files": {name: {"size_bytes": len(data), "sha256": sha256(data)} for name, data in core.items()},
            "projection": projection,
            "run_metadata": metadata,
        },
        "analysis": {
            "runtime": runtime_result,
            "tools": tool,
            "files": {"created": counts["agent.file.created"], "modified": counts["agent.file.modified"], "deleted": counts["agent.file.deleted"]},
            "artifacts": {
                "registry_count": len(registry),
                "byte_verified_count": len(registry),
                "created_count": len(artifact_created),
                "collected_count": len(collected),
                "download_verified_count": len(downloaded),
                "registry_sha256": sha256(core["artifact-registry.json"]),
            },
            "collaboration": {
                "message_count": len(messages),
                "distinct_actor_count": len({(r.get("payload") or {}).get("from_agent_id") for r in messages}),
                "rounds": dict(sorted(Counter(str((r.get("payload") or {}).get("round")) for r in messages).items())),
                "anchors": [{"sequence": r["sequence"], "event_id": r["event_id"], "from_agent_id": (r.get("payload") or {}).get("from_agent_id"), "to_agent_id": (r.get("payload") or {}).get("to_agent_id"), "message_type": (r.get("payload") or {}).get("message_type")} for r in messages],
            },
            "judge": {"event_count": len(judge), "anchors": [{"sequence": r["sequence"], "event_id": r["event_id"], "type": r["type"]} for r in judge]},
            "rework": {
                "attempt_count": len(attempts),
                "linked_attempt_count": sum(1 for r in attempts if (r.get("payload") or {}).get("rework_of")),
                "anchors": [{"sequence": r["sequence"], "event_id": r["event_id"], "platform_attempt_id": (r.get("payload") or {}).get("platform_attempt_id"), "rework_of": (r.get("payload") or {}).get("rework_of")} for r in attempts],
            },
            "memory": _memory_analysis(events),
            "pause": {"event_count": len(pauses), "anchors": [{"sequence": r["sequence"], "event_id": r["event_id"], "type": r["type"]} for r in pauses]},
            "recovery": {
                "chain": [{"sequence": r["sequence"], "event_id": r["event_id"], "type": r["type"], "payload": r.get("payload")} for r in recovery],
                "terminal_duplicate_effect_reconciliation": any(r.get("type") in {"worker.duplicate_side_effect.reconciled", "run.converged", "run.completed"} for r in events),
                "run_converged_or_completed": any(r.get("type") in {"run.converged", "run.completed"} for r in events),
            },
        },
    }
    index["controls"] = _controls(index)
    index["acceptance"] = {
        "pass_count": sum(1 for c in index["controls"] if c["status"] == "PASS"),
        "partial_count": sum(1 for c in index["controls"] if c["status"] == "PARTIAL"),
        "not_pass_count": sum(1 for c in index["controls"] if c["status"] == "NOT_PASS"),
        "claude_agent_sdk_full_runtime_migration": "NO_GO",
        "openclaw_retirement": "REJECTED",
    }
    return index


def capture(root: Path) -> dict[str, Any]:
    live = root / ".jianghu-platform-evidence"
    snapshot = root / "evidence" / "runtime_probe" / "platform_snapshot"
    captured = _stable_read(live)
    events = load_events(captured["events.ndjson"])
    metadata = load_json(captured["run-metadata.json"], "run-metadata.json")
    critical = load_json(captured["critical-events.json"], "critical-events.json")
    registry = load_json(captured["artifact-registry.json"], "artifact-registry.json")
    _assert(isinstance(registry, list), "artifact registry must be a list")
    _event_projection_check(events, metadata, critical)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.mkdir(parents=True)
    for name, data in captured.items():
        (snapshot / name).write_bytes(data)
    receipts = _artifact_check(live, snapshot, registry, events)
    (snapshot / "artifact-byte-receipts.json").write_text(json.dumps(receipts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index = analyze(snapshot)
    index["analysis"]["artifacts"]["receipts"] = receipts
    index_path = root / "evidence" / "runtime_probe" / "evidence-index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = index["analysis"]["tools"].pop("failed_receipts")
    failed_path = root / "evidence" / "runtime_probe" / "failed-tool-inventory.json"
    failed_path.write_text(json.dumps({"run_id": RUN_ID, "count": len(failed), "limitations": "Summary and exit_code only; raw Tool Result and side-effect causality are not in the public projection.", "items": failed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def load_index(root: Path) -> dict[str, Any]:
    path = root / "evidence" / "runtime_probe" / "evidence-index.json"
    _assert(path.is_file(), "evidence index missing; run build first")
    return json.loads(path.read_text(encoding="utf-8"))
