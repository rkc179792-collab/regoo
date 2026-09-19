"""Typed data exchanged between the agents."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Status = Literal["pass", "warn", "fail", "skipped"]
Decision = Literal["GO", "HOLD"]


@dataclass(frozen=True)
class Message:
    sender: str
    recipient: str
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    ts: float = field(default_factory=time.time)


@dataclass
class Check:
    """One observed signal, for example the test run or the lint run."""

    name: str
    status: Status
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    """Everything the Tracker saw in one observation round."""

    round: int
    ts: float
    stacks: list[str]
    checks: dict[str, Check]
    churn: list[dict[str, Any]]  # [{"path": str, "commits": int}], most changed first


@dataclass(frozen=True)
class Driver:
    name: str
    weight: float
    severity: float  # 0..1
    evidence: str

    @property
    def contribution(self) -> float:
        return self.weight * self.severity


@dataclass
class Forecast:
    round: int
    base_risk: float  # weighted drivers, before the trend term
    risk: float  # base_risk plus the trend term, clipped to 0..1
    level: str  # low | moderate | high
    drivers: list[Driver]
    hotspots: list[dict[str, Any]]
    narrative: str = ""


@dataclass(frozen=True)
class Action:
    tool: str
    args: dict[str, Any]
    reason: str
    mutating: bool = False


@dataclass
class Verdict:
    decision: Decision
    risk: float
    level: str
    rounds: int
    executed: list[dict[str, Any]]
    planned: list[dict[str, Any]]
    blockers: list[str]
    advisories: list[str]
    summary: str
    report_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
