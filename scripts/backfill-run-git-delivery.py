from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.git_delivery import commit_run_changes
from server.app.platform_store import PlatformStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a traceable Git Commit Artifact for an existing Run workspace.")
    parser.add_argument("run_id")
    parser.add_argument("--database", default=".data/jianghu.db")
    parser.add_argument("--allow-active", action="store_true")
    args = parser.parse_args()

    store = PlatformStore(args.database)
    run = store.get_run(args.run_id)
    if not run:
        raise SystemExit("run_not_found")
    if run["status"] in {"running", "pause_requested", "paused"} and not args.allow_active:
        raise SystemExit("run_is_active_refusing_inconsistent_git_snapshot")
    completed_tasks = [task for task in run.get("tasks", []) if task.get("status") == "completed"]
    if not completed_tasks:
        raise SystemExit("run_has_no_completed_task")
    task = completed_tasks[-1]
    agent = store.get_agent(str(task.get("agent_id") or "")) or {
        "id": "jianghu-platform",
        "name": "Jianghu Platform",
    }
    attempt_payload = {
        "task_id": task["id"],
        "node_key": task["node_key"],
        "agent_id": agent["id"],
        "backfilled": True,
        "delivery_mode": "local_commit",
    }
    store.append_run_event(
        args.run_id,
        "git.commit.started",
        "artifact",
        "开始补录当前 Run 的 Git Commit",
        "平台正在把已保留的隔离代码工作区形成不可变本地提交。",
        attempt_payload,
    )
    commit = commit_run_changes(
        run["workspace"]["code"],
        run_id=args.run_id,
        node_key="run_delivery_backfill",
        node_name="Claude Code SDK current Run Git delivery snapshot",
        agent=agent,
    )
    if not commit:
        store.append_run_event(
            args.run_id,
            "git.commit.skipped",
            "artifact",
            "当前 Run 无需补录新 Commit",
            "Git 工作区没有尚未提交的新增、修改或删除内容。",
            {**attempt_payload, "reason": "working_tree_clean"},
        )
        print(json.dumps({"run_id": args.run_id, "created": False, "reason": "workspace_clean"}, ensure_ascii=False))
        return 0

    public_commit = {key: value for key, value in commit.items() if key != "repository"}
    artifact = store.create_artifact(
        args.run_id,
        task["id"],
        "git_commit",
        f"Git Commit {commit['short_sha']} · 当前事件代码交付补录",
        json.dumps(public_commit, ensure_ascii=False, indent=2),
        "recorded",
        supersede_candidates=False,
    )
    receipt = store.verify_artifact_bytes(args.run_id, artifact["id"])
    payload = {
        "task_id": task["id"],
        "node_key": task["node_key"],
        "artifact_id": artifact["id"],
        "artifact_version": artifact["version"],
        "relative_path": artifact["relative_path"],
        "sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
        "backfilled": True,
        "delivery_mode": "local_commit",
        **public_commit,
    }
    store.append_run_event(
        args.run_id,
        "git.commit.created",
        "artifact",
        f"当前事件形成 Git Commit {commit['short_sha']}",
        f"{commit['subject']}；{commit['shortstat'] or str(commit['file_count']) + ' 个文件'}。",
        payload,
    )
    store.append_run_event(
        args.run_id,
        "git.commit.verified",
        "validation",
        f"Git Commit {commit['short_sha']} 已复核",
        "现有 Run 代码区已形成不可变 Commit，Commit 元数据 Artifact 字节与 Registry 一致。",
        {**payload, "status": "matched" if receipt["matched"] else "mismatch"},
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "created": True,
                "commit_sha": commit["commit_sha"],
                "artifact_id": artifact["id"],
                "file_count": commit["file_count"],
                "shortstat": commit["shortstat"],
                "verified": receipt["matched"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
