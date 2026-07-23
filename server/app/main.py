from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .models import RunEvent, RunSnapshot, RunStatus
from .simulator import run_demo
from .store import store


app = FastAPI(
    title="Agent Arena API",
    description="多智能体协作、攻防、裁决与复盘平台 API",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
