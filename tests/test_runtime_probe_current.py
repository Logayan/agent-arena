from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from runtime_probe.delivery import check_manifest, verify
from runtime_probe.gate import evaluate
from runtime_probe.platform import analyze


class CurrentRuntimeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        required_fixtures = (
            cls.root / "evidence/runtime_probe/platform_snapshot/README.md",
            cls.root / "evidence/local-probes/local-probe-proof.json",
        )
        missing = [path.relative_to(cls.root).as_posix() for path in required_fixtures if not path.is_file()]
        if missing:
            raise unittest.SkipTest(
                "external frozen runtime-probe fixtures are not materialized: "
                + ", ".join(missing)
            )
        cls.index = json.loads((cls.root / "evidence/runtime_probe/evidence-index.json").read_text(encoding="utf-8"))
        cls.recalculated = analyze(cls.root / "evidence/runtime_probe/platform_snapshot")
        cls.supplemental = json.loads((cls.root / "evidence/local-probes/local-probe-proof.json").read_text(encoding="utf-8"))

    def test_projection_is_current_frozen_public_safe_scope(self) -> None:
        p = self.index["snapshot"]["projection"]
        self.assertGreaterEqual(p["event_count"], 6003)
        self.assertGreaterEqual(p["sequence_last"], 6015)
        self.assertEqual(1, p["sequence_first"])
        self.assertEqual("public_agent_safe", p["projection"])
        self.assertFalse(p["source_database_verified"])
        self.assertEqual("PASS", p["critical_correspondence"])

    def test_projection_digest_recalculates(self) -> None:
        path = self.root / "evidence/runtime_probe/platform_snapshot/events.ndjson"
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(observed, self.index["snapshot"]["core_files"]["events.ndjson"]["sha256"])
        self.assertEqual(self.index["snapshot"]["projection"]["event_count"], self.recalculated["snapshot"]["projection"]["event_count"])

    def test_runtime_binding_correspondence(self) -> None:
        runtime = self.index["analysis"]["runtime"]
        self.assertEqual("claude_code", runtime["health"]["runtime"])
        self.assertEqual("agent-sdk-bridge", runtime["health"]["mode"])
        self.assertEqual(runtime["binding_count"], runtime["binding_verified_count"])
        self.assertGreaterEqual(runtime["binding_count"], 22)
        self.assertGreaterEqual(runtime["distinct_bound_agents"], 4)
        self.assertEqual(0, runtime["explicit_sdk_session_started_event_count"])

    def test_tool_lifecycle_is_complete_but_native_fields_are_missing(self) -> None:
        tools = self.index["analysis"]["tools"]
        self.assertGreaterEqual(tools["group_count"], 906)
        self.assertEqual(tools["group_count"], tools["complete_four_phase_groups"])
        self.assertEqual(0, tools["incomplete_group_count"])
        self.assertFalse(tools["raw_tool_request_or_result_bytes_available"])
        self.assertEqual(0, sum(tools["native_result_linkage_group_coverage"].values()))

    def test_registered_artifact_bytes_and_partial_lifecycle(self) -> None:
        artifacts = self.index["analysis"]["artifacts"]
        self.assertEqual(38, artifacts["registry_count"])
        self.assertEqual(38, artifacts["byte_verified_count"])
        receipts = json.loads((self.root / "evidence/runtime_probe/platform_snapshot/artifact-byte-receipts.json").read_text(encoding="utf-8"))
        self.assertEqual(38, len(receipts))
        self.assertLess(artifacts["download_verified_count"], artifacts["registry_count"])

    def test_platform_judge_pause_and_terminal_state_fail_closed(self) -> None:
        analysis = self.index["analysis"]
        self.assertEqual(0, analysis["judge"]["event_count"])
        self.assertEqual(0, analysis["pause"]["event_count"])
        self.assertFalse(analysis["recovery"]["terminal_duplicate_effect_reconciliation"])
        self.assertFalse(analysis["recovery"]["run_converged_or_completed"])
        self.assertEqual("running", self.index["snapshot"]["run_metadata"]["status"])

    def test_memory_is_not_overclaimed(self) -> None:
        memory = self.index["analysis"]["memory"]
        self.assertGreaterEqual(memory["committed_count"], 4)
        self.assertFalse(memory["cross_session_roundtrip_proven"])

    def test_primary_candidate_v1_really_rejects_and_is_immutable(self) -> None:
        candidate = self.root / "config/candidate-v1.json"
        before = candidate.read_bytes()
        receipt = evaluate(candidate, self.root / "config/predeclared-blocker.json")
        self.assertEqual(("REJECT", 42), (receipt["verdict"], receipt["exit_code"]))
        self.assertFalse(receipt["acceptance_eligible"])
        self.assertTrue(receipt["not_a_platform_judge_event"])
        self.assertEqual(before, candidate.read_bytes())
        self.assertFalse((self.root / "config/candidate-v2.json").exists())

    def test_supplemental_local_probes_are_real_but_ineligible(self) -> None:
        proof = self.supplemental
        self.assertEqual("PASS_LOCAL_SCOPE", proof["status"])
        self.assertFalse(proof["acceptance_eligible"])
        self.assertGreaterEqual(proof["event_count"], 23)
        self.assertGreaterEqual(proof["commands"], 13)
        self.assertFalse(proof["negative_gate"]["platform_judge_event"])

    def test_supplemental_memory_force_kill_dependency_and_path_boundary(self) -> None:
        proof = self.supplemental
        self.assertTrue(proof["memory"]["distinct_processes"])
        self.assertEqual(77, proof["memory"]["wrong_namespace_exit"])
        self.assertTrue(proof["failure_recovery"]["distinct_processes"])
        self.assertEqual(1, proof["failure_recovery"]["effect_count"])
        self.assertTrue(proof["failure_recovery"]["duplicate_suppressed"])
        self.assertEqual({"first_exit": 69, "retry_exit": 0}, proof["dependency"])
        self.assertEqual(64, proof["file_delivery"]["path_escape_exit"])
        self.assertFalse((self.root / "evidence/local-probes/escape.txt").exists())

    def test_five_role_contract_does_not_invent_platform_identities(self) -> None:
        team = json.loads((self.root / "config/team-roles.json").read_text(encoding="utf-8"))
        self.assertEqual(5, len(team["roles"]))
        self.assertTrue(team["separation_of_duties"])
        self.assertTrue(all(row["platform_identity"] is None for row in team["roles"]))
        self.assertTrue(all(row["status"] == "PENDING_PLATFORM_BINDING" for row in team["roles"]))

    def test_public_submission_rows_have_explicit_decisions(self) -> None:
        review = json.loads((self.root / "evidence/runtime_probe/public-submission-review.json").read_text(encoding="utf-8"))
        summary = review["summary"]
        self.assertEqual(sum(x["change_row_count"] for x in review["submissions"]), summary["manifest_change_row_count"])
        self.assertEqual(summary["manifest_change_row_count"], len(review["reviews"]))
        self.assertEqual(0, summary["byte_audit_mismatch_count"])
        self.assertEqual(summary["non_deleted_row_count"], summary["raw_byte_verified_non_deleted_rows"] + summary["publicly_attested_not_materialized_rows"])
        self.assertTrue(all(row["decision"] for row in review["reviews"]))

    def test_target_schema_remains_a_target_not_observed_conformance(self) -> None:
        schema = json.loads((self.root / "schemas/runtime-evidence-event.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("TARGET_ONLY", schema["x-acceptance-note"]["status"])
        self.assertFalse(schema["x-acceptance-note"]["observed_projection_conforms"])

    def test_cam_and_retirement_remain_fail_closed(self) -> None:
        self.assertEqual(0, self.index["acceptance"]["pass_count"])
        self.assertEqual("NO_GO", self.index["acceptance"]["claude_agent_sdk_full_runtime_migration"])
        self.assertEqual("REJECTED", self.index["acceptance"]["openclaw_retirement"])

    def test_whole_package_verification(self) -> None:
        status = verify(self.root)
        self.assertEqual("PASS_ENGINEERING_NO_GO_MIGRATION", status["status"])
        self.assertEqual("PASS", check_manifest(self.root)["status"])


if __name__ == "__main__":
    unittest.main()
