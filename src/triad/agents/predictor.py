from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from triad.agents.base import Agent
from triad.config import BASELINE_DAYS, CHURN_DAYS
from triad.models import Check, Driver, Forecast, Message, Snapshot

WEIGHTS = {"tests": 0.40, "lint": 0.15, "churn": 0.20, "deps": 0.10, "todos": 0.05, "trend": 0.10}

NARRATOR_PROMPT = (
    "You are a release-risk analyst. Write two plain sentences explaining the forecast. "
    "Use only the numbers and names in the data. Do not invent causes."
)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _level(risk: float) -> str:
    return "low" if risk < 0.25 else "moderate" if risk < 0.5 else "high"


def _tests_severity(check: Check | None) -> float:
    if check is None or check.status == "skipped":
        return 0.3  # no test signal is itself a risk
    return 1.0 if check.status == "fail" else 0.0


def _lint_severity(check: Check | None) -> float:
    if check is None or check.status == "pass":
        return 0.0
    if check.status == "skipped":
        return 0.1
    issues = check.metrics.get("issues")
    return 0.6 if issues is None else _clip(0.3 + issues / 40)


def _deps_severity(check: Check | None) -> float:
    if check is None or check.status == "skipped":
        return 0.0
    return _clip(check.metrics.get("outdated", 0) / 20)


def _hotspots(
    snapshot: Snapshot, todo_by_file: dict[str, int], baseline: dict[str, int]
) -> list[dict[str, Any]]:
    spots = []
    for entry in snapshot.churn[:5]:
        commits = entry["commits"]
        if commits < 3:
            continue
        # Commits before the recent window, scaled to a window of the same length.
        prior = max(baseline.get(entry["path"], commits) - commits, 0)
        prior_rate = prior * CHURN_DAYS / (BASELINE_DAYS - CHURN_DAYS)
        spots.append(
            {
                "path": entry["path"],
                "commits": commits,
                "todos": todo_by_file.get(entry["path"], 0),
                "accelerating": bool(baseline) and commits >= 2 * max(prior_rate, 1.0),
            }
        )
    return spots


def compute_forecast(
    snapshot: Snapshot,
    *,
    todo_by_file: dict[str, int],
    baseline_commits: dict[str, int],
    prev_base_risk: float | None,
) -> Forecast:
    """Pure scoring function: the same inputs always give the same forecast."""
    tests, lint, deps = (snapshot.checks.get(k) for k in ("tests", "lint", "deps"))
    hotspots = _hotspots(snapshot, todo_by_file, baseline_commits)
    top3 = sum(f["commits"] for f in snapshot.churn[:3])
    hot_todos = sum(h["todos"] for h in hotspots)

    drivers = [
        Driver("tests", WEIGHTS["tests"], _tests_severity(tests),
               tests.detail if tests else "no test signal"),
        Driver("lint", WEIGHTS["lint"], _lint_severity(lint),
               lint.detail if lint else "no lint signal"),
        Driver("churn", WEIGHTS["churn"], _clip(top3 / 15),
               f"top 3 files changed {top3} times in {CHURN_DAYS} days"),
        Driver("deps", WEIGHTS["deps"], _deps_severity(deps),
               deps.detail if deps else "not checked"),
        Driver("todos", WEIGHTS["todos"], _clip(hot_todos / 5),
               f"{hot_todos} TODO/FIXME marker(s) in high-churn files"),
    ]  # fmt: skip
    base = sum(d.contribution for d in drivers)

    trend = 0.0 if prev_base_risk is None else _clip((base - prev_base_risk) / 0.2)
    prev_text = (
        "no earlier forecast" if prev_base_risk is None else f"previous base {prev_base_risk:.2f}"
    )
    drivers.append(Driver("trend", WEIGHTS["trend"], trend, f"base {base:.2f} vs {prev_text}"))

    risk = _clip(base + WEIGHTS["trend"] * trend)
    return Forecast(snapshot.round, round(base, 4), round(risk, 4), _level(risk), drivers, hotspots)


def template_narrative(forecast: Forecast) -> str:
    top = max(forecast.drivers, key=lambda d: d.contribution)
    if top.contribution == 0:
        return f"Release risk is {forecast.level} ({forecast.risk:.2f}) and no driver contributes."
    text = (
        f"Release risk is {forecast.level} ({forecast.risk:.2f}). "
        f"The largest driver is {top.name}: {top.evidence}."
    )
    if forecast.hotspots:
        h = forecast.hotspots[0]
        text += f" Hotspot: {h['path']} ({h['commits']} commits, {h['todos']} TODO markers)."
    return text


class Predictor(Agent):
    """Turns the Tracker's facts into a risk forecast. It reads history but never runs checks."""

    name = "predictor"

    def on_snapshot(self, message: Message) -> None:
        snapshot: Snapshot = message.payload["snapshot"]

        todos = self.tools.call("todo_scan")
        todo_by_file = todos.data.get("by_file", {}) if todos.ok else {}

        history = self.tools.call("git_churn", days=BASELINE_DAYS, top=200)
        baseline = {f["path"]: f["commits"] for f in history.data["files"]} if history.ok else {}

        previous = self.memory.last("forecast")
        prev_base = previous["data"]["base_risk"] if previous else None

        forecast = compute_forecast(
            snapshot,
            todo_by_file=todo_by_file,
            baseline_commits=baseline,
            prev_base_risk=prev_base,
        )
        facts = json.dumps(asdict(forecast), default=str)
        forecast.narrative = self.llm.complete(NARRATOR_PROMPT, facts) or template_narrative(
            forecast
        )

        self.memory.record("forecast", asdict(forecast))
        self.send("commander", "forecast", forecast=forecast, snapshot=snapshot)
