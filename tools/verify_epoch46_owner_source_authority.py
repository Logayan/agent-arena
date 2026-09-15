#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path.cwd().resolve()
OUT = ROOT / "evidence/epoch46-owner-remediation-rerun/inspections/source-authority.json"
EFFECTIVE_TARGET = "58c0e52e0bb16386674b4c4edde6dd5fd3b5c7b0"
CONFLICTING_SUPPLEMENT_TARGET = "b7c338a32c53e181079b0c769561ce0aebf630be"
GIT_CONTEXT_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in GIT_CONTEXT_VARIABLES:
        environment.pop(name, None)
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
        env=environment,
    )


def value(*arguments: str) -> str | None:
    result = git(*arguments)
    return result.stdout.strip() if result.returncode == 0 else None


def object_exists(commit: str) -> bool:
    return git("cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def main() -> int:
    if ROOT.name != "delivery":
        raise SystemExit("must run from delivery root")
    head = value("rev-parse", "HEAD")
    origin_master = value("rev-parse", "refs/remotes/origin/master")
    top_level = value("rev-parse", "--show-toplevel")
    branch = value("branch", "--show-current")
    tracked_raw = git("ls-files", "-z")
    tracked_count = len([item for item in tracked_raw.stdout.split("\0") if item]) if tracked_raw.returncode == 0 else 0
    status_raw = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    status_entry_count = len([item for item in status_raw.stdout.split("\0") if item]) if status_raw.returncode == 0 else None
    effective_object_available = object_exists(EFFECTIVE_TARGET)
    conflicting_object_available = object_exists(CONFLICTING_SUPPLEMENT_TARGET)
    origin_descends_from_effective = bool(
        effective_object_available and origin_master and is_ancestor(EFFECTIVE_TARGET, origin_master)
    )
    head_matches_origin = bool(head and origin_master and head == origin_master)
    product_paths = ["server/app", "server/tests", "server/claude_agent_runtime", "client/src", "client/e2e"]
    product_tree_present = all((ROOT / item).exists() for item in product_paths)
    source_authoritative = bool(
        effective_object_available
        and origin_master
        and origin_descends_from_effective
        and head_matches_origin
        and tracked_count > 0
        and status_entry_count == 0
        and product_tree_present
    )
    cwd = str(ROOT)
    short_root = len(cwd) < 100 and "run_bda13e93b2ea-" not in cwd
    result = {
        "schema_version": "jianghu.source-authority.v2",
        "run_id": "run_bda13e93b2ea",
        "run_version": 9,
        "execution_epoch": 46,
        "attempt_id": "attempt:run_bda13e93b2ea:remediation_rerun:epoch46:loop2:node1",
        "effective_target_commit": EFFECTIVE_TARGET,
        "conflicting_supplement_target_commit": CONFLICTING_SUPPLEMENT_TARGET,
        "conflict_resolution": "latest intervention naming 58c0e52 is the effective target; b7c338 is preserved as a conflicting supplement and is not averaged",
        "head": head,
        "origin_master": origin_master,
        "branch": branch,
        "git_top_level": top_level,
        "effective_target_object_available": effective_object_available,
        "conflicting_target_object_available": conflicting_object_available,
        "origin_master_descends_from_effective_target": origin_descends_from_effective,
        "head_matches_origin_master": head_matches_origin,
        "tracked_file_count": tracked_count,
        "working_tree_status_entry_count": status_entry_count,
        "product_tree_present": product_tree_present,
        "cwd": cwd,
        "cwd_length": len(cwd),
        "system_short_root_proven": short_root,
        "subst_used": False,
        "source_authoritative": source_authoritative,
        "status": "PASS_SOURCE_AUTHORITY" if source_authoritative else "BLOCKED_SOURCE_AUTHORITY",
        "system_short_root_status": "PASS" if short_root else "NOT_PROVEN",
        "operations_prohibited_and_not_performed": ["fetch", "reset", "push", "force-push", "history rewrite"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": result["status"],
        "system_short_root_status": result["system_short_root_status"],
        "effective_target_object_available": effective_object_available,
        "origin_master_available": origin_master is not None,
        "tracked_file_count": tracked_count,
        "working_tree_status_entry_count": status_entry_count,
    }, ensure_ascii=False))
    return 0 if source_authoritative and short_root else 2


if __name__ == "__main__":
    raise SystemExit(main())
