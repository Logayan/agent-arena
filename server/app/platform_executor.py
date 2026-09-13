from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agent_runtime import AgentRuntimeError, public_runtime_error
from .agent_runtime_registry import agent_runtime
from .git_delivery import GitDeliveryError, commit_run_changes, deliver_commit_to_remote, ensure_run_repository
from .llm_client import LLMRequestError
from .platform_store import PlatformStore
from .run_budget import active_execution_epoch_seconds, effective_run_minutes


class ArtifactValidationError(RuntimeError):
    pass


class _AttemptEvidenceBundleCache:
    """Freeze one evidence bundle per platform Attempt.

    Team members in the same node share a platform Attempt. Without this
    cache, every member rebuilt the full event projection and recopied every
    Artifact before entering Claude Code SDK, which could starve API traffic
    for mature Runs. Different Attempts remain independently auditable.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._paths: dict[str, Path] = {}

    async def get_or_create(
        self,
        platform_attempt_id: str,
        builder: Callable[[], Awaitable[Path]],
    ) -> Path:
        cached = self._paths.get(platform_attempt_id)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._paths.get(platform_attempt_id)
            if cached is not None:
                return cached
            created = await builder()
            self._paths[platform_attempt_id] = created
            return created


def _runtime_error_metadata(exc: Exception) -> dict[str, Any]:
    public_error = public_runtime_error(exc)
    if isinstance(exc, AgentRuntimeError):
        return {
            **public_error,
            "runtime_error": {
                "message": public_error["error_detail"],
                "category": exc.category,
                "retryable": exc.retryable,
                "runtime": exc.runtime,
                "diagnostic_id": public_error["diagnostic_id"],
            },
        }
    return public_error


def _run_time_limit_enabled(policies: dict[str, Any]) -> bool:
    """Fixed Run wall-clock limits are opt-in for explicitly bounded workflows."""
    return policies.get("enforce_run_time_limit") is True


ENGINEERING_KEYWORDS = {
    "code", "coding", "implementation", "development", "develop", "build", "test", "testing",
    "deploy", "deployment", "frontend", "backend", "software delivery", "runnable", "软件开发", "代码", "开发实现",
    "编码", "自动化测试", "功能测试", "集成测试", "构建", "部署", "前端开发", "后端开发", "可运行",
}

RUNTIME_TOOL_NODE_KEYWORDS = {
    "audit", "verify", "verification", "evidence", "forensic", "artifact", "file", "hash",
    "runtime", "test", "testing", "remediation", "rerun", "migration report", "gap list",
    "审计", "核验", "复验", "取证", "证据", "事件", "产物", "文件", "哈希", "测试",
    "故障注入", "整改", "重跑", "迁移报告", "缺口清单", "证据索引",
}

EVIDENCE_PAYLOAD_KEYS = {
    "task_id", "node_key", "node_attempt", "loop_round", "agent_id", "agent_role", "team_id",
    "phase", "session_key", "runtime", "runtime_mode", "mode", "model", "models", "execution_epoch",
    "tool_call_id", "tool_name", "command", "status", "exit_code", "cwd", "shell", "environment",
    "path", "relative_path", "sha256", "size_bytes", "previous_sha256", "action", "artifact_id",
    "artifact_ids", "artifact_kind", "artifact_title", "artifact_version", "decision", "revision_round",
    "target_node_keys", "impacted_node_keys", "max_revision_rounds",
    "error_type", "error_detail", "error_code", "error_category", "retryable", "diagnostic_id",
    "minutes", "base_minutes", "effective_minutes", "maximum_minutes", "budget_kind",
    "completed_node_keys", "interrupted_node_keys", "file_change_count", "action_count", "usage",
    "message_type", "from_agent_id", "to_agent_id", "round", "total_rounds", "content",
    "platform_attempt_id", "rework_of", "rework_of_run_id", "supersedes", "causation_event_id",
    "role_instance_id", "approval_credential_id", "platform_session_id", "authorization_decision",
    "operation_id", "idempotency_key", "side_effect_status", "source_run_id", "source_task_id",
    "source_artifact_id", "source_artifact_sha256", "inherited_artifact_sha256", "memory_id",
    "memory_key", "memory_version", "value_sha256", "writer_session_id", "reader_session_id",
    "writer_sdk_session_id", "reader_sdk_session_id", "claude_sdk_session_id",
    "commit_sha", "short_sha", "tree_sha", "parent_shas", "branch", "subject",
    "author_name", "author_agent_id", "committed_at", "file_count", "shortstat", "patch_sha256",
    "entrypoints", "entrypoint", "entrypoint_id", "business_invocation_id", "worker_id", "lease_id",
    "stale_execution_epoch", "revoked_by_lease_id", "revoked_by_worker_id",
    "openclaw_traffic_count", "claude_writer_count", "dual_write_count", "silent_fallback_count",
    "single_writer", "fail_closed", "rollback_status",
    "timeout_seconds", "next_timeout_seconds", "timeout_retry_level", "timeout_extended",
    "reconciled_after_interruption", "source_event_id", "source_event_sequence", "source_sequence",
    "disposition", "resolved_by_event_id", "canonical_event_id", "canonical_sequence",
    "superseded_event_id", "superseded_event_ids", "superseded_sequence", "superseded_sequences",
    "terminal_count_before", "terminal_count_after", "duplicate_side_effect_count", "duplicate_count",
    "write_count", "terminal", "is_error", "input_schema", "output_schema", "schema_id", "schema_sha256",
    "arguments_type", "required_fields", "missing_fields", "passed",
    "arguments_sha256", "output_sha256", "before_sha256", "after_sha256", "read_back_sha256",
    "supersedes_memory_id", "superseded_memory_id", "superseded_by_memory_id",
    "superseded_memory_version", "superseded_value_sha256", "first_sdk_session_id",
    "second_sdk_session_id", "first_response_sha256", "second_response_sha256",
    "superseded_artifact_id", "superseded_by_artifact_id", "superseded_artifact_version",
    "seal_id", "seal_ids", "seal_sha256", "reveal_id", "thread_id", "thread_status",
    "participant_agent_ids", "contribution_count", "sealed_contribution_count", "message_count",
    "visible_message_count", "round_message_count", "member_count", "decision_sha256",
    "recoverable", "safe_boundary", "interruption_kind", "previous_status", "reason",
    "strict_sdk_session",
}


def _safe_segment(value: object, fallback: str = "item") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-_").lower()
    return normalized[:64] or fallback


def _memory_key(agent: dict[str, Any], memory_id: object) -> str:
    return f"agent-family:{agent.get('family_id') or agent.get('id')}:{memory_id}"


def _is_engineering_node(node: dict[str, Any], agent: dict[str, Any] | None = None) -> bool:
    explicit = str(node.get("execution_mode") or node.get("delivery_mode") or "").lower()
    if explicit in {"code", "engineering", "implementation", "executable"}:
        return True
    if explicit in {"document", "analysis", "text"}:
        return False
    text = " ".join(
        str(value or "")
        for value in (
            node.get("key"), node.get("name"), node.get("purpose"), node.get("type"),
            (agent or {}).get("role"),
        )
    ).lower()
    return any(keyword in text for keyword in ENGINEERING_KEYWORDS)


def _node_requires_runtime_tools(node: dict[str, Any], agent: dict[str, Any] | None = None) -> bool:
    explicit = node.get("requires_runtime_tools")
    if isinstance(explicit, bool):
        return explicit
    node_type = str(node.get("type") or "").lower()
    if node_type in {"judge", "gate", "quality_gate"} or _is_engineering_node(node, agent):
        return True
    text = " ".join(
        str(value or "")
        for value in (
            node.get("key"), node.get("name"), node.get("purpose"), node.get("type"),
        )
    ).lower()
    return any(keyword in text for keyword in RUNTIME_TOOL_NODE_KEYWORDS)


def _compact_evidence_value(value: Any, *, max_string: int = 8_000, depth: int = 0) -> Any:
    if depth >= 5:
        return "<depth-limited>"
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "…<truncated>"
    if isinstance(value, dict):
        return {
            str(key): _compact_evidence_value(item, max_string=max_string, depth=depth + 1)
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, list):
        return [_compact_evidence_value(item, max_string=max_string, depth=depth + 1) for item in value[:80]]
    return value


def _public_event_projection(event: dict[str, Any]) -> dict[str, Any] | None:
    if str(event.get("category") or "") == "private_audit" or str(event.get("type") or "") == "agent.rationale.submitted":
        return None
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    selected_payload = {
        key: _compact_evidence_value(value)
        for key, value in payload.items()
        if key in EVIDENCE_PAYLOAD_KEYS
    }
    return {
        "event_id": event.get("id"),
        "run_id": event.get("run_id"),
        "organization_id": event.get("organization_id"),
        "sequence": event.get("sequence"),
        "type": event.get("type"),
        "category": event.get("category"),
        "title": _compact_evidence_value(str(event.get("title") or ""), max_string=2_000),
        "summary": _compact_evidence_value(str(event.get("summary") or ""), max_string=8_000),
        "payload": selected_payload,
        "created_at": event.get("created_at"),
        "source_event_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "projection": "public_agent_safe",
    }


def _runtime_attestation(
    projections: list[dict[str, Any]],
    runtime_health: dict[str, Any],
    runtime_sync: dict[str, Any],
) -> dict[str, Any]:
    bindings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in projections:
        if event.get("type") != "agent.turn.completed":
            continue
        event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        runtime_details = event_payload.get("runtime") if isinstance(event_payload.get("runtime"), dict) else {}
        session_id = str(runtime_details.get("session_id") or "")
        agent_id = str(event_payload.get("agent_id") or runtime_details.get("agent_id") or "")
        session_key = str(event_payload.get("session_key") or runtime_details.get("session_key") or "")
        if not session_id:
            continue
        identity = (agent_id, session_key, session_id)
        if identity in seen:
            continue
        seen.add(identity)
        bindings.append(
            {
                "event_sequence": event.get("sequence"),
                "event_id": event.get("event_id"),
                "run_id": event.get("run_id"),
                "source_event_sha256": event.get("source_event_sha256"),
                "agent_id": agent_id,
                "node_key": event_payload.get("node_key"),
                "phase": event_payload.get("phase"),
                "role_instance_id": (
                    f"role:{event.get('run_id')}:{event_payload.get('node_key')}:{agent_id}"
                    if event.get("run_id") and event_payload.get("node_key") and agent_id
                    else ""
                ),
                "platform_session_id": session_key,
                "platform_session_key": session_key,
                "claude_sdk_session_id": session_id,
                "model": runtime_details.get("model"),
                "runtime": runtime_details.get("runtime"),
            }
        )
    return {
        "schema_version": "jianghu.runtime-attestation.v1",
        "runtime_health": _compact_evidence_value(runtime_health),
        "runtime_sync": _compact_evidence_value(runtime_sync),
        "session_binding_count": len(bindings),
        "distinct_agent_count": len({item["agent_id"] for item in bindings if item["agent_id"]}),
        "distinct_sdk_session_count": len({item["claude_sdk_session_id"] for item in bindings}),
        "session_bindings": bindings,
    }


def _interrupted_tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return started tool calls whose process ended without a terminal receipt."""
    groups: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = str(event.get("type") or "")
        if event_type not in {
            "agent.tool.authorization.decided",
            "agent.tool.started",
            "agent.tool.completed",
            "agent.command.started",
            "agent.command.completed",
            "agent.side_effect.verified",
        }:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        tool_call_id = str(payload.get("tool_call_id") or "")
        if not tool_call_id:
            continue
        group = groups.setdefault(tool_call_id, {"tool_call_id": tool_call_id})
        group[event_type] = event
    interrupted = []
    for group in groups.values():
        started = group.get("agent.tool.started")
        if not started or group.get("agent.tool.completed"):
            continue
        started_payload = started.get("payload") if isinstance(started.get("payload"), dict) else {}
        authorization = group.get("agent.tool.authorization.decided") or {}
        authorization_payload = (
            authorization.get("payload") if isinstance(authorization.get("payload"), dict) else {}
        )
        command_started = group.get("agent.command.started")
        interrupted.append(
            {
                **authorization_payload,
                **started_payload,
                "tool_call_id": group["tool_call_id"],
                "source_event_id": started.get("id"),
                "source_event_sequence": started.get("sequence"),
                "command": (
                    (command_started.get("payload") or {}).get("command")
                    if isinstance(command_started, dict)
                    else None
                ),
            }
        )
    return interrupted


def _tool_event_identity(event: dict[str, Any]) -> tuple[str, str, str]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return (
        str(payload.get("agent_id") or ""),
        str(payload.get("platform_session_id") or payload.get("session_key") or ""),
        str(payload.get("tool_call_id") or ""),
    )


def _tool_terminal_reconciliations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reconciled = {
        _tool_event_identity(event)
        for event in events
        if event.get("type") == "agent.tool.terminal.reconciled"
    }
    terminals: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for event in events:
        if event.get("type") != "agent.tool.completed":
            continue
        identity = _tool_event_identity(event)
        if not identity[2]:
            continue
        terminals.setdefault(identity, []).append(event)
    results: list[dict[str, Any]] = []
    for identity, candidates in terminals.items():
        if len(candidates) < 2 or identity in reconciled:
            continue
        successful = []
        for candidate in candidates:
            payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
            if not payload.get("is_error") and str(payload.get("status") or "").lower() not in {"failed", "error", "timeout", "interrupted"} and payload.get("exit_code") in {None, 0}:
                successful.append(candidate)
        canonical = (successful or candidates)[-1]
        superseded = [item for item in candidates if item.get("id") != canonical.get("id")]
        results.append(
            {
                "agent_id": identity[0],
                "platform_session_id": identity[1],
                "tool_call_id": identity[2],
                "canonical_event_id": canonical.get("id"),
                "canonical_sequence": canonical.get("sequence"),
                "superseded_event_ids": [item.get("id") for item in superseded],
                "superseded_sequences": [item.get("sequence") for item in superseded],
                "duplicate_count": len(candidates) - 1,
                "write_count": 1,
                "terminal": True,
                "terminal_count_before": len(candidates),
                "terminal_count_after": 1,
            }
        )
    return results


def _unreviewed_failed_tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviewed_ids = {
        str((event.get("payload") or {}).get("source_event_id") or "")
        for event in events
        if event.get("type") == "agent.tool.failure.reviewed" and isinstance(event.get("payload"), dict)
    }
    failed: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "agent.tool.completed" or str(event.get("id") or "") in reviewed_ids:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        status = str(payload.get("status") or "").lower()
        if payload.get("is_error") or status in {"failed", "error", "timeout", "interrupted"} or payload.get("exit_code") not in {None, 0}:
            failed.append(event)
    return failed


def _attempt_rework_run_id(
    run_id: str,
    run: dict[str, Any],
    prior_attempt_event: dict[str, Any] | None,
    loop_round: int,
) -> str | None:
    """Return the Run that owns the Attempt named by ``rework_of``.

    A gate retry inside one Run must never point its Attempt edge at the
    parent Run. Cross-Run retry ancestry is retained only when there is no
    same-Run prior Attempt.
    """
    # A recovered execution epoch resets ``loop_round`` to 1, but that does
    # not turn the new Attempt into a child of the parent Run.  Prefer the
    # actual owner of the most recent same-node Attempt whenever one exists.
    if prior_attempt_event:
        return str(prior_attempt_event.get("run_id") or run_id)
    parent_run_id = run.get("parent_run_id")
    return str(parent_run_id) if parent_run_id else None


def _attempt_rework_attempt_id(
    prior_attempt_event: dict[str, Any] | None,
) -> str | None:
    """Return the concrete prior Attempt referenced by a resumed execution."""
    if not prior_attempt_event:
        return None
    payload = prior_attempt_event.get("payload")
    if not isinstance(payload, dict):
        return None
    platform_attempt_id = payload.get("platform_attempt_id")
    return str(platform_attempt_id) if platform_attempt_id else None


