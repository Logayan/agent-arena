from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def fetch_json(url: str) -> Any:
    with urlopen(url, timeout=30) as response:  # noqa: S310 - local verification endpoint
        return json.loads(response.read().decode("utf-8"))


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def event_sample(events: list[dict[str, Any]], predicate, limit: int = 5) -> list[dict[str, Any]]:
    selected = []
    for event in events:
        if not predicate(event):
            continue
        selected.append(
            {
                "run_id": event.get("run_id"),
                "sequence": event.get("sequence"),
                "type": event.get("type"),
                "title": event.get("title"),
                "summary": str(event.get("summary") or "")[:500],
            }
        )
    return selected[-limit:]


def check(status: str, summary: str, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"status": status, "summary": summary, "evidence": evidence or []}


def find_by_id(items: Any, item_id: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    return next((item for item in items if isinstance(item, dict) and str(item.get("id")) == item_id), None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a real browser-created Claude Runtime E2E run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--organization-id", default="org_jianghu")
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--output")
    parser.add_argument("--require-passed", action="store_true")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    query = urlencode({"organization_id": args.organization_id})
    run = fetch_json(f"{base_url}/api/platform/runs/{args.run_id}?{query}")["run"]
    runtime_status = fetch_json(f"{base_url}/api/platform/runtime/status")
    workflows = fetch_json(f"{base_url}/api/platform/workflows?{query}")
    teams = fetch_json(f"{base_url}/api/platform/teams?{query}")
    commissions = fetch_json(f"{base_url}/api/platform/commissions?{query}")

    events = list(run.get("events") or [])
    event_counts = Counter(str(event.get("type") or "") for event in events)
    tasks = list(run.get("tasks") or [])
    artifacts = list(run.get("artifacts") or [])
    workflow = find_by_id(workflows, str(run.get("workflow_id") or ""))
    team_ids = sorted({str(task.get("team_id")) for task in tasks if task.get("team_id")})
    linked_teams = [item for item in teams if isinstance(item, dict) and str(item.get("id")) in team_ids]
    linked_commissions = [
        item for item in commissions
        if isinstance(item, dict) and str(item.get("run_id") or "") == str(run.get("id") or "")
    ]

    run_started = next((event for event in events if event.get("type") == "run.started"), None)
    run_started_payload = payload(run_started or {})
    runtime_ready = next(
        (
            event for event in reversed(events)
            if event.get("type") in {"agent.runtime.ready", "agent.runtime.recovered"}
        ),
        None,
    )
    runtime_ready_payload = payload(runtime_ready or {})
    run_runtime_event = next(
        (event for event in reversed(events) if event.get("type") in {"run.started", "run.recovered"}),
        None,
    )
    run_runtime_payload = payload(run_runtime_event or {})
    ancestor_runs: list[dict[str, Any]] = []
    ancestor_id = str(run.get("parent_run_id") or "")
    visited_run_ids = {str(run.get("id") or "")}
    while ancestor_id and ancestor_id not in visited_run_ids:
        visited_run_ids.add(ancestor_id)
        ancestor = fetch_json(
            f"{base_url}/api/platform/runs/{ancestor_id}?{query}"
        )["run"]
        ancestor_runs.append(ancestor)
        ancestor_id = str(ancestor.get("parent_run_id") or "")
    ancestor_events = [
        event
        for ancestor in ancestor_runs
        for event in list(ancestor.get("events") or [])
    ]
    ancestor_text = "\n".join(
        f"{event.get('title', '')}\n{event.get('summary', '')}\n{json.dumps(payload(event), ensure_ascii=False)}"
        for event in ancestor_events
    )

    command_events = [event for event in events if event.get("type") == "agent.command.completed"]
    failed_commands = [event for event in command_events if payload(event).get("is_error") or payload(event).get("status") == "failed"]
    successful_commands = [
        event for event in command_events
        if payload(event).get("exit_code") == 0 and not payload(event).get("is_error")
    ]
    recovered_pairs = []
    for failed in failed_commands:
        failed_payload = payload(failed)
        recovery = next(
            (
                success for success in successful_commands
                if int(success.get("sequence") or 0) > int(failed.get("sequence") or 0)
                and payload(success).get("agent_id") == failed_payload.get("agent_id")
            ),
            None,
        )
        if recovery:
            recovered_pairs.append(
                {
                    "failed_sequence": failed.get("sequence"),
                    "recovered_sequence": recovery.get("sequence"),
                    "agent_id": failed_payload.get("agent_id"),
                }
            )

    tool_results = [event for event in events if event.get("type") == "agent.tool.completed"]
    file_tool_counts = Counter(
        str(payload(event).get("tool_name") or "")
        for event in tool_results
        if str(payload(event).get("tool_name") or "") in {"Read", "Write", "Edit"}
    )
    shell_events = []
    for event in command_events:
        item = payload(event)
        output = str(item.get("output") or "")
        if item.get("shell") in {"git-bash", "bash"} or '"shell":"git-bash"' in output or '"shell": "git-bash"' in output:
            shell_events.append(event)
    credential_isolated_shell_events = []
    for event in shell_events:
        item = payload(event)
        output = str(item.get("output") or "")
        if (
            item.get("environment") == "credential-isolated"
            or '"environment":"credential-isolated"' in output
            or '"environment": "credential-isolated"' in output
        ):
            credential_isolated_shell_events.append(event)
    judge_agent_ids = {
        str(task.get("agent_id") or "")
        for task in tasks
        if "judge" in str(task.get("node_key") or "").lower()
        or "judgement" in str(task.get("node_key") or "").lower()
    }
    judge_agent_ids.discard("")
    tool_enabled_agent_ids = {
        str(agent_id) for agent_id in runtime_ready_payload.get("tool_enabled_agent_ids") or []
    }
    workspace_root = Path(str((run.get("workspace") or {}).get("root") or ""))
    artifact_byte_results = []
    for artifact in artifacts:
        relative_path = str(artifact.get("relative_path") or "")
        artifact_path = workspace_root / relative_path if relative_path else Path()
        observed_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest() if artifact_path.is_file() else ""
        artifact_byte_results.append(
            {
                "id": artifact.get("id"),
                "relative_path": relative_path,
                "registered_sha256": artifact.get("sha256"),
                "observed_sha256": observed_sha256,
                "matched": bool(observed_sha256) and observed_sha256 == artifact.get("sha256"),
            }
        )

    checks: dict[str, dict[str, Any]] = {}
    checks["runtime_is_claude_code"] = check(
        "passed" if runtime_status.get("runtime") == "claude_code" else "failed",
        f"runtime={runtime_status.get('runtime')}",
    )
    checks["sdk_bridge_available"] = check(
        "passed" if runtime_status.get("available") and runtime_status.get("mode") == "agent-sdk-bridge" else "failed",
        f"mode={runtime_status.get('mode')}, sdk={runtime_status.get('version')}, claude_code={runtime_status.get('claude_code_version')}",
    )
    checks["model_configured"] = check(
        "passed" if runtime_status.get("model_configured") and runtime_status.get("synced", {}).get("model") else "failed",
        f"model={runtime_status.get('synced', {}).get('model')}",
    )
    checks["product_goal_team_workflow_run"] = check(
        "passed" if workflow and linked_teams and tasks and run_started else "failed",
        f"workflow={bool(workflow)}, teams={len(linked_teams)}, tasks={len(tasks)}, linked_commissions={len(linked_commissions)}",
        event_sample(events, lambda event: event.get("type") in {"run.retry_created", "run.started"}),
    )
    checks["run_runtime_snapshot"] = check(
        "passed"
        if run_runtime_payload.get("runtime") == "claude_code"
        and run_runtime_payload.get("runtime_mode") == "agent-sdk-bridge"
        and runtime_ready_payload.get("mode") == "agent-sdk-bridge"
        else "failed",
        (
            f"runtime={run_runtime_payload.get('runtime')}, "
            f"run_mode={run_runtime_payload.get('runtime_mode')}, "
            f"adapter_mode={runtime_ready_payload.get('mode')}, model={run_runtime_payload.get('model')}"
        ),
        event_sample(
            events,
            lambda event: event.get("type") in {
                "run.started", "run.recovered", "agent.runtime.ready", "agent.runtime.recovered",
            },
        ),
    )
    checks["runtime_tool_policy"] = check(
        "passed" if judge_agent_ids and judge_agent_ids.issubset(tool_enabled_agent_ids) else "failed",
        f"judge_agents={sorted(judge_agent_ids)}, tool_enabled={sorted(tool_enabled_agent_ids)}",
        event_sample(events, lambda event: event.get("type") == "agent.runtime.ready"),
    )
    fallback_seen = "model_config_missing_for_tier:high" in ancestor_text and run_started_payload.get("model")
    checks["model_tier_controlled_fallback"] = check(
        "passed" if fallback_seen else ("pending" if not ancestor_runs else "failed"),
        (
            f"版本链中的 high 档位失败证据已保留；当前第 {run.get('run_version')} 版使用 {run_started_payload.get('model')}。"
            if fallback_seen
            else "未在完整 Run 版本链中找到档位失败与恢复证据。"
        ),
        event_sample(
            ancestor_events,
            lambda event: "model_config_missing_for_tier:high" in (
                f"{event.get('title', '')}\n{event.get('summary', '')}\n{json.dumps(payload(event), ensure_ascii=False)}"
            ),
        ),
    )
    checks["pause_resume"] = check(
        "passed" if event_counts["run.pause_requested"] and event_counts["run.resumed"] else "pending",
        f"pause={event_counts['run.pause_requested']}, resume={event_counts['run.resumed']}",
        event_sample(events, lambda event: event.get("type") in {"run.pause_requested", "run.resumed"}),
    )
    checks["api_restart_recovery"] = check(
        "passed"
        if event_counts["run.interrupted"] and event_counts["run.recovered"]
        and event_counts["agent.runtime.recovered"]
        else "pending",
        (
            f"interrupted={event_counts['run.interrupted']}, recovered={event_counts['run.recovered']}, "
            f"runtime_recovered={event_counts['agent.runtime.recovered']}"
        ),
        event_sample(
            events,
            lambda event: event.get("type") in {"run.interrupted", "run.recovered", "agent.runtime.recovered"},
        ),
    )
    checks["windows_real_bash"] = check(
        "passed" if shell_events else "pending",
        f"bash-evidenced commands={len(shell_events)}",
        event_sample(shell_events, lambda _event: True),
    )
    checks["credential_isolation"] = check(
        "passed" if shell_events and len(credential_isolated_shell_events) == len(shell_events) else "failed",
        f"isolated={len(credential_isolated_shell_events)}, shell_commands={len(shell_events)}",
        event_sample(shell_events, lambda _event: True),
    )
    checks["generic_runtime_events"] = check(
        "passed"
        if event_counts["agent.runtime.ready"] and event_counts["agent.turn.started"]
        and not any(name.startswith("openclaw.") for name in event_counts)
        else "failed",
        (
            f"agent.runtime.ready={event_counts['agent.runtime.ready']}, "
            f"agent.turn.started={event_counts['agent.turn.started']}, "
            f"legacy_openclaw_events={sum(count for name, count in event_counts.items() if name.startswith('openclaw.'))}"
        ),
        event_sample(events, lambda event: event.get("type") in {"agent.runtime.ready", "agent.turn.started"}),
    )
    checks["tools_files_tests"] = check(
        "passed" if file_tool_counts["Read"] and file_tool_counts["Write"] and event_counts["agent.test.completed"] else "pending",
        f"Read={file_tool_counts['Read']}, Write={file_tool_counts['Write']}, Edit={file_tool_counts['Edit']}, tests={event_counts['agent.test.completed']}",
        event_sample(
            events,
            lambda event: event.get("type") in {"agent.tool.completed", "agent.test.completed"}
            and (payload(event).get("tool_name") in {"Read", "Write", "Edit"} or event.get("type") == "agent.test.completed"),
        ),
    )
    checks["command_failure_recovery"] = check(
        "passed" if recovered_pairs else "pending",
        f"failed={len(failed_commands)}, successful={len(successful_commands)}, recovered_pairs={len(recovered_pairs)}",
        event_sample(events, lambda event: event.get("type") in {"agent.action.failed", "agent.action.retrying", "task.retrying"}),
    )
    checks["public_team_collaboration"] = check(
        "passed" if event_counts["agent.message.sent"] and event_counts["team.communication.round.completed"] else "pending",
        f"messages={event_counts['agent.message.sent']}, completed_rounds={event_counts['team.communication.round.completed']}",
        event_sample(events, lambda event: event.get("type") in {"agent.message.sent", "team.communication.round.completed"}),
    )
    checks["team_synthesis"] = check(
        "passed" if event_counts["team.synthesis.completed"] else "pending",
        f"started={event_counts['team.synthesis.started']}, completed={event_counts['team.synthesis.completed']}",
        event_sample(events, lambda event: str(event.get("type") or "").startswith("team.synthesis.")),
    )
    checks["judge_reject_revision"] = check(
        "passed" if event_counts["gate.rejected"] and event_counts["workflow.loop.created"] else "pending",
        f"rejected={event_counts['gate.rejected']}, loops={event_counts['workflow.loop.created']}",
        event_sample(events, lambda event: event.get("type") in {"gate.rejected", "workflow.loop.created"}),
    )
    checks["judge_final_pass"] = check(
        "passed" if event_counts["gate.passed"] else "pending",
        f"passed={event_counts['gate.passed']}",
        event_sample(events, lambda event: event.get("type") == "gate.passed"),
    )
    checks["memory_persisted"] = check(
        "passed" if event_counts["agent.memory.persisted"] else "pending",
        f"memory_events={event_counts['agent.memory.persisted']}",
        event_sample(events, lambda event: event.get("type") == "agent.memory.persisted"),
    )
    checks["engineering_submissions"] = check(
        "passed" if event_counts["engineering.submission.published"] >= 2 else "pending",
        f"published={event_counts['engineering.submission.published']}",
        event_sample(events, lambda event: event.get("type") == "engineering.submission.published"),
    )
    checks["artifact_byte_integrity"] = check(
        "passed"
        if artifact_byte_results and all(item["matched"] for item in artifact_byte_results)
        else ("pending" if not artifact_byte_results else "failed"),
        (
            f"matched={sum(1 for item in artifact_byte_results if item['matched'])}, "
            f"artifacts={len(artifact_byte_results)}"
        ),
        event_sample(events, lambda event: event.get("type") == "artifact.storage.repaired"),
    )
    checks["artifacts_and_terminal_result"] = check(
        "passed" if run.get("status") == "completed" and artifacts and event_counts["run.completed"] else "pending",
        f"status={run.get('status')}, artifacts={len(artifacts)}, run.completed={event_counts['run.completed']}",
        event_sample(events, lambda event: event.get("type") in {"artifact.created", "run.completed", "run.failed"}),
    )

    blocking = [name for name, value in checks.items() if value["status"] != "passed"]
    legacy_event_count = sum(count for name, count in event_counts.items() if name.startswith("openclaw."))
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "source": {
            "base_url": base_url,
            "organization_id": args.organization_id,
            "run_id": args.run_id,
            "driver": "real-browser-created-product-run",
        },
        "status": "passed" if not blocking else ("failed" if run.get("status") in {"failed", "cancelled"} else "in_progress"),
        "run": {
            "id": run.get("id"),
            "family_id": run.get("run_family_id"),
            "version": run.get("run_version"),
            "parent_run_id": run.get("parent_run_id"),
            "ancestor_run_ids": [item.get("id") for item in ancestor_runs],
            "status": run.get("status"),
            "stage": run.get("stage"),
            "progress": run.get("progress"),
            "workflow_id": run.get("workflow_id"),
            "workflow_name": (workflow or {}).get("name"),
            "team_ids": team_ids,
            "team_names": [item.get("name") for item in linked_teams],
            "commission_ids": [item.get("id") for item in linked_commissions],
            "task_counts": dict(Counter(str(task.get("status") or "") for task in tasks)),
            "artifact_count": len(artifacts),
            "event_count": len(events),
        },
        "runtime": runtime_status,
        "checks": checks,
        "blocking_checks": blocking,
        "event_counts": dict(sorted(event_counts.items())),
        "command_recovery_pairs": recovered_pairs,
        "compatibility_observation": {
            "legacy_openclaw_event_alias_count": legacy_event_count,
            "note": "本 Run 在通用 agent.* 事件名切换前启动；历史事件名仅作读取兼容，不代表实际 Runtime。"
            if legacy_event_count else "新事件已使用通用命名。",
        },
        "artifacts": [
            {
                "id": item.get("id"),
                "task_id": item.get("task_id"),
                "title": item.get("title"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "version": item.get("version"),
                "relative_path": item.get("relative_path"),
                "sha256": item.get("sha256"),
            }
            for item in artifacts
        ],
        "artifact_byte_results": artifact_byte_results,
    }

    output = Path(args.output) if args.output else PROJECT_ROOT / "experiments" / "runtime-g6" / "results" / f"ui-e2e-{args.run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.resolve()), "status": result["status"], "blocking_checks": blocking}, ensure_ascii=False))
    return 1 if args.require_passed and blocking else 0


if __name__ == "__main__":
    sys.exit(main())
