"""A synchronous, in-process message bus.

Agents never call each other. They send a Message to a name (or to "*") and the
bus delivers it to the `on_<topic>` method of the recipient. Every delivery is
kept in `history`, which is the audit trail of who told whom what.
"""

from __future__ import annotations

import dataclasses
from collections import deque
from typing import TYPE_CHECKING

from triad.models import Message

if TYPE_CHECKING:
    from triad.agents.base import Agent

BROADCAST = "*"


class MessageBus:
    def __init__(self, max_steps: int = 200) -> None:
        self._agents: dict[str, Agent] = {}
        self._queue: deque[Message] = deque()
        self.history: list[Message] = []
        self.max_steps = max_steps

    def register(self, agent: Agent) -> None:
        if agent.name in self._agents:
            raise ValueError(f"agent already registered: {agent.name}")
        self._agents[agent.name] = agent

    def send(self, message: Message) -> None:
        if message.recipient == BROADCAST:
            for name in self._agents:
                if name != message.sender:
                    self._queue.append(dataclasses.replace(message, recipient=name))
            return
        if message.recipient not in self._agents:
            raise KeyError(f"unknown recipient: {message.recipient}")
        self._queue.append(message)

    def run_until_idle(self) -> int:
        """Deliver queued messages until none are left. Returns the delivery count."""
        steps = 0
        while self._queue:
            if steps >= self.max_steps:
                raise RuntimeError(f"message loop exceeded {self.max_steps} deliveries")
            message = self._queue.popleft()
            self.history.append(message)
            self._agents[message.recipient].handle(message)
            steps += 1
        return steps

    def trace(self) -> list[str]:
        return [
            f"{m.sender:>10} -> {m.recipient:<10} {m.topic:<9} [{', '.join(sorted(m.payload))}]"
            for m in self.history
        ]
