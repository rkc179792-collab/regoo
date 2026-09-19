"""Language-model backends.

The agents decide with deterministic rules. The model only writes the two prose
fields (the Predictor's narrative and the Commander's summary), so a missing key
or a network failure degrades to templated text instead of stopping a release gate.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from triad.config import Config

log = logging.getLogger(__name__)


class LLM(Protocol):
    def complete(self, system: str, prompt: str, max_tokens: int = 300) -> str:
        """Return generated text, or an empty string if nothing could be generated."""
        ...


class OfflineLLM:
    def complete(self, system: str, prompt: str, max_tokens: int = 300) -> str:
        return ""


class AnthropicLLM:
    def __init__(self, model: str, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("install the extra first: pip install 'triad[anthropic]'") from exc
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    def complete(self, system: str, prompt: str, max_tokens: int = 300) -> str:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning("LLM call failed, using templated text: %s", exc)
            return ""
        return "".join(b.text for b in response.content if b.type == "text").strip()


def build_llm(config: Config) -> LLM:
    if config.llm == "anthropic":
        return AnthropicLLM(config.model)
    return OfflineLLM()
