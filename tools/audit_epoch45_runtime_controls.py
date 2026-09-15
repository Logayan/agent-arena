#!/usr/bin/env python3
"""Audit Memory, pause/resume, recovery, routing and rework controls from one frozen public snapshot.

The auditor reads only public_agent_safe events plus omission metadata and Registry
metadata. It never reads omitted payloads, Provider credentials, or private Memory
content. Values retained below are event identities and control digests only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ID = "attempt-ef6476c5bf4ad3e8"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / SNAPSHOT_ID
OUT = ROOT / "evidence" / "epoch45-final-remediation" / "runtime-control-audit.json"
RUN_ID = "run_bda13e93b2ea"
CURRENT_ATTEMPT = "attempt:run_bda13e93b2ea:remediation_rerun:epoch45:loop3:node1"


def event_id(event: dict[str, Any]) -> str:
    return str(event.get("id") or event.get("event_id") or "")


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def key(event: dict[str, Any]) -> tuple[str, str]:
    item = payload(event)
    return str(item.get("memory_id") or ""), str(item.get("value_sha256") or "")


def ref(event: dict[str, Any]) -> dict[str, Any]:
    item = payload(event)
    return {
        "sequence": int(event["sequence"]),
        "event_id": event_id(event),
        "type": str(event.get("type") or ""),
        "platform_attempt_id": item.get("platform_attempt_id"),
    }


def first_between(events: list[dict[str, Any]], type_name: str, start: int, end: int) -> dict[str, Any] | None:
    return next((event for event in events if event.get("type") == type_name and start < int(event["sequence"]) < end), None)


def main() -> int:
    selected_types = {
        "agent.memory.candidate", "agent.memory.reviewed", "agent.memory.committed",
        "agent.memory.retrieved", "agent.memory.used", "agent.memory.closure.verified",
        "agent.memory.namespace.denied", "agent.memory.superseded", "agent.memory.tombstoned",
        "agent.memory.old_value.hidden", "agent.turn.completed",
        "run.pause_requested", "run.checkpoint.persisted", "run.paused", "run.resumed",
        "run.checkpoint.loaded", "run.interrupted", "run.recovered",
        "worker.lease.acquired", "worker.lease.revoked", "worker.stale_writer.denied",
        "worker.fencing.verified", "worker.duplicate_side_effect.scan",
        "runtime.entrypoint.routed", "runtime.route.attested", "runtime.fallback.denied",
        "runtime.rollback.exercised", "runtime.source.registry.completed",
        "agent.runtime.continuation.started", "agent.runtime.continuation.verified",
        "sdk.session.continued", "agent.side_effect.verified",
        "attempt.created", "judge.verdict.accepted", "gate.rejected", "gate.passed",
        "run.converged", "run.completed", "artifact.authoritative", "artifact.authority.frozen",
    }
    events: list[dict[str, Any]] = []
    all_sequences: list[int] = []
    type_counts: Counter[str] = Counter()
    with (SNAPSHOT / "events.ndjson").open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line)
            if str(event.get("run_id") or "") != RUN_ID:
                raise RuntimeError("foreign_run_event")
            sequence = int(event["sequence"])
            all_sequences.append(sequence)
            type_name = str(event.get("type") or "")
            type_counts[type_name] += 1
            if type_name in selected_types or payload(event).get("platform_attempt_id") == CURRENT_ATTEMPT:
                events.append(event)
    omissions_doc = json.loads((SNAPSHOT / "projection-omissions.json").read_text(encoding="utf-8"))
    omission_sequences = sorted(int(item["sequence"]) for item in omissions_doc.get("omissions", []))
    registry_doc = json.loads((SNAPSHOT / "artifact-registry.json").read_text(encoding="utf-8"))
    registry_items = registry_doc.get("artifacts") if isinstance(registry_doc, dict) else registry_doc
    if not isinstance(registry_items, list):
        registry_items = registry_doc.get("items", []) if isinstance(registry_doc, dict) else []
    registry = {str(item.get("id") or item.get("artifact_id") or ""): item for item in registry_items}

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_type[str(event.get("type") or "")].append(event)

    # Strict Memory chains. The closure must be backed by candidate/review/commit,
    # a later retrieve/use pair for the same immutable value, and a different SDK
    # Session. Completed-turn presence for both SDK identities is independently checked.
    memory_by_type_key: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for type_name in (
        "agent.memory.candidate", "agent.memory.reviewed", "agent.memory.committed",
        "agent.memory.retrieved", "agent.memory.used", "agent.memory.closure.verified",
        "agent.memory.namespace.denied", "agent.memory.superseded", "agent.memory.tombstoned",
        "agent.memory.old_value.hidden",
    ):
        for event in by_type[type_name]:
            memory_by_type_key[type_name][key(event)].append(event)
    completed_sdk_sessions = {
        str(payload(event).get("claude_sdk_session_id") or "")
        for event in by_type["agent.turn.completed"]
        if payload(event).get("claude_sdk_session_id")
    }
    strict_chains: list[dict[str, Any]] = []
    for closure in by_type["agent.memory.closure.verified"]:
        identity = key(closure)
        closure_payload = payload(closure)
        closure_sequence = int(closure["sequence"])
        writer_sdk = str(closure_payload.get("writer_sdk_session_id") or "")
        reader_sdk = str(closure_payload.get("reader_sdk_session_id") or "")
        candidate = next((e for e in memory_by_type_key["agent.memory.candidate"][identity] if int(e["sequence"]) < closure_sequence), None)
        reviewed = next((e for e in memory_by_type_key["agent.memory.reviewed"][identity] if candidate and int(candidate["sequence"]) < int(e["sequence"]) < closure_sequence), None)
        committed = next((e for e in memory_by_type_key["agent.memory.committed"][identity] if reviewed and int(reviewed["sequence"]) < int(e["sequence"]) < closure_sequence), None)
        retrieved = next((e for e in memory_by_type_key["agent.memory.retrieved"][identity] if committed and int(committed["sequence"]) < int(e["sequence"]) < closure_sequence and str(payload(e).get("reader_session_id") or "") == str(closure_payload.get("reader_session_id") or "")), None)
        used = next((e for e in memory_by_type_key["agent.memory.used"][identity] if retrieved and int(retrieved["sequence"]) < int(e["sequence"]) < closure_sequence and str(payload(e).get("reader_sdk_session_id") or "") == reader_sdk), None)
        event_chain_checks = {
            "candidate_review_commit_ordered": bool(candidate and reviewed and committed),
            "later_retrieve_use_ordered": bool(retrieved and used),
            "immutable_value_identity_exact": bool(identity[0] and identity[1]),
            "writer_reader_sdk_sessions_present": bool(writer_sdk and reader_sdk),
            "writer_reader_sdk_sessions_distinct": bool(writer_sdk and reader_sdk and writer_sdk != reader_sdk),
            "closure_declares_strict_terminal_pass": closure_payload.get("strict_sdk_session") is True and closure_payload.get("terminal") is True and closure_payload.get("status") == "passed",
        }
        turn_checks = {
            "writer_completed_turn_observed": writer_sdk in completed_sdk_sessions,
            "reader_completed_turn_observed": reader_sdk in completed_sdk_sessions,
        }
        strict_chains.append({
            "memory_id": identity[0], "value_sha256": identity[1],
            "platform_attempt_id": closure_payload.get("platform_attempt_id"),
            "writer_sdk_session_id": writer_sdk, "reader_sdk_session_id": reader_sdk,
            "events": {
                "candidate": ref(candidate) if candidate else None,
                "reviewed": ref(reviewed) if reviewed else None,
                "committed": ref(committed) if committed else None,
                "retrieved": ref(retrieved) if retrieved else None,
                "used": ref(used) if used else None,
                "closure": ref(closure),
            },
            "event_chain_checks": event_chain_checks,
            "completed_turn_checks": turn_checks,
            "strict_event_chain_complete": all(event_chain_checks.values()),
            "dual_completed_turn_attested": all(turn_checks.values()),
        })
    supersession_complete = 0
    for event in by_type["agent.memory.superseded"]:
        identity = key(event)
        sequence = int(event["sequence"])
        tombstone = next((e for e in memory_by_type_key["agent.memory.tombstoned"][identity] if int(e["sequence"]) > sequence), None)
        hidden = next((e for e in memory_by_type_key["agent.memory.old_value.hidden"][identity] if int(e["sequence"]) > sequence), None)
        if tombstone and hidden:
            supersession_complete += 1

    # Pause cycles. Public and omitted sequence domains are both checked, so a
    # quiet claim is made only when neither contains a sequence in the interval.
    pause_cycles: list[dict[str, Any]] = []
    paused_events = by_type["run.paused"]
    request_events = by_type["run.pause_requested"]
    resumed_events = by_type["run.resumed"]
    for index, paused in enumerate(paused_events):
        paused_sequence = int(paused["sequence"])
        previous_resume = int(resumed_events[index - 1]["sequence"]) if index and index - 1 < len(resumed_events) else 0
        request = next((e for e in reversed(request_events) if previous_resume < int(e["sequence"]) < paused_sequence), None)
        next_pause = int(paused_events[index + 1]["sequence"]) if index + 1 < len(paused_events) else 10**18
        resumed = next((e for e in resumed_events if paused_sequence < int(e["sequence"]) < next_pause), None)
        resumed_sequence = int(resumed["sequence"]) if resumed else next_pause
        checkpoint = next((e for e in reversed(by_type["run.checkpoint.persisted"]) if request and int(request["sequence"]) < int(e["sequence"]) < paused_sequence), None)
        loaded = next((e for e in by_type["run.checkpoint.loaded"] if resumed and int(resumed["sequence"]) < int(e["sequence"]) < next_pause), None)
        public_between = sum(paused_sequence < sequence < resumed_sequence for sequence in all_sequences)
        omitted_between = sum(paused_sequence < sequence < resumed_sequence for sequence in omission_sequences)
        checkpoint_payload = payload(checkpoint) if checkpoint else {}
        checkpoint_artifact = registry.get(str(checkpoint_payload.get("artifact_id") or "")) if checkpoint else None
        checkpoint_registry_exact = bool(
            checkpoint and checkpoint_artifact
            and str(checkpoint_artifact.get("sha256") or checkpoint_artifact.get("expected_sha256") or "") == str(checkpoint_payload.get("sha256") or "")
        )
        pause_cycles.append({
            "index": index + 1,
            "request": ref(request) if request else None,
            "checkpoint_persisted": ref(checkpoint) if checkpoint else None,
            "paused": ref(paused),
            "resumed": ref(resumed) if resumed else None,
            "checkpoint_loaded": ref(loaded) if loaded else None,
            "checkpoint_artifact_id": checkpoint_payload.get("artifact_id"),
            "checkpoint_registry_sha256_exact": checkpoint_registry_exact,
            "public_events_strictly_between_paused_and_resumed": public_between,
            "omission_receipts_strictly_between_paused_and_resumed": omitted_between,
            "source_domain_quiet": public_between == 0 and omitted_between == 0,
            "ordered_checkpoint_cycle": bool(request and checkpoint and resumed and loaded),
        })

    # Worker fencing/reconciliation by execution epoch.
    recovery_types = (
        "worker.lease.acquired", "worker.lease.revoked", "worker.stale_writer.denied",
        "worker.fencing.verified", "run.checkpoint.loaded", "worker.duplicate_side_effect.scan",
        "runtime.route.attested", "runtime.fallback.denied",
    )
    by_epoch: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for type_name in recovery_types:
        for event in by_type[type_name]:
            epoch = payload(event).get("execution_epoch")
            if isinstance(epoch, int):
                by_epoch[epoch][type_name].append(event)
    recovery_epochs: list[dict[str, Any]] = []
    for epoch in sorted(by_epoch):
        group = by_epoch[epoch]
        acquired = group["worker.lease.acquired"][-1] if group["worker.lease.acquired"] else None
        acquired_payload = payload(acquired) if acquired else {}
        new_lease = str(acquired_payload.get("lease_id") or "")
        new_worker = str(acquired_payload.get("worker_id") or "")
        revoked = next((e for e in group["worker.lease.revoked"] if str(payload(e).get("revoked_by_lease_id") or "") == new_lease), None)
        stale = next((e for e in group["worker.stale_writer.denied"] if str(payload(e).get("revoked_by_lease_id") or "") == new_lease), None)
        fenced = next((e for e in group["worker.fencing.verified"] if str(payload(e).get("lease_id") or "") == new_lease and str(payload(e).get("worker_id") or "") == new_worker), None)
        loaded = group["run.checkpoint.loaded"][-1] if group["run.checkpoint.loaded"] else None
        terminal_scan = next((e for e in reversed(group["worker.duplicate_side_effect.scan"]) if payload(e).get("terminal") is True and payload(e).get("status") == "completed"), None)
        route = group["runtime.route.attested"][-1] if group["runtime.route.attested"] else None
        fallback = group["runtime.fallback.denied"][-1] if group["runtime.fallback.denied"] else None
        checks = {
            "new_lease_acquired": bool(acquired and new_lease and new_worker),
            "old_lease_revoked_by_new_lease": bool(revoked),
            "stale_old_writer_actually_denied": bool(stale and payload(stale).get("authorization_decision") == "deny"),
            "new_worker_fencing_verified": bool(fenced),
            "checkpoint_loaded": bool(loaded),
            "terminal_duplicate_scan_zero": bool(terminal_scan and int(payload(terminal_scan).get("duplicate_side_effect_count", -1)) == 0),
            "claude_only_route": bool(route and payload(route).get("runtime") == "claude_code" and payload(route).get("openclaw_traffic_count") == 0),
            "fallback_denied": bool(fallback and payload(fallback).get("authorization_decision") == "deny"),
        }
        recovery_epochs.append({
            "execution_epoch": epoch,
            "new_worker_id": new_worker or None,
            "new_lease_id": new_lease or None,
            "events": {name: ref(value) if value else None for name, value in {
                "lease_acquired": acquired, "lease_revoked": revoked, "stale_writer_denied": stale,
                "fencing_verified": fenced, "checkpoint_loaded": loaded,
                "terminal_duplicate_scan": terminal_scan, "runtime_route": route, "fallback_denied": fallback,
            }.items()},
            "checks": checks,
            "strict_epoch_control_complete": all(checks.values()),
        })

    object_side_effects = [event for event in by_type["agent.side_effect.verified"] if payload(event).get("object_id")]
    object_ledger_exact = [
        event for event in object_side_effects
        if payload(event).get("operation_id") and payload(event).get("idempotency_key")
        and int(payload(event).get("write_count", -1)) == 1
        and int(payload(event).get("duplicate_count", -1)) == 0
        and payload(event).get("terminal") is True
    ]
    object_reconciled_after_interruption = [event for event in object_ledger_exact if payload(event).get("reconciled_after_interruption") is True]

    # Latest runtime-route and continuation facts.
    latest_route = by_type["runtime.route.attested"][-1] if by_type["runtime.route.attested"] else None
    latest_route_payload = payload(latest_route) if latest_route else {}
    latest_source = by_type["runtime.source.registry.completed"][-1] if by_type["runtime.source.registry.completed"] else None
    continuation = by_type["sdk.session.continued"][-1] if by_type["sdk.session.continued"] else None
    continuation_payload = payload(continuation) if continuation else {}
    first_sdk = str(continuation_payload.get("first_sdk_session_id") or "")
    second_sdk = str(continuation_payload.get("second_sdk_session_id") or "")
    window_seconds = None
    if latest_route_payload.get("window_started_at") and latest_route_payload.get("window_ended_at"):
        start = datetime.fromisoformat(str(latest_route_payload["window_started_at"]))
        end = datetime.fromisoformat(str(latest_route_payload["window_ended_at"]))
        window_seconds = (end - start).total_seconds()

    current_attempt_events = [event for event in events if payload(event).get("platform_attempt_id") == CURRENT_ATTEMPT]
    attempt_created = next((event for event in current_attempt_events if event.get("type") == "attempt.created"), None)
    causation_id = str(payload(attempt_created).get("causation_event_id") or "") if attempt_created else ""
    causation = next((event for event in events if event_id(event) == causation_id), None)
    current_attempt_counts = Counter(str(event.get("type") or "") for event in current_attempt_events)

    result = {
        "schema_version": "jianghu.epoch45.runtime-control-audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "snapshot_id": SNAPSHOT_ID,
        "cutoff_sequence": max(all_sequences + omission_sequences),
        "privacy_boundary": "Only public_agent_safe event objects, omission metadata and public Registry metadata were read; no omitted payload, private Memory body, environment value or Provider credential was read.",
        "memory": {
            "event_counts": {name: type_counts[name] for name in (
                "agent.memory.candidate", "agent.memory.reviewed", "agent.memory.committed",
                "agent.memory.retrieved", "agent.memory.used", "agent.memory.closure.verified",
                "agent.memory.namespace.denied", "agent.memory.superseded", "agent.memory.tombstoned",
                "agent.memory.old_value.hidden",
            )},
            "strict_closure_declared": len(strict_chains),
            "strict_event_chain_complete": sum(item["strict_event_chain_complete"] for item in strict_chains),
            "dual_completed_turn_attested": sum(item["strict_event_chain_complete"] and item["dual_completed_turn_attested"] for item in strict_chains),
            "supersession_tombstone_old_value_hidden_complete": supersession_complete,
            "current_attempt_strict_event_chain_count": sum(item["strict_event_chain_complete"] and item["platform_attempt_id"] == CURRENT_ATTEMPT for item in strict_chains),
            "latest_strict_chain": strict_chains[-1] if strict_chains else None,
            "status": "HISTORICAL_STRICT_EVENT_CLOSURE_PRESENT_READER_COMPLETED_TURN_NOT_CORROBORATED; CURRENT_ATTEMPT_NOT_CLOSED" if strict_chains and not any(item["platform_attempt_id"] == CURRENT_ATTEMPT for item in strict_chains) else "REVIEW",
        },
        "pause_resume": {
            "requested": type_counts["run.pause_requested"],
            "paused": type_counts["run.paused"],
            "resumed": type_counts["run.resumed"],
            "checkpoint_persisted": type_counts["run.checkpoint.persisted"],
            "checkpoint_loaded": type_counts["run.checkpoint.loaded"],
            "cycle_count": len(pause_cycles),
            "ordered_checkpoint_cycles": sum(item["ordered_checkpoint_cycle"] for item in pause_cycles),
            "source_domain_quiet_cycles": sum(item["source_domain_quiet"] for item in pause_cycles),
            "cycles": pause_cycles,
            "status": "PARTIAL",
        },
        "recovery": {
            "run_interrupted": type_counts["run.interrupted"],
            "run_recovered": type_counts["run.recovered"],
            "lease_revoked": type_counts["worker.lease.revoked"],
            "stale_writer_denied": type_counts["worker.stale_writer.denied"],
            "terminal_duplicate_scans": sum(payload(event).get("terminal") is True and payload(event).get("status") == "completed" for event in by_type["worker.duplicate_side_effect.scan"]),
            "strict_epoch_control_complete": sum(item["strict_epoch_control_complete"] for item in recovery_epochs),
            "latest_epoch": recovery_epochs[-1] if recovery_epochs else None,
            "object_side_effect_ledger_count": len(object_side_effects),
            "object_side_effect_write_once_zero_duplicate_terminal": len(object_ledger_exact),
            "object_reconciled_after_interruption": len(object_reconciled_after_interruption),
            "status": "PARTIAL_TERMINAL_SCAN_AND_FENCING_PRESENT_OBJECT_RECONCILIATION_ABSENT" if not object_reconciled_after_interruption else "PASS",
        },
        "sdk_continuation": {
            "event_count": type_counts["sdk.session.continued"],
            "latest": ref(continuation) if continuation else None,
            "first_sdk_session_id": first_sdk or None,
            "second_sdk_session_id": second_sdk or None,
            "distinct_sdk_sessions": bool(first_sdk and second_sdk and first_sdk != second_sdk),
            "declared_strict_sdk_session": continuation_payload.get("strict_sdk_session") is True,
            "status": "FAIL_SAME_SDK_SESSION_ID" if continuation and first_sdk == second_sdk else ("PASS" if continuation else "ABSENT"),
        },
        "runtime_and_openclaw": {
            "latest_route": ref(latest_route) if latest_route else None,
            "execution_epoch": latest_route_payload.get("execution_epoch"),
            "entrypoints": latest_route_payload.get("entrypoints", []),
            "sample_count": latest_route_payload.get("sample_count"),
            "window_seconds": window_seconds,
            "runtime": latest_route_payload.get("runtime"),
            "runtime_mode": latest_route_payload.get("runtime_mode"),
            "openclaw_traffic_count": latest_route_payload.get("openclaw_traffic_count"),
            "silent_fallback_count": latest_route_payload.get("silent_fallback_count"),
            "dual_write_count": latest_route_payload.get("dual_write_count"),
            "source_registry": {"event": ref(latest_source) if latest_source else None, "payload": payload(latest_source) if latest_source else None},
            "retirement_status": "REJECTED_PENDING_SOURCE_AUTHORITY_SUSTAINED_PRODUCTION_EVIDENCE_AND_JUDGE_ACCEPT",
        },
        "rework_causation": {
            "current_attempt": CURRENT_ATTEMPT,
            "attempt_created": ref(attempt_created) if attempt_created else None,
            "causation_event_id": causation_id or None,
            "causation_event": ref(causation) if causation else None,
            "causation_is_gate_rejected": bool(causation and causation.get("type") == "gate.rejected" and int(causation["sequence"]) < int(attempt_created["sequence"])),
            "rework_of": payload(attempt_created).get("rework_of") if attempt_created else None,
            "supersedes": payload(attempt_created).get("supersedes") if attempt_created else None,
            "current_attempt_event_counts": dict(sorted(current_attempt_counts.items())),
            "completed_turn_count": current_attempt_counts["agent.turn.completed"],
            "judge_accept_count": type_counts["judge.verdict.accepted"],
            "terminal_counts": {name: type_counts[name] for name in ("gate.passed", "run.converged", "run.completed")},
        },
        "status": "PASS_AUDIT_WITH_FAIL_CLOSED_GAPS",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": result["status"],
        "memory_strict_event_chain_complete": result["memory"]["strict_event_chain_complete"],
        "memory_dual_completed_turn_attested": result["memory"]["dual_completed_turn_attested"],
        "current_attempt_memory": result["memory"]["current_attempt_strict_event_chain_count"],
        "pause_cycles": f"{result['pause_resume']['ordered_checkpoint_cycles']}/{result['pause_resume']['cycle_count']}",
        "recovery_latest_epoch": result["recovery"]["latest_epoch"]["execution_epoch"] if result["recovery"]["latest_epoch"] else None,
        "sdk_continuation": result["sdk_continuation"]["status"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
