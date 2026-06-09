from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str


@dataclass
class TokenUsageStats:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StepOutcome:
    data: Any
    next_prompt: str | None = None
    should_exit: bool = False


@dataclass
class WorkingMemoryState:
    history_info: list[str] = field(default_factory=list)
    key_info: str = ""
    related_sop: str = ""
    current_turn: int = 0
