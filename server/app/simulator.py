from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .models import (
    AgentStatus,
    Defect,
    RunEvent,
    RunStatus,
    ScoreDimension,
)
from .store import RunStore


@dataclass(frozen=True)
class SimulationStep:
    status: RunStatus
    stage: int
    stage_label: str
    progress: int
    agent_index: int
    event_type: str
    category: str
    title: str
    summary: str
    task: str
    severity: str = "info"


STEPS = [
    SimulationStep(
        RunStatus.PREPARING,
        1,
        "资料与目标",
        8,
        0,
        "run.state_changed",
        "system",
        "生产流启动",
        "协调 Agent 正在检查输入、角色与预算配置。",
        "校验运行前置条件",
    ),
    SimulationStep(
        RunStatus.ANALYZING,
        2,
        "知识与角色",
        20,
        1,
        "artifact.submitted",
        "collaboration",
        "需求基线 v1 已提交",
        "识别 4 类目标用户、12 项需求、5 个约束和 3 个高影响假设。",
        "构建结构化需求基线",
    ),
    SimulationStep(
        RunStatus.DESIGNING,
        3,
        "协作与对抗",
        34,
        2,
        "agent.message_sent",
        "collaboration",
        "产品方案提出分层知识权限",
        "产品 Agent 建议将空间、知识库和文档权限分离，并请求技术 Agent 评估。",
        "设计产品流程与业务规则",
    ),
    SimulationStep(
        RunStatus.DESIGNING,
        3,
        "协作与对抗",
        46,
        3,
        "artifact.submitted",
        "collaboration",
        "技术方案 v1 已提交",
        "技术 Agent 完成检索服务、权限边界、审计事件和分阶段交付方案。",
        "设计系统架构与接口",
    ),
    SimulationStep(
        RunStatus.ATTACKING,
        3,
        "协作与对抗",
        58,
        4,
        "defect.proposed",
        "attack",
        "发现跨空间引用授权缺口",
        "共享回答中的引用链接可能暴露用户无权查看的源文档，严重度为 high。",
        "攻击权限与引用设计",
        "high",
    ),
    SimulationStep(
        RunStatus.REVISING,
        3,
        "协作与对抗",
        70,
        5,
        "revision.submitted",
        "revision",
        "权限缺陷修订已提交",
        "引用生成前增加资源级授权过滤，无法访问的来源仅显示脱敏摘要。",
        "修订已接受缺陷",
    ),
    SimulationStep(
        RunStatus.VERIFYING,
        3,
        "协作与对抗",
        80,
        4,
        "defect.status_changed",
        "attack",
        "红队复测通过",
        "跨空间引用测试已阻断，缺陷状态从 accepted 更新为 fixed。",
        "复测修订结果",
    ),
    SimulationStep(
        RunStatus.JUDGING,
        4,
        "结果与终审",
        91,
        6,
        "gate.completed",
        "gate",
        "终审评分完成",
        "总分 86，所有维度均超过 60，且不存在未处置的阻断缺陷。",
        "执行终审与报告生成",
    ),
    SimulationStep(
        RunStatus.COMPLETED,
        5,
        "深度交互",
        100,
        6,
        "run.state_changed",
        "gate",
        "运行通过并开放访谈",
        "最终报告、证据附录和 Agent 访谈工作台已就绪。",
        "等待用户深度交互",
    ),
]


async def run_demo(store: RunStore, run_id: str, delay: float = 0.75) -> None:
    run = store.get_run(run_id)
    if not run:
        return

    for agent in run.agents:
        agent.status = AgentStatus.IDLE
        agent.current_task = None
        agent.progress = 0

    for step in STEPS:
        if run.status == RunStatus.CANCELLED:
            return
        await asyncio.sleep(delay)

        for agent in run.agents:
            if agent.status == AgentStatus.WORKING:
                agent.status = AgentStatus.COMPLETED
                agent.progress = 100

        active_agent = run.agents[step.agent_index]
        active_agent.status = (
            AgentStatus.COMPLETED
            if step.status == RunStatus.COMPLETED
            else AgentStatus.WORKING
        )
        active_agent.current_task = step.task
        active_agent.progress = step.progress

        run.status = step.status
        run.stage = step.stage
        run.stage_label = step.stage_label
        run.progress = step.progress
        run.token_count += 1450 + step.progress * 3
        run.estimated_cost = round(run.token_count * 0.0000024, 2)

        if step.event_type == "defect.proposed" and not run.defects:
            run.defects.append(
                Defect(
                    title="跨空间引用缺少资源级授权",
                    category="security",
                    severity="high",
                    status="proposed",
                    owner="红队攻击",
                )
            )
        elif step.event_type == "revision.submitted" and run.defects:
            run.defects[0].status = "accepted"
            run.defects[0].owner = "修订处理"
        elif step.event_type == "defect.status_changed" and run.defects:
            run.defects[0].status = "fixed"
            run.defects[0].owner = "红队攻击"
        elif step.status == RunStatus.JUDGING:
            run.scores = [
                ScoreDimension(name="需求完整性", score=88, weight=20),
                ScoreDimension(name="用户价值", score=84, weight=15),
                ScoreDimension(name="方案可行性", score=87, weight=20),
                ScoreDimension(name="风险与安全", score=82, weight=15),
                ScoreDimension(name="证据追溯", score=86, weight=15),
                ScoreDimension(name="可交付性", score=85, weight=15),
            ]
            run.total_score = 86

        store.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                type=step.event_type,
                category=step.category,
                title=step.title,
                summary=step.summary,
                agent_id=active_agent.id,
                severity=step.severity,
            ),
        )

    for agent in run.agents:
        agent.status = AgentStatus.COMPLETED
        agent.progress = 100
