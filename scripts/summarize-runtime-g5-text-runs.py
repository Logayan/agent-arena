from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.platform_store import PlatformStore

def summarize(runtime_name: str, database: Path, run_id: str) -> dict[str, Any]:
    store = PlatformStore(str(database))
    result = store.get_run(run_id)
    if not result:
        raise RuntimeError(f"run_not_found:{runtime_name}")
    event_counts: dict[str, int] = {}
    for event in result["events"]:
        event_type = str(event["type"])
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    task_by_id = {str(task["id"]): task for task in result["tasks"]}
    artifact_versions: dict[str, list[dict[str, Any]]] = {}
    for artifact in result["artifacts"]:
        task = task_by_id.get(str(artifact.get("task_id") or ""))
        node_key = str(task["node_key"]) if task else "run"
        artifact_versions.setdefault(node_key, []).append(
            {
                "version": int(artifact.get("version", 0) or 0),
                "status": str(artifact.get("status") or ""),
                "path": str(artifact.get("relative_path") or ""),
            }
        )
    checks = {
        "run_completed": result["status"] == "completed",
        "independent_contributions": event_counts.get("team.member.completed", 0) >= 2,
        "public_messages": event_counts.get("agent.message.sent", 0) >= 2,
        "team_synthesis": event_counts.get("team.synthesis.completed", 0) >= 1,
        "judge_rejected": event_counts.get("gate.rejected", 0) >= 1,
        "revision_loop": event_counts.get("workflow.loop.created", 0) >= 1,
        "judge_passed": event_counts.get("gate.passed", 0) >= 1,
        "memory_persisted": event_counts.get("agent.memory.persisted", 0) >= 1,
        "artifact_versions_preserved": any(
            len(items) >= 2 for key, items in artifact_versions.items() if key != "run"
        ),
        "final_run_artifact": any(
            item["status"] == "final" for item in artifact_versions.get("run", [])
        ),
    }
    return {
        "runtime": runtime_name,
        "database": database.name,
        "run_id": run_id,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "run": {
            "status": result["status"],
            "progress": result["progress"],
            "token_count": result["token_count"],
            "task_count": len(result["tasks"]),
            "artifact_count": len(result["artifacts"]),
            "event_count": len(result["events"]),
        },
        "event_counts": {
            key: event_counts.get(key, 0)
            for key in (
                "team.member.completed",
                "agent.message.sent",
                "team.synthesis.completed",
                "gate.rejected",
                "workflow.loop.created",
                "gate.passed",
                "agent.memory.persisted",
                "run.completed",
            )
        },
        "artifact_versions": artifact_versions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openclaw-db", required=True)
    parser.add_argument("--openclaw-run", required=True)
    parser.add_argument("--claude-db", required=True)
    parser.add_argument("--claude-run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    results = [
        summarize("openclaw", Path(args.openclaw_db).resolve(), args.openclaw_run),
        summarize("claude_code", Path(args.claude_db).resolve(), args.claude_run),
    ]
    report = {
        "schema_version": "jianghu.runtime-g5-text-comparison.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "source": "recovered_from_completed_runs_after_summary_script_bug",
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "runtimes": results,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "result_path": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
