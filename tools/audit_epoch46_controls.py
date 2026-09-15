#!/usr/bin/env python3
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path.cwd().resolve()
SNAPSHOT = ROOT / ".jianghu-platform-evidence/snapshots/attempt-49d1df2dfeb3e1f2"
OUT = ROOT / "evidence/epoch46-owner-remediation-rerun/inspections"
ATTEMPT = "attempt:run_bda13e93b2ea:remediation_rerun:epoch46:loop2:node1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(name: str, value: object) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_events() -> tuple[list[dict], Counter]:
    events: list[dict] = []
    counts: Counter = Counter()
    with (SNAPSHOT / "events.ndjson").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
            counts[str(event.get("type") or "")] += 1
    return events, counts


def png_receipt(path: Path) -> dict:
    data = path.read_bytes()
    valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = height = 0
    chunks = 0
    crc_valid = valid
    while valid and offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
        observed_crc = binascii.crc32(chunk_type)
        observed_crc = binascii.crc32(payload, observed_crc) & 0xFFFFFFFF
        crc_valid = crc_valid and expected_crc == observed_crc
        chunks += 1
        if chunk_type == b"IHDR" and len(payload) >= 8:
            width, height = struct.unpack(">II", payload[:8])
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    return {
        "path": path.relative_to(ROOT).as_posix(), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "png_signature": valid, "chunk_crc_valid": crc_valid, "width": width, "height": height,
        "chunk_count": chunks, "status": "PASS" if valid and crc_valid and width > 0 and height > 0 else "FAIL",
    }


def media_audit() -> dict:
    base = ROOT / "evidence/epoch46-owner-remediation-rerun/e2e/results"
    manifest = json.loads((base / "sha256-manifest.json").read_text(encoding="utf-8"))
    manifest_failures = []
    for item in manifest["files"]:
        path = base / item["path"]
        if not path.is_file() or path.stat().st_size != int(item["size_bytes"]) or digest(path) != item["sha256"]:
            manifest_failures.append(item["path"])
    screenshots = [png_receipt(base / item["path"]) for item in manifest["files"] if item["path"].endswith(".png")]
    har = json.loads((base / "network.har").read_text(encoding="utf-8"))
    entries = list((har.get("log") or {}).get("entries") or [])
    http_errors = [int((item.get("response") or {}).get("status") or 0) for item in entries if int((item.get("response") or {}).get("status") or 0) >= 400]
    failed_requests = [item for item in entries if item.get("_failureText")]
    with zipfile.ZipFile(base / "playwright-trace.zip") as archive:
        trace_bad = archive.testzip()
        trace_members = len(archive.infolist())
    result = {
        "manifest_entry_count": len(manifest["files"]), "manifest_failures": manifest_failures,
        "screenshots": screenshots, "screenshot_count": len(screenshots),
        "har_entry_count": len(entries), "har_http_error_count": len(http_errors), "har_failed_request_count": len(failed_requests),
        "trace_member_count": trace_members, "trace_crc_failure": trace_bad,
        "browser_download": next((item for item in manifest["files"] if item["path"].startswith("downloads/")), None),
        "status": "PASS" if not manifest_failures and all(item["status"] == "PASS" for item in screenshots) and not http_errors and not failed_requests and trace_bad is None else "FAIL",
    }
    dump("e2e-media-verification.json", result)
    return result


