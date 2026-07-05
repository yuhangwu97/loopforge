"""Tests for the core Loop Engine with a mock strategy (no LLM required)."""

import pytest

from loopforge.models import (
    Constraints,
    Decision,
    LoopConfig,
    LoopState,
    LoopStatus,
    RoundResult,
    TargetSpec,
)
from loopforge.strategy.base import (
    ActionPlan,
    ActionResult,
    BaseStrategy,
    EvaluateResult,
)


# ── Mock Strategy ────────────────────────────────────────────────────

class MockStrategy(BaseStrategy):
    """A deterministic mock strategy for testing the engine."""

    name = "mock"
    description = "Mock strategy for testing"

    def __init__(self, llm=None, **kwargs):
        super().__init__(llm=llm, **kwargs)
        # Configurable behavior
        self.plan_calls = 0
        self.act_calls = 0
        self.eval_calls = 0
        self.decide_calls = 0
        self.scores = [0.5, 0.7, 0.85, 0.95]  # improving scores
        self.decisions = [Decision.CONTINUE, Decision.CONTINUE, Decision.CONTINUE, Decision.STOP]

    async def plan(self, state: LoopState) -> ActionPlan:
        self.plan_calls += 1
        return ActionPlan(
            goal=f"Mock plan round {state.current_round}",
            steps=[f"Step 1 for round {state.current_round}"],
            reasoning="Mock reasoning",
        )

    async def act(self, plan: ActionPlan, state: LoopState) -> ActionResult:
        self.act_calls += 1
        from loopforge.models import ActionStep
        return ActionResult(
            success=True,
            actions=[ActionStep(
                description=f"Executed {plan.goal}",
                tool="mock_tool",
                input_summary="mock input",
                output_summary="mock output",
                duration_ms=10,
            )],
        )

    async def evaluate(self, result: ActionResult, state: LoopState) -> EvaluateResult:
        self.eval_calls += 1
        idx = min(state.current_round - 1, len(self.scores) - 1)
        return EvaluateResult(
            score=self.scores[idx],
            raw_output=f"Mock evaluation round {state.current_round}",
        )

    async def decide(
        self, score: float, history: list[RoundResult], constraints: Constraints
    ) -> Decision:
        self.decide_calls += 1
        # history is previous rounds (current round not yet appended)
        idx = min(len(history), len(self.decisions) - 1)
        return self.decisions[idx]


# ── Helpers ──────────────────────────────────────────────────────────

def make_state(name="test", strategy="mock", max_rounds=4, threshold=0.9):
    return LoopState(
        config=LoopConfig(
            name=name,
            strategy=strategy,
            target=TargetSpec(path="/tmp/test"),
            constraints=Constraints(
                max_rounds=max_rounds,
                evaluation="echo ok",
                threshold=threshold,
            ),
        ),
    )


# ── Tests ────────────────────────────────────────────────────────────

class TestEngineWithMockStrategy:
    """Test the engine using MockStrategy (no real LLM)."""

    @pytest.mark.asyncio
    async def test_full_run_completes(self, monkeypatch):
        """Engine should complete all rounds and reach DONE."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        # Register mock strategy
        registry.register("mock", MockStrategy)

        state = make_state(max_rounds=4, threshold=0.9)
        engine = LoopEngine(state)
        result = await engine.run()

        assert result.status == LoopStatus.DONE
        assert result.current_round == 4
        assert result.best_score == 0.95
        assert len(result.rounds) == 4
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_stops_at_threshold(self, monkeypatch):
        """Engine should stop when score meets threshold, even if rounds remain."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        registry.register("mock", MockStrategy)

        # Low threshold — should stop after first high score
        state = make_state(max_rounds=10, threshold=0.45)
        engine = LoopEngine(state)
        result = await engine.run()

        # First score is 0.5 >= 0.45, should stop at round 1
        assert result.status == LoopStatus.DONE
        assert result.current_round == 1

    @pytest.mark.asyncio
    async def test_max_rounds_limit(self, monkeypatch):
        """Engine should stop at max_rounds even if threshold not met."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        registry.register("mock", MockStrategy)

        state = make_state(max_rounds=2, threshold=0.99)
        engine = LoopEngine(state)
        result = await engine.run()

        assert result.status == LoopStatus.DONE
        assert result.current_round == 2
        assert result.best_score <= 0.7  # second score

    @pytest.mark.asyncio
    async def test_cancel(self, monkeypatch):
        """Cancel should stop the engine."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        registry.register("mock", MockStrategy)

        state = make_state(max_rounds=10, threshold=0.99)
        engine = LoopEngine(state)
        engine.cancel()  # cancel before running

        result = await engine.run()
        assert result.status == LoopStatus.CANCELLED
        assert result.current_round == 0

    @pytest.mark.asyncio
    async def test_round_results_recorded(self, monkeypatch):
        """Each round should be recorded with plan, actions, and score."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        registry.register("mock", MockStrategy)

        state = make_state(max_rounds=3, threshold=0.99)
        engine = LoopEngine(state)
        result = await engine.run()

        assert len(result.rounds) == 3
        for i, r in enumerate(result.rounds):
            assert r.round_number == i + 1
            assert r.score > 0
            assert r.plan
            assert len(r.actions) > 0

    @pytest.mark.asyncio
    async def test_best_score_tracks_maximum(self, monkeypatch):
        """best_score should always be the maximum across rounds."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        # Strategy that gives decreasing scores (to test best_score is max)
        class DecreasingMock(MockStrategy):
            def __init__(self, llm=None, **kwargs):
                super().__init__(llm=llm, **kwargs)
                self.scores = [0.8, 0.6, 0.4]
                self.decisions = [Decision.CONTINUE, Decision.CONTINUE, Decision.STOP]

        registry.register("decreasing", DecreasingMock)

        state = make_state(strategy="decreasing", max_rounds=3, threshold=0.99)
        engine = LoopEngine(state)
        result = await engine.run()

        assert result.best_score == 0.8  # max of [0.8, 0.6, 0.4]
        assert result.current_round == 3


class TestEngineWithFailure:
    """Test engine behavior when strategy fails."""

    @pytest.mark.asyncio
    async def test_act_failure_recorded(self, monkeypatch):
        """Failed actions should be recorded, engine should continue."""
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        class FailActMock(MockStrategy):
            async def act(self, plan, state):
                return ActionResult(success=False, error="Simulated failure")

        registry.register("fail_act", FailActMock)

        state = make_state(strategy="fail_act", max_rounds=1, threshold=0.99)
        engine = LoopEngine(state)
        result = await engine.run()

        assert result.status == LoopStatus.DONE
        assert "Simulated failure" in result.errors[0]


class TestEventEmission:
    """Test SSE event emission."""

    @pytest.mark.asyncio
    async def test_events_emitted(self, monkeypatch):
        """Engine should push events to the queue when set."""
        import asyncio
        from loopforge.engine import LoopEngine
        from loopforge.strategy import registry

        registry.register("mock", MockStrategy)

        state = make_state(max_rounds=1, threshold=0.99)
        engine = LoopEngine(state)

        queue = asyncio.Queue()
        engine.event_queue = queue

        await engine.run()

        # Should have emitted several events
        events = []
        while not queue.empty():
            events.append(queue.get_nowait().event)

        assert "round_start" in events
        assert "plan" in events
        assert "act" in events
        assert "round_end" in events
        assert "loop_done" in events
