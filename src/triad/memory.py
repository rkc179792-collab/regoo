"""Append-only JSONL history shared by all agents and kept across runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Memory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, data: dict[str, Any]) -> None:
        line = json.dumps({"kind": kind, "ts": time.time(), "data": data}, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def last(self, kind: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("kind") == kind:
                return entry
        return None
