"""Tests for data models."""

import json
from loopforge.models import (
    LoopConfig,
    LoopState,
    LoopStatus,
    TargetSpec,
    Constraints,
    RoundResult,
    Decision,
    CreateLoopRequest,
    new_id,
)


class TestLoopConfig:
    def test_defaults(self):
        cfg = LoopConfig(name="test", strategy="fix")
        assert cfg.name == "test"
        assert cfg.strategy == "fix"
        assert cfg.constraints.max_rounds == 10
        assert cfg.constraints.threshold == 0.9
        assert cfg.llm_model == "claude-sonnet-5"

    def test_serialization(self):
        cfg = LoopConfig(
            name="test",
            strategy="optimize",
            target=TargetSpec(path="./src", language="python"),
            constraints=Constraints(max_rounds=3, evaluation="pytest && python bench.py"),
        )
        d = cfg.model_dump()
        assert d["name"] == "test"
        assert d["target"]["path"] == "./src"
        assert d["constraints"]["max_rounds"] == 3

        # Round-trip
        cfg2 = LoopConfig.model_validate(d)
        assert cfg2 == cfg


class TestLoopState:
    def test_initial_state(self):
        state = LoopState(
            config=LoopConfig(name="test", strategy="fix"),
        )
        assert state.status == LoopStatus.IDLE
        assert state.current_round == 0
        assert state.best_score == 0.0
        assert state.rounds == []
        assert state.errors == []

    def test_id_generation(self):
        id1 = new_id()
        id2 = new_id()
        assert len(id1) == 12
        assert id1 != id2


class TestRoundResult:
    def test_serialization(self):
        r = RoundResult(
            round_number=1,
            plan="Fix syntax error",
            score=0.85,
            decision=Decision.CONTINUE,
        )
        d = r.model_dump()
        assert d["round_number"] == 1
        assert d["score"] == 0.85
        assert d["decision"] == "continue"


class TestCreateLoopRequest:
    def test_deserialization(self):
        body = {
            "config": {
                "name": "my-loop",
                "strategy": "fix",
                "target": {"path": "./src"},
                "constraints": {"max_rounds": 5, "evaluation": "pytest"},
            }
        }
        req = CreateLoopRequest.model_validate(body)
        assert req.config.name == "my-loop"
        assert req.config.constraints.max_rounds == 5
