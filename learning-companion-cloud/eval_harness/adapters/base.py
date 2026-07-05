from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class EvalResult:
    case_id: str
    agent: str
    passed: bool
    score: float
    metrics: dict[str, float] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


class AgentAdapter(Protocol):
    name: str

    def reset(self) -> None:
        ...

    def run_case(self, case: dict[str, Any]) -> EvalResult:
        ...
