from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.platform_store import PlatformStore


REQUIRED_FILES = {
    "calculator/__init__.py",
    "calculator/core.py",
    "tests/test_core.py",
    "README.md",
}
FORBIDDEN_NAMES = {
    "AGENTS.md",
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "TOOLS.md",
    "MEMORY.md",
    "CLAUDE.md",
}
FORBIDDEN_DIRECTORIES = {".claude"}


def _portable_test(code_root: Path, runtime_name: str) -> dict[str, Any]:
    if not code_root.is_dir():
        raise RuntimeError(f"workspace_code_missing:{runtime_name}:{code_root}")
    with tempfile.TemporaryDirectory(prefix=f"jianghu-g5-{runtime_name}-") as temporary:
        delivery = Path(temporary) / "delivery"
        shutil.copytree(code_root, delivery)
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=delivery,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        files = sorted(
            path.relative_to(delivery).as_posix()
            for path in delivery.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    output = completed.stdout + completed.stderr
    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    return {
        "exit_code": completed.returncode,
        "test_count": int(match.group(1)) if match else None,
        "output_tail": output[-4000:],
        "files": files,
    }


def summarize(
    runtime_name: str,
    database: Path,
    run_id: str,
    duration_seconds: float,
) -> dict[str, Any]:
    store = PlatformStore(str(database))
    result = store.get_run(run_id)
    if not result:
        raise RuntimeError(f"run_not_found:{runtime_name}")

    event_counts: dict[str, int] = {}
    for event in result["events"]:
        event_type = str(event["type"])
        event_counts[event_type] = event_counts.get(event_type, 0) + 1

    task_outputs = [task.get("output") or {} for task in result["tasks"]]
    validations = [
        output.get("validation")
        for output in task_outputs
        if isinstance(output.get("validation"), dict)
    ]
    validation = next(
        (item for item in validations if item.get("passed") is True),
        validations[0] if validations else {},
    )

    code_root = Path(result["workspace"]["code"]).resolve()
    portable = _portable_test(code_root, runtime_name)
    file_set = set(portable["files"])
    forbidden_files = sorted(
        item
        for item in portable["files"]
        if Path(item).name in FORBIDDEN_NAMES
        or FORBIDDEN_DIRECTORIES.intersection(Path(item).parts)
    )
    checks = {
        "run_completed": result["status"] == "completed",
        "independent_public_submissions": event_counts.get("engineering.submission.published", 0) >= 2,
        "public_messages": event_counts.get("agent.message.sent", 0) >= 2,
        "command_events": event_counts.get("agent.command.completed", 0) >= 1,
        "test_events": event_counts.get("agent.test.completed", 0) >= 1,
        "artifact_validator_passed": (
            validation.get("passed") is True
            and event_counts.get("artifact.validation.passed", 0) >= 1
        ),
        "required_files_present": REQUIRED_FILES.issubset(file_set),
        "control_files_not_leaked": not forbidden_files,
        "portable_tests_passed": portable["exit_code"] == 0,
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
            "duration_seconds": duration_seconds,
            "token_count": result["token_count"],
            "task_count": len(result["tasks"]),
            "artifact_count": len(result["artifacts"]),
            "event_count": len(result["events"]),
        },
        "validation": {
            "passed": validation.get("passed"),
            "file_count": validation.get("file_count"),
            "command_count": validation.get("command_count"),
            "successful_test_count": validation.get("successful_test_count"),
            "portable_successful_test_count": validation.get("portable_successful_test_count"),
        },
        "event_counts": {
            key: event_counts.get(key, 0)
            for key in (
                "team.member.completed",
                "team.dossier.published",
                "engineering.submission.published",
                "team.communication.round.started",
                "agent.message.sent",
                "team.synthesis.started",
                "agent.file.created",
                "agent.file.modified",
                "agent.command.completed",
                "agent.test.completed",
                "artifact.validation.passed",
                "run.completed",
                "run.failed",
            )
        },
        "delivery": {
            "files": portable["files"],
            "required_files": sorted(REQUIRED_FILES),
            "forbidden_files": forbidden_files,
            "portable_test_exit_code": portable["exit_code"],
            "portable_test_count": portable["test_count"],
            "portable_test_output_tail": portable["output_tail"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openclaw-db", required=True)
    parser.add_argument("--openclaw-run", required=True)
    parser.add_argument("--openclaw-duration", required=True, type=float)
    parser.add_argument("--claude-db", required=True)
    parser.add_argument("--claude-run", required=True)
    parser.add_argument("--claude-duration", required=True, type=float)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    results = [
        summarize(
            "openclaw",
            Path(args.openclaw_db).resolve(),
            args.openclaw_run,
            args.openclaw_duration,
        ),
        summarize(
            "claude_code",
            Path(args.claude_db).resolve(),
            args.claude_run,
            args.claude_duration,
        ),
    ]
    report = {
        "schema_version": "jianghu.runtime-g5-engineering-comparison.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "source": "recovered_from_completed_runs",
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "pair_checks": {
            "both_runtimes_passed": all(item["status"] == "passed" for item in results),
            "same_required_delivery_contract": all(
                item["checks"]["required_files_present"] for item in results
            ),
            "both_portable": all(item["checks"]["portable_tests_passed"] for item in results),
        },
        "runtimes": results,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "result_path": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
