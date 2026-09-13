from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

from . import NODE_KEY, RUN_ID

PAUSE_EXIT = 75
FAIL_EXIT = 73


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(root).as_posix().encode())
            h.update(b"\0")
            h.update(path.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def append_receipt(path: Path, record: dict[str, Any]) -> None:
    prior = "0" * 64
    sequence = 1
    if path.exists():
        lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        if lines:
            prior = lines[-1]["record_sha256"]
            sequence = lines[-1]["local_sequence"] + 1
    payload = {
        "local_sequence": sequence,
        "receipt_id": "local-receipt-" + uuid.uuid4().hex,
        "recorded_at": now(),
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "evidence_class": "observed_local_process",
        "acceptance_eligible": False,
        "platform_event_id": None,
        "previous_record_sha256": prior,
        **record,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    payload["record_sha256"] = hashlib.sha256(canonical).hexdigest()
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def worker_pause(work: Path, mode: str) -> int:
    checkpoint = work / "pause" / "checkpoint.json"
    lease = work / "pause" / "lease.json"
    if mode == "pause":
        atomic_json(checkpoint, {
            "logical_execution_id": "RP-PAUSE-EXEC-001",
            "state": "PAUSED",
            "completed_steps": ["input_loaded", "checkpoint_committed"],
            "pending_steps": ["finalize"],
            "writer_pid": os.getpid(),
            "lease_epoch": 1,
        })
        atomic_json(lease, {"lease_epoch": 1, "worker_pid": os.getpid(), "fencing_token": "RP-FENCE-EPOCH-1", "valid": True})
        return PAUSE_EXIT
    prior = json.loads(checkpoint.read_text(encoding="utf-8"))
    old_lease = json.loads(lease.read_text(encoding="utf-8"))
    old_lease["valid"] = False
    old_lease["revoked_by_epoch"] = 2
    atomic_json(work / "pause" / "old-lease.json", old_lease)
    atomic_json(lease, {"lease_epoch": 2, "worker_pid": os.getpid(), "fencing_token": "RP-FENCE-EPOCH-2", "valid": True})
    atomic_json(work / "pause" / "final.json", {
        "logical_execution_id": prior["logical_execution_id"],
        "state": "COMPLETED",
        "completed_steps": prior["completed_steps"] + ["finalize"],
        "pending_steps": [],
        "recovery_pid": os.getpid(),
        "loaded_checkpoint_sha256": file_sha(checkpoint),
        "old_worker_fenced": True,
    })
    return 0


def worker_failure(work: Path, mode: str) -> int:
    base = work / "failure"
    effect = base / "side-effect.json"
    operation_id = "RP-OP-FAILURE-001"
    key = "RP-IDEMPOTENCY-001"
    if mode == "fail":
        if not effect.exists():
            atomic_json(effect, {"operation_id": operation_id, "idempotency_key": key, "occurrences": 1, "committing_pid": os.getpid()})
        atomic_json(base / "fault.json", {"state": "FAILED_AFTER_SIDE_EFFECT", "operation_id": operation_id, "idempotency_key": key, "pid": os.getpid()})
        return FAIL_EXIT
    current = json.loads(effect.read_text(encoding="utf-8"))
    duplicate_suppressed = current["idempotency_key"] == key
    if not duplicate_suppressed:
        current["occurrences"] += 1
        atomic_json(effect, current)
    atomic_json(base / "recovery.json", {
        "state": "COMPLETED",
        "operation_id": operation_id,
        "idempotency_key": key,
        "recovery_pid": os.getpid(),
        "side_effect_duplicate_suppressed": duplicate_suppressed,
        "occurrences": json.loads(effect.read_text(encoding="utf-8"))["occurrences"],
        "side_effect_sha256": file_sha(effect),
    })
    return 0


def worker_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=("pause", "resume", "fail", "recover"))
    parser.add_argument("--work", required=True)
    args = parser.parse_args(argv)
    work = Path(args.work)
    if args.scenario in {"pause", "resume"}:
        return worker_pause(work, args.scenario)
    return worker_failure(work, args.scenario)


def run_faults(root: Path) -> dict[str, Any]:
    base = root / "evidence" / "runtime_probe" / "local_faults"
    if base.exists():
        shutil.rmtree(base)
    work = base / "work"
    ledger = base / "local-process-receipts.ndjson"
    work.mkdir(parents=True)
    env = {"PYTHONIOENCODING": "utf-8"}
    # Deliberately do not copy provider credentials or arbitrary parent environment.
    python_path = str(root)
    env["PYTHONPATH"] = python_path

    def invoke(scenario: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "runtime_probe.faults", scenario, "--work", str(work)],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    paused = invoke("pause")
    checkpoint = work / "pause" / "checkpoint.json"
    lease = work / "pause" / "lease.json"
    before = tree_digest(work / "pause")
    time.sleep(0.35)
    after = tree_digest(work / "pause")
    append_receipt(ledger, {"kind": "pause_process_exit", "exit_code": paused.returncode, "checkpoint_sha256": file_sha(checkpoint), "worker_pid": json.loads(checkpoint.read_text(encoding="utf-8"))["writer_pid"]})
    append_receipt(ledger, {"kind": "pause_quiet_window", "seconds": 0.35, "before_sha256": before, "after_sha256": after, "unchanged": before == after})
    resumed = invoke("resume")
    final_pause = json.loads((work / "pause" / "final.json").read_text(encoding="utf-8"))
    append_receipt(ledger, {"kind": "resume_process_exit", "exit_code": resumed.returncode, "recovery_pid": final_pause["recovery_pid"], "old_worker_fenced": final_pause["old_worker_fenced"]})

    failed = invoke("fail")
    effect = work / "failure" / "side-effect.json"
    pre_recovery_sha = file_sha(effect)
    append_receipt(ledger, {"kind": "post_side_effect_failure", "exit_code": failed.returncode, "side_effect_sha256": pre_recovery_sha})
    recovered = invoke("recover")
    post_recovery_sha = file_sha(effect)
    failure_result = json.loads((work / "failure" / "recovery.json").read_text(encoding="utf-8"))
    append_receipt(ledger, {"kind": "idempotent_recovery", "exit_code": recovered.returncode, "side_effect_sha256_before": pre_recovery_sha, "side_effect_sha256_after": post_recovery_sha, "duplicate_suppressed": failure_result["side_effect_duplicate_suppressed"], "occurrences": failure_result["occurrences"]})

    conditions = [
        paused.returncode == PAUSE_EXIT,
        before == after,
        resumed.returncode == 0,
        final_pause["old_worker_fenced"] is True,
        failed.returncode == FAIL_EXIT,
        recovered.returncode == 0,
        pre_recovery_sha == post_recovery_sha,
        failure_result["occurrences"] == 1,
        failure_result["side_effect_duplicate_suppressed"] is True,
    ]
    result = {
        "schema_version": "jianghu.local-fault-result.v1",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "status": "PASS_LOCAL_SCOPE" if all(conditions) else "FAIL",
        "evidence_class": "observed_local_process",
        "acceptance_eligible": False,
        "platform_or_sdk_resume_proven": False,
        "pause": {
            "pause_exit_code": paused.returncode,
            "resume_exit_code": resumed.returncode,
            "pause_pid": json.loads(checkpoint.read_text(encoding="utf-8"))["writer_pid"],
            "resume_pid": final_pause["recovery_pid"],
            "different_processes": json.loads(checkpoint.read_text(encoding="utf-8"))["writer_pid"] != final_pause["recovery_pid"],
            "checkpoint_sha256": file_sha(checkpoint),
            "quiet_window_seconds": 0.35,
            "quiet_window_unchanged": before == after,
            "old_worker_fenced": final_pause["old_worker_fenced"],
        },
        "failure_recovery": {
            "failure_exit_code": failed.returncode,
            "recovery_exit_code": recovered.returncode,
            "operation_id": failure_result["operation_id"],
            "idempotency_key": failure_result["idempotency_key"],
            "side_effect_sha256_before": pre_recovery_sha,
            "side_effect_sha256_after": post_recovery_sha,
            "side_effect_duplicate_suppressed": failure_result["side_effect_duplicate_suppressed"],
            "occurrences": failure_result["occurrences"],
        },
        "receipt_ledger_sha256": file_sha(ledger),
    }
    atomic_json(base / "result.json", result)
    if result["status"] != "PASS_LOCAL_SCOPE":
        raise RuntimeError("local fault drill did not converge")
    return result


if __name__ == "__main__":
    raise SystemExit(worker_main())
