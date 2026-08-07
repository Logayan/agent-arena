from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.platform_executor import execute_platform_run
from server.app.platform_store import PlatformStore, platform_store


async def main() -> None:
    verification_root = Path(".data/verification").resolve()
    verification_root.mkdir(parents=True, exist_ok=True)
    db_path = verification_root / f"real-openclaw-e2e-{uuid4().hex[:10]}.db"
    store = PlatformStore(str(db_path))

    active = platform_store.get_active_model_config(include_secret=True)
    if not active:
        raise RuntimeError("active_model_config_missing")
    store.save_model_config(
        config_id=None,
        name="真实验收模型",
        provider=active["provider"],
        base_url=active["base_url"],
        model=active["model"],
        token=active["token"],
        active=True,
    )

    proposer = store.create_agent(
        name="叶知秋",
        role="方案提案人",
        description="负责形成不超过 120 字的可核验结论",
        persona="表达极简，只保留结论、证据与风险，并按退回意见修订。",
        capabilities=["方案设计", "证据整理"],
        skills=[
            {
                "key": "evidence_delivery",
                "name": "证据化交付",
                "description": "形成可核验交付",
                "instructions": "总输出不超过 120 字，明确列出结论、证据和风险。",
                "enabled": True,
            }
        ],
    )
    challenger = store.create_agent(
        name="商清言",
        role="方案质疑人",
        description="负责用一句话发现不可验证之处",
        persona="保持独立判断，贡献与公开消息都必须简短。",
        capabilities=["风险质疑", "可验证性审查"],
        skills=[
            {
                "key": "challenge",
                "name": "结构化质疑",
                "description": "指出证据缺口",
                "instructions": "质疑不超过 60 字，必须指向具体内容。",
                "enabled": True,
            }
        ],
    )
    judge = store.create_agent(
        name="闻止衡",
        role="独立裁判",
        description="不参与创作，只依据契约裁决",
        persona="使用独立身份、独立上下文和独立 Prompt，不因团队共识而放宽标准。",
        capabilities=["独立验收", "证据核验"],
    )
    team = store.create_team(
        organization_id="org_jianghu",
        name="真实闭环验收小组",
        purpose="验证隔离协作、公开通信、正式产物与裁判返工闭环",
        operating_mode="debate",
        members=[
            {
                "agent_id": proposer["id"],
                "member_role": "leader",
                "responsibility": "主持合议与正式提交",
            },
            {
                "agent_id": challenger["id"],
                "member_role": "challenger",
                "responsibility": "独立质疑证据缺口",
            },
        ],
    )
    workflow = store.create_workflow(
        "OpenClaw真实多人物闭环验收流",
        "两位人物独立贡献、公开通信与合议，独立裁判不通过则自动返工。",
        "real_acceptance",
        {
            "nodes": [
                {
                    "key": "proposal",
                    "name": "协作形成验收提案",
                    "type": "team_task",
                    "purpose": "正式产物不超过 160 字，包含事实、分歧、证据、风险。首轮严禁出现复核码 JH-PASS-2；收到退回意见后必须加入复核码 JH-PASS-2。",
                    "agent_id": proposer["id"],
                    "agent_role": proposer["role"],
                    "team_id": team["id"],
                    "participant_agent_ids": [proposer["id"], challenger["id"]],
                    "communication_rounds": 1,
                },
                {
                    "key": "judge",
                    "name": "独立裁决",
                    "type": "judge",
                    "purpose": "候选含复核码 JH-PASS-2 且含证据、风险时 pass；否则 revise 并打回 proposal。JSON 各文本字段不超过 40 字。",
                    "agent_id": judge["id"],
                    "agent_role": judge["role"],
                },
            ],
            "edges": [["proposal", "judge"]],
            "policies": {
                "max_parallel_agents": 3,
                "max_debate_rounds": 1,
                "max_revision_rounds": 2,
                "max_run_minutes": 60,
                "max_total_tokens": 400_000,
            },
        },
    )
    run = store.create_run(
        workflow["id"],
        "用极简文本验证真实多 Agent 闭环。首轮不得出现 JH-PASS-2，裁判应退回；返工后加入 JH-PASS-2，再裁决通过。正式产物必须有事实、分歧、证据、风险，总计不超过 160 字。",
    )
    print(
        {
            "phase": "started",
            "db": str(db_path),
            "run_id": run["id"],
            "workflow_id": workflow["id"],
            "agents": 3,
        },
        flush=True,
    )

    await execute_platform_run(store, run["id"])
    result = store.get_run(run["id"])
    if not result:
        raise RuntimeError("verification_run_not_found")
    event_counts: dict[str, int] = {}
    for event in result["events"]:
        event_counts[event["type"]] = event_counts.get(event["type"], 0) + 1
    artifact_versions: dict[str, list[dict[str, object]]] = {}
    for artifact in result["artifacts"]:
        task = next(item for item in result["tasks"] if item["id"] == artifact["task_id"])
        artifact_versions.setdefault(task["node_key"], []).append(
            {
                "version": artifact["version"],
                "status": artifact["status"],
                "path": artifact["relative_path"],
            }
        )
    summary = {
        "phase": "completed",
        "run_id": result["id"],
        "status": result["status"],
        "progress": result["progress"],
        "token_count": result["token_count"],
        "artifact_count": len(result["artifacts"]),
        "event_counts": {
            key: event_counts.get(key, 0)
            for key in [
                "openclaw.turn.started",
                "openclaw.turn.completed",
                "team.member.completed",
                "agent.message.sent",
                "team.synthesis.completed",
                "gate.rejected",
                "workflow.loop.created",
                "gate.passed",
                "agent.memory.persisted",
                "run.completed",
                "run.failed",
            ]
        },
        "artifact_versions": artifact_versions,
        "workspace": result["workspace"]["root"],
    }
    print(summary, flush=True)
    if result["status"] != "completed":
        raise RuntimeError(f"real_e2e_failed:{result['status']}")
    if event_counts.get("team.member.completed", 0) < 2:
        raise RuntimeError("real_multi_agent_contributions_missing")
    if event_counts.get("agent.message.sent", 0) < 2:
        raise RuntimeError("real_agent_communication_missing")
    if event_counts.get("gate.rejected", 0) < 1 or event_counts.get("workflow.loop.created", 0) < 1:
        raise RuntimeError("real_revision_loop_missing")
    if event_counts.get("gate.passed", 0) < 1:
        raise RuntimeError("real_judge_pass_missing")


if __name__ == "__main__":
    asyncio.run(main())
