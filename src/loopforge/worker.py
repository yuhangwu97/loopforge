"""Background worker — manages running loops.

Supports two backends:
- In-process (asyncio tasks) — always available, no external dependencies
- Celery + Redis — survives restarts, scales across workers
"""

from __future__ import annotations

import asyncio

from loopforge.db import save_loop
from loopforge.engine import LoopEngine
from loopforge.models import LoopState


class LoopWorker:
    """Manages background loop execution."""

    def __init__(self):
        self._engines: dict[str, LoopEngine] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._use_celery: bool | None = None

    @property
    def use_celery(self) -> bool:
        """Check if Celery+Redis is available."""
        if self._use_celery is None:
            try:
                from loopforge.celery_app import is_redis_available

                self._use_celery = is_redis_available()
            except Exception:
                self._use_celery = False
        return self._use_celery

    def get_queue(self, loop_id: str) -> asyncio.Queue:
        if loop_id not in self._queues:
            self._queues[loop_id] = asyncio.Queue()
        return self._queues[loop_id]

    async def start_loop(self, state: LoopState):
        """Start executing a loop in the background.

        Dispatches to Celery if Redis is available, otherwise runs in-process.
        """
        if self.use_celery:
            await self._dispatch_celery(state)
        else:
            self._run_in_process(state)

    async def _dispatch_celery(self, state: LoopState):
        """Send task to Celery worker."""
        from loopforge.celery_app import run_loop_task

        # Save state so the worker can load it
        save_loop(state)

        # Dispatch to Celery (non-blocking)
        run_loop_task.delay(state.id)

    def _run_in_process(self, state: LoopState):
        """Run the loop in this process (fallback mode)."""
        loop_id = state.id
        engine = LoopEngine(state)
        engine.event_queue = self.get_queue(loop_id)
        self._engines[loop_id] = engine

        task = asyncio.create_task(self._run_loop(engine, loop_id))
        self._tasks[loop_id] = task

    async def _run_loop(self, engine: LoopEngine, loop_id: str):
        """Run the loop and persist results."""
        try:
            state = await engine.run()
        except Exception as e:
            state = engine.state
            state.errors.append(str(e))
        finally:
            save_loop(state)
            self._engines.pop(loop_id, None)
            self._tasks.pop(loop_id, None)

    def cancel_loop(self, loop_id: str):
        engine = self._engines.get(loop_id)
        if engine:
            engine.cancel()

    def pause_loop(self, loop_id: str):
        engine = self._engines.get(loop_id)
        if engine:
            engine.pause()

    def resume_loop(self, loop_id: str):
        engine = self._engines.get(loop_id)
        if engine:
            engine.resume()


# Global singleton
_worker: LoopWorker | None = None


def get_worker() -> LoopWorker:
    global _worker
    if _worker is None:
        _worker = LoopWorker()
    return _worker