def control_audit() -> dict:
    events, counts = load_events()
    metadata = json.loads((SNAPSHOT / "run-metadata.json").read_text(encoding="utf-8"))
    runtime = json.loads((SNAPSHOT / "runtime-attestation.json").read_text(encoding="utf-8"))
    source = json.loads((SNAPSHOT / "runtime-source-attestation.json").read_text(encoding="utf-8"))
    registry = json.loads((SNAPSHOT / "artifact-registry.json").read_text(encoding="utf-8"))
    registry_by_id = {item["id"]: item for item in registry}
    attempt_created = next(event for event in events if event["type"] == "attempt.created" and str((event.get("payload") or {}).get("platform_attempt_id") or "") == ATTEMPT)
    current_events = [event for event in events if int(event["sequence"]) >= int(attempt_created["sequence"])]
    current_counts = Counter(str(event.get("type") or "") for event in current_events)
    supersedes_id = str((attempt_created.get("payload") or {}).get("supersedes") or "")
    predecessor = registry_by_id.get(supersedes_id)
    authority_frozen = [event for event in events if event["type"] == "artifact.authority.frozen"]
    key_types = [
        "agent.turn.completed", "team.member.completed", "agent.message.sent", "agent.memory.committed",
        "agent.memory.closure.verified", "run.pause_requested", "run.checkpoint.persisted", "run.paused",
        "run.resumed", "run.checkpoint.loaded", "run.interrupted", "run.recovered", "agent.runtime.recovered",
        "worker.fencing.verified", "worker.stale_writer.denied", "worker.duplicate_side_effect.scan",
        "gate.rejected", "artifact.authoritative", "artifact.authority.frozen", "judge.verdict.accepted",
        "gate.passed", "run.converged", "run.completed",
    ]
    result = {
        "run_id": metadata["id"], "execution_epoch": metadata["execution_epoch"], "cutoff_sequence": metadata["cutoff_sequence"],
        "run_status": metadata["status"], "runtime_health": runtime["runtime_health"],
        "runtime_session_binding_count": runtime["session_binding_count"],
        "runtime_distinct_agent_count": runtime["distinct_agent_count"],
        "runtime_distinct_sdk_session_count": runtime["distinct_sdk_session_count"],
        "runtime_source_attestation_status": source["status"],
        "registry_artifact_count": len(registry),
        "run_level_key_event_counts": {key: counts[key] for key in key_types},
        "current_attempt": {
            "id": ATTEMPT, "start_sequence": attempt_created["sequence"], "event_count": len(current_events),
            "event_counts": dict(sorted(current_counts.items())),
            "completed_turn_present": current_counts["agent.turn.completed"] > 0,
            "two_round_messages_present": current_counts["agent.message.sent"] >= 4,
            "memory_closure_present": current_counts["agent.memory.closure.verified"] > 0,
            "artifact_authority_frozen_present": current_counts["artifact.authority.frozen"] > 0,
        },
        "semantic_supersession": {
            "supersedes_artifact_id": supersedes_id,
            "artifact_found": predecessor is not None,
            "artifact_kind": predecessor.get("kind") if predecessor else None,
            "artifact_status": predecessor.get("status") if predecessor else None,
            "same_task": bool(predecessor and predecessor.get("task_id") == (attempt_created.get("payload") or {}).get("task_id")),
            "valid_workflow_output_predecessor": bool(predecessor and predecessor.get("kind") == "workflow_output"),
        },
        "latest_authority_freeze": (
            {
                "sequence": authority_frozen[-1]["sequence"],
                "event_id": authority_frozen[-1]["event_id"],
                "platform_attempt_id": (authority_frozen[-1].get("payload") or {}).get("platform_attempt_id"),
                "authority_artifact_count": (authority_frozen[-1].get("payload") or {}).get("authority_artifact_count"),
                "authority_manifest_sha256": (authority_frozen[-1].get("payload") or {}).get("authority_manifest_sha256"),
                "status": (authority_frozen[-1].get("payload") or {}).get("status"),
            }
            if authority_frozen else None
        ),
        "current_attempt_authority_is_distinct_from_historical": not authority_frozen or int(authority_frozen[-1]["sequence"]) >= int(attempt_created["sequence"]),
    }
    dump("runtime-control-audit.json", result)
    return result


