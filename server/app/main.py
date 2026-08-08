from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .platform_store import platform_store
from .llm_client import LLMConfigurationError, LLMRequestError, client_for_config, configured_llm
from .platform_executor import execute_platform_run
from .openclaw_runtime import OpenClawRuntimeError, openclaw_runtime
from .secret_store import SecretStorageError
from .showcase import CASE_ID, CASE_TASK, comparison_report, ensure_showcase_assets, showcase_snapshot


class WorkflowBuildRequest(BaseModel):
    requirement: str = Field(min_length=10)
    name: str | None = None


class RunCreateRequest(BaseModel):
    workflow_id: str
    task: str = Field(min_length=1)
    project_id: str = "project_jianghu"
    clarification_id: str | None = None
    commission_id: str | None = None


class ClarificationCreateRequest(BaseModel):
    workflow_id: str
    requirement: str = Field(min_length=1)


class ClarificationFinalizeRequest(BaseModel):
    answers: list[dict[str, str]] = Field(min_length=1)


class ModelConfigRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    provider: str = "anthropic-compatible"
    base_url: str = Field(min_length=8)
    model: str = Field(min_length=1)
    token: str | None = None
    active: bool = True


class ModelConnectionTestRequest(BaseModel):
    id: str | None = None
    base_url: str | None = None
    model: str | None = None
    token: str | None = None


class KnowledgeSourceRequest(BaseModel):
    project_id: str = "project_jianghu"
    name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    uri: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class TeamKnowledgeUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    media_type: str = "application/octet-stream"
    project_id: str = "project_jianghu"
    relative_path: str = ""
    collection_id: str = ""


class KnowledgeFolderFile(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    relative_path: str = Field(min_length=1, max_length=2_000)
    content_base64: str = Field(min_length=1)
    media_type: str = "application/octet-stream"


class KnowledgeFolderUploadRequest(BaseModel):
    folder_name: str = Field(min_length=1, max_length=255)
    files: list[KnowledgeFolderFile] = Field(min_length=1, max_length=500)
    project_id: str = "project_jianghu"
    collection_id: str | None = Field(default=None, min_length=1, max_length=100)


class TeamKnowledgeNoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=200_000)
    project_id: str = "project_jianghu"


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    description: str = ""
    persona: str = ""
    capabilities: list[str] = Field(default_factory=list)
    visibility: str = "private"
    skills: list[dict[str, object]] = Field(default_factory=list)
    runtime: str = "openclaw"
    memory_policy: dict[str, object] = Field(default_factory=lambda: {"enabled": True, "max_prompt_items": 8, "write_after_task": True})


class AgentRevisionRequest(AgentCreateRequest):
    # Omitted means "keep existing grants"; an explicit empty list revokes all.
    knowledge_source_ids: list[str] | None = None


class AgentMemoryRequest(BaseModel):
    kind: str = "user_note"
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=200_000)
    visibility: str = "private"


class AgentGenerateRequest(BaseModel):
    requirement: str = Field(min_length=1)
    organization_id: str = "org_jianghu"
    preferred_role: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class TeamMemberRequest(BaseModel):
    agent_id: str
    member_role: str = "member"
    responsibility: str = ""


class TeamCreateRequest(BaseModel):
    organization_id: str = "org_jianghu"
    name: str = Field(min_length=1)
    purpose: str = ""
    operating_mode: str = "collaborative"
    members: list[TeamMemberRequest] = Field(min_length=1)
    visibility: str = "private"
    knowledge_paths: list[str] = Field(default_factory=list)


class CommissionAssessRequest(BaseModel):
    organization_id: str = "org_jianghu"
    title: str | None = None
    description: str | None = None
    commission_id: str | None = None


class CommissionTeamResolveRequest(BaseModel):
    force_create: bool = False


class TeamProposalConfirmRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    purpose: str | None = Field(default=None, max_length=2_000)
    operating_mode: str | None = Field(default=None, pattern="^(collaborative|debate|red_team|hierarchical)$")
    members: list[TeamMemberRequest] | None = None


class TeamWorkflowGenerateRequest(BaseModel):
    company_task_id: str
    team_ids: list[str] = Field(min_length=1)


class WorkflowRevisionRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    definition: dict[str, object]


class RunInterventionRequest(BaseModel):
    kind: str = Field(pattern="^(supplement|correction|question|require_rework)$")
    content: str = Field(min_length=1, max_length=100_000)
    task_id: str | None = None
    agent_id: str | None = None


class RunRetryRequest(BaseModel):
    from_task_id: str | None = None


platform_tasks: dict[str, asyncio.Task[None]] = {}


def schedule_platform_execution(run_id: str) -> asyncio.Task[None]:
    active = platform_tasks.get(run_id)
    if active and not active.done():
        return active
    task = asyncio.create_task(execute_platform_run(platform_store, run_id))
    platform_tasks[run_id] = task

    def forget_finished(finished: asyncio.Task[None]) -> None:
        if platform_tasks.get(run_id) is finished:
            platform_tasks.pop(run_id, None)

    task.add_done_callback(forget_finished)
    return task


async def recover_durable_platform_runs() -> None:
    for run in platform_store.list_runs_by_status({"pause_requested"}):
        platform_store.update_run(str(run["id"]), status="paused", stage="paused")
        platform_store.append_run_event(
            str(run["id"]),
            "run.paused",
            "intervention",
            "江湖现场在服务恢复后保持停手",
            "服务中断前已经收到暂停要求；平台不会自行恢复行动，等待发起人明确继续。",
            {"source": "startup_recovery"},
        )
    for run in platform_store.list_runs_by_status({"running"}):
        schedule_platform_execution(str(run["id"]))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await recover_durable_platform_runs()
    yield


app = FastAPI(
    title="Agent Arena API",
    description="多智能体协作、攻防、裁决与复盘平台 API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def prepare_openclaw_run(run: dict[str, object]) -> dict[str, object]:
    health = openclaw_runtime.health()
    if not health.get("available"):
        raise HTTPException(status_code=503, detail=f"OpenClaw Runtime 不可用：{health.get('error') or '健康检查失败'}")
    try:
        model_config = platform_store.get_active_model_config(include_secret=True)
    except SecretStorageError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(LLMConfigurationError(str(exc)))) from exc
    if not model_config:
        raise HTTPException(status_code=503, detail="尚未配置可供 OpenClaw 使用的真实模型与凭据。")
    workflow = platform_store.get_workflow(str(run["workflow_id"]))
    runtime_agents: dict[str, dict[str, object]] = {}
    for node in (workflow or {}).get("definition", {}).get("nodes", []):
        agent = platform_store.get_agent(str(node.get("agent_id") or ""))
        if agent:
            runtime_agents[str(agent["id"])] = agent
        if node.get("team_id"):
            team = platform_store.get_team(str(node["team_id"]))
            for member in (team or {}).get("members", []):
                runtime_agents[str(member["id"])] = member
    try:
        memories = {agent_id: platform_store.list_agent_memories(agent_id, 30) for agent_id in runtime_agents}
        return openclaw_runtime.sync(list(runtime_agents.values()), memories, model_config)
    except (OpenClawRuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"OpenClaw 运行快照准备失败：{exc}") from exc


def contains_chinese(value: object) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(value))


def capability_overlap_ratio(requested: set[str], available: set[str]) -> float:
    if not requested:
        return 1.0
    matched = sum(
        1
        for needed in requested
        if any(needed == owned or needed in owned or owned in needed for owned in available)
    )
    return matched / len(requested)


def bounded_score(value: object, default: int = 0) -> int:
    try:
        score = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        matched = re.search(r"-?\d{1,3}", str(value or ""))
        score = int(matched.group(0)) if matched else default
    return max(0, min(100, score))


def public_llm_error(exc: Exception) -> str:
    message = str(exc)
    if "model_token_cannot_be_decrypted" in message or "legacy_model_token_cannot_be_decrypted" in message:
        return "已保存的模型 Token 无法在当前服务进程中解密。请在“模型与凭据”中重新填写并保存 Token，然后重试；委托、团队和生产流数据均未丢失。"
    if "Insufficient balance" in message or "no resource package" in message:
        return "LLM 服务额度不足，本次操作未执行，也没有创建正式 Run。请补充模型额度或更换可用模型配置。"
    if "network failure" in message or "connection attempts failed" in message:
        return "LLM 服务当前无法连接，本次操作未执行，也没有创建正式 Run。请检查模型服务地址和网络状态。"
    if "HTTP 401" in message or "HTTP 403" in message:
        return "模型服务拒绝了当前凭据，请在“模型与凭据”中更新 Token 后重新测试。"
    if "HTTP 429" in message:
        return "模型服务当前请求过多或额度受限，请稍后重试。"
    if "model_not_found" in message or "无可用渠道" in message:
        return "当前模型在该服务中没有可用渠道，请检查模型 ID。"
    if "endpoint not supported" in message:
        return "当前模型服务不支持所选协议，请检查协议类型。"
    if "non-JSON" in message or "JSON output" in message or "no content blocks" in message:
        return "模型已响应，但输出不符合平台要求的结构化 JSON；本次操作未保存，请重试。"
    if "response stream ended" in message:
        return "模型流式响应未完整结束，本次操作未保存，请重试。"
    if isinstance(exc, LLMConfigurationError):
        return "LLM 尚未正确配置，本次操作未执行。"
    return "LLM 调用失败，本次操作未执行。请检查模型配置和服务状态。"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/platform/overview")
