#!/usr/bin/env python3
"""Isolated child process used by the local-only fault harness.

Every write is constrained to a caller supplied work directory below delivery/.
The process never reads environment variables or provider credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
from typing import Any


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def confined(root: Path, raw: str) -> Path:
    root = root.resolve()
    path = (root / raw).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"path escapes work root: {raw}")
    return path


def judge(args: argparse.Namespace) -> int:
    work = Path(args.work_root).resolve()
    candidate_path = confined(work, args.candidate)
    verdict_path = confined(work, args.verdict)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    candidate_bytes = candidate_path.read_bytes()
    candidate = json.loads(candidate_bytes)
    missing = "platform_evidence_binding" not in candidate
    expected_reject = candidate.get("candidate_version") == 1
    if expected_reject and missing:
        verdict = {
            "verdict": "REJECT",
            "blocker_id": config["blocker_id"],
            "exit_code": 42,
            "candidate_sha256": digest(candidate_bytes),
            "reason": "required platform_evidence_binding is absent",
            "evidence_class": "observed_local_process",
            "acceptance_eligible": False,
        }
        write_json(verdict_path, verdict)
        return 42
    binding = candidate.get("platform_evidence_binding")
    valid = isinstance(binding, dict) and all(binding.get(k) for k in ("events_sha256", "sequence_last", "rejected_candidate_sha256", "rejected_verdict_sha256"))
    verdict = {
        "verdict": "ACCEPT" if valid else "REJECT",
        "blocker_id": None if valid else config["blocker_id"],
        "exit_code": 0 if valid else 42,
        "candidate_sha256": digest(candidate_bytes),
        "reason": "repaired candidate carries all frozen evidence and rejection bindings" if valid else "repair binding incomplete",
        "evidence_class": "observed_local_process",
        "acceptance_eligible": False,
    }
    write_json(verdict_path, verdict)
    return 0 if valid else 42


def memory_write(args: argparse.Namespace) -> int:
    db = Path(args.database)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS memory(namespace TEXT, memory_key TEXT, value TEXT, value_sha256 TEXT, PRIMARY KEY(namespace,memory_key))")
    value_sha = digest(args.value.encode("utf-8"))
    conn.execute("INSERT OR REPLACE INTO memory VALUES(?,?,?,?)", (args.namespace, args.memory_key, args.value, value_sha))
    conn.commit()
    conn.close()
    write_json(Path(args.receipt), {"operation": "write", "namespace": args.namespace, "memory_key": args.memory_key, "value_sha256": value_sha, "writer_pid": os.getpid()})
    return 0


def memory_read(args: argparse.Namespace) -> int:
    conn = sqlite3.connect(args.database)
    row = conn.execute("SELECT value,value_sha256 FROM memory WHERE namespace=? AND memory_key=?", (args.namespace, args.memory_key)).fetchone()
    conn.close()
    if row is None:
        write_json(Path(args.receipt), {"operation": "read", "status": "NAMESPACE_OR_KEY_NOT_FOUND", "reader_pid": os.getpid()})
        return 77
    value, value_sha = row
    valid = digest(value.encode("utf-8")) == value_sha == args.expected_sha256
    write_json(Path(args.receipt), {"operation": "read", "status": "MATCH" if valid else "MISMATCH", "value_sha256": value_sha, "reader_pid": os.getpid(), "used": valid})
    return 0 if valid else 78


def pause(args: argparse.Namespace) -> int:
    checkpoint = {
        "status": "PAUSED",
        "checkpoint_version": 1,
        "operation_id": args.operation_id,
        "completed_steps": ["prepare"],
        "pending_steps": ["continue", "finalize"],
        "writer_pid": os.getpid(),
    }
    write_json(Path(args.checkpoint), checkpoint)
    return 75


def resume(args: argparse.Namespace) -> int:
    source = Path(args.checkpoint)
    source_bytes = source.read_bytes()
    checkpoint = json.loads(source_bytes)
    valid = checkpoint.get("status") == "PAUSED" and checkpoint.get("operation_id") == args.operation_id
    result = {
        "status": "COMPLETED" if valid else "INVALID_CHECKPOINT",
        "operation_id": args.operation_id,
        "source_checkpoint_sha256": digest(source_bytes),
        "resumer_pid": os.getpid(),
        "completed_steps": ["prepare", "continue", "finalize"] if valid else [],
    }
    write_json(Path(args.result), result)
    return 0 if valid else 76


def crash_worker(args: argparse.Namespace) -> int:
    db = Path(args.database)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS effects(operation_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, payload_sha256 TEXT)")
    conn.execute("INSERT OR IGNORE INTO effects VALUES(?,?,?)", (args.operation_id, args.idempotency_key, digest(args.payload.encode("utf-8"))))
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    conn.close()
    write_json(Path(args.checkpoint), {"status": "SIDE_EFFECT_COMMITTED_TASK_IN_PROGRESS", "operation_id": args.operation_id, "idempotency_key": args.idempotency_key, "effect_count": count, "worker_pid": os.getpid()})
    write_json(Path(args.ready), {"ready": True, "worker_pid": os.getpid()})
    while True:
        time.sleep(1)


def recover_effect(args: argparse.Namespace) -> int:
    checkpoint_bytes = Path(args.checkpoint).read_bytes()
    checkpoint = json.loads(checkpoint_bytes)
    conn = sqlite3.connect(args.database)
    before = conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO effects VALUES(?,?,?)", (args.operation_id, args.idempotency_key, digest(args.payload.encode("utf-8"))))
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    conn.close()
    valid = checkpoint.get("operation_id") == args.operation_id and before == after == 1
    write_json(Path(args.receipt), {"status": "COMPLETED" if valid else "FAILED", "operation_id": args.operation_id, "idempotency_key": args.idempotency_key, "effect_count_before": before, "effect_count_after": after, "duplicate_suppressed": before == after, "checkpoint_sha256": digest(checkpoint_bytes), "recovery_pid": os.getpid()})
    return 0 if valid else 74


def dependency(args: argparse.Namespace) -> int:
    try:
        with socket.create_connection((args.host, args.port), timeout=1.0) as sock:
            sock.sendall(b"probe")
            response = sock.recv(16)
        ok = response == b"ok"
    except OSError as exc:
        write_json(Path(args.receipt), {"status": "DEPENDENCY_UNAVAILABLE", "error_type": type(exc).__name__, "worker_pid": os.getpid()})
        return 69
    write_json(Path(args.receipt), {"status": "DEPENDENCY_RECOVERED" if ok else "BAD_RESPONSE", "worker_pid": os.getpid()})
    return 0 if ok else 68


def file_write(args: argparse.Namespace) -> int:
    root = Path(args.work_root).resolve()
    try:
        target = confined(root, args.relative_path)
    except ValueError as exc:
        write_json(Path(args.receipt), {"status": "PATH_DENIED", "reason": str(exc), "worker_pid": os.getpid()})
        return 64
    data = args.content.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    write_json(Path(args.receipt), {"status": "WRITTEN", "path": target.relative_to(root).as_posix(), "size_bytes": len(data), "sha256": digest(data), "worker_pid": os.getpid()})
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("judge"); q.add_argument("--work-root", required=True); q.add_argument("--candidate", required=True); q.add_argument("--verdict", required=True); q.add_argument("--config", required=True)
    q = sub.add_parser("memory-write"); q.add_argument("--database", required=True); q.add_argument("--namespace", required=True); q.add_argument("--memory-key", required=True); q.add_argument("--value", required=True); q.add_argument("--receipt", required=True)
    q = sub.add_parser("memory-read"); q.add_argument("--database", required=True); q.add_argument("--namespace", required=True); q.add_argument("--memory-key", required=True); q.add_argument("--expected-sha256", required=True); q.add_argument("--receipt", required=True)
    q = sub.add_parser("pause"); q.add_argument("--checkpoint", required=True); q.add_argument("--operation-id", required=True)
    q = sub.add_parser("resume"); q.add_argument("--checkpoint", required=True); q.add_argument("--result", required=True); q.add_argument("--operation-id", required=True)
    q = sub.add_parser("crash-worker"); q.add_argument("--database", required=True); q.add_argument("--checkpoint", required=True); q.add_argument("--ready", required=True); q.add_argument("--operation-id", required=True); q.add_argument("--idempotency-key", required=True); q.add_argument("--payload", required=True)
    q = sub.add_parser("recover-effect"); q.add_argument("--database", required=True); q.add_argument("--checkpoint", required=True); q.add_argument("--receipt", required=True); q.add_argument("--operation-id", required=True); q.add_argument("--idempotency-key", required=True); q.add_argument("--payload", required=True)
    q = sub.add_parser("dependency"); q.add_argument("--host", default="127.0.0.1"); q.add_argument("--port", type=int, required=True); q.add_argument("--receipt", required=True)
    q = sub.add_parser("file-write"); q.add_argument("--work-root", required=True); q.add_argument("--relative-path", required=True); q.add_argument("--content", required=True); q.add_argument("--receipt", required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    return {
        "judge": judge,
        "memory-write": memory_write,
        "memory-read": memory_read,
        "pause": pause,
        "resume": resume,
        "crash-worker": crash_worker,
        "recover-effect": recover_effect,
        "dependency": dependency,
        "file-write": file_write,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
