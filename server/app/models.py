from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class RunStatus(StrEnum):
    DRAFT = "draft"
    PREPARING = "preparing"
    ANALYZING = "analyzing"
    DESIGNING = "designing"
    ATTACKING = "attacking"
    REVISING = "revising"
    VERIFYING = "verifying"
    JUDGING = "judging"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    COMPLETED = "completed"


class Agent(BaseModel):
    id: str
    name: str
    role: str
    short_name: str
    status: AgentStatus = AgentStatus.IDLE
    current_task: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    tone: str = "neutral"


class RunEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    sequence: int = 0
    run_id: str
    type: str
    category: str
    title: str
    summary: str
    agent_id: str | None = None
    severity: str = "info"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class Defect(BaseModel):
    id: str = Field(default_factory=lambda: new_id("defect"))
    title: str
    category: str
    severity: str
    status: str
    owner: str


class ScoreDimension(BaseModel):
    name: str
    score: int
    weight: int


class Run(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    project_name: str
    title: str
    status: RunStatus = RunStatus.DRAFT
    stage: int = 1
    stage_label: str = "资料与目标"
    progress: int = 0
    agents: list[Agent] = Field(default_factory=list)
    defects: list[Defect] = Field(default_factory=list)
    scores: list[ScoreDimension] = Field(default_factory=list)
    total_score: int | None = None
    estimated_cost: float = 0
    token_count: int = 0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class RunSnapshot(BaseModel):
    run: Run
    events: list[RunEvent]
