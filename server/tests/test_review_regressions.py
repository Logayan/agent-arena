import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from server.app.main import app
from server.app.openclaw_runtime import OpenClawRuntimeError
from server.app.platform_store import PlatformStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def platform(monkeypatch, tmp_path):
    store = PlatformStore(str(tmp_path / "regression.db"))
    monkeypatch.setattr("server.app.main.platform_store", store)
    return store


@pytest.mark.anyio
@pytest.mark.parametrize("preferred_role", [None, "风险审计师"])
async def test_agent_generation_scopes_reuse_and_prompt(platform, monkeypatch, preferred_role):
    foreign = platform.create_agent(name="异域审计员", role="风险审计师", description="异域私有说明",
                                   persona="谨慎", capabilities=["风险审计"])
    realm = platform.create_organization(name="新江湖", description="隔离人物")
    local = platform.create_agent(name="本地分析员", role="数据分析师", description="本地说明",
                                 persona="审慎", capabilities=["数据分析"], organization_id=realm["id"])
    generated = {"name": "新任审计员", "role": "风险审计师", "description": "负责风险审计",
                 "persona": "独立审慎", "capabilities": ["风险审计"]}
    prompts = []

    async def json_message(prompt, **kwargs):
        prompts.append(json.loads(prompt))
        return generated

    monkeypatch.setattr("server.app.main.configured_llm", lambda: SimpleNamespace(model="test", json_message=json_message))
    payload = {"organization_id": realm["id"], "requirement": "寻找风险审计人员",
               "preferred_role": preferred_role, "required_capabilities": ["风险审计"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/platform/agents/generate", json=payload)
        assert response.status_code == 200
        created = response.json()["agent"]
        assert created["id"] != foreign["id"]
        assert created["organization_id"] == realm["id"]
        assert [person["name"] for person in prompts[0]["existing_agents"]] == [local["name"]]
        again = await client.post("/api/platform/agents/generate", json=payload)
        assert again.status_code == 200
        assert again.json()["agent"]["id"] == created["id"]
        assert again.json()["generation"]["mode"] == "reused"


@pytest.mark.anyio
async def test_unknown_realm_does_not_call_model(platform, monkeypatch):
    model = Mock(side_effect=AssertionError("must reject before model access"))
    monkeypatch.setattr("server.app.main.configured_llm", model)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/platform/agents/generate", json={"organization_id": "missing", "requirement": "寻找分析员"})
    assert response.status_code == 404
    model.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("name,purpose,expected_name,expected_description", [
    ("  制造研发中心  ", "  专注光学研发  ", "制造研发中心", "专注光学研发"),
    ("", "", "说明第一行", "说明第一行\n说明第二行"),
    ("   ", "   ", "说明第一行", "说明第一行\n说明第二行"),
])
async def test_large_organization_preserves_explicit_fields(platform, name, purpose, expected_name, expected_description):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/platform/organizations/generate", json={
            "world_type": "large", "name": name, "purpose": purpose, "intent": "说明第一行\n说明第二行"})
    assert response.status_code == 200
    organization = response.json()["organization"]
    persisted = next(item for item in platform.list_organizations() if item["id"] == organization["id"])
    assert persisted["name"] == expected_name
    assert persisted["description"] == expected_description


@pytest.fixture
def failed_run(platform):
    agent = platform.create_agent(name="执行员", role="执行者", description="负责执行", persona="审慎", capabilities=["任务执行"])
    workflow = platform.create_workflow("核验流程", "重试核验", "test", {
        "nodes": [{"key": "check", "name": "检查", "agent_id": agent["id"], "agent_role": agent["role"]}],
        "edges": [], "policies": {}})
    run = platform.create_run(workflow["id"], "核验失败重试")
    platform.update_run(run["id"], status="failed", stage="failed")
    commission = platform.create_company_task(organization_id="org_jianghu", title="核验委托", description="核验重试关联")
    platform.link_company_task(commission["id"], workflow_id=workflow["id"], run_id=run["id"])
    return run, commission


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["runtime", "model", "sync"])
async def test_failed_retry_preparation_has_no_persistent_side_effects(platform, failed_run, monkeypatch, failure):
    run, commission = failed_run
    runtime = SimpleNamespace(health=lambda: {"available": failure != "runtime", "error": "test unavailable"},
                              sync=Mock(side_effect=OpenClawRuntimeError("test sync failure")))
    monkeypatch.setattr("server.app.main.openclaw_runtime", runtime)
    monkeypatch.setattr(platform, "get_active_model_config", lambda **kwargs: None if failure == "model" else {"model": "test"})
    schedule = Mock(side_effect=AssertionError("must not schedule failed preparation"))
    monkeypatch.setattr("server.app.main.schedule_platform_execution", schedule)
    with platform._connect() as db:
        before = db.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.post(f"/api/platform/runs/{run['id']}/retry", json={})
            assert response.status_code == 503
    with platform._connect() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == before
    assert platform.get_run(run["id"])["status"] == "failed"
    assert next(c for c in platform.list_company_tasks() if c["id"] == commission["id"])["run_id"] == run["id"]
    schedule.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("targeted", [False, True])
async def test_successful_retry_prepares_then_creates_and_links(platform, failed_run, monkeypatch, targeted):
    run, commission = failed_run
    order = []

    def prepare(source):
        with platform._connect() as db:
            assert db.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == 1
        assert source["id"] == run["id"]
        order.append("prepared")
        return {"available": True}

    def schedule(run_id):
        assert order == ["prepared"]
        assert platform.get_run(run_id)["run_version"] == 2
        order.append("scheduled")

    monkeypatch.setattr("server.app.main.prepare_openclaw_run", prepare)
    monkeypatch.setattr("server.app.main.schedule_platform_execution", schedule)
    payload = {"from_task_id": run["tasks"][0]["id"]} if targeted else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/platform/runs/{run['id']}/retry", json=payload)
    assert response.status_code == 200
    retried = response.json()["run"]
    assert retried["id"] != run["id"]
    assert order == ["prepared", "scheduled"]
    assert next(c for c in platform.list_company_tasks() if c["id"] == commission["id"])["run_id"] == retried["id"]


@pytest.mark.anyio
async def test_invalid_retry_rejected_before_runtime_preparation(platform, failed_run, monkeypatch):
    run, _ = failed_run
    prepare = Mock(side_effect=AssertionError("must validate before runtime preparation"))
    monkeypatch.setattr("server.app.main.prepare_openclaw_run", prepare)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        bad_task = await client.post(f"/api/platform/runs/{run['id']}/retry", json={"from_task_id": "missing"})
        assert bad_task.status_code == 409
        assert bad_task.json()["detail"] == "retry_task_not_found"
        platform.update_run(run["id"], status="completed", stage="completed")
        terminal = await client.post(f"/api/platform/runs/{run['id']}/retry", json={})
        assert terminal.status_code == 409
        assert terminal.json()["detail"] == "run_is_not_retryable"
    prepare.assert_not_called()