from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.app import claude_code_runtime as claude_runtime_module
from server.app.agent_runtime import AgentRuntimeError
from server.app.claude_code_runtime import ClaudeCodeRuntime, _bridge_stream_limit_bytes, _configured_max_turns
from server.app.platform_executor import (
    RUNTIME_SOURCE_PATHS,
    _AttemptEvidenceBundleCache,
    _active_memory_items_for_actor,
    _agent_timeout_seconds,
    _apply_run_execution_policy_amendments,
    _artifact_authority_manifest,
    _attempt_rework_attempt_id,
    _attempt_rework_run_id,
    _code_manifest,
    _compact_tool_recovery_history,
    _completed_node_progress,
    _event_snapshot_metadata,
    _next_timeout_retry_level,
    _normalized_max_revision_rounds,
    _remember_next_timeout_retry_level,
    _artifact_creation_provenance,
    _gather_cancel_on_error,
    _interrupted_tool_calls,
    _public_event_projection,
    _public_event_projection_omission,
    _product_workspace_changes,
    _resolve_gate_targets,
    _recover_public_text_from_file_changes,
    _runtime_attestation,
    _runtime_mode,
    _runtime_source_attestation,
    _sdk_session_continuation_payload,
    _revision_limit_exhausted,
    _ensure_runtime_source_artifacts,
    _runtime_tool_authorization_matrix,
    _runtime_tool_enabled_agent_ids,
    _run_time_limit_enabled,
    _tool_schema_validation,
    _tool_schema_authorization_decision,
    _tool_terminal_reconciliations,
    _write_public_event_snapshot,
    _release_run_execution_lease,
    _try_acquire_run_execution_lease,
    _upstream_gate_targets,
)
from server.app.platform_store import PlatformStore
from server.app.run_budget import active_execution_epoch_seconds, active_run_seconds, configured_maximum_run_minutes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_parallel_runtime_failure_cancels_sibling() -> None:
    sibling_cancelled = asyncio.Event()

    async def fail() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("primary failure")

    async def sibling() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            sibling_cancelled.set()
            raise

    with pytest.raises(RuntimeError, match="primary failure"):
        await _gather_cancel_on_error(fail(), sibling())

    assert sibling_cancelled.is_set()


