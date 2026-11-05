"""Anthropic API katmanı.

Tüm ajanlar bu tek arayüz üzerinden model çağırır; testlerde FakeLLM ile
değiştirilir. Structured output için `messages.parse` / `messages.stream` +
Pydantic `output_format` kullanılır (şema doğrulama SDK katmanında yapılır).
Her çağrının token kullanımı `record_usage` ile run'a yazılır.
"""

from __future__ import annotations

import base64
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app_factory.llm.usage import record_usage

T = TypeVar("T", bound=BaseModel)

# Bu değerin üzerindeki max_tokens isteklerinde HTTP timeout'a takılmamak için
# streaming kullanılır (SDK büyük non-streaming istekleri reddeder).
STREAMING_THRESHOLD = 16000


class LLMRefusalError(RuntimeError):
    """Model güvenlik nedeniyle isteği reddetti (stop_reason: refusal)."""


class LLMOutputError(RuntimeError):
    """Model çıktısı şemaya uymadı veya max_tokens'ta kesildi."""


class LLMProvider(Protocol):
    def structured(
        self,
        *,
        model: str,
        output_model: type[T],
        system: str,
        prompt: str,
        images: list[bytes] | None = None,
        max_tokens: int = 16000,
    ) -> T: ...


def _image_media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class AnthropicLLM:
    def __init__(self, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client

    def structured(
        self,
        *,
        model: str,
        output_model: type[T],
        system: str,
        prompt: str,
        images: list[bytes] | None = None,
        max_tokens: int = 16000,
    ) -> T:
        content: list[dict] = []
        for img in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _image_media_type(img),
                        "data": base64.standard_b64encode(img).decode("utf-8"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_format": output_model,
        }
        # Fable ailesinde thinking her zaman açık; parametre omit edilir.
        # Diğer güncel modellerde adaptive thinking'i açıkça istiyoruz.
        if not model.startswith("claude-fable"):
            kwargs["thinking"] = {"type": "adaptive"}

        if max_tokens > STREAMING_THRESHOLD:
            # Coder gibi uzun çıktılı çağrılar: streaming + nihai mesaj
            with self._client.messages.stream(**kwargs) as stream:
                response = stream.get_final_message()
        else:
            response = self._client.messages.parse(**kwargs)

        usage = getattr(response, "usage", None)
        if usage is not None:
            record_usage(
                model=model,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )

        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"Model refused the request (model={model})")
        if response.stop_reason == "max_tokens":
            raise LLMOutputError(
                f"Output truncated at max_tokens={max_tokens} (model={model}); "
                "çıktı şemaya uygun tamamlanamadı"
            )
        if response.parsed_output is None:
            raise LLMOutputError(f"Structured output parse failed (model={model})")
        return response.parsed_output
