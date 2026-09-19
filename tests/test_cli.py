import json

from conftest import needs_git
from triad.cli import main

PASSING = {
    "test_ok.py": "def test_ok():\n    assert True\n",
    "pyproject.toml": "[project]\nname='x'\n",
}
FAILING = {
    "test_bad.py": "def test_bad():\n    value = 1\n    assert value == 2\n",
    "pyproject.toml": "[project]\nname='x'\n",
}


def test_bad_path_exits_2(capsys):
    assert main(["run", "/definitely/not/here"]) == 2
    assert "not a directory" in capsys.readouterr().err


@needs_git
def test_go_exits_0_and_json_is_parseable(make_repo, capsys):
    assert main(["run", str(make_repo(PASSING)), "--no-deps", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "GO"


@needs_git
def test_hold_exits_1(make_repo):
    assert main(["run", str(make_repo(FAILING)), "--no-deps"]) == 1
