from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from . import NODE_KEY, RUN_ID
from .faults import run_faults
from .gate import REJECT_EXIT, evaluate, remediate
from .platform import EvidenceError, analyze, capture, load_index
from src.run_local_probes import run as run_supplemental_probes


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate_reports(root: Path, index: dict[str, Any], faults: dict[str, Any], supplemental: dict[str, Any], gate_receipt: dict[str, Any]) -> None:
    p = index["snapshot"]["projection"]
    a = index["analysis"]
    route = a["runtime"]["route_events"]
    recovery = a["recovery"]["chain"]
    registry_receipts = a["artifacts"].get("receipts", [])
    route_refs = ", ".join(f"seq {r['sequence']} / `{r['event_id']}`" for r in route)
    recovery_refs = " → ".join(f"{r['sequence']} {r['type']}" for r in recovery)
    memory_refs = ", ".join(f"seq {r['sequence']} / `{r['event_id']}`" for r in a["memory"]["commit_anchors"])
    control_rows = "\n".join(f"| {c['control_id']} | {c['status']} | {c['basis']} |" for c in index["controls"])
    report = f"""# Claude Agent SDK Runtime 取证与故障注入验收报告

**Run：** `{RUN_ID}`  
**节点：** Runtime 取证与故障注入执行环境  
**工程实现者：** 林砚｜后端工程师｜`agent_eac0b56ad320`  
**发起人现场补充意见：** 无；本轮未扩展或缩减验收范围。  
**证据截止：** platform metadata `{index['snapshot']['run_metadata'].get('generated_at')}`；公开投影 sequence `{p['sequence_first']}..{p['sequence_last']}`。

## 一、正式结论【决定】

```text
runtime_probe_engineering_delivery=PASS
platform_projection_integrity=PASS_PUBLIC_AGENT_SAFE_SCOPE
platform_registered_artifact_bytes=PASS_{a['artifacts']['byte_verified_count']}_OF_{a['artifacts']['registry_count']}
local_fault_injection=PASS_LOCAL_SCOPE
predeclared_candidate_v1_gate=REJECT_EXPECTED_EXIT_{gate_receipt['exit_code']}
cam_pass_count={index['acceptance']['pass_count']}_OF_13
claude_agent_sdk_full_runtime_migration=NO_GO
openclaw_retirement=REJECTED
```

本节点交付的是可运行采集器、证据索引、隔离故障探针和失败关闭门禁。工程与本地探针通过，不等于平台全 Runtime 迁移通过。当前冻结投影仍缺五角色全链路、独立 Judge、平台 intentional pause/resume、Memory 同值跨新 Session 读用闭环、终态对账及 OpenClaw 零流量证据。

## 二、事实与平台证据【事实/证据】

### 2.1 投影完整性

- 实际读取：`.jianghu-platform-evidence/events.ndjson`，冻结到 `evidence/runtime_probe/platform_snapshot/events.ndjson`；
- 字节数：`{index['snapshot']['core_files']['events.ndjson']['size_bytes']}`；SHA-256：`{index['snapshot']['core_files']['events.ndjson']['sha256']}`；
- 投影事件：`{p['event_count']}`；metadata event count：`{p['metadata_event_count']}`；sequence `{p['sequence_first']}..{p['sequence_last']}`；过滤缺口：`{p['missing_sequences']}`；
- sequence、event ID、source_event_sha256 均唯一；critical event `{p['critical_count']}` 条逐对象与投影一致；
- 边界：这是 `public_agent_safe` 投影，不是源数据库导出，未读取或注入发起人私享审计内容。

### 2.2 Runtime 与 SDK Session

- Runtime health：`{a['runtime']['health'].get('runtime')}` / `{a['runtime']['health'].get('mode')}`；Bridge `{a['runtime']['health'].get('version')}`；Claude Code `{a['runtime']['health'].get('claude_code_version')}`；
- source attestation：`{a['runtime']['source_attestation_status']}`，源码指纹 `{a['runtime']['source_file_fingerprint_count']}` 项；
- route attestation：{route_refs}；
- completed-turn SDK binding：`{a['runtime']['binding_verified_count']}/{a['runtime']['binding_count']}` 逐 sequence、event ID、source hash、platform Session 与 SDK Session 一致；
- distinct bound actor：`{a['runtime']['distinct_bound_agents']}`；distinct SDK Session：`{a['runtime']['distinct_sdk_sessions']}`；
- 限制：`agent.turn.started` 不携带 SDK Session ID，显式 `sdk.session.started`={a['runtime']['explicit_sdk_session_started_event_count']}、`sdk.session.continued`={a['runtime']['sdk_session_continued_event_count']}。attestation 中 `model` 字段不被解释为模型供应商端到端执行证明。

### 2.3 Tool 请求、结果和副作用

- Tool group：`{a['tools']['group_count']}`；授权/started/completed/side-effect 四阶段完整：`{a['tools']['complete_four_phase_groups']}`；不完整：`{a['tools']['incomplete_group_count']}`；
- completion：`{a['tools']['completion_statuses']}`；authorization：`{a['tools']['authorization_decisions']}`；side effect：`{a['tools']['side_effect_statuses']}`；
- 失败清单：`evidence/runtime_probe/failed-tool-inventory.json`；
- 限制：投影未提供原始 Tool Request/Result 字节、独立参数 Schema 判定、SDK invocation ID、result digest/output SHA-256，因此只能判 `PARTIAL`。

### 2.4 文件与 Artifact Registry

- 文件事件：created `{a['files']['created']}`、modified `{a['files']['modified']}`、deleted `{a['files']['deleted']}`；
- Registry：`{a['artifacts']['registry_count']}` 项，SHA-256 `{a['artifacts']['registry_sha256']}`；
- 原始物化字节、expected/observed SHA-256、大小、source event sequence/id/hash：`{a['artifacts']['byte_verified_count']}/{a['artifacts']['registry_count']}` 全部一致；
- `artifact.collected` / `artifact.download.verified`：`{a['artifacts']['collected_count']}` / `{a['artifacts']['download_verified_count']}`；两份 workflow output 没有同等完整的 collect/download 事件，因此 CAM-04 保持 `PARTIAL`；
- 逐项收据：`evidence/runtime_probe/platform_snapshot/artifact-byte-receipts.json`（共 `{len(registry_receipts)}` 项）。

### 2.5 公开协作、Judge、返工与 Memory

- `agent.message.sent`：`{a['collaboration']['message_count']}` 条，覆盖 `{a['collaboration']['distinct_actor_count']}` 个发送 actor；不足五角色；
- Judge/gate 事件：`{a['judge']['event_count']}`；不得把本地预门禁冒充独立 Judge；
- `attempt.created`：`{a['rework']['attempt_count']}`，其中 `rework_of` 非空 `{a['rework']['linked_attempt_count']}`；存在返工 Attempt 事实，但没有 Judge 因果链；
- Memory candidate/review/commit/persist：`{a['memory']['candidate_count']}/{a['memory']['reviewed_count']}/{a['memory']['committed_count']}/{a['memory']['persisted_count']}`；commit 锚点：{memory_refs or '无'}；
- retrieved/used：`{a['memory']['retrieved_count']}/{a['memory']['used_count']}`；本轮 commit 后同值跨新 Session retrieve/use：`{a['memory']['cross_session_roundtrip_proven']}`。

### 2.6 暂停与恢复

- intentional platform pause/resume 事件：`{a['pause']['event_count']}`；
- 后端中断恢复链：`{recovery_refs}`；
- 缺少 terminal duplicate-effect reconciliation、`run.converged`/`run.completed`，冻结 Run 状态仍为 `{index['snapshot']['run_metadata'].get('status')}`。

## 三、本次真实本地故障注入【事实/边界】

- pause 子进程 PID `{faults['pause']['pause_pid']}`，退出 `{faults['pause']['pause_exit_code']}`；不同恢复 PID `{faults['pause']['resume_pid']}`，退出 `{faults['pause']['resume_exit_code']}`；
- checkpoint SHA-256 `{faults['pause']['checkpoint_sha256']}`；静默窗口 `{faults['pause']['quiet_window_seconds']}` 秒，目录摘要不变=`{faults['pause']['quiet_window_unchanged']}`；旧 worker fenced=`{faults['pause']['old_worker_fenced']}`；
- side-effect 后故障退出 `{faults['failure_recovery']['failure_exit_code']}`，恢复退出 `{faults['failure_recovery']['recovery_exit_code']}`；operation `{faults['failure_recovery']['operation_id']}`；同幂等键副作用次数 `{faults['failure_recovery']['occurrences']}`；重复抑制=`{faults['failure_recovery']['side_effect_duplicate_suppressed']}`；
- 所有本地收据均标记 `evidence_class=observed_local_process`、`acceptance_eligible=false`。这证明本地实现可运行，不证明江湖编排器或 Claude SDK Session 恢复。

### 3.1 公开提交合并后的补充探针

经逐行审查谢临川公开实现后，合并了 SQLite Memory、OS `kill()`、依赖故障恢复及路径逃逸拒绝探针。补充结果：事件 `{supplemental['event_count']}` 条、命令 `{supplemental['commands']}` 条；Memory writer/reader PID `{supplemental['memory']['writer_pid']}/{supplemental['memory']['reader_pid']}`；错误 namespace 退出 `{supplemental['memory']['wrong_namespace_exit']}`；强制终止后副作用计数 `{supplemental['failure_recovery']['effect_count']}` 且重复抑制=`{supplemental['failure_recovery']['duplicate_suppressed']}`；依赖退出/恢复 `{supplemental['dependency']['first_exit']}/{supplemental['dependency']['retry_exit']}`；路径逃逸退出 `{supplemental['file_delivery']['path_escape_exit']}`。补充探针仍为 `acceptance_eligible=false`。

## 四、预声明阻断与首轮候选【决定】

`config/candidate-v1.json` 有意保持 `collector_provenance=null`；`config/predeclared-blocker.json` 在任何裁判结果前固定 `RP-BLOCKER-001`。本地预门禁真实返回：

```text
verdict={gate_receipt['verdict']}
exit_code={gate_receipt['exit_code']}
candidate_sha256={gate_receipt['candidate_sha256']}
```

该阻断可通过创建不可变 V2 修复；`runtime_probe.gate.remediate` 会关联 V1 SHA-256 且不改写 V1。当前未创建正式 `config/candidate-v2.json`、未伪造 platform attempt 或 Judge event，等待后续独立 Judge 真实退回后再返工。补充探针目录中的 V2 只是 `acceptance_eligible=false` 的本地门禁自检，不是正式候选。

## 五、公开工程提交审查与实质分歧【事实/决定】

- 实际读取两份授权 public manifest，并对每一行形成决定：`evidence/runtime_probe/public-submission-review.json`；
- prompt 中列示谢临川 manifest 为 96 文件，但执行时公开 manifest 已有 128 行；本次按实际读取的 manifest SHA-256 和 128 行审查，不把差异静默平均；
- 林砚早期快照：sequence `5336` / events SHA-256 `d7950a97b07fee5e69daab3f413c5c0e1fc61df009d7ee526d7fa7a9bbf5bfdd`；谢临川较晚快照：sequence `5349` / `3228b7cc97d49a88270052acc7a5e51c2099ceb8613a49c92b62f3e78f060325`；两者作为 moving projection 的历史合法截止保留；
- 本报告采用当前重新冻结的 sequence `{p['sequence_last']}` / SHA-256 `{index['snapshot']['core_files']['events.ndjson']['sha256']}` 作为唯一正式判断截止，不平均计数，也不改写历史快照；
- 采用 `runtime_probe` 为主取证实现；合并谢临川的五角色契约、target schema、SQLite/强制终止/依赖/路径边界探针；拒绝用第二套并行 CLI 覆盖主实现；
- 38/38 Artifact 原始字节事实可合并，但 collect/download 未覆盖全部 Artifact，故 CAM-04 继续 `PARTIAL`。

## 六、CAM-00～CAM-12

| Control | 状态 | 证据边界 |
|---|---|---|
{control_rows}

## 七、假设与待解决风险

### 假设

1. 平台后续追加事件可继续由同一采集器冻结；每次结论只适用于对应 SHA-256 截止。
2. 后续节点会由平台实际绑定质量审计者和独立 Judge；本节点不自行代替。

### 待解决风险

1. 五个两两独立 actor/role/platform Session/SDK Session 生产链未形成；
2. Tool 原始请求、结果摘要、Schema/IAM 拒绝与业务副作用因果不完整；
3. 两份 workflow output 的 collect/download 完整链缺失；
4. Judge `REJECT → revision request → new Attempt → V2 → rejudge` 为 0；
5. 本轮 Memory commit 尚无同值跨新 Session retrieve/use；
6. 平台 intentional pause/resume、checkpoint hash、静默窗口和 SDK continuation 缺失；
7. 中断恢复未终态对账；Run 仍在 running；
8. OpenClaw 历史能力等价、全入口零流量、无旁路、无静默回退及退役回滚未证明。
"""
    gaps = {
        "schema_version": "jianghu.runtime-migration-gap-list.v1",
        "run_id": RUN_ID,
        "generated_from_evidence_index_sha256": sha(root / "evidence" / "runtime_probe" / "evidence-index.json"),
        "overall": "NO_GO",
        "items": [
            {"id": c["control_id"], "priority": "P0", "status": "OPEN" if c["status"] == "NOT_PASS" else "PARTIAL", "gap": c["name"], "basis": c["basis"]}
            for c in index["controls"]
        ],
    }
    readme = f"""# Runtime 取证与故障注入执行环境

本项目根目录就是正式 `delivery/`。它只使用 Python 标准库，不读取环境变量或 Provider 凭据。

## 命令

```bash
python run_runtime_probe.py build
python -m unittest discover -s tests -v
python run_runtime_probe.py write-manifest
python run_runtime_probe.py verify
python run_runtime_probe.py gate config/candidate-v1.json  # 预期退出 42
```

`build` 会冻结 `.jianghu-platform-evidence`、按 registry 复算正式 Artifact 原始字节、生成证据索引、执行两个真实本地子进程故障场景，并运行预声明失败关闭门禁。冻结投影：{p['event_count']} events / sequence {p['sequence_first']}..{p['sequence_last']} / SHA-256 `{index['snapshot']['core_files']['events.ndjson']['sha256']}`。

正式结论：本地工程 `PASS`；全 Runtime 迁移 `NO_GO`；OpenClaw 退役 `REJECTED`。
"""
    (root / "docs").mkdir(exist_ok=True)
    gap_rows = "\n".join(
        f"| {item['id']} | {item['priority']} | {item['status']} | {item['gap']} | {item['basis']} |"
        for item in gaps["items"]
    )
    gap_markdown = f"""# Claude Agent SDK Runtime 迁移缺口清单

**Run：** `{RUN_ID}`  
**节点：** `runtime_probe_harness`  
**总体结论：** `NO_GO`  
**证据截止：** sequence `{p['sequence_last']}`；events SHA-256 `{index['snapshot']['core_files']['events.ndjson']['sha256']}`。

本清单由 `evidence/runtime_probe/evidence-index.json` 自动生成。`PARTIAL` 不等于发布通过，本地探针均为 `acceptance_eligible=false`。

| ID | 优先级 | 状态 | 缺口 | 当前证据依据 |
|---|---|---|---|---|
{gap_rows}

## 关闭原则

- 必须使用本次 Run 后续平台事件、SDK Session binding、Artifact Registry 原始字节或独立审计产物关闭；
- 不得用本地子进程事件替代平台 Judge、Memory、暂停或 Worker 恢复事件；
- 五个 distinct actor 计数不能替代产品、架构、工程、质量、独立裁判五个具名角色与独立 Session 的绑定；
- OpenClaw 退役必须补齐全入口、零流量、无旁路、无静默回退、单写者和回滚演练。
"""
    (root / "docs" / "Claude_Runtime_取证与故障注入验收报告.md").write_text(report, encoding="utf-8")
    (root / "docs" / "Claude_Runtime_迁移缺口清单.md").write_text(gap_markdown, encoding="utf-8")
    write_json(root / "gaps" / "runtime-probe-gap-list.json", gaps)
    (root / "README_Runtime_Probe.md").write_text(readme, encoding="utf-8")


