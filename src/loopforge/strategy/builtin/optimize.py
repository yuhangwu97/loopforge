"""Optimize strategy — benchmark-driven performance optimization loop."""

from loopforge.models import Constraints, Decision, LoopState, RoundResult
from loopforge.strategy.base import (
    ActionPlan,
    ActionResult,
    BaseStrategy,
    EvaluateResult,
)


class OptimizeStrategy(BaseStrategy):
    name = "optimize"
    description = "Benchmark-driven performance optimization — profile, optimize, measure, repeat"

    async def plan(self, state: LoopState) -> ActionPlan:
        return ActionPlan(
            goal="Analyze performance and propose optimization",
            steps=["Run benchmark to find bottleneck", "Propose optimization"],
            reasoning="TODO: implement profiling-based planning",
        )

    async def act(self, plan: ActionPlan, state: LoopState) -> ActionResult:
        return ActionResult(success=True)

    async def evaluate(self, result: ActionResult, state: LoopState) -> EvaluateResult:
        return EvaluateResult(score=0.5, raw_output="TODO: benchmark runner")

    async def decide(
        self, score: float, history: list[RoundResult], constraints: Constraints
    ) -> Decision:
        return Decision.STOP if score >= constraints.threshold else Decision.CONTINUE
