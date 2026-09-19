"""Tool registry shared by all agents.

There is one registry. Each agent receives a restricted `view` of it, so the
tools are shared but the permissions are not. Mutating tools are refused in
dry-run mode, and every call lands in one audit log.
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

log = logging.getLogger(__name__)

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., dict[str, Any]]
    mutating: bool
    input_schema: dict[str, Any]


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    blocked: bool = False


def _input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    hints = get_type_hints(fn)
    hints.pop("return", None)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in inspect.signature(fn).parameters.values():
        properties[param.name] = {"type": _JSON_TYPES.get(hints.get(param.name, str), "string")}
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
    return {"type": "object", "properties": properties, "required": required}


class ToolRegistry:
    def __init__(
        self,
        *,
        dry_run: bool = False,
        _tools: dict[str, Tool] | None = None,
        _audit: list[dict[str, Any]] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = _tools if _tools is not None else {}
        self.audit: list[dict[str, Any]] = _audit if _audit is not None else []
        self.dry_run = dry_run

    def tool(
        self, *, description: str, mutating: bool = False, name: str | None = None
    ) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
        def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            tool_name = name or fn.__name__
            self._tools[tool_name] = Tool(tool_name, description, fn, mutating, _input_schema(fn))
            return fn

        return decorator

    def view(self, allow: Iterable[str], *, dry_run: bool | None = None) -> ToolRegistry:
        """Return a registry limited to `allow`. It shares tools and the audit log."""
        subset = {name: self._tools[name] for name in allow}
        return ToolRegistry(
            dry_run=self.dry_run if dry_run is None else dry_run,
            _tools=subset,
            _audit=self.audit,
        )

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        """Tool definitions in the shape the Anthropic Messages API expects."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(name)
        started = time.perf_counter()
        if tool is None:
            result = ToolResult(False, error=f"tool '{name}' is not available to this agent")
        elif tool.mutating and self.dry_run:
            result = ToolResult(False, error="blocked: dry-run mode", blocked=True)
        else:
            try:
                result = ToolResult(True, data=tool.fn(**kwargs))
            except Exception as exc:  # a tool failure must not crash an agent
                log.debug("tool %s failed", name, exc_info=True)
                result = ToolResult(False, error=f"{type(exc).__name__}: {exc}")
        self.audit.append(
            {
                "tool": name,
                "args": kwargs,
                "ok": result.ok,
                "blocked": result.blocked,
                "seconds": round(time.perf_counter() - started, 3),
            }
        )
        return result
