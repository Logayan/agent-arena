from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ID = "attempt-415cb8b318fda11f"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / SNAPSHOT_ID
RECEIPT_PATH = ROOT / "evidence" / "verification-receipt.json"
MANIFEST_PATH = ROOT / "artifacts" / "sha256-manifest.json"
RUN_ID = "run_6940048dd30f"

EXPECTED_SNAPSHOT = {
    "events.ndjson": (95579, "f2663c4ec156deb9eecc72b5c80d49f6d2879128e5c16ed72e0a999d2ca4891b"),
    "critical-events.json": (94542, "dd9dbf92f5a805440e3edffef8b61f4035a0d97d8120997a949d37f9343c2372"),
    "artifact-registry.json": (14106, "aaa67ba117215881a836eae95b59ff768d5dfed294ebb0e44b2e232e8e8b68b9"),
    "runtime-attestation.json": (1326, "5ab05e98d8eaeede8bf85a0fc3655d4fbefd6f8e259f49e437b2b161c7418a64"),
    "runtime-source-attestation.json": (3691, "c43e907bb1c0b98ed70dda849a50da3d3282a1ca9a6d740b18050a671161c852"),
    "run-metadata.json": (596, "e56fe3df6331ce8027db8d78cd05e99220d3defcbc6136a9e411d7fb11080d39"),
    "run-lineage.json": (197, "e00b0d0e6ffb1f0f964cee6c58cc5c15a0627eee2025a97e8f6953947cf27a0b"),
    "projection-omissions.json": (232, "91acb4b0f30267643a1442391038830c6e43cae2d682353219223d6b5097e085"),
}

EXPECTED_ENTRYPOINTS = {
    "normal", "parallel", "judge", "rework", "recovery",
    "retry", "scheduled", "callback", "manual", "background",
}

REQUIRED_SOURCE_PATTERNS = {
    "server/app/agent_runtime_registry.py": [
        r'configured_runtime\s*=.*"claude_code"',
        r'configured_runtime\s*!=\s*"claude_code"',
        r'AgentRuntimeRegistry\(claude_code_runtime\)',
    ],
    "server/app/claude_code_runtime.py": [
        r'class ClaudeCodeRuntime',
        r'def _save_session_id',
        r'async def message',
        r'"resume_session_id"',
        r'"sdk_invocation_id"',
        r'"claude_sdk_session_id"',
        r'"request_sha256"',
        r'"result_sha256"',
    ],
    "server/claude_agent_runtime/bridge.mjs": [
        r"from '@anthropic-ai/claude-agent-sdk'",
        r'createSdkMcpServer',
        r'query\(\{ prompt, options \}\)',
        r'persistSession:\s*true',
        r'options\.resume',
        r'(?:strictMcpConfig:\s*true|strictMcpConfig\s*=\s*true)',
    ],
    "server/app/platform_executor.py": [
        r'"agent\.turn\.completed"',
        r'"agent\.tool\.completed"',
        r'"agent\.side_effect\.verified"',
        r'"agent\.memory\.committed"',
        r'"agent\.message\.sent"',
        r'"run\.converged"',
    ],
    "server/app/platform_store.py": [
        r'CREATE TABLE IF NOT EXISTS agent_memories',
        r'CREATE TABLE IF NOT EXISTS runs',
        r'CREATE TABLE IF NOT EXISTS tasks',
        r'CREATE TABLE IF NOT EXISTS artifacts',
        r'CREATE TABLE IF NOT EXISTS events',
        r'def verify_artifact_bytes',
        r'def recover_run',
        r'def retry_run',
    ],
    "server/app/main.py": [
        r'/api/platform/runtime/status',
        r'/api/platform/runs/\{run_id\}/pause',
        r'/api/platform/runs/\{run_id\}/resume',
        r'/api/platform/runs/\{run_id\}/recover',
        r'"run\.checkpoint\.persisted"',
    ],
    "Dockerfile": [
        r'JIANGHU_AGENT_RUNTIME=claude_code',
        r'@anthropic-ai/claude-agent-sdk',
    ],
    "compose.yaml": [r'JIANGHU_AGENT_RUNTIME:\s*claude_code'],
}

