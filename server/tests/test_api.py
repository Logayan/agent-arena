import asyncio
import base64
import io
import json
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from server.app.main import app, bounded_score, capability_overlap_ratio
from server.app.models import RunStatus
from server.app.simulator import run_demo
from server.app.store import RunStore
from server.app.platform_store import PlatformStore, STARTER_STRATEGIST
from server.app.platform_executor import _extract_initiator_note, _resolve_gate_targets, _team_knowledge, execute_platform_run
from server.app.openclaw_runtime import OpenClawRuntime, OpenClawRuntimeError, openclaw_runtime
from server.app.showcase import CASE_ID, CASE_MANIFEST, CASE_TASK, comparison_report, ensure_showcase_assets


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_legacy_demo_api_is_not_available() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/demo")
    assert response.status_code == 405


@pytest.mark.anyio
async def test_missing_run_returns_404() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/runs/run_missing")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_terminal_platform_run_cannot_be_cancelled(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "terminal-run.db"))
    agent = platform.create_agent(
        name="终态校验员",
        role="交付校验",
        description="验证终态不可变",
        persona="谨慎",
        capabilities=["状态校验"],
    )
    workflow = platform.create_workflow(
        "终态取消校验流",
        "验证已完成 Run 不可被取消",
        "test",
        {
            "nodes": [{
                "key": "check",
                "name": "状态校验",
                "agent_id": agent["id"],
                "agent_role": agent["role"],
            }],
            "edges": [],
            "policies": {},
        },
    )
    run = platform.create_run(workflow["id"], "验证完成状态")
    platform.update_run(run["id"], status="completed", stage="completed")
    monkeypatch.setattr("server.app.main.platform_store", platform)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/platform/runs/{run['id']}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"] == "run_is_terminal"
    assert platform.get_run(run["id"])["status"] == "completed"


def _make_runtime_limited_run(tmp_path, *, max_run_minutes: int = 180):
    platform = PlatformStore(str(tmp_path / "runtime-extension.db"))
    agent = platform.create_agent(
        name="Runtime Tester",
        role="Execution Analyst",
        description="Checks resumable execution",
        persona="Keeps completed evidence intact",
        capabilities=["execution"],
    )
    workflow = platform.create_workflow(
        "Runtime extension workflow",
        "Workflow for runtime extension tests",
        "test",
        {
            "nodes": [
                {"key": "collect", "name": "Collect", "agent_id": agent["id"], "agent_role": agent["role"]},
                {"key": "deliver", "name": "Deliver", "agent_id": agent["id"], "agent_role": agent["role"]},
            ],
            "edges": [["collect", "deliver"]],
            "policies": {"max_run_minutes": max_run_minutes},
        },
    )
    run = platform.create_run(workflow["id"], "Complete a resumable task")
    collect = next(task for task in run["tasks"] if task["node_key"] == "collect")
    deliver = next(task for task in run["tasks"] if task["node_key"] == "deliver")
    artifact = platform.create_artifact(run["id"], collect["id"], "workflow_output", "Collected evidence", "kept")
    platform.update_task(collect["id"], status="completed", output_data={"artifact_id": artifact["id"]})
    platform.update_task(deliver["id"], status="pending")
    platform.append_run_event(run["id"], "run.started", "system", "Run started", "Started")
    platform.update_run(run["id"], status="budget_exhausted", stage="budget_exhausted", progress=50)
    platform.append_run_event(
        run["id"],
        "run.budget_exhausted",
        "system",
        "Budget exhausted",
        "Runtime limit reached",
        {"error_type": "RuntimeError", "error_detail": "budget_exhausted:run_time_limit"},
    )
    return platform, run, collect, deliver


def test_runtime_extension_preserves_completed_nodes_and_records_event(tmp_path) -> None:
    platform, run, collect, deliver = _make_runtime_limited_run(tmp_path)

    extended = platform.extend_run_time(run["id"], 60)

    assert extended["status"] == "running"
    assert next(task for task in extended["tasks"] if task["id"] == collect["id"])["status"] == "completed"
    assert next(task for task in extended["tasks"] if task["id"] == deliver["id"])["status"] == "pending"
    assert len([item for item in extended["artifacts"] if item["task_id"] == collect["id"]]) == 1
    extension = next(item for item in extended["events"] if item["type"] == "run.time_extended")
    assert extension["payload"]["minutes"] == 60
    assert extension["payload"]["effective_minutes"] == 240


def test_runtime_extension_rejects_token_limit_and_total_cap(tmp_path) -> None:
    platform, run, _, _ = _make_runtime_limited_run(tmp_path)
    platform.append_run_event(
        run["id"],
        "run.budget_exhausted",
        "system",
        "Token budget exhausted",
        "Token limit reached",
        {"error_type": "RuntimeError", "error_detail": "budget_exhausted:token_limit"},
    )
    with pytest.raises(ValueError, match="run_time_extension_not_allowed"):
        platform.extend_run_time(run["id"], 60)

    capped, capped_run, _, _ = _make_runtime_limited_run(tmp_path / "cap", max_run_minutes=300)
    first = capped.extend_run_time(capped_run["id"], 60)
    assert first["status"] == "running"
    capped.update_run(capped_run["id"], status="budget_exhausted", stage="budget_exhausted")
    capped.append_run_event(
        capped_run["id"],
        "run.budget_exhausted",
        "system",
        "Runtime limit reached",
        "Runtime limit reached",
        {"error_type": "RuntimeError", "error_detail": "budget_exhausted:run_time_limit"},
    )
    with pytest.raises(ValueError, match="run_time_extension_limit_exceeded"):
        capped.extend_run_time(capped_run["id"], 30)


@pytest.mark.anyio
async def test_runtime_extension_api_resumes_same_run(monkeypatch, tmp_path) -> None:
    platform, run, _, _ = _make_runtime_limited_run(tmp_path)
    monkeypatch.setattr("server.app.main.platform_store", platform)
    monkeypatch.setattr("server.app.main.prepare_openclaw_run", lambda current: {"mode": "test"})
    monkeypatch.setattr("server.app.main.schedule_platform_execution", lambda run_id: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/platform/runs/{run['id']}/extend", json={"minutes": 120})
    assert response.status_code == 200
    assert response.json()["run"]["id"] == run["id"]
    assert response.json()["run"]["status"] == "running"
    assert response.json()["extension"]["effective_minutes"] == 300


@pytest.mark.anyio
async def test_generated_workflow_uses_three_hour_default(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "workflow-default.db"))
    agent = platform.create_agent(
        name="Default Planner",
        role="Planner",
        description="Builds workflows",
        persona="Keeps execution bounded",
        capabilities=["planning"],
    )

    class WorkflowBuilder:
        model = "workflow-builder-test"

        async def json_message(self, prompt, system, max_tokens):
            return {
                "name": "Three hour default workflow",
                "description": "A generated workflow",
                "nodes": [{"key": "plan", "name": "Plan", "agent_role": agent["role"], "purpose": "Plan the work"}],
                "edges": [],
                "policies": {},
            }

    monkeypatch.setattr("server.app.main.platform_store", platform)
    monkeypatch.setattr("server.app.main.configured_llm", lambda: WorkflowBuilder())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/platform/workflows/build",
            json={"name": "Generated", "requirement": "Create a bounded planning workflow"},
        )
    assert response.status_code == 200
    assert response.json()["workflow"]["definition"]["policies"]["max_run_minutes"] == 180


@pytest.mark.anyio
async def test_demo_simulation_completes_with_fixed_defect_and_scores() -> None:
    store = RunStore()
    run = store.create_demo_run()

    await run_demo(store, run.id, delay=0)

    assert run.status == RunStatus.COMPLETED
    assert run.progress == 100
    assert run.total_score == 86
    assert run.defects[0].status == "fixed"
    assert store.events[run.id][-1].type == "run.state_changed"


@pytest.mark.anyio
async def test_platform_assets_are_persisted_and_workflow_binds_agents() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        workflows = await client.get("/api/platform/workflows")
        assert workflows.status_code == 200
        workflow = workflows.json()[0]
        assert workflow["status"] == "ready"
        assert workflow["agent_ids"]
        assert workflow["definition"]["nodes"][0]["agent_id"] in workflow["agent_ids"]



@pytest.mark.anyio
async def test_platform_workflow_build_requires_a_real_requirement() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/platform/workflows/build", json={"requirement": "short"})
        assert response.status_code == 422


