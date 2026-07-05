"""Celery app and tasks for LoopForge — optional, requires Redis."""

from __future__ import annotations

import asyncio
import os

from celery import Celery

REDIS_URL = os.getenv("LOOPFORGE_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "loopforge",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="loopforge.run_loop", bind=True)
def run_loop_task(self, loop_id: str):
    """Celery task: run a loop to completion, persist results."""
    from loopforge.db import load_loop, save_loop
    from loopforge.engine import LoopEngine

    state = load_loop(loop_id)
    if not state:
        return {"error": f"Loop {loop_id} not found"}

    engine = LoopEngine(state)

    try:
        result = asyncio.run(engine.run())
        save_loop(result)
        return {
            "loop_id": loop_id,
            "status": result.status.value,
            "rounds": result.current_round,
            "best_score": result.best_score,
        }
    except Exception as e:
        state.errors.append(str(e))
        save_loop(state)
        raise


def is_redis_available() -> bool:
    """Check if Redis is reachable."""
    try:
        import redis

        r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2)
        r.ping()
        return True
    except Exception:
        return False
