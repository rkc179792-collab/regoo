"""Wires the three agents to one bus, one tool registry, and one memory."""

from __future__ import annotations

from triad.agents import Commander, Predictor, Tracker
from triad.bus import MessageBus
from triad.config import Config
from triad.llm import LLM, build_llm
from triad.memory import Memory
from triad.models import Message, Verdict
from triad.toolkit import build_registry

# Least privilege: the registry is shared, the permissions are not.
TRACKER_TOOLS = ("detect_stack", "git_churn", "run_tests", "run_lint", "dependency_drift")
PREDICTOR_TOOLS = ("git_churn", "todo_scan")
COMMANDER_TOOLS = ("lint_fix", "write_report")


class Crew:
    def __init__(self, config: Config, llm: LLM | None = None) -> None:
        self.config = config
        self.llm = llm or build_llm(config)
        self.registry = build_registry(config)
        self.bus = MessageBus()
        self.memory = Memory(config.state_dir / "history.jsonl")

        shared = {"bus": self.bus, "memory": self.memory, "llm": self.llm, "config": config}
        self.tracker = Tracker(tools=self.registry.view(TRACKER_TOOLS), **shared)
        self.predictor = Predictor(tools=self.registry.view(PREDICTOR_TOOLS), **shared)
        self.commander = Commander(
            tools=self.registry.view(COMMANDER_TOOLS, dry_run=not config.apply), **shared
        )

    def run(self, objective: str = "decide whether this repository is safe to release") -> Verdict:
        self.bus.send(Message("user", "commander", "goal", {"objective": objective}))
        self.bus.run_until_idle()
        if self.commander.verdict is None:
            raise RuntimeError("the Commander finished without a verdict")
        return self.commander.verdict