def test_confirmed_requirement_contract_is_required_before_formal_run(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "platform.db"))
    now = "2026-01-01T00:00:00+00:00"
    agent_id = "agent_test"
    with platform._connect() as db:
        db.execute(
            """INSERT INTO agent_blueprints
            (id,name,role,description,persona,capabilities_json,version,visibility,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (agent_id, "Test Agent", "builder", "", "", "[]", "1.0.0", "private", now, now),
        )
    workflow = platform.create_workflow(
        "Test workflow",
        "A persisted test workflow",
        "test",
        {
            "nodes": [{"key": "build", "name": "Build", "agent_id": agent_id, "agent_role": "builder"}],
            "edges": [],
            "policies": {},
        },
    )
    clarification = platform.create_clarification(
        workflow["id"],
        "Build a real community repair application with runnable delivery",
        [{"id": "scope", "question": "What is in scope?", "why": "Defines acceptance", "recommended_answer": "Resident and property portals"}],
    )
    with pytest.raises(ValueError, match="requirement_contract_not_confirmed"):
        platform.create_run(workflow["id"], clarification["original_requirement"], clarification_id=clarification["id"])
    confirmed = platform.finalize_clarification(
        clarification["id"],
        [{"question_id": "scope", "answer": "Resident and property portals"}],
        {"goal": "Deliver a runnable repair application", "acceptance_criteria": ["Both portals can complete a repair lifecycle"]},
    )
    run = platform.create_run(workflow["id"], confirmed["original_requirement"], clarification_id=confirmed["id"])
    assert run["clarification_id"] == confirmed["id"]
    assert len(run["tasks"]) == len(workflow["definition"]["nodes"])


def test_model_token_is_encrypted_and_never_returned_by_listing(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "models.db"))
    saved = platform.save_model_config(
        config_id=None,
        name="Test model",
        provider="anthropic-compatible",
        base_url="https://model.example.test",
        model="test-model",
        token="test-secret-token",
        active=True,
    )
    assert "token" not in saved
    assert "encrypted_token" not in saved
    active = platform.get_active_model_config(include_secret=True)
    assert active is not None
    assert active["token"] == "test-secret-token"
    with platform._connect() as db:
        stored = db.execute("SELECT encrypted_token FROM model_configs WHERE id=?", (saved["id"],)).fetchone()[0]
    assert stored != "test-secret-token"
    assert stored.startswith("fernet:v1:")
    restarted = PlatformStore(str(tmp_path / "models.db"))
    restarted_active = restarted.get_active_model_config(include_secret=True)
    assert restarted_active is not None
    assert restarted_active["token"] == "test-secret-token"


def test_bounded_score_accepts_model_friendly_score_text() -> None:
    assert bounded_score("82/100") == 82
    assert bounded_score("评分：120") == 100
    assert bounded_score("unknown", 70) == 70


def test_rejected_root_judge_reopens_itself_when_no_target_is_given() -> None:
    assert _resolve_gate_targets("judge", {"verdict": "reject"}, {"judge": set()}, {"judge"}) == {"judge"}


def test_rejected_judge_prefers_explicit_targets_then_upstream() -> None:
    dependencies = {"build": set(), "judge": {"build"}, "publish": {"judge"}}
    assert _resolve_gate_targets("judge", {"target_node_keys": ["build"]}, dependencies, set(dependencies)) == {"build"}
    assert _resolve_gate_targets("judge", {}, dependencies, set(dependencies)) == {"build"}


def test_active_model_config_prefers_medium_tier(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "tier-order.db"))
    platform.save_model_config(config_id=None, name="low", provider="x", base_url="https://example.test", model="low-model", tier="low", token="low-token", active=True)
    platform.save_model_config(config_id=None, name="high", provider="x", base_url="https://example.test", model="high-model", tier="high", token="high-token", active=True)
    platform.save_model_config(config_id=None, name="medium", provider="x", base_url="https://example.test", model="medium-model", tier="medium", token="medium-token", active=True)
    assert platform.get_active_model_config(include_secret=True)["model"] == "medium-model"


def test_model_tier_lookup_does_not_silently_downgrade_when_strict(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "strict-tier.db"))
    platform.save_model_config(
        config_id=None,
        name="medium",
        provider="openai-responses",
        base_url="https://example.test",
        model="gpt-medium",
        tier="medium",
        token="shared-token",
        active=True,
    )
    assert platform.get_model_config_for_tier("medium", include_secret=True, allow_fallback=False)["model"] == "gpt-medium"
    assert platform.get_model_config_for_tier("high", include_secret=True, allow_fallback=False) is None
    assert platform.get_model_config_for_tier("low", include_secret=True, allow_fallback=False) is None
    assert platform.get_model_config_for_tier("high", include_secret=True)["model"] == "gpt-medium"


def test_multiple_model_configs_can_coexist_and_inactive_secret_is_addressable(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "multiple-models.db"))
    active = platform.save_model_config(
        config_id=None,
        name="primary",
        provider="openai-responses",
        base_url="https://example.test",
        model="gpt-primary",
        tier="medium",
        token="primary-token",
        active=True,
    )
    standby = platform.save_model_config(
        config_id=None,
        name="standby",
        provider="openai-responses",
        base_url="https://standby.example.test",
        model="gpt-standby",
        tier="medium",
        token="standby-token",
        active=False,
    )
    listed = platform.list_model_configs()
    assert {item["id"] for item in listed} == {active["id"], standby["id"]}
    assert next(item for item in listed if item["id"] == active["id"])["active"] is True
    stored_standby = platform.get_model_config(standby["id"], include_secret=True)
    assert stored_standby is not None
    assert stored_standby["token"] == "standby-token"


def test_deleting_active_model_config_promotes_latest_same_tier_config(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "delete-model.db"))
    first = platform.save_model_config(
        config_id=None,
        name="first",
        provider="openai-responses",
        base_url="https://example.test",
        model="gpt-first",
        tier="high",
        token="first-token",
        active=True,
    )
    second = platform.save_model_config(
        config_id=None,
        name="second",
        provider="openai-responses",
        base_url="https://example.test",
        model="gpt-second",
        tier="high",
        token="second-token",
        active=True,
    )
    deleted = platform.delete_model_config(second["id"])
    assert deleted["promoted_config_id"] == first["id"]
    assert platform.get_model_config_for_tier("high")["id"] == first["id"]


def test_new_workspace_contains_one_idempotent_high_capability_starter(tmp_path) -> None:
    database = tmp_path / "starter.db"
    first = PlatformStore(str(database))
    first_agents = first.list_agents()
    assert len(first_agents) == 1
    starter = first_agents[0]
    assert starter["id"] == STARTER_STRATEGIST["id"]
    assert starter["name"] == "沈砺川"
    assert starter["role"] == "科技产品与产业经营者"
    assert starter["visibility"] == "public"
    assert len(starter["capabilities"]) == 10
    assert len(starter["skills"]) == 6
    assert starter["memory_policy"]["review_before_promote"] is True

    restarted = PlatformStore(str(database))
    assert [agent["id"] for agent in restarted.list_agents()] == [STARTER_STRATEGIST["id"]]


def test_commission_survives_hiring_workflow_and_run_linking(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "commission.db"))
    agents = [
        platform.create_agent(
            name="沈测试", role="产品负责人", description="负责范围", persona="重视证据",
            capabilities=["需求澄清"],
        ),
        platform.create_agent(
            name="苏验证", role="质量工程师", description="负责验证", persona="独立审慎",
            capabilities=["自动化回归测试"],
        ),
    ]
    team = platform.create_team(
        organization_id="org_jianghu",
        name="持久化响应队",
        purpose="验证同一委托可以在补充人物后继续推进",
        operating_mode="collaborative",
        members=[{"agent_id": agents[0]["id"], "member_role": "leader", "responsibility": "牵头"}],
    )
    platform.add_team_member(team["id"], agents[1]["id"], "补足缺口")
    commission = platform.create_company_task(
        organization_id="org_jianghu",
        title="持久化委托",
        description="引入人物后不得丢失原委托",
    )
    commission = platform.save_team_assessments(
        commission["id"],
        [{"team_id": team["id"], "fit_status": "fit", "fit_score": 88, "reasoning": "能力已补足"}],
    )
    commission = platform.select_company_task_teams(commission["id"], [team["id"]])
    assert commission["selected_team_ids"] == [team["id"]]
    workflow = platform.create_workflow(
        "持久化执行流",
        "验证委托、流程和执行的关联",
        "test",
        {
            "nodes": [{
                "key": "deliver",
                "name": "完成交付",
                "agent_id": agents[0]["id"],
                "agent_role": agents[0]["role"],
                "team_id": team["id"],
                "participant_agent_ids": [agents[0]["id"], agents[1]["id"]],
            }],
            "edges": [],
            "policies": {},
        },
    )
    platform.link_company_task(commission["id"], workflow_id=workflow["id"])
    run = platform.create_run(workflow["id"], commission["description"])
    restored = platform.link_company_task(commission["id"], run_id=run["id"])
    assert restored["id"] == commission["id"]
    assert restored["workflow_id"] == workflow["id"]
    assert restored["run_id"] == run["id"]
    assert restored["assessments"][0]["fit_score"] == 88
    assert len(platform.get_team(team["id"])["members"]) == 2


def test_capability_matching_reuses_exact_role_with_specific_skill_labels() -> None:
    requested = {"自动化回归测试", "性能测试"}
    available = {"自动化回归测试建设", "性能测试与容量分析", "缺陷管理"}
    assert capability_overlap_ratio(requested, available) == 1.0


def test_workflow_revision_keeps_family_and_records_generation_source(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "workflow-revision.db"))
    agent = platform.create_agent(
        name="顾行舟",
        role="流程设计师",
        description="负责设计生产流",
        persona="重视复用与版本边界",
        capabilities=["流程设计"],
    )
    definition = {
        "nodes": [{"key": "plan", "name": "形成章法", "agent_id": agent["id"], "agent_role": agent["role"]}],
        "edges": [],
        "policies": {},
    }
    original = platform.create_workflow("通用章法", "第一版", "team_generated", definition)
    revised = platform.revise_workflow(
        original["id"],
        name="通用章法",
        description="根据新委托补足后的版本",
        definition=definition,
        source="llm_optimized",
    )
    assert revised["family_id"] == original["id"]
    assert revised["parent_workflow_id"] == original["id"]
    assert revised["version"] == "1.1.0"
    assert revised["source"] == "llm_optimized"


def test_failed_run_retry_creates_new_immutable_run(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "run-retry.db"))
    agent = platform.create_agent(
        name="沈复行",
        role="执行者",
        description="负责实际执行",
        persona="遇到瞬时失败会留下证据后重试",
        capabilities=["任务执行"],
    )
    workflow = platform.create_workflow(
        "可重试章法",
        "失败后创建新现场",
        "test",
        {
            "nodes": [{"key": "work", "name": "实际行动", "agent_id": agent["id"], "agent_role": agent["role"]}],
            "edges": [],
            "policies": {},
        },
    )
    failed = platform.create_run(workflow["id"], "完成一项真实任务")
    platform.update_run(failed["id"], status="failed", stage="execution_failed")
    retried = platform.retry_run(failed["id"])
    assert retried["id"] != failed["id"]
    assert retried["status"] == "draft"
    assert retried["task_input"] == failed["task_input"]
    assert retried["tasks"][0]["status"] == "pending"
    assert retried["events"][0]["type"] == "run.retry_created"
    assert platform.get_run(failed["id"])["status"] == "failed"


def test_targeted_retry_preserves_completed_upstream_artifact(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "targeted-run-retry.db"))
    planner = platform.create_agent(
        name="沈先行", role="规划者", description="形成上游规划", persona="保留已验证产物",
        capabilities=["规划"],
    )
    builder = platform.create_agent(
        name="林再行", role="执行者", description="根据规划形成交付", persona="失败后定向重试",
        capabilities=["实现"],
    )
    workflow = platform.create_workflow(
        "定向重试章法",
        "只重跑失败节点和下游",
        "test",
        {
            "nodes": [
                {"key": "plan", "name": "形成规划", "agent_id": planner["id"], "agent_role": planner["role"]},
                {"key": "build", "name": "完成实现", "agent_id": builder["id"], "agent_role": builder["role"]},
            ],
            "edges": [["plan", "build"]],
            "policies": {},
        },
    )
    failed = platform.create_run(workflow["id"], "依据规划完成真实实现")
    plan_task = next(task for task in failed["tasks"] if task["node_key"] == "plan")
    build_task = next(task for task in failed["tasks"] if task["node_key"] == "build")
    platform.update_task(plan_task["id"], status="completed")
    platform.create_artifact(failed["id"], plan_task["id"], "workflow_output", "正式规划", "# 已验证规划", "candidate")
    platform.update_task(build_task["id"], status="failed", output_data={"error": "temporary failure"})
    platform.update_run(failed["id"], status="failed", stage="execution_failed")

    retried = platform.retry_run(failed["id"], from_task_id=build_task["id"])
    retried_plan = next(task for task in retried["tasks"] if task["node_key"] == "plan")
    retried_build = next(task for task in retried["tasks"] if task["node_key"] == "build")
    assert retried_plan["status"] == "completed"
    assert retried_build["status"] == "pending"
    assert retried["artifacts"][0]["task_id"] == retried_plan["id"]
    assert retried["artifacts"][0]["content"] == "# 已验证规划"
    assert retried["events"][0]["payload"]["retry_from_node_key"] == "build"
    assert retried["events"][0]["payload"]["preserved_node_keys"] == ["plan"]


@pytest.mark.anyio
async def test_commission_team_resolution_requires_confirmation_before_creating_team(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "team-resolution.db"))
    product = platform.create_agent(
        name="沈问策", role="产品负责人", description="澄清目标与验收", persona="目标导向",
        capabilities=["需求澄清", "验收标准"],
    )
    engineer = platform.create_agent(
        name="林造物", role="全栈工程师", description="实现并测试可运行交付", persona="以真实产物为准",
        capabilities=["软件开发", "自动化测试"],
    )
    commission = platform.create_company_task(
        organization_id="org_jianghu",
        title="开发一个可运行工具",
        description="从需求澄清到开发测试形成真实可运行交付",
    )

    class TeamPlanner:
        model = "team-planner-test"

        async def json_message(self, prompt, system, max_tokens):
            return {
                "decision": "create",
                "reason": "已有团队不匹配，使用现有人物组成最小交付团队。",
                "team_name": "问策造物社",
                "team_purpose": "持续完成从需求澄清到可运行软件交付的任务",
                "operating_mode": "collaborative",
                "members": [
                    {"agent_id": product["id"], "member_role": "leader", "responsibility": "负责目标、范围和验收"},
                    {"agent_id": engineer["id"], "member_role": "member", "responsibility": "负责真实开发、测试和交付"},
                ],
                "fit_score": 88,
                "missing_capabilities": [],
            }

    monkeypatch.setattr("server.app.main.platform_store", platform)
    monkeypatch.setattr("server.app.main.configured_llm", lambda: TeamPlanner())
    team_count_before = len(platform.list_teams("org_jianghu"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/platform/commissions/{commission['id']}/resolve-team", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["team_resolution"]["mode"] == "create"
        assert body["team_resolution"]["status"] == "awaiting_confirmation"
        assert body["team"] is None
        assert body["team_proposal"]["name"] == "问策造物社"
        assert [member["agent_id"] for member in body["team_proposal"]["members"]] == [product["id"], engineer["id"]]
        assert body["company_task"]["selected_team_ids"] == []
        assert len(platform.list_teams("org_jianghu")) == team_count_before

        proposal_id = body["team_proposal"]["id"]
        confirmed = await client.post(
            f"/api/platform/commissions/{commission['id']}/team-proposals/{proposal_id}/confirm",
            json={
                "name": "问策造物社（确认版）",
                "purpose": "持续交付可运行软件",
                "operating_mode": "collaborative",
                "members": body["team_proposal"]["members"],
            },
        )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["team"]["name"] == "问策造物社（确认版）"
    assert [member["id"] for member in confirmed_body["team"]["members"]] == [product["id"], engineer["id"]]
    assert confirmed_body["company_task"]["selected_team_ids"] == [confirmed_body["team"]["id"]]
    assert len(platform.list_teams("org_jianghu")) == team_count_before + 1


@pytest.mark.anyio
async def test_rejected_team_proposal_does_not_create_or_select_team(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "team-proposal-reject.db"))
    agent = platform.create_agent(
        name="顾缓行", role="调研员", description="负责形成调研证据", persona="先建议后行动", capabilities=["调研"],
    )
    commission = platform.create_company_task(
        organization_id="org_jianghu", title="开展专项调研", description="需要一支临时调研团队",
    )
    proposal = platform.create_team_proposal(
        company_task_id=commission["id"], decision="create", existing_team_id=None,
        name="专项调研社", purpose="完成可核验调研", operating_mode="collaborative",
        members=[{"agent_id": agent["id"], "member_role": "leader", "responsibility": "负责调研"}],
        fit_score=82, reason="当前没有适用团队，建议新组队。", missing_capabilities=[],
    )
    team_count_before = len(platform.list_teams("org_jianghu"))
    monkeypatch.setattr("server.app.main.platform_store", platform)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/api/platform/commissions/{commission['id']}/team-proposals/{proposal['id']}"
        )
    assert response.status_code == 200
    assert response.json()["proposal"]["status"] == "rejected"
    assert response.json()["company_task"]["selected_team_ids"] == []
    assert len(platform.list_teams("org_jianghu")) == team_count_before


@pytest.mark.anyio
async def test_workflow_delete_archives_family_and_blocks_unfinished_runs(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "workflow-delete.db"))
    agent = platform.create_agent(
        name="闻归档", role="流程管理员", description="负责流程治理", persona="保留历史证据", capabilities=["流程治理"],
    )
    definition = {
        "nodes": [{"key": "deliver", "name": "形成交付", "agent_id": agent["id"], "agent_role": agent["role"]}],
        "edges": [],
    }
    active = platform.create_workflow("执行中章法", "存在未结束运行", "test", definition)
    platform.create_run(active["id"], "执行一件事")
    removable = platform.create_workflow("可归档章法", "没有运行", "test", definition)
    removable_v2 = platform.revise_workflow(
        removable["id"], name="可归档章法", description="第二版", definition=definition,
    )
    monkeypatch.setattr("server.app.main.platform_store", platform)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.delete(f"/api/platform/workflows/{active['id']}")
        archived = await client.delete(f"/api/platform/workflows/{removable_v2['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "workflow_has_active_runs"
    assert archived.status_code == 200
    assert set(archived.json()["workflow"]["workflow_ids"]) == {removable["id"], removable_v2["id"]}
    assert platform.get_workflow(removable["id"])["status"] == "archived"
    assert platform.get_workflow(removable_v2["id"])["status"] == "archived"
    assert {item["id"] for item in platform.list_workflows()}.isdisjoint({removable["id"], removable_v2["id"]})


@pytest.mark.anyio
async def test_knowledge_folder_batches_share_collection_and_sources_page(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "knowledge-page.db"))
    agent = platform.create_agent(
        name="白知卷", role="知识管理员", description="维护知识目录", persona="重视分页读取", capabilities=["知识管理"],
    )
    team = platform.create_team(
        organization_id="org_jianghu", name="知卷阁", purpose="管理目录知识", operating_mode="collaborative",
        members=[{"agent_id": agent["id"], "member_role": "leader", "responsibility": "维护知识"}],
    )
    monkeypatch.setattr("server.app.main.platform_store", platform)
    collection_id = "folder_shared_batch"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for start in (0, 2):
            files = [
                {
                    "filename": f"规则-{index}.md",
                    "relative_path": f"完整目录/子目录/规则-{index}.md",
                    "media_type": "text/markdown",
                    "content_base64": base64.b64encode(f"# 规则 {index}\n\n批次知识 {index}".encode()).decode(),
                }
                for index in range(start, start + 2)
            ]
            uploaded = await client.post(
                f"/api/platform/teams/{team['id']}/knowledge/folders",
                json={"folder_name": "完整目录", "collection_id": collection_id, "files": files},
            )
            assert uploaded.status_code == 200
            assert uploaded.json()["collection_id"] == collection_id
        first_page = await client.get(
            "/api/platform/knowledge-sources/page",
            params={"scope_type": "team", "scope_id": team["id"], "offset": 0, "limit": 3},
        )
        second_page = await client.get(
            "/api/platform/knowledge-sources/page",
            params={"scope_type": "team", "scope_id": team["id"], "offset": 3, "limit": 3},
        )
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 3
    assert first_page.json()["pagination"] == {"offset": 0, "limit": 3, "total": 4, "has_more": True}
    assert len(second_page.json()["items"]) == 1
    assert {item["metadata"]["collection_id"] for item in first_page.json()["items"] + second_page.json()["items"]} == {collection_id}


@pytest.mark.anyio
async def test_delete_managed_knowledge_removes_file_chunks_bindings_and_team_path(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "knowledge-delete.db"))
    agent = platform.create_agent(
        name="白归卷", role="知识管理员", description="维护知识删除闭环", persona="谨慎删除", capabilities=["知识管理"],
    )
    team = platform.create_team(
        organization_id="org_jianghu", name="归卷阁", purpose="验证知识删除", operating_mode="collaborative",
        members=[{"agent_id": agent["id"], "member_role": "leader", "responsibility": "维护知识"}],
    )
    monkeypatch.setattr("server.app.main.platform_store", platform)
    payload = {
        "folder_name": "待删除目录",
        "collection_id": "folder_delete_test",
        "files": [{
            "filename": "待删除规则.md",
            "relative_path": "待删除目录/待删除规则.md",
            "media_type": "text/markdown",
            "content_base64": base64.b64encode("# 删除验证\n\n此内容应连同 RAG 切片一起删除。".encode()).decode(),
        }],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post(f"/api/platform/teams/{team['id']}/knowledge/folders", json=payload)
        assert uploaded.status_code == 200
        source = uploaded.json()["uploaded"][0]["source"]
        managed_path = Path(source["uri"])
        managed_directory = managed_path.parent
        assert managed_path.is_file()
        assert (managed_directory / "extracted.txt").is_file()
        assert str(managed_path.resolve()) in platform.get_team(team["id"])["knowledge_paths"]
        deleted = await client.delete(f"/api/platform/knowledge-sources/{source['id']}")
        missing = await client.delete(f"/api/platform/knowledge-sources/{source['id']}")
        page = await client.get(
            "/api/platform/knowledge-sources/page",
            params={"scope_type": "team", "scope_id": team["id"], "offset": 0, "limit": 20},
        )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["physical_file_deleted"] is True
    assert missing.status_code == 404
    assert page.json()["pagination"]["total"] == 0
    assert not managed_directory.exists()
    assert platform.get_knowledge_source(source["id"]) is None
    assert str(managed_path.resolve()) not in platform.get_team(team["id"])["knowledge_paths"]
    with platform._connect() as db:
        chunk_count = db.execute("SELECT COUNT(*) AS value FROM knowledge_chunks WHERE source_id=?", (source["id"],)).fetchone()["value"]
        binding_count = db.execute("SELECT COUNT(*) AS value FROM knowledge_bindings WHERE source_id=?", (source["id"],)).fetchone()["value"]
    assert chunk_count == 0
    assert binding_count == 0


def test_run_workspace_is_isolated_and_artifact_is_materialized(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "workspace.db"))
    agent = platform.create_agent(
        name="林归档",
        role="交付工程师",
        description="负责形成真实文件产物",
        persona="严格遵守运行隔离边界",
        capabilities=["交付归档"],
    )
    workflow = platform.create_workflow(
        "隔离交付流",
        "每次执行拥有独立工作区",
        "test",
        {
            "nodes": [{"key": "deliver", "name": "形成交付物", "agent_id": agent["id"], "agent_role": agent["role"]}],
            "edges": [],
            "policies": {},
        },
    )
    run = platform.create_run(workflow["id"], "形成可追溯交付物")
    workspace_root = tmp_path / "workspaces" / "project_jianghu" / "runs" / run["id"]
    assert run["workspace"]["root"] == str(workspace_root.resolve())
    assert (workspace_root / "input" / "task.json").is_file()
    assert (workspace_root / "workflow" / "workflow.json").is_file()
    assert (workspace_root / "code").is_dir()
    task = run["tasks"][0]
    artifact = platform.create_artifact(run["id"], task["id"], "workflow_output", "交付说明", "# 真实交付\n\n内容", "candidate")
    artifact_path = workspace_root / artifact["relative_path"]
    assert artifact_path.read_text(encoding="utf-8") == "# 真实交付\n\n内容"
    assert artifact["sha256"]
    manifest = (workspace_root / "manifest.json").read_text(encoding="utf-8")
    assert artifact["id"] in manifest
    assert platform.artifact_file_path(artifact["id"]) == artifact_path.resolve()


def test_team_knowledge_upload_is_platform_managed_and_bound_to_team(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "knowledge.db"))
    agent = platform.create_agent(
        name="知库管理员",
        role="知识管理员",
        description="维护组织公共知识",
        persona="重视来源和版本",
        capabilities=["知识管理"],
    )
    team = platform.create_team(
        organization_id="org_jianghu",
        name="知识营",
        purpose="使用平台托管知识开展工作",
        operating_mode="collaborative",
        members=[{"agent_id": agent["id"], "member_role": "leader", "responsibility": "维护公共知识"}],
    )
    payload = "# 组织规则\n\n所有正式结论必须引用来源。".encode("utf-8")
    uploaded = platform.attach_team_knowledge_file(team["id"], "组织规则.md", payload, "text/markdown")
    source = uploaded["source"]
    managed_path = platform.knowledge_file_path(source["id"])
    assert managed_path.is_relative_to((tmp_path / "knowledge").resolve())
    assert managed_path.read_bytes() == payload
    assert source["metadata"]["original_filename"] == "组织规则.md"
    assert source["metadata"]["sha256"]
    assert str(managed_path) in uploaded["team"]["knowledge_paths"]
    repeated = platform.attach_team_knowledge_file(team["id"], "copy.md", payload, "text/markdown")
    assert repeated["reused"] is True
    assert repeated["source"]["id"] == source["id"]
    managed_sources = [
        item
        for item in platform.list_knowledge_sources()
        if item["source_type"] == "managed_upload" and item["metadata"].get("team_id") == team["id"]
    ]
    assert len(managed_sources) == 1
    assert source["status"] == "ready"
    assert source["metadata"]["indexed"] is True
    assert source["metadata"]["chunk_count"] >= 1
    detail = platform.knowledge_source_detail(source["id"])
    assert detail["pagination"]["total"] >= 1
    assert detail["chunks"][0]["source_id"] == source["id"]

    note = platform.attach_team_knowledge_note(
        team["id"],
        "Release policy",
        "Production releases require rollback drills and a named incident commander.",
    )
    note_search = platform.search_team_knowledge(team["id"], "rollback incident commander")
    assert note["source"]["source_type"] == "managed_note"
    assert note_search["strategy"] == "hybrid_lexical_char_ngram"
    assert note_search["results"][0]["source_id"] == note["source"]["id"]
    agent_context, agent_matches = _team_knowledge(platform, platform.get_team(team["id"]), "rollback incident commander")
    assert note["source"]["id"] in agent_context
    assert agent_matches[0]["source_id"] == note["source"]["id"]

    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Capacity Plan"
    worksheet.append(["service", "maximum concurrency", "owner"])
    worksheet.append(["workflow runner", 5, "platform team"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    spreadsheet = platform.attach_team_knowledge_file(
        team["id"],
        "capacity-plan.xlsx",
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    spreadsheet_search = platform.search_team_knowledge(team["id"], "maximum concurrency workflow runner")
    assert spreadsheet["source"]["metadata"]["parser"] == "openpyxl"
    assert spreadsheet_search["results"][0]["source_id"] == spreadsheet["source"]["id"]

    document_buffer = io.BytesIO()
    with zipfile.ZipFile(document_buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Customer escalation handbook</w:t></w:r></w:p>
              <w:p><w:r><w:t>Critical incidents require executive notification within fifteen minutes.</w:t></w:r></w:p></w:body>
            </w:document>""",
        )
    document = platform.attach_team_knowledge_file(
        team["id"],
        "escalation-handbook.docx",
        document_buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    document_search = platform.search_team_knowledge(team["id"], "executive notification fifteen minutes")
    assert document["source"]["metadata"]["parser"] == "docx-openxml"
    assert document_search["results"][0]["source_id"] == document["source"]["id"]


def test_managed_knowledge_paths_are_repaired_after_data_directory_moves(tmp_path) -> None:
    database_path = tmp_path / "portable.db"
    platform = PlatformStore(str(database_path))
    agent = platform.create_agent(
        name="迁移校验员",
        role="知识管理员",
        description="校验知识文件迁移",
        persona="谨慎",
        capabilities=["知识管理"],
    )
    team = platform.create_team(
        organization_id="org_jianghu",
        name="迁移校验组",
        purpose="校验 Docker 数据挂载",
        operating_mode="collaborative",
        members=[{"agent_id": agent["id"], "member_role": "leader", "responsibility": "校验路径"}],
    )
    source = platform.attach_team_knowledge_file(
        team["id"], "portable.md", b"# portable\n", "text/markdown"
    )["source"]
    stale_metadata = dict(source["metadata"])
    stale_metadata["managed_path"] = r"D:\old-host\.data\knowledge\content.md"
    stale_metadata["extracted_path"] = r"D:\old-host\.data\knowledge\extracted.txt"
    with platform._connect() as db:
        db.execute(
            "UPDATE knowledge_sources SET uri=?,metadata_json=? WHERE id=?",
            (r"D:\old-host\.data\knowledge\content.md", json.dumps(stale_metadata, ensure_ascii=False), source["id"]),
        )
        db.execute(
            "UPDATE agent_teams SET knowledge_paths_json=? WHERE id=?",
            (json.dumps([r"D:\old-host\.data\knowledge\content.md"]), team["id"]),
        )

    restarted = PlatformStore(str(database_path))
    repaired = restarted.knowledge_source_detail(source["id"])["source"]
    repaired_path = Path(repaired["uri"])
    assert repaired_path.is_file()
    assert repaired_path.is_relative_to((tmp_path / "knowledge").resolve())
    assert repaired["metadata"]["managed_path"] == str(repaired_path)
    assert restarted.get_team(team["id"])["knowledge_paths"] == [str(repaired_path)]


def test_agent_revision_preserves_frozen_workflow_and_continues_memory_and_knowledge(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "agent-version.db"))
    source = platform.attach_organization_knowledge_file(
        "org_jianghu",
        "组织章程.md",
        "# 组织章程\n\n所有交付都必须可追溯。".encode("utf-8"),
        "text/markdown",
        relative_path="公共制度/组织章程.md",
        collection_id="collection_rules",
    )["source"]
    original = platform.create_agent(
        name="顾知行",
        role="知识工程师",
        description="维护组织知识",
        persona="重视来源、权限与历史版本",
        capabilities=["知识治理"],
        skills=[
            {
                "key": "source_review",
                "name": "来源核验",
                "description": "核验事实来源",
                "instructions": "引用正式结论时标注来源。",
                "enabled": True,
            }
        ],
    )
    platform.set_knowledge_bindings("agent", original["id"], [source["id"]])
    platform.add_agent_memory(
        original["id"],
        kind="task_experience",
        title="第一次知识审计",
        content="发现无来源结论必须退回。",
    )
    team = platform.create_team(
        organization_id="org_jianghu",
        name="知识司",
        purpose="治理公共知识",
        operating_mode="collaborative",
        members=[{"agent_id": original["id"], "member_role": "leader", "responsibility": "负责人"}],
    )
    workflow = platform.create_workflow(
        "知识审计章法",
        "冻结具体人物版本",
        "test",
        {
            "nodes": [
                {
                    "key": "audit",
                    "name": "知识审计",
                    "agent_id": original["id"],
                    "agent_role": original["role"],
                    "team_id": team["id"],
                    "participant_agent_ids": [original["id"]],
                }
            ],
            "edges": [],
            "policies": {},
        },
    )

    revised = platform.revise_agent(
        original["id"],
        name="顾知行",
        role="首席知识工程师",
        description="维护大小江湖的知识治理",
        persona="重视来源、权限、历史版本和可撤回授权",
        capabilities=["知识治理", "知识图谱"],
        visibility="private",
        skills=[
            {
                "key": "source_review",
                "name": "来源核验",
                "description": "核验事实来源与授权边界",
                "instructions": "引用正式结论时标注来源与授权作用域。",
                "enabled": True,
            }
        ],
        runtime="openclaw",
        memory_policy={"enabled": True, "max_prompt_items": 12, "write_after_task": True},
        knowledge_source_ids=None,
    )

    assert revised["family_id"] == original["id"]
    assert revised["version"] == "1.1.0"
    assert revised["runtime"] == "openclaw"
    assert revised["skills"][0]["name"] == "来源核验"
    assert revised["knowledge_source_ids"] == [source["id"]]
    assert revised["memory_count"] == 1
    assert platform.list_agent_memories(revised["id"])[0]["title"] == "第一次知识审计"
    assert platform.get_team(team["id"])["members"][0]["id"] == revised["id"]
    assert platform.get_workflow(workflow["id"])["definition"]["nodes"][0]["agent_id"] == original["id"]

    runtime = OpenClawRuntime(tmp_path / "openclaw")
    assert runtime._workspace(original) != runtime._workspace(revised)
    assert runtime.for_run("run-one").state_root != runtime.for_run("run-two").state_root


