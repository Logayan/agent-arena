"""Fail-closed verifier for the frozen Jianghu public platform snapshot.

The verifier uses only Python's standard library and files below ``delivery/``.
It deliberately separates current platform facts, platform attestations, local
package checks, design-only contracts, and capabilities not observed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import re

RUN_ID = "run_9226059d74a1"
NODE_KEY = "openclaw_baseline_mapping"
SNAPSHOT_COUNT = 4395
METADATA_EVENT_COUNT = 4403
SEQUENCE_FIRST = 1
SEQUENCE_LAST = 4403
MISSING_SEQUENCES = [687, 812, 1258, 2248, 3898, 3937, 4211, 4329]
EVENTS_SHA256 = "3f9453f269a962240931d57f9bd91820bd3f578353e7300648e9f1d4a937f782"
ARTIFACT_REGISTRY_SHA256 = "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"
SOURCE_ATTESTATION_SHA256 = "015dc05d5ce0550117c8b3b53922970faf368b8d6a3418b79b7fc7c3b3b36f64"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

TOOL_TYPES = {
    "agent.tool.authorization.decided",
    "agent.tool.started",
    "agent.tool.completed",
    "agent.side_effect.verified",
}
MEMORY_WRITE_TYPES = {
    "agent.memory.candidate.created",
    "agent.memory.reviewed",
    "agent.memory.committed",
    "agent.memory.persisted",
    "agent.memory.superseded",
    "agent.memory.tombstoned",
    "memory.candidate.created",
    "memory.reviewed",
    "memory.committed",
    "memory.persisted",
    "memory.superseded",
    "memory.tombstoned",
}
JUDGE_TYPES = {
    "judge.verdict",
    "gate.rejected",
    "revision_request",
    "revision.requested",
    "rework.requested",
    "rejudge.completed",
}
PAUSE_RESUME_TYPES = {
    "run.pause.requested",
    "run.pause_requested",
    "run.paused",
    "run.resumed",
}
CONTINUATION_TYPES = {"sdk.session.continued"}
CONVERGENCE_TYPES = {"run.converged", "run.completed"}


class EvidenceError(RuntimeError):
    """Raised whenever evidence is absent, stale, malformed, or inconsistent."""


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read valid JSON: {path}: {exc}") from exc


def _read_events(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"cannot read events: {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"invalid NDJSON at line {line_number}: {exc}") from exc
        _assert(isinstance(value, dict), f"event line {line_number} is not an object")
        rows.append(value)
    return rows, raw


def _events_by_sequence(events: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row["sequence"]): row for row in events}


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload") or {}
    _assert(isinstance(value, dict), f"event payload is not an object: {event.get('event_id')}")
    return value


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(event)
    return {
        "sequence": event["sequence"],
        "event_id": event["event_id"],
        "type": event["type"],
        "source_event_sha256": event["source_event_sha256"],
        "agent_id": payload.get("agent_id") or event.get("agent_id"),
        "node_key": payload.get("node_key") or event.get("node_key"),
    }


def verify_projection(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = root / "evidence" / "platform_snapshot"
    index = _read_json(root / "evidence" / "platform_snapshot_index.json")
    events, raw = _read_events(snapshot / "events.ndjson")
    projection = index.get("projection") or {}

    _assert(index.get("run_id") == RUN_ID, "snapshot index run_id mismatch")
    _assert(index.get("projection_boundary", "").startswith("public_agent_safe"), "projection boundary is not public_agent_safe")
    _assert(len(events) == SNAPSHOT_COUNT, f"event count mismatch: {len(events)}")
    _assert(projection.get("event_count") == SNAPSHOT_COUNT, "snapshot index event_count mismatch")
    _assert(projection.get("metadata_event_count") == METADATA_EVENT_COUNT, "metadata event_count mismatch")
    _assert(_sha256(raw) == EVENTS_SHA256, "events.ndjson digest mismatch")
    _assert(projection.get("events_ndjson_sha256") == EVENTS_SHA256, "index events digest mismatch")

    sequences = [row.get("sequence") for row in events]
    _assert(all(isinstance(value, int) for value in sequences), "non-integer event sequence")
    _assert(sequences == sorted(sequences), "events are not sequence ordered")
    _assert(len(sequences) == len(set(sequences)), "duplicate event sequence")
    _assert(sequences[0] == SEQUENCE_FIRST and sequences[-1] == SEQUENCE_LAST, "sequence range mismatch")
    observed_missing = sorted(set(range(SEQUENCE_FIRST, SEQUENCE_LAST + 1)) - set(sequences))
    _assert(observed_missing == MISSING_SEQUENCES, f"filtered sequence gap mismatch: {observed_missing}")
    _assert(projection.get("missing_sequences") == MISSING_SEQUENCES, "index missing_sequences mismatch")

    event_ids = [row.get("event_id") for row in events]
    _assert(all(isinstance(value, str) and value for value in event_ids), "empty event_id")
    _assert(len(event_ids) == len(set(event_ids)), "duplicate event_id")
    for row in events:
        _assert(row.get("run_id") == RUN_ID, f"event run_id mismatch: {row.get('event_id')}")
        _assert(row.get("projection") == "public_agent_safe", f"projection marker mismatch: {row.get('event_id')}")
        source_hash = row.get("source_event_sha256")
        _assert(isinstance(source_hash, str) and HEX64.fullmatch(source_hash) is not None, f"invalid source hash: {row.get('event_id')}")

    critical = _read_json(snapshot / "critical-events.json")
    _assert(isinstance(critical, list) and len(critical) == 330, "critical event count mismatch")
    by_id = {row["event_id"]: row for row in events}
    for row in critical:
        full = by_id.get(row.get("event_id"))
        _assert(full is not None, f"critical event absent from projection: {row.get('event_id')}")
        for key in ("sequence", "type", "source_event_sha256"):
            _assert(full.get(key) == row.get(key), f"critical correspondence mismatch: {row.get('event_id')} {key}")

    metadata = _read_json(snapshot / "run-metadata.json")
    _assert(metadata.get("id") == RUN_ID, "run metadata id mismatch")
    _assert(metadata.get("event_count") == METADATA_EVENT_COUNT, "run metadata event_count mismatch")
    _assert(metadata.get("version") == 8, "run version mismatch")
    _assert(metadata.get("execution_epoch") == 2, "execution epoch mismatch")
    _assert(metadata.get("status") == "running", "snapshot must remain explicitly non-terminal")
    _assert(metadata.get("artifact_count") == 0, "metadata artifact count mismatch")

    for file_row in index.get("evidence_files", []):
        path = root / file_row["path"]
        _assert(path.is_file(), f"snapshot evidence file missing: {file_row['path']}")
        data = path.read_bytes()
        _assert(len(data) == file_row["size_bytes"], f"snapshot evidence size mismatch: {file_row['path']}")
        _assert(_sha256(data) == file_row["sha256"], f"snapshot evidence digest mismatch: {file_row['path']}")

    return events, {
        "status": "PASS_FROZEN_PUBLIC_PROJECTION",
        "count": len(events),
        "metadata_event_count": metadata["event_count"],
        "sequence_first": sequences[0],
        "sequence_last": sequences[-1],
        "missing_sequences": observed_missing,
        "events_ndjson_sha256": _sha256(raw),
        "critical_count": len(critical),
        "projection_boundary": index["projection_boundary"],
        "source_database_verified": False,
        "run_status_at_snapshot": metadata["status"],
        "execution_epoch": metadata["execution_epoch"],
    }


def verify_runtime(root: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot = root / "evidence" / "platform_snapshot"
    attestation = _read_json(snapshot / "runtime-attestation.json")
    source = _read_json(snapshot / "runtime-source-attestation.json")
    health = attestation.get("runtime_health") or {}

    _assert(health.get("available") is True, "runtime unavailable")
    _assert(health.get("runtime") == "claude_code", "runtime is not claude_code")
    _assert(health.get("mode") == "agent-sdk-bridge", "runtime mode is not agent-sdk-bridge")
    _assert(health.get("version") == "0.3.268", "bridge version mismatch")
    _assert(health.get("claude_code_version") == "2.1.268", "Claude Code version mismatch")
    _assert(health.get("config_ready") is True, "runtime configuration not ready")
    _assert(source.get("status") == "passed", "runtime source attestation did not pass")
    _assert(_sha256((snapshot / "runtime-source-attestation.json").read_bytes()) == SOURCE_ATTESTATION_SHA256, "source attestation digest mismatch")
    checks = source.get("checks") or {}
    _assert(len(checks) == 9 and all(checks.values()), "runtime source checks incomplete")
    _assert(len(source.get("files") or []) == 13, "source fingerprint count mismatch")
    _assert(all(row.get("present") is True and HEX64.fullmatch(row.get("sha256", "")) for row in source["files"]), "source fingerprint invalid")

    by_sequence = _events_by_sequence(events)
    bindings = attestation.get("session_bindings") or []
    _assert(attestation.get("session_binding_count") == 16 and len(bindings) == 16, "SDK binding count mismatch")
    _assert(len({row["claude_sdk_session_id"] for row in bindings}) == 16, "SDK Session IDs are not unique")
    _assert(len({row["platform_session_id"] for row in bindings}) == 16, "platform Session IDs are not unique")
    _assert(len({row["agent_id"] for row in bindings}) == 4, "binding actor count mismatch")

    for binding in bindings:
        event = by_sequence.get(binding["event_sequence"])
        _assert(event is not None, f"binding event missing: {binding['event_sequence']}")
        _assert(event.get("event_id") == binding["event_id"], "binding event_id mismatch")
        _assert(event.get("type") == "agent.turn.completed", "binding source is not agent.turn.completed")
        _assert(event.get("source_event_sha256") == binding["source_event_sha256"], "binding source hash mismatch")
        payload = _payload(event)
        runtime = payload.get("runtime") or {}
        _assert(payload.get("agent_id") == binding["agent_id"], "binding agent mismatch")
        _assert(payload.get("node_key") == binding["node_key"], "binding node mismatch")
        _assert(payload.get("session_key") == binding["platform_session_id"], "binding platform Session mismatch")
        _assert(runtime.get("session_id") == binding["claude_sdk_session_id"], "binding SDK Session mismatch")
        _assert(runtime.get("session_key") == binding["platform_session_key"], "binding runtime session_key mismatch")
        _assert(runtime.get("runtime") == "agent-sdk-bridge", "binding runtime field mismatch")
        _assert(runtime.get("model") == binding["model"], "binding model field mismatch")

    node_bindings = [row for row in bindings if row["node_key"] == NODE_KEY]
    expected_node_sequences = [704, 831, 879, 890, 939, 954, 3926, 4243, 4282, 4292, 4379, 4390]
    _assert([row["event_sequence"] for row in node_bindings] == expected_node_sequences, "node SDK binding sequences mismatch")
    _assert(len(node_bindings) == 12, "node SDK binding count mismatch")
    _assert(len({row["agent_id"] for row in node_bindings}) == 2, "node SDK binding actor count mismatch")

    route_sequences = [row["sequence"] for row in events if row["type"] == "runtime.route.attested"]
    fallback_sequences = [row["sequence"] for row in events if row["type"] == "runtime.fallback.denied"]
    _assert(route_sequences == [4, 2522], "runtime route attestation sequence mismatch")
    _assert(fallback_sequences == [5, 2523], "runtime fallback denial sequence mismatch")
    for sequence in route_sequences:
        payload = _payload(by_sequence[sequence])
        _assert(payload.get("runtime") == "claude_code", "route runtime mismatch")
        _assert(payload.get("runtime_mode") == "agent-sdk-bridge", "route mode mismatch")
        _assert(payload.get("authorization_decision") == "claude_code_only", "route is not Claude-only")
    for sequence in fallback_sequences:
        payload = _payload(by_sequence[sequence])
        _assert(payload.get("authorization_decision") == "deny", "fallback was not denied")
        _assert(payload.get("status") == "passed", "fallback denial status mismatch")

    model_values = sorted({row.get("model") for row in bindings})
    _assert(model_values == ["gpt-5.6-sol"], "unexpected binding model field values")
    explicit_sdk_events = [row for row in events if row["type"].startswith("sdk.session.") or row["type"].startswith("sdk.invocation.")]
    _assert(not explicit_sdk_events, "unexpected explicit SDK Session/Invocation lifecycle events")

    return {
        "status": "PASS_PLATFORM_ROUTE_AND_TURN_BINDINGS",
        "runtime_available": True,
        "runtime": health["runtime"],
        "runtime_mode": health["mode"],
        "bridge_version": health["version"],
        "claude_code_version": health["claude_code_version"],
        "source_attestation": "PASS_PLATFORM_ATTESTATION_RAW_SOURCE_BYTES_UNAVAILABLE",
        "source_check_count": len(checks),
        "source_file_fingerprint_count": len(source["files"]),
        "source_raw_bytes_available": False,
        "route_attestation_sequences": route_sequences,
        "fallback_denial_sequences": fallback_sequences,
        "session_binding_count": len(bindings),
        "distinct_agent_count": len({row["agent_id"] for row in bindings}),
        "distinct_sdk_session_count": len({row["claude_sdk_session_id"] for row in bindings}),
        "node_session_binding_count": len(node_bindings),
        "node_distinct_agent_count": len({row["agent_id"] for row in node_bindings}),
        "node_binding_sequences": expected_node_sequences,
        "binding_model_field_values": model_values,
        "model_field_interpretation": "ATTESTATION_FIELD_ONLY_NOT_END_TO_END_CLAUDE_MODEL_EXECUTION_PROOF",
        "explicit_sdk_session_or_invocation_event_count": 0,
        "bindings": bindings,
        "node_bindings": node_bindings,
        "historical_exclusions": source.get("historical_exclusions") or [],
    }


def _verify_tool_scope(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tool_call_id = _payload(row).get("tool_call_id")
        _assert(isinstance(tool_call_id, str) and tool_call_id, f"{label}: missing tool_call_id")
        groups[tool_call_id].append(row)

    completed_status = Counter()
    side_effect_status = Counter()
    tool_names = Counter()
    authorization = Counter()
    compact_groups: list[dict[str, Any]] = []
    for tool_call_id, group in groups.items():
        type_counts = Counter(row["type"] for row in group)
        _assert(set(type_counts) == TOOL_TYPES, f"{label}: incomplete Tool lifecycle: {tool_call_id}")
        _assert(all(type_counts[name] == 1 for name in TOOL_TYPES), f"{label}: duplicate Tool lifecycle event: {tool_call_id}")
        ordered = sorted(group, key=lambda row: row["sequence"])
        _assert([row["type"] for row in ordered] == [
            "agent.tool.authorization.decided",
            "agent.tool.started",
            "agent.tool.completed",
            "agent.side_effect.verified",
        ], f"{label}: Tool lifecycle order mismatch: {tool_call_id}")
        authorization_event, started_event, completed_event, effect_event = ordered
        payloads = [_payload(row) for row in ordered]
        stable_fields = (
            "tool_call_id",
            "tool_name",
            "agent_id",
            "node_key",
            "platform_attempt_id",
            "platform_session_id",
            "session_key",
        )
        for field in stable_fields:
            values = {payload.get(field) for payload in payloads}
            _assert(len(values) == 1 and None not in values and "" not in values, f"{label}: Tool linkage mismatch {field}: {tool_call_id}")
        auth_payload, _, completed_payload, effect_payload = payloads
        _assert(auth_payload.get("operation_id") == effect_payload.get("operation_id"), f"{label}: operation_id mismatch: {tool_call_id}")
        _assert(auth_payload.get("idempotency_key") == effect_payload.get("idempotency_key"), f"{label}: idempotency_key mismatch: {tool_call_id}")
        _assert(auth_payload.get("authorization_decision") in {"allow", "deny"}, f"{label}: invalid authorization decision: {tool_call_id}")
        _assert(completed_payload.get("status") in {"completed", "failed"}, f"{label}: invalid Tool completion status: {tool_call_id}")
        expected_effect = "completed" if completed_payload["status"] == "completed" else "failed_preserved"
        _assert(effect_payload.get("side_effect_status") == expected_effect, f"{label}: side-effect terminal status mismatch: {tool_call_id}")
        if completed_payload.get("exit_code") is not None:
            _assert(effect_payload.get("exit_code") == completed_payload.get("exit_code"), f"{label}: exit_code mismatch: {tool_call_id}")
        authorization[auth_payload["authorization_decision"]] += 1
        completed_status[completed_payload["status"]] += 1
        side_effect_status[effect_payload["side_effect_status"]] += 1
        tool_names[completed_payload["tool_name"]] += 1
        compact_groups.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": completed_payload["tool_name"],
                "status": completed_payload["status"],
                "side_effect_status": effect_payload["side_effect_status"],
                "authorization_decision": auth_payload["authorization_decision"],
                "operation_id": auth_payload["operation_id"],
                "idempotency_key": auth_payload["idempotency_key"],
                "platform_session_id": completed_payload["platform_session_id"],
                "agent_id": completed_payload["agent_id"],
                "sequences": [row["sequence"] for row in ordered],
                "event_ids": [row["event_id"] for row in ordered],
            }
        )
    compact_groups.sort(key=lambda row: row["sequences"][0])
    return {
        "scope": label,
        "tool_call_group_count": len(groups),
        "authorization_decisions": dict(sorted(authorization.items())),
        "completion_statuses": dict(sorted(completed_status.items())),
        "side_effect_statuses": dict(sorted(side_effect_status.items())),
        "tool_names": dict(sorted(tool_names.items())),
        "platform_session_count": len({row["platform_session_id"] for row in compact_groups}),
        "groups": compact_groups,
    }


def verify_tools(events: list[dict[str, Any]], bindings: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows = [row for row in events if row["type"] in TOOL_TYPES]
    node_rows = [row for row in all_rows if _payload(row).get("node_key") == NODE_KEY]
    run_wide = _verify_tool_scope(all_rows, "run_wide")
    node = _verify_tool_scope(node_rows, "node_scoped")

    _assert(run_wide["tool_call_group_count"] == 785, "Run-wide Tool group count mismatch")
    _assert(run_wide["completion_statuses"] == {"completed": 720, "failed": 65}, "Run-wide Tool status counts mismatch")
    _assert(run_wide["side_effect_statuses"] == {"completed": 720, "failed_preserved": 65}, "Run-wide side-effect counts mismatch")
    _assert(run_wide["tool_names"] == {"Bash": 271, "Edit": 115, "Read": 333, "Write": 66}, "Run-wide Tool names mismatch")
    _assert(run_wide["authorization_decisions"] == {"allow": 785}, "Run-wide authorization counts mismatch")

    _assert(node["tool_call_group_count"] == 371, "node Tool group count mismatch")
    _assert(node["completion_statuses"] == {"completed": 324, "failed": 47}, "node Tool status counts mismatch")
    _assert(node["side_effect_statuses"] == {"completed": 324, "failed_preserved": 47}, "node side-effect counts mismatch")
    _assert(node["tool_names"] == {"Bash": 102, "Edit": 28, "Read": 196, "Write": 45}, "node Tool names mismatch")
    _assert(node["authorization_decisions"] == {"allow": 371}, "node authorization counts mismatch")
    _assert(node["platform_session_count"] == 6, "node Tool platform Session count mismatch")

    bound_sessions = {row["platform_session_id"] for row in bindings}
    bound_group_count = sum(row["platform_session_id"] in bound_sessions for row in node["groups"])
    unbound_group_count = len(node["groups"]) - bound_group_count
    _assert(bound_group_count == 240 and unbound_group_count == 131, "node Tool/SDK binding coverage mismatch")

    linkage_fields = ("sdk_session_id", "invocation_id", "result_digest", "output_sha256")
    linkage_coverage = {
        field: sum(
            any(_payload(event).get(field) for event in group_events)
            for group_events in (
                [event for event in node_rows if _payload(event).get("tool_call_id") == group["tool_call_id"]]
                for group in node["groups"]
            )
        )
        for field in linkage_fields
    }

    return {
        "status": "PASS_PLATFORM_TOOL_LIFECYCLE_WITH_LIMITATIONS",
        "run_wide": run_wide,
        "node_scoped": node,
        "tool_call_group_count": node["tool_call_group_count"],
        "run_wide_tool_call_group_count": run_wide["tool_call_group_count"],
        "bound_to_frozen_sdk_session_count": bound_group_count,
        "unbound_at_snapshot_count": unbound_group_count,
        "native_sdk_linkage_field_coverage": linkage_coverage,
        "authorization_deny_path_observed": False,
        "interpretation": "Complete four-event platform lifecycle is evidenced. Missing native SDK/Invocation/result-digest linkage and an all-allow authorization sample block complete SDK Tool acceptance.",
    }


def _verify_collaboration_cycle(events: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    by_sequence = _events_by_sequence(events)
    for sequence, event_type in spec["expected_types"].items():
        event = by_sequence.get(sequence)
        _assert(event is not None and event.get("type") == event_type, f"collaboration cycle mismatch at sequence {sequence}")
        payload = _payload(event)
        _assert(payload.get("node_key") == NODE_KEY, f"collaboration node mismatch at sequence {sequence}")
    submissions = [by_sequence[value] for value in spec["submission_sequences"]]
    messages = [by_sequence[value] for value in spec["message_sequences"]]
    _assert({(_payload(row).get("agent_id")) for row in submissions} == {"agent_cb495a9bea1e", "agent_bcde21fdede6"}, "collaboration submission actor mismatch")
    _assert(Counter(_payload(row).get("round") for row in messages) == {1: 2, 2: 2}, "collaboration message round mismatch")
    _assert(Counter(_payload(row).get("message_type") for row in messages) == {"challenge": 2, "reply": 2}, "collaboration challenge/reply mismatch")
    directions = Counter((_payload(row).get("from_agent_id"), _payload(row).get("to_agent_id")) for row in messages)
    _assert(directions == {
        ("agent_cb495a9bea1e", "agent_bcde21fdede6"): 2,
        ("agent_bcde21fdede6", "agent_cb495a9bea1e"): 2,
    }, "collaboration direction mismatch")
    return {
        "cycle": spec["name"],
        "submission_events": [_compact_event(row) for row in submissions],
        "round_start_sequences": spec["round_start_sequences"],
        "message_events": [
            {
                **_compact_event(row),
                "round": _payload(row)["round"],
                "message_type": _payload(row)["message_type"],
                "from_agent_id": _payload(row)["from_agent_id"],
                "to_agent_id": _payload(row)["to_agent_id"],
                "content_sha256": _sha256(_payload(row)["content"].encode("utf-8")),
                "content": _payload(row)["content"],
            }
            for row in messages
        ],
        "round_complete_sequences": spec["round_complete_sequences"],
        "synthesis_started_sequence": spec["synthesis_started_sequence"],
        "synthesis_completed": False,
    }


def verify_collaboration(events: list[dict[str, Any]]) -> dict[str, Any]:
    node_events = [row for row in events if _payload(row).get("node_key") == NODE_KEY]
    node_by_sequence = _events_by_sequence(node_events)
    historical_spec = {
        "name": "historical_epoch1_cycle",
        "submission_sequences": [843, 844],
        "round_start_sequences": [845, 903],
        "message_sequences": [900, 901, 964, 965],
        "round_complete_sequences": [902, 966],
        "synthesis_started_sequence": 967,
    }
    current_spec = {
        "name": "current_epoch2_cycle",
        "submission_sequences": [4255, 4256],
        "round_start_sequences": [4257, 4305],
        "message_sequences": [4302, 4303, 4400, 4401],
        "round_complete_sequences": [4304, 4402],
        "synthesis_started_sequence": 4403,
    }
    for spec in (historical_spec, current_spec):
        expected: dict[int, str] = {}
        expected.update({value: "engineering.submission.published" for value in spec["submission_sequences"]})
        expected.update({value: "team.communication.round.started" for value in spec["round_start_sequences"]})
        expected.update({value: "agent.message.sent" for value in spec["message_sequences"]})
        expected.update({value: "team.communication.round.completed" for value in spec["round_complete_sequences"]})
        expected[spec["synthesis_started_sequence"]] = "team.synthesis.started"
        spec["expected_types"] = expected
    historical = _verify_collaboration_cycle(node_events, historical_spec)
    current = _verify_collaboration_cycle(node_events, current_spec)

    all_submissions = [row for row in node_events if row["type"] == "engineering.submission.published"]
    all_messages = [row for row in node_events if row["type"] == "agent.message.sent"]
    all_synthesis_completed = [row for row in node_events if row["type"] == "team.synthesis.completed"]
    _assert([row["sequence"] for row in all_submissions] == [843, 844, 4255, 4256], "unexpected node submission history")
    _assert([row["sequence"] for row in all_messages] == [900, 901, 964, 965, 4302, 4303, 4400, 4401], "unexpected node collaboration messages")
    _assert(not all_synthesis_completed, "unexpected team.synthesis.completed event")
    _assert(node_by_sequence[4403]["event_id"] == "evt_91be130e1a12", "current synthesis event_id mismatch")

    return {
        "status": "PASS_TWO_ACTORS_TWO_ROUNDS_CURRENT_CYCLE_SYNTHESIS_NOT_COMPLETED",
        "historical_cycle": historical,
        "current_cycle": current,
        "submission_count": len(all_submissions),
        "message_count": len(all_messages),
        "messages": historical["message_events"] + current["message_events"],
        "current_messages": current["message_events"],
        "synthesis_completion_status": "BLOCKED_NO_TEAM_SYNTHESIS_COMPLETED_EVENT",
        "interpretation": "Two complete public challenge/reply rounds are evidenced in both cycles; final synthesis completion is not evidenced at the snapshot cutoff.",
    }


def verify_memory(events: list[dict[str, Any]]) -> dict[str, Any]:
    retrievals = [row for row in events if row["type"] == "agent.memory.retrieved"]
    uses = [row for row in events if row["type"] == "agent.memory.used"]
    node_retrievals = [row for row in retrievals if _payload(row).get("node_key") == NODE_KEY]
    node_uses = [row for row in uses if _payload(row).get("node_key") == NODE_KEY]
    write_events = [row for row in events if row["type"] in MEMORY_WRITE_TYPES]

    _assert(len(retrievals) == 168 and len(uses) == 128, "Run-wide Memory read/use counts mismatch")
    _assert(len(node_retrievals) == 104 and len(node_uses) == 96, "node Memory read/use counts mismatch")
    _assert(len({_payload(row).get("memory_id") for row in retrievals}) == 32, "Run-wide Memory ID count mismatch")
    _assert(len({_payload(row).get("memory_id") for row in node_retrievals}) == 16, "node Memory ID count mismatch")
    _assert(not write_events, "unexpected Memory write lifecycle event")

    retrieved_session_keys = {
        (
            _payload(row).get("memory_id"),
            _payload(row).get("reader_session_id"),
            _payload(row).get("value_sha256"),
        )
        for row in retrievals
    }
    retrieved_identity_keys = {
        (
            _payload(row).get("memory_id"),
            _payload(row).get("value_sha256"),
            _payload(row).get("agent_id"),
        )
        for row in retrievals
    }
    for row in uses:
        payload = _payload(row)
        identity_key = (
            payload.get("memory_id"),
            payload.get("value_sha256"),
            payload.get("agent_id"),
        )
        _assert(identity_key in retrieved_identity_keys, f"Memory use lacks matching retrieved identity: {row['event_id']}")
    run_session_match_count = sum(
        (
            _payload(row).get("memory_id"),
            _payload(row).get("reader_session_id"),
            _payload(row).get("value_sha256"),
        )
        in retrieved_session_keys
        for row in uses
    )
    node_retrieved_session_keys = {
        (
            _payload(row).get("memory_id"),
            _payload(row).get("reader_session_id"),
            _payload(row).get("value_sha256"),
        )
        for row in node_retrievals
    }
    node_session_match_count = sum(
        (
            _payload(row).get("memory_id"),
            _payload(row).get("reader_session_id"),
            _payload(row).get("value_sha256"),
        )
        in node_retrieved_session_keys
        for row in node_uses
    )
    _assert(run_session_match_count == 112, "Run-wide same-Session Memory correspondence mismatch")
    _assert(node_session_match_count == 96, "node same-Session Memory correspondence mismatch")

    return {
        "status": "PARTIAL_READ_AND_USE_ONLY_NO_WRITE_ROUNDTRIP",
        "run_wide_retrieval_count": len(retrievals),
        "run_wide_use_count": len(uses),
        "run_wide_distinct_memory_id_count": len({_payload(row).get("memory_id") for row in retrievals}),
        "node_retrieval_count": len(node_retrievals),
        "node_use_count": len(node_uses),
        "node_distinct_memory_id_count": len({_payload(row).get("memory_id") for row in node_retrievals}),
        "run_wide_same_session_use_match_count": run_session_match_count,
        "run_wide_same_session_use_unmatched_in_filtered_projection": len(uses) - run_session_match_count,
        "node_same_session_use_match_count": node_session_match_count,
        "node_same_session_use_unmatched_in_filtered_projection": len(node_uses) - node_session_match_count,
        "write_lifecycle_event_count": 0,
        "later_distinct_session_roundtrip_proven": False,
        "namespace_denial_test_observed": False,
        "supersede_or_tombstone_observed": False,
    }


def verify_artifacts(root: Path) -> dict[str, Any]:
    snapshot = root / "evidence" / "platform_snapshot"
    registry_path = snapshot / "artifact-registry.json"
    raw = registry_path.read_bytes()
    registry = json.loads(raw.decode("utf-8-sig"))
    metadata = _read_json(snapshot / "run-metadata.json")
    _assert(registry == [], "Artifact Registry is not empty")
    _assert(len(raw) == 3, "Artifact Registry byte count mismatch")
    _assert(_sha256(raw) == ARTIFACT_REGISTRY_SHA256, "Artifact Registry digest mismatch")
    _assert(metadata.get("artifact_count") == 0, "metadata Artifact count mismatch")
    return {
        "status": "BLOCKED_NO_CURRENT_RUN_FORMAL_ARTIFACT",
        "registry_count": 0,
        "registry_sha256": _sha256(raw),
        "registry_size_bytes": len(raw),
        "materialized_artifact_count": 0,
        "registry_and_materialized_bytes_reread": True,
        "formal_artifact_lifecycle_proven": False,
        "workspace_file_publication_is_formal_artifact": False,
    }


def verify_submission_review(root: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    review = _read_json(root / "evidence" / "submission_review.json")
    _assert(review.get("schema_version") == "jianghu.submission-review.v3", "submission review schema mismatch")
    basis = review.get("review_basis") or {}
    rows = review.get("reviews") or []
    submissions = review.get("submissions") or []
    _assert(basis.get("manifest_change_row_count") == 58 and len(rows) == 58, "submission review row count mismatch")
    _assert(basis.get("non_deleted_row_count") == 53, "submission non-deleted count mismatch")
    _assert(basis.get("deletion_marker_count") == 5, "submission deletion count mismatch")
    _assert(basis.get("snapshot_sha256") == EVENTS_SHA256, "submission review snapshot mismatch")
    _assert([(row["agent_id"], row["change_row_count"]) for row in submissions] == [
        ("agent_cb495a9bea1e", 31),
        ("agent_bcde21fdede6", 27),
    ], "submission manifest counts mismatch")
    _assert([row["manifest_sha256"] for row in submissions] == [
        "478e89e2f908e8573d301c0d895fb88432329ff528dfb21dcb4405760111aee1",
        "3c98a67dec4388a49d9afd171c2e57145281d47c7b43d5161558a50c87e048c5",
    ], "submission manifest digest mismatch")
    _assert([row["publication_event"]["sequence"] for row in submissions] == [4255, 4256], "submission publication sequence mismatch")

    by_sequence = _events_by_sequence(events)
    review_ids = [row.get("review_id") for row in rows]
    _assert(len(review_ids) == len(set(review_ids)), "duplicate submission review_id")
    for row in rows:
        _assert(row.get("decision") in {
            "adopt",
            "revise",
            "replace",
            "preserve_deletion",
            "reject_duplicate",
            "reject_stale_generated",
            "adopt_concepts_revised",
            "adopt_concepts_reimplemented",
        }, f"invalid merge decision: {row.get('review_id')}")
        _assert(bool(row.get("decision_reason")), f"missing merge decision reason: {row.get('review_id')}")
        event_ref = row.get("platform_file_event") or {}
        event = by_sequence.get(event_ref.get("sequence"))
        _assert(event is not None, f"review platform event absent: {row.get('review_id')}")
        _assert(event.get("event_id") == event_ref.get("event_id"), f"review event_id mismatch: {row.get('review_id')}")
        payload = _payload(event)
        _assert(payload.get("agent_id") == row.get("agent_id"), f"review agent mismatch: {row.get('review_id')}")
        _assert(payload.get("path") == row.get("path"), f"review path mismatch: {row.get('review_id')}")
        _assert(payload.get("action") == row.get("action"), f"review action mismatch: {row.get('review_id')}")
        _assert(payload.get("sha256", "") == row.get("manifest_sha256", ""), f"review digest mismatch: {row.get('review_id')}")
        _assert(payload.get("size_bytes") == row.get("manifest_size_bytes"), f"review size mismatch: {row.get('review_id')}")
        export = row.get("public_export") or {}
        _assert(export.get("status") != "raw_bytes_reread_mismatch", f"raw byte mismatch retained: {row.get('review_id')}")
        if export.get("raw_bytes_available"):
            _assert(export.get("matches_manifest") is True, f"available public bytes do not match: {row.get('review_id')}")

    raw_audit = review.get("raw_byte_audit") or {}
    _assert(raw_audit.get("matched_non_deleted_rows") == 45, "submission raw matched count mismatch")
    _assert(raw_audit.get("non_materialized_non_deleted_rows") == 8, "submission raw missing count mismatch")
    _assert(raw_audit.get("mismatch_rows") == 0, "submission raw mismatch count non-zero")
    _assert(sum(1 for row in rows if row["action"] == "deleted") == 5, "review deletion rows mismatch")

    return {
        "status": "PASS_ALL_LATEST_MANIFEST_ROWS_REVIEWED",
        "file_count": len(rows),
        "manifest_change_row_count": len(rows),
        "non_deleted_row_count": 53,
        "deletion_marker_count": 5,
        "submission_count": len(submissions),
        "submission_manifest_sha256": [row["manifest_sha256"] for row in submissions],
        "decision_counts": review.get("decision_counts") or {},
        "raw_byte_audit": raw_audit,
    }


def verify_mapping_and_gaps(root: Path, snapshot: dict[str, Any], runtime: dict[str, Any], tools: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
    mapping = _read_json(root / "mapping" / "capability_mapping.json")
    gaps = _read_json(root / "gaps" / "migration-gap-list.json")
    _assert(mapping.get("run_id") == RUN_ID and mapping.get("node_key") == NODE_KEY, "mapping identity mismatch")
    observed = mapping.get("observed_snapshot") or {}
    _assert(observed.get("event_projection_count") == snapshot["count"], "mapping event count stale")
    _assert(observed.get("metadata_event_count") == snapshot["metadata_event_count"], "mapping metadata count stale")
    _assert(observed.get("sequence_last") == snapshot["sequence_last"], "mapping sequence cutoff stale")
    _assert(observed.get("events_ndjson_sha256") == snapshot["events_ndjson_sha256"], "mapping digest stale")
    _assert(observed.get("sdk_session_binding_count") == runtime["session_binding_count"], "mapping SDK binding count stale")
    _assert(observed.get("node_tool_call_group_count") == tools["tool_call_group_count"], "mapping node Tool count stale")
    _assert(observed.get("run_wide_tool_call_group_count") == tools["run_wide_tool_call_group_count"], "mapping Run-wide Tool count stale")
    _assert(observed.get("node_memory_retrieval_count") == memory["node_retrieval_count"], "mapping Memory count stale")
    verdict = mapping.get("verdict") or {}
    _assert(verdict.get("complete_migration") == "NOT_PROVEN", "mapping complete migration verdict mismatch")
    _assert(verdict.get("openclaw_retirement") == "NOT_APPROVED", "mapping OpenClaw retirement verdict mismatch")
    _assert(verdict.get("interruption_recovery") == "PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT", "mapping recovery verdict mismatch")

    gap_rows = gaps.get("gaps") or []
    _assert(gaps.get("run_id") == RUN_ID and gaps.get("node_key") == NODE_KEY, "gap list identity mismatch")
    _assert(isinstance(gap_rows, list) and gap_rows, "gap list empty")
    ids = [row.get("id") for row in gap_rows]
    _assert(len(ids) == len(set(ids)), "duplicate gap ID")
    _assert(all(row.get("status") == "open" for row in gap_rows), "closed gap appears without acceptance evidence")
    open_p0 = sum(row.get("priority") == "P0" for row in gap_rows)
    _assert(open_p0 >= 10, "insufficient P0 blocker coverage")
    _assert((gaps.get("observed_counts") or {}).get("event_projection_count") == snapshot["count"], "gap counts stale")
    return {
        "status": "PASS_MAPPING_AND_GAPS_SELF_CONSISTENT",
        "mapping_capability_count": len(mapping.get("capabilities") or []),
        "gap_count": len(gap_rows),
        "open_p0_count": open_p0,
    }


def verify_absent_lifecycles(events: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts = Counter(row["type"] for row in events)
    judge = sum(type_counts[name] for name in JUDGE_TYPES)
    pause_resume = sum(type_counts[name] for name in PAUSE_RESUME_TYPES)
    continuation = sum(type_counts[name] for name in CONTINUATION_TYPES)
    convergence = sum(type_counts[name] for name in CONVERGENCE_TYPES)
    _assert(judge == 0, "unexpected Judge/rework lifecycle")
    _assert(pause_resume == 0, "unexpected intentional pause/resume lifecycle")
    _assert(continuation == 0, "unexpected SDK Session continuation")
    _assert(convergence == 0, "unexpected Run convergence/completion")

    by_sequence = _events_by_sequence(events)
    recovery_spec = [
        (2519, "run.interrupted", "evt_990a82e9307e"),
        (2520, "run.recovered", "evt_cfae787120d6"),
        (2521, "agent.runtime.recovered", "evt_2a24838a3d43"),
        (2522, "runtime.route.attested", "evt_c72cdb538df1"),
        (2523, "runtime.fallback.denied", "evt_722014a4a38e"),
        (2524, "worker.lease.acquired", "evt_645e0a15b9be"),
        (2525, "worker.fencing.verified", "evt_57c3bd34191f"),
        (2526, "run.checkpoint.loaded", "evt_f3eb80c9934b"),
        (2527, "worker.duplicate_side_effect.scan", "evt_8928b43ace1e"),
    ]
    recovery_events: list[dict[str, Any]] = []
    for sequence, event_type, event_id in recovery_spec:
        event = by_sequence.get(sequence)
        _assert(event is not None, f"recovery event missing: {sequence}")
        _assert(event.get("type") == event_type and event.get("event_id") == event_id, f"recovery event mismatch: {sequence}")
        recovery_events.append(_compact_event(event))
    _assert(_payload(by_sequence[2520]).get("execution_epoch") == 2, "recovery epoch mismatch")
    _assert(_payload(by_sequence[2524]).get("status") == "acquired", "lease not acquired")
    _assert(_payload(by_sequence[2525]).get("authorization_decision") == "old_epoch_denied", "fencing status mismatch")
    _assert(_payload(by_sequence[2526]).get("status") == "loaded", "checkpoint not loaded")
    _assert(_payload(by_sequence[2527]).get("status") == "monitoring", "duplicate side-effect scan status mismatch")

    return {
        "judge_reject_rework_rejudge_status": "BLOCKED_NO_EVENTS",
        "judge_related_event_count": judge,
        "intentional_pause_resume_status": "BLOCKED_NO_EVENTS",
        "intentional_pause_resume_event_count": pause_resume,
        "sdk_session_continuation_status": "BLOCKED_NO_EVENT",
        "sdk_session_continuation_event_count": continuation,
        "interruption_recovery_status": "PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT",
        "recovery_chain": recovery_events,
        "terminal_duplicate_effect_reconciliation_observed": False,
        "run_convergence_or_completion_observed": False,
        "run_convergence_event_count": convergence,
    }


def verify_all(root: Path) -> dict[str, Any]:
    root = root.resolve()
    events, snapshot = verify_projection(root)
    runtime = verify_runtime(root, events)
    tools = verify_tools(events, runtime["bindings"])
    collaboration = verify_collaboration(events)
    memory = verify_memory(events)
    artifacts = verify_artifacts(root)
    submission_review = verify_submission_review(root, events)
    absent = verify_absent_lifecycles(events)
    gaps = verify_mapping_and_gaps(root, snapshot, runtime, tools, memory)
    return {
        "schema_version": "jianghu.openclaw-baseline-verification.v3",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "snapshot": snapshot,
        "runtime": runtime,
        "tools": tools,
        "collaboration": collaboration,
        "memory": memory,
        "artifacts": artifacts,
        "submission_review": submission_review,
        "absent_lifecycles": absent,
        "gaps": gaps,
        "node_delivery_status": "CONDITIONAL_PASS_MAPPING_AND_BOUNDARY_DELIVERED",
        "migration_acceptance": "NO_GO_COMPLETE_MIGRATION_NOT_PROVEN",
        "openclaw_retirement": "NOT_APPROVED",
        "evidence_strength_policy": [
            "platform_event_plus_raw_bytes",
            "platform_event",
            "platform_attestation_without_raw_source_bytes",
            "local_only_probe",
            "design_only",
            "not_observed",
        ],
    }


def _json_ready_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a receipt-sized result while retaining detailed audit evidence."""
    data = json.loads(json.dumps(result, ensure_ascii=False))
    # Full 785/371 Tool groups are deterministic but unnecessarily duplicate the
    # 10 MB ledger in generated receipts. Keep aggregate evidence and boundaries.
    data["tools"]["run_wide"].pop("groups", None)
    data["tools"]["node_scoped"].pop("groups", None)
    data["runtime"].pop("bindings", None)
    data["runtime"].pop("node_bindings", None)
    return data


