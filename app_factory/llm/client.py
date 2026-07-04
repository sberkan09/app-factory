"""Anthropic API katmanı.

Tüm ajanlar bu tek arayüz üzerinden model çağırır; testlerde FakeLLM ile
değiştirilir. Structured output için `client.messages.parse` + Pydantic
kullanılır (şema doğrulama SDK katmanında yapılır).
"""

from __future__ import annotations

import base64
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMRefusalError(RuntimeError):
    """Model güvenlik nedeniyle isteği reddetti (stop_reason: refusal)."""


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
                        "media_type": "image/png",
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
        # Fable 5'te thinking parametresi tamamen omit edilmeli (her config 400
        # döner, adaptive hariç); diğer modellerde adaptive'i açıkça isteriz.
        if not model.startswith("claude-fable"):
            kwargs["thinking"] = {"type": "adaptive"}

        # Büyük max_tokens'ta SDK non-streaming isteği timeout korumasıyla
        # reddeder; timeout'u açıkça genişletiyoruz.
        response = self._client.with_options(timeout=600.0).messages.parse(**kwargs)

        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"Model refused the request (model={model})")
        if response.parsed_output is None:
            raise ValueError(f"Structured output parse failed (model={model})")
        return response.parsed_output
