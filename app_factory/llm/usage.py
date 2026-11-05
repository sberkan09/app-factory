"""Token kullanımı ve maliyet takibi (ARCHITECTURE.md §4.1 "maliyet kontrolü").

LLM sağlayıcısı her çağrıdan sonra `record_usage` çağırır. Graf node'ları
`collect_usage()` bağlamında çalıştırılır; toplanan kayıtlar state'teki
`llm_calls` listesine eklenir. Böylece run başına hangi ajanın hangi modelle
ne kadar token harcadığı panelde görülebilir.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

# USD / 1M token: (input, output). Önbellek okuma ~0.1x, yazma ~1.25x input.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

_current: ContextVar[list[dict] | None] = ContextVar("af_llm_usage", default=None)


@contextmanager
def collect_usage() -> Iterator[list[dict]]:
    calls: list[dict] = []
    token = _current.set(calls)
    try:
        yield calls
    finally:
        _current.reset(token)


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  cache_read: int = 0, cache_write: int = 0) -> float | None:
    price = MODEL_PRICES.get(model)
    if price is None:
        return None
    p_in, p_out = price
    return (
        input_tokens * p_in
        + cache_read * p_in * 0.1
        + cache_write * p_in * 1.25
        + output_tokens * p_out
    ) / 1_000_000


def record_usage(*, model: str, input_tokens: int, output_tokens: int,
                 cache_read: int = 0, cache_write: int = 0, agent: str = "") -> None:
    calls = _current.get()
    if calls is None:
        return  # takip bağlamı dışında (ör. doğrudan ajan çağrısı)
    calls.append({
        "model": model,
        "agent": agent,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cost_usd": estimate_cost(model, input_tokens, output_tokens, cache_read, cache_write),
    })


def summarize_usage(calls: list[dict]) -> dict:
    """Panel için özet: toplam + model bazında token/maliyet."""
    by_model: dict[str, dict] = {}
    total_cost = 0.0
    cost_known = True
    for c in calls:
        m = by_model.setdefault(c["model"], {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["input_tokens"] += c.get("input_tokens", 0) + c.get("cache_read_tokens", 0) + c.get("cache_write_tokens", 0)
        m["output_tokens"] += c.get("output_tokens", 0)
        if c.get("cost_usd") is None:
            cost_known = False
        else:
            m["cost_usd"] += c["cost_usd"]
            total_cost += c["cost_usd"]
    return {
        "calls": len(calls),
        "input_tokens": sum(m["input_tokens"] for m in by_model.values()),
        "output_tokens": sum(m["output_tokens"] for m in by_model.values()),
        "cost_usd": round(total_cost, 4),
        "cost_complete": cost_known,
        "by_model": by_model,
    }
