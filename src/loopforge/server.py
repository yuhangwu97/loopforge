"""FastAPI server — REST API for LoopForge."""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from loopforge.db import delete_loop, init_db, list_loops, load_loop, save_loop
from loopforge.engine import LoopEngine
from loopforge.models import (
    CreateLoopRequest,
    LoopState,
    LoopStatus,
    LoopSummary,
    StrategyInfo,
)
from loopforge.strategy.registry import list_strategies
from loopforge.worker import get_worker

app = FastAPI(
    title="LoopForge",
    description="AI-powered engineering loop engine",
    version="0.1.0",
)


@app.on_event("startup")
async def startup():
    init_db()


# ── Health ───────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Dashboard ─────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard", "index.html")
    with open(dashboard_path) as f:
        return f.read()


# ── Strategies ───────────────────────────────────────────────────────


@app.get("/api/v1/strategies")
async def get_strategies() -> list[StrategyInfo]:
    return [
        StrategyInfo(name=s["name"], description=s["description"], version="0.1.0")
        for s in list_strategies()
    ]


# ── Loops CRUD ───────────────────────────────────────────────────────


@app.post("/api/v1/loops", status_code=201)
async def create_loop(req: CreateLoopRequest) -> dict:
    state = LoopState(config=req.config)
    save_loop(state)

    # Start running in background
    worker = get_worker()
    await worker.start_loop(state)

    return {"id": state.id, "status": state.status.value}


@app.get("/api/v1/loops")
async def get_loops(status: str | None = None) -> list[LoopSummary]:
    loops = list_loops(status=status)
    return [LoopSummary(**l) for l in loops]


@app.get("/api/v1/loops/{loop_id}")
async def get_loop(loop_id: str) -> LoopState:
    state = load_loop(loop_id)
    if not state:
        raise HTTPException(404, "Loop not found")
    return state


@app.post("/api/v1/loops/{loop_id}/pause")
async def pause_loop(loop_id: str) -> dict:
    worker = get_worker()
    worker.pause_loop(loop_id)
    return {"status": "paused"}


@app.post("/api/v1/loops/{loop_id}/resume")
async def resume_loop(loop_id: str) -> dict:
    worker = get_worker()
    worker.resume_loop(loop_id)
    return {"status": "resumed"}


@app.post("/api/v1/loops/{loop_id}/stop")
async def stop_loop(loop_id: str) -> dict:
    worker = get_worker()
    worker.cancel_loop(loop_id)
    return {"status": "cancelled"}


@app.delete("/api/v1/loops/{loop_id}")
async def remove_loop(loop_id: str) -> dict:
    worker = get_worker()
    worker.cancel_loop(loop_id)
    delete_loop(loop_id)
    return {"status": "deleted"}


# ── Events (SSE) ─────────────────────────────────────────────────────


@app.get("/api/v1/loops/{loop_id}/events")
async def loop_events(loop_id: str) -> EventSourceResponse:
    worker = get_worker()
    queue = worker.get_queue(loop_id)

    async def event_stream():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield {
                    "event": event.event,
                    "data": event.model_dump_json(),
                }
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}

    return EventSourceResponse(event_stream())
