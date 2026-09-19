from __future__ import annotations

import time
from dataclasses import asdict

from triad.agents.base import Agent
from triad.config import CHURN_DAYS
from triad.models import Check, Message, Snapshot


class Tracker(Agent):
    """Observes the repository and reports facts. It never interprets and never changes anything."""

    name = "tracker"

    def on_observe(self, message: Message) -> None:
        round_no: int = message.payload["round"]
        stacks = self.tools.call("detect_stack").data.get("stacks", [])

        checks = {
            "tests": self._check("tests", "run_tests"),
            "lint": self._check("lint", "run_lint"),
        }
        if self.config.check_deps:
            checks["deps"] = self._check("deps", "dependency_drift")

        churn: list[dict] = []
        result = self.tools.call("git_churn", days=CHURN_DAYS, top=15)
        if result.ok and result.data["status"] == "pass":
            churn = result.data["files"]
            checks["churn"] = Check(
                "churn", "pass", result.data["detail"], {"commits": result.data["commits"]}
            )
        else:
            checks["churn"] = Check("churn", "skipped", result.error or result.data["detail"])

        snapshot = Snapshot(round_no, time.time(), stacks, checks, churn)
        self.memory.record("snapshot", asdict(snapshot))
        self.send("predictor", "snapshot", snapshot=snapshot)

    def _check(self, name: str, tool: str) -> Check:
        result = self.tools.call(tool)
        if not result.ok:
            return Check(name, "skipped", f"tool error: {result.error}")
        data = result.data
        return Check(name, data["status"], data.get("detail", ""), data.get("metrics", {}))
