#!/usr/bin/env python3
"""Run a credential-isolated command and emit immutable local receipts.

The runner never serializes environment values. ``__SYSTEM_TEMP__`` in a
command argument or safe environment value is replaced with a fresh short
folder beneath the inherited system TEMP and removed after the child exits.
Only explicitly expected outputs inside this delivery checkout are indexed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_FRAGMENTS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "APIKEY",
    "CREDENTIAL",
    "ANTHROPIC",
    "OPENAI",
    "CLAUDE",
)
GIT_OVERRIDE_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)
TEMP_TOKEN = "__SYSTEM_TEMP__"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_file(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def within(path: Path, root: Path) -> bool:
    try:
        return Path(os.path.realpath(path)).is_relative_to(Path(os.path.realpath(root)))
    except (OSError, RuntimeError, ValueError):
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, default=Path("."))
    parser.add_argument("--safe-env", action="append", default=[])
    parser.add_argument("--expect", type=Path, action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def output_receipt(path: Path, checkout: Path) -> dict[str, Any]:
    if not within(path, checkout):
        return {"path": str(path), "exists": False, "reason": "path_outside_delivery"}
    relative = path.relative_to(checkout).as_posix()
    if path.is_file():
        return {"path": relative, "exists": True, "kind": "file", **digest_file(path)}
    if path.is_dir():
        files = []
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
            files.append({"path": item.relative_to(path).as_posix(), **digest_file(item)})
        manifest_bytes = json.dumps(
            files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return {
            "path": relative,
            "exists": True,
            "kind": "directory",
            "nonempty": bool(files),
            "file_count": len(files),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "files": files,
        }
    return {"path": relative, "exists": False}


def main() -> int:
    args = parse_args()
    checkout = absolute(Path.cwd())
    evidence_root = absolute(args.evidence_root)
    child_cwd = absolute(args.cwd)
    if not within(evidence_root, checkout) or not within(child_cwd, checkout):
        raise SystemExit("path_outside_delivery")
    evidence_root.mkdir(parents=True, exist_ok=True)

    safe_environment: dict[str, str] = {}
    for item in args.safe_env:
        if "=" not in item:
            raise SystemExit("safe_env_must_be_key_equals_value")
        key, value = item.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key or any(fragment in normalized_key.upper() for fragment in SENSITIVE_FRAGMENTS):
            raise SystemExit("unsafe_environment_key")
        safe_environment[normalized_key] = value

    inherited = {
        key: value
        for key, value in os.environ.items()
        if not any(fragment in key.upper() for fragment in SENSITIVE_FRAGMENTS)
    }
    for key in GIT_OVERRIDE_KEYS:
        inherited.pop(key, None)
    inherited.update(safe_environment)

    uses_system_temp = any(TEMP_TOKEN in item for item in args.command) or any(
        TEMP_TOKEN in value for value in safe_environment.values()
    )
    temp_root: Path | None = None
    if uses_system_temp:
        temp_root = Path(
            tempfile.mkdtemp(prefix="jh-acceptance-", dir=os.environ["TEMP"])
        )
    replacement = str(temp_root) if temp_root else TEMP_TOKEN
    command = [item.replace(TEMP_TOKEN, replacement) for item in args.command]
    for key, value in list(inherited.items()):
        inherited[key] = value.replace(TEMP_TOKEN, replacement)

    stdout_path = evidence_root / f"{args.id}.stdout.log"
    stderr_path = evidence_root / f"{args.id}.stderr.log"
    receipt_path = evidence_root / f"{args.id}.receipt.json"
    started_at = timestamp()
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                completed = subprocess.run(
                    command,
                    cwd=child_cwd,
                    env=inherited,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
                exit_code = int(completed.returncode)
                launch_error = None
            except OSError as error:
                exit_code = 127
                launch_error = type(error).__name__
                stderr.write(f"command_launch_failed:{launch_error}\n".encode("utf-8"))
        expected_outputs = [
            output_receipt(absolute(path), checkout)
            for path in args.expect
        ]
        expected_outputs_valid = all(
            item.get("exists") is True
            and (item.get("kind") != "directory" or item.get("nonempty") is True)
            for item in expected_outputs
        )
        effective_exit_code = exit_code if exit_code else (0 if expected_outputs_valid else 2)
        receipt = {
            "schema_version": "jianghu.recorded-command-receipt.v1",
            "id": args.id,
            "command": [item.replace(replacement, TEMP_TOKEN) for item in command],
            "workdir": child_cwd.relative_to(checkout).as_posix() or ".",
            "environment_policy": (
                "credential-isolated; provider-like variables and inherited Git overrides removed; "
                "environment values not serialized"
            ),
            "safe_environment_keys": sorted(safe_environment),
            "system_temp_used": uses_system_temp,
            "started_at": started_at,
            "finished_at": timestamp(),
            "child_exit_code": exit_code,
            "exit_code": effective_exit_code,
            "launch_error": launch_error,
            "stdout": {
                "path": stdout_path.relative_to(checkout).as_posix(),
                **digest_file(stdout_path),
            },
            "stderr": {
                "path": stderr_path.relative_to(checkout).as_posix(),
                **digest_file(stderr_path),
            },
            "expected_outputs_valid": expected_outputs_valid,
            "expected_outputs": expected_outputs,
        }
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "id": args.id,
                    "exit_code": effective_exit_code,
                    "expected_outputs_valid": expected_outputs_valid,
                    "receipt": receipt_path.relative_to(checkout).as_posix(),
                },
                ensure_ascii=False,
            )
        )
        return effective_exit_code
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