def test_openclaw_sync_registers_all_same_endpoint_models_for_per_turn_override(tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "openclaw-models")
    result = runtime.sync(
        agents=[],
        memories_by_agent={},
        model_config={
            "provider": "openai-responses",
            "base_url": "https://example.test",
            "model": "gpt-medium",
            "token": "shared-token",
            "tier": "medium",
        },
        model_configs=[
            {
                "provider": "openai-responses",
                "base_url": "https://example.test",
                "model": "gpt-high",
                "token": "shared-token",
                "tier": "high",
            },
            {
                "provider": "openai-responses",
                "base_url": "https://other.example",
                "model": "should-not-be-added",
                "token": "shared-token",
                "tier": "low",
            },
        ],
    )
    assert result["models"] == ["jianghu/gpt-medium", "jianghu/gpt-high"]
    config = json.loads((tmp_path / "openclaw-models" / "openclaw.json").read_text(encoding="utf-8"))
    models = config["models"]["providers"]["jianghu"]["models"]
    assert [item["id"] for item in models] == ["gpt-medium", "gpt-high"]


def test_big_realm_knowledge_is_inherited_and_folder_graph_is_visible(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "knowledge-graph.db"))
    agent = platform.create_agent(
        name="沈观澜",
        role="组织研究员",
        description="读取大江湖公共知识并服务小江湖",
        persona="尊重知识所有权和选择性披露",
        capabilities=["组织研究"],
    )
    team = platform.create_team(
        organization_id="org_jianghu",
        name="东篱研究社",
        purpose="独立完成组织研究",
        operating_mode="collaborative",
        members=[{"agent_id": agent["id"], "member_role": "leader", "responsibility": "主持研究"}],
    )
    realm_source = platform.attach_organization_knowledge_file(
        "org_jianghu",
        "发布门禁.md",
        "# 发布门禁\n\n正式发布必须完成回滚演练。".encode("utf-8"),
        "text/markdown",
        relative_path="制度/研发/发布门禁.md",
        collection_id="realm-folder-upload",
    )["source"]
    team_source = platform.attach_team_knowledge_file(
        team["id"],
        "架构约束.md",
        "# 架构约束\n\n研究社交付必须附带架构决策记录。".encode("utf-8"),
        "text/markdown",
        relative_path="项目甲/架构/架构约束.md",
        collection_id="team-folder-upload",
    )["source"]

    inherited = platform.search_team_knowledge(team["id"], "发布 回滚 演练")
    assert inherited["results"][0]["source_id"] == realm_source["id"]
    graph = platform.knowledge_graph("org_jianghu")
    node_ids = {node["id"] for node in graph["nodes"]}
    assert team["id"] in node_ids
    assert realm_source["id"] in node_ids
    assert team_source["id"] in node_ids
    assert any(node["type"] == "folder" and node["label"] == "制度" for node in graph["nodes"])
    assert any(node["type"] == "folder" and node["label"] == "架构" for node in graph["nodes"])
    assert any(node["type"] == "concept" and "发布门禁" in node["label"] for node in graph["nodes"])
    assert graph["construction"]["chunk_count"] >= 2
    assert graph["construction"]["concept_count"] >= 2
    assert any(edge["type"] == "describes" and edge["evidence"] for edge in graph["edges"])
    assert any(item["type"] == "concept" for item in graph["entity_types"])
    assert any(
        edge["source"] == realm_source["id"]
        and edge["target"] == team["id"]
        and edge["type"] == "inherited_by"
        for edge in graph["edges"]
    )


