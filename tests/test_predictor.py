import time

from triad.agents.predictor import compute_forecast
from triad.models import Check, Snapshot


def _snapshot(tests="pass", lint="pass", churn=None, deps=None):
    checks = {"tests": Check("tests", tests), "lint": Check("lint", lint)}
    if deps is not None:
        checks["deps"] = Check("deps", "warn", metrics={"outdated": deps})
    return Snapshot(1, time.time(), ["python"], checks, churn or [])


def _score(snapshot, **kw):
    kw.setdefault("todo_by_file", {})
    kw.setdefault("baseline_commits", {})
    kw.setdefault("prev_base_risk", None)
    return compute_forecast(snapshot, **kw)


def test_clean_repo_scores_zero():
    assert _score(_snapshot()).risk == 0.0


def test_failing_tests_dominate():
    forecast = _score(_snapshot(tests="fail"))
    assert forecast.risk >= 0.4
    assert max(forecast.drivers, key=lambda d: d.contribution).name == "tests"


def test_hotspot_needs_three_commits_and_reports_todos():
    churn = [{"path": "api.py", "commits": 6}, {"path": "ui.js", "commits": 2}]
    forecast = _score(_snapshot(churn=churn), todo_by_file={"api.py": 2})
    assert [h["path"] for h in forecast.hotspots] == ["api.py"]
    assert forecast.hotspots[0]["todos"] == 2


def test_trend_rises_only_when_base_risk_worsens():
    worse = _score(_snapshot(tests="fail"), prev_base_risk=0.0)
    same = _score(_snapshot(tests="fail"), prev_base_risk=worse.base_risk)
    assert worse.risk > worse.base_risk
    assert same.risk == same.base_risk


def test_risk_is_clipped_to_one():
    churn = [{"path": f"f{i}.py", "commits": 50} for i in range(3)]
    forecast = _score(
        _snapshot(tests="fail", lint="fail", churn=churn, deps=99), prev_base_risk=0.0
    )
    assert forecast.risk <= 1.0
