"""Core Loop Engine — orchestrates the Plan→Act→Evaluate→Decide cycle."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from datetime import datetime

from loopforge.llm.client import get_llm
from loopforge.models import (
    Constraints,
    Decision,
    LoopState,
    LoopStatus,
    RoundResult,
)
from loopforge.strategy.base import BaseStrategy
from loopforge.strategy.registry import get_strategy


class LoopEngine:
    """Orchestrates one loop from IDLE to DONE/FAILED/CANCELLED."""

    def __init__(self, state: LoopState):
        self.state = state
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused initially
        self._event_queue: asyncio.Queue | None = None

    @property
    def event_queue(self) -> asyncio.Queue | None:
        return self._event_queue

    @event_queue.setter
    def event_queue(self, q: asyncio.Queue):
        self._event_queue = q

    def cancel(self):
        self._cancel_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def _snapshot(self, target_path: str) -> dict[str, str]:
        """Save contents of all files under target_path."""
        snap = {}
        if not target_path:
            return snap
        if os.path.isfile(target_path):
            try:
                with open(target_path) as f:
                    snap[target_path] = f.read()
            except Exception:
                pass
        elif os.path.isdir(target_path):
            for root, _, files in os.walk(target_path):
                for fn in files:
                    fpath = os.path.join(root, fn)
                    try:
                        with open(fpath) as f:
                            snap[fpath] = f.read()
                    except Exception:
                        pass
        return snap

    def _restore_snapshot(self, snap: dict[str, str]):
        """Write snapshot contents back to disk."""
        for fpath, content in snap.items():
            try:
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w") as f:
                    f.write(content)
            except Exception:
                pass

    async def run(self) -> LoopState:
        """Run the loop until done, failed, or cancelled."""
        cfg = self.state.config
        llm = get_llm(model=cfg.llm_model)

        # Load strategy
        strategy = get_strategy(cfg.strategy, llm=llm)

        try:
            while self.state.current_round < cfg.constraints.max_rounds:
                # Check cancellation
                if self._cancel_event.is_set():
                    self.state.status = LoopStatus.CANCELLED
                    break

                # Check pause
                await self._pause_event.wait()

                self.state.current_round += 1
                round_num = self.state.current_round

                await self._emit("round_start", {"round": round_num})

                # ── PLAN ──────────────────────────────────────────
                self.state.status = LoopStatus.PLANNING
                self.state.updated_at = datetime.now().isoformat()

                plan = await strategy.plan(self.state)
                await self._emit("plan", {
                    "round": round_num,
                    "goal": plan.goal,
                    "steps": plan.steps,
                    "reasoning": plan.reasoning,
                })

                # ── ACT ───────────────────────────────────────────
                self.state.status = LoopStatus.ACTING
                self.state.updated_at = datetime.now().isoformat()

                # Snapshot files before acting — used for backtrack
                snapshot = self._snapshot(cfg.target.path)

                result = await strategy.act(plan, self.state)
                await self._emit("act", {
                    "round": round_num,
                    "success": result.success,
                    "actions": [
                        {"desc": a.description, "tool": a.tool, "duration_ms": a.duration_ms}
                        for a in result.actions
                    ],
                })

                if not result.success and result.error:
                    self.state.errors.append(f"Round {round_num}: {result.error}")

                # ── EVALUATE ──────────────────────────────────────
                self.state.status = LoopStatus.EVALUATING
                self.state.updated_at = datetime.now().isoformat()

                eval_result = await strategy.evaluate(result, self.state)

                # ── DECIDE ────────────────────────────────────────
                self.state.status = LoopStatus.DECIDING
                self.state.updated_at = datetime.now().isoformat()

                decision = await strategy.decide(
                    eval_result.score,
                    self.state.rounds,
                    cfg.constraints,
                )

                # Record round
                round_result = RoundResult(
                    round_number=round_num,
                    plan=plan.goal + "\n" + "\n".join(f"- {s}" for s in plan.steps),
                    actions=result.actions,
                    score=eval_result.score,
                    evaluation_output=eval_result.raw_output,
                    decision=decision,
                    tokens_used=llm.total_tokens,
                    started_at=self.state.updated_at,
                    finished_at=datetime.now().isoformat(),
                )
                self.state.rounds.append(round_result)

                if eval_result.score > self.state.best_score:
                    self.state.best_score = eval_result.score

                await self._emit("round_end", {
                    "round": round_num,
                    "score": eval_result.score,
                    "best_score": self.state.best_score,
                    "decision": decision.value,
                })

                # ── Check termination ─────────────────────────────
                if decision == Decision.STOP:
                    self.state.status = LoopStatus.DONE
                    break

                if eval_result.score >= cfg.constraints.threshold:
                    self.state.status = LoopStatus.DONE
                    break

                if decision == Decision.BACKTRACK:
                    # Revert files to pre-round state
                    self._restore_snapshot(snapshot)
                    await self._emit("backtrack", {
                        "round": round_num,
                        "files_restored": len(snapshot),
                    })

        except Exception as e:
            self.state.status = LoopStatus.FAILED
            self.state.errors.append(str(e))
            await self._emit("error", {"round": self.state.current_round, "error": str(e)})

        finally:
            self.state.finished_at = datetime.now().isoformat()
            self.state.updated_at = datetime.now().isoformat()
            if self.state.status not in (
                LoopStatus.DONE,
                LoopStatus.CANCELLED,
                LoopStatus.FAILED,
            ):
                self.state.status = LoopStatus.DONE
            await self._emit("loop_done", {
                "status": self.state.status.value,
                "total_rounds": self.state.current_round,
                "best_score": self.state.best_score,
            })

        return self.state

    async def _emit(self, event: str, data: dict):
        """Push an SSE event to the queue if available."""
        if self._event_queue:
            from loopforge.models import LoopEvent

            await self._event_queue.put(LoopEvent(
                event=event,
                loop_id=self.state.id,
                round_number=self.state.current_round,
                data=data,
            ))
