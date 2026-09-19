import sys
import types

import pytest

from triad.config import Config
from triad.llm import AnthropicLLM, OfflineLLM, build_llm


def _fake_anthropic(monkeypatch, *, fail=False):
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if fail:
                raise RuntimeError("network down")
            block = types.SimpleNamespace(type="text", text="  two sentences.  ")
            return types.SimpleNamespace(content=[block])

    class Client:
        def __init__(self, api_key=None):
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    return calls


def test_offline_backend_returns_empty_text():
    assert OfflineLLM().complete("s", "p") == ""
    assert isinstance(build_llm(Config()), OfflineLLM)


def test_anthropic_backend_sends_system_prompt_and_strips_text(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    llm = AnthropicLLM("some-model", api_key="k")
    assert llm.complete("be brief", "facts") == "two sentences."
    assert calls[0]["system"] == "be brief"
    assert calls[0]["model"] == "some-model"


def test_anthropic_failure_degrades_to_empty_text(monkeypatch):
    _fake_anthropic(monkeypatch, fail=True)
    assert AnthropicLLM("m", api_key="k").complete("s", "p") == ""


def test_missing_sdk_gives_an_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(RuntimeError, match="triad\\[anthropic\\]"):
        AnthropicLLM("m")