def test_code_manifest_excludes_platform_evidence_tree(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    source = candidate / "server" / "app.py"
    evidence = candidate / ".jianghu-platform-evidence" / "snapshots" / "attempt-current" / "events.ndjson"
    source.parent.mkdir(parents=True)
    evidence.parent.mkdir(parents=True)
    source.write_text("print('candidate')\n", encoding="utf-8")
    evidence.write_bytes(b"platform evidence must not be hashed as candidate code\n" * 1000)

    manifest = _code_manifest(candidate)

    assert [item["path"] for item in manifest] == ["server/app.py"]


def test_product_promotion_keeps_source_changes_and_excludes_generated_evidence() -> None:
    changes = [
        {"path": "server/app/runtime.py", "action": "modified"},
        {"path": "client/e2e/runtime.spec.mjs", "action": "created"},
        {"path": "evidence/run/trace.zip", "action": "created"},
        {"path": "artifacts/package.zip", "action": "created"},
        {"path": ".playwright-browsers/chromium/chrome.exe", "action": "created"},
        {"path": "t/pytest-of-agent/result.xml", "action": "created"},
    ]

    assert _product_workspace_changes(changes) == changes[:2]


def test_empty_public_text_recovers_only_from_same_turn_real_files(tmp_path: Path) -> None:
    delivery = tmp_path / "delivery"
    report = delivery / "reports" / "迁移验收报告.md"
    report.parent.mkdir(parents=True)
    report.write_text("# 迁移验收报告\n\n结论：NO_GO，仍有 16 个真实缺口。\n", encoding="utf-8")
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    response = {
        "content": [{"type": "text", "text": ""}],
        "recorded_file_changes": [
            {
                "action": "created",
                "path": "reports/迁移验收报告.md",
                "sha256": digest,
                "size_bytes": report.stat().st_size,
            }
        ],
    }

    recovered, receipt = _recover_public_text_from_file_changes(
        response,
        promoted_root=delivery,
        node_name="迁移验收报告与缺口清单封版",
        phase="团队合议与正式提交",
    )

    assert "NO_GO" in recovered
    assert "16 个真实缺口" in recovered
    assert "reports/迁移验收报告.md" in recovered
    assert receipt is not None
    assert receipt["recovery_source"] == "same_sdk_turn_promoted_files"
    assert receipt["files"][0]["sha256"] == digest


def test_empty_public_text_is_not_fabricated_without_real_files(tmp_path: Path) -> None:
    recovered, receipt = _recover_public_text_from_file_changes(
        {"content": [{"type": "text", "text": ""}], "recorded_file_changes": []},
        promoted_root=tmp_path,
        node_name="封版",
        phase="团队合议与正式提交",
    )

    assert recovered == ""
    assert receipt is None


@pytest.mark.anyio
async def test_attempt_evidence_bundle_is_built_once_for_parallel_team_members(
    tmp_path: Path,
) -> None:
    cache = _AttemptEvidenceBundleCache()
    build_count = 0
    bundle = tmp_path / "evidence" / "attempt-1"

    async def build() -> Path:
        nonlocal build_count
        build_count += 1
        await asyncio.sleep(0.02)
        bundle.mkdir(parents=True, exist_ok=True)
        return bundle

    paths = await asyncio.gather(
        *(cache.get_or_create("attempt-1", build) for _ in range(5))
    )

    assert paths == [bundle] * 5
    assert build_count == 1


@pytest.mark.anyio
async def test_attempt_evidence_bundle_keeps_distinct_attempt_snapshots(
    tmp_path: Path,
) -> None:
    cache = _AttemptEvidenceBundleCache()
    build_count = 0

    async def build() -> Path:
        nonlocal build_count
        build_count += 1
        path = tmp_path / f"attempt-{build_count}"
        path.mkdir()
        return path

    first = await cache.get_or_create("attempt-1", build)
    second = await cache.get_or_create("attempt-2", build)

    assert first != second
    assert build_count == 2


def test_claude_turn_limit_is_opt_in_and_not_silently_bounded(monkeypatch) -> None:
    monkeypatch.delenv("JIANGHU_CLAUDE_MAX_TURNS", raising=False)
    assert _configured_max_turns(False) is None
    assert _configured_max_turns(True) is None

    monkeypatch.setenv("JIANGHU_CLAUDE_MAX_TURNS", "64")
    assert _configured_max_turns(True) == 64
    monkeypatch.setenv("JIANGHU_CLAUDE_MAX_TURNS", "999")
    assert _configured_max_turns(True) == 999
    monkeypatch.setenv("JIANGHU_CLAUDE_MAX_TURNS", "0")
    assert _configured_max_turns(True) is None
    monkeypatch.setenv("JIANGHU_CLAUDE_MAX_TURNS", "invalid")
    assert _configured_max_turns(True) is None


def test_claude_bridge_stream_limit_supports_large_ndjson_events(monkeypatch) -> None:
    monkeypatch.delenv("JIANGHU_CLAUDE_STREAM_LIMIT_BYTES", raising=False)
    assert _bridge_stream_limit_bytes() == 8 * 1024 * 1024

    monkeypatch.setenv("JIANGHU_CLAUDE_STREAM_LIMIT_BYTES", str(12 * 1024 * 1024))
    assert _bridge_stream_limit_bytes() == 12 * 1024 * 1024
    monkeypatch.setenv("JIANGHU_CLAUDE_STREAM_LIMIT_BYTES", "999999999")
    assert _bridge_stream_limit_bytes() == 16 * 1024 * 1024
    monkeypatch.setenv("JIANGHU_CLAUDE_STREAM_LIMIT_BYTES", "1024")
    assert _bridge_stream_limit_bytes() == 1024 * 1024


def test_sdk_session_continuation_payload_requires_the_same_real_sdk_session() -> None:
    continued = _sdk_session_continuation_payload(
        execution_epoch=44,
        agent_id="agent-1",
        platform_session_id="session-1",
        first_sdk_session_id="sdk-1",
        second_sdk_session_id="sdk-1",
    )
    mismatched = _sdk_session_continuation_payload(
        execution_epoch=44,
        agent_id="agent-1",
        platform_session_id="session-1",
        first_sdk_session_id="sdk-1",
        second_sdk_session_id="sdk-2",
    )

    assert continued["status"] == "continued"
    assert continued["strict_sdk_session"] is True
    assert continued["claude_sdk_session_id"] == "sdk-1"
    assert continued["terminal"] is True
    assert mismatched["status"] == "mismatched"
    assert mismatched["strict_sdk_session"] is False


def test_runtime_turn_refreshes_active_memory_after_superseding_old_version(tmp_path: Path) -> None:
    platform = PlatformStore(str(tmp_path / "memory-refresh.db"))
    agent = platform.create_agent(
        name="记忆刷新工程师",
        role="工程师",
        description="验证每回合读取当前活动 Memory",
        persona="不使用墓碑版本",
        capabilities=["Memory"],
    )
    old = platform.add_agent_memory(
        agent["id"],
        kind="task_experience",
        title="旧版本",
        content="old",
        source_run_id="run-1",
        source_task_id="task-1",
    )
    stale_epoch_cache = platform.list_agent_memories(agent["id"], 8)
    new = platform.add_agent_memory(
        agent["id"],
        kind="task_experience",
        title="新版本",
        content="new",
        source_run_id="run-1",
        source_task_id="task-1",
    )

    refreshed = _active_memory_items_for_actor(platform, agent)

    assert [item["id"] for item in stale_epoch_cache] == [old["id"]]
    assert [item["id"] for item in refreshed] == [new["id"]]
    assert old["id"] not in {item["id"] for item in refreshed}


def test_artifact_authority_manifest_is_order_independent() -> None:
    artifacts = [
        {
            "id": "artifact-b", "kind": "runtime_file", "title": "result.json", "version": 2,
            "relative_path": "artifacts/node/files/result.json", "sha256": "b" * 64, "size_bytes": 20,
        },
        {
            "id": "artifact-a", "kind": "workflow_output", "title": "结果", "version": 1,
            "relative_path": "artifacts/node/result.md", "sha256": "a" * 64, "size_bytes": 10,
        },
    ]

    first = _artifact_authority_manifest(
        run_id="run-1", task_id="task-1", node_key="node", platform_attempt_id="attempt-1",
        artifacts=artifacts,
    )
    second = _artifact_authority_manifest(
        run_id="run-1", task_id="task-1", node_key="node", platform_attempt_id="attempt-1",
        artifacts=[*reversed(artifacts), artifacts[0]],
    )

    assert first == second
    assert [item["artifact_id"] for item in first["artifacts"]] == ["artifact-a", "artifact-b"]
    assert len(first["manifest_sha256"]) == 64


def test_task_artifact_authority_replaces_prior_set_without_deleting_history(tmp_path: Path) -> None:
    platform = PlatformStore(str(tmp_path / "artifact-authority.db"))
    agent = platform.create_agent(
        name="权威集合审计", role="质量工程师", description="验证 Artifact authority", persona="保留历史",
        capabilities=["证据归档"],
    )
    workflow = platform.create_workflow(
        "权威集合章法", "冻结当前成功 Attempt", "test",
        {"nodes": [{"key": "evidence", "name": "证据", "agent_id": agent["id"]}], "edges": []},
    )
    run = platform.create_run(workflow["id"], "验证权威集合替换")
    task = platform.get_run_execution_snapshot(run["id"], include_events=False)["tasks"][0]
    first = platform.create_artifact(run["id"], task["id"], "workflow_output", "第一版", "one")
    first_file = platform.create_artifact(
        run["id"], task["id"], "runtime_file", "first.json", "{}", supersede_candidates=False,
    )

    initial = platform.mark_task_artifacts_authoritative(
        run["id"], task["id"], [first_file["id"], first["id"]],
    )
    second = platform.create_artifact(
        run["id"], task["id"], "workflow_output", "第二版", "two", supersede_candidates=False,
    )
    replacement = platform.mark_task_artifacts_authoritative(run["id"], task["id"], [second["id"]])
    rows = {item["id"]: item for item in platform.list_run_artifacts(run["id"])}

    assert {item["id"] for item in initial["authoritative"]} == {first["id"], first_file["id"]}
    assert {item["id"] for item in replacement["superseded"]} == {first["id"], first_file["id"]}
    assert rows[first["id"]]["status"] == "superseded"
    assert rows[first_file["id"]]["status"] == "superseded"
    assert rows[second["id"]]["status"] == "authoritative"
    assert platform.verify_artifact_bytes(run["id"], first["id"])["matched"] is True


def test_invalid_tool_schema_is_denied_before_execution_projection() -> None:
    valid = _tool_schema_validation("Bash", {"command": "pwd"})
    invalid = _tool_schema_validation("Bash", {})

    assert valid["passed"] is True
    assert _tool_schema_authorization_decision(valid) == "allow"
    assert invalid["passed"] is False
    assert invalid["missing_fields"] == ["command"]
    assert _tool_schema_authorization_decision(invalid) == "deny"


def test_agent_timeout_is_configurable_and_bounded(monkeypatch) -> None:
    monkeypatch.delenv("JIANGHU_AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("JIANGHU_AGENT_TIMEOUT_MAX_SECONDS", raising=False)
    monkeypatch.delenv("JIANGHU_AGENT_TIMEOUT_RETRY_MULTIPLIER", raising=False)
    assert _agent_timeout_seconds(False) == 600
    assert _agent_timeout_seconds(True) == 1800
    assert _agent_timeout_seconds(True, 1) == 3600
    assert _agent_timeout_seconds(True, 2) == 7200
    assert _agent_timeout_seconds(True, 3) == 14400
    assert _agent_timeout_seconds(True, 4) == 14400

    monkeypatch.setenv("JIANGHU_AGENT_TIMEOUT_SECONDS", "1200")
    assert _agent_timeout_seconds(True) == 1200
    assert _agent_timeout_seconds(True, 1) == 2400
    monkeypatch.setenv("JIANGHU_AGENT_TIMEOUT_SECONDS", "99999")
    assert _agent_timeout_seconds(True) == 14400

    monkeypatch.setenv("JIANGHU_AGENT_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("JIANGHU_AGENT_TIMEOUT_MAX_SECONDS", "7200")
    monkeypatch.setenv("JIANGHU_AGENT_TIMEOUT_RETRY_MULTIPLIER", "2")
    assert _agent_timeout_seconds(True) == 1800
    assert _agent_timeout_seconds(True, 1) == 3600
    assert _agent_timeout_seconds(True, 2) == 7200


def test_node_retry_continues_after_the_timeout_tier_consumed_by_agent_retry() -> None:
    error = AgentRuntimeError("claude_timeout:3600s", category="timeout", retryable=True)
    _remember_next_timeout_retry_level(error, 2)

    assert _next_timeout_retry_level(error, 0) == 2


def test_node_retry_advances_one_timeout_tier_without_carried_state() -> None:
    error = AgentRuntimeError("claude_timeout:1800s", category="timeout", retryable=True)

    assert _next_timeout_retry_level(error, 0) == 1


@pytest.mark.parametrize("category", ["network", "authentication", "configuration", "runtime_failure"])
def test_node_retry_does_not_extend_timeout_for_non_timeout_failures(category: str) -> None:
    error = AgentRuntimeError("not a timeout", category=category, retryable=True)

    assert _next_timeout_retry_level(error, 2) == 2


def test_run_execution_lease_allows_only_one_local_worker(tmp_path) -> None:
    store = PlatformStore(str(tmp_path / "lease.db"))
    first = _try_acquire_run_execution_lease(store, "run_same")
    assert first is not None

    try:
        assert _try_acquire_run_execution_lease(store, "run_same") is None
    finally:
        _release_run_execution_lease(first)

    replacement = _try_acquire_run_execution_lease(store, "run_same")
    assert replacement is not None
    _release_run_execution_lease(replacement)


def test_maximum_run_minutes_is_configurable_and_bounded(monkeypatch) -> None:
    monkeypatch.delenv("JIANGHU_MAX_RUN_MINUTES", raising=False)
    assert configured_maximum_run_minutes() == 360
    monkeypatch.setenv("JIANGHU_MAX_RUN_MINUTES", "720")
    assert configured_maximum_run_minutes() == 720
    monkeypatch.setenv("JIANGHU_MAX_RUN_MINUTES", "9999")
    assert configured_maximum_run_minutes() == 1440
    monkeypatch.setenv("JIANGHU_MAX_RUN_MINUTES", "invalid")
    assert configured_maximum_run_minutes() == 360


def test_active_run_time_excludes_pause_and_budget_intervention_waits() -> None:
    events = [
        {"sequence": 1, "type": "run.started", "created_at": "2026-09-12T00:00:00+00:00"},
        {"sequence": 2, "type": "run.pause_requested", "created_at": "2026-09-12T00:10:00+00:00"},
        {"sequence": 3, "type": "run.paused", "created_at": "2026-09-12T00:40:00+00:00"},
        {"sequence": 4, "type": "run.resumed", "created_at": "2026-09-12T01:00:00+00:00"},
        {"sequence": 5, "type": "run.budget_exhausted", "created_at": "2026-09-12T01:20:00+00:00"},
        {"sequence": 6, "type": "run.time_extended", "created_at": "2026-09-12T02:00:00+00:00"},
    ]
    now = datetime(2026, 9, 12, 2, 30, tzinfo=timezone.utc)
    assert active_run_seconds(events, now=now) == 60 * 60


def test_recovery_epoch_gets_fresh_window_without_erasing_total_active_time() -> None:
    events = [
        {"sequence": 1, "type": "run.started", "created_at": "2026-09-12T00:00:00+00:00"},
        {"sequence": 2, "type": "run.failed", "created_at": "2026-09-12T03:00:00+00:00"},
        {"sequence": 3, "type": "run.recovery_requested", "created_at": "2026-09-12T04:00:00+00:00"},
        {"sequence": 4, "type": "run.recovered", "created_at": "2026-09-12T04:00:10+00:00"},
    ]
    now = datetime(2026, 9, 12, 4, 30, 10, tzinfo=timezone.utc)

    assert active_run_seconds(events, now=now) == 3.5 * 60 * 60
    assert active_execution_epoch_seconds(events, now=now) == 30 * 60


def test_run_time_limit_is_disabled_by_default_and_requires_explicit_opt_in() -> None:
    assert _run_time_limit_enabled({}) is False
    assert _run_time_limit_enabled({"max_run_minutes": 180}) is False
    assert _run_time_limit_enabled({"enforce_run_time_limit": False, "max_run_minutes": 180}) is False
    assert _run_time_limit_enabled({"enforce_run_time_limit": True, "max_run_minutes": 180}) is True


def test_queued_recovery_has_not_consumed_its_new_execution_window() -> None:
    events = [
        {"sequence": 1, "type": "run.started", "created_at": "2026-09-12T00:00:00+00:00"},
        {"sequence": 2, "type": "run.failed", "created_at": "2026-09-12T03:00:00+00:00"},
        {"sequence": 3, "type": "run.recovery_requested", "created_at": "2026-09-12T04:00:00+00:00"},
    ]
    now = datetime(2026, 9, 12, 5, 0, tzinfo=timezone.utc)

    assert active_execution_epoch_seconds(events, now=now) == 0


def test_interrupted_tool_scan_only_returns_started_calls_without_terminal_receipts() -> None:
    events = [
        {
            "id": "evt-auth",
            "sequence": 1,
            "type": "agent.tool.authorization.decided",
            "payload": {"tool_call_id": "call-orphan", "operation_id": "op-1", "tool_name": "Bash"},
        },
        {
            "id": "evt-start",
            "sequence": 2,
            "type": "agent.tool.started",
            "payload": {"tool_call_id": "call-orphan", "platform_session_id": "session-1"},
        },
        {
            "id": "evt-command",
            "sequence": 3,
            "type": "agent.command.started",
            "payload": {"tool_call_id": "call-orphan", "command": "python verify.py"},
        },
        {
            "id": "evt-start-complete",
            "sequence": 4,
            "type": "agent.tool.started",
            "payload": {"tool_call_id": "call-complete"},
        },
        {
            "id": "evt-complete",
            "sequence": 5,
            "type": "agent.tool.completed",
            "payload": {"tool_call_id": "call-complete", "status": "completed"},
        },
    ]
    interrupted = _interrupted_tool_calls(events)
    assert interrupted == [
        {
            "tool_call_id": "call-orphan",
            "operation_id": "op-1",
            "tool_name": "Bash",
            "platform_session_id": "session-1",
            "source_event_id": "evt-start",
            "source_event_sequence": 2,
            "command": "python verify.py",
        }
    ]


def test_runtime_mode_comes_from_adapter_health() -> None:
    class Runtime:
        @staticmethod
        def health() -> dict[str, str]:
            return {"mode": "agent-sdk-bridge"}

    assert _runtime_mode(Runtime()) == "agent-sdk-bridge"


def test_judge_engineering_and_evidence_audit_agents_receive_runtime_tools() -> None:
    agents = {
        "engineer": {"id": "engineer", "role": "后端工程师"},
        "judge": {"id": "judge", "role": "独立裁判"},
        "quality": {"id": "quality", "role": "质量工程师"},
        "risk": {"id": "risk", "role": "安全与风险审计师"},
        "writer": {"id": "writer", "role": "文案"},
    }
    nodes = {
        "build": {
            "key": "build",
            "name": "后端开发",
            "type": "team_task",
            "agent_id": "engineer",
            "participant_agent_ids": ["engineer"],
        },
        "judge": {
            "key": "judge",
            "name": "独立验收",
            "type": "judge",
            "agent_id": "judge",
            "participant_agent_ids": ["judge"],
        },
        "audit": {
            "key": "independent_quality_audit",
            "name": "运行证据独立质量与风险审计",
            "purpose": "核验原始事件、文件实体、内容哈希和 Artifact 回执。",
            "type": "team_task",
            "agent_id": "quality",
            "participant_agent_ids": ["quality", "risk"],
        },
        "write": {
            "key": "write",
            "name": "产品说明",
            "type": "team_task",
            "agent_id": "writer",
            "participant_agent_ids": ["writer"],
            "execution_mode": "document",
        },
    }

    enabled = _runtime_tool_enabled_agent_ids(nodes, agents.get)

    assert enabled == {"engineer", "judge", "quality", "risk"}


def test_runtime_tool_policy_can_explicitly_disable_keyword_inference() -> None:
    node = {
        "key": "evidence_summary",
        "name": "证据摘要",
        "purpose": "只阅读注入摘要，不访问工作区。",
        "type": "team_task",
        "agent_id": "writer",
        "participant_agent_ids": ["writer"],
        "requires_runtime_tools": False,
    }

    assert _runtime_tool_enabled_agent_ids({"summary": node}, lambda _agent_id: {"role": "文案"}) == set()


def test_runtime_tool_authorization_matrix_covers_positive_negative_roles_and_forbidden_tool() -> None:
    matrix = _runtime_tool_authorization_matrix(
        {
            "engineer": {"id": "engineer", "role": "工程师"},
            "reviewer": {"id": "reviewer", "role": "审计员"},
        },
        {"engineer"},
        7,
    )

    assert len(matrix) == 10
    decisions = {(item["agent_id"], item["tool_name"]): item["authorization_decision"] for item in matrix}
    assert decisions[("engineer", "Write")] == "allow"
    assert decisions[("reviewer", "Write")] == "deny"
    assert decisions[("engineer", "OpenClawGateway")] == "deny"
    assert all(item["authorization_policy_version"] == "1.0.0" for item in matrix)
    assert all(item["side_effect_status"] == "not_started" for item in matrix)


def test_public_event_projection_keeps_evidence_ids_but_excludes_private_audit() -> None:
    public = _public_event_projection(
        {
            "id": "evt_gate_42",
            "run_id": "run_42",
            "organization_id": "org_jianghu",
            "sequence": 42,
            "type": "gate.rejected",
            "category": "judge",
            "title": "退回",
            "summary": "必须返工",
            "payload": {"node_key": "audit", "decision": {"verdict": "revise", "score": 42}},
            "created_at": "2026-09-12T00:00:00+00:00",
        }
    )
    private = _public_event_projection(
        {
            "sequence": 43,
            "type": "agent.rationale.submitted",
            "category": "private_audit",
            "payload": {"content": "private"},
        }
    )

    assert public is not None
    assert public["event_id"] == "evt_gate_42"
    assert public["run_id"] == "run_42"
    assert public["sequence"] == 42
    assert public["payload"]["decision"] == {"verdict": "revise", "score": 42}
    assert len(public["source_event_sha256"]) == 64
    assert private is None
    omission = _public_event_projection_omission(
        {
            "id": "evt_private_43",
            "run_id": "run_42",
            "organization_id": "org_jianghu",
            "sequence": 43,
            "type": "agent.rationale.submitted",
            "category": "private_audit",
            "payload": {"content": "private"},
        }
    )
    assert omission is not None
    assert omission["sequence"] == 43
    assert omission["projection_status"] == "omitted"
    assert omission["reason_code"] == "private_audit_not_shared_with_agents"
    assert omission["policy_version"] == "1.0.0"
    assert len(omission["source_event_sha256"]) == 64


def test_public_event_snapshot_streams_valid_files_and_keeps_snapshot_bounded(tmp_path: Path) -> None:
    platform = PlatformStore(str(tmp_path / "streamed-evidence.db"))
    agent = platform.create_agent(
        name="流式证据工程师",
        role="质量工程师",
        description="验证长 Run 证据按批写出",
        persona="只保留必要的 Runtime 绑定集合",
        capabilities=["证据归档"],
    )
    workflow = platform.create_workflow(
        "流式证据章法",
        "不在内存拼接整个事件历史",
        "test",
        {"nodes": [{"key": "evidence", "name": "证据", "agent_id": agent["id"]}], "edges": []},
    )
    run = platform.create_run(workflow["id"], "验证流式证据包")
    platform.append_run_event(
        run["id"], "gate.rejected", "judge", "退回", "需要补证",
        {"node_key": "evidence", "decision": {"verdict": "revise"}},
    )
    platform.append_run_event(
        run["id"], "agent.rationale.submitted", "private_audit", "私有思考", "不公开",
        {"content": "private"},
    )
    platform.append_run_event(
        run["id"], "agent.turn.completed", "runtime", "人物回合完成", "Claude SDK 已返回",
        {
            "agent_id": agent["id"],
            "node_key": "evidence",
            "session_key": "session:streamed",
            "runtime": {"session_id": "claude-session-streamed", "model": "gpt-5.6-sol", "runtime": "claude_code"},
        },
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = _write_public_event_snapshot(platform, run["id"], bundle)
    public_events = [json.loads(line) for line in (bundle / "events.ndjson").read_text(encoding="utf-8").splitlines()]
    critical_events = json.loads((bundle / "critical-events.json").read_text(encoding="utf-8"))
    omissions = json.loads((bundle / "projection-omissions.json").read_text(encoding="utf-8"))
    bounded = platform.get_run_execution_snapshot(run["id"], include_events=False)

    assert result["projection_count"] == len(public_events)
    assert result["critical_count"] == len(critical_events)
    assert result["omission_count"] == 1
    assert result["source_event_count"] == len(public_events) + omissions["omission_count"]
    assert result["cutoff_sequence"] == max(
        [event["sequence"] for event in public_events]
        + [item["sequence"] for item in omissions["omissions"]]
    )
    assert omissions["omission_count"] == 1
    assert omissions["omissions"][0]["reason_code"] == "private_audit_not_shared_with_agents"
    assert all(event["type"] != "agent.rationale.submitted" for event in public_events)
    assert result["runtime_binding_projections"][0]["type"] == "agent.turn.completed"
    assert bounded is not None and bounded["events"] == []
    assert bounded["event_count_total"] == len(public_events) + omissions["omission_count"]
    assert not list(bundle.glob("*.tmp"))


def test_event_snapshot_metadata_uses_one_frozen_count_contract() -> None:
    metadata = _event_snapshot_metadata(
        {
            "projection_count": 162_751,
            "omission_count": 91,
            "source_event_count": 162_842,
            "first_event_sequence": 1,
            "cutoff_sequence": 162_842,
            "event_snapshot_coherent": True,
            "event_snapshot_boundary_rule": "same_connection_max_sequence_then_sequence_lte_frozen_cutoff",
        }
    )

    assert metadata == {
        "event_count": 162_842,
        "source_event_count": 162_842,
        "public_event_count": 162_751,
        "omitted_event_count": 91,
        "first_event_sequence": 1,
        "cutoff_sequence": 162_842,
        "event_snapshot_coherent": True,
        "event_snapshot_boundary_rule": "same_connection_max_sequence_then_sequence_lte_frozen_cutoff",
    }


def test_compact_event_queries_preserve_order_and_latest_boundary(tmp_path: Path) -> None:
    platform = PlatformStore(str(tmp_path / "compact-event-history.db"))
    agent = platform.create_agent(
        name="轻量历史审计", role="质量工程师", description="验证执行器不加载整条 Run", persona="只读必要事件",
        capabilities=["恢复审计"],
    )
    workflow = platform.create_workflow(
        "轻量历史章法", "按类型读取控制历史", "test",
        {"nodes": [{"key": "audit", "name": "审计", "agent_id": agent["id"]}], "edges": []},
    )
    run = platform.create_run(workflow["id"], "验证轻量事件历史")
    platform.append_run_event(run["id"], "agent.tool.completed", "runtime", "工具完成", "大载荷", {"blob": "x" * 10000})
    platform.append_run_event(run["id"], "gate.rejected", "judge", "退回", "需要整改", {"node_key": "audit"})
    platform.append_run_event(
        run["id"], "workflow.execution_policy.amended", "intervention", "策略修订", "无限返工", {"max_revision_rounds": 0}
    )

    selected = platform.list_run_events_by_types(
        run["id"], ("gate.rejected", "workflow.execution_policy.amended")
    )

    assert [item["type"] for item in selected] == [
        "gate.rejected", "workflow.execution_policy.amended",
    ]
    assert platform.get_run_latest_event_sequence(run["id"]) == selected[-1]["sequence"]
    assert all(item["type"] != "agent.tool.completed" for item in selected)


def test_tool_recovery_history_discards_large_outputs_but_keeps_identity(tmp_path: Path) -> None:
    platform = PlatformStore(str(tmp_path / "compact-tool-recovery.db"))
    agent = platform.create_agent(
        name="恢复去重审计", role="质量工程师", description="验证 Tool 历史轻量化", persona="保留身份与终态",
        capabilities=["恢复审计"],
    )
    workflow = platform.create_workflow(
        "恢复去重章法", "不把大输出长期留在执行器内存", "test",
        {"nodes": [{"key": "audit", "name": "审计", "agent_id": agent["id"]}], "edges": []},
    )
    run = platform.create_run(workflow["id"], "验证 Tool 恢复历史")
    platform.append_run_event(
        run["id"], "agent.tool.completed", "tool", "工具完成", "输出已留在原事件",
        {
            "agent_id": agent["id"], "platform_session_id": "session-1",
            "tool_call_id": "call-1", "tool_name": "Bash", "status": "completed",
            "exit_code": 0, "stdout": "x" * 1_000_000, "result": {"blob": "y" * 1_000_000},
        },
    )

    compact = _compact_tool_recovery_history(platform, run["id"])

    assert len(compact) == 1
    assert compact[0]["payload"] == {
        "agent_id": agent["id"], "platform_session_id": "session-1",
        "tool_call_id": "call-1", "tool_name": "Bash", "status": "completed",
        "exit_code": 0,
    }


def test_public_event_projection_keeps_runtime_recovery_and_memory_machine_evidence() -> None:
    payload = {
        "entrypoint": "retry",
        "entrypoint_id": "agent-runtime:retry",
        "business_invocation_id": "invocation:run_42:epoch2:retry",
        "openclaw_traffic_count": 0,
        "claude_writer_count": 1,
        "dual_write_count": 0,
        "silent_fallback_count": 0,
        "disposition": "resolved_by_retry",
        "resolved_by_event_id": "evt_success",
        "canonical_event_id": "evt_success",
        "superseded_event_ids": ["evt_failed"],
        "duplicate_count": 1,
        "write_count": 1,
        "terminal": True,
        "superseded_memory_id": "memory_old",
        "superseded_by_memory_id": "memory_new",
        "first_sdk_session_id": "sdk_1",
        "second_sdk_session_id": "sdk_2",
        "revoked_by_lease_id": "lease_new",
        "revoked_by_worker_id": "worker_new",
    }
    projection = _public_event_projection(
        {
            "id": "evt_machine",
            "run_id": "run_42",
            "sequence": 50,
            "type": "runtime.entrypoint.routed",
            "category": "validation",
            "title": "retry routed",
            "summary": "machine evidence",
            "payload": payload,
        }
    )

    assert projection is not None
    assert projection["payload"] == payload


def test_same_run_attempt_rework_lineage_does_not_point_to_parent_run() -> None:
    prior_attempt = {
        "id": "evt_attempt",
        "run_id": "run_current",
        "payload": {"platform_attempt_id": "attempt:run_current:work:epoch30:loop1:node1"},
    }

    assert _attempt_rework_run_id(
        "run_current", {"parent_run_id": "run_parent"}, prior_attempt, 2
    ) == "run_current"
    # A same-Run recovery starts a new execution epoch and therefore resets
    # loop_round to 1.  Its lineage must still follow the prior current-Run
    # Attempt instead of incorrectly jumping back to the parent Run.
    assert _attempt_rework_run_id(
        "run_current", {"parent_run_id": "run_parent"}, prior_attempt, 1
    ) == "run_current"
    assert _attempt_rework_run_id(
        "run_current", {"parent_run_id": "run_parent"}, None, 1
    ) == "run_parent"
    assert _attempt_rework_attempt_id(prior_attempt) == (
        "attempt:run_current:work:epoch30:loop1:node1"
    )
    assert _attempt_rework_attempt_id(None) is None


def test_run_local_policy_amendment_changes_participants_without_new_workflow_version() -> None:
    run = {
        "events": [
            {
                "sequence": 10,
                "type": "workflow.execution_policy.amended",
                "payload": {
                    "node_key": "final_report",
                    "participant_agent_ids": ["architect", "product", "quality", "engineer", "risk"],
                    "max_revision_rounds": 6,
                },
            }
        ]
    }
    nodes, policies = _apply_run_execution_policy_amendments(
        run,
        {"final_report": {"key": "final_report", "participant_agent_ids": ["product", "quality"]}},
        {"max_revision_rounds": 3},
    )

    assert nodes["final_report"]["participant_agent_ids"] == [
        "architect", "product", "quality", "engineer", "risk"
    ]
    assert policies["max_revision_rounds"] == 6


def test_run_local_policy_amendment_supports_auditable_unbounded_revision_loop() -> None:
    run = {
        "events": [
            {
                "sequence": 11,
                "type": "workflow.execution_policy.amended",
                "payload": {
                    "node_key": "final_report",
                    "max_revision_rounds": 0,
                },
            }
        ]
    }

    _, policies = _apply_run_execution_policy_amendments(
        run,
        {"final_report": {"key": "final_report"}},
        {"max_revision_rounds": 3},
    )

    assert policies["max_revision_rounds"] == 0
    assert _normalized_max_revision_rounds(0) == 0
    assert _revision_limit_exhausted(6, 0) is False
    assert _revision_limit_exhausted(600, 0) is False


def test_positive_revision_policy_is_not_silently_capped_at_six() -> None:
    assert _normalized_max_revision_rounds(12) == 12
    assert _revision_limit_exhausted(12, 12) is False
    assert _revision_limit_exhausted(13, 12) is True
    assert _normalized_max_revision_rounds(None) == 3
    assert _normalized_max_revision_rounds("invalid") == 3


def test_completed_node_progress_drops_when_rework_invalidates_three_nodes() -> None:
    tasks = [{"node_key": f"node-{index}"} for index in range(10)]

    assert _completed_node_progress({f"node-{index}" for index in range(9)}, tasks) == 90
    assert _completed_node_progress({f"node-{index}" for index in range(7)}, tasks) == 70


def test_final_judge_can_route_rework_to_transitive_fact_changing_ancestor() -> None:
    dependencies = {
        "quality_audit": set(),
        "remediation_rerun": {"quality_audit"},
        "final_report": {"remediation_rerun", "quality_audit"},
        "final_judge": {"final_report"},
    }
    task_keys = set(dependencies)
    definitions = {
        "remediation_rerun": {
            "key": "remediation_rerun",
            "name": "缺陷整改与真实产品重跑",
            "purpose": "修改源码、Runtime 与 E2E 后重新验证",
            "type": "team_task",
        },
        "final_report": {
            "key": "final_report",
            "name": "验收报告封版",
            "purpose": "汇总报告和缺口清单",
            "type": "team_task",
        },
    }

    assert _upstream_gate_targets("final_judge", dependencies, task_keys) == {
        "quality_audit", "remediation_rerun", "final_report",
    }
    assert _resolve_gate_targets(
        "final_judge",
        {"verdict": "revise", "target_node_keys": ["final_report"]},
        dependencies,
        task_keys,
        definitions,
    ) == {"final_report", "remediation_rerun"}


def test_gate_rework_rejects_non_upstream_target_and_prefers_remediation() -> None:
    dependencies = {
        "audit": set(),
        "remediation_rerun": {"audit"},
        "final_report": {"remediation_rerun"},
        "final_judge": {"final_report"},
        "unrelated": set(),
    }
    definitions = {
        "remediation_rerun": {"key": "remediation_rerun", "name": "整改重跑"},
        "final_report": {"key": "final_report", "name": "报告封版"},
    }

    assert _resolve_gate_targets(
        "final_judge",
        {"verdict": "revise", "target_node_keys": ["unrelated"]},
        dependencies,
        set(dependencies),
        definitions,
    ) == {"remediation_rerun"}


def test_tool_schema_receipt_and_terminal_reconciliation_are_machine_complete() -> None:
    schema = _tool_schema_validation("Read", {"path": "README.md"})
    assert schema["passed"] is True
    assert schema["schema_version"] == "1.0.0"
    assert schema["input_schema"]["schema_id"] == schema["schema_id"]
    assert len(schema["schema_sha256"]) == 64
    assert len(schema["arguments_sha256"]) == 64

    reconciliations = _tool_terminal_reconciliations(
        [
            {
                "id": "evt_failed",
                "sequence": 1,
                "type": "agent.tool.completed",
                "payload": {
                    "agent_id": "agent_1", "platform_session_id": "session_1",
                    "tool_call_id": "call_1", "status": "failed", "is_error": True,
                },
            },
            {
                "id": "evt_success",
                "sequence": 2,
                "type": "agent.tool.completed",
                "payload": {
                    "agent_id": "agent_1", "platform_session_id": "session_1",
                    "tool_call_id": "call_1", "status": "completed", "exit_code": 0,
                },
            },
        ]
    )

    assert reconciliations == [
        {
            "agent_id": "agent_1",
            "platform_session_id": "session_1",
            "tool_call_id": "call_1",
            "canonical_event_id": "evt_success",
            "canonical_sequence": 2,
            "superseded_event_ids": ["evt_failed"],
            "superseded_sequences": [1],
            "duplicate_count": 1,
            "write_count": 1,
            "terminal": True,
            "terminal_count_before": 2,
            "terminal_count_after": 1,
        }
    ]


def test_runtime_attestation_exposes_host_sdk_and_session_binding() -> None:
    projection = _public_event_projection(
        {
            "id": "evt_turn_88",
            "run_id": "run_88",
            "sequence": 88,
            "type": "agent.turn.completed",
            "category": "execution",
            "title": "完成",
            "summary": "真实回合完成",
            "payload": {
                "agent_id": "agent_quality",
                "node_key": "audit",
                "phase": "独立审计",
                "session_key": "platform-session-1",
                "platform_attempt_id": "attempt:run_88:audit:epoch1:loop1:node1",
                "sdk_invocation_id": "sdk-invocation-1",
                "runtime": {
                    "runtime": "agent-sdk-bridge",
                    "agent_id": "agent_quality",
                    "session_key": "platform-session-1",
                    "session_id": "claude-session-1",
                    "model": "gpt-5.6-sol",
                },
            },
            "created_at": "2026-09-12T00:00:00+00:00",
        }
    )

    attestation = _runtime_attestation(
        [projection],
        {"runtime": "claude_code", "mode": "agent-sdk-bridge", "version": "0.3.268"},
        {"model": "gpt-5.6-sol", "tool_enabled_agent_ids": ["agent_quality"]},
    )

    assert attestation["runtime_health"]["mode"] == "agent-sdk-bridge"
    assert attestation["session_binding_count"] == 1
    assert attestation["distinct_sdk_session_count"] == 1
    assert attestation["session_bindings"][0]["claude_sdk_session_id"] == "claude-session-1"
    assert attestation["session_bindings"][0]["event_id"] == "evt_turn_88"
    assert attestation["session_bindings"][0]["run_id"] == "run_88"
    assert attestation["session_bindings"][0]["role_instance_id"] == "role:run_88:audit:agent_quality"
    assert attestation["session_bindings"][0]["platform_session_id"] == "platform-session-1"
    assert attestation["session_bindings"][0]["platform_attempt_id"] == "attempt:run_88:audit:epoch1:loop1:node1"
    assert attestation["session_bindings"][0]["sdk_invocation_id"] == "sdk-invocation-1"


def test_artifact_creation_provenance_keeps_current_and_inherited_event_identity() -> None:
    current = {
        "id": "run_current",
        "events": [
            {
                "id": "evt_current",
                "run_id": "run_current",
                "organization_id": "org",
                "sequence": 20,
                "type": "artifact.created",
                "category": "artifact",
                "title": "current",
                "summary": "created",
                "payload": {
                    "artifact_id": "artifact_current",
                    "task_id": "task_2",
                    "node_key": "report",
                    "artifact_version": 2,
                },
            }
        ],
    }
    parent = {
        "id": "run_parent",
        "events": [
            {
                "id": "evt_parent",
                "run_id": "run_parent",
                "organization_id": "org",
                "sequence": 10,
                "type": "artifact.created",
                "category": "artifact",
                "title": "parent",
                "summary": "created",
                "payload": {
                    "artifact_id": "artifact_parent",
                    "task_id": "task_1",
                    "node_key": "build",
                    "artifact_version": 1,
                },
            }
        ],
    }

    provenance = _artifact_creation_provenance([current, parent])

    assert provenance["artifact_current"]["source_run_id"] == "run_current"
    assert provenance["artifact_current"]["source_event_id"] == "evt_current"
    assert provenance["artifact_parent"]["source_run_id"] == "run_parent"
    assert provenance["artifact_parent"]["source_event_sequence"] == 10
    assert len(provenance["artifact_parent"]["source_event_sha256"]) == 64


def test_artifact_creation_provenance_recovers_legacy_retry_copy_by_bytes() -> None:
    current = {
        "id": "run_current",
        "tasks": [{"id": "task_current", "node_key": "plan"}],
        "artifacts": [
            {
                "id": "artifact_copy", "task_id": "task_current", "version": 1,
                "sha256": "a" * 64, "content": "same",
            }
        ],
        "events": [
            {
                "id": "evt_retry", "run_id": "run_current", "organization_id": "org",
                "sequence": 1, "type": "run.retry_created", "category": "system",
                "title": "retry", "summary": "retry", "payload": {"source_run_id": "run_parent"},
            }
        ],
    }
    parent = {
        "id": "run_parent",
        "tasks": [{"id": "task_parent", "node_key": "plan"}],
        "artifacts": [
            {
                "id": "artifact_parent", "task_id": "task_parent", "version": 1,
                "sha256": "a" * 64, "content": "same",
            }
        ],
        "events": [],
    }

    provenance = _artifact_creation_provenance([current, parent])

    assert provenance["artifact_copy"]["source_run_id"] == "run_current"
    assert provenance["artifact_copy"]["source_event_id"] == "evt_retry"
    assert provenance["artifact_copy"]["inherited_from_run_id"] == "run_parent"
    assert provenance["artifact_copy"]["inherited_from_artifact_id"] == "artifact_parent"


def test_artifact_creation_provenance_records_retry_inheritance_identity() -> None:
    retry = {
        "id": "run_retry",
        "events": [
            {
                "id": "evt_inherited",
                "run_id": "run_retry",
                "organization_id": "org",
                "sequence": 2,
                "type": "artifact.inherited",
                "category": "artifact",
                "title": "inherited",
                "summary": "copied",
                "payload": {
                    "artifact_id": "artifact_copy",
                    "artifact_version": 1,
                    "task_id": "task_copy",
                    "node_key": "plan",
                    "source_run_id": "run_parent",
                    "source_task_id": "task_parent",
                    "source_artifact_id": "artifact_parent",
                    "source_artifact_sha256": "a" * 64,
                },
            }
        ],
    }

    provenance = _artifact_creation_provenance([retry])

    assert provenance["artifact_copy"]["source_run_id"] == "run_retry"
    assert provenance["artifact_copy"]["inheritance_event"] is True
    assert provenance["artifact_copy"]["inherited_from_run_id"] == "run_parent"
    assert provenance["artifact_copy"]["inherited_from_artifact_id"] == "artifact_parent"
    assert provenance["artifact_copy"]["inherited_from_artifact_sha256"] == "a" * 64


def test_runtime_source_attestation_proves_claude_only_product_route() -> None:
    attestation = _runtime_source_attestation(
        {"runtime": "openclaw", "mode": "legacy"}
    )
    assert attestation["status"] == "failed"

    attestation = _runtime_source_attestation(
        {"runtime": "claude_code", "mode": "agent-sdk-bridge"}
    )

    assert attestation["status"] == "passed"
    assert attestation["blocking_findings"] == []
    assert all(attestation["checks"].values())
    assert any(
        item["path"] == "server/app/agent_runtime_registry.py" and item["present"]
        for item in attestation["files"]
    )
    assert attestation["historical_exclusions"][0]["path"] == "experiments/openclaw_baseline/openclaw_runtime.py"


def test_runtime_source_files_are_registered_as_exact_run_level_artifacts(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "runtime-source-artifacts.db"))
    agent = platform.create_agent(
        name="源码审计", role="质量工程师", description="复核生产源码", persona="逐字节核验",
        capabilities=["源码重建"],
    )
    workflow = platform.create_workflow(
        "源码证据章法", "登记生产 Runtime 源字节", "test",
        {
            "nodes": [{"key": "runtime_probe_harness", "name": "Runtime 取证", "agent_id": agent["id"], "agent_role": agent["role"]}],
            "edges": [], "policies": {},
        },
    )
    run = platform.create_run(workflow["id"], "建立可隔离重建的源码证据")

    registered = _ensure_runtime_source_artifacts(platform, run)
    refreshed = platform.get_run_execution_snapshot(run["id"])
    repeated = _ensure_runtime_source_artifacts(platform, refreshed)

    assert len(registered) == len(RUNTIME_SOURCE_PATHS)
    assert repeated == []
    assert all(item["task_id"] is None for item in registered)
    assert {item["title"] for item in registered} == set(RUNTIME_SOURCE_PATHS)
    assert all(platform.verify_artifact_bytes(run["id"], item["id"])["matched"] for item in registered)
    source_events = [
        event for event in platform.get_run_execution_snapshot(run["id"])["events"]
        if event["type"] == "runtime.source.registry.completed"
    ]
    assert len(source_events) == 1
    assert source_events[0]["payload"]["matched_source_file_count"] == len(RUNTIME_SOURCE_PATHS)


def test_claude_workspace_promotion_retries_transient_windows_file_error(monkeypatch, tmp_path) -> None:
    runtime = ClaudeCodeRuntime(
        state_root=tmp_path / "state",
        workspace_root=tmp_path / "agents",
    )
    agent = {"id": "engineer"}
    delivery = runtime.workspace_path(agent) / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    (delivery / "result.txt").write_text("verified", encoding="utf-8")
    destination = tmp_path / "run-code"
    real_copy2 = claude_runtime_module.shutil.copy2
    copy_attempts = 0

    def transient_copy(source, target):
        nonlocal copy_attempts
        copy_attempts += 1
        if copy_attempts == 1:
            raise FileNotFoundError(3, "transient Windows path lookup failure")
        return real_copy2(source, target)

    monkeypatch.setattr(claude_runtime_module.shutil, "copy2", transient_copy)

    promoted = runtime.promote_workspace_tree(agent=agent, destination=destination)

    assert copy_attempts == 2
    assert (destination / "result.txt").read_text(encoding="utf-8") == "verified"
    assert len(promoted) == 1
    assert promoted[0]["path"] == "result.txt"
    assert promoted[0]["action"] == "created"
    assert promoted[0]["size_bytes"] == len("verified")
    assert promoted[0]["promoted"] is True


def test_claude_engineering_submission_retries_transient_windows_file_error(monkeypatch, tmp_path) -> None:
    runtime = ClaudeCodeRuntime(
        state_root=tmp_path / "state",
        workspace_root=tmp_path / "agents",
    )
    agent = {"id": "engineer", "name": "工程师"}
    delivery = runtime.workspace_path(agent) / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    source = delivery / "submission.txt"
    source.write_text("published", encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(delivery))
    real_copy2 = claude_runtime_module.shutil.copy2
    copy_attempts = 0

    def transient_copy(source_path, target_path):
        nonlocal copy_attempts
        copy_attempts += 1
        if copy_attempts == 1:
            raise FileNotFoundError(3, "transient Windows path lookup failure")
        return real_copy2(source_path, target_path)

    monkeypatch.setattr(claude_runtime_module.shutil, "copy2", transient_copy)

    submission = runtime.publish_workspace_submission(
        agent=agent,
        changes=changes,
        destination=tmp_path / "public-submission",
    )

    assert copy_attempts == 2
    assert submission["file_count"] == 1
    assert (Path(submission["files_root"]) / "submission.txt").read_text(encoding="utf-8") == "published"
