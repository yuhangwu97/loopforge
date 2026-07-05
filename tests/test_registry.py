"""Tests for strategy registry."""

from loopforge.strategy.registry import list_strategies, get_strategy, register
from loopforge.strategy.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    name = "dummy"
    description = "Dummy for testing"

    async def plan(self, state):
        from loopforge.strategy.base import ActionPlan
        return ActionPlan(goal="dummy", steps=[])

    async def act(self, plan, state):
        from loopforge.strategy.base import ActionResult
        return ActionResult(success=True)

    async def evaluate(self, result, state):
        from loopforge.strategy.base import EvaluateResult
        return EvaluateResult(score=1.0)

    async def decide(self, score, history, constraints):
        from loopforge.models import Decision
        return Decision.STOP


class TestRegistry:
    def test_list_builtins(self):
        strategies = list_strategies()
        names = {s["name"] for s in strategies}
        assert "fix" in names
        assert "optimize" in names
        assert "refactor" in names

    def test_get_builtin(self):
        s = get_strategy("fix", llm=None)
        assert isinstance(s, BaseStrategy)
        assert s.name == "fix"

    def test_get_unknown_raises(self):
        try:
            get_strategy("nonexistent", llm=None)
            assert False, "Should have raised"
        except ValueError as e:
            assert "nonexistent" in str(e)

    def test_register_custom(self):
        register("dummy", DummyStrategy)
        s = get_strategy("dummy", llm=None)
        assert isinstance(s, DummyStrategy)
        assert s.name == "dummy"