def test_multiple_big_realms_filter_agents_teams_workflows_and_runs(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "multiple-realms.db"))
    original_agent = platform.list_agents("org_jianghu")[0]
    second_realm = platform.create_organization(name="云海江湖", description="独立的大江湖边界")
    second_agent = platform.create_agent(
        organization_id=second_realm["id"],
        name="顾云舟",
        role="云海召集人",
        description="负责第二个大江湖的目标统筹",
        persona="只在云海江湖的授权边界内行动。",
        capabilities=["目标统筹"],
    )
    second_team = platform.create_team(
        organization_id=second_realm["id"],
        name="云海议事堂",
        purpose="承接云海江湖事务",
        operating_mode="collaborative",
        members=[{"agent_id": second_agent["id"], "member_role": "leader", "responsibility": "召集"}],
    )
    with pytest.raises(ValueError, match="team_member_organization_mismatch"):
        platform.create_team(
            organization_id=second_realm["id"],
            name="越界队伍",
            purpose="验证隔离",
            operating_mode="collaborative",
            members=[{"agent_id": original_agent["id"], "member_role": "member", "responsibility": "不应加入"}],
        )
    workflow = platform.create_workflow(
        "云海章法",
        "只属于云海江湖",
        source="test",
        organization_id=second_realm["id"],
        definition={
            "nodes": [{"key": "act", "name": "云海行动", "agent_id": second_agent["id"], "team_id": second_team["id"]}],
            "edges": [],
            "policies": {},
        },
    )
    run = platform.create_run(workflow["id"], "执行云海江湖事务")
    assert [item["id"] for item in platform.list_agents(second_realm["id"])] == [second_agent["id"]]
    assert [item["id"] for item in platform.list_teams(second_realm["id"])] == [second_team["id"]]
    assert [item["id"] for item in platform.list_workflows(organization_id=second_realm["id"])] == [workflow["id"]]
    assert [item["id"] for item in platform.list_runs(organization_id=second_realm["id"])] == [run["id"]]
    assert all(item["organization_id"] == "org_jianghu" for item in platform.list_agents("org_jianghu"))
    assert platform.get_run(run["id"], organization_id=second_realm["id"])["organization_id"] == second_realm["id"]
    assert platform.get_run(run["id"], organization_id="org_jianghu") is None
    assert all(item["organization_id"] == second_realm["id"] for item in platform.get_run(run["id"])["tasks"])
    assert all(item["organization_id"] == second_realm["id"] for item in platform.get_run(run["id"])["events"])


