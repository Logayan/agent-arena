#!/usr/bin/env python3
"""Run reversible, isolated, observed-local-process acceptance probes.

This harness never emits Jianghu platform events. Its NDJSON records are clearly
marked acceptance_eligible=false and are used only to prove the engineering
fixture behaves as claimed before the platform exercises equivalent lifecycles.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "evidence" / "local-probes" / "work"
OUT = ROOT / "evidence" / "local-probes"
WORKER = ROOT / "tasks" / "probe_worker.py"
CONFIG = ROOT / "config" / "supplemental-predeclared-blocker.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


class Ledger:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.previous = "0" * 64

    def add(self, event_type: str, **payload: Any) -> None:
        base = {
            "sequence": len(self.rows) + 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "evidence_class": "observed_local_process",
            "acceptance_eligible": False,
            "platform_event": False,
            "run_id": "run_9226059d74a1",
            "node_key": "runtime_probe_harness",
            "previous_record_sha256": self.previous,
            "payload": payload,
        }
        record_hash = sha(json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        base["record_sha256"] = record_hash
        self.rows.append(base)
        self.previous = record_hash

    def write(self, path: Path) -> None:
        path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in self.rows), encoding="utf-8")


def run_child(label: str, args: list[str], expected: set[int], commands: list[dict[str, Any]], ledger: Ledger) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(WORKER), *args]
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, timeout=30)
    receipt = {
        "label": label,
        "argv": [rel(Path(x)) if i == 1 else x for i, x in enumerate(argv)],
        "cwd": ".",
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": proc.returncode,
        "expected_exit_codes": sorted(expected),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "status": "EXPECTED" if proc.returncode in expected else "UNEXPECTED",
    }
    commands.append(receipt)
    ledger.add("LOCAL_COMMAND_COMPLETED", label=label, exit_code=proc.returncode, expected=proc.returncode in expected)
    if proc.returncode not in expected:
        raise RuntimeError(f"{label} exit={proc.returncode}, expected={sorted(expected)}: {proc.stderr}")
    return proc


def start_one_shot_server(port: int, ready: threading.Event) -> threading.Thread:
    def serve() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", port)); server.listen(1); ready.set()
            conn, _ = server.accept()
            with conn:
                conn.recv(16); conn.sendall(b"ok")
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def run() -> dict[str, Any]:
    if OUT.exists():
        shutil.rmtree(OUT)
    WORK.mkdir(parents=True)
    commands: list[dict[str, Any]] = []
    ledger = Ledger()
    ledger.add("LOCAL_HARNESS_STARTED", work_root=rel(WORK))

    # The declaration is a source-controlled input and is validated before V1 exists.
    blocker = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not blocker.get("declared_before_candidate_execution"):
        raise RuntimeError("negative gate was not predeclared")
    ledger.add("LOCAL_PREDECLARED_BLOCKER_LOADED", blocker_id=blocker["blocker_id"], config_sha256=sha(CONFIG.read_bytes()))

    snapshot_index = json.loads((ROOT / "evidence" / "runtime_probe" / "evidence-index.json").read_text(encoding="utf-8"))
    projection = dict(snapshot_index["snapshot"]["projection"])
    projection["event_sha256"] = snapshot_index["snapshot"]["core_files"]["events.ndjson"]["sha256"]
    candidate_v1 = {
        "schema_version": "jianghu.local-candidate.v1",
        "candidate_version": 1,
        "run_id": "run_9226059d74a1",
        "node_key": "runtime_probe_harness",
        "claim": "local harness candidate deliberately missing a mandatory evidence binding",
        "acceptance_eligible": False,
    }
    c1 = WORK / "judge" / "candidate-v1.json"; write_json(c1, candidate_v1)
    c1_before = c1.read_bytes()
    v1 = WORK / "judge" / "verdict-v1.json"
    run_child("negative-gate-v1-reject", ["judge", "--work-root", str(WORK), "--candidate", "judge/candidate-v1.json", "--verdict", "judge/verdict-v1.json", "--config", str(CONFIG)], {42}, commands, ledger)
    if c1.read_bytes() != c1_before:
        raise RuntimeError("rejected candidate was mutated")
    verdict_v1 = json.loads(v1.read_text(encoding="utf-8"))
    ledger.add("LOCAL_CANDIDATE_REJECTED", blocker_id=verdict_v1["blocker_id"], candidate_sha256=sha(c1_before), verdict_sha256=sha(v1.read_bytes()), candidate_unchanged=True)

    candidate_v2 = {
        "schema_version": "jianghu.local-candidate.v1",
        "candidate_version": 2,
        "run_id": "run_9226059d74a1",
        "node_key": "runtime_probe_harness",
        "supersedes_local_candidate_sha256": sha(c1_before),
        "platform_evidence_binding": {
            "events_sha256": projection["event_sha256"],
            "sequence_last": projection["sequence_last"],
            "rejected_candidate_sha256": sha(c1_before),
            "rejected_verdict_sha256": sha(v1.read_bytes()),
        },
        "acceptance_eligible": False,
    }
    c2 = WORK / "judge" / "candidate-v2.json"; write_json(c2, candidate_v2)
    v2 = WORK / "judge" / "verdict-v2.json"
    run_child("negative-gate-v2-accept", ["judge", "--work-root", str(WORK), "--candidate", "judge/candidate-v2.json", "--verdict", "judge/verdict-v2.json", "--config", str(CONFIG)], {0}, commands, ledger)
    ledger.add("LOCAL_REPAIR_ACCEPTED", candidate_v2_sha256=sha(c2.read_bytes()), verdict_v2_sha256=sha(v2.read_bytes()), supersedes_sha256=sha(c1_before))

    memory_db = WORK / "memory" / "memory.sqlite3"
    value = "runtime-probe-memory-value-v1"; value_sha = sha(value.encode("utf-8"))
    mw = WORK / "memory" / "write-receipt.json"; mr = WORK / "memory" / "read-receipt.json"; bad = WORK / "memory" / "wrong-namespace.json"
    run_child("memory-write-process", ["memory-write", "--database", str(memory_db), "--namespace", "run_9226059d74a1/runtime_probe_harness", "--memory-key", "probe-memory", "--value", value, "--receipt", str(mw)], {0}, commands, ledger)
    run_child("memory-read-process", ["memory-read", "--database", str(memory_db), "--namespace", "run_9226059d74a1/runtime_probe_harness", "--memory-key", "probe-memory", "--expected-sha256", value_sha, "--receipt", str(mr)], {0}, commands, ledger)
    run_child("memory-wrong-namespace-denied", ["memory-read", "--database", str(memory_db), "--namespace", "other-run", "--memory-key", "probe-memory", "--expected-sha256", value_sha, "--receipt", str(bad)], {77}, commands, ledger)
    writer_pid = json.loads(mw.read_text(encoding="utf-8"))["writer_pid"]; reader_pid = json.loads(mr.read_text(encoding="utf-8"))["reader_pid"]
    if writer_pid == reader_pid:
        raise RuntimeError("memory write and read did not use distinct processes")
    ledger.add("LOCAL_MEMORY_ROUNDTRIP_VERIFIED", writer_pid=writer_pid, reader_pid=reader_pid, value_sha256=value_sha, wrong_namespace_exit=77)

    checkpoint = WORK / "pause" / "checkpoint-paused.json"; resumed = WORK / "pause" / "checkpoint-resumed.json"; operation = "pause-op-run-9226059d74a1"
    run_child("pause-process", ["pause", "--checkpoint", str(checkpoint), "--operation-id", operation], {75}, commands, ledger)
    checkpoint_hash = sha(checkpoint.read_bytes()); checkpoint_bytes = checkpoint.read_bytes(); time.sleep(0.25)
    if checkpoint.read_bytes() != checkpoint_bytes:
        raise RuntimeError("checkpoint changed during pause silent interval")
    run_child("resume-process", ["resume", "--checkpoint", str(checkpoint), "--result", str(resumed), "--operation-id", operation], {0}, commands, ledger)
    paused_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    resume_payload = json.loads(resumed.read_text(encoding="utf-8"))
    pause_pid = paused_payload["writer_pid"]; resume_pid = resume_payload["resumer_pid"]
    if resume_payload["source_checkpoint_sha256"] != checkpoint_hash or pause_pid == resume_pid:
        raise RuntimeError("resumer did not bind the paused checkpoint from a distinct process")
    ledger.add("LOCAL_PAUSE_RESUME_VERIFIED", checkpoint_sha256=checkpoint_hash, pause_silent_seconds=0.25, pause_exit=75, resume_exit=0, pause_pid=pause_pid, resume_pid=resume_pid, different_pids=True)

    effect_db = WORK / "failure" / "effects.sqlite3"; effect_checkpoint = WORK / "failure" / "checkpoint.json"; ready_path = WORK / "failure" / "ready.json"; recovery_receipt = WORK / "failure" / "recovery.json"
    operation_id = "effect-op-run-9226059d74a1"; idempotency_key = "idempotency-run-9226059d74a1"; payload = "single-side-effect"
    argv = [sys.executable, str(WORKER), "crash-worker", "--database", str(effect_db), "--checkpoint", str(effect_checkpoint), "--ready", str(ready_path), "--operation-id", operation_id, "--idempotency-key", idempotency_key, "--payload", payload]
    killed = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 10
    while not ready_path.exists() and time.time() < deadline:
        if killed.poll() is not None:
            raise RuntimeError(f"crash worker exited before ready: {killed.returncode}")
        time.sleep(0.05)
    if not ready_path.exists():
        killed.kill(); raise RuntimeError("crash worker readiness timeout")
    old_pid = killed.pid; checkpoint_before_kill = effect_checkpoint.read_bytes(); db_before_kill = effect_db.read_bytes()
    alive_before = killed.poll() is None
    killed.kill(); stdout, stderr = killed.communicate(timeout=10)
    alive_after = killed.poll() is None
    commands.append({"label": "os-force-kill-worker", "argv": [rel(Path(argv[1])), *argv[2:]], "cwd": ".", "pid": old_pid, "alive_before_kill": alive_before, "alive_after_kill": alive_after, "exit_code": killed.returncode, "stdout": stdout, "stderr": stderr, "status": "EXPECTED_FORCE_TERMINATION"})
    if not alive_before or alive_after or effect_checkpoint.read_bytes() != checkpoint_before_kill or effect_db.read_bytes() != db_before_kill:
        raise RuntimeError("force-kill durability conditions failed")
    ledger.add("LOCAL_PROCESS_FORCE_TERMINATED", old_worker_pid=old_pid, return_code=killed.returncode, checkpoint_sha256=sha(checkpoint_before_kill), database_sha256=sha(db_before_kill))
    run_child("idempotent-recovery-process", ["recover-effect", "--database", str(effect_db), "--checkpoint", str(effect_checkpoint), "--receipt", str(recovery_receipt), "--operation-id", operation_id, "--idempotency-key", idempotency_key, "--payload", payload], {0}, commands, ledger)
    recovered = json.loads(recovery_receipt.read_text(encoding="utf-8"))
    if recovered["recovery_pid"] == old_pid or recovered["effect_count_after"] != 1 or not recovered["duplicate_suppressed"]:
        raise RuntimeError("idempotent recovery conditions failed")
    ledger.add("LOCAL_IDEMPOTENT_RECOVERY_VERIFIED", old_worker_pid=old_pid, recovery_pid=recovered["recovery_pid"], effect_count=recovered["effect_count_after"], duplicate_suppressed=True)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserve:
        reserve.bind(("127.0.0.1", 0)); port = reserve.getsockname()[1]
    dependency_fail = WORK / "dependency" / "failed.json"; dependency_ok = WORK / "dependency" / "recovered.json"
    run_child("dependency-unavailable-process", ["dependency", "--port", str(port), "--receipt", str(dependency_fail)], {69}, commands, ledger)
    ready = threading.Event(); server = start_one_shot_server(port, ready)
    if not ready.wait(5):
        raise RuntimeError("dependency recovery server did not start")
    run_child("dependency-recovered-process", ["dependency", "--port", str(port), "--receipt", str(dependency_ok)], {0}, commands, ledger)
    server.join(timeout=5)
    ledger.add("LOCAL_DEPENDENCY_FAILURE_RECOVERY_VERIFIED", first_exit=69, retry_exit=0, host="127.0.0.1", port=port)

    file_receipt = WORK / "file" / "write.json"; deny_receipt = WORK / "file" / "deny.json"
    run_child("file-delivery-process", ["file-write", "--work-root", str(WORK), "--relative-path", "file/delivered.txt", "--content", "runtime-probe-file-roundtrip", "--receipt", str(file_receipt)], {0}, commands, ledger)
    run_child("file-path-escape-denied", ["file-write", "--work-root", str(WORK), "--relative-path", "../escape.txt", "--content", "must-not-write", "--receipt", str(deny_receipt)], {64}, commands, ledger)
    file_data = (WORK / "file" / "delivered.txt").read_bytes(); file_meta = json.loads(file_receipt.read_text(encoding="utf-8"))
    if file_meta["sha256"] != sha(file_data) or (OUT / "escape.txt").exists():
        raise RuntimeError("file delivery/path boundary conditions failed")
    ledger.add("LOCAL_FILE_DELIVERY_VERIFIED", file_sha256=sha(file_data), size_bytes=len(file_data), path_escape_exit=64)

    ledger.add("LOCAL_HARNESS_COMPLETED", status="PASS_LOCAL_SCOPE", acceptance_eligible=False)
    ledger_path = OUT / "events.ndjson"; ledger.write(ledger_path)
    write_json(OUT / "commands.json", commands)
    proof = {
        "schema_version": "jianghu.local-probe-proof.v1",
        "run_id": "run_9226059d74a1",
        "node_key": "runtime_probe_harness",
        "status": "PASS_LOCAL_SCOPE",
        "evidence_class": "observed_local_process",
        "acceptance_eligible": False,
        "platform_session_id": None,
        "claude_sdk_session_id": None,
        "event_count": len(ledger.rows),
        "event_chain_head_sha256": ledger.previous,
        "commands": len(commands),
        "negative_gate": {"blocker_id": blocker["blocker_id"], "v1_exit": 42, "v1_verdict": "REJECT", "v1_unchanged": True, "v2_exit": 0, "v2_verdict": "ACCEPT", "platform_judge_event": False},
        "memory": {"writer_pid": writer_pid, "reader_pid": reader_pid, "distinct_processes": writer_pid != reader_pid, "wrong_namespace_exit": 77, "value_sha256": value_sha},
        "pause_resume": {"pause_exit": 75, "resume_exit": 0, "pause_pid": pause_pid, "resume_pid": resume_pid, "distinct_processes": pause_pid != resume_pid, "checkpoint_sha256": checkpoint_hash, "silent_window_seconds": 0.25, "checkpoint_unchanged": True},
        "failure_recovery": {"old_worker_pid": old_pid, "old_worker_exit": killed.returncode, "recovery_pid": recovered["recovery_pid"], "distinct_processes": old_pid != recovered["recovery_pid"], "effect_count": 1, "duplicate_suppressed": True},
        "dependency": {"first_exit": 69, "retry_exit": 0},
        "file_delivery": {"sha256": sha(file_data), "size_bytes": len(file_data), "path_escape_exit": 64},
        "boundary": "This proves the supplied local engineering harness only. It does not prove Jianghu orchestrator, Worker lease, Claude SDK Session, platform Memory, platform Judge, or platform pause/resume semantics.",
    }
    write_json(OUT / "local-probe-proof.json", proof)
    return proof


def main() -> int:
    proof = run()
    print(f"LOCAL_PROBES_PASS events={proof['event_count']} commands={proof['commands']} acceptance_eligible={str(proof['acceptance_eligible']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
