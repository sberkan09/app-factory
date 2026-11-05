"""AnthropicLLM: streaming eşiği, kullanım kaydı ve hata durumları (sahte SDK istemcisiyle)."""

from types import SimpleNamespace

import pytest

from app_factory.llm import AnthropicLLM, LLMOutputError, LLMRefusalError, collect_usage
from app_factory.schemas.contracts import ErrorAnalysis

PARSED = ErrorAnalysis(root_cause="x", fix_strategy="y")


def response(stop_reason="end_turn", parsed=PARSED, text=None):
    usage = SimpleNamespace(input_tokens=1200, output_tokens=300,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    if text is None:
        text = parsed.model_dump_json() if parsed is not None else ""
    content = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage,
                           content=content)


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
    # SDK erken parse etmesin diye şema output_config ile gider
    assert "output_format" not in kwargs
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_streamed_output_is_parsed_after_stop_reason_check():
    assert call(FakeClient(response()), max_tokens=64000) == PARSED


def test_streamed_truncation_raises_output_error_and_records_usage():
    truncated = response(stop_reason="max_tokens", parsed=None, text='{"root_cause": "x", "fix_')
    with collect_usage() as calls, pytest.raises(LLMOutputError, match="truncated"):
        call(FakeClient(truncated), max_tokens=64000)
    assert calls and calls[0]["output_tokens"] == 300


def test_streamed_invalid_json_raises_output_error():
    bad = response(stop_reason="end_turn", parsed=None, text='{"root_cause": 1}')
    with pytest.raises(LLMOutputError, match="parse failed"):
        call(FakeClient(bad), max_tokens=64000)


def test_refusal_and_truncation_raise():
    with pytest.raises(LLMRefusalError):
        call(FakeClient(response(stop_reason="refusal", parsed=None)))
    with pytest.raises(LLMOutputError):
        call(FakeClient(response(stop_reason="max_tokens", parsed=None)))