async def platform_overview() -> dict[str, object]:
    return {
        "name": "Jianghu Online",
        "storage": "sqlite-local",
        "agents": len(platform_store.list_agents()),
        "teams": len(platform_store.list_teams()),
        "organizations": len(platform_store.list_organizations()),
        "workflows": len(platform_store.list_workflows()),
        "runs": len(platform_store.list_runs()),
        "knowledge_sources": len(platform_store.list_knowledge_sources()),
    }


@app.get("/api/platform/projects")
async def list_platform_projects() -> list[dict[str, object]]:
    return platform_store.list_projects()


@app.get("/api/platform/organizations")
async def list_platform_organizations() -> list[dict[str, object]]:
    return platform_store.list_organizations()


@app.get("/api/platform/runs")
async def list_platform_runs() -> list[dict[str, object]]:
    return platform_store.list_runs()


@app.get("/api/platform/showcases/production-flow-comparison")
async def get_production_flow_showcase() -> dict[str, object]:
    return showcase_snapshot(platform_store)


@app.post("/api/platform/showcases/production-flow-comparison/install")
async def install_production_flow_showcase() -> dict[str, object]:
    return showcase_snapshot(platform_store, install=True)


@app.post("/api/platform/showcases/production-flow-comparison/comparisons")
async def create_production_flow_comparison() -> dict[str, object]:
    assets = ensure_showcase_assets(platform_store)
    baseline_run = platform_store.create_run(
        str(assets["workflows"]["baseline"]["id"]),
        CASE_TASK,
        "project_jianghu",
    )
    multi_run = platform_store.create_run(
        str(assets["workflows"]["multi_agent"]["id"]),
        CASE_TASK,
        "project_jianghu",
    )
    comparison = platform_store.create_showcase_comparison(
        case_id=CASE_ID,
        baseline_run_id=str(baseline_run["id"]),
        multi_run_id=str(multi_run["id"]),
    )
    return {
        "comparison": comparison_report(platform_store, comparison),
        "message": "两套冻结生产流和独立 Run 已建立，尚未调用模型；确认启动后才会产生真实费用。",
    }


@app.get("/api/platform/showcases/production-flow-comparison/comparisons/{comparison_id}")
async def get_production_flow_comparison(comparison_id: str) -> dict[str, object]:
    comparison = platform_store.get_showcase_comparison(comparison_id)
    if not comparison or comparison.get("case_id") != CASE_ID:
        raise HTTPException(status_code=404, detail="showcase_comparison_not_found")
    return {"comparison": comparison_report(platform_store, comparison)}


@app.post("/api/platform/showcases/production-flow-comparison/comparisons/{comparison_id}/start")
async def start_production_flow_comparison(comparison_id: str) -> dict[str, object]:
    comparison = platform_store.get_showcase_comparison(comparison_id)
    if not comparison or comparison.get("case_id") != CASE_ID:
        raise HTTPException(status_code=404, detail="showcase_comparison_not_found")
    runs = [
        platform_store.get_run(str(comparison["baseline_run_id"])),
        platform_store.get_run(str(comparison["multi_run_id"])),
    ]
    if any(run is None for run in runs):
        raise HTTPException(status_code=404, detail="showcase_run_not_found")
    invalid = [run for run in runs if run and run.get("status") not in {"draft", "running"}]
    if invalid:
        return {
            "comparison": comparison_report(platform_store, comparison),
            "message": "本轮对照已有 Run 进入终态；如需再次比较，请创建新一轮，不会覆盖历史证据。",
        }
    draft_runs = [run for run in runs if run and run.get("status") == "draft"]
    # 两边均完成运行时准备后再启动，避免只启动一边导致不公平对照。
    for run in draft_runs:
        prepare_openclaw_run(run)
    for run in draft_runs:
        schedule_platform_execution(str(run["id"]))
    return {
        "comparison": comparison_report(platform_store, comparison),
        "execution": {"mode": "real-openclaw", "started_run_ids": [run["id"] for run in draft_runs]},
        "message": "单 Agent 基线与多 Agent 协作/对抗 Run 已使用真实 OpenClaw 和真实模型启动。",
    }


@app.get("/api/platform/agents")
async def list_platform_agents() -> list[dict[str, object]]:
    return platform_store.list_agents()


@app.post("/api/platform/agents")
async def create_platform_agent(request: AgentCreateRequest) -> dict[str, object]:
    if not contains_chinese(request.name) or not contains_chinese(request.role):
        raise HTTPException(status_code=422, detail="江湖人物的姓名和职业身份必须使用中文。")
    if any(not contains_chinese(capability) for capability in request.capabilities):
        raise HTTPException(status_code=422, detail="江湖人物的能力标签必须使用中文描述。")
    if request.runtime != "openclaw":
        raise HTTPException(status_code=422, detail="当前正式 Agent Runtime 固定为 OpenClaw，不允许以普通 LLM 封装冒充 Agent。")
    return {"agent": platform_store.create_agent(**request.model_dump())}