@pytest.mark.anyio
async def test_team_synthesis_does_not_deadlock_the_event_ledger(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "team-synthesis.db"))
    lead = platform.create_agent(
        name="程观澜",
        role="系统架构师",
        description="整合团队意见并形成正式交付",
        persona="保留分歧并依据证据作出决定",
        capabilities=["架构设计", "团队整合"],
    )
    reviewer = platform.create_agent(
        name="沈知微",
        role="产品负责人",
        description="从业务价值和验收边界提出独立意见",
        persona="重视目标、边界和可验证结果",
        capabilities=["需求分析", "验收设计"],
    )
    team = platform.create_team(
        organization_id="org_jianghu",
        name="托管云转型小队",
        purpose="共同形成 AINative 组织方案",
        operating_mode="collaborative",
        members=[
            {"agent_id": lead["id"], "member_role": "leader", "responsibility": "整合正式方案"},
            {"agent_id": reviewer["id"], "member_role": "member", "responsibility": "独立审查业务边界"},
        ],
    )
    platform.save_model_config(
        config_id=None,
        name="team-synthesis-test",
        provider="openai-responses",
        base_url="https://example.invalid",
        model="test-model",
        token="unit-test-secret",
        active=True,
    )
    workflow = platform.create_workflow(
        "团队合议章法",
        "验证多人独立贡献、公开通信和负责人整合可以完成",
        "test",
        {
            "nodes": [
                {
                    "key": "design",
                    "name": "形成目标组织方案",
                    "purpose": "输出经过团队合议的正式方案",
                    "agent_id": lead["id"],
                    "agent_role": lead["role"],
                    "team_id": team["id"],
                    "participant_agent_ids": [lead["id"], reviewer["id"]],
                }
            ],
            "edges": [],
            "policies": {"max_debate_rounds": 1, "max_parallel_agents": 2},
        },
    )
    run = platform.create_run(workflow["id"], "形成托管云 AINative 目标组织方案")

    class TeamRuntime:
        def sync(self, agents, memories, model_config):
            return {"agent_count": len(agents), "config_path": "isolated-test", "model": "test/test-model"}

        async def message(self, *, agent, prompt, session_key, model_config, timeout_seconds):
            if "message-" in session_key:
                target = reviewer["id"] if agent["id"] == lead["id"] else lead["id"]
                text = json.dumps(
                    {"to_agent_id": target, "message_type": "challenge", "content": "请补充可验证的组织指标。"},
                    ensure_ascii=False,
                )
            elif "synthesis" in session_key:
                text = "正式方案：保留专业单元，按事件动态编组，并用交付周期和返工率验证。"
            else:
                text = f"{agent['name']}的独立贡献：明确职责边界和验收证据。"
            return {
                "id": session_key,
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "openclaw": {"runtime": "team-test"},
            }

    runtime = TeamRuntime()
    monkeypatch.setattr(openclaw_runtime, "for_run", lambda run_id: runtime)
    await asyncio.wait_for(execute_platform_run(platform, run["id"]), timeout=10)

    completed = platform.get_run(run["id"])
    assert completed["status"] == "completed"
    event_types = [event["type"] for event in completed["events"]]
    assert "team.synthesis.started" in event_types
    assert "team.synthesis.completed" in event_types
    assert "run.completed" in event_types
    conclusions = [item for item in completed["artifacts"] if item["title"] == "一页纸结论"]
    assert len(conclusions) == 1
    assert conclusions[0]["task_id"] is None
    assert all(section in conclusions[0]["content"] for section in ["核心发现", "使用边界", "下一步"])


