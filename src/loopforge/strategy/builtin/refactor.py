"""Refactor strategy — complexity-driven refactoring loop."""

from loopforge.models import Constraints, Decision, LoopState, RoundResult
from loopforge.strategy.base import (
    ActionPlan,
    ActionResult,
    BaseStrategy,
    EvaluateResult,
)


class RefactorStrategy(BaseStrategy):
    name = "refactor"
    description = "Complexity-driven refactoring — reduce complexity, improve maintainability, keep tests green"

    async def plan(self, state: LoopState) -> ActionPlan:
        return ActionPlan(
            goal="Identify code smells and plan refactoring",
            steps=["Analyze code complexity", "Propose refactoring"],
            reasoning="TODO: implement complexity analysis",
        )

    async def act(self, plan: ActionPlan, state: LoopState) -> ActionResult:
        return ActionResult(success=True)

    async def evaluate(self, result: ActionResult, state: LoopState) -> EvaluateResult:
        return EvaluateResult(score=0.5, raw_output="TODO: complexity metrics")

    async def decide(
        self, score: float, history: list[RoundResult], constraints: Constraints
    ) -> Decision:
        return Decision.STOP if score >= constraints.threshold else Decision.CONTINUE