def write_receipts(root: Path) -> dict[str, Any]:
    result = verify_all(root)
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    files = {
        "final_verification.json": _json_ready_result(result),
        "runtime_session_bindings.json": {
            "schema_version": "jianghu.runtime-session-bindings.v2",
            "run_id": RUN_ID,
            "route_attestation_sequences": result["runtime"]["route_attestation_sequences"],
            "model_field_interpretation": result["runtime"]["model_field_interpretation"],
            "session_binding_count": result["runtime"]["session_binding_count"],
            "node_session_binding_count": result["runtime"]["node_session_binding_count"],
            "bindings": result["runtime"]["bindings"],
        },
        "tool_lifecycle_summary.json": {
            "schema_version": "jianghu.tool-lifecycle-summary.v2",
            "run_id": RUN_ID,
            "node_key": NODE_KEY,
            "status": result["tools"]["status"],
            "run_wide": {key: value for key, value in result["tools"]["run_wide"].items() if key != "groups"},
            "node_scoped": {key: value for key, value in result["tools"]["node_scoped"].items() if key != "groups"},
            "bound_to_frozen_sdk_session_count": result["tools"]["bound_to_frozen_sdk_session_count"],
            "unbound_at_snapshot_count": result["tools"]["unbound_at_snapshot_count"],
            "native_sdk_linkage_field_coverage": result["tools"]["native_sdk_linkage_field_coverage"],
            "authorization_deny_path_observed": False,
        },
        "public_collaboration.json": {
            "schema_version": "jianghu.public-collaboration.v2",
            "run_id": RUN_ID,
            "node_key": NODE_KEY,
            "status": result["collaboration"]["status"],
            "historical_cycle": result["collaboration"]["historical_cycle"],
            "current_cycle": result["collaboration"]["current_cycle"],
            "synthesis_completion_status": result["collaboration"]["synthesis_completion_status"],
        },
    }
    for name, data in files.items():
        (evidence / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def _manifest_files(root: Path) -> list[Path]:
    rows: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.as_posix() == "artifacts/sha256_manifest.json":
            continue
        if relative.parts and relative.parts[0] == ".jianghu-platform-evidence":
            continue
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        rows.append(path)
    return sorted(rows, key=lambda value: value.relative_to(root).as_posix())


def write_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    rows = []
    for path in _manifest_files(root):
        raw = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": len(raw),
                "sha256": _sha256(raw),
            }
        )
    manifest = {
        "schema_version": "jianghu.delivery-sha256-manifest.v2",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "coverage_rule": "all regular files below delivery except this manifest, .jianghu-platform-evidence, __pycache__, pyc and pyo",
        "file_count": len(rows),
        "files": rows,
    }
    target = root / "artifacts" / "sha256_manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def check_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = _read_json(root / "artifacts" / "sha256_manifest.json")
    expected = {row["path"]: row for row in manifest.get("files") or []}
    actual_paths = {path.relative_to(root).as_posix(): path for path in _manifest_files(root)}
    _assert(manifest.get("run_id") == RUN_ID, "manifest run_id mismatch")
    _assert(manifest.get("node_key") == NODE_KEY, "manifest node_key mismatch")
    _assert(manifest.get("file_count") == len(expected), "manifest file_count mismatch")
    _assert(set(expected) == set(actual_paths), "manifest path set mismatch")
    for relative, path in actual_paths.items():
        raw = path.read_bytes()
        row = expected[relative]
        _assert(len(raw) == row.get("size_bytes"), f"manifest size mismatch: {relative}")
        _assert(_sha256(raw) == row.get("sha256"), f"manifest digest mismatch: {relative}")
    return {
        "status": "PASS_WHOLE_PACKAGE_MANIFEST",
        "file_count": len(actual_paths),
    }