@pytest.mark.anyio
async def test_judge_rejection_reopens_responsible_dag_subgraph(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "loop.db"))
    builder = platform.create_agent(
        name="陆成蹊",
        role="交付工程师",
        description="形成节点交付",
        persona="根据裁判意见完成闭环返工",
        capabilities=["交付实现"],
    )
    judge = platform.create_agent(
        name="谢衡",
        role="独立裁判",
        description="独立验收并定向退回",
        persona="不参与创作，只依据验收标准裁决",
        capabilities=["独立验收"],
    )
    platform.save_model_config(
        config_id=None,
        name="loop-test",
        provider="openai-responses",
        base_url="https://example.invalid",
        model="test-model",
        token="unit-test-secret",
        active=True,
    )
    workflow = platform.create_workflow(
        "闭环交付章法",
        "裁判不通过后自动返工并重新裁决",
        "test",
        {
            "nodes": [
                {
                    "key": "deliver",
                    "name": "形成交付",
                    "purpose": "提交包含验收证据的交付",
                    "agent_id": builder["id"],
                    "agent_role": builder["role"],
                },
                {
                    "key": "judge",
                    "name": "独立裁决",
                    "type": "judge",
                    "purpose": "检查交付是否包含验收证据",
                    "agent_id": judge["id"],
                    "agent_role": judge["role"],
                },
            ],
            "edges": [["deliver", "judge"]],
            "policies": {"max_revision_rounds": 2, "max_parallel_agents": 2},
        },
    )
    run = platform.create_run(workflow["id"], "形成一份带可核验证据的完整交付")
    calls = {"deliver": 0, "judge": 0}

    class DeterministicRuntime:
        def sync(self, agents, memories, model_config):
            return {"agent_count": len(agents), "config_path": "isolated-test", "model": "test/test-model"}

        async def message(self, *, agent, prompt, session_key, model_config, timeout_seconds):
            if agent["id"] == builder["id"]:
                calls["deliver"] += 1
                if calls["deliver"] == 1:
                    text = "第一版交付，尚未附验收证据。"
                else:
                    assert "补充可核验的验收证据" in prompt
                    text = "第二版交付：已附测试记录与产物校验值作为验收证据。"
            else:
                calls["judge"] += 1
                if calls["judge"] == 1:
                    text = (
                        '{"verdict":"revise","score":55,"summary":"证据不足",'
                        '"feedback":"补充可核验的验收证据","target_node_keys":["deliver"],'
                        '"acceptance_evidence":[],"remaining_risks":["无法复验"]}'
                    )
                else:
                    text = (
                        '{"verdict":"pass","score":92,"summary":"证据完整",'
                        '"feedback":"","target_node_keys":[],"acceptance_evidence":["测试记录"],'
                        '"remaining_risks":[]}'
                    )
            return {
                "id": session_key,
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "openclaw": {"runtime": "deterministic-test"},
            }

    deterministic_runtime = DeterministicRuntime()
    monkeypatch.setattr(openclaw_runtime, "for_run", lambda run_id: deterministic_runtime)
    await execute_platform_run(platform, run["id"])

    completed = platform.get_run(run["id"])
    assert completed["status"] == "completed"
    assert calls == {"deliver": 2, "judge": 2}
    deliver_task_id = next(task["id"] for task in completed["tasks"] if task["node_key"] == "deliver")
    deliver_artifacts = [item for item in completed["artifacts"] if item["task_id"] == deliver_task_id]
    assert [item["version"] for item in deliver_artifacts] == [1, 2]
    assert [item["status"] for item in deliver_artifacts] == ["superseded", "candidate"]
    event_types = [event["type"] for event in completed["events"]]
    assert "gate.rejected" in event_types
    assert "workflow.loop.created" in event_types
    assert "gate.passed" in event_types
    assert "run.completed" in event_types


@pytest.mark.anyio
async def test_running_run_recovers_completed_artifacts_and_only_reexecutes_unfinished_nodes(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "recovery.db"))
    first_agent = platform.create_agent(
        name="苏砚清",
        role="资料整理师",
        description="整理已确认的事实材料",
        persona="谨慎记录，不覆盖历史",
        capabilities=["资料整理"],
    )
    second_agent = platform.create_agent(
        name="顾行舟",
        role="方案撰写师",
        description="基于上游材料形成方案",
        persona="重视证据和可追溯交付",
        capabilities=["方案撰写"],
    )
    platform.save_model_config(
        config_id=None,
        name="recovery-test",
        provider="openai-responses",
        base_url="https://example.invalid",
        model="test-model",
        token="unit-test-secret",
        active=True,
    )
    workflow = platform.create_workflow(
        "断点续办章法",
        "服务恢复后只执行未完成节点",
        "test",
        {
            "nodes": [
                {
                    "key": "collect",
                    "name": "整理事实",
                    "purpose": "形成事实基线",
                    "agent_id": first_agent["id"],
                    "agent_role": first_agent["role"],
                },
                {
                    "key": "write",
                    "name": "形成方案",
                    "purpose": "使用事实基线形成正式方案",
                    "agent_id": second_agent["id"],
                    "agent_role": second_agent["role"],
                },
            ],
            "edges": [["collect", "write"]],
        },
    )
    run = platform.create_run(workflow["id"], "完成一份可追溯方案")
    collect_task = next(item for item in run["tasks"] if item["node_key"] == "collect")
    write_task = next(item for item in run["tasks"] if item["node_key"] == "write")
    old_artifact = platform.create_artifact(
        run["id"], collect_task["id"], "workflow_output", "事实基线", "已经确认的事实基线。"
    )
    platform.update_task(
        collect_task["id"], status="completed", output_data={"artifact_id": old_artifact["id"]}
    )
    platform.update_task(write_task["id"], status="running")
    platform.update_run(run["id"], status="running", stage="形成方案", progress=50)
    platform.append_run_event(
        run["id"], "run.started", "system", "首次执行开始", "首次执行在第二个节点中断。"
    )

    calls: list[str] = []

    class RecoveryRuntime:
        def sync(self, agents, memories, model_config):
            return {"agent_count": len(agents), "config_path": "isolated-test", "model": "test/test-model"}

        async def message(self, *, agent, prompt, session_key, model_config, timeout_seconds):
            calls.append(agent["id"])
            assert "已经确认的事实基线" in prompt
            assert "epoch2" in session_key
            return {
                "id": session_key,
                "content": [{"type": "text", "text": "基于已确认事实形成的可追溯正式方案。"}],
                "usage": {"input_tokens": 12, "output_tokens": 8},
                "openclaw": {"runtime": "recovery-test"},
            }

    runtime = RecoveryRuntime()
    monkeypatch.setattr(openclaw_runtime, "for_run", lambda run_id: runtime)
    await execute_platform_run(platform, run["id"])

    recovered = platform.get_run(run["id"])
    assert recovered["status"] == "completed"
    assert calls == [second_agent["id"]]
    assert len([item for item in recovered["artifacts"] if item["task_id"] == collect_task["id"]]) == 1
    assert len([item for item in recovered["artifacts"] if item["task_id"] == write_task["id"]]) == 1
    recovery_event = next(item for item in recovered["events"] if item["type"] == "run.recovered")
    assert recovery_event["payload"]["completed_node_keys"] == ["collect"]
    assert recovery_event["payload"]["interrupted_node_keys"] == ["write"]
    assert recovery_event["payload"]["execution_epoch"] == 2