def cam_and_gaps(control: dict, media: dict) -> None:
    cam = [
        {"id": "CAM-00", "name": "冻结快照同游标一致性与边界声明", "status": "BLOCKED", "release_pass": False, "evidence": "snapshot-verification.json：内容域精确，但冻结包缺少新 boundary attestation 字段"},
        {"id": "CAM-01", "name": "源码权威与目标 Git 基线", "status": "BLOCKED", "release_pass": False, "evidence": "effective target=58c0e52...；冲突补充 b7c338... 保留；当前 checkout 两者均未证明"},
        {"id": "CAM-02", "name": "Claude Agent SDK 生产 Runtime 与 OpenClaw 静态退场", "status": "PASS", "release_pass": True, "evidence": "runtime-source-attestation status=passed；OpenClaw prohibited findings=0"},
        {"id": "CAM-03", "name": "当前 Attempt completed-turn SDK 绑定", "status": "BLOCKED", "release_pass": False, "evidence": "current attempt agent.turn.completed=0"},
        {"id": "CAM-04", "name": "Tool、文件与 Artifact 原始字节链", "status": "PARTIAL", "release_pass": False, "evidence": f"Registry {control['registry_artifact_count']} items independently scanned；当前候选包尚未登记"},
        {"id": "CAM-05", "name": "当前 Attempt 两轮公开协作", "status": "BLOCKED", "release_pass": False, "evidence": "current attempt agent.message.sent=0"},
        {"id": "CAM-06", "name": "Judge 退回、不可变返工与语义 supersedes", "status": "PARTIAL", "release_pass": False, "evidence": f"rework_of 存在；supersedes={control['semantic_supersession']['supersedes_artifact_id']} kind={control['semantic_supersession']['artifact_kind']}，非 workflow_output"},
        {"id": "CAM-07", "name": "Memory 写回、持久化与后续不同 SDK Session 使用", "status": "PARTIAL", "release_pass": False, "evidence": "Run 历史 closure.verified=42；当前 Attempt=0"},
        {"id": "CAM-08", "name": "暂停、Checkpoint 与恢复", "status": "PASS_RUN_LEVEL", "release_pass": True, "evidence": "run.paused=11、run.resumed=11、checkpoint persisted=13/loaded=55"},
        {"id": "CAM-09", "name": "Worker/Runtime 恢复与 exactly-once 终态对账", "status": "PARTIAL", "release_pass": False, "evidence": "worker fencing/stale-writer 有事件；duplicate scan 仍非 terminal reconciliation"},
        {"id": "CAM-10", "name": "全量测试、Bridge、Build 与真实浏览器 E2E", "status": "PASS", "release_pass": True, "evidence": "E46-OWNER-UNIQUE-263-v1=263/263；frontend build PASS；E2E media=" + media["status"]},
        {"id": "CAM-11", "name": "当前候选包 Registry、authority 与浏览器下载闭环", "status": "BLOCKED", "release_pass": False, "evidence": f"本 turn 新包没有 Artifact ID；EVC-009 下载的是既有 Registry Artifact（{(media.get('browser_download') or {}).get('path')}）"},
        {"id": "CAM-12", "name": "独立 Judge ACCEPT 到 Run 完成终态链", "status": "BLOCKED", "release_pass": False, "evidence": "judge.verdict.accepted/gate.passed/run.converged/run.completed 均为 0"},
    ]
    cam_doc = {
        "denominator_id": "E46-CAM-13-v1", "total": len(cam),
        "release_pass": sum(1 for item in cam if item["release_pass"]),
        "not_release_pass": sum(1 for item in cam if not item["release_pass"]),
        "controls": cam, "overall": "NO_GO" if any(not item["release_pass"] for item in cam) else "PASS",
    }
    gaps = [
        {"id": "G46-001", "severity": "P0", "title": "目标源码基线 authority 未建立", "closure": "干净 product checkout 中 HEAD/origin/master 精确绑定有效目标 58c0e52... 或更新已推送提交；冲突 b7c338... 单独裁决"},
        {"id": "G46-002", "severity": "P0", "title": "58c0e52 所要求的 Windows 系统短根行为未证明", "closure": "不用 SUBST，在系统短根 checkout 重跑 build/test/E2E；记录 cwd 与长度"},
        {"id": "G46-003", "severity": "P0", "title": "平台冻结包未含整改后的 snapshot boundary attestation", "closure": "post-turn 新快照含 first_event_sequence/coherent/boundary_rule 且 verifier PASS"},
        {"id": "G46-004", "severity": "P0", "title": "当前 Attempt 尚无 completed turn 与 SDK binding", "closure": "post-turn snapshot 出现当前 platform_attempt_id 的 completed turn 和 attestation binding"},
        {"id": "G46-005", "severity": "P0", "title": "当前 Attempt 两轮公开协作尚未闭合", "closure": "当前 Attempt 的轮次 1/2 消息、synthesis、decision、freeze 全部出现"},
        {"id": "G46-006", "severity": "P0", "title": "当前 Attempt Memory writer/reader 闭环缺失", "closure": "commit 后 writer Session 结束，后续不同 SDK Session 同 ID/hash retrieve 并 use"},
        {"id": "G46-007", "severity": "P0", "title": "当前 Attempt 原生 supersedes 指向 runtime_file", "closure": "由修复后代码创建新不可变 Attempt，supersedes 同 task 的 workflow_output"},
        {"id": "G46-008", "severity": "P0", "title": "当前候选包尚无 Registry/authority/浏览器下载闭环", "closure": "平台登记本轮 Manifest/ZIP/receipt，冻结唯一 authority，并由真实前端下载复算"},
        {"id": "G46-009", "severity": "P0", "title": "Worker exactly-once 缺少终态对象级 reconciliation", "closure": "stale writer 拒绝、零重复副作用和 terminal reconciliation 绑定同一业务对象"},
        {"id": "G46-010", "severity": "P0", "title": "独立 Judge ACCEPT 与完成链缺失", "closure": "满足 pre-Judge 后新 Judge ACCEPT，并验证 accepted→gate.passed→converged→completed"},
        {"id": "G46-011", "severity": "P1", "title": "58c0e52 与 b7c338 基线指令冲突尚无权威 checkout 消解", "closure": "以最新 58c0e52 指令为有效门槛，在平台 git.workspace.ready 中记录 target_commit；保留 b7c338 冲突来源，不做平均"},
    ]
    gap_doc = {
        "denominator_id": "E46-GAPS-11-v1", "total": len(gaps),
        "open": len(gaps), "closed": 0,
        "p0_open": sum(1 for item in gaps if item["severity"] == "P0"),
        "p1_open": sum(1 for item in gaps if item["severity"] == "P1"),
        "gaps": gaps,
    }
    dump("cam-matrix.json", cam_doc)
    dump("gap-denominator.json", gap_doc)


def main() -> int:
    if ROOT.name != "delivery":
        raise SystemExit("must run from delivery root")
    media = media_audit()
    control = control_audit()
    cam_and_gaps(control, media)
    print(json.dumps({"media": media["status"], "current_attempt_events": control["current_attempt"]["event_count"], "semantic_supersession_valid": control["semantic_supersession"]["valid_workflow_output_predecessor"]}, ensure_ascii=False))
    return 0 if media["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