def _apply_run_execution_policy_amendments(
    run: dict[str, Any],
    node_def_by_key: dict[str, dict[str, Any]],
    policies: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Apply auditable Run-local policy changes without creating a new version."""
    amended_nodes = {key: dict(value) for key, value in node_def_by_key.items()}
    amended_policies = dict(policies)
    for event in sorted(run.get("events", []), key=lambda item: int(item.get("sequence", 0) or 0)):
        if event.get("type") != "workflow.execution_policy.amended":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        node_key = str(payload.get("node_key") or "")
        participant_ids = payload.get("participant_agent_ids")
        if node_key in amended_nodes and isinstance(participant_ids, list) and participant_ids:
            amended_nodes[node_key]["participant_agent_ids"] = [
                str(item) for item in participant_ids if str(item)
            ]
        if payload.get("max_revision_rounds") is not None:
            amended_policies["max_revision_rounds"] = max(
                1, min(int(payload.get("max_revision_rounds") or 1), 6)
            )
    return amended_nodes, amended_policies


def _unresolved_tool_terminal_duplicate_count(events: list[dict[str, Any]]) -> int:
    reconciled = {
        _tool_event_identity(event)
        for event in events
        if event.get("type") == "agent.tool.terminal.reconciled"
    }
    counts: dict[tuple[str, str, str], int] = {}
    for event in events:
        if event.get("type") != "agent.tool.completed":
            continue
        identity = _tool_event_identity(event)
        if identity[2]:
            counts[identity] = counts.get(identity, 0) + 1
    return sum(1 for identity, count in counts.items() if count > 1 and identity not in reconciled)


def _artifact_creation_provenance(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    provenance: dict[str, dict[str, Any]] = {}
    for source_run in runs:
        source_run_id = str(source_run.get("id") or "")
        for event in source_run.get("events", []):
            if event.get("type") not in {"artifact.created", "artifact.inherited"}:
                continue
            event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            artifact_id = str(event_payload.get("artifact_id") or "")
            if not artifact_id or artifact_id in provenance:
                continue
            projection = _public_event_projection(event)
            provenance[artifact_id] = {
                "source_run_id": source_run_id,
                "source_event_id": event.get("id"),
                "source_event_sequence": event.get("sequence"),
                "source_event_sha256": (projection or {}).get("source_event_sha256", ""),
                "source_task_id": event_payload.get("task_id"),
                "source_node_key": event_payload.get("node_key"),
                "artifact_version": event_payload.get("artifact_version"),
                "inherited_from_run_id": event_payload.get("source_run_id"),
                "inherited_from_task_id": event_payload.get("source_task_id") if event.get("type") == "artifact.inherited" else None,
                "inherited_from_artifact_id": event_payload.get("source_artifact_id"),
                "inherited_from_artifact_sha256": event_payload.get("source_artifact_sha256"),
                "inheritance_event": event.get("type") == "artifact.inherited",
            }
    for run_index, source_run in enumerate(runs):
        source_run_id = str(source_run.get("id") or "")
        task_node_by_id = {
            str(task.get("id") or ""): str(task.get("node_key") or "")
            for task in source_run.get("tasks", [])
        }
        retry_event = next(
            (event for event in source_run.get("events", []) if event.get("type") == "run.retry_created"),
            None,
        )
        retry_projection = _public_event_projection(retry_event) if retry_event else None
        for artifact in source_run.get("artifacts", []):
            artifact_id = str(artifact.get("id") or "")
            if not artifact_id or artifact_id in provenance:
                continue
            node_key = task_node_by_id.get(str(artifact.get("task_id") or ""), "")
            inherited_source: tuple[dict[str, Any], dict[str, Any]] | None = None
            for ancestor in runs[run_index + 1:]:
                ancestor_task_nodes = {
                    str(task.get("id") or ""): str(task.get("node_key") or "")
                    for task in ancestor.get("tasks", [])
                }
                for candidate in ancestor.get("artifacts", []):
                    if ancestor_task_nodes.get(str(candidate.get("task_id") or ""), "") != node_key:
                        continue
                    hashes_match = bool(artifact.get("sha256")) and artifact.get("sha256") == candidate.get("sha256")
                    if hashes_match or artifact.get("content") == candidate.get("content"):
                        inherited_source = (ancestor, candidate)
                        break
                if inherited_source:
                    break
            if not inherited_source:
                continue
            ancestor, candidate = inherited_source
            provenance[artifact_id] = {
                "source_run_id": source_run_id,
                "source_event_id": (retry_event or {}).get("id"),
                "source_event_sequence": (retry_event or {}).get("sequence"),
                "source_event_sha256": (retry_projection or {}).get("source_event_sha256", ""),
                "source_task_id": artifact.get("task_id"),
                "source_node_key": node_key,
                "artifact_version": artifact.get("version"),
                "inherited_from_run_id": ancestor.get("id"),
                "inherited_from_artifact_id": candidate.get("id"),
                "inherited_from_artifact_sha256": candidate.get("sha256"),
                "inheritance_attestation": "retry_preserved_artifact_byte_match",
            }
    return provenance


def _runtime_source_attestation(runtime_health: dict[str, Any]) -> dict[str, Any]:
    """Build a byte-verifiable statement about the production Runtime route.

    The historical OpenClaw adapter is retained under ``experiments`` so the
    frozen baseline and adapter parity tests can still instantiate it.  Any
    executable OpenClaw adapter left in ``server.app`` or imported, registered,
    packaged, or configured by a product entrypoint is a blocking finding.
    """
    project_root = Path(__file__).resolve().parents[2]
    source_paths = (
        "server/app/agent_runtime_registry.py",
        "server/app/main.py",
        "server/app/platform_executor.py",
        "server/app/platform_store.py",
        "server/app/claude_code_runtime.py",
        "server/claude_agent_runtime/bridge.mjs",
        "server/claude_agent_runtime/package.json",
        "server/claude_agent_runtime/package-lock.json",
        "client/src/App.vue",
        "client/src/api.ts",
        "Dockerfile",
        "compose.yaml",
        ".env.docker.example",
    )
    records: list[dict[str, Any]] = []
    source_text: dict[str, str] = {}
    for relative_path in source_paths:
        path = project_root / relative_path
        if not path.is_file():
            records.append({"path": relative_path, "present": False})
            continue
        data = path.read_bytes()
        records.append(
            {
                "path": relative_path,
                "present": True,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        source_text[relative_path] = data.decode("utf-8", errors="replace")

    registry_text = source_text.get("server/app/agent_runtime_registry.py", "")
    package_text = source_text.get("server/claude_agent_runtime/package.json", "")
    package_lock_text = source_text.get("server/claude_agent_runtime/package-lock.json", "")
    deployment_text = "\n".join(
        source_text.get(name, "") for name in ("Dockerfile", "compose.yaml", ".env.docker.example")
    )
    routing_text = "\n".join(
        source_text.get(name, "")
        for name in (
            "server/app/agent_runtime_registry.py",
            "server/app/main.py",
            "server/app/claude_code_runtime.py",
        )
    )
    routing_forbidden_patterns = {
        "production_imports_openclaw_adapter": r"from\s+\.openclaw_runtime\s+import",
        "production_constructs_openclaw_runtime": r"\bOpenClawRuntime\s*\(",
        "legacy_openclaw_switch_present": r"JIANGHU_ENABLE_LEGACY_OPENCLAW",
    }
    deployment_forbidden_patterns = {
        "deployment_installs_openclaw_package": r"openclaw\s*@|openclaw@|npm\s+install[^\n]*openclaw",
        "deployment_configures_openclaw_runtime": r"JIANGHU_OPENCLAW_|OPENCLAW_VERSION",
    }
    findings = [
        name
        for name, pattern in routing_forbidden_patterns.items()
        if re.search(pattern, routing_text, flags=re.IGNORECASE)
    ] + [
        name
        for name, pattern in deployment_forbidden_patterns.items()
        if re.search(pattern, deployment_text, flags=re.IGNORECASE)
    ]
    if (project_root / "server/app/openclaw_runtime.py").is_file():
        findings.append("production_openclaw_adapter_file_present")
    checks = {
        "runtime_health_is_claude_code": str(runtime_health.get("runtime") or "") == "claude_code",
        "runtime_mode_is_sdk_bridge": str(runtime_health.get("mode") or "") == "agent-sdk-bridge",
        "registry_constructs_only_claude_default": "AgentRuntimeRegistry(claude_code_runtime)" in registry_text,
        "registry_rejects_non_claude_configuration": "agent_runtime_fixed_to_claude_code" in registry_text,
        "registry_does_not_import_openclaw": re.search(
            r"from\s+\.openclaw_runtime\s+import", registry_text
        ) is None,
        "production_openclaw_adapter_file_absent": not (
            project_root / "server/app/openclaw_runtime.py"
        ).exists(),
        "frozen_openclaw_baseline_is_outside_product_package": (
            project_root / "experiments/openclaw_baseline/openclaw_runtime.py"
        ).is_file(),
        "sdk_dependency_is_pinned": "@anthropic-ai/claude-agent-sdk" in package_text
        and "@anthropic-ai/claude-agent-sdk" in package_lock_text,
        "deployment_uses_claude_runtime": "JIANGHU_AGENT_RUNTIME=claude_code" in deployment_text,
        "deployment_has_no_openclaw_runtime_dependency": not any(
            finding.startswith("deployment_") for finding in findings
        ),
        "new_runtime_events_are_generic": '"agent.turn.started"' in source_text.get(
            "server/app/platform_executor.py", ""
        )
        and '"agent.turn.completed"' in source_text.get("server/app/platform_executor.py", ""),
    }
    return {
        "schema_version": "jianghu.runtime-source-attestation.v1",
        "scope": "production runtime registry, execution entrypoints, SDK bridge and deployment inputs",
        "status": "passed" if all(checks.values()) and not findings else "failed",
        "checks": checks,
        "blocking_findings": findings,
        "files": records,
        "historical_exclusions": [
            {
                "path": "experiments/openclaw_baseline/openclaw_runtime.py",
                "reason": "frozen migration baseline and direct adapter parity only; physically outside the product package",
            },
            {
                "path": "server/tests/runtime_contract/test_openclaw_runtime_contract.py",
                "reason": "migration baseline regression only",
            },
        ],
    }


def _is_test_command(command: str) -> bool:
    lowered = command.lower()
    return any(
        marker in lowered
        for marker in (
            "pytest", "unittest", "npm test", "npm run test", "pnpm test", "yarn test", "vitest", "jest",
            "go test", "cargo test", "mvn test", "gradle test", "dotnet test", "ctest", "playwright test",
            "测试", "test_", " test ",
        )
    )


def _is_command_tool(tool_name: object) -> bool:
    return str(tool_name or "").strip().lower() in {"exec", "process", "bash"}


def _tool_schema_validation(tool_name: object, arguments: object) -> dict[str, Any]:
    """Validate the public shape of a Claude Runtime tool request.

    The MCP server remains the enforcement boundary. This validation produces a
    stable, reviewable receipt before the terminal tool result is recorded.
    """
    normalized = str(tool_name or "").strip().lower()
    payload = arguments if isinstance(arguments, dict) else {}
    required_by_tool = {
        "read": ("path",),
        "write": ("path", "content"),
        "edit": ("path",),
        "bash": ("command",),
        "exec": ("command",),
        "process": ("command",),
    }
    required = required_by_tool.get(normalized, ())
    missing = [key for key in required if not isinstance(payload.get(key), str) or not str(payload.get(key)).strip()]
    schema_id = f"jianghu.workspace.{normalized or 'unknown'}.v1"
    schema_document = {"schema_id": schema_id, "required_fields": list(required), "arguments_type": "object"}
    canonical_arguments = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "schema_id": schema_id,
        "schema_sha256": hashlib.sha256(
            json.dumps(schema_document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "arguments_sha256": hashlib.sha256(canonical_arguments.encode("utf-8")).hexdigest(),
        "arguments_type": "object" if isinstance(arguments, dict) else type(arguments).__name__,
        "required_fields": list(required),
        "missing_fields": missing,
        "passed": isinstance(arguments, dict) and normalized in required_by_tool and not missing,
    }


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _agent_timeout_seconds(needs_tools: bool, timeout_retry_level: int = 0) -> int:
    default = 1800 if needs_tools else 600
    # The executor has two person attempts inside two node attempts.  Keep the
    # default ceiling high enough for every timeout retry to consume a new tier
    # instead of flattening the latter half of the chain at 3600 seconds.
    maximum = _bounded_env_int("JIANGHU_AGENT_TIMEOUT_MAX_SECONDS", 14400, 60, 14400)
    base = _bounded_env_int("JIANGHU_AGENT_TIMEOUT_SECONDS", default, 60, maximum)
    multiplier = _bounded_env_int("JIANGHU_AGENT_TIMEOUT_RETRY_MULTIPLIER", 2, 1, 4)
    return min(maximum, base * (multiplier ** max(0, int(timeout_retry_level))))


_NEXT_TIMEOUT_RETRY_LEVEL_ATTR = "_jianghu_next_timeout_retry_level"


def _remember_next_timeout_retry_level(exc: Exception, level: int) -> None:
    """Carry the consumed timeout tier back to the enclosing node retry."""
    try:
        setattr(exc, _NEXT_TIMEOUT_RETRY_LEVEL_ATTR, max(0, int(level)))
    except (AttributeError, TypeError, ValueError):
        return


def _next_timeout_retry_level(exc: Exception, current_level: int) -> int:
    current = max(0, int(current_level))
    if public_runtime_error(exc)["error_category"] != "timeout":
        return current
    fallback = current + 1
    try:
        carried = int(getattr(exc, _NEXT_TIMEOUT_RETRY_LEVEL_ATTR, fallback))
    except (TypeError, ValueError):
        carried = fallback
    return max(fallback, carried)


def _try_acquire_run_execution_lease(store: PlatformStore, run_id: str) -> tuple[str, Any, int | None] | None:
    """Acquire a process-lifetime lease before mutating a durable Run.

    PostgreSQL uses an advisory lock held by a dedicated connection. SQLite
    uses an OS file lock next to the database. Both are released by the OS when
    a worker process dies, so startup recovery does not need a stale timeout.
    """
    scope = str(getattr(store, "database_url", "") or Path(getattr(store, "path", ".data/jianghu.db")).resolve())
    identity = hashlib.sha256(f"{scope}:{run_id}".encode("utf-8")).digest()
    if bool(getattr(store, "is_postgres", False)):
        try:
            import psycopg

            connection = psycopg.connect(store.database_url, autocommit=True)
            lock_key = int.from_bytes(identity[:8], byteorder="big", signed=True)
            row = connection.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()
            if not row or not bool(row[0]):
                connection.close()
                return None
            return ("postgres", connection, lock_key)
        except Exception:
            return None

    lock_root = Path(getattr(store, "path", Path(".data/jianghu.db"))).parent / ".run-execution-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / f"{identity.hex()}.lock"
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        handle.close()
        return None
    return ("file", handle, None)


def _release_run_execution_lease(lease: tuple[str, Any, int | None] | None) -> None:
    if lease is None:
        return
    kind, handle, lock_key = lease
    try:
        if kind == "postgres":
            handle.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        else:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _runtime_health(runtime: Any) -> dict[str, Any]:
    try:
        return dict(runtime.health() or {})
    except Exception:
        return {}


def _runtime_mode(runtime: Any) -> str:
    return str(_runtime_health(runtime).get("mode") or "unknown")


def _runtime_tool_enabled_agent_ids(
    node_definitions: dict[str, dict[str, Any]],
    agent_lookup,
) -> set[str]:
    enabled: set[str] = set()
    for node in node_definitions.values():
        agent_id = str(node.get("agent_id") or "")
        if not _node_requires_runtime_tools(node, agent_lookup(agent_id)):
            continue
        if agent_id:
            enabled.add(agent_id)
        enabled.update(str(item) for item in node.get("participant_agent_ids", []) if item)
    return enabled


async def _gather_cancel_on_error(*awaitables):
    tasks = [asyncio.create_task(awaitable) for awaitable in awaitables]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _code_manifest(root: Path) -> list[dict[str, Any]]:
    ignored = {".git", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".venv", "venv"}
    manifest: list[dict[str, Any]] = []
    if not root.is_dir():
        return manifest
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        manifest.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    return manifest


def _text(response: dict[str, Any]) -> str:
    blocks = response.get("content", [])
    return "\n".join(
        str(block.get("text", "")) for block in blocks if isinstance(block, dict)
    ).strip()


def _preview(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}…"


def _one_page_excerpt(value: str, limit: int = 260) -> str:
    for raw_line in str(value or "").splitlines():
        line = re.sub(r"^[#>*\-\s|`]+", "", raw_line).strip()
        if line and not re.fullmatch(r"[-|: ]+", line):
            return _preview(line, limit)
    return "暂无可提炼的公开摘要。"


def _build_one_page_conclusion(run: dict[str, Any], tasks: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> str:
    latest_by_task: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        task_id = str(artifact.get("task_id") or "")
        current = latest_by_task.get(task_id)
        if current is None or int(artifact.get("version", 0) or 0) > int(current.get("version", 0) or 0):
            latest_by_task[task_id] = artifact
    ordered = [latest_by_task[str(task.get("id"))] for task in tasks if str(task.get("id")) in latest_by_task]
    final_artifact = next(
        (item for item in reversed(ordered) if re.search(r"结论|报告|汇总|裁定", str(item.get("title") or ""))),
        ordered[-1] if ordered else None,
    )
    source = str((final_artifact or {}).get("content") or "")
    decision_match = re.search(
        r"(?:是否值得引进|结论|决定)[：:]?\s*([^\n]{8,220})",
        source,
        re.IGNORECASE,
    )
    decision = decision_match.group(1).strip() if decision_match else (
        "事件已完成，具体引进判断请结合下方节点产物复核。"
    )
    finding_lines = [
        f"- {item.get('title')}: {_one_page_excerpt(str(item.get('content') or ''))}"
        for item in ordered[:6]
    ]
    return "\n".join([
        "# 一页纸结论",
        "",
        f"**事件**：{run.get('task_input') or run.get('workflow_name') or '未命名事件'}",
        f"**Run**：{run.get('id', '')}",
        f"**结论**：{decision}",
        "",
        "## 核心发现",
        *(finding_lines or ["- 本次事件没有形成可汇总的正式产物。"]),
        "",
        "## 使用边界",
        "以上结论来自本次事件已验收的正式节点产物；未被产物证实的内容仍属于推断或待验证假设，不应直接作为采购、上线或对外承诺依据。",
        "",
        "## 下一步",
        "优先把结论转化为一个受控试点，明确负责人、真实数据边界、验收指标和复盘时间，再决定是否扩大引进。",
    ])[:12000]


def _extract_initiator_note(value: str) -> tuple[str, str]:
    """Split an agent-authored rationale summary from the public contribution.

    This is deliberately not a hidden chain-of-thought capture.  The model is
    asked to provide a concise, reviewable explanation of facts, trade-offs,
    uncertainty and verification steps.  The note is removed before any team
    contribution or message is shared with other agents.
    """
    matches = list(re.finditer(r"<initiator_note>\s*(.*?)\s*</initiator_note>", value, re.IGNORECASE | re.DOTALL))
    if not matches:
        return value.strip(), ""
    note = "\n\n".join(match.group(1).strip() for match in matches if match.group(1).strip())[:6000]
    public = re.sub(r"<initiator_note>\s*.*?\s*</initiator_note>", "", value, flags=re.IGNORECASE | re.DOTALL).strip()
    return public, note


def _legacy_team_knowledge(team: dict[str, Any]) -> str:
    documents: list[str] = []
    seen_content: set[str] = set()
    suffixes = {
        ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".xml",
        ".py", ".js", ".ts", ".tsx", ".vue", ".sql", ".toml", ".ini", ".log",
    }
    for raw_path in team.get("knowledge_paths", [])[:8]:
        path = Path(str(raw_path)).expanduser()
        candidates = [path] if path.is_file() else ([item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in suffixes][:12] if path.is_dir() else [])
        for candidate in candidates:
            try:
                content = candidate.read_text(encoding="utf-8", errors="replace")[:12000]
            except OSError:
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen_content:
                continue
            seen_content.add(digest)
            documents.append(f"## 来源：{candidate}\n{content}")
            if sum(len(item) for item in documents) >= 48000:
                return "\n\n".join(documents)[:48000]
    return "\n\n".join(documents)[:48000]


def _team_knowledge(store: PlatformStore, team: dict[str, Any], query: str, agent_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    try:
        retrieval = store.search_team_knowledge(str(team["id"]), query, limit=8, agent_id=agent_id)
    except ValueError:
        retrieval = {"results": []}
    results = retrieval.get("results", [])
    if not results:
        return _legacy_team_knowledge(team), []
    documents = []
    for result in results:
        documents.append(
            "\n".join(
                [
                    f"## 来源：{result.get('source_name', '组织知识')}（{result.get('locator', '片段')}）",
                    f"知识来源 ID：{result.get('source_id', '')}",
                    f"检索相关度：{float(result.get('score', 0)):.3f}",
                    str(result.get("content") or ""),
                ]
            )
        )
    return "\n\n".join(documents)[:48000], results


def _json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _judge_decision_from_delivery(response: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Recover a machine-readable Judge verdict from its isolated delivery tree.

    Tool-enabled Judges may correctly write ``verdict.json`` but use their
    public final message for a human-readable report. The captured delivery
    tree belongs to the same isolated SDK turn, so a validated verdict file is
    a safe fallback instead of turning a completed Judge turn into a failure.
    """
    delivery_root = Path(str(response.get("delivery_root") or ""))
    if not delivery_root.is_dir():
        return None, None
    try:
        candidates = sorted(
            delivery_root.rglob("verdict.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return None, None
    for path in candidates[:32]:
        try:
            if path.stat().st_size > 1_000_000:
                continue
            parsed = _json_object(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        if parsed and str(parsed.get("verdict")) in {"pass", "revise"}:
            return parsed, path.relative_to(delivery_root).as_posix()
    return None, None


def _dependencies(workflow: dict[str, Any]) -> dict[str, set[str]]:
    nodes = workflow["definition"].get("nodes", [])
    keys = [str(node["key"]) for node in nodes]
    deps = {key: set() for key in keys}
    edges = workflow["definition"].get("edges", [])
    if not isinstance(edges, list) or not edges:
        # An edgeless DAG means every node is an independent parallel root.
        return deps
    for edge in edges:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            source, target = str(edge[0]), str(edge[1])
            if source in deps and target in deps and source != target:
                deps[target].add(source)
    return deps


async def execute_platform_run(store: PlatformStore, run_id: str) -> None:
    # Mature Runs can contain tens of thousands of events and hundreds of
    # materialized Artifacts. Hydrating that projection is blocking I/O/CPU and
    # must never monopolize the FastAPI event-loop thread.
    run = await asyncio.to_thread(store.get_run_execution_snapshot, run_id)
    if not run:
        return
    workflow = store.get_workflow(run["workflow_id"])
    if not workflow:
        store.update_run(run_id, status="failed", stage="workflow_not_found")
        return

    execution_lease = _try_acquire_run_execution_lease(store, run_id)
    if execution_lease is None:
        # Another process already owns this Run. The active worker remains the
        # sole event writer; this contender exits without changing Run state.
        return

    try:
        try:
            run_runtime = agent_runtime.for_run(run_id, run.get("workspace", {}).get("root"))
        except TypeError:
            # Keep lightweight test/adaptor runtimes compatible while the real
            # Runtime adapter uses the Run-scoped execution root.
            run_runtime = agent_runtime.for_run(run_id)
        runtime_name = str(getattr(run_runtime, "runtime_name", agent_runtime.runtime_name))
        runtime_mode = _runtime_mode(run_runtime)
        model_config = store.get_active_model_config(include_secret=True)
        if not model_config:
            raise AgentRuntimeError("runtime_model_config_missing", runtime=agent_runtime.runtime_name)
        initial_run_status = str(run.get("status") or "draft")
        is_recovery = initial_run_status in {"running", "pause_requested", "paused", "budget_exhausted"}
        tasks = run["tasks"]
        task_by_key = {str(task["node_key"]): task for task in tasks}
        node_def_by_key = {
            str(node["key"]): dict(node) for node in workflow["definition"].get("nodes", [])
        }
        dependencies = _dependencies(workflow)
        policies = dict(workflow["definition"].get("policies", {}))
        node_def_by_key, policies = _apply_run_execution_policy_amendments(
            run, node_def_by_key, policies
        )
        max_parallel = int(policies.get("max_parallel_agents", 5) or 5)
        max_parallel = max(1, min(max_parallel, 5))
        enforce_run_time_limit = _run_time_limit_enabled(policies)
        base_max_run_minutes = int(policies.get("max_run_minutes", 180) or 180)
        extension_minutes = sum(
            int((event.get("payload") or {}).get("minutes", 0) or 0)
            for event in run.get("events", [])
            if event.get("type") == "run.time_extended"
        )
        max_run_minutes = effective_run_minutes(base_max_run_minutes, extension_minutes)
        max_total_tokens = int(policies.get("max_total_tokens", 0) or 0)
        started_at = time.monotonic()
        elapsed_before_invocation = (
            active_execution_epoch_seconds(list(run.get("events", [])))
            if enforce_run_time_limit
            else 0.0
        )

        def bounded_run_timeout(seconds: int) -> int:
            return min(seconds, max_run_minutes * 60) if enforce_run_time_limit else seconds
        node_semaphore = asyncio.Semaphore(max_parallel)
        llm_semaphore = asyncio.Semaphore(max_parallel)
        event_lock = asyncio.Lock()
        evidence_bundle_cache = _AttemptEvidenceBundleCache()
        evidence_artifact_cache: dict[tuple[str, str], dict[str, Any]] = {}
        artifacts_by_key: dict[str, str] = {}
        completed: set[str] = set()
        latest_artifact_by_task: dict[str, dict[str, Any]] = {}
        for artifact in run.get("artifacts", []):
            task_id = str(artifact.get("task_id") or "")
            current = latest_artifact_by_task.get(task_id)
            if current is None or int(artifact.get("version", 0) or 0) > int(current.get("version", 0) or 0):
                latest_artifact_by_task[task_id] = artifact
        interrupted_node_keys: list[str] = []
        for task in tasks:
            node_key = str(task["node_key"])
            artifact = latest_artifact_by_task.get(str(task["id"]))
            if str(task.get("status")) == "completed" and artifact:
                completed.add(node_key)
                artifacts_by_key[node_key] = f"[{artifact['title']}]\n{str(artifact.get('content') or '')[:4000]}"
            elif str(task.get("status")) in {"running", "retrying"}:
                interrupted_node_keys.append(node_key)
                store.update_task(str(task["id"]), status="pending")
        pending = set(task_by_key) - completed
        total_tokens = int(run.get("token_count", 0) or 0)
        max_revision_rounds = int(policies.get("max_revision_rounds", policies.get("max_debate_rounds", 3)) or 3)
        max_revision_rounds = max(1, min(max_revision_rounds, 6))
        revision_counts: dict[str, int] = {}
        revision_feedback: dict[str, list[str]] = {}
        for event in run.get("events", []):
            if event.get("type") != "gate.rejected":
                continue
            payload = event.get("payload") or {}
            gate_key = str(payload.get("node_key") or "")
            if gate_key:
                revision_counts[gate_key] = max(
                    revision_counts.get(gate_key, 0),
                    int(payload.get("revision_round", 0) or 0),
                )
        for task in tasks:
            feedback = (task.get("output") or {}).get("feedback")
            if feedback and str(task["node_key"]) in pending:
                revision_feedback.setdefault(str(task["node_key"]), []).append(str(feedback))
        handled_rework_interventions: set[str] = {
            str(item["id"])
            for item in run.get("interventions", [])
            if item.get("kind") == "require_rework" and item.get("status") == "applied"
        }
        execution_epoch = 1 + sum(
            1 for event in run.get("events", []) if event.get("type") in {"run.started", "run.recovered"}
        )

        runtime_agents: dict[str, dict[str, Any]] = {}
        for task in tasks:
            if task.get("agent_id"):
                bound = store.get_agent(str(task["agent_id"]))
                if bound:
                    runtime_agents[bound["id"]] = bound
            if task.get("team_id"):
                team_snapshot = store.get_team(str(task["team_id"]))
                for member in (team_snapshot or {}).get("members", []):
                    runtime_agents[member["id"]] = member
        memories = {
            agent_id: store.list_agent_memories(agent_id, int(agent.get("memory_policy", {}).get("max_prompt_items", 8) or 8))
            for agent_id, agent in runtime_agents.items()
        }
        engineering_node_keys = {
            key
            for key, node in node_def_by_key.items()
            if _is_engineering_node(node, store.get_agent(str(node.get("agent_id") or "")))
            and str(node.get("type") or "") not in {"judge", "gate", "quality_gate"}
        }
        git_workspace: dict[str, Any] | None = None
        git_workspace_error = ""
        git_delivery_config = store.get_run_git_delivery_config(run_id, include_secret=True)
        if git_delivery_config is None:
            # Compatibility for Runs created before event-scoped Git delivery existed.
            git_delivery_config = store.get_git_delivery_config(str(run["project_id"]), include_secret=True)
        if git_delivery_config and not git_delivery_config.get("active"):
            git_delivery_config = None
        if engineering_node_keys:
            try:
                git_workspace = ensure_run_repository(run["workspace"]["code"], run_id)
            except (GitDeliveryError, OSError) as exc:
                git_workspace_error = str(exc)
        tool_enabled_agent_ids = _runtime_tool_enabled_agent_ids(node_def_by_key, store.get_agent)
        try:
            runtime_model_configs = [
                config
                for tier in ("high", "medium", "low")
                if (config := store.get_model_config_for_tier(tier, include_secret=True))
            ]
            runtime_sync = await asyncio.to_thread(
                run_runtime.sync,
                list(runtime_agents.values()),
                memories,
                model_config,
                tool_enabled_agent_ids=tool_enabled_agent_ids,
                model_configs=runtime_model_configs,
            )
        except TypeError:
            runtime_sync = await asyncio.to_thread(
                run_runtime.sync,
                list(runtime_agents.values()),
                memories,
                model_config,
            )

        async def wait_for_control_boundary(*, settle_pause: bool = False) -> None:
            while True:
                current = store.get_run_state(run_id)
                if not current or current["status"] == "cancelled":
                    raise asyncio.CancelledError
                if current["status"] == "pause_requested":
                    if not settle_pause:
                        # Work that was already admitted before the pause request
                        # must drain before the coordinator publishes run.paused.
                        # This prevents parallel siblings from writing new events
                        # after the public pause boundary.
                        return
                    async with event_lock:
                        # Full checkpoint materialization is only needed after a
                        # real pause request. Normal control checks stay light.
                        latest = await asyncio.to_thread(store.get_run_execution_snapshot, run_id)
                        if latest and latest["status"] == "pause_requested":
                            latest_sequence = max(
                                (int(item.get("sequence") or 0) for item in latest.get("events", [])),
                                default=0,
                            )
                            # Three Artifact lifecycle events are written before
                            # run.paused, so the immutable checkpoint can name the
                            # exact effective pause boundary in advance.
                            effective_pause_sequence = latest_sequence + 4
                            checkpoint = store.create_artifact(
                                run_id,
                                None,
                                "run_checkpoint",
                                "有效暂停边界 Checkpoint",
                                json.dumps(
                                    {
                                        "run_id": run_id,
                                        "status": "paused",
                                        "checkpoint_phase": "effective_pause_boundary",
                                        "completed_node_keys": sorted(
                                            str(item.get("node_key"))
                                            for item in latest.get("tasks", [])
                                            if item.get("status") == "completed"
                                        ),
                                        "artifact_ids": [item.get("id") for item in latest.get("artifacts", [])],
                                        "last_sequence": effective_pause_sequence,
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                                "candidate",
                                supersede_candidates=False,
                            )
                            checkpoint_receipt = store.verify_artifact_bytes(run_id, checkpoint["id"])
                            checkpoint_payload = {
                                "artifact_id": checkpoint["id"],
                                "artifact_kind": checkpoint["kind"],
                                "artifact_title": checkpoint["title"],
                                "relative_path": checkpoint["relative_path"],
                                "sha256": checkpoint["sha256"],
                                "size_bytes": checkpoint["size_bytes"],
                                "checkpoint_phase": "effective_pause_boundary",
                                "last_sequence": effective_pause_sequence,
                            }
                            store.append_run_event(
                                run_id, "artifact.created", "artifact",
                                "有效暂停边界 Checkpoint 已登记",
                                "所有已放行回合均已排空；Checkpoint 绑定即将发布的 run.paused 边界。",
                                checkpoint_payload,
                            )
                            store.append_run_event(
                                run_id, "artifact.collected", "artifact",
                                "有效暂停边界 Checkpoint 原始字节已采集",
                                "平台已复读 Checkpoint 原始字节并核对 SHA-256。",
                                {**checkpoint_payload, "status": "sha256_verified" if checkpoint_receipt["matched"] else "mismatched"},
                            )
                            store.append_run_event(
                                run_id, "artifact.download.verified", "validation",
                                "有效暂停边界 Checkpoint 下载字节已复算",
                                "下载路径读取的字节数和 SHA-256 与 Registry 一致。",
                                {**checkpoint_payload, "status": "matched" if checkpoint_receipt["matched"] else "mismatched"},
                            )
                            store.update_run(run_id, status="paused")
                            store.append_run_event(
                                run_id,
                                "run.paused",
                                "intervention",
                                "江湖现场已经停手",
                                "所有未开始的新回合、公开通信、合议和节点切换均已阻断；有效边界 Checkpoint 已按本事件 sequence 固化。",
                                checkpoint_payload,
                            )
                    continue
                if current["status"] == "paused":
                    await asyncio.sleep(0.5)
                    continue
                return

        async def materialize_public_evidence_bundle(platform_attempt_id: str) -> Path:
            async def build() -> Path:
                latest_run = await asyncio.to_thread(store.get_run_execution_snapshot, run_id) or run
                workspace = latest_run.get("workspace") or run.get("workspace") or {}
                run_root = Path(str(workspace.get("root") or "")).resolve()
                code_root = Path(str(workspace.get("code") or "")).resolve()
                evidence_root = code_root / ".jianghu-platform-evidence"
                # Keep the complete identity in run-metadata.json while using
                # a stable short directory on disk. Windows test/workspace
                # roots can already be deep enough that the full Attempt ID
                # would exceed the legacy path-length boundary.
                attempt_digest = hashlib.sha256(
                    platform_attempt_id.encode("utf-8")
                ).hexdigest()[:16]
                bundle_root = evidence_root / "snapshots" / (
                    f"attempt-{attempt_digest}"
                )
                bundle_root.mkdir(parents=True, exist_ok=True)

                projections = await asyncio.to_thread(
                    lambda: [
                        projection
                        for item in latest_run.get("events", [])
                        if (projection := _public_event_projection(item)) is not None
                    ]
                )
                events_payload = await asyncio.to_thread(
                    lambda: "\n".join(
                        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in projections
                    ) + "\n"
                )
                await asyncio.to_thread(
                    (bundle_root / "events.ndjson").write_text,
                    events_payload,
                    encoding="utf-8",
                    newline="\n",
                )
                critical_prefixes = (
                    "run.", "task.", "artifact.", "gate.", "workflow.", "agent.runtime.",
                    "runtime.", "worker.", "attempt.", "agent.session.", "agent.tool.",
                    "agent.side_effect.", "agent.memory.",
                    "agent.message.", "engineering.submission.", "team.",
                )
                critical = await asyncio.to_thread(
                    lambda: [
                        item for item in projections
                        if str(item.get("type") or "").startswith(critical_prefixes)
                    ]
                )
                await asyncio.to_thread(
                    (bundle_root / "critical-events.json").write_text,
                    json.dumps(critical, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                runtime_attestation = _runtime_attestation(
                    projections,
                    _runtime_health(run_runtime),
                    dict(runtime_sync or {}),
                )
                runtime_attestation["generated_at"] = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    (bundle_root / "runtime-attestation.json").write_text,
                    json.dumps(runtime_attestation, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                runtime_source_attestation = _runtime_source_attestation(_runtime_health(run_runtime))
                runtime_source_attestation["generated_at"] = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    (bundle_root / "runtime-source-attestation.json").write_text,
                    json.dumps(runtime_source_attestation, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

                # Artifact bytes are content-addressed and shared across frozen
                # Attempt snapshots. Snapshot registries remain immutable while
                # repeated nodes avoid rewriting hundreds of identical files.
                artifacts_root = evidence_root / "artifacts"
                artifacts_root.mkdir(parents=True, exist_ok=True)
                lineage_runs = [latest_run]
                lineage_ids = {str(latest_run.get("id") or "")}
                ancestor_id = str(latest_run.get("parent_run_id") or "")
                while ancestor_id and ancestor_id not in lineage_ids:
                    lineage_ids.add(ancestor_id)
                    ancestor = await asyncio.to_thread(
                        store.get_run_execution_snapshot, ancestor_id
                    )
                    if not ancestor:
                        break
                    lineage_runs.append(ancestor)
                    ancestor_id = str(ancestor.get("parent_run_id") or "")
                creation_provenance = _artifact_creation_provenance(lineage_runs)
                artifact_registry: list[dict[str, Any]] = []
                for artifact in latest_run.get("artifacts", []):
                    relative_path = str(artifact.get("relative_path") or "")
                    source = (run_root / relative_path).resolve()
                    origin = creation_provenance.get(str(artifact.get("id") or ""), {})
                    inherited = bool(
                        origin.get("inherited_from_run_id")
                        or (
                            origin.get("source_run_id")
                            and str(origin.get("source_run_id")) != str(latest_run.get("id") or "")
                        )
                    )
                    if not relative_path or not source.is_relative_to(run_root) or not source.is_file():
                        artifact_registry.append(
                            {
                                **artifact,
                                **origin,
                                "inherited": inherited,
                                "materialized": False,
                                "observed_sha256": "",
                            }
                        )
                        continue
                    suffix = source.suffix or ".bin"
                    expected_sha256 = str(artifact.get("sha256") or "")
                    cache_key = (str(artifact.get("id") or ""), expected_sha256)
                    cached_artifact = evidence_artifact_cache.get(cache_key)
                    target = artifacts_root / (
                        f"{_safe_segment(artifact.get('id'), 'artifact')}"
                        f"-{_safe_segment(expected_sha256[:16], 'nohash')}{suffix}"
                    )
                    if cached_artifact is None or not target.is_file():
                        data = await asyncio.to_thread(source.read_bytes)
                        observed_sha256 = hashlib.sha256(data).hexdigest()
                        await asyncio.to_thread(target.write_bytes, data)
                        cached_artifact = {
                            "observed_sha256": observed_sha256,
                            "size_bytes": len(data),
                        }
                        evidence_artifact_cache[cache_key] = cached_artifact
                    artifact_registry.append(
                        {
                            "id": artifact.get("id"),
                            "task_id": artifact.get("task_id"),
                            "title": artifact.get("title"),
                            "kind": artifact.get("kind"),
                            "status": artifact.get("status"),
                            "version": artifact.get("version"),
                            "source_relative_path": relative_path,
                            "materialized_path": os.path.relpath(
                                target, bundle_root
                            ).replace("\\", "/"),
                            "expected_sha256": expected_sha256,
                            "observed_sha256": cached_artifact["observed_sha256"],
                            "size_bytes": cached_artifact["size_bytes"],
                            "materialized": True,
                            **origin,
                            "inherited": inherited,
                        }
                    )
                await asyncio.to_thread(
                    (bundle_root / "artifact-registry.json").write_text,
                    json.dumps(artifact_registry, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                run_lineage = [
                    {
                        "id": item.get("id"),
                        "family_id": item.get("run_family_id") or item.get("family_id"),
                        "version": item.get("run_version") or item.get("version"),
                        "parent_run_id": item.get("parent_run_id"),
                        "status": item.get("status"),
                        "artifact_count": len(item.get("artifacts", [])),
                        "event_count": len(item.get("events", [])),
                    }
                    for item in lineage_runs
                ]
                await asyncio.to_thread(
                    (bundle_root / "run-lineage.json").write_text,
                    json.dumps(run_lineage, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

                run_metadata = {
                    "id": latest_run.get("id"),
                    "family_id": latest_run.get("run_family_id") or latest_run.get("family_id"),
                    "version": latest_run.get("run_version") or latest_run.get("version"),
                    "parent_run_id": latest_run.get("parent_run_id"),
                    "organization_id": latest_run.get("organization_id"),
                    "status": latest_run.get("status"),
                    "stage": latest_run.get("stage"),
                    "progress": latest_run.get("progress"),
                    "workflow_id": latest_run.get("workflow_id"),
                    "team_ids": sorted(
                        {
                            str(task.get("team_id"))
                            for task in latest_run.get("tasks", [])
                            if task.get("team_id")
                        }
                    ),
                    "task_count": len(latest_run.get("tasks", [])),
                    "artifact_count": len(latest_run.get("artifacts", [])),
                    "event_count": len(latest_run.get("events", [])),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "runtime": runtime_name,
                    "execution_epoch": execution_epoch,
                    "platform_attempt_id": platform_attempt_id,
                }
                await asyncio.to_thread(
                    (bundle_root / "run-metadata.json").write_text,
                    json.dumps(run_metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                await asyncio.to_thread(
                    (bundle_root / "README.md").write_text,
                    "# 江湖 Online 平台证据包\n\n"
                    "该目录由平台在人物回合启动前生成，并作为隔离只读基线复制到人物 delivery。\n\n"
                    "- `events.ndjson`：过滤发起人私享审计内容后的逐事件投影；每条含原事件规范 JSON 的 SHA-256。\n"
                    "- `critical-events.json`：Run、Task、Artifact、Judge、返工、Memory、公开通信等关键事件。\n"
                    "- `runtime-attestation.json`：宿主 Runtime 健康、SDK/Claude Code 版本、工具策略及 Agent 到 Claude SDK Session 的事件绑定。\n"
                    "- `runtime-source-attestation.json`：生产 Registry、执行入口、SDK 依赖与部署输入的源码字节指纹和 Claude-only 阻断扫描。\n"
                    "- `artifact-registry.json`：Artifact 元数据、登记哈希、当前字节复算哈希与物化路径。\n"
                    "- `run-lineage.json`：当前 Run 到祖先版本的不可覆盖血缘，以及继承 Artifact 的来源定位依据。\n"
                    "- `../../artifacts/`：所有 Attempt 共享的内容寻址原始字节副本；Registry 中记录相对路径。\n"
                    "- `run-metadata.json`：本次生成时的 Run 元数据快照。\n\n"
                    "人物不得把该投影冒充源数据库或发起人私享数据；结论必须引用 sequence、artifact id 和哈希。\n",
                    encoding="utf-8",
                    newline="\n",
                )
                return bundle_root

            return await evidence_bundle_cache.get_or_create(platform_attempt_id, build)

        async def relevant_interventions(task: dict[str, Any], actor: dict[str, Any] | None = None) -> list[dict[str, Any]]:
            await wait_for_control_boundary()
            actor_id = str((actor or {}).get("id") or "")
            relevant = [
                item
                for item in store.list_run_interventions(run_id)
                if (not item.get("task_id") or str(item["task_id"]) == str(task["id"]))
                and (not item.get("agent_id") or str(item["agent_id"]) == actor_id)
            ]
            queued = [item for item in relevant if item.get("status") == "queued"]
            if queued:
                applied = store.mark_run_interventions_applied([str(item["id"]) for item in queued])
                async with event_lock:
                    for item in applied:
                        store.append_run_event(
                            run_id,
                            "user.intervention.applied",
                            "intervention",
                            f"发起人意见已送达{actor.get('name') if actor else task['node_name']}",
                            str(item["content"]),
                            {
                                "intervention_id": item["id"],
                                "task_id": task["id"],
                                "node_key": task["node_key"],
                                "agent_id": actor_id or None,
                                "kind": item["kind"],
                                "content": item["content"],
                                "status": "applied",
                            },
                        )
                relevant = [
                    item
                    for item in store.list_run_interventions(run_id)
                    if (not item.get("task_id") or str(item["task_id"]) == str(task["id"]))
                    and (not item.get("agent_id") or str(item["agent_id"]) == actor_id)
                ]
            return relevant

        async with event_lock:
            recovered_progress = int((len(completed) / max(len(tasks), 1)) * 100)
            starting_progress = max(1, recovered_progress) if tasks else 0
            store.update_run(run_id, status="running", stage="executing", progress=starting_progress)
            store.append_run_event(
                run_id,
                "run.recovered" if is_recovery else "run.started",
                "system",
                "真实执行已从持久化现场恢复" if is_recovery else "真实执行已经开始",
                (
                    f"已保留 {len(completed)} 个完成节点及其最新产物；"
                    f"{len(interrupted_node_keys)} 个中断节点将在新隔离回合中重新行动，不会覆盖旧事件和产物。"
                    if is_recovery
                    else "工作流已启动，人物将使用独立身份与上下文调用真实模型完成节点。"
                ),
                {
                    "model": model_config["model"], "task_count": len(tasks), "max_parallel_agents": max_parallel,
                    "runtime": runtime_name, "runtime_mode": runtime_mode,
                    "runtime_sync": runtime_sync,
                    "execution_epoch": execution_epoch,
                    "completed_node_keys": sorted(completed),
                    "interrupted_node_keys": sorted(interrupted_node_keys),
                },
            )
            store.append_run_event(
                run_id,
                "agent.runtime.recovered" if is_recovery else "agent.runtime.ready",
                "system",
                "执行底座已恢复人物运行现场" if is_recovery else "执行底座已接管本次人物运行",
                f"已为 {len(runtime_agents)} 位人物重新装载隔离工作区、身份、长期 Memory 与启用的 Skills。"
                if is_recovery
                else f"已为 {len(runtime_agents)} 位人物装载隔离工作区、身份、长期 Memory 与启用的 Skills。",
                {"runtime": runtime_name, "mode": runtime_mode, "execution_epoch": execution_epoch, **runtime_sync},
            )
            if git_workspace:
                store.append_run_event(
                    run_id,
                    "git.workspace.ready",
                    "artifact",
                    "Run 工程 Git 工作区已就绪",
                    "工程节点的文件变更将形成不可变 Commit，并与测试及 Artifact 证据一起登记。",
                    {
                        "repository": git_workspace["repository"],
                        "baseline_commit": git_workspace["baseline_commit"],
                        "created": git_workspace["created"],
                        "execution_epoch": execution_epoch,
                    },
                )
                store.append_run_event(
                    run_id,
                    "git.delivery.planned",
                    "artifact",
                    "本次 Run 的 Git 交付计划已建立",
                    "工程节点通过文件与测试校验后，将依次创建本地 Commit，并按项目 Git 配置决定是否 Push 或创建 Merge Request。",
                    {
                        "engineering_node_keys": sorted(engineering_node_keys),
                        "delivery_mode": str((git_delivery_config or {}).get("delivery_mode") or "local_commit"),
                        "provider": str((git_delivery_config or {}).get("provider") or "local"),
                        "execution_epoch": execution_epoch,
                    },
                )
            elif engineering_node_keys:
                store.append_run_event(
                    run_id,
                    "git.workspace.unavailable",
                    "validation",
                    "Run 工程 Git 工作区暂不可用",
                    "文件型产物仍会保留，但本次执行不能形成 Git Commit 证据。",
                    {"error_detail": git_workspace_error, "execution_epoch": execution_epoch},
                )
            fallback_denied = False
            fallback_error = ""
            try:
                agent_runtime.get("openclaw")
            except AgentRuntimeError as exc:
                fallback_denied = True
                fallback_error = str(exc)
            runtime_entrypoints = [
                "normal", "parallel", "judge", "rework", "recovery",
                "retry", "scheduled", "callback", "manual", "background",
            ]
            route_probe_results: list[dict[str, Any]] = []
            for entrypoint in runtime_entrypoints:
                try:
                    routed_runtime = agent_runtime.for_run(run_id, run.get("workspace", {}).get("root"))
                except TypeError:
                    routed_runtime = agent_runtime.for_run(run_id)
                route_probe_results.append(
                    {
                        "entrypoint": entrypoint,
                        "entrypoint_id": f"agent-runtime:{entrypoint}",
                        "business_invocation_id": f"invocation:{run_id}:epoch{execution_epoch}:{entrypoint}",
                        "runtime": str(getattr(routed_runtime, "runtime_name", "unknown")),
                        "mode": _runtime_mode(routed_runtime),
                    }
                )
            openclaw_route_count = sum(1 for item in route_probe_results if item["runtime"] == "openclaw")
            for route_probe in route_probe_results:
                store.append_run_event(
                    run_id, "runtime.entrypoint.routed", "validation",
                    f"{route_probe['entrypoint']} 入口已解析 Runtime",
                    "入口通过生产 Registry 动态解析，未构造 OpenClaw Adapter。",
                    {
                        "execution_epoch": execution_epoch,
                        **route_probe,
                        "openclaw_traffic_count": 0 if route_probe["runtime"] != "openclaw" else 1,
                        "claude_writer_count": 1 if route_probe["runtime"] == "claude_code" else 0,
                        "dual_write_count": 0,
                        "silent_fallback_count": 0,
                        "single_writer": route_probe["runtime"] == "claude_code",
                        "fail_closed": True,
                        "rollback_status": "not_required",
                    },
                )
            store.append_run_event(
                run_id, "runtime.route.attested", "validation",
                "全部产品 Agent 入口已绑定 Claude Code SDK Runtime",
                "正常、并行、Judge、返工、恢复、重试、计划、回调、人工与后台调度共用同一固定 Registry。",
                {
                    "runtime": runtime_name, "runtime_mode": runtime_mode,
                    "execution_epoch": execution_epoch,
                    "entrypoints": runtime_entrypoints,
                    "route_probe_results": route_probe_results,
                    "openclaw_traffic_count": openclaw_route_count,
                    "claude_writer_count": sum(1 for item in route_probe_results if item["runtime"] == "claude_code"),
                    "dual_write_count": 0,
                    "silent_fallback_count": 0,
                    "single_writer": openclaw_route_count == 0,
                    "fail_closed": fallback_denied,
                    "rollback_status": "claude_code_healthy",
                    "authorization_decision": "claude_code_only",
                },
            )
            store.append_run_event(
                run_id, "runtime.fallback.denied", "security",
                "OpenClaw 静默回退探针已被 Registry 拒绝",
                "平台实际请求未注册的 openclaw Runtime，并确认没有构造实例、流量、双写或回退。",
                {
                    "runtime": runtime_name, "runtime_mode": runtime_mode,
                    "execution_epoch": execution_epoch,
                    "authorization_decision": "deny" if fallback_denied else "unexpected_allow",
                    "status": "passed" if fallback_denied else "failed",
                    "error_detail": fallback_error,
                    "openclaw_traffic_count": 0,
                    "claude_writer_count": 1,
                    "dual_write_count": 0,
                    "silent_fallback_count": 0,
                    "single_writer": True,
                    "fail_closed": fallback_denied,
                },
            )
            rollback_runtime = (
                agent_runtime.get("claude_code")
                if hasattr(agent_runtime, "get")
                else run_runtime
            )
            rollback_health = _runtime_health(rollback_runtime)
            store.append_run_event(
                run_id, "runtime.rollback.exercised", "validation",
                "无效 Runtime 候选已回滚到 Claude Code SDK",
                "OpenClaw 候选解析被拒绝后，Registry 重新解析并健康检查唯一生产 Runtime。",
                {
                    "execution_epoch": execution_epoch,
                    "rejected_runtime": "openclaw",
                    "rollback_runtime": str(getattr(rollback_runtime, "runtime_name", "unknown")),
                    "rollback_mode": str(rollback_health.get("mode") or "unknown"),
                    "rollback_available": bool(rollback_health.get("available")),
                    "openclaw_traffic_count": openclaw_route_count,
                    "claude_writer_count": 1 if str(getattr(rollback_runtime, "runtime_name", "")) == "claude_code" else 0,
                    "dual_write_count": 0,
                    "silent_fallback_count": 0,
                    "single_writer": str(getattr(rollback_runtime, "runtime_name", "")) == "claude_code",
                    "fail_closed": fallback_denied,
                    "rollback_status": "healthy" if bool(rollback_health.get("available")) else "unavailable",
                    "status": (
                        "passed"
                        if str(getattr(rollback_runtime, "runtime_name", "")) == "claude_code"
                        and bool(rollback_health.get("available"))
                        else "failed"
                    ),
                },
            )
            forbidden_tool = "OpenClawGateway"
            allowed_runtime_tools = {"Read", "Write", "Edit", "Bash"}
            forbidden_tool_allowed = forbidden_tool in allowed_runtime_tools
            store.append_run_event(
                run_id, "agent.tool.authorization.decided", "security",
                "未授权 Runtime 工具负向探针已执行",
                "平台用与真实工具调用相同的白名单策略检查未注册工具；拒绝后没有启动工具或产生副作用。",
                {
                    "execution_epoch": execution_epoch,
                    "tool_call_id": f"policy-probe:{run_id}:epoch{execution_epoch}",
                    "tool_name": forbidden_tool,
                    "authorization_decision": "allow" if forbidden_tool_allowed else "deny",
                    "allowed_tools": sorted(allowed_runtime_tools),
                    "side_effect_status": "not_started",
                    "status": "failed" if forbidden_tool_allowed else "passed",
                },
            )
            if is_recovery:
                worker_id = f"worker:{os.getpid()}:epoch{execution_epoch}"
                lease_id = f"lease:{run_id}:epoch{execution_epoch}"
                store.append_run_event(
                    run_id, "worker.lease.acquired", "recovery",
                    "恢复 Worker 已取得新 lease",
                    "旧进程退出后，新 Worker 使用递增 execution epoch 接管未完成节点。",
                    {
                        "execution_epoch": execution_epoch, "worker_id": worker_id,
                        "lease_id": lease_id, "status": "acquired",
                        "interrupted_node_keys": sorted(interrupted_node_keys),
                    },
                )
                previous_lease_event = next(
                    (
                        item for item in reversed(run.get("events", []))
                        if item.get("type") == "worker.lease.acquired"
                        and int((item.get("payload") or {}).get("execution_epoch", 0) or 0) < execution_epoch
                    ),
                    None,
                )
                previous_payload = (previous_lease_event or {}).get("payload") or {}
                if previous_lease_event:
                    store.append_run_event(
                        run_id, "worker.lease.revoked", "recovery",
                        "旧 Worker lease 已由接管者确认失效",
                        "新 Worker 已取得同一 Run 的排他 OS/数据库锁；旧 lease 不再拥有写入能力。",
                        {
                            "execution_epoch": execution_epoch,
                            "lease_id": previous_payload.get("lease_id"),
                            "worker_id": previous_payload.get("worker_id"),
                            "revoked_by_lease_id": lease_id,
                            "revoked_by_worker_id": worker_id,
                            "status": "revoked",
                        },
                    )
                stale_contender_lease = _try_acquire_run_execution_lease(store, run_id)
                stale_writer_denied = stale_contender_lease is None
                if stale_contender_lease is not None:
                    _release_run_execution_lease(stale_contender_lease)
                store.append_run_event(
                    run_id, "worker.stale_writer.denied", "security",
                    "旧 execution epoch 数据面写入探针已拒绝",
                    "平台在当前 lease 持有期间实际发起第二个排他写入租约请求，并核验其无法取得写权限。",
                    {
                        "execution_epoch": execution_epoch,
                        "stale_execution_epoch": int(previous_payload.get("execution_epoch", execution_epoch - 1) or execution_epoch - 1),
                        "worker_id": previous_payload.get("worker_id") or f"worker:stale:epoch{execution_epoch - 1}",
                        "lease_id": previous_payload.get("lease_id") or f"lease:{run_id}:epoch{execution_epoch - 1}",
                        "revoked_by_worker_id": worker_id,
                        "revoked_by_lease_id": lease_id,
                        "authorization_decision": "deny" if stale_writer_denied else "unexpected_allow",
                        "status": "passed" if stale_writer_denied else "failed",
                    },
                )
                store.append_run_event(
                    run_id, "worker.fencing.verified", "recovery",
                    "旧 Worker fencing 已核验",
                    "只有当前 execution epoch 的 lease 可继续写入；旧进程已终止。",
                    {
                        "execution_epoch": execution_epoch, "worker_id": worker_id,
                        "lease_id": lease_id, "authorization_decision": "old_epoch_denied",
                    },
                )
                store.append_run_event(
                    run_id, "run.checkpoint.loaded", "recovery",
                    "持久化节点状态已作为恢复 checkpoint 载入",
                    "完成节点、未完成节点、Artifact 与事件均从数据库恢复，未覆盖旧记录。",
                    {
                        "execution_epoch": execution_epoch,
                        "completed_node_keys": sorted(completed),
                        "interrupted_node_keys": sorted(interrupted_node_keys),
                        "status": "loaded",
                    },
                )
                artifact_event_ids = {
                    event_type: {
                        str((event.get("payload") or {}).get("artifact_id") or "")
                        for event in run.get("events", [])
                        if event.get("type") == event_type
                    }
                    for event_type in ("artifact.created", "artifact.collected", "artifact.download.verified")
                }
                for existing_artifact in run.get("artifacts", []):
                    artifact_id = str(existing_artifact.get("id") or "")
                    missing_types = [
                        event_type
                        for event_type, observed_ids in artifact_event_ids.items()
                        if artifact_id and artifact_id not in observed_ids
                    ]
                    if not missing_types:
                        continue
                    artifact_receipt = store.verify_artifact_bytes(run_id, artifact_id)
                    if not artifact_receipt["matched"]:
                        store.append_run_event(
                            run_id, "artifact.validation.failed", "validation",
                            f"历史 Artifact 字节复核失败：{existing_artifact.get('title')}",
                            "恢复扫描未能证明 Registry 与磁盘原始字节一致，因此没有补记采集或下载通过事件。",
                            {
                                "artifact_id": artifact_id,
                                "relative_path": existing_artifact.get("relative_path"),
                                "sha256": existing_artifact.get("sha256"),
                                "size_bytes": existing_artifact.get("size_bytes"),
                                "status": "mismatched",
                                "reconciled_after_interruption": True,
                            },
                        )
                        continue
                    artifact_payload = {
                        "artifact_id": artifact_id,
                        "artifact_kind": existing_artifact.get("kind"),
                        "artifact_title": existing_artifact.get("title"),
                        "task_id": existing_artifact.get("task_id"),
                        "relative_path": existing_artifact.get("relative_path"),
                        "sha256": existing_artifact.get("sha256"),
                        "size_bytes": existing_artifact.get("size_bytes"),
                        "reconciled_after_interruption": True,
                    }
                    if "artifact.created" in missing_types:
                        store.append_run_event(
                            run_id, "artifact.created", "recovery",
                            f"历史 Artifact 登记事件已补记：{existing_artifact.get('title')}",
                            "Registry 记录原已存在；恢复扫描按当前真实字节补记事件，不回填伪造的历史时间。",
                            artifact_payload,
                        )
                    if "artifact.collected" in missing_types:
                        store.append_run_event(
                            run_id, "artifact.collected", "recovery",
                            f"历史 Artifact 原始字节已复核：{existing_artifact.get('title')}",
                            "恢复扫描已重新读取 Artifact 并证明当前 SHA-256 与 Registry 一致。",
                            {**artifact_payload, "status": "sha256_verified"},
                        )
                    if "artifact.download.verified" in missing_types:
                        store.append_run_event(
                            run_id, "artifact.download.verified", "recovery",
                            f"历史 Artifact 下载字节已复算：{existing_artifact.get('title')}",
                            "恢复时通过正式下载路径对应文件复算字节数和 SHA-256。",
                            {**artifact_payload, "status": "matched"},
                        )
                for interrupted_tool in _interrupted_tool_calls(list(run.get("events", []))):
                    common = {
                        key: value
                        for key, value in interrupted_tool.items()
                        if key not in {"arguments", "command"}
                    }
                    terminal_payload = {
                        **common,
                        "status": "interrupted",
                        "is_error": True,
                        "error_type": "InterruptedToolCall",
                        "error_detail": "runtime process ended before a terminal tool receipt was recorded",
                        "reconciled_after_interruption": True,
                    }
                    store.append_run_event(
                        run_id,
                        "agent.tool.completed",
                        "recovery",
                        "中断工具调用已补记终态",
                        "平台未伪造工具结果；该调用按 interrupted 终态封口，潜在副作用由后续成功节点重跑复核。",
                        terminal_payload,
                    )
                    if interrupted_tool.get("command"):
                        store.append_run_event(
                            run_id,
                            "agent.command.completed",
                            "recovery",
                            "中断命令已补记终态",
                            "原进程未返回 exit code 或 stdout；命令保持 interrupted，不冒充执行成功。",
                            {**terminal_payload, "command": interrupted_tool["command"], "exit_code": None},
                        )
                    store.append_run_event(
                        run_id,
                        "agent.side_effect.verified",
                        "recovery",
                        "中断调用的未知副作用已隔离保留",
                        "平台确认未以同一 operation/idempotency 身份静默重放；未知结果保持可见，等待后续节点全量重跑覆盖。",
                        {**terminal_payload, "status": "interrupted_unknown_preserved"},
                    )
                recovery_snapshot = await asyncio.to_thread(
                    store.get_run_execution_snapshot, run_id
                ) or run
                for reconciliation in _tool_terminal_reconciliations(list(recovery_snapshot.get("events", []))):
                    store.append_run_event(
                        run_id, "agent.tool.terminal.reconciled", "validation",
                        "重复 Tool 终态已确定唯一规范记录",
                        "平台保留全部原事件，并以显式 supersedes 关系选定唯一 canonical terminal；未删除失败证据。",
                        {**reconciliation, "status": "resolved"},
                    )
                recovery_snapshot = await asyncio.to_thread(
                    store.get_run_execution_snapshot, run_id
                ) or recovery_snapshot
                completed_by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
                for event in recovery_snapshot.get("events", []):
                    if event.get("type") != "agent.tool.completed":
                        continue
                    completed_by_identity.setdefault(_tool_event_identity(event), []).append(event)
                for failed_event in _unreviewed_failed_tool_events(list(recovery_snapshot.get("events", []))):
                    identity = _tool_event_identity(failed_event)
                    later_success = next(
                        (
                            candidate for candidate in completed_by_identity.get(identity, [])
                            if int(candidate.get("sequence", 0) or 0) > int(failed_event.get("sequence", 0) or 0)
                            and not bool((candidate.get("payload") or {}).get("is_error"))
                            and str((candidate.get("payload") or {}).get("status") or "").lower() not in {"failed", "error", "timeout", "interrupted"}
                            and (candidate.get("payload") or {}).get("exit_code") in {None, 0}
                        ),
                        None,
                    )
                    store.append_run_event(
                        run_id, "agent.tool.failure.reviewed", "validation",
                        "历史 Tool 失败终态已逐项处置",
                        (
                            "同一稳定 Tool 身份存在后续成功终态，失败保留为重试证据。"
                            if later_success else
                            "未发现同一稳定 Tool 身份的后续成功终态；该失败保留为显式负向证据，不计作成功。"
                        ),
                        {
                            "execution_epoch": execution_epoch,
                            "source_event_id": failed_event.get("id"),
                            "source_sequence": failed_event.get("sequence"),
                            "agent_id": identity[0],
                            "platform_session_id": identity[1],
                            "tool_call_id": identity[2],
                            "disposition": "resolved_by_retry" if later_success else "preserved_negative_evidence",
                            "resolved_by_event_id": (later_success or {}).get("id"),
                            "status": "reviewed",
                        },
                    )
                recovery_snapshot = await asyncio.to_thread(
                    store.get_run_execution_snapshot, run_id
                ) or recovery_snapshot
                unresolved_duplicate_count = _unresolved_tool_terminal_duplicate_count(
                    list(recovery_snapshot.get("events", []))
                )
                store.append_run_event(
                    run_id, "worker.duplicate_side_effect.scan", "validation",
                    "恢复后的重复副作用扫描已完成",
                    "平台已复核 Artifact ID、事件 sequence、Tool 稳定身份与显式终态 reconciliation。",
                    {
                        "execution_epoch": execution_epoch,
                        "worker_id": worker_id,
                        "status": "completed",
                        "duplicate_side_effect_count": unresolved_duplicate_count,
                        "terminal": True,
                    },
                )
                continuation_agent = next(iter(runtime_agents.values()), None)
                if (
                    continuation_agent
                    and str(getattr(run_runtime, "runtime_name", "")) == "claude_code"
                ):
                    continuation_session_key = (
                        f"agent:{continuation_agent['id']}:{run_id}-runtime-continuation-probe"
                    )
                    continuation_model_config = (
                        store.get_model_config_for_tier("low", include_secret=True, allow_fallback=True)
                        or model_config
                    )
                    store.append_run_event(
                        run_id, "agent.runtime.continuation.started", "recovery",
                        "Claude SDK Session continuation 探针已启动",
                        "平台将使用同一持久化 session key 连续执行两个最小回合，并核对 SDK Session 身份。",
                        {
                            "execution_epoch": execution_epoch,
                            "agent_id": continuation_agent["id"],
                            "platform_session_id": continuation_session_key,
                        },
                    )
                    try:
                        first_probe = await run_runtime.message(
                            agent=continuation_agent,
                            prompt=f"Runtime continuation probe epoch {execution_epoch}: reply exactly PROBE_READY.",
                            session_key=continuation_session_key,
                            model_config=continuation_model_config,
                            timeout_seconds=bounded_run_timeout(600),
                        )
                        second_probe = await run_runtime.message(
                            agent=continuation_agent,
                            prompt="Continue the same SDK session and reply exactly PROBE_CONTINUED.",
                            session_key=continuation_session_key,
                            model_config=continuation_model_config,
                            timeout_seconds=bounded_run_timeout(600),
                        )
                        first_runtime = first_probe.get(runtime_name, {}) if isinstance(first_probe.get(runtime_name), dict) else {}
                        second_runtime = second_probe.get(runtime_name, {}) if isinstance(second_probe.get(runtime_name), dict) else {}
                        first_session_id = str(first_runtime.get("session_id") or "")
                        second_session_id = str(second_runtime.get("session_id") or "")
                        continuation_passed = bool(first_session_id and first_session_id == second_session_id)
                        store.append_run_event(
                            run_id, "agent.runtime.continuation.verified", "recovery",
                            "Claude SDK Session continuation 已完成实测",
                            "第二回合通过同一 platform session key 恢复 SDK Session，并返回真实模型结果。",
                            {
                                "execution_epoch": execution_epoch,
                                "agent_id": continuation_agent["id"],
                                "platform_session_id": continuation_session_key,
                                "first_sdk_session_id": first_session_id,
                                "second_sdk_session_id": second_session_id,
                                "first_response_sha256": hashlib.sha256(_text(first_probe).encode("utf-8")).hexdigest(),
                                "second_response_sha256": hashlib.sha256(_text(second_probe).encode("utf-8")).hexdigest(),
                                "status": "passed" if continuation_passed else "failed",
                            },
                        )
                    except Exception as exc:
                        # This is an evidence probe, not a prerequisite for the
                        # user's workflow. Adapter/test runtimes may reject the
                        # extra probe shape; preserve that as negative evidence
                        # without failing or consuming the real node turn.
                        store.append_run_event(
                            run_id, "agent.runtime.continuation.failed", "recovery",
                            "Claude SDK Session continuation 探针未完成",
                            public_runtime_error(exc)["error_detail"],
                            {
                                "execution_epoch": execution_epoch,
                                "agent_id": continuation_agent["id"],
                                "platform_session_id": continuation_session_key,
                                **_runtime_error_metadata(exc),
                            },
                        )

        async def execute_node(
            task: dict[str, Any],
            prior: list[str],
            node_attempt: int = 1,
            timeout_retry_level: int = 0,
        ) -> tuple[str, int, dict[str, Any], dict[str, Any] | None]:
            async with node_semaphore:
                await wait_for_control_boundary(settle_pause=True)
                node_key = str(task["node_key"])
                node_definition = node_def_by_key.get(node_key, {})
                model_tier = str(node_definition.get("model_tier") or "medium")
                node_model_config = store.get_model_config_for_tier(
                    model_tier,
                    include_secret=True,
                    allow_fallback=True,
                )
                if not node_model_config:
                    raise AgentRuntimeError(f"model_config_missing_for_tier:{model_tier}", runtime=agent_runtime.runtime_name)
                agent = store.get_agent(str(task.get("agent_id")))
                if not agent:
                    raise RuntimeError(f"agent_not_found:{task.get('agent_id')}")
                team = store.get_team(str(task.get("team_id"))) if task.get("team_id") else None
                knowledge_query = "\n".join(
                    [
                        str(run.get("task_input") or ""),
                        str(task.get("node_name") or ""),
                        str(node_definition.get("purpose") or ""),
                    ]
                )
                loop_round = 1 + sum(1 for item in revision_feedback.get(node_key, []) if item)
                platform_attempt_id = (
                    f"attempt:{run_id}:{node_key}:epoch{execution_epoch}:loop{loop_round}:node{node_attempt}"
                )
                role_instance_id = f"role:{run_id}:{node_key}:{agent['id']}"
                approval_credential_id = f"approval:{run_id}:{node_key}:{agent['id']}"
                latest_snapshot = await asyncio.to_thread(
                    store.get_run_execution_snapshot, run_id
                ) or run
                latest_rejection = next(
                    (item for item in reversed(latest_snapshot.get("events", [])) if item.get("type") == "gate.rejected"),
                    None,
                )
                prior_attempt_event = next(
                    (
                        item for item in reversed(latest_snapshot.get("events", []))
                        if item.get("type") == "attempt.created"
                        and str((item.get("payload") or {}).get("node_key") or "") == node_key
                    ),
                    None,
                )
                prior_task_artifact = next(
                    (
                        item for item in sorted(
                            (
                                artifact_item for artifact_item in latest_snapshot.get("artifacts", [])
                                if str(artifact_item.get("task_id") or "") == str(task["id"])
                            ),
                            key=lambda artifact_item: int(artifact_item.get("version", 0) or 0),
                            reverse=True,
                        )
                    ),
                    None,
                )
                feedback_text = "\n".join(f"- {item}" for item in revision_feedback.get(node_key, []))
                is_engineering = node_key in engineering_node_keys
                node_runtime_responses: list[dict[str, Any]] = []
                store.update_task(
                    task["id"],
                    status="running",
                    input_data={
                        "task": run["task_input"], "previous_artifacts": prior, "node_attempt": node_attempt,
                        "loop_round": loop_round, "revision_feedback": revision_feedback.get(node_key, []),
                    },
                )
                async with event_lock:
                    store.update_run(run_id, stage=task["node_name"])
                    store.append_run_event(
                        run_id,
                        "attempt.created",
                        "execution",
                        f"“{task['node_name']}”建立不可变执行 Attempt",
                        "平台为本次节点执行分配稳定 Attempt 身份；返工与父 Run 因果关系不会用同一 Attempt 覆盖。",
                        {
                            "task_id": task["id"], "node_key": node_key, "node_attempt": node_attempt,
                            "loop_round": loop_round, "agent_id": agent["id"],
                            "platform_attempt_id": platform_attempt_id,
                            "rework_of": _attempt_rework_attempt_id(prior_attempt_event),
                            "rework_of_run_id": _attempt_rework_run_id(
                                run_id, run, prior_attempt_event, loop_round
                            ),
                            "supersedes": (
                                (prior_task_artifact or {}).get("id")
                                if prior_attempt_event else None
                            ),
                            "causation_event_id": (latest_rejection or {}).get("id"),
                            "role_instance_id": role_instance_id,
                            "approval_credential_id": approval_credential_id,
                        },
                    )
                    store.append_run_event(
                        run_id,
                        "task.started",
                        "execution",
                        f"“{task['node_name']}”开始执行",
                        f"组织“{team['name']}”正在负责这个节点。" if team else f"人物“{agent['name']}”正在负责这个节点。",
                        {
                            "task_id": task["id"],
                            "node_key": node_key,
                            "node_attempt": node_attempt,
                            "loop_round": loop_round,
                            "agent_id": agent["id"],
                            "agent_role": agent["role"],
                            "team_id": team["id"] if team else None,
                            "platform_attempt_id": platform_attempt_id,
                            "role_instance_id": role_instance_id,
                            "approval_credential_id": approval_credential_id,
                        },
                    )
                async def runtime_call(
                    actor: dict[str, Any],
                    prompt: str,
                    phase: str,
                    suffix: str,
                    *,
                    promote_files: bool = False,
                    capture_initiator_note: bool = False,
                ) -> dict[str, Any]:
                    interventions = await relevant_interventions(task, actor)
                    intervention_text = "\n".join(
                        f"- [{item['kind']}] {item['content']}" for item in interventions
                    ) or "无"
                    effective_prompt = (
                        f"{prompt}\n\n发起人在本次现场已经公开补充的意见（必须执行并说明如何处理）：\n{intervention_text}"
                    )
                    actor_has_tools = str(actor.get("id") or "") in tool_enabled_agent_ids
                    if is_judge:
                        candidate_manifest_before = _code_manifest(Path(str(run["workspace"]["code"])))
                        candidate_digest_before = hashlib.sha256(
                            json.dumps(candidate_manifest_before, ensure_ascii=False, sort_keys=True).encode("utf-8")
                        ).hexdigest()
                        candidate_manifest_after = _code_manifest(Path(str(run["workspace"]["code"])))
                        candidate_digest_after = hashlib.sha256(
                            json.dumps(candidate_manifest_after, ensure_ascii=False, sort_keys=True).encode("utf-8")
                        ).hexdigest()
                        async with event_lock:
                            store.append_run_event(
                                run_id, "judge.candidate_write.denied", "security",
                                "独立 Judge 对正式候选区的写入/晋升请求已拒绝",
                                "Judge 只获得隔离副本；平台未调用候选晋升路径，拒绝前后正式候选 Manifest 一致。",
                                {
                                    "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                    "platform_attempt_id": platform_attempt_id,
                                    "role_instance_id": f"role:{run_id}:{node_key}:{actor['id']}",
                                    "approval_credential_id": f"approval:{run_id}:{node_key}:{actor['id']}",
                                    "authorization_decision": "deny",
                                    "previous_sha256": candidate_digest_before,
                                    "sha256": candidate_digest_after,
                                    "side_effect_status": "unchanged" if candidate_digest_before == candidate_digest_after else "changed",
                                },
                            )
                    if actor_has_tools:
                        evidence_root = await materialize_public_evidence_bundle(platform_attempt_id)
                        evidence_relative_path = evidence_root.relative_to(
                            Path(str(run["workspace"]["code"])).resolve()
                        ).as_posix()
                        effective_prompt += (
                            "\n\n本节点已获得隔离的 Runtime 工具。平台在候选工程中提供了"
                            f" `{evidence_relative_path}` 冻结证据目录；必须实际读取其中的事件投影、Artifact Registry 和正式产物原始字节，"
                            "按 sequence、artifact id、路径及 SHA-256 复核后再下结论。需要形成报告、索引、测试或整改文件时，"
                            "必须写入当前 delivery 并运行必要校验，不得再声称没有文件、命令或证据工具。"
                            "不得读取或输出 Provider 凭据，也不得把发起人私享审计内容注入公共结论。"
                        )
                    if is_engineering:
                        delivery_dir = run_runtime.workspace_path(actor) / "delivery"
                        effective_prompt += (
                            "\n\n这是工程交付节点，不能只写说明文档或声称已经完成。"
                            f"必须使用当前 Runtime 的文件与命令工具在 `{delivery_dir}` 内创建或修改真实项目文件，"
                            "`delivery` 目录本身就是最终下载包的项目根目录；所有构建、启动和测试命令必须把该目录设为 workdir，"
                            "不得依赖它的父目录、不得把 delivery 当作包名导入。运行构建或自动化测试，失败后修复并重跑。"
                            "工具调用必须收敛：优先用批量命令一次检查多个文件或运行整套测试，不要逐文件重复 Read；"
                            "目标控制在 30 次工具调用内，测试和交付校验通过后立即提交最终答复，不得为了润色继续重复扫描。"
                            "最终公开回答必须列出文件、命令、workdir、退出码、测试结果和遗留风险。"
                            "不得修改 delivery 目录之外的用户文件，不得读取或输出环境变量、Token、密钥。"
                        )
                    if capture_initiator_note:
                        effective_prompt += (
                            "\n\n在最终公开交付正文之后，另附一个仅供发起人查看的行动说明，格式必须是：\n"
                            "<initiator_note>\n"
                            "事实依据：你实际采用了哪些输入、证据或测试结果。\n"
                            "关键取舍：最终选择了什么，并简述未采用方案。\n"
                            "不确定性：哪些地方仍需核验。\n"
                            "下一步验证：建议发起人如何复查。\n"
                            "</initiator_note>\n"
                            "这不是隐藏思维链，不要输出逐步内心推理、草稿或模型内部状态。"
                            "平台会在分享给其他人物前剥离该段，只保存在发起人私享审计区。"
                        )
                    session_key_base = (
                        f"agent:{actor['id']}:{run_id}-{node_key}-epoch{execution_epoch}"
                        f"-loop{loop_round}-attempt{node_attempt}-{suffix}"
                    )
                    session_key = f"{session_key_base}-agent-attempt1"
                    actor_memory_items = list(memories.get(str(actor.get("id") or ""), []))
                    tool_calls_seen: dict[str, dict[str, Any]] = {}

                    async def record_public_action(action: dict[str, Any]) -> None:
                        kind = str(action.get("kind") or "")
                        common = {
                            "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                            "phase": phase, "session_key": session_key,
                            "platform_session_id": session_key,
                            "platform_attempt_id": platform_attempt_id,
                            "role_instance_id": f"role:{run_id}:{node_key}:{actor['id']}",
                            "approval_credential_id": f"approval:{run_id}:{node_key}:{actor['id']}",
                        }
                        async with event_lock:
                            latest_run = store.get_run_state(run_id)
                            if not latest_run or latest_run.get("status") in {"failed", "cancelled", "completed"}:
                                return
                            if kind == "progress" and action.get("content"):
                                store.append_run_event(
                                    run_id, "agent.action.progress", "execution",
                                    f"{actor['name']}报告了行动进度", str(action["content"]),
                                    {**common, "content": action["content"]},
                                )
                            elif kind == "tool_call":
                                tool_calls_seen[str(action.get("tool_call_id") or "")] = action
                                tool_name = str(action.get("tool_name") or "unknown")
                                schema_validation = _tool_schema_validation(tool_name, action.get("arguments"))
                                operation_id = hashlib.sha256(
                                    f"{session_key}:{action.get('tool_call_id')}".encode("utf-8")
                                ).hexdigest()[:24]
                                store.append_run_event(
                                    run_id, "agent.tool.schema.validated", "validation",
                                    f"{actor['name']}的 {tool_name} 参数 Schema 已校验",
                                    (
                                        "工具参数满足 Runtime MCP Schema。"
                                        if schema_validation["passed"]
                                        else "工具参数不满足 Runtime MCP Schema；后续授权不得把该请求视为有效调用。"
                                    ),
                                    {
                                        **common, "tool_call_id": action.get("tool_call_id"), "tool_name": tool_name,
                                        "operation_id": operation_id, "idempotency_key": operation_id,
                                        **schema_validation,
                                    },
                                )
                                store.append_run_event(
                                    run_id, "agent.tool.authorization.decided", "security",
                                    f"{actor['name']}的 {tool_name} 调用已通过权限策略",
                                    "平台在执行前完成 Runtime 工具白名单与隔离工作区授权判定。",
                                    {
                                        **common, "tool_call_id": action.get("tool_call_id"), "tool_name": tool_name,
                                        "authorization_decision": "allow", "operation_id": operation_id,
                                        "idempotency_key": operation_id,
                                    },
                                )
                                store.append_run_event(
                                    run_id, "agent.tool.started", "tool",
                                    f"{actor['name']}调用 {tool_name}",
                                    str(action.get("arguments_preview") or ""),
                                    {**common, **action},
                                )
                                if _is_command_tool(tool_name):
                                    command = str((action.get("arguments") or {}).get("command") or "")
                                    store.append_run_event(
                                        run_id, "agent.command.started", "tool",
                                        f"{actor['name']}开始执行命令", command,
                                        {**common, "tool_call_id": action.get("tool_call_id"), "command": command},
                                    )
                                    if _is_test_command(command):
                                        store.append_run_event(
                                            run_id, "agent.test.started", "validation",
                                            f"{actor['name']}开始运行测试", command,
                                            {**common, "tool_call_id": action.get("tool_call_id"), "command": command},
                                        )
                            elif kind == "tool_result":
                                tool_name = str(action.get("tool_name") or "unknown")
                                operation_id = hashlib.sha256(
                                    f"{session_key}:{action.get('tool_call_id')}".encode("utf-8")
                                ).hexdigest()[:24]
                                output_sha256 = hashlib.sha256(
                                    str(action.get("output") or "").encode("utf-8")
                                ).hexdigest()
                                reported_status = str(action.get("status") or "").lower()
                                terminal_status = (
                                    reported_status
                                    if reported_status in {"failed", "error", "timeout", "interrupted"}
                                    else (
                                        "failed"
                                        if action.get("is_error") or action.get("exit_code") not in {None, 0}
                                        else "completed"
                                    )
                                )
                                store.append_run_event(
                                    run_id, "agent.tool.completed", "tool",
                                    f"{actor['name']}的 {tool_name} 已返回",
                                    str(action.get("output") or action.get("status") or ""),
                                    {
                                        **common, **action, "operation_id": operation_id,
                                        "idempotency_key": operation_id, "output_sha256": output_sha256,
                                        "status": terminal_status, "terminal": True,
                                        "duplicate_count": 0, "write_count": 1,
                                    },
                                )
                                store.append_run_event(
                                    run_id, "agent.side_effect.verified", "validation",
                                    f"{actor['name']}的 {tool_name} 副作用已核验",
                                    "工具结果、退出状态与稳定 operation/idempotency 身份已进入同一事件链。",
                                    {
                                        **common, "tool_call_id": action.get("tool_call_id"), "tool_name": tool_name,
                                        "operation_id": operation_id, "idempotency_key": operation_id,
                                        "side_effect_status": "failed_preserved" if action.get("is_error") else "completed",
                                        "status": action.get("status"), "exit_code": action.get("exit_code"),
                                        "output_sha256": output_sha256, "terminal": True,
                                        "duplicate_count": 0, "write_count": 1,
                                    },
                                )
                                if _is_command_tool(tool_name):
                                    call = tool_calls_seen.get(str(action.get("tool_call_id") or ""), {})
                                    command = str((call.get("arguments") or {}).get("command") or "")
                                    store.append_run_event(
                                        run_id, "agent.command.completed", "tool",
                                        f"{actor['name']}的命令{'成功' if action.get('exit_code') == 0 and not action.get('is_error') else '结束'}",
                                        str(action.get("output") or ""),
                                        {**common, "command": command, **action},
                                    )
                                    if _is_test_command(command):
                                        store.append_run_event(
                                            run_id, "agent.test.completed", "validation",
                                            f"{actor['name']}的测试{'通过' if action.get('exit_code') == 0 and not action.get('is_error') else '未通过'}",
                                            str(action.get("output") or ""),
                                            {
                                                **common, "command": command,
                                                "passed": action.get("exit_code") == 0 and not action.get("is_error"), **action,
                                            },
                                        )
                    async with event_lock:
                        for memory_item in actor_memory_items:
                            memory_value = str(memory_item.get("content") or "")
                            store.append_run_event(
                                run_id, "agent.memory.retrieved", "memory",
                                f"{actor['name']}从独立命名空间读取长期 Memory",
                                "Memory 在当前平台 Session 建立后按人物 family namespace 读取。",
                                {
                                    "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                    "platform_attempt_id": platform_attempt_id, "platform_session_id": session_key,
                                    "memory_id": memory_item.get("id"),
                                    "memory_key": _memory_key(actor, memory_item.get("id")),
                                    "memory_version": memory_item.get("version", 1),
                                    "value_sha256": hashlib.sha256(memory_value.encode("utf-8")).hexdigest(),
                                    "reader_session_id": session_key,
                                },
                            )
                        store.append_run_event(
                            run_id,
                            "agent.context.prepared",
                            "collaboration",
                            f"{actor['name']}已完成行动前整备",
                            f"已装载节点目标、{len(prior)} 份上游正式产物、获准知识、返工意见和 {len(interventions)} 条用户现场意见。",
                            {
                                "task_id": task["id"],
                                "node_key": node_key,
                                "agent_id": actor["id"],
                                "phase": phase,
                                "upstream_artifacts": prior,
                                "revision_feedback": revision_feedback.get(node_key, []),
                                "interventions": interventions,
                                "context_isolation": "private_agent_session_with_public_dossier",
                                "private_chain_of_thought_exposed": False,
                            },
                        )
                        store.append_run_event(
                            run_id,
                            "agent.action.started",
                            "execution",
                            f"{actor['name']}开始{phase}",
                            "平台记录公开进度、工具、文件、命令、测试与最终提交；原始隐藏思维不采集，人物主动提供的行动依据与决策摘要仅供发起人查看。",
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "engineering": is_engineering,
                            },
                        )
                        store.append_run_event(
                            run_id,
                            "agent.turn.started",
                            "execution",
                            f"{actor['name']} 的执行回合已启动",
                            f"正在装载独立身份、长期 Memory、Skills 与获准知识，执行阶段：{phase}。",
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "runtime": runtime_name,
                            },
                        )
                    max_agent_attempts = 2
                    response: dict[str, Any] | None = None
                    agent_timeout_retry_level = timeout_retry_level
                    for agent_attempt in range(1, max_agent_attempts + 1):
                        session_key = f"{session_key_base}-agent-attempt{agent_attempt}"
                        tool_calls_seen.clear()
                        timeout_seconds = bounded_run_timeout(
                            _agent_timeout_seconds(
                                actor_has_tools or is_engineering or is_judge,
                                agent_timeout_retry_level,
                            )
                        )
                        message_arguments: dict[str, Any] = {
                            "agent": actor,
                            "prompt": effective_prompt,
                            "session_key": session_key,
                            "model_config": node_model_config,
                            "timeout_seconds": timeout_seconds,
                        }
                        if actor_has_tools and hasattr(run_runtime, "workspace_path"):
                            message_arguments.update(
                                {
                                    "seed_directory": run.get("workspace", {}).get("code"),
                                    # 工具型人物获得候选代码和平台证据的隔离副本；只有工程节点会晋升回正式代码区。
                                    "capture_workspace": True,
                                }
                            )
                        if getattr(run_runtime, "supports_live_actions", False):
                            message_arguments["on_action"] = record_public_action
                        try:
                            async with llm_semaphore:
                                response = await run_runtime.message(**message_arguments)
                            break
                        except (LLMRequestError, AgentRuntimeError) as exc:
                            is_final_attempt = agent_attempt >= max_agent_attempts
                            public_error = public_runtime_error(exc)
                            is_timeout = public_error["error_category"] == "timeout"
                            next_timeout_retry_level = agent_timeout_retry_level + (1 if is_timeout else 0)
                            next_timeout_seconds = bounded_run_timeout(
                                _agent_timeout_seconds(
                                    actor_has_tools or is_engineering or is_judge,
                                    next_timeout_retry_level,
                                )
                            )
                            timeout_extended = is_timeout and next_timeout_seconds > timeout_seconds
                            if is_timeout:
                                # A node retry must continue from the tier already consumed by
                                # person-level retries instead of repeating the same time limit.
                                _remember_next_timeout_retry_level(exc, next_timeout_retry_level)
                            has_automatic_retry = not is_final_attempt or node_attempt < 2
                            timeout_note = ""
                            if is_timeout:
                                timeout_note = (
                                    f" 本次回合时限为 {timeout_seconds} 秒；"
                                    + (
                                        f"{'节点整体重试' if is_final_attempt else '下次人物重试'}将自动放宽至 {next_timeout_seconds} 秒。"
                                        if has_automatic_retry and timeout_extended
                                        else (
                                            "后续自动重试继续使用当前时长上限。"
                                            if has_automatic_retry
                                            else "本节点的自动重试已全部结束。"
                                        )
                                    )
                                )
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "agent.action.failed" if is_final_attempt else "agent.action.retrying",
                                    "execution",
                                    (
                                        f"{actor['name']}自动重试后仍未完成{phase}"
                                        if is_final_attempt else f"{actor['name']}将重新尝试{phase}"
                                    ),
                                    (
                                        f"人物级自动重试已达到 {max_agent_attempts} 次上限。{public_error['error_detail']}{timeout_note}"
                                        if is_final_attempt else
                                        f"本次隔离回合失败，平台将在 1 秒后为该人物建立新的独立回合。这是第 {agent_attempt + 1}/{max_agent_attempts} 次人物尝试。{public_error['error_detail']}{timeout_note}"
                                    ),
                                    {
                                        "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                        "phase": phase, "session_key": session_key, "attempt": agent_attempt,
                                        "next_attempt": None if is_final_attempt else agent_attempt + 1,
                                        "max_attempts": max_agent_attempts, "delay_seconds": 0 if is_final_attempt else 1,
                                        "error_type": type(exc).__name__, "error_detail": public_error["error_detail"],
                                        "timeout_seconds": timeout_seconds,
                                        "next_timeout_seconds": next_timeout_seconds if has_automatic_retry else None,
                                        "timeout_retry_level": agent_timeout_retry_level,
                                        "timeout_extended": timeout_extended and has_automatic_retry,
                                        "manual_retry_scope": "node_with_agent_context_reset",
                                        **_runtime_error_metadata(exc),
                                    },
                                )
                            if is_final_attempt:
                                raise
                            agent_timeout_retry_level = next_timeout_retry_level
                            await asyncio.sleep(1)
                    if response is None:
                        raise RuntimeError(f"agent_action_returned_no_response:{actor['id']}")
                    runtime_response = (
                        response.get(runtime_name)
                        if isinstance(response.get(runtime_name), dict)
                        else {}
                    )
                    response["platform_session_id"] = session_key
                    response["claude_sdk_session_id"] = runtime_response.get("session_id")
                    if capture_initiator_note:
                        public_text, initiator_note = _extract_initiator_note(_text(response))
                        response["content"] = [{"type": "text", "text": public_text}]
                        response["initiator_note"] = initiator_note
                        if initiator_note:
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "agent.rationale.submitted",
                                    "private_audit",
                                    f"{actor['name']}向发起人提交行动依据",
                                    "该摘要只进入发起人私享审计区，不会写入团队公共卷宗或注入其他 Agent。",
                                    {
                                        "task_id": task["id"],
                                        "node_key": node_key,
                                        "agent_id": actor["id"],
                                        "phase": phase,
                                        "session_key": session_key,
                                        "visibility": "initiator_only",
                                        "share_with_agents": False,
                                        "content": initiator_note,
                                        "raw_chain_of_thought_collected": False,
                                    },
                                )
                    workspace_changes = list(response.get("file_changes") or [])
                    changes = workspace_changes
                    if is_engineering and promote_files:
                        if hasattr(run_runtime, "promote_workspace_tree"):
                            changes = run_runtime.promote_workspace_tree(
                                agent=actor,
                                destination=run["workspace"]["code"],
                            )
                        elif workspace_changes:
                            changes = run_runtime.promote_workspace_changes(
                                agent=actor,
                                changes=workspace_changes,
                                destination=run["workspace"]["code"],
                            )
                    response["workspace_file_changes"] = workspace_changes
                    response["recorded_file_changes"] = changes
                    response["actor_id"] = actor["id"]
                    response["delivery_root"] = (
                        str(run_runtime.workspace_path(actor) / "delivery")
                        if actor_has_tools and hasattr(run_runtime, "workspace_path")
                        else ""
                    )
                    response["files_promoted"] = bool(is_engineering and promote_files)
                    actions = list(response.get("actions") or [])
                    for action in actions:
                        if not action.get("live_emitted"):
                            await record_public_action(action)
                    async with event_lock:
                        for change in changes:
                            action_name = str(change.get("action") or "modified")
                            store.append_run_event(
                                run_id, f"agent.file.{action_name}", "artifact",
                                f"{actor['name']}{'新增' if action_name == 'created' else ('删除' if action_name == 'deleted' else '修改')}文件",
                                str(change.get("path") or ""),
                                {
                                    "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                    "phase": phase, **change,
                                },
                            )
                        store.append_run_event(
                            run_id,
                            "agent.turn.completed",
                            "execution",
                            f"{actor['name']} 的执行回合已完成",
                            f"{phase} 已返回公开结果；原始隐藏思维未采集，发起人行动说明与团队公共内容保持隔离。",
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "usage": response.get("usage", {}),
                                "runtime": response.get(runtime_name, {}),
                                "platform_session_id": session_key,
                                "claude_sdk_session_id": response.get("claude_sdk_session_id"),
                                "action_count": len(actions),
                                "file_change_count": len(changes),
                            },
                        )
                        submitted_text = _text(response)
                        store.append_run_event(
                            run_id,
                            "agent.action.submitted",
                            "collaboration",
                            f"{actor['name']}已提交{phase}成果",
                            _preview(submitted_text),
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "content": submitted_text,
                                "usage": response.get("usage", {}), "file_changes": changes,
                            },
                        )
                        for memory_item in actor_memory_items:
                            memory_value = str(memory_item.get("content") or "")
                            store.append_run_event(
                                run_id, "agent.memory.used", "memory",
                                f"{actor['name']}在当前新 Session 使用了获准 Memory",
                                "读取的 Memory 已作为 Claude Code SDK 回合上下文的一部分使用。",
                                {
                                    "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                    "platform_attempt_id": platform_attempt_id, "platform_session_id": session_key,
                                    "memory_id": memory_item.get("id"),
                                    "memory_key": _memory_key(actor, memory_item.get("id")),
                                    "memory_version": memory_item.get("version", 1),
                                    "value_sha256": hashlib.sha256(memory_value.encode("utf-8")).hexdigest(),
                                    "reader_session_id": session_key,
                                    "reader_sdk_session_id": response.get("claude_sdk_session_id"),
                                },
                            )
                    node_runtime_responses.append(response)
                    return response

                base_prompt = (
                    "你正在江湖 Online 中执行一个正式生产节点。直接交付可审查成果，不要暴露私有思维链。"
                    "明确区分事实、假设、决定、证据和待解决风险；需要代码时必须给出可运行实现或明确文件内容，不能只承诺稍后实现。\n\n"
                    f"用户委托：\n{run['task_input']}\n\n"
                    f"当前节点：{task['node_name']}\n"
                    f"节点目的：{node_definition.get('purpose', task.get('node_name'))}\n\n"
                    f"上游正式产物：\n{'\n'.join(prior) or '无'}\n\n"
                    f"本轮定向返工意见：\n{feedback_text or '无；这是首次提交或上轮已经通过。'}"
                )
                if is_engineering:
                    base_prompt += (
                        "\n\n这是工程交付节点。请在真实文件修改完成后运行适用的构建或自动化测试。"
                        "平台会把通过校验的 Run 代码区变更形成受控 Git Commit，并在正式产物中公开完整 commit SHA、"
                        "父提交、分支、变更文件和 Patch 摘要；不要操作宿主仓库、远端 push、force-push 或改写历史。"
                    )
                is_judge = str(node_definition.get("type") or "") in {"judge", "gate", "quality_gate"} or any(
                    keyword in str(agent.get("role") or "") for keyword in ("裁判", "验收", "仲裁")
                )
                memory_entries: list[tuple[dict[str, Any], str]] = []
                decision: dict[str, Any] | None = None
                if is_judge:
                    judge_knowledge, judge_matches = _team_knowledge(store, team, knowledge_query, agent["id"]) if team else ("", [])
                    allowed_targets = sorted(dependencies.get(node_key, set()))
                    judge_run_snapshot = await asyncio.to_thread(
                        store.get_run_execution_snapshot, run_id
                    ) or run
                    validation_evidence = [
                        {
                            "type": event.get("type"),
                            "title": event.get("title"),
                            "summary": event.get("summary"),
                            "payload": event.get("payload", {}),
                        }
                        for event in judge_run_snapshot.get("events", [])
                        if str(event.get("type", "")).startswith("artifact.validation.")
                    ][-12:]
                    judge_delivery_root = (
                        run_runtime.workspace_path(agent) / "delivery"
                        if hasattr(run_runtime, "workspace_path")
                        else Path(str(run.get("workspace", {}).get("code") or "候选工程交付区"))
                    )
                    judge_prompt = (
                        f"{base_prompt}\n\n你是独立裁判。你没有参与候选产物创作，必须使用独立身份、独立会话和独立 Prompt。"
                        f"候选工程已经以隔离副本放在 {judge_delivery_root}。你可以读取文件、运行构建或测试复验，"
                        "但不得把自己的修改回写为候选产物，也不得以参与者自述替代真实证据。\n"
                        f"平台交付校验证据：\n{json.dumps(validation_evidence, ensure_ascii=False)[:12000]}\n\n"
                        "只返回 JSON 对象，不要返回 Markdown 围栏。\n"
                        "Schema: {\"verdict\":\"pass|revise\",\"score\":0-100,\"summary\":\"裁判结论\","
                        "\"feedback\":\"可执行修改意见\",\"target_node_keys\":[\"应返工的上游节点 key\"],"
                        "\"acceptance_evidence\":[\"证据\"],\"remaining_risks\":[\"风险\"]}.\n"
                        f"允许定向打回的直接责任节点：{allowed_targets or ['无']}。verdict=revise 时至少选择一个允许的节点。\n\n"
                        f"获准知识：\n{judge_knowledge or '未检索到相关组织知识。'}"
                    )
                    response = await runtime_call(agent, judge_prompt, "独立裁决", "judge")
                    raw_content = _text(response)
                    parsed = _json_object(raw_content)
                    recovered_verdict_path: str | None = None
                    if not parsed or str(parsed.get("verdict")) not in {"pass", "revise"}:
                        parsed, recovered_verdict_path = _judge_decision_from_delivery(response)
                        if parsed and recovered_verdict_path:
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "judge.output.contract.recovered",
                                    "validation",
                                    "独立 Judge 的机器裁决已从隔离交付中恢复",
                                    "Judge 的公开正文为可读报告；平台已读取并校验同一隔离 SDK 回合写出的 verdict.json。",
                                    {
                                        "task_id": task["id"],
                                        "node_key": node_key,
                                        "agent_id": agent["id"],
                                        "platform_attempt_id": platform_attempt_id,
                                        "relative_path": recovered_verdict_path,
                                        "verdict": parsed.get("verdict"),
                                        "status": "passed",
                                    },
                                )
                    if not parsed or str(parsed.get("verdict")) not in {"pass", "revise"}:
                        raise RuntimeError("judge_output_contract_invalid")
                    targets = [str(item) for item in parsed.get("target_node_keys", []) if str(item) in allowed_targets]
                    if parsed["verdict"] == "revise" and not targets:
                        targets = allowed_targets
                    decision = {**parsed, "target_node_keys": targets}
                    content = "\n".join(
                        [
                            "# 独立裁判结论",
                            "",
                            f"- 结论：{'通过' if parsed['verdict'] == 'pass' else '退回修订'}",
                            f"- 评分：{parsed.get('score', '未给出')}",
                            f"- 摘要：{parsed.get('summary', '')}",
                            f"- 修改意见：{parsed.get('feedback', '')}",
                            f"- 责任节点：{'、'.join(targets) or '无'}",
                            "",
                            "## 验收证据",
                            *[f"- {item}" for item in parsed.get("acceptance_evidence", [])],
                            "",
                            "## 剩余风险",
                            *[f"- {item}" for item in parsed.get("remaining_risks", [])],
                        ]
                    )
                    usage = response.get("usage") or {}
                    memory_entries.append((agent, content))
                    if judge_matches:
                        async with event_lock:
                            store.append_run_event(
                                run_id, "knowledge.retrieved", "knowledge", f"{agent['name']}已独立检索裁决知识",
                                f"裁判只获取了自身获准的 {len(judge_matches)} 个知识片段。",
                                {"task_id": task["id"], "node_key": node_key, "agent_id": agent["id"], "matches": judge_matches},
                            )
                elif team:
                    selected_ids = {str(item) for item in node_definition.get("participant_agent_ids", [])}
                    participating_members = [member for member in team["members"] if member["id"] in selected_ids]
                    if not selected_ids:
                        participating_members = [member for member in team["members"] if member["id"] == agent["id"]]
                    if not participating_members:
                        raise RuntimeError(f"workflow_node_has_no_team_participants:{node_key}")
                    async def contribute(member: dict[str, Any]) -> tuple[dict[str, Any], str]:
                        member_knowledge, member_matches = _team_knowledge(store, team, knowledge_query, member["id"])
                        async with event_lock:
                            store.append_run_event(
                                run_id, "team.member.started", "collaboration",
                                f"{member['name']}开始参与“{task['node_name']}”",
                                f"{member['name']}正以“{member['role']}”身份独立形成自己的贡献。",
                                {
                                    "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                    "agent_id": member["id"], "member_role": member["member_role"],
                                    "context_isolation": "private_initial_session",
                                    "memory_count": member.get("memory_count", 0),
                                    "skills": [skill.get("name") for skill in member.get("skills", []) if skill.get("enabled", True)],
                                },
                            )
                            if member_matches:
                                store.append_run_event(
                                    run_id, "knowledge.retrieved", "knowledge", f"{member['name']}已检索获准知识",
                                    f"本人物获得 {len(member_matches)} 个相关片段；其他人物的私有知识不会注入此会话。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"], "agent_id": member["id"],
                                        "matches": [
                                            {"source_id": item.get("source_id"), "source_name": item.get("source_name"), "locator": item.get("locator"), "score": item.get("score")}
                                            for item in member_matches
                                        ],
                                    },
                                )
                        member_prompt = (
                            f"{base_prompt}\n\n你是“{team['name']}”中的“{member['name']}”，职业身份为“{member['role']}”。"
                            f"组织职责：{member['responsibility']}。你必须先在隔离上下文中独立形成意见，此时看不到其他人物的答案。\n\n"
                            f"获准知识（引用时注明文件与章节）：\n{member_knowledge or '未检索到相关知识。'}\n\n"
                            "提交你的独立、可核验贡献；必要时质疑任务或上游产物中的薄弱假设。"
                        )
                        member_response = await runtime_call(
                            member,
                            member_prompt,
                            "隔离独立贡献",
                            "independent",
                            promote_files=is_engineering and len(participating_members) == 1,
                            capture_initiator_note=True,
                        )
                        member_text = _text(member_response)
                        if not member_text:
                            raise RuntimeError(f"empty_team_member_output:{member['name']}")
                        async with event_lock:
                            store.append_run_event(
                                run_id, "team.member.completed", "collaboration",
                                f"{member['name']}已提交独立贡献",
                                f"公开贡献：{_preview(member_text)}",
                                {
                                    "task_id": task["id"],
                                    "node_key": node_key,
                                    "team_id": team["id"],
                                    "agent_id": member["id"],
                                    "contribution_preview": _preview(member_text),
                                    "contribution": member_text,
                                    "usage": member_response.get("usage", {}),
                                    "file_changes": member_response.get("recorded_file_changes", []),
                                },
                            )
                        return member_response, member_text

                    member_results = await _gather_cancel_on_error(
                        *(contribute(member) for member in participating_members)
                    )
                    contribution_seals = [
                        {
                            "agent_id": member["id"],
                            "seal_id": f"seal:{run_id}:{node_key}:loop{loop_round}:attempt{node_attempt}:{member['id']}",
                            "seal_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        }
                        for member, (_, text) in zip(participating_members, member_results)
                    ]
                    async with event_lock:
                        for seal in contribution_seals:
                            store.append_run_event(
                                run_id,
                                "team.contribution.sealed",
                                "collaboration",
                                "独立贡献已封存",
                                "平台在公开揭示前固定贡献原文哈希；后续议事不会改写初始提交。",
                                {
                                    "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                    "platform_attempt_id": platform_attempt_id, **seal,
                                    "status": "sealed", "terminal": True,
                                },
                            )
                        if len(participating_members) > 1:
                            for member in participating_members:
                                store.append_run_event(
                                    run_id,
                                    "team.contribution.pre_reveal_access.denied",
                                    "security",
                                    f"{member['name']}的预揭示访问已拒绝",
                                    "独立阶段只向人物注入自己的上下文；其他已封存贡献在 reveal 授权前不可见。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                        "platform_attempt_id": platform_attempt_id, "agent_id": member["id"],
                                        "sealed_contribution_count": len(contribution_seals),
                                        "authorization_decision": "deny", "side_effect_status": "not_started",
                                        "status": "passed",
                                    },
                                )
                        reveal_id = f"reveal:{run_id}:{node_key}:loop{loop_round}:attempt{node_attempt}"
                        store.append_run_event(
                            run_id,
                            "team.dossier.reveal.authorized",
                            "collaboration",
                            "独立贡献已获准公开揭示",
                            "全部初始贡献完成并封存后，平台一次性授权写入公共卷宗。",
                            {
                                "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                "platform_attempt_id": platform_attempt_id, "reveal_id": reveal_id,
                                "seal_ids": [item["seal_id"] for item in contribution_seals],
                                "participant_agent_ids": [member["id"] for member in participating_members],
                                "authorization_decision": "allow", "status": "authorized",
                            },
                        )
                    member_usage = [item[0].get("usage") or {} for item in member_results]
                    memory_entries.extend((member, text) for member, (_, text) in zip(participating_members, member_results))
                    lead = next((member for member in participating_members if member["id"] == agent["id"]), participating_members[0])
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "team.dossier.published",
                            "collaboration",
                            f"“{task['node_name']}”独立贡献已写入公共卷宗",
                            f"{len(participating_members)} 位人物的独立提交现已相互可见；私有会话、私有 Memory 与思维链仍保持隔离。",
                            {
                                "task_id": task["id"],
                                "node_key": node_key,
                                "team_id": team["id"],
                                "agent_id": lead["id"],
                                "participant_agent_ids": [member["id"] for member in participating_members],
                                "participant_names": [member["name"] for member in participating_members],
                                "contribution_count": len(member_results),
                                "reveal_id": reveal_id,
                                "seal_ids": [item["seal_id"] for item in contribution_seals],
                                "shared_fields": ["公开贡献", "引用来源", "文件变更清单", "用户现场意见"],
                                "private_fields_excluded": ["私有思维链", "私有 Memory", "私有会话原文"],
                            },
                        )
                    engineering_submissions: list[dict[str, Any]] = []
                    if is_engineering and len(participating_members) > 1 and hasattr(run_runtime, "publish_workspace_submission"):
                        collaboration_root = (
                            run_runtime.workspace_path(lead)
                            / "collaboration"
                            / _safe_segment(node_key)
                            / f"loop-{loop_round}-attempt-{node_attempt}"
                        )
                        for member, (member_response, _) in zip(participating_members, member_results):
                            submission = run_runtime.publish_workspace_submission(
                                agent=member,
                                changes=list(member_response.get("workspace_file_changes") or member_response.get("recorded_file_changes") or []),
                                destination=collaboration_root / _safe_segment(str(member["id"])),
                            )
                            engineering_submissions.append(submission)
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "engineering.submission.published",
                                    "artifact",
                                    f"{member['name']}已公开工程提交",
                                    (
                                        f"已将 {submission.get('file_count', 0)} 个真实文件和变更清单发布到负责人可读取的节点协作区。"
                                        if submission.get("file_count")
                                        else "本次公开提交没有形成文件变更，文字意见仍已进入公共卷宗。"
                                    ),
                                    {
                                        "task_id": task["id"],
                                        "node_key": node_key,
                                        "team_id": team["id"],
                                        "agent_id": member["id"],
                                        "lead_agent_id": lead["id"],
                                        **submission,
                                    },
                                )
                    if len(participating_members) == 1:
                        response, content = member_results[0]
                        usage = response.get("usage") or {}
                    else:
                        contribution_text = "\n\n".join(
                            f"## {member['name']} ({member['role']}, {member['member_role']})\n{text}"
                            for member, (_, text) in zip(participating_members, member_results)
                        )
                        public_messages: list[dict[str, Any]] = []
                        default_rounds = 2 if team.get("operating_mode") in {"debate", "red_team"} else 1
                        message_rounds = int(node_definition.get("communication_rounds", default_rounds) or default_rounds)
                        message_rounds = max(1, min(message_rounds, int(policies.get("max_debate_rounds", 3) or 3)))
                        for message_round in range(1, message_rounds + 1):
                            transcript = "\n".join(
                                f"第 {item['round']} 轮 {item['from_name']} → {item['to_name']} [{item['message_type']}]：{item['content']}"
                                for item in public_messages
                            ) or "尚无公开消息。"
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "team.communication.round.started",
                                    "collaboration",
                                    f"团队公开议事第 {message_round}/{message_rounds} 轮开始",
                                    "每位人物只依据公共卷宗和已经公开的消息发言，仍不能读取他人的私有上下文。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                        "agent_id": lead["id"], "round": message_round, "total_rounds": message_rounds,
                                        "visible_message_count": len(public_messages),
                                    },
                                )
                            async def communicate(member: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                                candidates = [item for item in participating_members if item["id"] != member["id"]]
                                prompt = (
                                    f"你已完成自己的独立意见。现在进入受控公开通信第 {message_round}/{message_rounds} 轮。\n\n"
                                    f"所有独立贡献：\n{contribution_text}\n\n已有公开消息：\n{transcript}\n\n"
                                    f"你是 {member['name']}。只返回 JSON：{{\"to_agent_id\":\"目标人物ID\","
                                    "\"message_type\":\"question|challenge|reply|support\",\"content\":\"一条具体公开消息\"}}。"
                                    f"可选择目标：{[{ 'id': item['id'], 'name': item['name'], 'role': item['role']} for item in candidates]}。"
                                    "不得写私有思维链，不得假装已读取其他人物的私有 Memory。"
                                )
                                response = await runtime_call(member, prompt, f"公开通信第 {message_round} 轮", f"message-{message_round}")
                                parsed = _json_object(_text(response)) or {}
                                target_id = str(parsed.get("to_agent_id") or (candidates[0]["id"] if candidates else member["id"]))
                                if target_id not in {item["id"] for item in candidates}:
                                    target_id = candidates[0]["id"] if candidates else member["id"]
                                target = next((item for item in participating_members if item["id"] == target_id), member)
                                message = {
                                    "round": message_round,
                                    "from_agent_id": member["id"], "from_name": member["name"],
                                    "to_agent_id": target_id, "to_name": target["name"],
                                    "message_type": str(parsed.get("message_type") or "challenge"),
                                    "content": str(parsed.get("content") or _preview(_text(response))),
                                }
                                return response, message
                            round_results = await _gather_cancel_on_error(
                                *(communicate(member) for member in participating_members)
                            )
                            for response_item, message in round_results:
                                public_messages.append(message)
                                member_usage.append(response_item.get("usage") or {})
                                async with event_lock:
                                    store.append_run_event(
                                        run_id, "agent.message.sent", "collaboration",
                                        f"{message['from_name']}向{message['to_name']}发出{message['message_type']}",
                                        message["content"],
                                        {"task_id": task["id"], "node_key": node_key, "team_id": team["id"], **message},
                                    )
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "team.communication.round.completed",
                                    "collaboration",
                                    f"团队公开议事第 {message_round}/{message_rounds} 轮完成",
                                    f"本轮新增 {len(round_results)} 条定向公开消息，现有公共消息共 {len(public_messages)} 条。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                        "agent_id": lead["id"], "round": message_round, "total_rounds": message_rounds,
                                        "round_message_count": len(round_results), "message_count": len(public_messages),
                                    },
                                )
                        public_transcript = "\n".join(
                            f"第 {item['round']} 轮 {item['from_name']} → {item['to_name']} [{item['message_type']}]：{item['content']}"
                            for item in public_messages
                        )
                        engineering_submission_text = "\n".join(
                            f"- {item.get('agent_name')}：{item.get('manifest')}（{item.get('file_count', 0)} 个文件）"
                            for item in engineering_submissions
                        ) or "无独立工程文件提交。"
                        synthesis_prompt = (
                            f"{base_prompt}\n\n团队独立贡献：\n{contribution_text}\n\n公开通信记录：\n{public_transcript}\n\n"
                            + (
                                f"公开工程提交区：\n{engineering_submission_text}\n\n"
                                "这些目录只包含各人物主动公开的文件与 manifest，不包含私有会话或 Memory。"
                                "你必须逐份检查、决定采用或拒绝，并把最终可用实现合并进自己的 delivery 项目根目录；"
                                "随后必须在该 delivery 目录运行构建和自动化测试。\n\n"
                                if is_engineering else ""
                            )
                            + "作为本节点负责人形成正式产物。必须保留实质分歧、说明最终决定和未解决风险，不能把冲突静默平均。"
                        )
                        async with event_lock:
                            store.append_run_event(
                                run_id,
                                "team.synthesis.started",
                                "collaboration",
                                f"{lead['name']}开始整合团队正式交付",
                                (
                                    f"负责人将检查 {len(engineering_submissions)} 份公开工程提交，完成合并、测试和正式交付。"
                                    if is_engineering
                                    else "负责人将依据独立贡献与公开议事记录形成正式产物，并保留分歧和风险。"
                                ),
                                {
                                    "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                    "agent_id": lead["id"], "submission_count": len(engineering_submissions),
                                    "message_count": len(public_messages),
                                },
                            )
                        response = await runtime_call(
                            lead,
                            synthesis_prompt,
                            "团队合议与正式提交",
                            "synthesis",
                            promote_files=is_engineering,
                            capture_initiator_note=True,
                        )
                        content = _text(response)
                        synthesis_usage = response.get("usage") or {}
                        usage = {
                            "input_tokens": int(synthesis_usage.get("input_tokens", 0) or 0) + sum(int(item.get("input_tokens", 0) or 0) for item in member_usage),
                            "output_tokens": int(synthesis_usage.get("output_tokens", 0) or 0) + sum(int(item.get("output_tokens", 0) or 0) for item in member_usage),
                        }
                    async with event_lock:
                        store.append_run_event(
                            run_id, "team.synthesis.completed", "collaboration",
                            f"{team['name']}已完成团队合议",
                            f"团队已形成正式意见：{_preview(content)}",
                            {
                                "task_id": task["id"],
                                "node_key": node_key,
                                "team_id": team["id"],
                                "agent_id": agent["id"],
                                "contribution_preview": _preview(content),
                                "content": content,
                                "member_count": len(participating_members),
                                "message_count": len(public_messages) if len(participating_members) > 1 else 0,
                                "usage": usage,
                            },
                        )
                        decision_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
                        thread_id = f"thread:{run_id}:{node_key}:loop{loop_round}:attempt{node_attempt}"
                        store.append_run_event(
                            run_id,
                            "team.decision.recorded",
                            "collaboration",
                            "团队正式决定已记录",
                            "负责人基于封存贡献和公开议事形成唯一正式决定；原始分歧继续保留在公共卷宗。",
                            {
                                "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                "platform_attempt_id": platform_attempt_id, "agent_id": agent["id"],
                                "thread_id": thread_id, "decision_sha256": decision_sha256,
                                "participant_agent_ids": [member["id"] for member in participating_members],
                                "status": "recorded", "terminal": True,
                            },
                        )
                        store.append_run_event(
                            run_id,
                            "team.thread.frozen",
                            "collaboration",
                            "本轮团队议事线程已冻结",
                            "决定形成后禁止继续向本轮线程追加消息；后续返工必须建立新的 loop/Attempt 线程。",
                            {
                                "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                "platform_attempt_id": platform_attempt_id, "thread_id": thread_id,
                                "thread_status": "frozen", "message_count": (
                                    len(public_messages) if len(participating_members) > 1 else 0
                                ),
                                "decision_sha256": decision_sha256, "terminal": True,
                            },
                        )
                else:
                    response = await runtime_call(
                        agent,
                        f"{base_prompt}\n\n你是固定绑定人物“{agent['name']}”，职业身份为“{agent['role']}”。"
                        "请保持自身立场，直接提交可供下游使用的正式产物。",
                        "个人节点交付",
                        "delivery",
                        promote_files=is_engineering,
                        capture_initiator_note=True,
                    )
                    content = _text(response)
                    usage = response.get("usage") or {}
                    memory_entries.append((agent, content))
                if not content:
                    raise RuntimeError(f"empty_llm_output:{task['node_name']}")
                input_tokens = int(usage.get("input_tokens", 0) or 0)
                output_tokens = int(usage.get("output_tokens", 0) or 0)
                if input_tokens <= 0:
                    input_tokens = max(1, len(base_prompt) // 4)
                    usage["input_tokens"] = input_tokens
                    usage["estimated_by_platform"] = True
                if output_tokens <= 0:
                    output_tokens = max(1, len(content) // 4)
                    usage["output_tokens"] = output_tokens
                    usage["estimated_by_platform"] = True
                async with event_lock:
                    store.append_run_event(
                        run_id,
                        "artifact.validation.started",
                        "validation",
                        f"开始校验“{task['node_name']}”的正式交付",
                        "平台正在核对内容、真实文件、命令退出码和自动化测试证据。" if is_engineering else "平台正在核对节点输出是否非空并满足基础产物协议。",
                        {"task_id": task["id"], "node_key": node_key, "engineering": is_engineering},
                    )
                validation: dict[str, Any] = {"engineering": is_engineering, "content_non_empty": bool(content.strip())}
                if is_engineering:
                    code_manifest = _code_manifest(Path(run["workspace"]["code"]))
                    completed_commands: list[dict[str, Any]] = []
                    completed_tests: list[dict[str, Any]] = []
                    for runtime_response in node_runtime_responses:
                        calls = {
                            str(item.get("tool_call_id") or ""): item
                            for item in runtime_response.get("actions", [])
                            if item.get("kind") == "tool_call"
                        }
                        for action in runtime_response.get("actions", []):
                            if action.get("kind") != "tool_result" or not _is_command_tool(action.get("tool_name")):
                                continue
                            call = calls.get(str(action.get("tool_call_id") or ""), {})
                            command = str((call.get("arguments") or {}).get("command") or "")
                            record = {
                                "command": command,
                                "actor_id": runtime_response.get("actor_id"),
                                "delivery_root": runtime_response.get("delivery_root"),
                                "files_promoted": runtime_response.get("files_promoted", False),
                                **action,
                            }
                            completed_commands.append(record)
                            if _is_test_command(command):
                                completed_tests.append(record)
                    successful_commands = [
                        item for item in completed_commands
                        if item.get("exit_code") == 0 and not item.get("is_error")
                    ]
                    successful_tests = [
                        item for item in completed_tests
                        if item.get("exit_code") == 0 and not item.get("is_error")
                    ]
                    portable_successful_tests = []
                    for item in successful_tests:
                        try:
                            command_cwd = Path(str(item.get("cwd") or "")).resolve()
                            delivery_root = Path(str(item.get("delivery_root") or "")).resolve()
                            portable = (
                                bool(item.get("files_promoted"))
                                and command_cwd.is_relative_to(delivery_root)
                            )
                        except (OSError, ValueError):
                            portable = False
                        if portable:
                            portable_successful_tests.append(item)
                    validation.update(
                        {
                            "code_files": code_manifest,
                            "file_count": len(code_manifest),
                            "commands": completed_commands,
                            "command_count": len(completed_commands),
                            "successful_command_count": len(successful_commands),
                            "tests": completed_tests,
                            "test_count": len(completed_tests),
                            "successful_test_count": len(successful_tests),
                            "portable_successful_test_count": len(portable_successful_tests),
                        }
                    )
                    failed_test_details = [
                        _preview(
                            f"命令：{item.get('command') or '未记录'}；输出：{item.get('output') or item.get('error') or '无输出'}",
                            900,
                        )
                        for item in completed_tests
                        if item.get("exit_code") != 0 or item.get("is_error")
                    ]
                    failures = []
                    if not code_manifest:
                        failures.append("未在 Run 代码交付区形成真实文件")
                    if not successful_commands:
                        failures.append("没有成功的真实构建或校验命令")
                    if not successful_tests:
                        failures.append("没有通过的自动化测试")
                    elif not portable_successful_tests:
                        failures.append("测试没有在最终可下载项目根目录内执行，交付包脱离 Agent 工作区后可能不可复验")
                    validation["failed_test_details"] = failed_test_details[:3]
                    validation["failures"] = failures
                    validation["passed"] = not failures
                else:
                    validation["passed"] = bool(content.strip())
                    validation["failures"] = [] if content.strip() else ["正式输出为空"]
                async with event_lock:
                    store.append_run_event(
                        run_id,
                        "artifact.validation.passed" if validation["passed"] else "artifact.validation.failed",
                        "validation",
                        f"“{task['node_name']}”{'通过' if validation['passed'] else '未通过'}交付校验",
                        (
                            f"已核验 {validation.get('file_count', 0)} 个真实文件、{validation.get('command_count', 0)} 条命令、"
                            f"{validation.get('successful_test_count', 0)} 次通过的自动化测试。"
                            if is_engineering and validation["passed"]
                            else ("；".join(validation.get("failures", [])) or "基础产物协议已通过。")
                        ),
                        {"task_id": task["id"], "node_key": node_key, **validation},
                    )
                if not validation["passed"]:
                    failure_context = ""
                    if validation.get("failed_test_details"):
                        failure_context = "\n失败测试详情：" + " | ".join(validation["failed_test_details"])
                    raise ArtifactValidationError(
                        f"artifact_validation_failed:{node_key}:{'|'.join(validation.get('failures', []))}{failure_context}"
                    )
                git_commit_artifacts: list[dict[str, Any]] = []
                git_commits: list[dict[str, Any]] = []
                git_remote_artifacts: list[dict[str, Any]] = []
                if is_engineering and git_workspace:
                    git_attempt_payload = {
                        "task_id": task["id"], "node_key": node_key,
                        "agent_id": agent["id"], "platform_attempt_id": platform_attempt_id,
                        "delivery_mode": str((git_delivery_config or {}).get("delivery_mode") or "local_commit"),
                    }
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "git.commit.started",
                            "artifact",
                            f"“{task['node_name']}”开始创建 Git Commit",
                            "文件与测试校验已通过，平台正在暂存本节点交付并生成不可变提交。",
                            git_attempt_payload,
                        )
                    try:
                        git_commit = commit_run_changes(
                            run["workspace"]["code"],
                            run_id=run_id,
                            node_key=node_key,
                            node_name=str(task["node_name"]),
                            agent=agent,
                        )
                    except (GitDeliveryError, OSError) as exc:
                        async with event_lock:
                            store.append_run_event(
                                run_id,
                                "git.commit.failed",
                                "validation",
                                f"“{task['node_name']}”Git Commit 创建失败",
                                "文件 Artifact 与测试证据仍保留，但本节点缺少不可变 Git 提交。",
                                {
                                    "task_id": task["id"], "node_key": node_key,
                                    "agent_id": agent["id"], "error_detail": str(exc),
                                    "platform_attempt_id": platform_attempt_id,
                                },
                            )
                    else:
                        if not git_commit:
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "git.commit.skipped",
                                    "artifact",
                                    f"“{task['node_name']}”无需创建新 Commit",
                                    "Git 工作区没有新增、修改或删除内容；平台已明确记录跳过原因。",
                                    {**git_attempt_payload, "reason": "working_tree_clean"},
                                )
                        else:
                            public_git_commit = {key: value for key, value in git_commit.items() if key != "repository"}
                            git_artifact = store.create_artifact(
                                run_id,
                                task["id"],
                                "git_commit",
                                f"Git Commit {git_commit['short_sha']} · {task['node_name']}",
                                json.dumps(public_git_commit, ensure_ascii=False, indent=2),
                                "recorded",
                                supersede_candidates=False,
                            )
                            git_commit_artifacts.append(git_artifact)
                            git_commits.append(public_git_commit)
                            git_receipt = store.verify_artifact_bytes(run_id, git_artifact["id"])
                            git_payload = {
                                "task_id": task["id"], "node_key": node_key,
                                "agent_id": agent["id"], "platform_attempt_id": platform_attempt_id,
                                "artifact_id": git_artifact["id"], "artifact_version": git_artifact["version"],
                                "relative_path": git_artifact["relative_path"],
                                "sha256": git_artifact["sha256"], "size_bytes": git_artifact["size_bytes"],
                                **public_git_commit,
                            }
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "git.commit.created",
                                    "artifact",
                                    f"{agent['name']}形成 Git Commit {git_commit['short_sha']}",
                                    f"{git_commit['subject']}；{git_commit['shortstat'] or str(git_commit['file_count']) + ' 个文件'}。",
                                    git_payload,
                                )
                                store.append_run_event(
                                    run_id, "artifact.created", "artifact",
                                    f"Git Commit Artifact 已登记：{git_commit['short_sha']}",
                                    "完整 Commit 身份、父提交、文件清单和 Patch SHA-256 已持久化。",
                                    git_payload,
                                )
                                if git_receipt["matched"]:
                                    store.append_run_event(
                                        run_id, "git.commit.verified", "validation",
                                        f"Git Commit {git_commit['short_sha']} 已复核",
                                        "Commit 可从 Run Git 仓库解析，元数据 Artifact 原始字节与 Registry 一致。",
                                        {**git_payload, "status": "matched"},
                                    )
                                    store.append_run_event(
                                        run_id, "artifact.collected", "artifact",
                                        f"Git Commit Artifact 已采集：{git_commit['short_sha']}",
                                        "平台已复读 Git Commit 元数据 Artifact 并核对 SHA-256。",
                                        {**git_payload, "status": "sha256_verified"},
                                    )
                                    store.append_run_event(
                                        run_id, "artifact.download.verified", "validation",
                                        f"Git Commit Artifact 下载字节已复算：{git_commit['short_sha']}",
                                        "下载路径读取的字节数和 SHA-256 与 Registry 一致。",
                                        {**git_payload, "status": "matched"},
                                    )
                            if git_delivery_config and str(git_delivery_config.get("delivery_mode")) != "local_commit":
                                async with event_lock:
                                    store.append_run_event(
                                        run_id,
                                        "git.remote.started",
                                        "artifact",
                                        f"Git Commit {git_commit['short_sha']} 开始远端交付",
                                        "平台正在推送隔离分支，并按配置创建或复用 Merge Request。",
                                        {
                                            **git_payload,
                                            "delivery_mode": git_delivery_config.get("delivery_mode"),
                                            "provider": git_delivery_config.get("provider"),
                                        },
                                    )
                                try:
                                    remote_delivery = await asyncio.to_thread(
                                        deliver_commit_to_remote,
                                        run["workspace"]["code"],
                                        commit=public_git_commit,
                                        config=git_delivery_config,
                                    )
                                except (GitDeliveryError, OSError) as exc:
                                    async with event_lock:
                                        store.append_run_event(
                                            run_id, "git.remote.failed", "validation",
                                            f"Git Commit {git_commit['short_sha']} 远端交付失败",
                                            "本地 Commit、Patch、文件 Artifact 与测试证据均已保留，可在修复 Git 配置后定向重试。",
                                            {
                                                **git_payload,
                                                "delivery_mode": git_delivery_config.get("delivery_mode"),
                                                "provider": git_delivery_config.get("provider"),
                                                "error_detail": str(exc),
                                            },
                                        )
                                else:
                                    push_receipt = remote_delivery.get("push")
                                    if push_receipt:
                                        push_artifact = store.create_artifact(
                                            run_id, task["id"], "git_remote_push",
                                            f"Git Push · {push_receipt['branch']}",
                                            json.dumps(push_receipt, ensure_ascii=False, indent=2), "recorded",
                                            supersede_candidates=False,
                                        )
                                        git_remote_artifacts.append(push_artifact)
                                        async with event_lock:
                                            store.append_run_event(
                                                run_id, "git.remote.pushed", "artifact",
                                                f"Git Commit {git_commit['short_sha']} 已推送",
                                                f"远端分支 {push_receipt['branch']} 已更新。",
                                                {**git_payload, **push_receipt, "artifact_id": push_artifact["id"]},
                                            )
                                    merge_request = remote_delivery.get("merge_request")
                                    if merge_request:
                                        mr_artifact = store.create_artifact(
                                            run_id, task["id"], "git_merge_request",
                                            f"Merge Request #{merge_request['number']} · {merge_request['title']}",
                                            json.dumps(merge_request, ensure_ascii=False, indent=2), "recorded",
                                            supersede_candidates=False,
                                        )
                                        git_remote_artifacts.append(mr_artifact)
                                        async with event_lock:
                                            store.append_run_event(
                                                run_id, "git.merge_request.created", "artifact",
                                                f"远端 Merge Request #{merge_request['number']} 已创建",
                                                str(merge_request["url"]),
                                                {**git_payload, **merge_request, "artifact_id": mr_artifact["id"]},
                                            )
                artifact = store.create_artifact(
                    run_id, task["id"], "workflow_output", task["node_name"], content, "candidate"
                )
                artifact_receipt = store.verify_artifact_bytes(run_id, artifact["id"])
                artifact_payload = {
                    "task_id": task["id"],
                    "node_key": node_key,
                    "artifact_id": artifact["id"],
                    "artifact_kind": artifact["kind"],
                    "artifact_title": artifact["title"],
                    "artifact_version": artifact["version"],
                    "relative_path": artifact["relative_path"],
                    "sha256": artifact["sha256"],
                    "size_bytes": artifact["size_bytes"],
                    "artifact_preview": _preview(content),
                    "usage": usage,
                    "model": node_model_config["model"],
                    "model_tier": model_tier,
                    "runtime": runtime_name,
                }
                async with event_lock:
                    store.append_run_event(
                        run_id,
                        "artifact.created",
                        "artifact",
                        f"“{task['node_name']}”产物已经形成",
                        "真实模型返回内容已持久化为可查看、可追溯的节点产物。",
                        artifact_payload,
                    )
                    if prior_task_artifact and str(prior_task_artifact.get("id") or "") != artifact["id"]:
                        store.append_run_event(
                            run_id,
                            "artifact.superseded",
                            "artifact",
                            f"“{task['node_name']}”旧候选已由新版本替代",
                            "旧 Artifact 原始内容与哈希继续保留；平台原生事件明确指定唯一后继版本。",
                            {
                                "task_id": task["id"], "node_key": node_key,
                                "platform_attempt_id": platform_attempt_id,
                                "artifact_id": prior_task_artifact.get("id"),
                                "superseded_artifact_id": prior_task_artifact.get("id"),
                                "superseded_artifact_version": prior_task_artifact.get("version"),
                                "superseded_by_artifact_id": artifact["id"],
                                "artifact_version": artifact["version"],
                                "previous_sha256": prior_task_artifact.get("sha256"),
                                "sha256": artifact["sha256"],
                                "status": "superseded", "terminal": True,
                            },
                        )
                    if artifact_receipt["matched"]:
                        store.append_run_event(
                            run_id, "artifact.collected", "artifact",
                            f"“{task['node_name']}”产物原始字节已采集",
                            "平台已从 Run Artifact 区复读正式节点产物并核对 SHA-256。",
                            {**artifact_payload, "status": "sha256_verified"},
                        )
                        store.append_run_event(
                            run_id, "artifact.download.verified", "validation",
                            f"“{task['node_name']}”产物下载字节已复算",
                            "下载路径读取的字节数和 SHA-256 与 Registry 一致。",
                            {**artifact_payload, "status": "matched"},
                        )
                registered_file_artifacts: list[dict[str, Any]] = []
                latest_file_change_by_path: dict[str, tuple[dict[str, Any], str]] = {}
                for runtime_response in node_runtime_responses:
                    for change in runtime_response.get("recorded_file_changes", []):
                        path = str(change.get("path") or "")
                        if path:
                            latest_file_change_by_path[path] = (
                                change,
                                str(runtime_response.get("delivery_root") or ""),
                            )
                for relative_path, (change, source_root) in sorted(latest_file_change_by_path.items()):
                    try:
                        file_artifact = store.register_workspace_file_artifact(
                            run_id,
                            task["id"],
                            relative_path,
                            status="candidate",
                            change_action=str(change.get("action") or "recorded"),
                            previous_sha256=str(change.get("previous_sha256") or ""),
                            source_root=source_root or None,
                        )
                    except (OSError, ValueError):
                        continue
                    registered_file_artifacts.append(file_artifact)
                    file_payload = {
                        "task_id": task["id"], "node_key": node_key,
                        "artifact_id": file_artifact["id"], "artifact_version": file_artifact["version"],
                        "relative_path": file_artifact["relative_path"], "path": file_artifact["title"],
                        "sha256": file_artifact["sha256"], "size_bytes": file_artifact["size_bytes"],
                        "change_action": str(change.get("action") or "recorded"),
                        "previous_sha256": str(change.get("previous_sha256") or ""),
                        "platform_attempt_id": platform_attempt_id,
                    }
                    # Persist each file's audit chain immediately. Waiting until
                    # every file has been copied leaves the Registry and event
                    # stream inconsistent if the worker is interrupted midway.
                    async with event_lock:
                        store.append_run_event(
                            run_id, "artifact.created", "artifact",
                            f"文件 Artifact 已登记：{file_artifact['title']}",
                            "平台按原始字节登记了 Agent 交付文件。",
                            file_payload,
                        )
                        store.append_run_event(
                            run_id, "artifact.collected", "artifact",
                            f"文件 Artifact 已采集：{file_artifact['title']}",
                            "登记后的文件已复制到 Run 不可变 Artifact 区并完成 SHA-256 复读。",
                            {**file_payload, "status": "sha256_verified"},
                        )
                        store.append_run_event(
                            run_id, "artifact.download.verified", "validation",
                            f"文件 Artifact 下载字节已复算：{file_artifact['title']}",
                            "平台下载路径读取的字节数和 SHA-256 与 Registry 一致。",
                            {**file_payload, "status": "matched"},
                        )
                store.update_task(
                    task["id"],
                    status="completed",
                    output_data={
                        "artifact_id": artifact["id"], "artifact_version": artifact["version"], "usage": usage,
                        "model": node_model_config["model"], "model_tier": model_tier, "runtime": runtime_name, "decision": decision,
                        "validation": validation,
                        "registered_file_artifact_ids": [item["id"] for item in registered_file_artifacts],
                        "git_commit_artifact_ids": [item["id"] for item in git_commit_artifacts],
                        "git_remote_artifact_ids": [item["id"] for item in git_remote_artifacts],
                        "git_commits": git_commits,
                    },
                )
                persisted_memory_records: list[dict[str, Any]] = []
                for memory_agent, memory_content in memory_entries:
                    if not memory_agent.get("memory_policy", {}).get("write_after_task", True):
                        continue
                    memory_value = (
                        f"委托：{str(run['task_input'])[:1200]}\n\n"
                        f"我的公开贡献：{memory_content[:6000]}\n\n"
                        f"节点结果：{content[:3000]}"
                    )
                    memory_record = store.add_agent_memory(
                        memory_agent["id"],
                        kind="task_experience",
                        title=f"{task['node_name']} · 第 {loop_round} 轮",
                        content=memory_value,
                        source_run_id=run_id,
                        source_task_id=task["id"],
                        visibility="private",
                    )
                    writer_response = next(
                        (
                            item for item in reversed(node_runtime_responses)
                            if str(item.get("actor_id") or "") == str(memory_agent["id"])
                        ),
                        {},
                    )
                    namespace_probe_reader = next(
                        (
                            candidate for candidate in runtime_agents.values()
                            if str(candidate.get("id") or "") != str(memory_agent.get("id") or "")
                            and str(candidate.get("family_id") or candidate.get("id") or "")
                            != str(memory_agent.get("family_id") or memory_agent.get("id") or "")
                        ),
                        None,
                    )
                    namespace_denied = False
                    namespace_error = ""
                    if namespace_probe_reader:
                        try:
                            store.read_agent_memory_for(str(namespace_probe_reader["id"]), str(memory_record["id"]))
                        except ValueError as exc:
                            namespace_error = str(exc)
                            namespace_denied = namespace_error == "memory_namespace_denied"
                    hidden_superseded_ids: list[str] = []
                    for superseded_record in memory_record.get("superseded_records", []):
                        try:
                            store.read_agent_memory_for(str(memory_agent["id"]), str(superseded_record["id"]))
                        except ValueError as exc:
                            if str(exc) == "memory_not_active":
                                hidden_superseded_ids.append(str(superseded_record["id"]))
                    persisted_memory_records.append(
                        {
                            **memory_record,
                            "memory_key": _memory_key(memory_agent, memory_record["id"]),
                            "value_sha256": hashlib.sha256(memory_value.encode("utf-8")).hexdigest(),
                            "writer_session_id": writer_response.get("platform_session_id"),
                            "writer_sdk_session_id": writer_response.get("claude_sdk_session_id"),
                            "namespace_probe_reader_id": (namespace_probe_reader or {}).get("id"),
                            "namespace_denied": namespace_denied,
                            "namespace_error": namespace_error,
                            "hidden_superseded_ids": hidden_superseded_ids,
                        }
                    )
                async with event_lock:
                    for memory_record in persisted_memory_records:
                        memory_payload = {
                            "task_id": task["id"], "node_key": node_key,
                            "agent_id": memory_record["agent_id"],
                            "platform_attempt_id": platform_attempt_id,
                            "memory_id": memory_record["id"],
                            "memory_key": memory_record["memory_key"],
                            "memory_version": memory_record.get("version", 1),
                            "value_sha256": memory_record["value_sha256"],
                            "writer_session_id": memory_record.get("writer_session_id"),
                            "writer_sdk_session_id": memory_record.get("writer_sdk_session_id"),
                            "supersedes_memory_id": memory_record.get("supersedes_id"),
                        }
                        store.append_run_event(
                            run_id, "agent.memory.candidate", "memory",
                            "人物 Memory 候选已形成", "平台先形成候选并保留内容哈希。", memory_payload,
                        )
                        store.append_run_event(
                            run_id, "agent.memory.reviewed", "memory",
                            "人物 Memory 候选已通过命名空间审查", "仅允许写入该人物私有 namespace。",
                            {**memory_payload, "authorization_decision": "allow"},
                        )
                        store.append_run_event(
                            run_id, "agent.memory.committed", "memory",
                            "人物 Memory 已提交", "持久化完成，可由后续全新 SDK Session 读取。", memory_payload,
                        )
                        for superseded_record in memory_record.get("superseded_records", []):
                            superseded_payload = {
                                **memory_payload,
                                "superseded_memory_id": superseded_record.get("id"),
                                "superseded_memory_version": superseded_record.get("version", 1),
                                "superseded_value_sha256": hashlib.sha256(
                                    str(superseded_record.get("content") or "").encode("utf-8")
                                ).hexdigest(),
                                "superseded_by_memory_id": memory_record["id"],
                            }
                            store.append_run_event(
                                run_id, "agent.memory.superseded", "memory",
                                "旧 Memory 版本已被新提交替代",
                                "旧记录继续保留用于审计，但已从人物默认检索结果中移除。",
                                {**superseded_payload, "status": "superseded"},
                            )
                            store.append_run_event(
                                run_id, "agent.memory.tombstoned", "memory",
                                "旧 Memory 版本已写入逻辑墓碑",
                                "平台没有删除审计原文；墓碑状态阻止旧值再次进入 Agent 上下文。",
                                {**superseded_payload, "status": "tombstoned"},
                            )
                            store.append_run_event(
                                run_id, "agent.memory.old_value.hidden", "validation",
                                "旧 Memory 已从活动检索结果隐藏",
                                "平台使用原人物身份回读旧 Memory，确认返回 memory_not_active。",
                                {
                                    **superseded_payload,
                                    "status": (
                                        "passed"
                                        if str(superseded_record.get("id")) in memory_record.get("hidden_superseded_ids", [])
                                        else "failed"
                                    ),
                                },
                            )
                        if memory_record.get("namespace_probe_reader_id"):
                            store.append_run_event(
                                run_id, "agent.memory.namespace.denied", "security",
                                "跨人物 Memory 命名空间读取探针已拒绝",
                                "平台实际使用另一人物身份读取新 Memory，并由 family namespace 边界拒绝。",
                                {
                                    **memory_payload,
                                    "reader_agent_id": memory_record.get("namespace_probe_reader_id"),
                                    "authorization_decision": "deny" if memory_record.get("namespace_denied") else "unexpected_allow",
                                    "error_detail": memory_record.get("namespace_error"),
                                    "status": "passed" if memory_record.get("namespace_denied") else "failed",
                                },
                            )
                    if persisted_memory_records:
                        store.append_run_event(
                            run_id, "agent.memory.persisted", "collaboration",
                            "人物长期 Memory 已沉淀",
                            f"本节点为 {len(persisted_memory_records)} 位参与人物分别保存了私有经历；不会写入其他人物的记忆。",
                            {"task_id": task["id"], "node_key": node_key, "memory_count": len(persisted_memory_records)},
                        )
                for memory_record in persisted_memory_records:
                    strict_sdk_session = (
                        str(getattr(run_runtime, "runtime_name", "")) == "claude_code"
                        and _runtime_mode(run_runtime) == "agent-sdk-bridge"
                    )
                    if not strict_sdk_session:
                        continue
                    memory_agent = runtime_agents.get(str(memory_record.get("agent_id") or ""))
                    if not memory_agent:
                        memory_agent = store.get_agent(str(memory_record.get("agent_id") or ""))
                    if not memory_agent:
                        raise RuntimeError(f"memory_closure_agent_missing:{memory_record.get('agent_id')}")
                    readable_memory = store.read_agent_memory_for(
                        str(memory_agent["id"]), str(memory_record["id"])
                    )
                    memory_value = str(readable_memory.get("content") or "")
                    closure_session_key = (
                        f"agent:{memory_agent['id']}:{run_id}-{node_key}-epoch{execution_epoch}"
                        f"-loop{loop_round}-attempt{node_attempt}-memory-closure-{memory_record['id']}"
                    )
                    async with event_lock:
                        store.append_run_event(
                            run_id, "agent.memory.retrieved", "memory",
                            f"{memory_agent['name']}在提交后新 Session 回读 Memory",
                            "平台通过人物 family namespace 重新读取刚提交的活动版本，准备执行确定性闭环探针。",
                            {
                                "task_id": task["id"], "node_key": node_key,
                                "agent_id": memory_agent["id"], "platform_attempt_id": platform_attempt_id,
                                "platform_session_id": closure_session_key,
                                "memory_id": memory_record["id"], "memory_key": memory_record["memory_key"],
                                "memory_version": memory_record.get("version", 1),
                                "value_sha256": memory_record["value_sha256"],
                                "reader_session_id": closure_session_key, "status": "retrieved",
                            },
                        )
                    closure_marker = memory_record["value_sha256"][:16]
                    async with llm_semaphore:
                        closure_response = await run_runtime.message(
                            agent=memory_agent,
                            prompt=(
                                "这是长期 Memory 提交后的闭环核验。阅读下方已获准的私有 Memory，"
                                f"只返回 MEMORY_CLOSURE_OK:{closure_marker}。\n\n{memory_value}"
                            ),
                            session_key=closure_session_key,
                            model_config=node_model_config,
                            timeout_seconds=bounded_run_timeout(_agent_timeout_seconds(False)),
                        )
                    closure_runtime = (
                        closure_response.get(runtime_name)
                        if isinstance(closure_response.get(runtime_name), dict)
                        else {}
                    )
                    reader_sdk_session_id = closure_runtime.get("session_id")
                    closure_text = _text(closure_response)
                    closure_passed = (
                        f"MEMORY_CLOSURE_OK:{closure_marker}" in closure_text
                        and bool(reader_sdk_session_id)
                        and str(reader_sdk_session_id)
                        != str(memory_record.get("writer_sdk_session_id") or "")
                    )
                    closure_usage = closure_response.get("usage") or {}
                    input_tokens += int(closure_usage.get("input_tokens", 0) or 0)
                    output_tokens += int(closure_usage.get("output_tokens", 0) or 0)
                    async with event_lock:
                        memory_closure_payload = {
                            "task_id": task["id"], "node_key": node_key,
                            "agent_id": memory_agent["id"], "platform_attempt_id": platform_attempt_id,
                            "platform_session_id": closure_session_key,
                            "memory_id": memory_record["id"], "memory_key": memory_record["memory_key"],
                            "memory_version": memory_record.get("version", 1),
                            "value_sha256": memory_record["value_sha256"],
                            "writer_session_id": memory_record.get("writer_session_id"),
                            "writer_sdk_session_id": memory_record.get("writer_sdk_session_id"),
                            "reader_session_id": closure_session_key,
                            "reader_sdk_session_id": reader_sdk_session_id,
                            "strict_sdk_session": strict_sdk_session,
                            "status": "passed" if closure_passed else "failed",
                        }
                        store.append_run_event(
                            run_id, "agent.memory.used", "memory",
                            f"{memory_agent['name']}在提交后新 SDK Session 使用了 Memory",
                            "闭环探针把刚提交的活动 Memory 注入新的 Claude SDK Session，并核对返回标记。",
                            memory_closure_payload,
                        )
                        store.append_run_event(
                            run_id, "agent.memory.closure.verified", "validation",
                            "Memory 提交、回读与新 Session 使用已闭环",
                            "writer 与 reader 使用不同 Claude SDK Session；Memory ID、版本和内容哈希保持一致。",
                            {**memory_closure_payload, "terminal": True},
                        )
                    if not closure_passed:
                        raise RuntimeError(f"memory_closure_failed:{memory_record['id']}")
                return node_key, input_tokens + output_tokens, {
                    "title": task["node_name"],
                    "content": content[:4000],
                }, decision

        async def execute_node_with_retries(
            task: dict[str, Any],
            prior: list[str],
        ) -> tuple[str, int, dict[str, Any], dict[str, Any] | None]:
            max_node_attempts = 2
            timeout_retry_level = 0
            for node_attempt in range(1, max_node_attempts + 1):
                try:
                    return await execute_node(task, prior, node_attempt, timeout_retry_level)
                except (LLMRequestError, AgentRuntimeError, ArtifactValidationError) as exc:
                    if node_attempt >= max_node_attempts:
                        raise
                    public_error = public_runtime_error(exc)
                    if public_error["error_category"] == "timeout":
                        timeout_retry_level = _next_timeout_retry_level(exc, timeout_retry_level)
                    retry_feedback = (
                        f"上一轮节点尝试失败（第 {node_attempt} 次）。请先读取并修复失败原因，再重新运行全部构建和测试命令；"
                        f"不要只重复生成原文件。平台记录的失败详情：{str(exc)[:5000]}"
                    )
                    revision_feedback.setdefault(str(task["node_key"]), []).append(retry_feedback)
                    store.update_task(
                        task["id"],
                        status="retrying",
                        output_data={
                            "last_error": public_error["error_detail"],
                            "error_type": type(exc).__name__,
                            "error_code": public_error["error_code"],
                            "diagnostic_id": public_error["diagnostic_id"],
                            "next_node_attempt": node_attempt + 1,
                        },
                    )
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "task.retrying",
                            "execution",
                            f"“{task['node_name']}”将整体重试",
                            f"节点内的模型调用已经连续失败，平台将在 2 秒后从本节点重新开始。这是第 {node_attempt + 1}/{max_node_attempts} 次节点尝试。{public_error['error_detail']}",
                            {
                                "task_id": task["id"],
                                "node_key": task["node_key"],
                                "attempt": node_attempt,
                                "next_attempt": node_attempt + 1,
                                "max_attempts": max_node_attempts,
                                "delay_seconds": 2,
                                "error_type": type(exc).__name__,
                                "error_detail": public_error["error_detail"],
                                "retry_feedback": public_error["error_detail"],
                                **_runtime_error_metadata(exc),
                            },
                        )
                    await asyncio.sleep(2)
            raise RuntimeError("unreachable_node_retry_state")

        def downstream_from(start_keys: set[str]) -> set[str]:
            impacted = set(start_keys)
            changed = True
            while changed:
                changed = False
                for candidate, candidate_dependencies in dependencies.items():
                    if candidate not in impacted and candidate_dependencies & impacted:
                        impacted.add(candidate)
                        changed = True
            return impacted

        async def process_rework_interventions() -> None:
            requests = [
                item
                for item in store.list_run_interventions(run_id)
                if item.get("kind") == "require_rework" and str(item["id"]) not in handled_rework_interventions
            ]
            for intervention in requests:
                target_task = next(
                    (item for item in tasks if str(item["id"]) == str(intervention.get("task_id") or "")),
                    None,
                )
                if not target_task:
                    handled_rework_interventions.add(str(intervention["id"]))
                    continue
                was_queued = intervention.get("status") == "queued"
                if was_queued:
                    store.mark_run_interventions_applied([str(intervention["id"])])
                target_key = str(target_task["node_key"])
                impacted = downstream_from({target_key})
                for impacted_key in impacted:
                    completed.discard(impacted_key)
                    pending.add(impacted_key)
                    revision_feedback.setdefault(impacted_key, []).append(
                        str(intervention["content"])
                        if impacted_key == target_key
                        else f"上游节点因发起人介入而返工；请使用新产物重新执行。发起人意见：{intervention['content']}"
                    )
                    store.update_task(
                        task_by_key[impacted_key]["id"],
                        status="pending",
                        output_data={
                            "rework_requested_by_user": True,
                            "intervention_id": intervention["id"],
                            "feedback": revision_feedback[impacted_key][-1],
                        },
                    )
                handled_rework_interventions.add(str(intervention["id"]))
                async with event_lock:
                    if was_queued:
                        store.append_run_event(
                            run_id,
                            "user.intervention.applied",
                            "intervention",
                            f"发起人要求“{target_task['node_name']}”返工",
                            str(intervention["content"]),
                            {
                                "intervention_id": intervention["id"],
                                "task_id": target_task["id"],
                                "node_key": target_key,
                                "kind": "require_rework",
                                "content": intervention["content"],
                                "status": "applied",
                            },
                        )
                    store.append_run_event(
                        run_id,
                        "workflow.loop.created",
                        "revision",
                        "发起人介入触发了定向返工闭环",
                        "责任节点及依赖其产物的下游节点将重新行动，旧产物继续保留为历史版本。",
                        {
                            "source": "user_intervention",
                            "intervention_id": intervention["id"],
                            "target_node_keys": [target_key],
                            "impacted_node_keys": sorted(impacted),
                        },
                    )

        while pending:
            await wait_for_control_boundary(settle_pause=True)
            await process_rework_interventions()
            current = store.get_run_state(run_id)
            if not current or current["status"] == "cancelled":
                return
            if enforce_run_time_limit and elapsed_before_invocation + (time.monotonic() - started_at) > max_run_minutes * 60:
                raise RuntimeError("budget_exhausted:run_time_limit")
            if max_total_tokens and total_tokens >= max_total_tokens:
                raise RuntimeError("budget_exhausted:token_limit")
            ready = [
                key for key in pending if dependencies.get(key, set()).issubset(completed)
            ]
            if not ready:
                raise RuntimeError("workflow_graph_cycle_or_unreachable_node")
            batch = [task_by_key[key] for key in ready]
            prior = [item for key in completed for item in [artifacts_by_key.get(key, "")] if item]
            results = await asyncio.gather(
                *(execute_node_with_retries(task, prior[-4:]) for task in batch), return_exceptions=True
            )
            errors = [result for result in results if isinstance(result, Exception)]
            if errors:
                for task, result in zip(batch, results):
                    if isinstance(result, Exception):
                        public_error = public_runtime_error(result)
                        store.update_task(
                            task["id"],
                            status="failed",
                            output_data={
                                "error": public_error["error_detail"],
                                "error_code": public_error["error_code"],
                                "diagnostic_id": public_error["diagnostic_id"],
                            },
                        )
                        async with event_lock:
                            store.append_run_event(
                                run_id,
                                "task.failed",
                                "execution",
                                f"“{task['node_name']}”在自动重试后仍然失败",
                                f"平台已完成模型请求级重试和节点级重试，仍未成功。{public_error['error_detail']}",
                                {
                                    "task_id": task["id"],
                                    "node_key": task["node_key"],
                                    "error_type": type(result).__name__,
                                    "error_detail": public_error["error_detail"],
                                    "automatic_retry_exhausted": isinstance(result, (LLMRequestError, AgentRuntimeError, ArtifactValidationError)),
                                    **_runtime_error_metadata(result),
                                },
                            )
                raise errors[0]
            gate_decisions: list[tuple[str, dict[str, Any]]] = []
            for result in results:
                node_key, used_tokens, artifact, decision = result
                completed.add(node_key)
                pending.remove(node_key)
                total_tokens += used_tokens
                artifacts_by_key[node_key] = f"[{artifact['title']}]\n{artifact['content']}"
                if decision:
                    gate_decisions.append((node_key, decision))
            for gate_key, decision in gate_decisions:
                verdict = str(decision.get("verdict") or "")
                if verdict == "pass":
                    async with event_lock:
                        store.append_run_event(
                            run_id, "gate.passed", "gate", f"“{task_by_key[gate_key]['node_name']}”裁决通过",
                            str(decision.get("summary") or "独立裁判确认本轮产物满足验收要求。"),
                            {"task_id": task_by_key[gate_key]["id"], "node_key": gate_key, "decision": decision},
                        )
                    continue
                gate_definition = node_def_by_key.get(gate_key, {})
                if _continues_after_expected_rejection(
                    gate_key,
                    gate_definition,
                    dependencies,
                    node_def_by_key,
                ):
                    revision_counts[gate_key] = revision_counts.get(gate_key, 0) + 1
                    feedback = str(
                        decision.get("feedback")
                        or decision.get("summary")
                        or "首轮裁决已按流程退回，进入下游整改节点。"
                    )
                    direct_downstream = sorted(
                        key for key, required in dependencies.items() if gate_key in required
                    )
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "gate.rejected",
                            "gate",
                            f"“{task_by_key[gate_key]['node_name']}”按预期退回",
                            feedback,
                            {
                                "task_id": task_by_key[gate_key]["id"],
                                "node_key": gate_key,
                                "target_node_keys": list(decision.get("target_node_keys") or []),
                                "impacted_node_keys": [],
                                "revision_round": revision_counts[gate_key],
                                "max_revision_rounds": max_revision_rounds,
                                "decision": decision,
                                "expected_rejection": True,
                                "continue_downstream": True,
                                "direct_downstream_node_keys": direct_downstream,
                            },
                        )
                        store.append_run_event(
                            run_id,
                            "gate.expected_rejection.recorded",
                            "revision",
                            "首轮退回证据已记录，生产流进入整改阶段",
                            "平台保留本次独立裁判退回及其责任意见；该节点是流程预设的首轮阻断验证点，因此不回滚上游审计，直接由下游整改节点承接。",
                            {
                                "gate_node_key": gate_key,
                                "revision_round": revision_counts[gate_key],
                                "continue_downstream": True,
                                "direct_downstream_node_keys": direct_downstream,
                                "decision": decision,
                            },
                        )
                    continue
                target_keys = _resolve_gate_targets(gate_key, decision, dependencies, set(task_by_key))
                if not target_keys:
                    raise RuntimeError(f"judge_rejected_without_target:{gate_key}")
                revision_counts[gate_key] = revision_counts.get(gate_key, 0) + 1
                if revision_counts[gate_key] > max_revision_rounds:
                    raise RuntimeError(f"revision_exhausted:{gate_key}")
                feedback = str(decision.get("feedback") or decision.get("summary") or "根据裁判意见修订并重新提交。")
                impacted = downstream_from(target_keys)
                for impacted_key in impacted:
                    completed.discard(impacted_key)
                    pending.add(impacted_key)
                    revision_feedback.setdefault(impacted_key, []).append(
                        feedback if impacted_key in target_keys else f"上游责任节点已被裁判打回；使用其修订产物重新执行。裁判意见：{feedback}"
                    )
                    store.update_task(
                        task_by_key[impacted_key]["id"],
                        status="pending",
                        output_data={
                            "rework_requested": True,
                            "gate_node_key": gate_key,
                            "revision_round": revision_counts[gate_key],
                            "feedback": revision_feedback[impacted_key][-1],
                        },
                    )
                async with event_lock:
                    store.append_run_event(
                        run_id, "gate.rejected", "gate", f"裁判第 {revision_counts[gate_key]} 次退回修订",
                        feedback,
                        {
                            "task_id": task_by_key[gate_key]["id"], "node_key": gate_key,
                            "target_node_keys": sorted(target_keys), "impacted_node_keys": sorted(impacted),
                            "revision_round": revision_counts[gate_key], "max_revision_rounds": max_revision_rounds,
                            "decision": decision,
                        },
                    )
                    store.append_run_event(
                        run_id, "workflow.loop.created", "revision", "生产流已自动回到责任节点",
                        "责任节点将携带裁判意见重做；其下游节点随后基于新版本产物重新执行，原产物继续保留为历史版本。",
                        {
                            "gate_node_key": gate_key, "target_node_keys": sorted(target_keys),
                            "impacted_node_keys": sorted(impacted), "revision_round": revision_counts[gate_key],
                        },
                    )
                    for target_key in sorted(target_keys):
                        target_task = task_by_key[target_key]
                        target_agent = store.get_agent(str(target_task.get("agent_id")))
                        store.append_run_event(
                            run_id, "agent.message.sent", "revision",
                            f"裁判向{target_agent['name'] if target_agent else target_task['node_name']}发出返工委托",
                            feedback,
                            {
                                "task_id": target_task["id"], "node_key": target_key,
                                "from_agent_id": task_by_key[gate_key].get("agent_id"),
                                "to_agent_id": target_task.get("agent_id"), "message_type": "revision_request",
                                "content": feedback, "round": revision_counts[gate_key],
                            },
                        )
            progress = int((len(completed) / max(len(tasks), 1)) * 100)
            store.update_run(run_id, progress=progress, token_count=total_tokens)

        convergence_snapshot = await asyncio.to_thread(
            store.get_run_execution_snapshot, run_id
        ) or {}
        unresolved_duplicate_count = _unresolved_tool_terminal_duplicate_count(
            list(convergence_snapshot.get("events", []))
        )
        store.append_run_event(
            run_id, "worker.duplicate_side_effect.scan", "validation",
            "Run 收敛前重复副作用终检已完成",
            "平台在所有固定节点完成后复核稳定 Tool 身份及显式 reconciliation。",
            {
                "execution_epoch": execution_epoch,
                "status": "completed",
                "terminal": True,
                "duplicate_side_effect_count": unresolved_duplicate_count,
            },
        )
        store.append_run_event(
            run_id, "run.converged", "gate",
            "工作流已收敛到最终通过状态",
            "所有固定节点均已完成，最终 Judge 已通过，未再产生待返工节点。",
            {
                "execution_epoch": execution_epoch,
                "completed_node_keys": sorted(completed),
                "pending_node_keys": [],
                "duplicate_side_effect_count": unresolved_duplicate_count,
            },
        )
        store.update_run(run_id, status="completed", stage="completed", progress=100, token_count=total_tokens)
        completed_run = await asyncio.to_thread(
            store.get_run_execution_snapshot, run_id
        ) or {}
        existing_conclusion = next(
            (item for item in completed_run.get("artifacts", []) if str(item.get("title") or "") == "一页纸结论"),
            None,
        )
        if not existing_conclusion and tasks:
            conclusion = store.create_artifact(
                run_id,
                None,
                "run_conclusion",
                "一页纸结论",
                _build_one_page_conclusion(completed_run, tasks, completed_run.get("artifacts", [])),
                "final",
            )
            conclusion_receipt = store.verify_artifact_bytes(run_id, conclusion["id"])
            conclusion_payload = {
                "artifact_id": conclusion["id"],
                "artifact_kind": conclusion["kind"],
                "artifact_title": conclusion["title"],
                "relative_path": conclusion["relative_path"],
                "sha256": conclusion["sha256"],
                "size_bytes": conclusion["size_bytes"],
            }
            store.append_run_event(
                run_id,
                "artifact.created",
                "artifact",
                "事件一页纸结论已经形成",
                "全部节点完成后，平台已将本次事件的结论、核心发现、使用边界和下一步整理为一页纸摘要。",
                conclusion_payload,
            )
            if conclusion_receipt["matched"]:
                store.append_run_event(
                    run_id, "artifact.collected", "artifact",
                    "事件一页纸结论原始字节已采集",
                    "平台已从 Run Artifact 区复读结论并核对 SHA-256。",
                    {**conclusion_payload, "status": "sha256_verified"},
                )
                store.append_run_event(
                    run_id, "artifact.download.verified", "validation",
                    "事件一页纸结论下载字节已复算",
                    "下载路径读取的字节数和 SHA-256 与 Registry 一致。",
                    {**conclusion_payload, "status": "matched"},
                )
        store.append_run_event(
            run_id,
            "run.completed",
            "gate",
            "全部节点已经完成",
            "工作流中的所有固定节点均已返回并保存真实模型产物。",
            {
                "artifact_count": len(artifacts_by_key), "model": model_config["model"], "token_count": total_tokens,
                "runtime": runtime_name, "revision_counts": revision_counts,
            },
        )
    except asyncio.CancelledError:
        current = store.get_run_state(run_id)
        if current and current.get("status") != "cancelled":
            if current.get("status") == "pause_requested":
                store.update_run(run_id, status="paused", stage="paused")
            elif current.get("status") != "paused":
                store.update_run(run_id, status="running", stage="interrupted_waiting_recovery")
            store.append_run_event(
                run_id,
                "run.interrupted",
                "system",
                "执行器已中断，现场等待恢复",
                "本次不是发起人取消。任务、事件、产物和人物工作区均已保留，后端恢复后将从未完成节点继续。",
                {"recoverable": True},
            )
        raise
    except Exception as exc:
        budget_kind = ""
        if str(exc).startswith("budget_exhausted:"):
            status, stage = "budget_exhausted", "budget_exhausted"
            budget_kind = str(exc).split(":", 1)[1]
        elif str(exc).startswith("revision_exhausted:"):
            status, stage = "revision_exhausted", "revision_exhausted"
        else:
            status, stage = "failed", "execution_failed"
        latest = store.get_run_live_snapshot(run_id, event_limit=20) or {}
        latest_tasks = latest.get("tasks") or []
        completed_count = sum(1 for item in latest_tasks if item.get("status") == "completed")
        terminal_progress = int((completed_count / max(len(latest_tasks), 1)) * 100)
        if latest_tasks and completed_count == 0:
            terminal_progress = max(1, int(latest.get("progress") or 0))
        store.update_run(run_id, status=status, stage=stage, progress=terminal_progress)
        public_error = public_runtime_error(exc)
        store.append_run_event(
            run_id,
            "run.budget_exhausted" if status == "budget_exhausted" else ("run.revision_exhausted" if status == "revision_exhausted" else "run.failed"),
            "system",
            "真实执行失败",
            f"执行已停止。平台保留全部重试记录、已完成节点和已有产物。{public_error['error_detail']}",
            {
                "error_type": type(exc).__name__,
                "error_detail": public_error["error_detail"],
                "budget_kind": budget_kind or None,
                **_runtime_error_metadata(exc),
            },
        )
    finally:
        _release_run_execution_lease(execution_lease)
