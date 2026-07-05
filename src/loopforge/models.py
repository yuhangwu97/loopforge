"""Pydantic models for LoopForge — loops, rounds, strategies, and configuration."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── IDs ──────────────────────────────────────────────────────────────

def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Loop State Machine ───────────────────────────────────────────────

class LoopStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    ACTING = "acting"
    EVALUATING = "evaluating"
    DECIDING = "deciding"
    DONE = "done"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Decision(str, Enum):
    CONTINUE = "continue"
    BACKTRACK = "backtrack"
    CHANGE_STRATEGY = "change_strategy"
    STOP = "stop"


# ── Target Specification ─────────────────────────────────────────────

class TargetSpec(BaseModel):
    """What the loop should operate on."""
    type: str = "code"               # code | file | project | url
    path: str = ""                   # file path or directory
    language: str | None = None      # python, javascript, sql, ...
    glob: str | None = None          # file pattern, e.g. "**/*.py"
    extra: dict[str, Any] = Field(default_factory=dict)


# ── Constraints ──────────────────────────────────────────────────────

class Constraints(BaseModel):
    """Limits and evaluation rules for a loop."""
    max_rounds: int = 10
    max_tokens_per_round: int = 50000
    max_total_tokens: int = 500000
    evaluation: str = "pytest"       # shell command that returns exit code + stdout
    threshold: float = 0.9           # 0-1, stop when score >= threshold
    sandbox: bool = False            # run in docker container
    timeout_per_round: int = 300     # seconds
    allow_git_commit: bool = False   # whether the agent can git commit


# ── Loop Configuration ───────────────────────────────────────────────

class LoopConfig(BaseModel):
    """Full configuration for creating a new loop."""
    name: str
    strategy: str = "fix"            # strategy name (registered plugin)
    target: TargetSpec = Field(default_factory=TargetSpec)
    constraints: Constraints = Field(default_factory=Constraints)
    llm_model: str = "claude-sonnet-5"
    llm_effort: str = "medium"       # low | medium | high | xhigh | max
    schedule: str | None = None      # cron expression, or None for one-shot
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Round Records ────────────────────────────────────────────────────

class ActionStep(BaseModel):
    """A single action taken within a round."""
    description: str
    tool: str                        # e.g. "write_file", "run_shell", "llm_call"
    input_summary: str
    output_summary: str
    duration_ms: int
    error: str | None = None


class RoundResult(BaseModel):
    """The result of one complete loop round."""
    id: str = Field(default_factory=new_id)
    round_number: int
    plan: str                        # LLM-generated plan for this round
    actions: list[ActionStep] = Field(default_factory=list)
    score: float = 0.0               # 0-1 evaluation score
    evaluation_output: str = ""      # raw output from evaluation command
    decision: Decision = Decision.CONTINUE
    tokens_used: int = 0
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""


class LoopState(BaseModel):
    """Runtime state of a loop, persisted in DB."""
    id: str = Field(default_factory=new_id)
    config: LoopConfig
    status: LoopStatus = LoopStatus.IDLE
    current_round: int = 0
    best_score: float = 0.0
    rounds: list[RoundResult] = Field(default_factory=list)
    total_tokens: int = 0
    errors: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""


# ── API Request/Response ─────────────────────────────────────────────

class CreateLoopRequest(BaseModel):
    config: LoopConfig


class LoopSummary(BaseModel):
    """Lightweight loop info for list endpoints."""
    id: str
    name: str
    strategy: str
    status: LoopStatus
    current_round: int
    best_score: float
    total_tokens: int
    created_at: str


class StrategyInfo(BaseModel):
    """Metadata about a registered strategy."""
    name: str
    description: str
    version: str
    author: str = ""
    homepage: str = ""


class LoopEvent(BaseModel):
    """SSE event emitted during loop execution."""
    event: str                       # round_start, action, evaluate, round_end, loop_done
    loop_id: str
    round_number: int
    data: dict[str, Any] = Field(default_factory=dict)
