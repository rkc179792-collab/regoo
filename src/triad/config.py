"""Run configuration. One frozen object is shared by every agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHURN_DAYS = 14
BASELINE_DAYS = 90


@dataclass(frozen=True)
class Config:
    workdir: Path = Path(".")
    apply: bool = False  # False = dry-run: mutating tools are blocked
    max_rounds: int = 3
    risk_threshold: float = 0.35
    check_deps: bool = True
    llm: str = "offline"  # offline | anthropic
    model: str = "claude-sonnet-5"
    state_dirname: str = ".triad"

    def __post_init__(self) -> None:
        object.__setattr__(self, "workdir", Path(self.workdir).resolve())
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        if not 0 < self.risk_threshold <= 1:
            raise ValueError("risk_threshold must be in (0, 1]")
        if self.llm not in {"offline", "anthropic"}:
            raise ValueError("llm must be 'offline' or 'anthropic'")

    @property
    def state_dir(self) -> Path:
        return self.workdir / self.state_dirname

    @classmethod
    def from_env(cls, **overrides: Any) -> Config:
        """Build a Config from TRIAD_* variables, then apply non-None overrides."""
        values: dict[str, Any] = {}
        if os.getenv("TRIAD_LLM"):
            values["llm"] = os.environ["TRIAD_LLM"]
        if os.getenv("TRIAD_MODEL"):
            values["model"] = os.environ["TRIAD_MODEL"]
        if os.getenv("TRIAD_RISK_THRESHOLD"):
            values["risk_threshold"] = float(os.environ["TRIAD_RISK_THRESHOLD"])
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
