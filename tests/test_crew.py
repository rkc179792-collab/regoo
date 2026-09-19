from conftest import needs_git, needs_ruff
from triad import Config, Crew

PASSING = {
    "test_ok.py": "def test_ok():\n    assert True\n",
    "pyproject.toml": "[project]\nname='x'\n",
}
FAILING = {
    "test_bad.py": "def test_bad():\n    value = 1\n    assert value == 2\n",
    "pyproject.toml": "[project]\nname='x'\n",
}
UNUSED_IMPORT = {**PASSING, "app.py": "import os\n\n\ndef f():\n    return 1\n"}


def _crew(repo, **kw):
    return Crew(Config(workdir=repo, check_deps=False, **kw))


@needs_git
def test_healthy_repo_is_go(make_repo):
    verdict = _crew(make_repo(PASSING)).run()
    assert verdict.decision == "GO"
    assert verdict.rounds == 1


@needs_git
def test_failing_tests_hold_and_are_never_auto_fixed(make_repo):
    crew = _crew(make_repo(FAILING), apply=True)
    verdict = crew.run()
    assert verdict.decision == "HOLD"
    assert verdict.executed == []
    assert any("Tests are failing" in b for b in verdict.blockers)


@needs_git
def test_agents_talk_only_through_the_bus_in_order(make_repo):
    crew = _crew(make_repo(PASSING))
    crew.run()
    topics = [(m.sender, m.recipient, m.topic) for m in crew.bus.history]
    assert topics == [
        ("user", "commander", "goal"),
        ("commander", "tracker", "observe"),
        ("tracker", "predictor", "snapshot"),
        ("predictor", "commander", "forecast"),
    ]


@needs_git
def test_tracker_cannot_call_commander_tools(make_repo):
    crew = _crew(make_repo(PASSING))
    assert not crew.tracker.tools.call("lint_fix").ok


@needs_git
@needs_ruff
def test_dry_run_plans_but_does_not_touch_files(make_repo):
    repo = make_repo(UNUSED_IMPORT)
    verdict = _crew(repo).run()
    assert (repo / "app.py").read_text().startswith("import os")
    assert [p["tool"] for p in verdict.planned] == ["lint_fix"]
    assert verdict.planned[0]["blocked"] is True


@needs_git
@needs_ruff
def test_apply_fixes_lint_then_reobserves(make_repo):
    repo = make_repo(UNUSED_IMPORT)
    crew = _crew(repo, apply=True)
    verdict = crew.run()
    assert not (repo / "app.py").read_text().startswith("import os")
    assert verdict.rounds == 2
    assert [e["tool"] for e in verdict.executed] == ["lint_fix"]
    assert verdict.decision == "GO"
    assert [m.topic for m in crew.bus.history].count("observe") == 2