def _resolve_gate_targets(
    gate_key: str,
    decision: dict[str, Any],
    dependencies: dict[str, set[str]],
    task_keys: set[str],
) -> set[str]:
    """Resolve a rejected judge's legal rework targets."""
    explicit = {
        str(item)
        for item in (decision.get("target_node_keys") or [])
        if str(item) in task_keys
    }
    if explicit:
        return explicit
    upstream = {str(item) for item in dependencies.get(gate_key, set()) if str(item) in task_keys}
    if upstream:
        return upstream
    return {gate_key} if gate_key in task_keys else set()


def _continues_after_expected_rejection(
    gate_key: str,
    gate_definition: dict[str, Any],
    dependencies: dict[str, set[str]],
    node_definitions: dict[str, dict[str, Any]],
) -> bool:
    """Return whether a rejected gate is an evidence checkpoint before remediation.

    New workflows should declare ``continue_after_rejection`` (and normally
    ``expected_verdict=revise``).  The narrow compatibility rule keeps already
    persisted workflows working when their first judge explicitly describes a
    required rejection and has a direct remediation/rework child.
    """
    expected_verdict = str(gate_definition.get("expected_verdict") or "").strip().lower()
    explicitly_continue = gate_definition.get("continue_after_rejection") is True
    if explicitly_continue:
        return expected_verdict in {"", "revise", "reject", "rejected"}

    gate_text = " ".join(
        str(gate_definition.get(field) or "")
        for field in ("key", "name", "purpose")
    ).lower()
    expected_rejection_marker = (
        "initial_judge_rejection" in gate_text
        or (
            any(marker in gate_text for marker in ("首轮", "首次", "initial"))
            and any(marker in gate_text for marker in ("退回", "拒绝", "不通过", "rejection", "reject"))
        )
    )
    if not expected_rejection_marker:
        return False

    direct_downstream = [
        node_definitions.get(node_key, {})
        for node_key, required in dependencies.items()
        if gate_key in required
    ]
    return any(
        any(
            marker in " ".join(
                str(node.get(field) or "") for field in ("key", "name", "purpose")
            ).lower()
            for marker in ("remediation", "整改", "返工", "重跑")
        )
        for node in direct_downstream
    )
