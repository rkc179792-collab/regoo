from triad.config import Config
from triad.toolkit import build_registry
from triad.tools import ToolRegistry


def test_view_limits_tools_and_shares_audit():
    registry = ToolRegistry()

    @registry.tool(description="a")
    def a() -> dict:
        return {"v": 1}

    @registry.tool(description="b")
    def b() -> dict:
        return {"v": 2}

    view = registry.view(["a"])
    assert view.call("a").ok
    assert not view.call("b").ok
    assert [entry["tool"] for entry in registry.audit] == ["a", "b"]


def test_mutating_tool_is_blocked_in_dry_run():
    registry = ToolRegistry()
    ran = []

    @registry.tool(description="writes", mutating=True)
    def write() -> dict:
        ran.append(1)
        return {}

    result = registry.view(["write"], dry_run=True).call("write")
    assert result.blocked and not ran
    assert registry.view(["write"], dry_run=False).call("write").ok and ran


def test_schema_marks_required_arguments():
    registry = ToolRegistry()

    @registry.tool(description="x")
    def f(path: str, days: int = 14) -> dict:
        return {}

    schema = registry.schemas()[0]["input_schema"]
    assert schema["required"] == ["path"]
    assert schema["properties"]["days"]["type"] == "integer"


def test_write_report_cannot_escape_state_dir(tmp_path):
    config = Config(workdir=tmp_path)
    result = build_registry(config).call("write_report", filename="../../evil.md", content="x")
    assert result.ok
    assert (config.state_dir / "evil.md").exists()
    assert not (tmp_path.parent / "evil.md").exists()
