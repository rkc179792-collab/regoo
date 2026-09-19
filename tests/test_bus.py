import pytest

from triad.agents.base import Agent
from triad.bus import MessageBus
from triad.config import Config
from triad.llm import OfflineLLM
from triad.memory import Memory
from triad.models import Message
from triad.tools import ToolRegistry


class Echo(Agent):
    name = "echo"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seen = []

    def on_ping(self, message):
        self.seen.append(message.payload["n"])


class Loop(Agent):
    name = "loop"

    def on_ping(self, message):
        self.send("loop", "ping", n=0)


def _agent(cls, bus, tmp_path):
    return cls(
        bus=bus, tools=ToolRegistry(), memory=Memory(tmp_path / "h.jsonl"),
        llm=OfflineLLM(), config=Config(workdir=tmp_path),
    )  # fmt: skip


def test_routes_by_recipient_and_topic(tmp_path):
    bus = MessageBus()
    echo = _agent(Echo, bus, tmp_path)
    bus.send(Message("x", "echo", "ping", {"n": 7}))
    assert bus.run_until_idle() == 1
    assert echo.seen == [7]


def test_unknown_recipient_fails_fast(tmp_path):
    bus = MessageBus()
    _agent(Echo, bus, tmp_path)
    with pytest.raises(KeyError):
        bus.send(Message("x", "nobody", "ping"))


def test_message_loop_is_bounded(tmp_path):
    bus = MessageBus(max_steps=5)
    _agent(Loop, bus, tmp_path)
    bus.send(Message("x", "loop", "ping"))
    with pytest.raises(RuntimeError):
        bus.run_until_idle()
