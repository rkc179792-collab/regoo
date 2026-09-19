from __future__ import annotations

import logging
from typing import Any, ClassVar

from triad.bus import MessageBus
from triad.config import Config
from triad.llm import LLM
from triad.memory import Memory
from triad.models import Message
from triad.tools import ToolRegistry


class Agent:
    """Base class. Subclasses define `name` and one `on_<topic>` method per topic they accept."""

    name: ClassVar[str]

    def __init__(
        self,
        *,
        bus: MessageBus,
        tools: ToolRegistry,
        memory: Memory,
        llm: LLM,
        config: Config,
    ) -> None:
        self.bus = bus
        self.tools = tools
        self.memory = memory
        self.llm = llm
        self.config = config
        self.log = logging.getLogger(f"triad.{self.name}")
        bus.register(self)

    def send(self, recipient: str, topic: str, **payload: Any) -> None:
        self.bus.send(Message(self.name, recipient, topic, payload))

    def handle(self, message: Message) -> None:
        handler = getattr(self, f"on_{message.topic}", None)
        if handler is None:
            self.log.warning("no handler for topic %r from %s", message.topic, message.sender)
            return
        self.log.debug("received %s from %s", message.topic, message.sender)
        handler(message)