@app.put("/api/platform/agents/{agent_id}")
async def revise_platform_agent(agent_id: str, request: AgentRevisionRequest) -> dict[str, object]:
    if not contains_chinese(request.name) or not contains_chinese(request.role):
        raise HTTPException(status_code=422, detail="江湖人物的姓名和职业身份必须使用中文。")
    if any(not contains_chinese(capability) for capability in request.capabilities):
        raise HTTPException(status_code=422, detail="江湖人物的能力标签必须使用中文描述。")
    if request.runtime != "openclaw":
        raise HTTPException(status_code=422, detail="当前正式 Agent Runtime 固定为 OpenClaw。")
    try:
        agent = platform_store.revise_agent(agent_id, **request.model_dump())
    except ValueError as exc:
        status = 404 if str(exc) in {"agent_not_found", "knowledge_source_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"agent": agent, "revision": {"mode": "new_version", "parent_agent_id": agent_id}}


@app.get("/api/platform/agents/{agent_id}/versions")
async def list_platform_agent_versions(agent_id: str) -> list[dict[str, object]]:
    try:
        return platform_store.list_agent_versions(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/platform/agents/{agent_id}/memories")
async def list_platform_agent_memories(agent_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, object]]:
    try:
        return platform_store.list_agent_memories(agent_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/platform/agents/{agent_id}/memories")
async def add_platform_agent_memory(agent_id: str, request: AgentMemoryRequest) -> dict[str, object]:
    try:
        memory = platform_store.add_agent_memory(agent_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"memory": memory}


@app.post("/api/platform/agents/generate")
async def generate_platform_agent(request: AgentGenerateRequest) -> dict[str, object]:
    existing = platform_store.list_agents()
    if request.preferred_role:
        requested = {item.strip() for item in request.required_capabilities if item.strip()}
        for existing_agent in existing:
            if str(existing_agent.get("role", "")).strip() != request.preferred_role.strip():
                continue
            available = {str(item).strip() for item in existing_agent.get("capabilities", []) if str(item).strip()}
            overlap_ratio = capability_overlap_ratio(requested, available)
            if overlap_ratio >= 0.4:
                return {
                    "agent": existing_agent,
                    "generation": {"mode": "reused", "model": configured_llm().model, "reason": "人物册已有同职业且能力匹配的人物"},
                }
    prompt = json.dumps(
        {
            "organization": request.organization_id,
            "agent_requirement": request.requirement,
            "existing_agents": [{"name": item["name"], "role": item["role"], "capabilities": item["capabilities"]} for item in existing],
            "output_schema": {
                "name": "a natural personal name or stable human social identity, never a task/process name",
                "role": "the person's profession or social role, such as 安全审计师、调解员、建筑师",
                "description": "what this person contributes and is accountable for",
                "persona": "background, temperament, values, professional stance, collaboration and conflict behavior",
                "capabilities": ["human-readable professional skill, use the user's language rather than machine keys"],
                "skills": [{"name": "可装载技能名称", "description": "何时使用", "instructions": "执行规范", "enabled": True}],
            },
        },
        ensure_ascii=False,
    )
    system = (
        "You design one reusable personified Agent Blueprint for a Chinese social world called a Jianghu. Return JSON only. "
        "All user-visible fields MUST be natural Chinese: name, role, description, persona and every capability label. "
        "English technical proper nouns may appear only inside an otherwise Chinese phrase. Never output an English role or snake_case capability. "
        "Do not duplicate an existing agent unless the requested capability boundary is materially different. "
        "The Agent must be a believable person, not a tool, workflow step, department, checklist or capability label. "
        "Give the person a natural name or stable human social identity and put work such as red-line checking, risk review, analysis or testing "
        "only in role, responsibility and capabilities. Define background, temperament, values, independent stance, collaboration style, "
        "challenge behavior and concrete capabilities. Capability labels must be natural, human-readable professional skills rather than snake_case keys."
    )
    try:
        generated = await configured_llm().json_message(prompt, system=system, max_tokens=2200)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc
    capabilities = generated.get("capabilities") if isinstance(generated.get("capabilities"), list) else []
    skills = generated.get("skills") if isinstance(generated.get("skills"), list) else []
    visible_fields = [generated.get("name"), generated.get("role"), generated.get("description"), generated.get("persona"), *capabilities]
    if any(not contains_chinese(value) for value in visible_fields):
        raise HTTPException(status_code=502, detail="模型未能生成符合要求的中文拟人角色，本次人物未保存，请重新生成。")
    generated_role = str(generated.get("role") or "").strip()
    generated_capability_set = {str(item).strip() for item in capabilities if str(item).strip()}
    for existing_agent in existing:
        existing_capability_set = {str(item).strip() for item in existing_agent.get("capabilities", []) if str(item).strip()}
        overlap = len(generated_capability_set & existing_capability_set)
        overlap_ratio = overlap / max(1, min(len(generated_capability_set), len(existing_capability_set)))
        if str(existing_agent.get("role", "")).strip() == generated_role and overlap_ratio >= 0.5:
            return {
                "agent": existing_agent,
                "generation": {"mode": "reused", "model": configured_llm().model, "reason": "已有高度匹配的江湖人物"},
            }
    agent = platform_store.create_agent(
        name=str(generated.get("name") or "New Agent"),
        role=str(generated.get("role") or "specialist"),
        description=str(generated.get("description") or request.requirement),
        persona=str(generated.get("persona") or "Work independently and collaborate through formal artifacts."),
        capabilities=[str(item) for item in capabilities],
        visibility="private",
        skills=[dict(item) for item in skills if isinstance(item, dict)],
        runtime="openclaw",
        memory_policy={"enabled": True, "max_prompt_items": 8, "write_after_task": True},
    )
    return {"agent": agent, "generation": {"mode": "real-llm", "model": configured_llm().model}}


@app.get("/api/platform/teams")
async def list_platform_teams(organization_id: str | None = None) -> list[dict[str, object]]:
    return platform_store.list_teams(organization_id)


@app.post("/api/platform/teams")
async def create_platform_team(request: TeamCreateRequest) -> dict[str, object]:
    try:
        team = platform_store.create_team(
            organization_id=request.organization_id,
            name=request.name,
            purpose=request.purpose,
            operating_mode=request.operating_mode,
            members=[member.model_dump() for member in request.members],
            visibility=request.visibility,
            knowledge_paths=request.knowledge_paths,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"team": team}


@app.post("/api/platform/teams/{team_id}/members")
async def add_platform_team_member(team_id: str, request: TeamMemberRequest) -> dict[str, object]:
    try:
        team = platform_store.add_team_member(team_id, request.agent_id, request.responsibility)
    except ValueError as exc:
        status = 404 if str(exc) in {"team_not_found", "agent_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"team": team}


@app.post("/api/platform/teams/{team_id}/knowledge")
async def upload_platform_team_knowledge(team_id: str, request: TeamKnowledgeUploadRequest) -> dict[str, object]:
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="knowledge_file_base64_invalid") from exc
    try:
        return platform_store.attach_team_knowledge_file(
            team_id,
            request.filename,
            content,
            request.media_type,
            request.project_id,
            relative_path=request.relative_path,
            collection_id=request.collection_id,
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"team_not_found", "project_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


def decode_knowledge_file(payload: KnowledgeFolderFile) -> bytes:
    try:
        return base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"knowledge_file_base64_invalid:{payload.relative_path}") from exc


@app.post("/api/platform/teams/{team_id}/knowledge/folders")
async def upload_platform_team_knowledge_folder(team_id: str, request: KnowledgeFolderUploadRequest) -> dict[str, object]:
    collection_id = request.collection_id or f"folder_{os.urandom(6).hex()}"
    uploaded: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []
    for file in request.files:
        try:
            uploaded.append(
                platform_store.attach_team_knowledge_file(
                    team_id,
                    file.filename,
                    decode_knowledge_file(file),
                    file.media_type,
                    request.project_id,
                    relative_path=file.relative_path,
                    collection_id=collection_id,
                )
            )
        except ValueError as exc:
            failed.append({"relative_path": file.relative_path, "error": str(exc)})
    if not uploaded:
        raise HTTPException(status_code=422, detail={"message": "knowledge_folder_has_no_supported_files", "failed": failed})
    return {"collection_id": collection_id, "folder_name": request.folder_name, "uploaded": uploaded, "failed": failed}


@app.post("/api/platform/organizations/{organization_id}/knowledge")
async def upload_platform_organization_knowledge(organization_id: str, request: TeamKnowledgeUploadRequest) -> dict[str, object]:
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="knowledge_file_base64_invalid") from exc
    try:
        return platform_store.attach_organization_knowledge_file(
            organization_id,
            request.filename,
            content,
            request.media_type,
            request.project_id,
            relative_path=request.relative_path,
            collection_id=request.collection_id,
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"organization_not_found", "project_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/api/platform/organizations/{organization_id}/knowledge/folders")
async def upload_platform_organization_knowledge_folder(organization_id: str, request: KnowledgeFolderUploadRequest) -> dict[str, object]:
    collection_id = request.collection_id or f"folder_{os.urandom(6).hex()}"
    uploaded: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []
    for file in request.files:
        try:
            uploaded.append(
                platform_store.attach_organization_knowledge_file(
                    organization_id,
                    file.filename,
                    decode_knowledge_file(file),
                    file.media_type,
                    request.project_id,
                    relative_path=file.relative_path,
                    collection_id=collection_id,
                )
            )
        except ValueError as exc:
            failed.append({"relative_path": file.relative_path, "error": str(exc)})
    if not uploaded:
        raise HTTPException(status_code=422, detail={"message": "knowledge_folder_has_no_supported_files", "failed": failed})
    return {"collection_id": collection_id, "folder_name": request.folder_name, "uploaded": uploaded, "failed": failed}


@app.post("/api/platform/organizations/{organization_id}/knowledge/notes")
async def add_platform_organization_knowledge_note(organization_id: str, request: TeamKnowledgeNoteRequest) -> dict[str, object]:
    try:
        return platform_store.attach_organization_knowledge_note(
            organization_id, request.title, request.content, request.project_id
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"organization_not_found", "project_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/platform/organizations/{organization_id}/knowledge-graph")
async def get_platform_knowledge_graph(organization_id: str) -> dict[str, object]:
    try:
        return platform_store.knowledge_graph(organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/platform/teams/{team_id}/knowledge/notes")
async def add_platform_team_knowledge_note(team_id: str, request: TeamKnowledgeNoteRequest) -> dict[str, object]:
    try:
        return platform_store.attach_team_knowledge_note(
            team_id,
            request.title,
            request.content,
            request.project_id,
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"team_not_found", "project_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/platform/teams/{team_id}/knowledge/search")
async def search_platform_team_knowledge(
    team_id: str,
    q: str = Query(min_length=1, max_length=2_000),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict[str, object]:
    try:
        return platform_store.search_team_knowledge(team_id, q, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/platform/teams/{team_id}")
async def disband_platform_team(team_id: str) -> dict[str, object]:
    try:
        result = platform_store.disband_team(team_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **result,
        "deletion": {
            "mode": "soft_delete",
            "message": "组织已从当前江湖解散；历史流程、运行记录和产物证据继续保留。",
        },
    }


@app.post("/api/platform/company-tasks/assess", include_in_schema=False)
@app.post("/api/platform/commissions/assess")
async def assess_commission(request: CommissionAssessRequest) -> dict[str, object]:
    if request.commission_id:
        company_task = platform_store.get_company_task(request.commission_id)
        if not company_task:
            raise HTTPException(status_code=404, detail="company_task_not_found")
        if company_task["organization_id"] != request.organization_id:
            raise HTTPException(status_code=422, detail="commission_organization_mismatch")
    else:
        title = str(request.title or "").strip()
        description = str(request.description or "").strip()
        if not title or not description:
            raise HTTPException(status_code=422, detail="commission_title_and_description_required")
        try:
            company_task = platform_store.create_company_task(
                organization_id=request.organization_id,
                title=title,
                description=description,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    teams = platform_store.list_teams(str(company_task["organization_id"]))
    prompt = json.dumps(
        {
            "task": {"title": company_task["title"], "description": company_task["description"]},
            "teams": [
                {
                    "id": team["id"], "name": team["name"], "purpose": team["purpose"],
                    "operating_mode": team["operating_mode"], "capabilities": team["capabilities"],
                    "members": [{"name": member["name"], "role": member["role"], "capabilities": member["capabilities"]} for member in team["members"]],
                }
                for team in teams
            ],
            "output_schema": {
                "assessments": [
                    {
                        "team_id": "existing team id or null when no team exists",
                        "fit_status": "fit|partial|gap",
                        "fit_score": "0-100 integer",
                        "reasoning": "specific explanation to the commission initiator",
                        "missing_capabilities": ["capability"],
                        "recommended_agents": [{"role": "role", "purpose": "why needed", "capabilities": ["capability"]}],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    system = (
        "You are the Jianghu capability council. Return JSON only. Evaluate whether each existing Agent group can truly accept the commission. "
        "Be willing to reject unsuitable work. A score of 70 or more means the team can accept it. When capabilities are missing, explain the gap "
        "and recommend the smallest set of new personified Agents needed. If there are no teams, return one gap assessment with team_id null. "
        "Never claim capabilities not present in the supplied members."
    )
    try:
        generated = await configured_llm().json_message(prompt, system=system, max_tokens=4200)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc
    raw_assessments = generated.get("assessments")
    if not isinstance(raw_assessments, list) or not raw_assessments:
        raise HTTPException(status_code=502, detail="team_assessment_invalid")
    known_team_ids = {team["id"] for team in teams}
    assessments = []
    for item in raw_assessments:
        if not isinstance(item, dict):
            continue
        team_id = item.get("team_id")
        if team_id is not None and str(team_id) not in known_team_ids:
            continue
        assessments.append(
            {
                "team_id": str(team_id) if team_id is not None else None,
                "fit_status": str(item.get("fit_status") or "gap"),
                "fit_score": bounded_score(item.get("fit_score"), 0),
                "reasoning": str(item.get("reasoning") or "No evidence that the current team can own this task."),
                "missing_capabilities": [str(value) for value in item.get("missing_capabilities", []) if value],
                "recommended_agents": item.get("recommended_agents", []) if isinstance(item.get("recommended_agents"), list) else [],
            }
        )
    assessed = platform_store.save_team_assessments(company_task["id"], assessments)
    return {"commission": assessed, "company_task": assessed, "generation": {"mode": "real-llm", "model": configured_llm().model}}


@app.post("/api/platform/commissions/{commission_id}/resolve-team")
async def resolve_commission_team(
    commission_id: str,
    request: CommissionTeamResolveRequest,
) -> dict[str, object]:
    company_task = platform_store.get_company_task(commission_id)
    if not company_task:
        raise HTTPException(status_code=404, detail="company_task_not_found")
    organization_id = str(company_task["organization_id"])
    teams = platform_store.list_teams(organization_id)
    agents = platform_store.list_agents()
    if not agents:
        raise HTTPException(status_code=422, detail="no_agents_available_for_team_assembly")
    agent_map = {str(agent["id"]): agent for agent in agents}
    team_map = {str(team["id"]): team for team in teams}
    prompt = json.dumps(
        {
            "task": {"title": company_task["title"], "description": company_task["description"]},
            "force_create": request.force_create,
            "existing_team_assessments": company_task.get("assessments", []),
            "existing_teams": [
                {
                    "id": team["id"], "name": team["name"], "purpose": team["purpose"],
                    "operating_mode": team["operating_mode"],
                    "members": [
                        {
                            "id": member["id"], "name": member["name"], "role": member["role"],
                            "responsibility": member.get("responsibility", ""), "capabilities": member["capabilities"],
                        }
                        for member in team["members"]
                    ],
                }
                for team in teams
            ],
            "available_agents": [
                {
                    "id": agent["id"], "name": agent["name"], "role": agent["role"],
                    "description": agent["description"], "capabilities": agent["capabilities"],
                    "skills": [skill.get("name") for skill in agent.get("skills", []) if skill.get("enabled", True)],
                }
                for agent in agents
            ],
            "output_schema": {
                "decision": "reuse|create",
                "existing_team_id": "required only for reuse",
                "reason": "Chinese explanation for the initiator",
                "team_name": "Chinese personified organization name for create",
                "team_purpose": "the task-facing mission of this reusable team",
                "operating_mode": "collaborative|debate|red_team|hierarchical",
                "members": [
                    {
                        "agent_id": "an available agent id",
                        "member_role": "leader|member",
                        "responsibility": "specific Chinese responsibility for this team and task",
                    }
                ],
                "fit_score": "0-100 integer",
                "missing_capabilities": ["capability still not covered by the available agents"],
            },
        },
        ensure_ascii=False,
    )
    system = (
        "你是江湖 Online 的组队总管，只返回 JSON。你的职责是先复用、再组队：如果已有团队对当前委托确实适合，"
        "且 force_create 为 false，就必须 decision=reuse；只有已有团队不适合或用户明确 force_create 时，才从 available_agents "
        "选择完成任务所需的最小充分人物集合创建团队。不得发明人物 ID，不得为了热闹把所有人物都加入。"
        "创建时必须且只能有一位 leader，leader 放在 members 第一位；每个人必须有不重叠的具体职责。"
        "团队是可复用资产，名称和使命不能只写一次性任务编号，但职责要针对本次委托可执行。"
        "如果现有人物无法完全覆盖，也要组建当前最佳可行团队，并诚实填写 missing_capabilities 和 fit_score，不能虚构能力。"
        "所有面向用户的文字使用中文。"
    )
    try:
        generated = await configured_llm().json_message(prompt, system=system, max_tokens=4200)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc

    decision = str(generated.get("decision") or "create").lower()
    selected_team: dict[str, object] | None = None
    if decision == "reuse" and not request.force_create:
        selected_team = team_map.get(str(generated.get("existing_team_id") or ""))
    normalized_members: list[dict[str, str]] = []
    if selected_team is None:
        raw_members = generated.get("members") if isinstance(generated.get("members"), list) else []
        seen_ids: set[str] = set()
        for item in raw_members:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id") or "")
            if agent_id not in agent_map or agent_id in seen_ids:
                continue
            seen_ids.add(agent_id)
            normalized_members.append(
                {
                    "agent_id": agent_id,
                    "member_role": "leader" if not normalized_members else "member",
                    "responsibility": str(item.get("responsibility") or agent_map[agent_id].get("description") or "承担本团队专业职责"),
                }
            )
        if not normalized_members:
            raise HTTPException(status_code=502, detail="team_resolution_has_no_valid_members")
        member_ids = {item["agent_id"] for item in normalized_members}
        duplicate = next(
            (
                team for team in teams
                if {str(member["id"]) for member in team.get("members", [])} == member_ids
            ),
            None,
        )
        if duplicate and not request.force_create:
            decision = "reuse"
            selected_team = duplicate
        else:
            decision = "create"
    operating_mode = str(generated.get("operating_mode") or (selected_team or {}).get("operating_mode") or "collaborative")
    if operating_mode not in {"collaborative", "debate", "red_team", "hierarchical"}:
        operating_mode = "collaborative"
    if selected_team is not None:
        normalized_members = [
            {
                "agent_id": str(member["id"]),
                "member_role": str(member.get("member_role") or ("leader" if index == 0 else "member")),
                "responsibility": str(member.get("responsibility") or member.get("description") or "承担本团队专业职责"),
            }
            for index, member in enumerate(selected_team.get("members", []))
        ]
    matched_previous = next(
        (
            item for item in company_task.get("assessments", [])
            if selected_team is not None and str(item.get("team_id") or "") == str(selected_team["id"])
        ),
        None,
    )
    fit_score = bounded_score(generated.get("fit_score"), int((matched_previous or {}).get("fit_score", 70) or 70))
    missing_capabilities = [str(item) for item in generated.get("missing_capabilities", []) if item] if isinstance(generated.get("missing_capabilities"), list) else []
    reason = str(generated.get("reason") or "平台已依据当前需求、现有人物能力和已有团队完成组队判断。")
    try:
        proposal = platform_store.create_team_proposal(
            company_task_id=company_task["id"],
            decision=decision,
            existing_team_id=str(selected_team["id"]) if selected_team is not None else None,
            name=str((selected_team or {}).get("name") or generated.get("team_name") or f"{company_task['title']}行动社"),
            purpose=str((selected_team or {}).get("purpose") or generated.get("team_purpose") or f"协作完成与“{company_task['title']}”同类的生产任务"),
            operating_mode=operating_mode,
            members=normalized_members,
            fit_score=fit_score,
            reason=reason,
            missing_capabilities=missing_capabilities,
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"company_task_not_found", "team_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    assessed = platform_store.get_company_task(company_task["id"])
    return {
        "team": selected_team,
        "team_proposal": proposal,
        "company_task": assessed,
        "team_resolution": {
            "mode": decision,
            "status": "awaiting_confirmation",
            "reason": reason,
            "fit_score": fit_score,
            "missing_capabilities": missing_capabilities,
            "selected_agent_ids": [str(member["agent_id"]) for member in normalized_members],
        },
        "generation": {"mode": "real-llm", "model": configured_llm().model},
    }


@app.post("/api/platform/commissions/{commission_id}/team-proposals/{proposal_id}/confirm")
async def confirm_commission_team_proposal(
    commission_id: str,
    proposal_id: str,
    request: TeamProposalConfirmRequest,
) -> dict[str, object]:
    proposal = platform_store.get_team_proposal(proposal_id)
    if not proposal or str(proposal.get("company_task_id")) != commission_id:
        raise HTTPException(status_code=404, detail="team_proposal_not_found")
    try:
        result = platform_store.confirm_team_proposal(
            proposal_id,
            name=request.name,
            purpose=request.purpose,
            operating_mode=request.operating_mode,
            members=[member.model_dump() for member in request.members] if request.members is not None else None,
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"team_proposal_not_found", "company_task_not_found", "team_not_found"} else 409 if str(exc) == "team_proposal_is_not_pending" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {
        **result,
        "team_resolution": {
            "mode": proposal["decision"],
            "status": "confirmed",
            "reason": proposal["reason"],
            "fit_score": proposal["fit_score"],
            "missing_capabilities": proposal["missing_capabilities"],
        },
    }


@app.delete("/api/platform/commissions/{commission_id}/team-proposals/{proposal_id}")
async def reject_commission_team_proposal(commission_id: str, proposal_id: str) -> dict[str, object]:
    proposal = platform_store.get_team_proposal(proposal_id)
    if not proposal or str(proposal.get("company_task_id")) != commission_id:
        raise HTTPException(status_code=404, detail="team_proposal_not_found")
    try:
        return platform_store.reject_team_proposal(proposal_id)
    except ValueError as exc:
        status = 404 if str(exc) == "team_proposal_not_found" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/api/platform/team-workflows/generate")
async def generate_team_workflow(request: TeamWorkflowGenerateRequest) -> dict[str, object]:
    company_task = platform_store.get_company_task(request.company_task_id)
    if not company_task:
        raise HTTPException(status_code=404, detail="company_task_not_found")
    team_map = {team["id"]: team for team in platform_store.list_teams() if team["id"] in request.team_ids}
    if len(team_map) != len(set(request.team_ids)):
        raise HTTPException(status_code=422, detail="team_not_found")
    company_task = platform_store.select_company_task_teams(company_task["id"], request.team_ids)

    def version_key(value: object) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in str(value).split("."))
        except ValueError:
            return (0,)

    latest_by_family: dict[str, dict[str, object]] = {}
    for existing in platform_store.list_workflows():
        family_id = str(existing.get("family_id") or existing["id"])
        current = latest_by_family.get(family_id)
        if current is None or version_key(existing.get("version")) > version_key(current.get("version")):
            latest_by_family[family_id] = existing
    candidates = list(latest_by_family.values())[:16]
    candidate_map: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        candidate_map[str(candidate["id"])] = candidate
        candidate_map[str(candidate.get("family_id") or candidate["id"])] = candidate

    linked_latest: dict[str, object] | None = None
    if company_task.get("workflow_id"):
        linked = platform_store.get_workflow(str(company_task["workflow_id"]))
        if linked:
            linked_latest = latest_by_family.get(str(linked.get("family_id") or linked["id"]), linked)

    prompt = json.dumps(
        {
            "task": {"title": company_task["title"], "description": company_task["description"]},
            "currently_linked_workflow_id": linked_latest["id"] if linked_latest else None,
            "available_teams": [
                {
                    "id": team["id"], "name": team["name"], "purpose": team["purpose"], "capabilities": team["capabilities"],
                    "members": [
                        {"id": member["id"], "name": member["name"], "role": member["role"], "capabilities": member["capabilities"]}
                        for member in team["members"]
                    ],
                }
                for team in team_map.values()
            ],
            "existing_workflow_families": [
                {
                    "id": workflow["id"],
                    "family_id": workflow.get("family_id") or workflow["id"],
                    "name": workflow["name"],
                    "description": workflow["description"],
                    "version": workflow["version"],
                    "nodes": [
                        {
                            "key": node.get("key"),
                            "name": node.get("name"),
                            "purpose": node.get("purpose"),
                            "team_id": node.get("team_id"),
                            "participant_agent_ids": node.get("participant_agent_ids", []),
                        }
                        for node in workflow["definition"].get("nodes", [])
                    ],
                    "edges": workflow["definition"].get("edges", []),
                }
                for workflow in candidates
            ],
            "output_schema": {
                "decision": "reuse | revise | create",
                "selected_workflow_id": "existing latest workflow id when decision is reuse or revise",
                "reason": "Chinese explanation of why this workflow is reused, upgraded, or newly created",
                "recommended_changes": ["Chinese change summary; empty for reuse"],
                "name": "Chinese flow name; required for revise/create",
                "description": "Chinese description; required for revise/create",
                "nodes": [{
                    "key": "node_key", "name": "Chinese node name", "purpose": "Chinese formal output", "team_id": "available team id",
                    "participant_agent_ids": ["only the member ids materially needed for this node"],
                    "lead_agent_id": "one participant who coordinates this node",
                    "type": "team_task | judge",
                    "communication_rounds": "1-3; judge must be 0",
                }],
                "edges": [["from_node", "to_node"]],
            },
        },
        ensure_ascii=False,
    )
    system = (
        "你是江湖 Online 的生产流总设计师，只返回 JSON。先判断已有 Workflow 家族是否适合当前委托：完全适合则 reuse；"
        "属于同类生产流但节点、人物绑定或能力有缺口则 revise，并基于已有家族形成新版本；只有与所有已有流程都无关时才 create。"
        "同一委托已经绑定 Workflow 时，优先 reuse 或 revise，不能另建重复家族。reuse 时可以不返回 nodes；revise/create 时必须返回完整 DAG。"
        "所有名称、说明和节点文案使用中文。每个节点只能由一个提供的团队负责，但只绑定完成该节点实际必要的最少人物，绝不能把全体成员复制到每个节点。"
        "没有真实产物依赖的节点应并行，边只表示正式产物依赖；需要质量收益时加入评审、争辩或独立验收。"
        "裁判节点 type 必须为 judge，只绑定一位具有裁判/验收职责的人物，且该人物不能出现在被裁决的创作节点。"
        "多人节点先隔离独立作答，再进行 1-3 轮公开类型化通信；communication_rounds 只表示上限内实际需要的轮数。"
        "正常流程通常为 4-10 个有明确正式产物的节点，避免无意义微步骤。"
    )
    try:
        generated = await configured_llm().json_message(prompt, system=system, max_tokens=5000)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc

    decision = str(generated.get("decision") or "create").lower()
    if decision not in {"reuse", "revise", "create"}:
        decision = "create"
    selected = candidate_map.get(str(generated.get("selected_workflow_id") or ""))
    if linked_latest and decision == "create":
        decision = "revise"
        selected = linked_latest
    if decision in {"reuse", "revise"} and selected is None:
        selected = linked_latest
    if decision in {"reuse", "revise"} and selected is None:
        decision = "create"

    reason = str(generated.get("reason") or "模型已根据当前委托与已有生产流完成适配判断。")
    changes = [str(item) for item in generated.get("recommended_changes", []) if item] if isinstance(generated.get("recommended_changes"), list) else []

    try:
        if decision == "reuse" and selected is not None:
            workflow = selected
        else:
            nodes = generated.get("nodes")
            if not isinstance(nodes, list) or not nodes:
                raise ValueError("team_workflow_has_no_nodes")
            normalized_nodes = []
            for index, node in enumerate(nodes):
                if not isinstance(node, dict) or str(node.get("team_id")) not in team_map:
                    raise ValueError("team_workflow_uses_unknown_team")
                team = team_map[str(node["team_id"])]
                team_member_map = {member["id"]: member for member in team["members"]}
                requested_participants = node.get("participant_agent_ids") if isinstance(node.get("participant_agent_ids"), list) else []
                participant_ids = list(dict.fromkeys(str(item) for item in requested_participants if str(item) in team_member_map))
                if not participant_ids:
                    participant_ids = [str(node.get("lead_agent_id"))] if str(node.get("lead_agent_id")) in team_member_map else [team["members"][0]["id"]]
                lead_id = str(node.get("lead_agent_id") or "")
                if lead_id not in participant_ids:
                    lead_id = participant_ids[0]
                leader = team_member_map[lead_id]
                node_type = "judge" if str(node.get("type") or "") == "judge" or any(keyword in str(leader.get("role") or "") for keyword in ("裁判", "验收", "仲裁")) else "team_task"
                if node_type == "judge":
                    participant_ids = [lead_id]
                normalized_nodes.append(
                    {
                        "key": str(node.get("key") or f"node_{index + 1}"),
                        "name": str(node.get("name") or f"行动节点 {index + 1}"),
                        "purpose": str(node.get("purpose") or "形成可交付、可复核的正式产物"),
                        "type": node_type,
                        "team_id": team["id"],
                        "team_name": team["name"],
                        "agent_id": leader["id"],
                        "agent_role": leader["role"],
                        "participant_agent_ids": participant_ids,
                        "communication_rounds": 0 if node_type == "judge" else max(1, min(3, int(node.get("communication_rounds", 1) or 1))),
                    }
                )
            definition = {
                "schema_version": "2.0-team",
                "inputs": ["company_task"],
                "outputs": ["accepted_delivery"],
                "nodes": normalized_nodes,
                "edges": generated.get("edges") if isinstance(generated.get("edges"), list) else [],
                "policies": {"max_parallel_agents": 5, "max_debate_rounds": 3, "max_revision_rounds": 3, "max_run_minutes": 60},
            }
            workflow_name = str(generated.get("name") or (selected["name"] if selected else f"{company_task['title']}生产流"))
            workflow_description = str(generated.get("description") or (selected["description"] if selected else "由江湖人物团队共同完成任务的生产流。"))
            if decision == "revise" and selected is not None:
                workflow = platform_store.revise_workflow(
                    str(selected["id"]),
                    name=workflow_name,
                    description=workflow_description,
                    definition=definition,
                    source="llm_optimized",
                )
            else:
                decision = "create"
                workflow = platform_store.create_workflow(
                    workflow_name,
                    workflow_description,
                    source="team_generated",
                    definition=definition,
                )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    company_task = platform_store.link_company_task(company_task["id"], workflow_id=workflow["id"])
    return {
        "workflow": workflow,
        "company_task": company_task,
        "workflow_decision": {
            "mode": decision,
            "reason": reason,
            "recommended_changes": changes,
            "family_id": workflow.get("family_id") or workflow["id"],
            "previous_workflow_id": selected["id"] if decision == "revise" and selected else None,
        },
        "generation": {"mode": "real-llm", "model": configured_llm().model},
    }


@app.get("/api/platform/commissions")
async def list_platform_commissions(organization_id: str | None = None) -> list[dict[str, object]]:
    return platform_store.list_company_tasks(organization_id)


@app.get("/api/platform/workflows")
async def list_platform_workflows() -> list[dict[str, object]]:
    return platform_store.list_workflows()


@app.delete("/api/platform/workflows/{workflow_id}")
async def delete_platform_workflow(workflow_id: str) -> dict[str, object]:
    try:
        archived = platform_store.archive_workflow_family(workflow_id)
    except ValueError as exc:
        status = 404 if str(exc) == "workflow_not_found" else 409 if str(exc) == "workflow_has_active_runs" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {
        "workflow": archived,
        "deletion": {
            "mode": "soft_delete",
            "message": "生产流家族已归档；历史版本、运行现场和产物证据继续保留。",
        },
    }


@app.post("/api/platform/workflows/{workflow_id}/revisions")
async def revise_platform_workflow(workflow_id: str, request: WorkflowRevisionRequest) -> dict[str, object]:
    try:
        workflow = platform_store.revise_workflow(
            workflow_id,
            name=request.name,
            description=request.description,
            definition=dict(request.definition),
        )
    except ValueError as exc:
        status = 404 if str(exc) == "workflow_not_found" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"workflow": workflow, "revision": {"mode": "new_version", "parent_workflow_id": workflow_id}}


@app.get("/api/platform/knowledge-sources")
async def list_platform_knowledge_sources(project_id: str | None = None) -> list[dict[str, object]]:
    return platform_store.list_knowledge_sources(project_id)


@app.get("/api/platform/knowledge-sources/page")
async def page_platform_knowledge_sources(
    scope_type: str = Query(pattern="^(organization|team)$"),
    scope_id: str = Query(min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    project_id: str | None = None,
) -> dict[str, object]:
    return platform_store.list_knowledge_sources_page(
        scope_type=scope_type,
        scope_id=scope_id,
        offset=offset,
        limit=limit,
        project_id=project_id,
    )


@app.post("/api/platform/knowledge-sources")
async def create_platform_knowledge_source(request: KnowledgeSourceRequest) -> dict[str, object]:
    try:
        source = platform_store.create_knowledge_source(
            request.project_id, request.name, request.source_type, request.uri, request.metadata
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"source": source}


@app.delete("/api/platform/knowledge-sources/{source_id}")
async def delete_platform_knowledge_source(source_id: str) -> dict[str, object]:
    try:
        return platform_store.delete_knowledge_source(source_id)
    except ValueError as exc:
        status = 404 if str(exc) == "knowledge_source_not_found" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/platform/knowledge-sources/{source_id}")
async def get_platform_knowledge_source(
    source_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=12, ge=1, le=100),
) -> dict[str, object]:
    try:
        return platform_store.knowledge_source_detail(source_id, offset, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/platform/knowledge-sources/{source_id}/download")
async def download_platform_knowledge_source(source_id: str) -> FileResponse:
    source = next((item for item in platform_store.list_knowledge_sources() if item["id"] == source_id), None)
    if not source:
        raise HTTPException(status_code=404, detail="knowledge_source_not_found")
    try:
        path = platform_store.knowledge_file_path(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=str(source.get("metadata", {}).get("media_type") or "application/octet-stream"), filename=str(source["name"]))


@app.get("/api/platform/marketplace")
async def list_platform_marketplace() -> dict[str, object]:
    agents = [agent for agent in platform_store.list_agents() if agent["visibility"] == "public"]
    workflows = [workflow for workflow in platform_store.list_workflows() if workflow["status"] == "ready"]
    return {"agents": agents, "workflows": workflows}


@app.get("/api/platform/llm/status")
async def llm_status() -> dict[str, object]:
    active = platform_store.get_active_model_config()
    configured = active is not None or all(
        os.getenv(name) for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_DEFAULT_SONNET_MODEL")
    )
    return {
        "configured": configured,
        "provider": active["provider"] if active else "anthropic-compatible",
        "base_url": active["base_url"] if active else os.getenv("ANTHROPIC_BASE_URL", ""),
        "model": active["model"] if active else os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
        "config_id": active["id"] if active else None,
        "token_hint": active["token_hint"] if active else None,
        "fallback": None,
    }


@app.get("/api/platform/openclaw/status")
async def openclaw_status() -> dict[str, object]:
    health = openclaw_runtime.health()
    try:
        active = platform_store.get_active_model_config(include_secret=True)
    except SecretStorageError as exc:
        health["available"] = False
        health["model_configured"] = False
        health["credential_error"] = True
        health["error"] = public_llm_error(LLMConfigurationError(str(exc)))
        return health
    health["model_configured"] = active is not None
    if health.get("available") and active:
        try:
            agents = platform_store.list_agents()
            memories = {agent["id"]: platform_store.list_agent_memories(agent["id"], 30) for agent in agents}
            synced = openclaw_runtime.sync(agents, memories, active)
            health["config_ready"] = True
            health["synced"] = synced
        except (OpenClawRuntimeError, ValueError) as exc:
            health["available"] = False
            health["error"] = str(exc)
    return health


@app.get("/api/platform/model-configs")
async def list_model_configs() -> list[dict[str, object]]:
    return platform_store.list_model_configs()


@app.post("/api/platform/model-configs")
async def save_model_config(request: ModelConfigRequest) -> dict[str, object]:
    try:
        saved = platform_store.save_model_config(
            config_id=request.id,
            name=request.name,
            provider=request.provider,
            base_url=request.base_url,
            model=request.model,
            token=request.token,
            active=request.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"config": saved}


@app.post("/api/platform/model-configs/test")
async def test_model_config(request: ModelConnectionTestRequest) -> dict[str, object]:
    if request.id and not request.token:
        active = platform_store.get_active_model_config(include_secret=True)
        if not active or active["id"] != request.id:
            raise HTTPException(status_code=404, detail="active_model_config_not_found")
        base_url, model, token = active["base_url"], active["model"], active["token"]
    else:
        base_url, model, token = request.base_url, request.model, request.token
    try:
        provider = "anthropic-compatible"
        if request.id:
            configs = {item["id"]: item for item in platform_store.list_model_configs()}
            provider = str(configs.get(request.id, {}).get("provider", provider))
        client = client_for_config(provider=provider, base_url=str(base_url), model=str(model), token=str(token))
        response = await client.message("Return exactly REAL_LLM_OK", max_tokens=32)
        return {"ok": True, "model": client.model, "usage": response.get("usage", {}), "response_id": response.get("id")}
    except (LLMConfigurationError, LLMRequestError) as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc


@app.post("/api/platform/llm/test")
async def test_llm() -> dict[str, object]:
    try:
        client = configured_llm()
        response = await client.message("Return exactly REAL_LLM_OK", max_tokens=32)
        return {"ok": True, "model": client.model, "usage": response.get("usage", {}), "response_id": response.get("id")}
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc


@app.post("/api/platform/clarifications")
async def create_platform_clarification(request: ClarificationCreateRequest) -> dict[str, object]:
    workflow = platform_store.get_workflow(request.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    prompt = json.dumps(
        {
            "requirement": request.requirement,
            "workflow": {"name": workflow["name"], "description": workflow["description"], "outputs": workflow["definition"].get("outputs", [])},
            "output_schema": {
                "questions": [
                    {"id": "stable_key", "question": "specific question", "why": "decision affected", "recommended_answer": "usable default"}
                ]
            },
        },
        ensure_ascii=False,
    )
    system = (
        "You are Jianghu Online Grill Me. Return JSON only. Ask 2 to 4 questions that are truly blocking "
        "execution or acceptance. Do not ask questions already answered by the requirement. Every question "
        "must explain its impact and include a concrete recommended default. "
        "All acceptance and delivery must use real LLM calls, real agents, real tools and real artifacts. "
        "Never propose mock, simulated, fake, placeholder or fallback execution, even as a default."
    )
    try:
        generated = await configured_llm().json_message(prompt, system=system, max_tokens=2500)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc
    questions = generated.get("questions")
    if not isinstance(questions, list) or not 2 <= len(questions) <= 4:
        raise HTTPException(status_code=502, detail="llm_clarification_questions_invalid")
    normalized = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict) or not str(question.get("question", "")).strip():
            raise HTTPException(status_code=502, detail="llm_clarification_question_invalid")
        normalized.append(
            {
                "id": str(question.get("id") or f"question_{index + 1}"),
                "question": str(question["question"]),
                "why": str(question.get("why") or "Affects workflow execution and acceptance"),
                "recommended_answer": str(question.get("recommended_answer") or "Use the system recommended default"),
            }
        )
    session = platform_store.create_clarification(request.workflow_id, request.requirement, normalized)
    return {"clarification": session, "generation": {"mode": "real-llm", "model": configured_llm().model}}


@app.post("/api/platform/clarifications/{clarification_id}/finalize")
async def finalize_platform_clarification(clarification_id: str, request: ClarificationFinalizeRequest) -> dict[str, object]:
    session = platform_store.get_clarification(clarification_id)
    if not session:
        raise HTTPException(status_code=404, detail="clarification_not_found")
    prompt = json.dumps(
        {
            "original_requirement": session["original_requirement"],
            "questions": session["questions"],
            "answers": request.answers,
            "output_schema": {
                "goal": "string",
                "users": ["string"],
                "scope_in": ["string"],
                "scope_out": ["string"],
                "acceptance_criteria": ["testable criterion"],
                "deliverables": ["string"],
                "constraints": ["string"],
                "assumptions": ["string"],
                "open_risks": ["string"],
            },
        },
        ensure_ascii=False,
    )
    system = (
        "You are the RequirementContract compiler. Return JSON only. Convert the original requirement and "
        "confirmed answers into a testable contract. Do not invent confirmed facts; put uncertainty into assumptions or open_risks."
    )
    try:
        contract = await configured_llm().json_message(prompt, system=system, max_tokens=3500)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc
    finalized = platform_store.finalize_clarification(clarification_id, request.answers, contract)
    return {"clarification": finalized, "contract": contract, "generation": {"mode": "real-llm", "model": configured_llm().model}}


@app.post("/api/platform/workflows/build")
async def build_platform_workflow(request: WorkflowBuildRequest) -> dict[str, object]:
    requirement = request.requirement.strip()
    if len(requirement) < 10:
        raise HTTPException(status_code=422, detail="requirement_too_short")
    available = platform_store.list_agents()
    role_map = {agent["role"]: agent for agent in available}
    prompt = json.dumps(
        {
            "requirement": requirement,
            "available_agent_roles": sorted(role_map),
            "output_schema": {
                "name": "string",
                "description": "string",
                "nodes": [{"key": "node_key", "name": "string", "type": "agent_task|judge", "agent_role": "one available role", "purpose": "string", "communication_rounds": "0-3"}],
                "edges": [["from_node_key", "to_node_key"]],
                "policies": {"max_parallel_agents": 5, "max_debate_rounds": 3, "max_run_minutes": 60},
            },
        },
        ensure_ascii=False,
    )
    system = (
        "You are the Jianghu Online workflow compiler. Generate only a JSON object. "
        "The workflow must be executable, use fixed bindings to the supplied agent roles, "
        "include a separate independent judge when quality evaluation is needed, and never invent roles. "
        "Build a real DAG rather than an automatic serial list: parallelize independent analysis, design, implementation or review nodes and add edges only for required artifact handoffs."
    )
    try:
        generated = await configured_llm().json_message(prompt, system=system, max_tokens=6000)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=public_llm_error(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=public_llm_error(exc)) from exc
    nodes = generated.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(status_code=502, detail="llm_workflow_has_no_nodes")
    normalized_nodes = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or node.get("agent_role") not in role_map:
            raise HTTPException(status_code=502, detail="llm_workflow_uses_unknown_agent_role")
        normalized_nodes.append(
            {
                "key": str(node.get("key") or f"node_{index + 1}"),
                "name": str(node.get("name") or f"Agent task {index + 1}"),
                "type": "judge" if str(node.get("type") or "") == "judge" or any(keyword in str(node.get("agent_role") or "") for keyword in ("裁判", "验收", "仲裁")) else "agent_task",
                "agent_role": node["agent_role"],
                "agent_id": role_map[node["agent_role"]]["id"],
                "purpose": str(node.get("purpose") or "Deliver the node artifact"),
                "communication_rounds": max(0, min(3, int(node.get("communication_rounds", 0) or 0))),
            }
        )
    normalized = {
        "schema_version": "1.0",
        "inputs": ["task"],
        "outputs": ["runnable_demo"],
        "nodes": normalized_nodes,
        "edges": generated.get("edges") if isinstance(generated.get("edges"), list) else [],
        "policies": {
            "max_parallel_agents": 5, "max_debate_rounds": 3, "max_revision_rounds": 3,
            "max_run_minutes": 60,
            **(generated.get("policies") if isinstance(generated.get("policies"), dict) else {}),
        },
    }
    try:
        workflow = platform_store.create_workflow(
            request.name or str(generated.get("name") or "Generated production workflow"),
            str(generated.get("description") or f"Generated from requirement: {requirement}"),
            source="llm_generated",
            definition=normalized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"workflow": workflow, "generation": {"mode": "real-llm", "status": "ready", "model": configured_llm().model, "requirement": requirement}}


@app.post("/api/platform/runs")
async def create_platform_run(request: RunCreateRequest) -> dict[str, object]:
    try:
        commission = None
        if request.commission_id:
            commission = platform_store.get_company_task(request.commission_id)
            if not commission:
                raise ValueError("company_task_not_found")
        run = platform_store.create_run(request.workflow_id, request.task, request.project_id, request.clarification_id)
        if request.commission_id:
            commission = platform_store.link_company_task(
                request.commission_id,
                workflow_id=request.workflow_id,
                run_id=run["id"],
            )
        return {"run": run, "commission": commission}
    except ValueError as exc:
        status = 404 if str(exc) in {"workflow_not_found", "project_not_found", "company_task_not_found"} else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/platform/runs/{run_id}")
async def get_platform_run(run_id: str) -> dict[str, object]:
    run = platform_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"run": run}


@app.get("/api/platform/artifacts/{artifact_id}/download")
async def download_platform_artifact(artifact_id: str) -> FileResponse:
    artifact = platform_store.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    try:
        path = platform_store.artifact_file_path(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = f"{artifact['title']}-v{artifact['version']}.md"
    return FileResponse(path, media_type=str(artifact.get("media_type") or "text/markdown"), filename=filename)


@app.get("/api/platform/runs/{run_id}/code/download")
async def download_platform_run_code(run_id: str) -> FileResponse:
    run = platform_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    code_root = Path(str(run["workspace"]["code"])).resolve()
    if not code_root.is_dir() or not any(path.is_file() for path in code_root.rglob("*")):
        raise HTTPException(status_code=404, detail="run_code_artifact_not_found")
    temp_root = Path(tempfile.mkdtemp(prefix=f"jianghu-{run_id}-"))
    archive_path = temp_root / f"{run_id}-真实工程产物.zip"
    ignored_parts = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".git"}
    ignored_suffixes = {".pyc", ".pyo"}
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(code_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(code_root)
            if any(part in ignored_parts for part in relative.parts) or path.suffix.lower() in ignored_suffixes:
                continue
            archive.write(path, relative.as_posix())
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=archive_path.name,
        background=BackgroundTask(shutil.rmtree, temp_root, ignore_errors=True),
    )


@app.post("/api/platform/runs/{run_id}/start")
async def start_platform_run(run_id: str) -> dict[str, object]:
    run = platform_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    active = platform_tasks.get(run_id)
    if active and not active.done():
        raise HTTPException(status_code=409, detail="run_already_active")
    if run["status"] != "draft":
        raise HTTPException(status_code=409, detail="run_is_immutable_use_retry_for_failed_run")
    runtime_snapshot = prepare_openclaw_run(run)
    schedule_platform_execution(run_id)
    return {"run": platform_store.get_run(run_id), "execution": {"mode": "openclaw", "status": "started", "runtime_snapshot": runtime_snapshot}}


@app.post("/api/platform/runs/{run_id}/retry")
async def retry_platform_run(run_id: str, request: RunRetryRequest | None = None) -> dict[str, object]:
    try:
        retry = platform_store.retry_run(run_id, from_task_id=request.from_task_id if request else None)
    except ValueError as exc:
        status = 404 if str(exc) in {"run_not_found", "workflow_not_found"} else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    for commission in platform_store.list_company_tasks():
        if commission.get("run_id") == run_id:
            platform_store.link_company_task(commission["id"], workflow_id=retry["workflow_id"], run_id=retry["id"])
            break
    runtime_snapshot = prepare_openclaw_run(retry)
    schedule_platform_execution(str(retry["id"]))
    return {
        "run": platform_store.get_run(retry["id"]),
        "retry": {
            "source_run_id": run_id,
            "source_task_id": request.from_task_id if request else None,
            "mode": "targeted_new_run" if request and request.from_task_id else "new_run",
            "status": "started",
            "runtime_snapshot": runtime_snapshot,
        },
    }


@app.post("/api/platform/runs/{run_id}/cancel")
async def cancel_platform_run(run_id: str) -> dict[str, object]:
    run = platform_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    active = platform_tasks.get(run_id)
    platform_store.update_run(run_id, status="cancelled", stage="cancelled")
    if active and not active.done():
        active.cancel()
    platform_store.append_run_event(run_id, "run.cancelled", "system", "执行已取消", "发起人停止了本次真实执行；已有事件和产物继续保留。")
    return {"run": platform_store.get_run(run_id)}


@app.post("/api/platform/runs/{run_id}/pause")
async def pause_platform_run(run_id: str) -> dict[str, object]:
    run = platform_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run["status"] in {"pause_requested", "paused"}:
        return {"run": run}
    if run["status"] != "running":
        raise HTTPException(status_code=409, detail="only_running_run_can_pause")
    platform_store.update_run(run_id, status="pause_requested")
    platform_store.append_run_event(
        run_id,
        "run.pause_requested",
        "intervention",
        "发起人要求现场停手",
        "当前已经发出的模型回合允许完成；下一个受控边界开始前，所有人物必须暂停并等待恢复。",
    )
    return {"run": platform_store.get_run(run_id)}


@app.post("/api/platform/runs/{run_id}/resume")
async def resume_platform_run(run_id: str) -> dict[str, object]:
    run = platform_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run["status"] == "running":
        return {"run": run}
    if run["status"] not in {"pause_requested", "paused"}:
        raise HTTPException(status_code=409, detail="run_is_not_paused")
    active = platform_tasks.get(run_id)
    platform_store.update_run(run_id, status="running")
    platform_store.append_run_event(
        run_id,
        "run.resumed",
        "intervention",
        "发起人允许继续行动",
        "现场沿用原 Run、原 WorkflowVersion 和已有产物，从暂停边界继续执行。",
    )
    if not active or active.done():
        prepare_openclaw_run(platform_store.get_run(run_id) or run)
        schedule_platform_execution(run_id)
    return {"run": platform_store.get_run(run_id)}


@app.post("/api/platform/runs/{run_id}/interventions")
async def intervene_platform_run(run_id: str, request: RunInterventionRequest) -> dict[str, object]:
    try:
        intervention = platform_store.create_run_intervention(
            run_id,
            kind=request.kind,
            content=request.content,
            task_id=request.task_id,
            agent_id=request.agent_id,
        )
    except ValueError as exc:
        status = 404 if str(exc) in {"run_not_found", "intervention_task_not_found", "intervention_agent_not_found"} else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    target = "整个现场"
    if request.task_id:
        run = platform_store.get_run(run_id)
        task = next((item for item in (run or {}).get("tasks", []) if item["id"] == request.task_id), None)
        target = f"节点“{task['node_name']}”" if task else request.task_id
    if request.agent_id:
        agent = platform_store.get_agent(request.agent_id)
        target += f"中的“{agent['name']}”" if agent else f"中的人物 {request.agent_id}"
    platform_store.append_run_event(
        run_id,
        "user.intervention.queued",
        "intervention",
        f"发起人向{target}补充了现场意见",
        request.content,
        {
            "intervention_id": intervention["id"],
            "task_id": request.task_id,
            "agent_id": request.agent_id,
            "kind": request.kind,
            "content": request.content,
            "status": "queued",
        },
    )
    return {"intervention": intervention, "run": platform_store.get_run(run_id)}


"""Removed legacy in-memory demo API.

The source is temporarily retained in this string while the old prototype
modules are removed separately. It cannot register routes or execute.

@app.post("/api/demo", response_model=RunSnapshot)
async def create_demo() -> RunSnapshot:
    run = store.create_demo_run()
    snapshot = store.snapshot(run.id)
    assert snapshot is not None
    return snapshot


@app.get("/api/demo", response_model=RunSnapshot)
async def get_demo() -> RunSnapshot:
    run = store.get_or_create_demo()
    snapshot = store.snapshot(run.id)
    assert snapshot is not None
    return snapshot


@app.get("/api/runs/{run_id}", response_model=RunSnapshot)
async def get_run(run_id: str) -> RunSnapshot:
    snapshot = store.snapshot(run_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Run not found")
    return snapshot


@app.post("/api/runs/{run_id}/start", response_model=RunSnapshot)
async def start_run(run_id: str) -> RunSnapshot:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    existing = store.tasks.get(run_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="Run is already active")
    if run.status == RunStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Completed runs are immutable")
    if run.status in {RunStatus.CANCELLED, RunStatus.FAILED}:
        run.status = RunStatus.DRAFT

    task = asyncio.create_task(run_demo(store, run_id))
    store.tasks[run_id] = task
    snapshot = store.snapshot(run_id)
    assert snapshot is not None
    return snapshot


@app.post("/api/runs/{run_id}/cancel", response_model=RunSnapshot)
async def cancel_run(run_id: str) -> RunSnapshot:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run.status = RunStatus.CANCELLED
    store.append_event(
        run_id,
        RunEvent(
            run_id=run_id,
            type="run.state_changed",
            category="system",
            title="运行已取消",
            summary="用户停止了当前运行，已有事件和产物仍然保留。",
            severity="warning",
        ),
    )
    snapshot = store.snapshot(run_id)
    assert snapshot is not None
    return snapshot


@app.get("/api/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
) -> StreamingResponse:
    if not store.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream():
        sequence = after_sequence
        while True:
            events = await store.wait_for_events(run_id, sequence)
            if not events:
                yield ": heartbeat\n\n"
                continue
            for event in events:
                sequence = event.sequence
                payload = json.dumps(event.model_dump(), ensure_ascii=False)
                yield f"id: {event.sequence}\nevent: run-event\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


"""

# Production-like local entrypoint: serve the built Vue client from the same
# origin as the API. API routes are registered first, so /api/* keeps working.
CLIENT_DIST = Path(__file__).resolve().parents[2] / "client" / "dist"
if CLIENT_DIST.joinpath("index.html").exists():
    app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")
