"""Background worker — manages running loops."""

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

    def get_queue(self, loop_id: str) -> asyncio.Queue:
        if loop_id not in self._queues:
            self._queues[loop_id] = asyncio.Queue()
        return self._queues[loop_id]

    async def start_loop(self, state: LoopState):
        """Start executing a loop in the background."""
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
            # Cleanup
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
