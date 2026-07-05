"""Shared types for LLM client and providers (no circular imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    stop_reason: str = ""


@dataclass
class LLMStreamChunk:
    text: str
    index: int = 0
