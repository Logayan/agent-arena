#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path.cwd().resolve()
OUT = ROOT / "evidence/epoch46-owner-remediation-rerun/inspections/playwright-browsers-exclusion.json"
SNAPSHOT_REGISTRY = ROOT / ".jianghu-platform-evidence/snapshots/attempt-49d1df2dfeb3e1f2/artifact-registry.json"
CANDIDATE_ZIP = ROOT / "artifacts/Claude_Agent_SDK_迁移整改证据包_run_bda13e93b2ea_epoch46_owner.zip"
GIT_CONTEXT_VARIABLES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in GIT_CONTEXT_VARIABLES:
        environment.pop(name, None)
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=60, env=environment,
    )


def main() -> int:
    workspace_directories = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob(".playwright-browsers")
        if path.is_dir()
    )
    tracked = git("ls-files", "-z")
    tracked_hits = sorted(
        item for item in tracked.stdout.split("\0")
        if item and ".playwright-browsers" in item.replace("\\", "/").split("/")
    ) if tracked.returncode == 0 else []
    changes = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    change_hits = sorted(
        item for item in changes.stdout.split("\0")
        if item and ".playwright-browsers" in item.replace("\\", "/").split("/")
    ) if changes.returncode == 0 else []

    registry_hits: list[str] = []
    if SNAPSHOT_REGISTRY.is_file():
        registry_doc = json.loads(SNAPSHOT_REGISTRY.read_text(encoding="utf-8"))
        items = registry_doc if isinstance(registry_doc, list) else registry_doc.get("artifacts", registry_doc.get("items", []))
        for item in items:
            searchable = " ".join(str(item.get(key) or "") for key in ("title", "relative_path", "materialized_path", "path"))
            if ".playwright-browsers" in searchable.replace("\\", "/").split("/"):
                registry_hits.append(str(item.get("id") or "unknown"))

    package_hits: list[str] = []
    if CANDIDATE_ZIP.is_file():
        with zipfile.ZipFile(CANDIDATE_ZIP) as archive:
            package_hits = [
                name for name in archive.namelist()
                if ".playwright-browsers" in name.replace("\\", "/").split("/")
            ]

    excluded = not tracked_hits and not change_hits and not registry_hits and not package_hits
    result = {
        "schema_version": "jianghu.playwright-exclusion.v1",
        "workspace_directory_presence_allowed_if_excluded": workspace_directories,
        "git_tracked_hits": tracked_hits,
        "git_change_hits": change_hits,
        "frozen_artifact_registry_hits": registry_hits,
        "candidate_package_path": CANDIDATE_ZIP.relative_to(ROOT).as_posix(),
        "candidate_package_present": CANDIDATE_ZIP.is_file(),
        "candidate_package_hits": package_hits,
        "excluded_from_git_changes_registry_and_candidate": excluded,
        "status": "PASS" if excluded else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "workspace_directory_count": len(workspace_directories), "tracked_hits": len(tracked_hits), "change_hits": len(change_hits), "registry_hits": len(registry_hits), "package_hits": len(package_hits)}, ensure_ascii=False))
    return 0 if excluded else 1


if __name__ == "__main__":
    raise SystemExit(main())