REQUIRED_MAPPING_STATUSES = {
    "PASS_CURRENT_RUN", "PASS_SOURCE_ONLY", "PARTIAL_CURRENT_RUN",
    "BLOCKED_NO_RUNTIME_EXECUTION", "BLOCKED_HISTORICAL_BASELINE_ABSENT",
    "NOT_APPLICABLE_CURRENT_OPENCLAW_ROUTE",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_events() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (SNAPSHOT / "events.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def source_by_title(registry: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], Path, str]]:
    result: dict[str, tuple[dict[str, Any], Path, str]] = {}
    root = ROOT.resolve()
    evidence_root = (ROOT / ".jianghu-platform-evidence").resolve()
    for item in registry:
        path = (SNAPSHOT / str(item["materialized_path"])).resolve()
        assert_true(path.is_relative_to(evidence_root), f"artifact_path_escape:{item['id']}")
        assert_true(path.is_file(), f"artifact_missing:{item['id']}")
        data = path.read_bytes()
        digest = sha256_bytes(data)
        assert_true(len(data) == int(item["size_bytes"]), f"artifact_size_mismatch:{item['id']}")
        assert_true(digest == item["expected_sha256"] == item["observed_sha256"], f"artifact_hash_mismatch:{item['id']}")
        assert_true(path.is_relative_to(root), f"artifact_outside_delivery:{item['id']}")
        result[str(item["title"])] = (item, path, data.decode("utf-8", errors="replace"))
    return result


def verify() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for name, (size, digest) in EXPECTED_SNAPSHOT.items():
        path = SNAPSHOT / name
        data = path.read_bytes()
        checks[f"snapshot:{name}"] = len(data) == size and sha256_bytes(data) == digest
        assert_true(checks[f"snapshot:{name}"], f"snapshot_mismatch:{name}")

    events = read_events()
    metadata = load_json(SNAPSHOT / "run-metadata.json")
    omissions = load_json(SNAPSHOT / "projection-omissions.json")
    critical = load_json(SNAPSHOT / "critical-events.json")
    registry = load_json(SNAPSHOT / "artifact-registry.json")
    runtime_attestation = load_json(SNAPSHOT / "runtime-attestation.json")
    source_attestation = load_json(SNAPSHOT / "runtime-source-attestation.json")

    sequences = [int(event["sequence"]) for event in events]
    event_ids = [str(event["event_id"]) for event in events]
    source_hashes = [str(event.get("source_event_sha256") or "") for event in events]
    checks["event_sequence_exact_1_94"] = sequences == list(range(1, 95))
    checks["event_ids_unique"] = len(event_ids) == len(set(event_ids)) == 94
    checks["source_event_hashes_unique_and_well_formed"] = (
        len(source_hashes) == len(set(source_hashes)) == 94
        and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in source_hashes)
    )
    checks["projection_omissions_zero"] = omissions.get("omission_count") == 0 and not omissions.get("omissions")
    assert_true(
        all(checks[key] for key in (
            "event_sequence_exact_1_94",
            "event_ids_unique",
            "source_event_hashes_unique_and_well_formed",
            "projection_omissions_zero",
        )),
        "event_projection_invalid",
    )

    event_by_id = {event["event_id"]: event for event in events}
    checks["critical_full_object_exact"] = len(critical) == 92 and all(event_by_id.get(event["event_id"]) == event for event in critical)
    assert_true(checks["critical_full_object_exact"], "critical_events_mismatch")

    metadata_delta = len(events) - int(metadata["event_count"])
    checks["metadata_lag_disclosed"] = metadata_delta == 1
    assert_true(checks["metadata_lag_disclosed"], f"unexpected_metadata_delta:{metadata_delta}")

    assert_true(isinstance(registry, list) and len(registry) == 13, "registry_count_mismatch")
    sources = source_by_title(registry)
    checks["artifact_raw_bytes_13_of_13"] = len(sources) == 13
    event_by_sequence = {int(event["sequence"]): event for event in events}
    checks["artifact_registry_source_events_exact"] = all(
        int(item["source_event_sequence"]) in event_by_sequence
        and event_by_sequence[int(item["source_event_sequence"])]["event_id"] == item["source_event_id"]
        and event_by_sequence[int(item["source_event_sequence"])]["source_event_sha256"] == item["source_event_sha256"]
        and event_by_sequence[int(item["source_event_sequence"])]["type"] == "artifact.created"
        and (event_by_sequence[int(item["source_event_sequence"])].get("payload") or {}).get("artifact_id") == item["id"]
        for item in registry
    )
    assert_true(checks["artifact_registry_source_events_exact"], "artifact_source_event_mismatch")

    lifecycle: dict[str, list[str]] = collections.defaultdict(list)
    lifecycle_sequences: dict[str, list[int]] = collections.defaultdict(list)
    for event in events:
        artifact_id = str((event.get("payload") or {}).get("artifact_id") or "")
        if artifact_id:
            lifecycle[artifact_id].append(str(event["type"]))
            lifecycle_sequences[artifact_id].append(int(event["sequence"]))
    expected_lifecycle = ["artifact.created", "artifact.collected", "artifact.download.verified"]
    checks["artifact_lifecycle_13_of_13"] = all(lifecycle[item["id"]] == expected_lifecycle for item in registry)
    assert_true(checks["artifact_lifecycle_13_of_13"], "artifact_lifecycle_mismatch")

    attested_files = {item["path"]: item for item in source_attestation["files"]}
    checks["source_attestation_matches_registry"] = (
        source_attestation.get("status") == "passed"
        and len(attested_files) == 13
        and all(
            item["title"] in attested_files
            and item["expected_sha256"] == attested_files[item["title"]]["sha256"]
            and item["size_bytes"] == attested_files[item["title"]]["size_bytes"]
            for item in registry
        )
    )
    assert_true(checks["source_attestation_matches_registry"], "source_attestation_registry_mismatch")
    checks["current_node_candidate_artifact_zero_at_cutoff"] = all(
        item.get("task_id") is None
        and item.get("source_task_id") is None
        and item.get("source_node_key") == "run"
        and item.get("kind") == "runtime_file"
        for item in registry
    )
    assert_true(checks["current_node_candidate_artifact_zero_at_cutoff"], "unexpected_node_candidate_artifact")

    package = json.loads(sources["server/claude_agent_runtime/package.json"][2])
    lock = json.loads(sources["server/claude_agent_runtime/package-lock.json"][2])
    checks["sdk_dependency_pinned_0_3_268"] = (
        package["dependencies"].get("@anthropic-ai/claude-agent-sdk") == "0.3.268"
        and lock["packages"]["node_modules/@anthropic-ai/claude-agent-sdk"]["version"] == "0.3.268"
    )
    assert_true(checks["sdk_dependency_pinned_0_3_268"], "sdk_pin_mismatch")

    source_contracts: dict[str, bool] = {}
    for title, patterns in REQUIRED_SOURCE_PATTERNS.items():
        assert_true(title in sources, f"required_source_missing:{title}")
        text = sources[title][2]
        for pattern in patterns:
            key = f"{title}:{pattern}"
            source_contracts[key] = re.search(pattern, text, re.MULTILINE) is not None
            assert_true(source_contracts[key], f"source_contract_missing:{key}")
    checks["source_contracts_complete"] = all(source_contracts.values())

    event_types = collections.Counter(str(event["type"]) for event in events)
    routed = [event for event in events if event["type"] == "runtime.entrypoint.routed"]
    route_entrypoints = {str(event["payload"]["entrypoint"]) for event in routed}
    checks["route_entrypoints_10_of_10"] = (
        route_entrypoints == EXPECTED_ENTRYPOINTS
        and len(routed) == 10
        and all(event["payload"].get("runtime") == "claude_code" for event in routed)
    )
    assert_true(checks["route_entrypoints_10_of_10"], "route_entrypoint_mismatch")
    route_summary = next(event for event in events if event["type"] == "runtime.route.attested")
    route_payload = route_summary["payload"]
    route_started = dt.datetime.fromisoformat(str(route_payload["window_started_at"]))
    route_ended = dt.datetime.fromisoformat(str(route_payload["window_ended_at"]))
    route_window_seconds = (route_ended - route_started).total_seconds()
    checks["route_window_duration_exact"] = abs(route_window_seconds - 16.218474) < 0.000001
    assert_true(checks["route_window_duration_exact"], "route_window_duration_changed")
    checks["route_zero_openclaw_single_writer"] = (
        route_payload.get("openclaw_traffic_count") == 0
        and route_payload.get("dual_write_count") == 0
        and route_payload.get("silent_fallback_count") == 0
        and route_payload.get("single_writer") is True
        and route_payload.get("fail_closed") is True
    )
    assert_true(checks["route_zero_openclaw_single_writer"], "route_summary_failed")

    fallback = next(event for event in events if event["type"] == "runtime.fallback.denied")
    rollback = next(event for event in events if event["type"] == "runtime.rollback.exercised")
    checks["fallback_denied_and_rollback_healthy"] = (
        fallback["payload"].get("authorization_decision") == "deny"
        and fallback["payload"].get("status") == "passed"
        and rollback["payload"].get("status") == "passed"
        and rollback["payload"].get("rollback_status") == "healthy"
    )
    assert_true(checks["fallback_denied_and_rollback_healthy"], "fallback_probe_failed")

    authorization_events = [event for event in events if event["type"] == "agent.tool.authorization.decided"]
    iam = [event for event in authorization_events if str(event["payload"].get("tool_call_id", "")).startswith("iam-probe:")]
    policy_probes = [event for event in authorization_events if str(event["payload"].get("tool_call_id", "")).startswith("policy-probe:")]
    checks["iam_matrix_30_expected"] = (
        len(iam) == 30
        and sum(event["payload"].get("authorization_decision") == "allow" for event in iam) == 24
        and sum(event["payload"].get("authorization_decision") == "deny" for event in iam) == 6
        and all(event["payload"].get("side_effect_status") == "not_started" for event in iam)
    )
    checks["authorization_total_31_with_independent_policy_deny"] = (
        len(authorization_events) == 31
        and len(policy_probes) == 1
        and policy_probes[0]["sequence"] == 90
        and policy_probes[0]["payload"].get("tool_name") == "OpenClawGateway"
        and policy_probes[0]["payload"].get("authorization_decision") == "deny"
        and policy_probes[0]["payload"].get("side_effect_status") == "not_started"
    )
    assert_true(
        checks["iam_matrix_30_expected"] and checks["authorization_total_31_with_independent_policy_deny"],
        "authorization_probe_mismatch",
    )

    required_absent = {
        "agent.turn.completed": event_types["agent.turn.completed"],
        "agent.tool.started": event_types["agent.tool.started"],
        "agent.tool.completed": event_types["agent.tool.completed"],
        "agent.side_effect.verified": event_types["agent.side_effect.verified"],
        "agent.message.sent": event_types["agent.message.sent"],
        "agent.memory.committed": event_types["agent.memory.committed"],
        "run.paused": event_types["run.paused"],
        "run.resumed": event_types["run.resumed"],
        "run.recovered": event_types["run.recovered"],
        "gate.rejected": event_types["gate.rejected"],
        "run.converged": event_types["run.converged"],
        "run.completed": event_types["run.completed"],
    }
    checks["runtime_acceptance_events_absent_and_blocked"] = all(value == 0 for value in required_absent.values())
    assert_true(checks["runtime_acceptance_events_absent_and_blocked"], "snapshot_cutoff_changed_review_required")
    checks["session_binding_zero"] = (
        runtime_attestation.get("session_binding_count") == 0
        and runtime_attestation.get("distinct_sdk_session_count") == 0
    )
    assert_true(checks["session_binding_zero"], "unexpected_session_binding")

    exclusions = source_attestation.get("historical_exclusions", [])
    registered_titles = set(sources)
    historical_paths = {str(item.get("path")) for item in exclusions}
    checks["historical_openclaw_bytes_absent"] = (
        "experiments/openclaw_baseline/openclaw_runtime.py" in historical_paths
        and "server/tests/runtime_contract/test_openclaw_runtime_contract.py" in historical_paths
        and not (historical_paths & registered_titles)
    )
    assert_true(checks["historical_openclaw_bytes_absent"], "historical_baseline_state_changed")

    mapping = load_json(ROOT / "mapping" / "capability-mapping.json")
    gaps = load_json(ROOT / "gaps" / "migration-gaps.json")
    evidence_index = load_json(ROOT / "evidence" / "evidence-index.json")
    collaboration = load_json(ROOT / "collaboration" / "public-communication-record.json")
    submission_review = load_json(ROOT / "collaboration" / "submission-review.json")
    capabilities = mapping.get("capabilities", [])
    checks["mapping_contract"] = (
        len(capabilities) == 12
        and len({item["id"] for item in capabilities}) == 12
        and all(item["status"] in REQUIRED_MAPPING_STATUSES for item in capabilities)
        and mapping["decision"]["mapping_deliverable"] == "CONDITIONAL_PASS_EVIDENCE_BOUND_MAPPING"
        and mapping["decision"]["complete_claude_agent_sdk_runtime_migration"] == "NO_GO"
        and mapping["decision"]["openclaw_retirement"] == "NOT_APPROVED"
    )
    checks["gap_contract"] = (
        gaps.get("open_gap_count") == len(gaps.get("gaps", [])) == 13
        and sum(item["priority"] == "P0" for item in gaps["gaps"]) == gaps.get("p0_open") == 11
        and sum(item["priority"] == "P1" for item in gaps["gaps"]) == gaps.get("p1_open") == 2
        and all(item["status"] == "OPEN" for item in gaps["gaps"])
    )
    checks["evidence_index_contract"] = len(evidence_index.get("artifacts", [])) == 13
    checks["public_collaboration_content_and_event_boundary"] = (
        len(collaboration.get("messages", [])) == 4
        and {item["round"] for item in collaboration["messages"]} == {1, 2}
        and {item["sender"] for item in collaboration["messages"]} == {"程观澜", "谢临川"}
        and collaboration["classification"]["content_level_two_round_exchange"] == "PASS_4_MESSAGES_2_ACTORS_2_ROUNDS"
        and collaboration["classification"]["frozen_event_projection_attestation"] == "BLOCKED_NOT_IN_SEQUENCE_1_94"
        and collaboration["classification"]["runtime_acceptance_eligible"] is False
    )
    reviewed_files = sum(item.get("reviewed_file_count", 0) for item in submission_review.get("submissions", []))
    checks["submission_review_59_of_59"] = (
        len(submission_review.get("submissions", [])) == 2
        and reviewed_files == 59
        and submission_review.get("summary", {}).get("reviewed_files") == 59
        and submission_review.get("summary", {}).get("undecided_files") == 0
        and all(item.get("all_paths_decided") is True for item in submission_review["submissions"])
    )
    assert_true(
        all(checks[key] for key in (
            "mapping_contract",
            "gap_contract",
            "evidence_index_contract",
            "public_collaboration_content_and_event_boundary",
            "submission_review_59_of_59",
        )),
        "delivery_contract_invalid",
    )

    residual_references: list[dict[str, Any]] = []
    classifications = {
        "server/app/platform_executor.py": "verification_and_negative_probe",
        "server/app/platform_store.py": "data_and_event_compatibility",
        "server/app/main.py": "api_and_error_compatibility",
        "client/src/App.vue": "ui_event_and_text_compatibility",
    }
    for title, (_, _, text) in sources.items():
        lines = [index for index, line in enumerate(text.splitlines(), 1) if "openclaw" in line.lower()]
        if lines:
            residual_references.append({
                "path": title,
                "line_count": len(lines),
                "lines": lines,
                "classification": classifications.get(title, "unclassified_review_required"),
            })
    checks["residual_references_classified"] = all(item["classification"] != "unclassified_review_required" for item in residual_references)
    assert_true(checks["residual_references_classified"], "unclassified_openclaw_reference")

    artifact_verification = []
    for item in sorted(registry, key=lambda value: int(value["source_event_sequence"])):
        materialized = (SNAPSHOT / str(item["materialized_path"])).resolve()
        raw = materialized.read_bytes()
        artifact_verification.append({
            "artifact_id": item["id"],
            "source_event_sequence": item["source_event_sequence"],
            "source_event_id": item["source_event_id"],
            "source_path": item["title"],
            "materialized_path": materialized.relative_to(ROOT.resolve()).as_posix(),
            "expected_size_bytes": item["size_bytes"],
            "observed_size_bytes": len(raw),
            "expected_sha256": item["expected_sha256"],
            "registry_observed_sha256": item["observed_sha256"],
            "independently_computed_sha256": sha256_bytes(raw),
            "lifecycle_sequences": lifecycle_sequences[item["id"]],
            "lifecycle_types": lifecycle[item["id"]],
            "verified": True,
        })

    all_integrity_checks_pass = all(checks.values())
    assert_true(all_integrity_checks_pass, "verification_failed")
    receipt = {
        "schema_version": "jianghu.runtime-mapping-verification-receipt.v1",
        "run_id": RUN_ID,
        "snapshot_id": SNAPSHOT_ID,
        "source_generated_at": metadata.get("generated_at"),
        "status": "PASS_EVIDENCE_INTEGRITY_NO_GO_ACCEPTANCE",
        "checks": checks,
        "metrics": {
            "public_events": len(events),
            "sequence_min": min(sequences),
            "sequence_max": max(sequences),
            "critical_events_exact": len(critical),
            "projection_omissions": omissions.get("omission_count"),
            "metadata_event_count": metadata.get("event_count"),
            "projection_minus_metadata": metadata_delta,
            "registry_artifacts": len(registry),
            "raw_artifacts_verified": len(sources),
            "artifact_lifecycles_verified": sum(lifecycle[item["id"]] == expected_lifecycle for item in registry),
            "route_entrypoints": len(routed),
            "route_window_seconds": route_window_seconds,
            "authorization_events": len(authorization_events),
            "iam_probes": len(iam),
            "iam_allow": sum(event["payload"].get("authorization_decision") == "allow" for event in iam),
            "iam_deny": sum(event["payload"].get("authorization_decision") == "deny" for event in iam),
            "policy_probe_deny": len(policy_probes),
            "session_bindings": runtime_attestation.get("session_binding_count"),
            "current_node_candidate_artifacts": 0,
            "public_collaboration_messages_content_level": len(collaboration["messages"]),
            "public_collaboration_messages_frozen_event_level": event_types["agent.message.sent"],
            "reviewed_public_submission_files": reviewed_files,
            "runtime_acceptance_event_counts": required_absent,
            "open_gaps": gaps.get("open_gap_count"),
            "p0_open": gaps.get("p0_open"),
            "p1_open": gaps.get("p1_open"),
        },
        "route_window": {
            "started_at": route_payload.get("window_started_at"),
            "ended_at": route_payload.get("window_ended_at"),
            "sample_count": route_payload.get("sample_count"),
            "duration_seconds": route_window_seconds,
            "classification": "PASS_PLATFORM_PROBE_WINDOW_ONLY",
            "openclaw_traffic_count": route_payload.get("openclaw_traffic_count"),
            "dual_write_count": route_payload.get("dual_write_count"),
            "silent_fallback_count": route_payload.get("silent_fallback_count"),
        },
        "artifact_byte_and_lifecycle_verification": artifact_verification,
        "residual_openclaw_references": residual_references,
        "decisions": {
            "mapping_deliverable": "CONDITIONAL_PASS_EVIDENCE_BOUND_MAPPING",
            "complete_claude_agent_sdk_runtime_migration": "NO_GO",
            "openclaw_retirement": "NOT_APPROVED",
            "public_collaboration_content": "PASS_4_MESSAGES_2_ACTORS_2_ROUNDS",
            "public_collaboration_frozen_event_attestation": "BLOCKED_0_AT_SEQUENCE_94",
            "current_node_candidate_artifact_lifecycle": "BLOCKED_0_AT_SEQUENCE_94",
        },
        "limitations": [
            "public_agent_safe projection is not the private source database export",
            "source_event_sha256 cannot be independently recomputed without source event bytes",
            "historical OpenClaw baseline bytes are not registered in this snapshot",
            "source implementation does not substitute for current-run execution evidence",
            "route observation window is short and not a long-term production traffic proof",
            "public two-round message content was provided after the frozen cutoff and is not a substitute for frozen event-level collaboration telemetry",
            "the 13 registered artifacts are runtime source/deployment inputs, not the current node candidate package",
        ],
    }
    return receipt


def delivery_files() -> list[Path]:
    excluded_roots = {".jianghu-platform-evidence", "__pycache__", ".git"}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative == MANIFEST_PATH.relative_to(ROOT):
            continue
        if any(part in excluded_roots for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def write_manifest() -> dict[str, Any]:
    entries = []
    for path in delivery_files():
        data = path.read_bytes()
        entries.append({
            "path": path.relative_to(ROOT).as_posix(),
            "size_bytes": len(data),
            "sha256": sha256_bytes(data),
        })
    manifest = {
        "schema_version": "jianghu.delivery-sha256-manifest.v1",
        "self_excluding": True,
        "excluded": [
            "artifacts/sha256-manifest.json",
            ".jianghu-platform-evidence/**",
            "**/__pycache__/**",
            "**/*.pyc",
        ],
        "file_count": len(entries),
        "files": entries,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def check_manifest() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    current = {path.relative_to(ROOT).as_posix(): path for path in delivery_files()}
    recorded = {item["path"]: item for item in manifest["files"]}
    assert_true(set(current) == set(recorded), "manifest_file_set_mismatch")
    for name, path in current.items():
        data = path.read_bytes()
        item = recorded[name]
        assert_true(len(data) == item["size_bytes"], f"manifest_size_mismatch:{name}")
        assert_true(sha256_bytes(data) == item["sha256"], f"manifest_hash_mismatch:{name}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--check-manifest", action="store_true")
    args = parser.parse_args()
    try:
        receipt = verify()
        if args.write_receipt:
            RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
            RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.write_manifest:
            manifest = write_manifest()
            print(f"MANIFEST WRITTEN files={manifest['file_count']}")
        if args.check_manifest:
            manifest = check_manifest()
            print(f"MANIFEST PASS files={manifest['file_count']}")
        metrics = receipt["metrics"]
        print(
            "VERIFICATION PASS "
            f"events={metrics['public_events']} critical={metrics['critical_events_exact']} "
            f"artifacts={metrics['raw_artifacts_verified']}/13 routes={metrics['route_entrypoints']}/10 "
            f"session_bindings={metrics['session_bindings']} gaps={metrics['open_gaps']} "
            "overall=NO_GO"
        )
        return 0
    except (AssertionError, KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
