"""AnthropicLLM: streaming eşiği, kullanım kaydı ve hata durumları (sahte SDK istemcisiyle)."""

from types import SimpleNamespace

import pytest

from app_factory.llm import AnthropicLLM, LLMOutputError, LLMRefusalError, collect_usage
from app_factory.schemas.contracts import ErrorAnalysis

PARSED = ErrorAnalysis(root_cause="x", fix_strategy="y")


def response(stop_reason="end_turn", parsed=PARSED):
    usage = SimpleNamespace(input_tokens=1200, output_tokens=300,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage)


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(("parse", kwargs))
        return self.resp

    def stream(self, **kwargs):
        self.calls.append(("stream", kwargs))
        resp = self.resp

        class Ctx:
            def __enter__(self_inner):
                return SimpleNamespace(get_final_message=lambda: resp)

            def __exit__(self_inner, *a):
                return False

        return Ctx()


def call(client, model="claude-sonnet-5-5", max_tokens=8000):
    return AnthropicLLM(client).structured(
        model=model, output_model=ErrorAnalysis, system="s", prompt="p", max_tokens=max_tokens)


def test_small_requests_use_parse_and_record_usage():
    client = FakeClient(response())
    with collect_usage() as calls:
        assert call(client) == PARSED
    kind, kwargs = client.calls[0]
    assert kind == "parse"
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert calls[0]["input_tokens"] == 1200 and calls[0]["cost_usd"] > 0


def test_large_requests_stream_and_fable_omits_thinking():
    client = FakeClient(response())
    call(client, model="claude-fable-5-1", max_tokens=64000)
    kind, kwargs = client.calls[0]
    assert kind == "stream"
    assert "thinking" not in kwargs


def test_refusal_and_truncation_raise():
    with pytest.raises(LLMRefusalError):
        call(FakeClient(response(stop_reason="refusal", parsed=None)))
    with pytest.raises(LLMOutputError):
        call(FakeClient(response(stop_reason="max_tokens", parsed=None)))
