import httpx
import pytest

from server.app.main import app
from server.app.models import RunStatus
from server.app.simulator import run_demo
from server.app.store import RunStore


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
async def test_demo_snapshot_has_agents_and_initial_event() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/demo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "draft"
    assert len(payload["run"]["agents"]) == 7
    assert payload["events"][0]["type"] == "run.created"


@pytest.mark.anyio
async def test_missing_run_returns_404() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/runs/run_missing")
    assert response.status_code == 404


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
