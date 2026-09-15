#!/usr/bin/env python3
"""Fail-closed verifier for the latest initiator-mandated product source baseline."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET = "b7c338a32c53e181079b0c769561ce0aebf630be"
OUT = ROOT / "evidence" / "epoch45-final-remediation" / "source-authority.json"
PRODUCT_ROOTS = ("client/", "server/")
REQUIRED_FILES = ("client/package.json", "server/app/platform_store.py", "server/claude_agent_runtime/bridge.mjs")


def git(*args: str) -> dict[str, Any]:
    environment = os.environ.copy()
    for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"
    ):
        environment.pop(key, None)
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    return {
        "command": ["git", *args],
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main() -> int:
    head = git("rev-parse", "HEAD")
    target = git("cat-file", "-e", f"{TARGET}^{{commit}}")
    origin = git("rev-parse", "--verify", "refs/remotes/origin/master")
    remotes = git("remote", "-v")
    status = git("status", "--short")
    tracked = git("ls-files", "client", "server")
    diff_check = git("diff", "--check")
    tracked_paths = [line for line in tracked["stdout"].splitlines() if line]
    required_presence = {name: (ROOT / name).is_file() for name in REQUIRED_FILES}
    checks = {
        "target_object_available": target["exit_code"] == 0,
        "origin_master_available": origin["exit_code"] == 0,
        "origin_master_equals_target": origin["stdout"] == TARGET,
        "head_equals_target": head["stdout"] == TARGET,
        "required_product_files_present": all(required_presence.values()),
        "product_tree_tracked": bool(tracked_paths),
        "clean_checkout": status["exit_code"] == 0 and not status["stdout"],
        "git_diff_check": diff_check["exit_code"] == 0,
        "command_cwd_is_delivery": Path.cwd().resolve() == ROOT.resolve(),
        "subst_not_used": not (len(str(ROOT)) >= 2 and str(ROOT)[1] == ":" and len(str(ROOT.anchor)) == 3 and str(ROOT)[0].upper() in {"J", "R"}),
    }
    passed = all(checks.values())
    result = {
        "schema_version": "jianghu.epoch45.source-authority.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required_authority": f"origin/master@{TARGET}",
        "latest_requirement_supersedes_targets": [
            "952a649", "c0332654e8b303a3f86be7103cef5005ebf34920", "58c0e52e0bb16386674b4c4edde6dd5fd3b5c7b0"
        ],
        "checkout_root": str(ROOT),
        "checkout_root_characters": len(str(ROOT)),
        "required_files": required_presence,
        "tracked_product_path_count": len(tracked_paths),
        "checks": checks,
        "commands": {
            "head": head,
            "target_object": target,
            "origin_master": origin,
            "remotes": remotes,
            "status": {**status, "stdout": "<nonempty>" if status["stdout"] else ""},
            "tracked_product_paths": {**tracked, "stdout": f"<{len(tracked_paths)} paths>" if tracked_paths else ""},
            "git_diff_check": diff_check,
        },
        "status": "PASS_SOURCE_AUTHORITY" if passed else "BLOCKED_SOURCE_AUTHORITY",
        "boundary": "The verifier never fetches, stages, commits, pushes, resets or rewrites history. Missing Git authority remains a hard blocker.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
