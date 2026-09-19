from __future__ import annotations

import json
import time
from typing import Any

from triad.agents.base import Agent
from triad.models import Action, Forecast, Message, Snapshot, Verdict

SUMMARY_PROMPT = (
    "You are the release commander. Write two or three plain sentences that state the "
    "decision and the reason. Use only the facts given. Do not invent numbers."
)


class Commander(Agent):
    """Owns the goal. Decides GO or HOLD, runs the safe fixes, and asks the Tracker to re-check.

    The decision policy is rule based so it is auditable. The Commander is the only agent
    holding mutating tools, and those are blocked unless the run was started with apply=True.
    """

    name = "commander"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.verdict: Verdict | None = None
        self._executed: list[dict[str, Any]] = []
        self._tried: set[str] = set()

    def on_goal(self, message: Message) -> None:
        self.send("tracker", "observe", round=1)

    def on_forecast(self, message: Message) -> None:
        forecast: Forecast = message.payload["forecast"]
        snapshot: Snapshot = message.payload["snapshot"]
        autofix, blockers, advisories = self._plan(snapshot)

        if autofix and self.config.apply and snapshot.round < self.config.max_rounds:
            ran_ok = False
            for action in autofix:
                self._tried.add(action.tool)
                result = self.tools.call(action.tool, **action.args)
                ran_ok = ran_ok or result.ok
                self._executed.append(
                    {
                        "round": snapshot.round,
                        "tool": action.tool,
                        "reason": action.reason,
                        "ok": result.ok,
                        "detail": result.data.get("detail", "") if result.ok else result.error,
                    }
                )
            if ran_ok:
                self.send("tracker", "observe", round=snapshot.round + 1)
                return
        self._finish(forecast, snapshot, autofix, blockers, advisories)

    # ---- policy --------------------------------------------------------------------------

    def _plan(self, snapshot: Snapshot) -> tuple[list[Action], list[str], list[str]]:
        autofix: list[Action] = []
        blockers: list[str] = []
        advisories: list[str] = []
        tests = snapshot.checks.get("tests")
        lint = snapshot.checks.get("lint")
        deps = snapshot.checks.get("deps")

        if tests is not None and tests.status == "fail":
            blockers.append(f"Tests are failing ({tests.detail}). A human has to fix these.")
        elif tests is None or tests.status == "skipped":
            advisories.append("No test runner was detected, so nothing verifies behavior.")

        if lint is not None and lint.status == "fail":
            if "lint_fix" in self._tried:
                advisories.append(f"Lint issues remain after autofix ({lint.detail}).")
            else:
                autofix.append(
                    Action(
                        "lint_fix", {}, "Lint is failing and autofix is low risk.", mutating=True
                    )
                )
        if deps is not None and deps.status == "warn":
            advisories.append(f"Outdated dependencies: {deps.detail}.")
        return autofix, blockers, advisories

    # ---- closing -------------------------------------------------------------------------

    def _finish(
        self,
        forecast: Forecast,
        snapshot: Snapshot,
        autofix: list[Action],
        blockers: list[str],
        advisories: list[str],
    ) -> None:
        planned = [
            {"tool": a.tool, "reason": a.reason, "blocked": not self.config.apply} for a in autofix
        ]
        if forecast.risk >= self.config.risk_threshold:
            blockers.append(
                f"Risk {forecast.risk:.2f} is at or above the threshold "
                f"{self.config.risk_threshold:.2f}."
            )
        decision = "HOLD" if blockers else "GO"

        facts = {
            "decision": decision,
            "risk": forecast.risk,
            "rounds": snapshot.round,
            "blockers": blockers,
            "executed": self._executed,
            "planned_but_blocked": planned,
            "forecast": forecast.narrative,
        }
        summary = self.llm.complete(SUMMARY_PROMPT, json.dumps(facts, default=str))
        if not summary:
            summary = (
                f"{decision}: risk {forecast.risk:.2f} ({forecast.level}) after "
                f"{snapshot.round} round(s). {forecast.narrative}"
            )

        verdict = Verdict(
            decision=decision,  # type: ignore[arg-type]
            risk=forecast.risk,
            level=forecast.level,
            rounds=snapshot.round,
            executed=self._executed,
            planned=planned,
            blockers=blockers,
            advisories=advisories,
            summary=summary,
            report_path="",
        )
        report = render_report(verdict, forecast, snapshot)
        written = self.tools.call("write_report", filename="report.md", content=report)
        verdict.report_path = written.data.get("path", "") if written.ok else ""
        self.memory.record("verdict", verdict.to_dict())
        self.verdict = verdict


def render_report(verdict: Verdict, forecast: Forecast, snapshot: Snapshot) -> str:
    lines = [
        "# Release readiness report",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Decision: {verdict.decision}** (risk {verdict.risk:.2f}, {verdict.level}, "
        f"{verdict.rounds} round(s))",
        "",
        verdict.summary,
        "",
        "## Risk drivers",
        "",
        "| Driver | Weight | Severity | Contribution | Evidence |",
        "|---|---|---|---|---|",
    ]
    for d in forecast.drivers:
        cells = [
            d.name,
            f"{d.weight:.2f}",
            f"{d.severity:.2f}",
            f"{d.contribution:.3f}",
            d.evidence,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    if forecast.hotspots:
        lines += [
            "",
            "## Hotspots",
            "",
            "| File | Commits | TODO markers | Accelerating |",
            "|---|---|---|---|",
        ]
        for h in forecast.hotspots:
            accelerating = "yes" if h["accelerating"] else "no"
            lines.append(f"| {h['path']} | {h['commits']} | {h['todos']} | {accelerating} |")
    lines += ["", "## Signals", ""]
    for c in snapshot.checks.values():
        lines.append(f"- **{c.name}**: {c.status}. {c.detail}".rstrip())
    if verdict.executed:
        lines += ["", "## Actions taken", ""]
        lines += [
            f"- round {e['round']}: `{e['tool']}` ({'ok' if e['ok'] else 'failed'}). {e['detail']}"
            for e in verdict.executed
        ]
    if verdict.planned:
        lines += ["", "## Actions planned but not run", ""]
        lines += [
            f"- `{p['tool']}`: {p['reason']} "
            f"({'re-run with --apply' if p['blocked'] else 'max rounds reached'})"
            for p in verdict.planned
        ]
    if verdict.blockers:
        lines += ["", "## Blockers", ""] + [f"- {b}" for b in verdict.blockers]
    if verdict.advisories:
        lines += ["", "## Advisories", ""] + [f"- {a}" for a in verdict.advisories]
    failing = snapshot.checks.get("tests")
    if failing and failing.metrics.get("output_tail"):
        lines += ["", "## Test output (tail)", "", "```text", failing.metrics["output_tail"], "```"]
    return "\n".join(lines) + "\n"