def iter_manifest_files(root: Path):
    excludes = {
        "artifacts/sha256_manifest.json",
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in excludes or rel.startswith(".jianghu-platform-evidence/") or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"} or "/test-tmp/" in f"/{rel}/":
            continue
        yield path, rel


def write_manifest(root: Path) -> dict[str, Any]:
    files = [{"path": rel, "size_bytes": path.stat().st_size, "sha256": sha(path)} for path, rel in iter_manifest_files(root)]
    payload = {
        "schema_version": "jianghu.delivery-sha256-manifest.v1",
        "run_id": RUN_ID,
        "node_key": NODE_KEY,
        "exclusions": ["moving .jianghu-platform-evidence/**", "manifest itself", "Python caches", "ephemeral test-tmp"],
        "file_count": len(files),
        "files": files,
    }
    write_json(root / "artifacts" / "sha256_manifest.json", payload)
    return payload


def check_manifest(root: Path) -> dict[str, Any]:
    path = root / "artifacts" / "sha256_manifest.json"
    if not path.is_file():
        raise EvidenceError("manifest missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in payload["files"]}
    actual = {rel: {"path": rel, "size_bytes": p.stat().st_size, "sha256": sha(p)} for p, rel in iter_manifest_files(root)}
    if expected != actual or payload.get("file_count") != len(actual):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])
        raise EvidenceError(f"manifest mismatch missing={missing} extra={extra} changed={changed}")
    return {"status": "PASS", "file_count": len(actual), "manifest_sha256": sha(path)}


