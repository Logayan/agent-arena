from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_mapping", ROOT / "src" / "verify_mapping.py")
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class RuntimeMappingVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.receipt = VERIFY.verify()

    def test_snapshot_projection_and_disclosed_metadata_lag(self) -> None:
        self.assertEqual(self.receipt["metrics"]["public_events"], 94)
        self.assertEqual(self.receipt["metrics"]["sequence_min"], 1)
        self.assertEqual(self.receipt["metrics"]["sequence_max"], 94)
        self.assertEqual(self.receipt["metrics"]["projection_minus_metadata"], 1)
        self.assertEqual(self.receipt["metrics"]["projection_omissions"], 0)

    def test_critical_objects_are_exact(self) -> None:
        self.assertTrue(self.receipt["checks"]["critical_full_object_exact"])
        self.assertEqual(self.receipt["metrics"]["critical_events_exact"], 92)

    def test_all_registered_raw_bytes_and_lifecycles_verify(self) -> None:
        self.assertEqual(self.receipt["metrics"]["raw_artifacts_verified"], 13)
        self.assertEqual(self.receipt["metrics"]["artifact_lifecycles_verified"], 13)
        self.assertTrue(self.receipt["checks"]["source_attestation_matches_registry"])
        details = self.receipt["artifact_byte_and_lifecycle_verification"]
        self.assertEqual(len(details), 13)
        self.assertTrue(all(item["verified"] for item in details))
        self.assertTrue(all(item["expected_sha256"] == item["independently_computed_sha256"] for item in details))

    def test_claude_route_is_short_window_and_fail_closed(self) -> None:
        self.assertEqual(self.receipt["metrics"]["route_entrypoints"], 10)
        self.assertEqual(self.receipt["route_window"]["openclaw_traffic_count"], 0)
        self.assertEqual(self.receipt["route_window"]["dual_write_count"], 0)
        self.assertEqual(self.receipt["route_window"]["silent_fallback_count"], 0)
        self.assertTrue(self.receipt["checks"]["fallback_denied_and_rollback_healthy"])

    def test_iam_probes_are_not_misclassified_as_tool_execution(self) -> None:
        self.assertEqual(self.receipt["metrics"]["iam_probes"], 30)
        self.assertEqual(self.receipt["metrics"]["iam_allow"], 24)
        self.assertEqual(self.receipt["metrics"]["iam_deny"], 6)
        counts = self.receipt["metrics"]["runtime_acceptance_event_counts"]
        self.assertEqual(counts["agent.tool.started"], 0)
        self.assertEqual(counts["agent.tool.completed"], 0)
        self.assertEqual(counts["agent.side_effect.verified"], 0)

    def test_session_and_end_to_end_acceptance_remain_blocked(self) -> None:
        self.assertEqual(self.receipt["metrics"]["session_bindings"], 0)
        counts = self.receipt["metrics"]["runtime_acceptance_event_counts"]
        self.assertTrue(all(value == 0 for value in counts.values()))
        self.assertEqual(self.receipt["decisions"]["complete_claude_agent_sdk_runtime_migration"], "NO_GO")
        self.assertEqual(self.receipt["decisions"]["openclaw_retirement"], "NOT_APPROVED")

    def test_historical_openclaw_baseline_bytes_are_absent(self) -> None:
        self.assertTrue(self.receipt["checks"]["historical_openclaw_bytes_absent"])
        mapping = json.loads((ROOT / "mapping" / "capability-mapping.json").read_text(encoding="utf-8"))
        self.assertTrue(any("历史" in item["historical_openclaw_actual"] or item["historical_openclaw_actual"].startswith("BLOCKED") for item in mapping["capabilities"]))

    def test_residual_openclaw_references_are_explicitly_classified(self) -> None:
        residual = self.receipt["residual_openclaw_references"]
        self.assertGreaterEqual(len(residual), 4)
        self.assertTrue(all(item["classification"] != "unclassified_review_required" for item in residual))
        self.assertIn("server/app/main.py", {item["path"] for item in residual})
        self.assertIn("client/src/App.vue", {item["path"] for item in residual})

    def test_mapping_and_gap_counts_are_fail_closed(self) -> None:
        self.assertTrue(self.receipt["checks"]["mapping_contract"])
        self.assertEqual(self.receipt["metrics"]["open_gaps"], 13)
        self.assertEqual(self.receipt["metrics"]["p0_open"], 11)
        self.assertEqual(self.receipt["metrics"]["p1_open"], 2)

    def test_source_hashes_and_registry_source_events_are_bound(self) -> None:
        self.assertTrue(self.receipt["checks"]["source_event_hashes_unique_and_well_formed"])
        self.assertTrue(self.receipt["checks"]["artifact_registry_source_events_exact"])

    def test_runtime_and_model_attestation_are_not_conflated(self) -> None:
        snapshot = json.loads((ROOT / ".jianghu-platform-evidence" / "snapshots" / VERIFY.SNAPSHOT_ID / "runtime-attestation.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["runtime_health"]["runtime"], "claude_code")
        self.assertEqual(snapshot["runtime_sync"]["model"], "gpt-5.6-sol")
        self.assertNotEqual(snapshot["runtime_health"]["runtime"], snapshot["runtime_sync"]["model"])

    def test_public_collaboration_content_is_not_event_attestation(self) -> None:
        self.assertTrue(self.receipt["checks"]["public_collaboration_content_and_event_boundary"])
        self.assertEqual(self.receipt["metrics"]["public_collaboration_messages_content_level"], 4)
        self.assertEqual(self.receipt["metrics"]["public_collaboration_messages_frozen_event_level"], 0)
        self.assertEqual(self.receipt["decisions"]["public_collaboration_frozen_event_attestation"], "BLOCKED_0_AT_SEQUENCE_94")

    def test_all_public_submission_paths_have_decisions(self) -> None:
        self.assertTrue(self.receipt["checks"]["submission_review_59_of_59"])
        self.assertEqual(self.receipt["metrics"]["reviewed_public_submission_files"], 59)

    def test_registered_sources_do_not_masquerade_as_current_candidate(self) -> None:
        self.assertTrue(self.receipt["checks"]["current_node_candidate_artifact_zero_at_cutoff"])
        self.assertEqual(self.receipt["metrics"]["current_node_candidate_artifacts"], 0)

    def test_route_window_is_explicitly_short(self) -> None:
        self.assertAlmostEqual(self.receipt["metrics"]["route_window_seconds"], 16.218474, places=6)
        self.assertEqual(self.receipt["route_window"]["classification"], "PASS_PLATFORM_PROBE_WINDOW_ONLY")

    def test_authorization_matrix_and_policy_probe_are_separate(self) -> None:
        self.assertEqual(self.receipt["metrics"]["authorization_events"], 31)
        self.assertEqual(self.receipt["metrics"]["iam_probes"], 30)
        self.assertEqual(self.receipt["metrics"]["policy_probe_deny"], 1)

    def test_tampered_snapshot_fails_closed(self) -> None:
        original_snapshot = VERIFY.SNAPSHOT
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temp_dir:
            copied = Path(temp_dir) / VERIFY.SNAPSHOT_ID
            shutil.copytree(original_snapshot, copied)
            events = copied / "events.ndjson"
            events.write_bytes(events.read_bytes() + b"\n")
            VERIFY.SNAPSHOT = copied
            try:
                with self.assertRaisesRegex(AssertionError, "snapshot_mismatch:events.ndjson"):
                    VERIFY.verify()
            finally:
                VERIFY.SNAPSHOT = original_snapshot


if __name__ == "__main__":
    unittest.main()
