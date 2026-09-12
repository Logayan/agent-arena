from __future__ import annotations

import json
from pathlib import Path
import unittest

from runtime_acceptance.verifier import (
    ARTIFACT_REGISTRY_SHA256,
    EVENTS_SHA256,
    EvidenceError,
    check_manifest,
    verify_all,
    verify_projection,
)


class RuntimeAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.result = verify_all(cls.root)

    def test_frozen_projection_identity(self) -> None:
        snapshot = self.result["snapshot"]
        self.assertEqual("PASS_FROZEN_PUBLIC_PROJECTION", snapshot["status"])
        self.assertEqual(4395, snapshot["count"])
        self.assertEqual(4403, snapshot["metadata_event_count"])
        self.assertEqual((1, 4403), (snapshot["sequence_first"], snapshot["sequence_last"]))
        self.assertEqual([687, 812, 1258, 2248, 3898, 3937, 4211, 4329], snapshot["missing_sequences"])
        self.assertEqual(EVENTS_SHA256, snapshot["events_ndjson_sha256"])
        self.assertEqual(330, snapshot["critical_count"])
        self.assertEqual("running", snapshot["run_status_at_snapshot"])
        self.assertEqual(2, snapshot["execution_epoch"])

    def test_projection_is_filtered_not_source_database(self) -> None:
        snapshot = self.result["snapshot"]
        self.assertIn("public_agent_safe", snapshot["projection_boundary"])
        self.assertFalse(snapshot["source_database_verified"])

    def test_runtime_route_and_source_attestation(self) -> None:
        runtime = self.result["runtime"]
        self.assertEqual("claude_code", runtime["runtime"])
        self.assertEqual("agent-sdk-bridge", runtime["runtime_mode"])
        self.assertEqual("0.3.268", runtime["bridge_version"])
        self.assertEqual("2.1.268", runtime["claude_code_version"])
        self.assertEqual([4, 2522], runtime["route_attestation_sequences"])
        self.assertEqual([5, 2523], runtime["fallback_denial_sequences"])
        self.assertFalse(runtime["source_raw_bytes_available"])
        self.assertEqual(13, runtime["source_file_fingerprint_count"])

    def test_sdk_bindings_are_current(self) -> None:
        runtime = self.result["runtime"]
        self.assertEqual(16, runtime["session_binding_count"])
        self.assertEqual(4, runtime["distinct_agent_count"])
        self.assertEqual(16, runtime["distinct_sdk_session_count"])
        self.assertEqual(12, runtime["node_session_binding_count"])
        self.assertEqual(2, runtime["node_distinct_agent_count"])
        self.assertEqual(
            [704, 831, 879, 890, 939, 954, 3926, 4243, 4282, 4292, 4379, 4390],
            runtime["node_binding_sequences"],
        )
        self.assertEqual(0, runtime["explicit_sdk_session_or_invocation_event_count"])

    def test_model_field_is_not_conflated_with_route(self) -> None:
        runtime = self.result["runtime"]
        self.assertEqual(["gpt-5.6-sol"], runtime["binding_model_field_values"])
        self.assertEqual(
            "ATTESTATION_FIELD_ONLY_NOT_END_TO_END_CLAUDE_MODEL_EXECUTION_PROOF",
            runtime["model_field_interpretation"],
        )

    def test_run_wide_tool_lifecycle(self) -> None:
        tools = self.result["tools"]["run_wide"]
        self.assertEqual(785, tools["tool_call_group_count"])
        self.assertEqual({"completed": 720, "failed": 65}, tools["completion_statuses"])
        self.assertEqual({"completed": 720, "failed_preserved": 65}, tools["side_effect_statuses"])
        self.assertEqual({"Bash": 271, "Edit": 115, "Read": 333, "Write": 66}, tools["tool_names"])
        self.assertEqual({"allow": 785}, tools["authorization_decisions"])

    def test_node_tool_lifecycle_and_binding_coverage(self) -> None:
        tools = self.result["tools"]
        node = tools["node_scoped"]
        self.assertEqual(371, node["tool_call_group_count"])
        self.assertEqual({"completed": 324, "failed": 47}, node["completion_statuses"])
        self.assertEqual({"completed": 324, "failed_preserved": 47}, node["side_effect_statuses"])
        self.assertEqual({"Bash": 102, "Edit": 28, "Read": 196, "Write": 45}, node["tool_names"])
        self.assertEqual(6, node["platform_session_count"])
        self.assertEqual(240, tools["bound_to_frozen_sdk_session_count"])
        self.assertEqual(131, tools["unbound_at_snapshot_count"])
        self.assertFalse(tools["authorization_deny_path_observed"])
        self.assertEqual(
            {"sdk_session_id": 0, "invocation_id": 0, "result_digest": 0, "output_sha256": 0},
            tools["native_sdk_linkage_field_coverage"],
        )

    def test_two_collaboration_cycles_are_preserved(self) -> None:
        collaboration = self.result["collaboration"]
        self.assertEqual(4, collaboration["submission_count"])
        self.assertEqual(8, collaboration["message_count"])
        self.assertEqual([843, 844], [row["sequence"] for row in collaboration["historical_cycle"]["submission_events"]])
        self.assertEqual([4255, 4256], [row["sequence"] for row in collaboration["current_cycle"]["submission_events"]])
        self.assertEqual([900, 901, 964, 965], [row["sequence"] for row in collaboration["historical_cycle"]["message_events"]])
        self.assertEqual([4302, 4303, 4400, 4401], [row["sequence"] for row in collaboration["current_cycle"]["message_events"]])
        self.assertEqual(4403, collaboration["current_cycle"]["synthesis_started_sequence"])
        self.assertFalse(collaboration["current_cycle"]["synthesis_completed"])

    def test_memory_read_use_is_partial(self) -> None:
        memory = self.result["memory"]
        self.assertEqual(168, memory["run_wide_retrieval_count"])
        self.assertEqual(128, memory["run_wide_use_count"])
        self.assertEqual(32, memory["run_wide_distinct_memory_id_count"])
        self.assertEqual(104, memory["node_retrieval_count"])
        self.assertEqual(96, memory["node_use_count"])
        self.assertEqual(16, memory["node_distinct_memory_id_count"])
        self.assertEqual(112, memory["run_wide_same_session_use_match_count"])
        self.assertEqual(16, memory["run_wide_same_session_use_unmatched_in_filtered_projection"])
        self.assertEqual(96, memory["node_same_session_use_match_count"])
        self.assertEqual(0, memory["node_same_session_use_unmatched_in_filtered_projection"])
        self.assertEqual(0, memory["write_lifecycle_event_count"])
        self.assertFalse(memory["later_distinct_session_roundtrip_proven"])

    def test_artifact_registry_is_raw_empty_evidence(self) -> None:
        artifacts = self.result["artifacts"]
        self.assertEqual(0, artifacts["registry_count"])
        self.assertEqual(ARTIFACT_REGISTRY_SHA256, artifacts["registry_sha256"])
        self.assertEqual(3, artifacts["registry_size_bytes"])
        self.assertTrue(artifacts["registry_and_materialized_bytes_reread"])
        self.assertFalse(artifacts["formal_artifact_lifecycle_proven"])
        self.assertFalse(artifacts["workspace_file_publication_is_formal_artifact"])

    def test_all_latest_manifest_rows_are_reviewed(self) -> None:
        review = self.result["submission_review"]
        self.assertEqual(58, review["manifest_change_row_count"])
        self.assertEqual(53, review["non_deleted_row_count"])
        self.assertEqual(5, review["deletion_marker_count"])
        self.assertEqual(2, review["submission_count"])
        self.assertEqual(45, review["raw_byte_audit"]["matched_non_deleted_rows"])
        self.assertEqual(8, review["raw_byte_audit"]["non_materialized_non_deleted_rows"])
        self.assertEqual(0, review["raw_byte_audit"]["mismatch_rows"])

    def test_non_materialized_submission_bytes_are_not_overclaimed(self) -> None:
        review = json.loads((self.root / "evidence" / "submission_review.json").read_text(encoding="utf-8"))
        missing = [
            row
            for row in review["reviews"]
            if row["public_export"]["status"].startswith("manifest_and_platform")
        ]
        self.assertEqual(8, len(missing))
        self.assertTrue(all(not row["public_export"]["raw_bytes_available"] for row in missing))
        self.assertTrue(all(row["public_export"]["matches_manifest"] is False for row in missing))

    def test_recovery_is_partial_and_not_converged(self) -> None:
        absent = self.result["absent_lifecycles"]
        self.assertEqual(
            "PARTIAL_PLATFORM_RECOVERY_OBSERVED_NOT_CONVERGED_AT_SNAPSHOT",
            absent["interruption_recovery_status"],
        )
        self.assertEqual(list(range(2519, 2528)), [row["sequence"] for row in absent["recovery_chain"]])
        self.assertFalse(absent["terminal_duplicate_effect_reconciliation_observed"])
        self.assertFalse(absent["run_convergence_or_completion_observed"])

    def test_required_negative_lifecycles_remain_blocked(self) -> None:
        absent = self.result["absent_lifecycles"]
        self.assertEqual(0, absent["judge_related_event_count"])
        self.assertEqual(0, absent["intentional_pause_resume_event_count"])
        self.assertEqual(0, absent["sdk_session_continuation_event_count"])
        self.assertEqual(0, absent["run_convergence_event_count"])

    def test_mapping_and_gap_verdicts_are_fail_closed(self) -> None:
        self.assertGreaterEqual(self.result["gaps"]["open_p0_count"], 10)
        self.assertEqual("CONDITIONAL_PASS_MAPPING_AND_BOUNDARY_DELIVERED", self.result["node_delivery_status"])
        self.assertEqual("NO_GO_COMPLETE_MIGRATION_NOT_PROVEN", self.result["migration_acceptance"])
        self.assertEqual("NOT_APPROVED", self.result["openclaw_retirement"])

    def test_target_schema_is_explicitly_not_current_conformance(self) -> None:
        schema = json.loads((self.root / "schemas" / "runtime-event-envelope.schema.json").read_text(encoding="utf-8"))
        note = schema["x-jianghu-acceptance-note"]
        self.assertEqual("TARGET_ONLY", note["status"])
        self.assertFalse(note["observed_projection_conforms"])
        self.assertTrue(note["route_model_non_conflation"])
        tool_required = schema["$defs"]["tool_operation"]["required"]
        for field in ("sdk_session_id", "invocation_id", "tool_use_id", "operation_id", "idempotency_key", "result_status"):
            self.assertIn(field, tool_required)

    def test_snapshot_verifier_is_deterministic(self) -> None:
        events, snapshot = verify_projection(self.root)
        self.assertEqual(4395, len(events))
        self.assertEqual(self.result["snapshot"], snapshot)

    def test_manifest_when_present_is_complete(self) -> None:
        manifest_path = self.root / "artifacts" / "sha256_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # This suite validates the preserved upstream OpenClaw snapshot. The
            # package manifest now belongs to runtime_probe_harness and is
            # independently checked by test_runtime_probe_current.py.
            if manifest.get("node_key") == "openclaw_baseline_mapping":
                status = check_manifest(self.root)
                self.assertEqual("PASS_WHOLE_PACKAGE_MANIFEST", status["status"])
                self.assertGreater(status["file_count"], 20)
            else:
                self.assertEqual("runtime_probe_harness", manifest.get("node_key"))

    def test_evidence_error_is_fail_closed(self) -> None:
        with self.assertRaises(EvidenceError):
            from runtime_acceptance.verifier import _assert
            _assert(False, "intentional test failure")


if __name__ == "__main__":
    unittest.main()