def build(root: Path) -> dict[str, Any]:
    index = capture(root)
    faults = run_faults(root)
    supplemental = run_supplemental_probes()
    candidate = root / "config" / "candidate-v1.json"
    blocker = root / "config" / "predeclared-blocker.json"
    gate_receipt = evaluate(candidate, blocker)
    if gate_receipt["exit_code"] != REJECT_EXIT:
        raise EvidenceError("predeclared first-candidate blocker did not reject")
    write_json(root / "evidence" / "runtime_probe" / "candidate-v1-pre-gate-receipt.json", gate_receipt)
    generate_reports(root, index, faults, supplemental, gate_receipt)
    manifest = write_manifest(root)
    return {"index": index, "faults": faults, "supplemental": supplemental, "gate": gate_receipt, "manifest": manifest}


def verify(root: Path) -> dict[str, Any]:
    index = load_index(root)
    snapshot = root / "evidence" / "runtime_probe" / "platform_snapshot"
    recalculated = analyze(snapshot)
    for path in [
        ("snapshot", "projection", "event_count"),
        ("snapshot", "projection", "sequence_last"),
        ("analysis", "runtime", "binding_verified_count"),
        ("analysis", "tools", "group_count"),
        ("analysis", "artifacts", "registry_count"),
        ("acceptance", "pass_count"),
    ]:
        left: Any = index
        right: Any = recalculated
        for key in path:
            left = left[key]
            right = right[key]
        if left != right:
            raise EvidenceError(f"stored index mismatch at {'.'.join(path)}")
    receipts = json.loads((snapshot / "artifact-byte-receipts.json").read_text(encoding="utf-8"))
    if len(receipts) != index["analysis"]["artifacts"]["registry_count"]:
        raise EvidenceError("artifact receipt count mismatch")
    for item in receipts:
        artifact = root / item["snapshot_path"]
        if not artifact.is_file() or sha(artifact) != item["observed_sha256"] or artifact.stat().st_size != item["size_bytes"]:
            raise EvidenceError(f"frozen artifact mismatch: {item['artifact_id']}")
    faults = json.loads((root / "evidence" / "runtime_probe" / "local_faults" / "result.json").read_text(encoding="utf-8"))
    if faults.get("status") != "PASS_LOCAL_SCOPE" or faults.get("acceptance_eligible") is not False:
        raise EvidenceError("local fault result invalid")
    gate_receipt = json.loads((root / "evidence" / "runtime_probe" / "candidate-v1-pre-gate-receipt.json").read_text(encoding="utf-8"))
    if gate_receipt.get("exit_code") != REJECT_EXIT or gate_receipt.get("acceptance_eligible") is not False:
        raise EvidenceError("pre-gate rejection receipt invalid")
    supplemental = json.loads((root / "evidence" / "local-probes" / "local-probe-proof.json").read_text(encoding="utf-8"))
    if supplemental.get("status") != "PASS_LOCAL_SCOPE" or supplemental.get("acceptance_eligible") is not False:
        raise EvidenceError("supplemental public probe result invalid")
    if supplemental.get("negative_gate", {}).get("platform_judge_event") is not False:
        raise EvidenceError("supplemental local gate was mislabeled as platform Judge")
    for path in [root / "docs" / "Claude_Runtime_取证与故障注入验收报告.md", root / "docs" / "Claude_Runtime_迁移缺口清单.md", root / "gaps" / "runtime-probe-gap-list.json", root / "README_Runtime_Probe.md"]:
        if not path.is_file() or not path.read_bytes():
            raise EvidenceError(f"required delivery missing: {path.name}")
    manifest = check_manifest(root)
    return {
        "status": "PASS_ENGINEERING_NO_GO_MIGRATION",
        "events": index["snapshot"]["projection"]["event_count"],
        "sequence_last": index["snapshot"]["projection"]["sequence_last"],
        "sdk_bindings": index["analysis"]["runtime"]["binding_verified_count"],
        "tool_groups": index["analysis"]["tools"]["group_count"],
        "artifacts": index["analysis"]["artifacts"]["registry_count"],
        "cam_pass": index["acceptance"]["pass_count"],
        "migration": "NO_GO",
        "openclaw_retirement": "REJECTED",
        "manifest": manifest,
    }

__all__ = ["build", "verify", "write_manifest", "check_manifest", "evaluate", "remediate"]
