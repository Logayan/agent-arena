from __future__ import annotations

import asyncio
from collections import defaultdict

from .models import Agent, Run, RunEvent, RunSnapshot, new_id


AGENT_DEFINITIONS = [
    ("流程协调", "负责阶段推进、预算与质量门禁", "协", "neutral"),
    ("需求分析", "提炼需求、证据、假设与开放问题", "需", "analysis"),
    ("产品方案", "设计用户流程、业务规则与验收条件", "产", "proposal"),
    ("技术方案", "设计架构、接口、安全与交付计划", "技", "proposal"),
    ("红队攻击", "寻找反例、风险、矛盾与不可交付路径", "红", "attack"),
    ("修订处理", "处置有效缺陷并维护产物版本", "修", "revision"),
    ("裁判报告", "独立评分、裁决并形成最终报告", "裁", "judge"),
]


class RunStore:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.events: dict[str, list[RunEvent]] = defaultdict(list)
        self.conditions: dict[str, asyncio.Condition] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def create_demo_run(self) -> Run:
        agents = [
            Agent(
                id=new_id("agent"),
                name=name,
                role=role,
                short_name=short_name,
                tone=tone,
            )
            for name, role, short_name, tone in AGENT_DEFINITIONS
        ]
        run = Run(
            project_name="智能需求评审示例",
            title="企业知识助手需求评审与方案攻防",
            agents=agents,
        )
        self.runs[run.id] = run
        self.conditions[run.id] = asyncio.Condition()
        self.append_event(
            run.id,
            RunEvent(
                run_id=run.id,
                type="run.created",
                category="system",
                title="演示运行已创建",
                summary="已装载 7 类 Agent 和产品需求评审生产流。",
            ),
        )
        return run

    def get_run(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def get_or_create_demo(self) -> Run:
        if self.runs:
            latest_run_id = next(reversed(self.runs))
            return self.runs[latest_run_id]
        return self.create_demo_run()

    def snapshot(self, run_id: str) -> RunSnapshot | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return RunSnapshot(run=run, events=self.events[run_id])

    def append_event(self, run_id: str, event: RunEvent) -> RunEvent:
        event.sequence = len(self.events[run_id]) + 1
        self.events[run_id].append(event)
        run = self.runs[run_id]
        run.updated_at = event.created_at
        condition = self.conditions.get(run_id)
        if condition:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._notify(condition))
            except RuntimeError:
                pass
        return event

    async def _notify(self, condition: asyncio.Condition) -> None:
        async with condition:
            condition.notify_all()

    async def wait_for_events(
        self, run_id: str, after_sequence: int, timeout: float = 15
    ) -> list[RunEvent]:
        current = self.events[run_id]
        if len(current) > after_sequence:
            return current[after_sequence:]
        condition = self.conditions[run_id]
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout)
        except TimeoutError:
            return []
        return self.events[run_id][after_sequence:]


store = RunStore()