@pytest.mark.anyio
async def test_agent_action_uses_a_fresh_isolated_retry_before_retrying_the_whole_node(monkeypatch, tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "agent-retry.db"))
    agent = platform.create_agent(
        name="陆行舟",
        role="全栈工程师",
        description="独立实现并验证真实交付",
        persona="遇到瞬时故障时重新建立隔离回合",
        capabilities=["软件开发", "自动化测试"],
    )
    platform.save_model_config(
        config_id=None,
        name="agent-retry-test",
        provider="openai-responses",
        base_url="https://example.invalid",
        model="test-model",
        token="unit-test-secret",
        active=True,
    )
    workflow = platform.create_workflow(
        "人物重试章法",
        "人物瞬时失败后先独立重试",
        "test",
        {
            "nodes": [
                {
                    "key": "deliver",
                    "name": "形成交付",
                    "purpose": "形成经过验证的真实交付",
                    "agent_id": agent["id"],
                    "agent_role": agent["role"],
                    "execution_mode": "document",
                }
            ],
            "edges": [],
        },
    )
    run = platform.create_run(workflow["id"], "完成一项可验证交付")
    session_keys: list[str] = []

    class RetryRuntime:
        def sync(self, agents, memories, model_config):
            return {"agent_count": len(agents), "config_path": "isolated-test", "model": "test/test-model"}

        async def message(self, *, agent, prompt, session_key, model_config, timeout_seconds):
            session_keys.append(session_key)
            if len(session_keys) == 1:
                raise OpenClawRuntimeError("temporary network failure")
            return {
                "id": session_key,
                "content": [{"type": "text", "text": "已完成真实交付并给出验证结果。"}],
                "usage": {"input_tokens": 8, "output_tokens": 6},
                "openclaw": {"runtime": "retry-test"},
            }

    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr(openclaw_runtime, "for_run", lambda run_id: RetryRuntime())
    monkeypatch.setattr("server.app.platform_executor.asyncio.sleep", no_wait)
    await execute_platform_run(platform, run["id"])

    completed = platform.get_run(run["id"])
    assert completed["status"] == "completed"
    assert len(session_keys) == 2
    assert session_keys[0].endswith("agent-attempt1")
    assert session_keys[1].endswith("agent-attempt2")
    retry_event = next(item for item in completed["events"] if item["type"] == "agent.action.retrying")
    assert retry_event["payload"]["agent_id"] == agent["id"]
    assert retry_event["payload"]["next_attempt"] == 2
    assert not any(item["type"] == "agent.action.failed" for item in completed["events"])


def test_run_public_dossier_intervention_and_presence_are_derived(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "dossier.db"))
    agent = platform.create_agent(
        name="顾行舟",
        role="调查员",
        description="调查事实并公开提交证据",
        persona="谨慎、独立、重视来源",
        capabilities=["调查", "证据整理"],
    )
    workflow = platform.create_workflow(
        "调查章法",
        "形成可追溯调查结论",
        "test",
        {
            "nodes": [
                {
                    "key": "investigate",
                    "name": "调查事实",
                    "purpose": "提交事实、证据和风险",
                    "agent_id": agent["id"],
                    "agent_role": agent["role"],
                }
            ],
            "edges": [],
        },
    )
    run = platform.create_run(workflow["id"], "调查一件真实事件")
    task = run["tasks"][0]
    intervention = platform.create_run_intervention(
        run["id"], task_id=task["id"], kind="correction", content="不要把未经证实的传闻当成事实。"
    )
    platform.append_run_event(
        run["id"], "agent.context.prepared", "collaboration", "整备完成", "已装载公共上下文",
        {"task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"]},
    )
    platform.append_run_event(
        run["id"], "agent.action.progress", "execution", "正在核对来源", "已经核对两份公开来源。",
        {"task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"], "content": "已经核对两份公开来源。"},
    )
    platform.append_run_event(
        run["id"], "agent.file.created", "artifact", "新增证据", "evidence.md",
        {"task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"], "path": "evidence.md", "sha256": "abc"},
    )
    platform.append_run_event(
        run["id"], "knowledge.retrieved", "knowledge", "已检索获准知识", "命中一份公开来源。",
        {
            "task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"],
            "matches": [{"source_id": "source_1", "source_name": "公开资料", "locator": "第 1 节", "score": 0.91}],
        },
    )
    platform.append_run_event(
        run["id"], "artifact.validation.started", "validation", "开始校验", "正在核验真实交付。",
        {"task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"]},
    )
    platform.append_run_event(
        run["id"], "agent.rationale.submitted", "private_audit", "提交发起人行动说明", "仅发起人可见。",
        {
            "task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"],
            "visibility": "initiator_only", "share_with_agents": False,
            "content": "事实依据：两份公开来源一致。\n关键取舍：未采用传闻。\n不确定性：仍缺现场记录。\n下一步验证：补充访谈。",
            "raw_chain_of_thought_collected": False,
        },
    )
    snapshot = platform.get_run(run["id"])
    dossier = snapshot["node_dossiers"][task["id"]]
    assert dossier["context"][0]["type"] == "agent.context.prepared"
    assert dossier["knowledge"][0]["payload"]["matches"][0]["source_name"] == "公开资料"
    assert dossier["actions"][0]["payload"]["content"] == "已经核对两份公开来源。"
    assert dossier["files"][0]["payload"]["path"] == "evidence.md"
    assert dossier["initiator_notes"][0]["payload"]["visibility"] == "initiator_only"
    assert dossier["initiator_notes"][0]["payload"]["share_with_agents"] is False
    assert not any(item["type"] == "agent.rationale.submitted" for item in dossier["context"])
    assert not any(item["type"] == "agent.rationale.submitted" for item in dossier["contributions"])
    assert not any(item["type"] == "agent.rationale.submitted" for item in dossier["communications"])
    assert dossier["interventions"][0]["id"] == intervention["id"]
    presence = next(item for item in snapshot["agent_presence"] if item["agent_id"] == agent["id"])
    assert presence["state"] == "validating"
    assert presence["state_label"] == "校验交付中"
    platform.append_run_event(
        run["id"], "agent.action.failed", "execution", "顾行舟行动失败", "自动重试后仍未完成。",
        {
            "task_id": task["id"], "node_key": task["node_key"], "agent_id": agent["id"],
            "error_detail": "temporary network failure", "manual_retry_scope": "node_with_agent_context_reset",
        },
    )
    failed_snapshot = platform.get_run(run["id"])
    failed_presence = next(item for item in failed_snapshot["agent_presence"] if item["agent_id"] == agent["id"])
    assert failed_presence["state"] == "blocked"
    assert failed_presence["state_label"] == "人物行动失败，等待重试"
    assert failed_presence["latest_event"]["type"] == "agent.action.failed"
    platform.update_run(run["id"], status="budget_exhausted", stage="budget_exhausted")
    stopped = platform.get_run(run["id"])
    stopped_presence = next(item for item in stopped["agent_presence"] if item["agent_id"] == agent["id"])
    assert stopped_presence["state"] == "blocked"
    assert stopped_presence["state_label"] == "预算耗尽，等待处理"
    applied = platform.mark_run_interventions_applied([intervention["id"]])
    assert applied[0]["status"] == "applied"
    with pytest.raises(ValueError, match="require_rework_needs_task"):
        platform.create_run_intervention(run["id"], kind="require_rework", content="重新调查")


def test_extract_initiator_note_removes_private_summary_from_public_contribution() -> None:
    response = (
        "这是可以写入公共卷宗的正式结论。\n\n"
        "<initiator_note>\n"
        "事实依据：真实文件与测试结果。\n"
        "关键取舍：选择了可复验方案。\n"
        "不确定性：仍需生产环境验证。\n"
        "下一步验证：运行端到端测试。\n"
        "</initiator_note>"
    )
    public, note = _extract_initiator_note(response)
    assert public == "这是可以写入公共卷宗的正式结论。"
    assert "事实依据：真实文件与测试结果。" in note
    assert "<initiator_note>" not in public

    unchanged, empty = _extract_initiator_note("只有公开结论。")
    assert unchanged == "只有公开结论。"
    assert empty == ""


def test_openclaw_public_action_parser_hides_thinking_and_keeps_tool_evidence(tmp_path) -> None:
    session_file = tmp_path / "session.jsonl"
    secret = "top-secret-token"
    records = [
        {
            "type": "message",
            "timestamp": "2026-08-06T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "private reasoning must stay hidden"},
                    {"type": "text", "text": "我正在运行自动化测试。"},
                    {"type": "toolCall", "id": "call-1", "name": "exec", "arguments": {"command": f"pytest -q --token={secret}"}},
                ],
            },
        },
        {
            "type": "message",
            "timestamp": "2026-08-06T10:00:01Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "call-1",
                "toolName": "exec",
                "content": [{"type": "text", "text": "12 passed"}],
                "details": {"status": "completed", "exitCode": 0, "durationMs": 812, "cwd": str(tmp_path)},
                "isError": False,
            },
        },
    ]
    session_file.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records), encoding="utf-8")
    actions = OpenClawRuntime._extract_public_actions(session_file, [secret])
    serialized = json.dumps(actions, ensure_ascii=False)
    assert "private reasoning" not in serialized
    assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert [item["kind"] for item in actions] == ["progress", "tool_call", "tool_result"]
    assert actions[-1]["exit_code"] == 0
    assert actions[-1]["output"] == "12 passed"


def test_openclaw_publishes_isolated_engineering_submission_and_promotes_complete_tree(tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")
    contributor = {"id": "agent_contributor", "name": "沈青岚", "role": "前端工程师"}
    lead = {"id": "agent_lead", "name": "顾行舟", "role": "技术负责人"}

    contributor_delivery = runtime.workspace_path(contributor) / "delivery"
    contributor_delivery.mkdir(parents=True, exist_ok=True)
    (contributor_delivery / "src").mkdir()
    (contributor_delivery / "src" / "panel.ts").write_text("export const panel = true\n", encoding="utf-8")
    contributor_changes = runtime._workspace_changes({}, runtime._workspace_snapshot(contributor_delivery))

    submission = runtime.publish_workspace_submission(
        agent=contributor,
        changes=contributor_changes,
        destination=runtime.workspace_path(lead) / "collaboration" / "node-build" / contributor["id"],
    )
    assert submission["file_count"] == 1
    assert Path(submission["manifest"]).is_file()
    assert (Path(submission["files_root"]) / "src" / "panel.ts").read_text(encoding="utf-8") == "export const panel = true\n"

    lead_delivery = runtime.workspace_path(lead) / "delivery"
    lead_delivery.mkdir(parents=True, exist_ok=True)
    (lead_delivery / "app.py").write_text("print('ready')\n", encoding="utf-8")
    final_root = tmp_path / "run" / "code"
    final_root.mkdir(parents=True)
    (final_root / "stale.txt").write_text("remove me", encoding="utf-8")
    promoted = runtime.promote_workspace_tree(agent=lead, destination=final_root)
    assert (final_root / "app.py").read_text(encoding="utf-8") == "print('ready')\n"
    assert not (final_root / "stale.txt").exists()
    assert {(item["action"], item["path"]) for item in promoted} == {
        ("created", "app.py"),
        ("deleted", "stale.txt"),
    }


@pytest.mark.anyio
async def test_openclaw_message_streams_public_tool_actions_before_turn_finishes(monkeypatch, tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = {"id": "agent_stream", "name": "林砚", "role": "后端工程师"}
    session_key = "agent:agent_stream:run-live-node-epoch1-loop1-attempt1-delivery"
    sessions_dir = tmp_path / "state" / "agents" / "agent_stream" / "sessions"
    session_file = sessions_dir / "session-live.jsonl"
    callback_seen = threading.Event()
    callback_happened_before_return = {"value": False}

    def fake_run(*args, **kwargs):
        command = args[0]
        assert command[command.index("--model") + 1] == "jianghu/test-model"
        workspace = runtime.workspace_path(agent)
        (workspace / "HEARTBEAT.md").write_text("OpenClaw control file", encoding="utf-8")
        (workspace / "delivery").mkdir(parents=True, exist_ok=True)
        (workspace / "delivery" / "calculator.py").write_text("print(4)", encoding="utf-8")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "sessions.json").write_text(
            json.dumps({session_key: {"sessionId": "session-live", "sessionFile": str(session_file)}}),
            encoding="utf-8",
        )
        first = {
            "type": "message",
            "timestamp": "2026-08-06T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "must remain private"},
                    {"type": "toolCall", "id": "call-live", "name": "exec", "arguments": {"command": "pytest -q"}},
                ],
            },
        }
        session_file.write_text(json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
        callback_happened_before_return["value"] = callback_seen.wait(timeout=2)
        second = {
            "type": "message",
            "timestamp": "2026-08-06T10:00:01Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "call-live",
                "toolName": "exec",
                "content": [{"type": "text", "text": "3 passed"}],
                "details": {"status": "completed", "exitCode": 0, "durationMs": 200},
                "isError": False,
            },
        }
        final = {
            "type": "message",
            "timestamp": "2026-08-06T10:00:02Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "真实代码与测试已完成。"}]},
        }
        with session_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(second, ensure_ascii=False) + "\n")
            handle.write(json.dumps(final, ensure_ascii=False) + "\n")
        payload = {
            "sessionId": "session-live",
            "payloads": [{"text": "真实代码与测试已完成。"}],
            "meta": {"agentMeta": {"sessionId": "session-live"}},
        }
        return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload, ensure_ascii=False), stderr="")

    monkeypatch.setattr(runtime, "_base_command", lambda: ["openclaw-test"])
    monkeypatch.setattr("server.app.openclaw_runtime.subprocess.run", fake_run)
    streamed: list[dict[str, object]] = []

    async def on_action(action):
        streamed.append(action)
        if action.get("kind") == "tool_call":
            callback_seen.set()

    response = await runtime.message(
        agent=agent,
        prompt="真实写代码并运行测试",
        session_key=session_key,
        model_config={"model": "test-model", "token": "secret"},
        timeout_seconds=10,
        on_action=on_action,
        capture_workspace=True,
    )

    assert callback_happened_before_return["value"] is True
    assert [item["kind"] for item in streamed] == ["tool_call", "tool_result", "progress"]
    assert all(item.get("live_emitted") is True for item in response["actions"])
    assert [item["path"] for item in response["file_changes"]] == ["calculator.py"]
    assert "must remain private" not in json.dumps(streamed, ensure_ascii=False)


def test_showcase_assets_are_idempotent_fixed_and_form_a_real_dag(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "showcase-assets.db"))

    first = ensure_showcase_assets(platform)
    second = ensure_showcase_assets(platform)

    assert first["changes"]["created_agent_ids"]
    assert second["changes"]["created_agent_ids"] == []
    assert second["changes"]["baseline_workflow_created"] is False
    assert second["changes"]["multi_workflow_created"] is False
    baseline = second["workflows"]["baseline"]
    multi = second["workflows"]["multi_agent"]
    assert baseline["definition"]["showcase"] == {"case_id": CASE_ID, "variant": "baseline"}
    assert [node["key"] for node in baseline["definition"]["nodes"]] == ["solo_delivery", "judge"]
    assert baseline["definition"]["nodes"][0]["agent_id"] != baseline["definition"]["nodes"][1]["agent_id"]
    assert multi["definition"]["showcase"] == {"case_id": CASE_ID, "variant": "multi_agent"}
    assert ["requirement", "implementation"] in multi["definition"]["edges"]
    assert ["architecture", "implementation"] in multi["definition"]["edges"]
    assert ["implementation", "quality"] in multi["definition"]["edges"]
    assert ["implementation", "red_team"] in multi["definition"]["edges"]
    assert multi["definition"]["nodes"][-1]["type"] == "judge"
    participant_sets = {
        tuple(node.get("participant_agent_ids", []))
        for node in multi["definition"]["nodes"]
        if node.get("type") == "team_task"
    }
    assert len(participant_sets) > 2
    assert max(len(item) for item in participant_sets) < len(second["team"]["members"])


def test_showcase_comparison_uses_real_code_hidden_acceptance_and_evidence(tmp_path) -> None:
    platform = PlatformStore(str(tmp_path / "showcase-metrics.db"))
    assets = ensure_showcase_assets(platform)
    baseline_run = platform.create_run(assets["workflows"]["baseline"]["id"], CASE_TASK)
    multi_run = platform.create_run(assets["workflows"]["multi_agent"]["id"], CASE_TASK)
    comparison = platform.create_showcase_comparison(
        case_id=CASE_ID,
        baseline_run_id=baseline_run["id"],
        multi_run_id=multi_run["id"],
    )

    baseline_code = Path(baseline_run["workspace"]["code"])
    multi_code = Path(multi_run["workspace"]["code"])
    for root in (baseline_code, multi_code):
        (root / "README.md").write_text("# 事件优先级评估器\n\n运行自动化测试。", encoding="utf-8")
        (root / "test_incident_priority.py").write_text("def test_delivery_exists():\n    assert True\n", encoding="utf-8")
    (baseline_code / "incident_priority.py").write_text(
        """def classify_incident(record):
    severity = record['severity']
    users = record['affected_users']
    minutes = record['minutes_open']
    if severity == 'critical' or (severity == 'high' and users >= 100):
        priority = 'P0'
    elif severity == 'high' or (severity == 'medium' and minutes >= 60):
        priority = 'P1'
    elif severity == 'medium':
        priority = 'P2'
    else:
        priority = 'P3'
    return {'incident_id': record['incident_id'], 'priority': priority, 'sla_minutes': {'P0':15,'P1':60,'P2':240,'P3':1440}[priority]}
""",
        encoding="utf-8",
    )
    (multi_code / "incident_priority.py").write_text(
        """VALID = {'low', 'medium', 'high', 'critical'}
SLA = {'P0': 15, 'P1': 60, 'P2': 240, 'P3': 1440}

def classify_incident(record):
    required = ('incident_id', 'severity', 'affected_users', 'minutes_open')
    if not isinstance(record, dict) or any(key not in record for key in required):
        raise ValueError('missing required field')
    severity = record['severity']
    users = record['affected_users']
    minutes = record['minutes_open']
    if severity not in VALID:
        raise ValueError('invalid severity')
    if type(users) is not int or type(minutes) is not int or users < 0 or minutes < 0:
        raise ValueError('invalid numeric field')
    if severity == 'critical' or (severity == 'high' and users >= 100):
        priority = 'P0'
    elif severity == 'high' or (severity == 'medium' and minutes >= 60):
        priority = 'P1'
    elif severity == 'medium':
        priority = 'P2'
    else:
        priority = 'P3'
    return {'incident_id': record['incident_id'], 'priority': priority, 'sla_minutes': SLA[priority]}
""",
        encoding="utf-8",
    )

    for run, risk_text, judge_score, token_count in (
        (baseline_run, "自动化测试与输出结构", 72, 1000),
        (multi_run, "缺字段、非法严重级别、类型错误、负数、边界 100 和 60、输出契约、确定性、自动化测试证据", 96, 2400),
    ):
        fresh = platform.get_run(run["id"])
        assert fresh is not None
        for task in fresh["tasks"]:
            is_judge = task["node_key"] == "judge"
            decision = {
                "verdict": "pass",
                "score": judge_score,
                "summary": "隐藏验收前的独立裁决通过",
                "remaining_risks": [],
            } if is_judge else None
            platform.update_task(task["id"], status="completed", output_data={"decision": decision} if decision else {})
            platform.create_artifact(run["id"], task["id"], "workflow_output", task["node_name"], risk_text)
        platform.append_run_event(
            run["id"],
            "artifact.validation.passed",
            "validation",
            "真实工程校验通过",
            risk_text,
            {
                "engineering": True,
                "code_files": [
                    {"path": "incident_priority.py"},
                    {"path": "README.md"},
                    {"path": "test_incident_priority.py"},
                ],
                "successful_test_count": 1,
                "command_count": 1,
            },
        )
        platform.update_run(run["id"], status="completed", progress=100, stage="completed", token_count=token_count)

    report = comparison_report(platform, comparison)
    assert report["status"] == "completed"
    assert report["baseline"]["hidden_acceptance"]["pass_rate"] < 100
    assert report["multi_agent"]["hidden_acceptance"]["pass_rate"] == 100
    assert report["multi_agent"]["risk_discovery"]["total"] == len(CASE_MANIFEST["risk_topics"])
    assert report["multi_agent"]["risk_discovery"]["rate"] > report["baseline"]["risk_discovery"]["rate"]
    assert report["delta"]["quality_score"] > 0
    assert report["delta"]["token_count"] == 1400
